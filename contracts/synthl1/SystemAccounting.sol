// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IERC20AccountingV5 {
    function balanceOf(address) external view returns (uint256);
    function totalSupply() external view returns (uint256);
    function decimals() external view returns (uint8);
}

/// @notice Conservative balance-sheet view for the recursive engine.
/// `protocolUSDxAccount` may include a GraphPool only when that pool is 100% protocol-owned.
contract SystemAccounting {
    address public owner;
    address public immutable hardToken;
    address public immutable usdx;
    uint8 public immutable hardDecimals;

    address[] public hardAccounts;
    mapping(address => bool) public isHardAccount;

    address[] public protocolUSDxAccounts;
    mapping(address => bool) public isProtocolUSDxAccount;

    event HardAccountAdded(address indexed account);
    event ProtocolUSDxAccountAdded(address indexed account);

    error Unauthorized();
    error BadConfig();

    constructor(address hardToken_, address usdx_, address owner_) {
        if (hardToken_ == address(0) || usdx_ == address(0) || owner_ == address(0)) revert BadConfig();
        hardToken = hardToken_;
        usdx = usdx_;
        hardDecimals = IERC20AccountingV5(hardToken_).decimals();
        if (hardDecimals > 18) revert BadConfig();
        owner = owner_;
    }

    modifier onlyOwner(){ if (msg.sender != owner) revert Unauthorized(); _; }

    function addHardAccount(address account) external onlyOwner {
        if (account == address(0) || isHardAccount[account] || hardAccounts.length >= 32) revert BadConfig();
        isHardAccount[account] = true;
        hardAccounts.push(account);
        emit HardAccountAdded(account);
    }

    function addProtocolUSDxAccount(address account) external onlyOwner {
        if (account == address(0) || isProtocolUSDxAccount[account] || protocolUSDxAccounts.length >= 64) revert BadConfig();
        isProtocolUSDxAccount[account] = true;
        protocolUSDxAccounts.push(account);
        emit ProtocolUSDxAccountAdded(account);
    }

    function hardAssets1e18() public view returns (uint256 total) {
        uint256 scale = 10 ** (18 - hardDecimals);
        for (uint256 i = 0; i < hardAccounts.length; ++i) {
            total += IERC20AccountingV5(hardToken).balanceOf(hardAccounts[i]) * scale;
        }
    }

    function protocolHeldUSDx() public view returns (uint256 held) {
        for (uint256 i = 0; i < protocolUSDxAccounts.length; ++i) {
            held += IERC20AccountingV5(usdx).balanceOf(protocolUSDxAccounts[i]);
        }
        uint256 supply = IERC20AccountingV5(usdx).totalSupply();
        return held > supply ? supply : held;
    }

    function externalUSDxLiability1e18() public view returns (uint256) {
        uint256 supply = IERC20AccountingV5(usdx).totalSupply();
        uint256 held = protocolHeldUSDx();
        return supply - held;
    }

    /// @notice Hard-asset coverage of externally held USDx. Internal treasury stock
    /// is excluded from the denominator. Returns max uint when external liability is zero.
    function externalCoverageBps() public view returns (uint256) {
        uint256 liability = externalUSDxLiability1e18();
        if (liability == 0) return type(uint256).max;
        return (hardAssets1e18() * 10_000) / liability;
    }

    function consolidatedHardNAV1e18() public view returns (int256) {
        return int256(hardAssets1e18()) - int256(externalUSDxLiability1e18());
    }

    function accountCounts() external view returns (uint256 hardCount, uint256 usdxCount) {
        return (hardAccounts.length, protocolUSDxAccounts.length);
    }
}
