// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IV15SolvencyRouteGate {
    /// @notice True only when a new searcher exploitation is permitted.
    /// ORANGE/RED are deliberately excluded even if the balance sheet still
    /// satisfies their lower survival floors: those modes are for unwind/restore.
    function searcherRouteAllowed() external view returns (bool);
}

/// @notice Compatibility gate used by V15AccountingAdapter inside the frozen
/// V13.1 GraphArbExecutor NAV snapshots. Because the frozen executor calls the
/// adapter before and after route execution, a false result at either boundary
/// reverts the complete route atomically.
contract V15PostRouteGate {
    address public immutable controller;

    error InsolventRouteState();

    constructor(address controller_) {
        require(controller_ != address(0), "controller=0");
        controller = controller_;
    }

    function assertRouteState() external view {
        if (!IV15SolvencyRouteGate(controller).searcherRouteAllowed()) {
            revert InsolventRouteState();
        }
    }
}
