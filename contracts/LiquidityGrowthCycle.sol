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

/// @notice Executes a bounded 15% LP remove / buyback / mint-add cycle.
contract LiquidityGrowthCycle {
    using SafeERC20 for IERC20;
    uint256 public constant REMOVE_BPS = 1_500;
    uint256 public constant PROFIT_TAX_BPS = 2_000;
    address public immutable controller;
    address public immutable treasury;
    IV2RouterLike public immutable router;
    mapping(address => bytes32) public allowedTargetCodehash;
    mapping(address => bool) public protectedAssets;
    bool private entered;

    error Unauthorized();
    error Reentrant();
    error TargetNotAllowed();
    error CallFailed(uint256 index, bytes reason);
    error InsufficientProfit(uint256 actual, uint256 required);
    event GraphArbitrage(uint256 indexed proposalId, address settlement, uint256 grossProfit, uint256 tax);
    constructor(address controller_, address treasury_, IV2RouterLike router_) {
        require(controller_ != address(0) && treasury_ != address(0) && address(router_) != address(0));
        controller = controller_; treasury = treasury_; router = router_;
    }

    function setAllowedTarget(address target, bool allowed) external {
        if (msg.sender != controller) revert Unauthorized();
        allowedTargetCodehash[target] = allowed ? target.codehash : bytes32(0);
    }

    function setProtectedAsset(address asset, bool protected_) external {
        if (msg.sender != controller) revert Unauthorized();
        protectedAssets[asset] = protected_;
    }

    /// @notice Executes pre-simulated graph legs using protocol capital. Each
    /// target is allowlisted and the whole transaction reverts unless settlement
    /// balance grows by minProfit. proposalId binds keeper calldata off-chain.
    function executeGraphArbitrage(
        uint256 proposalId,
        address settlement,
        address[] calldata targets,
        bytes[] calldata calls,
        address[] calldata assets,
        uint256 minProfit
    ) external returns (uint256 profit) {
        if (msg.sender != controller) revert Unauthorized();
        if (entered) revert Reentrant();
        require(targets.length == calls.length && targets.length > 1, "invalid route");
        entered = true;
        uint256 beforeBalance = IERC20(settlement).balanceOf(address(this));
        uint256[] memory beforeAssets = new uint256[](assets.length);
        for (uint256 i; i < assets.length; ++i) {
            require(protectedAssets[assets[i]], "asset not registered");
            beforeAssets[i] = IERC20(assets[i]).balanceOf(address(this));
        }
        for (uint256 i; i < targets.length; ++i) {
            bytes32 expected = allowedTargetCodehash[targets[i]];
            if (expected == bytes32(0) || targets[i].codehash != expected) revert TargetNotAllowed();
            (bool ok, bytes memory reason) = targets[i].call(calls[i]);
            if (!ok) revert CallFailed(i, reason);
        }
        uint256 afterBalance = IERC20(settlement).balanceOf(address(this));
        for (uint256 i; i < assets.length; ++i) {
            if (assets[i] != settlement) {
                require(IERC20(assets[i]).balanceOf(address(this)) >= beforeAssets[i], "protected asset loss");
            }
        }
        if (afterBalance < beforeBalance) revert InsufficientProfit(0, minProfit);
        profit = afterBalance - beforeBalance;
        if (profit < minProfit) revert InsufficientProfit(profit, minProfit);
        uint256 tax = profit * PROFIT_TAX_BPS / 10_000;
        IERC20(settlement).safeTransfer(treasury, tax);
        entered = false;
        emit GraphArbitrage(proposalId, settlement, profit, tax);
    }

    function cycle(
        address lp, address base, address quote,
        uint256 minBaseRemoved, uint256 minQuoteRemoved,
        uint256 minBaseSwapOut, uint256 minBaseAdded, uint256 minQuoteAdded,
        uint256 deadline
    )
        external returns (uint256 removedBase, uint256 removedQuote, uint256 boughtBase, uint256 mintedLp)
    {
        if (msg.sender != controller) revert Unauthorized();
        uint256 lpBalance = IERC20(lp).balanceOf(address(this));
        uint256 removeAmount = lpBalance * REMOVE_BPS / 10_000;
        IERC20(lp).forceApprove(address(router), removeAmount);
        (removedBase, removedQuote) = router.removeLiquidity(
            base, quote, removeAmount, minBaseRemoved, minQuoteRemoved, address(this), deadline
        );

        uint256 quoteForBuyback = removedQuote / 2;
        IERC20(quote).forceApprove(address(router), quoteForBuyback);
        address[] memory path = new address[](2); path[0] = quote; path[1] = base;
        uint256[] memory amounts = router.swapExactTokensForTokens(
            quoteForBuyback, minBaseSwapOut, path, address(this), deadline
        );
        boughtBase = amounts[1];

        uint256 quoteToAdd = removedQuote - quoteForBuyback;
        uint256 baseToAdd = removedBase + boughtBase;
        IMintable(base).mint(address(this), baseToAdd); // governed token must grant this module MINTER_ROLE
        IERC20(base).forceApprove(address(router), baseToAdd * 2);
        IERC20(quote).forceApprove(address(router), quoteToAdd);
        (,, mintedLp) = router.addLiquidity(
            base, quote, baseToAdd * 2, quoteToAdd,
            minBaseAdded, minQuoteAdded, address(this), deadline
        );
    }
}
