// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IV15SolvencyRouteGate {
    function routeSolvent() external view returns (bool);
}

/// @notice Compatibility gate used by V15AccountingAdapter inside frozen V13.1 executor NAV checks.
contract V15PostRouteGate {
    address public immutable controller;
    error InsolventRouteState();

    constructor(address controller_) {
        require(controller_ != address(0), "controller=0");
        controller = controller_;
    }

    function assertRouteState() external view {
        if (!IV15SolvencyRouteGate(controller).routeSolvent()) revert InsolventRouteState();
    }
}
