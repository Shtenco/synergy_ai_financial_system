// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IERC20AccountingV6 {
    function balanceOf(address) external view returns (uint256);
    function totalSupply() external view returns (uint256);
    function decimals() external view returns (uint8);
}

interface IProtocolOwnedPoolAccountingV6 {
    function totalShares() external view returns (uint256);
    function shares(address) external view returns (uint256);
}

interface IPriceOracleAccountingV6 {
    function price1e18(address token) external view returns (uint256);
}

/// @notice Conservative multi-asset consolidated accounting for the V13-style graph.
///
/// Assets:
/// - real quote assets (USDT/USDC/DAI/WPOL/WETH/...) are valued through PriceOracleHub;
/// - each asset has an explicit haircut;
/// - only registered asset/account pairs are included.
///
/// Liabilities:
/// - USDx held by static protocol accounts is treasury inventory;
/// - USDx inside a registered managed pool is protocol inventory only while the
///   configured protocol liquidity owner owns 100% of live LP shares;
/// - every remaining USDx unit is treated as a $1 external liability.
contract SystemAccounting {
    struct AssetConfig {
        bool enabled;
        uint8 decimals;
        uint16 haircutBps;
    }

    address public owner;
    address public immutable oracle;
    address public immutable usdx;
    address public protocolLiquidityOwner;

    address[] public hardAssets;
    mapping(address => AssetConfig) public assetConfig;
    mapping(address => address[]) private hardAccountsByAsset;
    mapping(address => mapping(address => bool)) public isHardAccount;

    address[] public protocolUSDxAccounts;
    mapping(address => bool) public isProtocolUSDxAccount;
    mapping(address => bool) public isProtocolUSDxPoolAccount;

    event HardAssetAdded(address indexed token, uint8 decimals, uint16 haircutBps);
    event HardAssetHaircutSet(address indexed token, uint16 haircutBps);
    event HardAccountAdded(address indexed token, address indexed account);
    event ProtocolUSDxAccountAdded(address indexed account, bool poolAccount);
    event ProtocolLiquidityOwnerSet(address indexed owner);

    error Unauthorized();
    error BadConfig();

    constructor(address oracle_, address usdx_, address owner_) {
        if (oracle_ == address(0) || usdx_ == address(0) || owner_ == address(0)) revert BadConfig();
        oracle = oracle_;
        usdx = usdx_;
        owner = owner_;
        protocolLiquidityOwner = owner_;
    }

    modifier onlyOwner(){ if (msg.sender != owner) revert Unauthorized(); _; }

    function setProtocolLiquidityOwner(address account) external onlyOwner {
        if (account == address(0)) revert BadConfig();
        protocolLiquidityOwner = account;
        emit ProtocolLiquidityOwnerSet(account);
    }

    function addHardAsset(address token, uint16 haircutBps) external onlyOwner {
        if (
            token == address(0) || token == usdx || assetConfig[token].enabled ||
            haircutBps == 0 || haircutBps > 10_000 || hardAssets.length >= 16
        ) revert BadConfig();
        uint8 d = IERC20AccountingV6(token).decimals();
        if (d > 36) revert BadConfig();
        assetConfig[token] = AssetConfig(true, d, haircutBps);
        hardAssets.push(token);
        emit HardAssetAdded(token, d, haircutBps);
    }

    function setHardAssetHaircut(address token, uint16 haircutBps) external onlyOwner {
        if (!assetConfig[token].enabled || haircutBps == 0 || haircutBps > 10_000) revert BadConfig();
        assetConfig[token].haircutBps = haircutBps;
        emit HardAssetHaircutSet(token, haircutBps);
    }

    function addHardAccount(address token, address account) external onlyOwner {
        if (
            !assetConfig[token].enabled || account == address(0) || isHardAccount[token][account] ||
            hardAccountsByAsset[token].length >= 64
        ) revert BadConfig();
        isHardAccount[token][account] = true;
        hardAccountsByAsset[token].push(account);
        emit HardAccountAdded(token, account);
    }

    function addProtocolUSDxAccount(address account) external onlyOwner {
        _addProtocolUSDxAccount(account, false);
    }

    function addProtocolUSDxPoolAccount(address account) external onlyOwner {
        _addProtocolUSDxAccount(account, true);
    }

    function _addProtocolUSDxAccount(address account, bool poolAccount) internal {
        if (
            account == address(0) || isProtocolUSDxAccount[account] ||
            protocolUSDxAccounts.length >= 64
        ) revert BadConfig();
        isProtocolUSDxAccount[account] = true;
        isProtocolUSDxPoolAccount[account] = poolAccount;
        protocolUSDxAccounts.push(account);
        emit ProtocolUSDxAccountAdded(account, poolAccount);
    }

    /// @notice Haircut USD value of all registered real assets and accounts.
    function hardAssets1e18() public view returns (uint256 total) {
        IPriceOracleAccountingV6 prices = IPriceOracleAccountingV6(oracle);
        for (uint256 i = 0; i < hardAssets.length; ++i) {
            address token = hardAssets[i];
            AssetConfig memory cfg = assetConfig[token];
            uint256 price = prices.price1e18(token);
            uint256 scale = 10 ** uint256(cfg.decimals);
            address[] storage accounts = hardAccountsByAsset[token];
            uint256 tokenBalance;
            for (uint256 j = 0; j < accounts.length; ++j) {
                tokenBalance += IERC20AccountingV6(token).balanceOf(accounts[j]);
            }
            uint256 grossUsd1e18 = (tokenBalance * price) / scale;
            total += (grossUsd1e18 * uint256(cfg.haircutBps)) / 10_000;
        }
    }

    function isLiveProtocolOwnedPool(address account) public view returns (bool) {
        if (!isProtocolUSDxPoolAccount[account]) return false;
        uint256 total = IProtocolOwnedPoolAccountingV6(account).totalShares();
        return total != 0 && IProtocolOwnedPoolAccountingV6(account).shares(protocolLiquidityOwner) == total;
    }

    function protocolHeldUSDx() public view returns (uint256 held) {
        for (uint256 i = 0; i < protocolUSDxAccounts.length; ++i) {
            address account = protocolUSDxAccounts[i];
            if (isProtocolUSDxPoolAccount[account] && !isLiveProtocolOwnedPool(account)) continue;
            held += IERC20AccountingV6(usdx).balanceOf(account);
        }
        uint256 supply = IERC20AccountingV6(usdx).totalSupply();
        return held > supply ? supply : held;
    }

    function externalUSDxLiability1e18() public view returns (uint256) {
        uint256 supply = IERC20AccountingV6(usdx).totalSupply();
        uint256 held = protocolHeldUSDx();
        return supply - held;
    }

    function externalCoverageBps() public view returns (uint256) {
        uint256 liability = externalUSDxLiability1e18();
        if (liability == 0) return type(uint256).max;
        return (hardAssets1e18() * 10_000) / liability;
    }

    function consolidatedHardNAV1e18() public view returns (int256) {
        return int256(hardAssets1e18()) - int256(externalUSDxLiability1e18());
    }

    function hardAssetCount() external view returns (uint256) {
        return hardAssets.length;
    }

    function hardAccountCount(address token) external view returns (uint256) {
        return hardAccountsByAsset[token].length;
    }

    function protocolUSDxAccountCount() external view returns (uint256) {
        return protocolUSDxAccounts.length;
    }
}
