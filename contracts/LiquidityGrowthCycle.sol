// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

interface IV2RouterLike {
    function removeLiquidity(address,address,uint256,uint256,uint256,address,uint256) external returns(uint256,uint256);
    function swapExactTokensForTokens(uint256,uint256,address[] calldata,address,uint256) external returns(uint256[] memory);
    function addLiquidity(address,address,uint256,uint256,uint256,uint256,address,uint256) external returns(uint256,uint256,uint256);
}
interface IMintable { function mint(address,uint256) external; }

/// @notice Executes the requested 15% remove / 10% LP burn / buyback / mint-add cycle.
/// Burning LP deliberately destroys the treasury's claim; it is not counted as LNAV growth.
contract LiquidityGrowthCycle {
    using SafeERC20 for IERC20;
    uint256 public constant REMOVE_BPS = 1_500;
    uint256 public constant BURN_LP_BPS = 1_000;
    address public constant BURN_SINK = 0x000000000000000000000000000000000000dEaD;
    address public immutable controller;
    IV2RouterLike public immutable router;
    mapping(address => bool) public allowedTargets;
    bool private entered;

    error Unauthorized();
    error Reentrant();
    error TargetNotAllowed();
    error CallFailed(uint256 index, bytes reason);
    error InsufficientProfit(uint256 actual, uint256 required);
    event GraphArbitrage(uint256 indexed proposalId, address settlement, uint256 profit);
    constructor(address controller_, IV2RouterLike router_) { controller = controller_; router = router_; }

    function setAllowedTarget(address target, bool allowed) external {
        if (msg.sender != controller) revert Unauthorized();
        allowedTargets[target] = allowed;
    }

    /// @notice Executes pre-simulated graph legs using protocol capital. Each
    /// target is allowlisted and the whole transaction reverts unless settlement
    /// balance grows by minProfit. proposalId binds keeper calldata off-chain.
    function executeGraphArbitrage(
        uint256 proposalId,
        address settlement,
        address[] calldata targets,
        bytes[] calldata calls,
        uint256 minProfit
    ) external returns (uint256 profit) {
        if (msg.sender != controller) revert Unauthorized();
        if (entered) revert Reentrant();
        require(targets.length == calls.length && targets.length > 1, "invalid route");
        entered = true;
        uint256 beforeBalance = IERC20(settlement).balanceOf(address(this));
        for (uint256 i; i < targets.length; ++i) {
            if (!allowedTargets[targets[i]]) revert TargetNotAllowed();
            (bool ok, bytes memory reason) = targets[i].call(calls[i]);
            if (!ok) revert CallFailed(i, reason);
        }
        uint256 afterBalance = IERC20(settlement).balanceOf(address(this));
        if (afterBalance < beforeBalance) revert InsufficientProfit(0, minProfit);
        profit = afterBalance - beforeBalance;
        if (profit < minProfit) revert InsufficientProfit(profit, minProfit);
        entered = false;
        emit GraphArbitrage(proposalId, settlement, profit);
    }

    function cycle(address lp, address base, address quote, uint256 minBaseOut, uint256 deadline)
        external returns (uint256 removedBase, uint256 removedQuote, uint256 boughtBase, uint256 mintedLp)
    {
        if (msg.sender != controller) revert Unauthorized();
        uint256 lpBalance = IERC20(lp).balanceOf(address(this));
        uint256 removeAmount = lpBalance * REMOVE_BPS / 10_000;
        uint256 burnAmount = lpBalance * BURN_LP_BPS / 10_000;
        IERC20(lp).forceApprove(address(router), removeAmount);
        (removedBase, removedQuote) = router.removeLiquidity(base, quote, removeAmount, 0, 0, address(this), deadline);
        IERC20(lp).safeTransfer(BURN_SINK, burnAmount);

        uint256 quoteForBuyback = removedQuote / 2;
        IERC20(quote).forceApprove(address(router), quoteForBuyback);
        address[] memory path = new address[](2); path[0] = quote; path[1] = base;
        uint256[] memory amounts = router.swapExactTokensForTokens(quoteForBuyback, minBaseOut, path, address(this), deadline);
        boughtBase = amounts[1];

        uint256 quoteToAdd = removedQuote - quoteForBuyback;
        uint256 baseToAdd = removedBase + boughtBase;
        IMintable(base).mint(address(this), baseToAdd); // governed token must grant this module MINTER_ROLE
        IERC20(base).forceApprove(address(router), baseToAdd * 2);
        IERC20(quote).forceApprove(address(router), quoteToAdd);
        (,, mintedLp) = router.addLiquidity(base, quote, baseToAdd * 2, quoteToAdd, 0, 0, address(this), deadline);
    }
}
