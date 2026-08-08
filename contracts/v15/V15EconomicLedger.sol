// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IERC20V15Ledger {
    function balanceOf(address) external view returns (uint256);
    function decimals() external view returns (uint8);
}

interface IV15CanonicalOracle {
    function price1e18(address token) external view returns (uint256);
}

interface IV15LiabilitiesCanonical {
    function totalCanonicalLiabilities1e18() external view returns (uint256);
}

/// @notice Canonical economic ledger. No haircut and no own-synthetic markups.
contract V15EconomicLedger {
    struct AssetConfig { bool enabled; uint8 decimals; }

    uint256 public constant MAX_ASSETS = 16;
    uint256 public constant MAX_ACCOUNTS_PER_ASSET = 64;

    address public owner;
    address public immutable oracle;
    address public immutable liabilityRegistry;

    address[] private assets;
    mapping(address => AssetConfig) public assetConfig;
    mapping(address => address[]) private accountsByAsset;
    mapping(address => mapping(address => bool)) public isHardAccount;
    mapping(address => mapping(address => bool)) private everHardAccount;
    mapping(address => bool) public permanentlyExcludedAsset;

    event AssetPermanentlyExcluded(address indexed token);
    event HardAssetAdded(address indexed token, uint8 decimals);
    event HardAccountSet(address indexed token, address indexed account, bool enabled);

    error Unauthorized();
    error BadConfig();

    constructor(address owner_, address oracle_, address liabilityRegistry_) {
        if (owner_ == address(0) || oracle_ == address(0) || liabilityRegistry_ == address(0)) revert BadConfig();
        owner = owner_;
        oracle = oracle_;
        liabilityRegistry = liabilityRegistry_;
    }

    modifier onlyOwner() { if (msg.sender != owner) revert Unauthorized(); _; }

    /// @dev One-way switch. Use for SYNA/SYNR/USDx and every own synthetic.
    function permanentlyExcludeAsset(address token) external onlyOwner {
        if (token == address(0) || assetConfig[token].enabled) revert BadConfig();
        permanentlyExcludedAsset[token] = true;
        emit AssetPermanentlyExcluded(token);
    }

    function addHardAsset(address token) external onlyOwner {
        if (
            token == address(0) || permanentlyExcludedAsset[token] || assetConfig[token].enabled ||
            assets.length >= MAX_ASSETS
        ) revert BadConfig();
        uint8 d = IERC20V15Ledger(token).decimals();
        if (d > 36) revert BadConfig();
        assetConfig[token] = AssetConfig(true, d);
        assets.push(token);
        emit HardAssetAdded(token, d);
    }

    function setHardAccount(address token, address account, bool enabled) external onlyOwner {
        if (!assetConfig[token].enabled || account == address(0)) revert BadConfig();
        bool old = isHardAccount[token][account];
        if (old == enabled) revert BadConfig();
        isHardAccount[token][account] = enabled;
        if (enabled && !everHardAccount[token][account]) {
            if (accountsByAsset[token].length >= MAX_ACCOUNTS_PER_ASSET) revert BadConfig();
            everHardAccount[token][account] = true;
            accountsByAsset[token].push(account);
        }
        emit HardAccountSet(token, account, enabled);
    }

    function assetBalance(address token) public view returns (uint256 total) {
        if (!assetConfig[token].enabled) revert BadConfig();
        address[] storage a = accountsByAsset[token];
        for (uint256 i; i < a.length; ++i) {
            if (isHardAccount[token][a[i]]) total += IERC20V15Ledger(token).balanceOf(a[i]);
        }
    }

    function markValue1e18(address token, uint256 amount) public view returns (uint256) {
        AssetConfig memory c = assetConfig[token];
        if (!c.enabled) revert BadConfig();
        uint256 p = IV15CanonicalOracle(oracle).price1e18(token);
        return (amount * p) / (10 ** uint256(c.decimals));
    }

    function hardAssets1e18() public view returns (uint256 total) {
        for (uint256 i; i < assets.length; ++i) {
            address token = assets[i];
            total += markValue1e18(token, assetBalance(token));
        }
    }

    function canonicalLiabilities1e18() public view returns (uint256) {
        return IV15LiabilitiesCanonical(liabilityRegistry).totalCanonicalLiabilities1e18();
    }

    function hardNAV1e18() public view returns (int256) {
        uint256 a = hardAssets1e18();
        uint256 l = canonicalLiabilities1e18();
        if (a > uint256(type(int256).max) || l > uint256(type(int256).max)) revert BadConfig();
        return int256(a) - int256(l);
    }

    function isHardAsset(address token) external view returns (bool) { return assetConfig[token].enabled; }
    function assetCount() external view returns (uint256) { return assets.length; }
    function assetAt(uint256 index) external view returns (address) { return assets[index]; }
    function assetDecimals(address token) external view returns (uint8) { return assetConfig[token].decimals; }
    function hardAccountCount(address token) external view returns (uint256) { return accountsByAsset[token].length; }
}
