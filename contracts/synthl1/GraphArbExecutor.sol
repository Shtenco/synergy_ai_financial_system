// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./SafeTransferLib.sol";

interface IERC20GraphExec {
    function balanceOf(address) external view returns (uint256);
}

/// @notice Public atomic graph router for MEV/searcher cycles.
/// The bot supplies its own principal. Every venue must be allowlisted.
/// Internal GraphPool legs charge their configured protocol toll.
/// The router itself never fabricates profit: final base-token balance must exceed principal.
contract GraphArbExecutor {
    using SafeTransferLib for address;

    uint256 public constant MAX_LEGS = 10;

    address public owner;
    bool public paused;
    uint256 private lockState = 1;

    mapping(address => bool) public allowedTarget;
    mapping(address => address) public spenderForTarget;

    struct Leg {
        address target;
        address spender;
        address tokenIn;
        address tokenOut;
        uint256 amountIn;
        uint256 minAmountOut;
        bytes data;
    }

    event VenueSet(address indexed target, address indexed spender, bool allowed);
    event Cycle(address indexed searcher, address indexed baseToken, uint256 principal, uint256 returned, uint256 profit, uint256 legs);

    error Unauthorized();
    error BadRoute();
    error VenueNotAllowed();
    error ExternalCallFailed();
    error InsufficientOutput();
    error NotProfitable();
    error Reentrancy();
    error PausedError();

    constructor(address owner_) {
        if (owner_ == address(0)) revert BadRoute();
        owner = owner_;
    }

    modifier onlyOwner(){ if (msg.sender != owner) revert Unauthorized(); _; }
    modifier nonReentrant(){ if (lockState != 1) revert Reentrancy(); lockState = 2; _; lockState = 1; }

    function setVenue(address target, address spender, bool allowed) external onlyOwner {
        if (target == address(0) || spender == address(0)) revert BadRoute();
        allowedTarget[target] = allowed;
        spenderForTarget[target] = allowed ? spender : address(0);
        emit VenueSet(target, spender, allowed);
    }

    function setPaused(bool value) external onlyOwner { paused = value; }

    function executeCycle(
        address baseToken,
        uint256 principal,
        uint256 minProfit,
        Leg[] calldata legs,
        uint256 deadline
    ) external nonReentrant returns (uint256 returned, uint256 profit) {
        if (paused) revert PausedError();
        if (block.timestamp > deadline || principal == 0) revert BadRoute();

        uint256 n = legs.length;
        if (n < 2 || n > MAX_LEGS) revert BadRoute();
        if (legs[0].tokenIn != baseToken || legs[n-1].tokenOut != baseToken) revert BadRoute();

        baseToken.safeTransferFrom(msg.sender, address(this), principal);
        uint256 startingBase = IERC20GraphExec(baseToken).balanceOf(address(this));

        address expected = baseToken;
        uint256 available = principal;

        for (uint256 i = 0; i < n; ++i) {
            Leg calldata leg = legs[i];
            if (leg.tokenIn != expected || leg.amountIn == 0 || leg.amountIn > available) revert BadRoute();
            if (!allowedTarget[leg.target] || spenderForTarget[leg.target] != leg.spender) revert VenueNotAllowed();

            leg.tokenIn.forceApprove(leg.spender, leg.amountIn);
            uint256 beforeOut = IERC20GraphExec(leg.tokenOut).balanceOf(address(this));

            (bool ok,) = leg.target.call(leg.data);
            leg.tokenIn.forceApprove(leg.spender, 0);
            if (!ok) revert ExternalCallFailed();

            uint256 afterOut = IERC20GraphExec(leg.tokenOut).balanceOf(address(this));
            uint256 received = afterOut > beforeOut ? afterOut - beforeOut : 0;
            if (received < leg.minAmountOut) revert InsufficientOutput();

            expected = leg.tokenOut;
            available = received;
        }

        uint256 endingBase = IERC20GraphExec(baseToken).balanceOf(address(this));
        uint256 cycleBase = endingBase + principal >= startingBase ? endingBase + principal - startingBase : 0;
        if (cycleBase < principal + minProfit) revert NotProfitable();

        returned = cycleBase;
        profit = returned - principal;
        baseToken.safeTransfer(msg.sender, returned);

        emit Cycle(msg.sender, baseToken, principal, returned, profit, n);
    }
}
