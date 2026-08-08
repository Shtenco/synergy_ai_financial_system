// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IV15EconomicLedgerAdapter {
    function hardNAV1e18() external view returns (int256);
    function isHardAccount(address token, address account) external view returns (bool);
    function isHardAsset(address token) external view returns (bool);
    function markValue1e18(address token, uint256 amount) external view returns (uint256);
}

interface IV15PostRouteGateAdapter {
    function assertRouteState() external view;
}

interface IV15CoverageAdapter {
    function currentCoverageBps() external view returns (uint256);
}

/// @notice Dual compatibility layer for frozen V13.1 GraphArbExecutor AND
/// ReserveGradientEngine. Naming keeps the frozen USDx ABI, while V15 treats
/// these mappings generically as own-synthetic protocol accounts/pools.
contract V15AccountingAdapter {
    address public owner;
    address public immutable protocolLiquidityOwner;
    IV15EconomicLedgerAdapter public immutable ledger;
    IV15PostRouteGateAdapter public immutable gate;
    IV15CoverageAdapter public immutable controller;

    mapping(address => bool) public syntheticProtocolAccount;
    mapping(address => bool) public syntheticPoolAccount;

    event SyntheticProtocolAccountSet(address indexed account, bool enabled);
    event SyntheticPoolAccountSet(address indexed account, bool enabled);
    error Unauthorized();
    error BadConfig();

    constructor(address owner_, address liquidityOwner_, address ledger_, address gate_, address controller_) {
        if (
            owner_ == address(0) || liquidityOwner_ == address(0) || ledger_ == address(0) ||
            gate_ == address(0) || controller_ == address(0)
        ) revert BadConfig();
        owner = owner_;
        protocolLiquidityOwner = liquidityOwner_;
        ledger = IV15EconomicLedgerAdapter(ledger_);
        gate = IV15PostRouteGateAdapter(gate_);
        controller = IV15CoverageAdapter(controller_);
    }

    modifier onlyOwner() { if (msg.sender != owner) revert Unauthorized(); _; }

    function setSyntheticProtocolAccount(address account, bool enabled) external onlyOwner {
        if (account == address(0)) revert BadConfig();
        syntheticProtocolAccount[account] = enabled;
        emit SyntheticProtocolAccountSet(account, enabled);
    }

    function setSyntheticPoolAccount(address account, bool enabled) external onlyOwner {
        if (account == address(0)) revert BadConfig();
        syntheticProtocolAccount[account] = enabled;
        syntheticPoolAccount[account] = enabled;
        emit SyntheticPoolAccountSet(account, enabled);
    }

    /// @dev Frozen executor calls this both pre- and post-route. If post-route
    /// K/STS is unsafe, the gate reverts and the full route rolls back atomically.
    function consolidatedHardNAV1e18() external view returns (int256) {
        gate.assertRouteState();
        return ledger.hardNAV1e18();
    }

    function economicHardNAV1e18() external view returns (int256) { return ledger.hardNAV1e18(); }
    function externalCoverageBps() external view returns (uint256) { return controller.currentCoverageBps(); }

    // Frozen V13.1 compatibility names.
    function isProtocolUSDxAccount(address account) external view returns (bool) { return syntheticProtocolAccount[account]; }
    function isProtocolUSDxPoolAccount(address account) external view returns (bool) { return syntheticPoolAccount[account]; }

    function isHardAccount(address token, address account) external view returns (bool) { return ledger.isHardAccount(token, account); }
    function isHardAsset(address token) external view returns (bool) { return ledger.isHardAsset(token); }
    function markValue1e18(address token, uint256 amount) external view returns (uint256) { return ledger.markValue1e18(token, amount); }
}
