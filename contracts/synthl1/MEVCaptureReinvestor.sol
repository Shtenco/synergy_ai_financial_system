// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./SafeTransferLib.sol";

interface IERC20Capture {
    function balanceOf(address) external view returns (uint256);
}

/// @notice Receives transparent pool tolls and exposes only actually received balances
/// for the next recursive pulse. No virtual fee accounting.
contract MEVCaptureReinvestor {
    using SafeTransferLib for address;

    address public owner;
    address public controller;

    mapping(address => bool) public allowedPool;
    mapping(address => mapping(bool => uint16)) public outputTollBps;
    mapping(address => uint256) public cumulativeCaptured;
    mapping(address => uint256) public cumulativeReinvested;

    uint16 public constant MAX_OUTPUT_TOLL_BPS = 3_000;

    event ControllerSet(address indexed controller);
    event PoolSet(address indexed pool, bool allowed);
    event TollSet(address indexed pool, bool zeroToOne, uint16 bps);
    event Captured(address indexed pool, address indexed token, uint256 amount);
    event Reinvested(address indexed token, address indexed to, uint256 amount);

    error Unauthorized();
    error BadConfig();

    constructor(address owner_) {
        if (owner_ == address(0)) revert BadConfig();
        owner = owner_;
    }

    modifier onlyOwner() { if (msg.sender != owner) revert Unauthorized(); _; }
    modifier onlyController() { if (msg.sender != controller) revert Unauthorized(); _; }
    modifier onlyPool() { if (!allowedPool[msg.sender]) revert Unauthorized(); _; }

    function setController(address controller_) external onlyOwner {
        if (controller_ == address(0)) revert BadConfig();
        controller = controller_;
        emit ControllerSet(controller_);
    }

    function setPool(address pool, bool allowed) external onlyOwner {
        if (pool == address(0)) revert BadConfig();
        allowedPool[pool] = allowed;
        emit PoolSet(pool, allowed);
    }

    function setOutputToll(address pool, bool zeroToOne, uint16 bps) external onlyController {
        if (!allowedPool[pool] || bps > MAX_OUTPUT_TOLL_BPS) revert BadConfig();
        outputTollBps[pool][zeroToOne] = bps;
        emit TollSet(pool, zeroToOne, bps);
    }

    function tollBps(address pool, bool zeroToOne) external view returns (uint16) {
        return outputTollBps[pool][zeroToOne];
    }

    function checkpoint(address token, uint256 amount) external onlyPool {
        cumulativeCaptured[token] += amount;
        emit Captured(msg.sender, token, amount);
    }

    function available(address token) public view returns (uint256) {
        return IERC20Capture(token).balanceOf(address(this));
    }

    function pullForReinvestment(address token, address to, uint256 amount) external onlyController {
        if (to == address(0) || amount == 0 || amount > available(token)) revert BadConfig();
        cumulativeReinvested[token] += amount;
        token.safeTransfer(to, amount);
        emit Reinvested(token, to, amount);
    }
}
