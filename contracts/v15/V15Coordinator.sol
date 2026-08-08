// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IV15SolvencyCoordinator {
    function canExpand() external view returns (bool);
    function routeSolvent() external view returns (bool);
    function maxGradientShiftBps() external view returns (uint16);
}

interface IV15GradientEngine {
    function active() external view returns (bool);
    function initializeGradient(address source, address destination, uint256 shift) external;
    function restoreGradient() external returns (uint256 restored);
    function reinvestCapturedQuote(address pool, uint256 amount) external;
    function closeGradient() external;
}

interface IV15GradientPoolView {
    function reserve0() external view returns (uint256);
}

/// @notice Upper policy/operator layer for one or more frozen V13.1 gradient engines.
contract V15Coordinator {
    address public owner;
    address public operator;
    IV15SolvencyCoordinator public immutable controller;
    mapping(address => bool) public engineAllowed;
    bool public paused;

    event OperatorSet(address indexed operator);
    event EngineSet(address indexed engine, bool allowed);
    event Paused(bool value);
    event GradientRequested(address indexed engine, address indexed source, address indexed destination, uint256 shift);

    error Unauthorized();
    error BadConfig();
    error RiskBlocked();

    constructor(address owner_, address operator_, address controller_) {
        if (owner_ == address(0) || operator_ == address(0) || controller_ == address(0)) revert BadConfig();
        owner = owner_;
        operator = operator_;
        controller = IV15SolvencyCoordinator(controller_);
    }

    modifier onlyOwner() { if (msg.sender != owner) revert Unauthorized(); _; }
    modifier onlyOperator() { if (msg.sender != operator) revert Unauthorized(); _; }

    function setOperator(address next) external onlyOwner {
        if (next == address(0)) revert BadConfig();
        operator = next;
        emit OperatorSet(next);
    }

    function setEngine(address engine, bool allowed) external onlyOwner {
        if (engine == address(0)) revert BadConfig();
        engineAllowed[engine] = allowed;
        emit EngineSet(engine, allowed);
    }

    function setPaused(bool value) external onlyOwner {
        paused = value;
        emit Paused(value);
    }

    function initializeGradient(address engine, address source, address destination, uint256 shift) external onlyOperator {
        if (paused || !engineAllowed[engine] || shift == 0) revert BadConfig();
        if (!controller.canExpand()) revert RiskBlocked();
        if (IV15GradientEngine(engine).active()) revert BadConfig();
        uint256 reserve = IV15GradientPoolView(source).reserve0();
        uint16 maxBps = controller.maxGradientShiftBps();
        if (maxBps == 0 || shift >= reserve || shift * 10_000 > reserve * uint256(maxBps)) revert RiskBlocked();
        IV15GradientEngine(engine).initializeGradient(source, destination, shift);
        emit GradientRequested(engine, source, destination, shift);
    }

    /// @notice Restore/close are always available, including RED emergency mode.
    function restoreGradient(address engine) external onlyOperator returns (uint256) {
        if (!engineAllowed[engine]) revert BadConfig();
        return IV15GradientEngine(engine).restoreGradient();
    }

    function closeGradient(address engine) external onlyOperator {
        if (!engineAllowed[engine]) revert BadConfig();
        IV15GradientEngine(engine).closeGradient();
    }

    function reinvestCapturedQuote(address engine, address pool, uint256 amount) external onlyOperator {
        if (paused || !engineAllowed[engine] || !controller.routeSolvent()) revert RiskBlocked();
        IV15GradientEngine(engine).reinvestCapturedQuote(pool, amount);
    }
}
