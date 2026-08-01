// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

interface IV2RouterV151 {
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);
}

interface IV3RouterV151 {
    struct ExactInputSingleParams {
        address tokenIn;
        address tokenOut;
        uint24 fee;
        address recipient;
        uint256 deadline;
        uint256 amountIn;
        uint256 amountOutMinimum;
        uint160 sqrtPriceLimitX96;
    }

    function exactInputSingle(ExactInputSingleParams calldata params)
        external
        payable
        returns (uint256 amountOut);
}

/// @notice Adapter for Uniswap-V2-compatible routers such as QuickSwap V2.
/// `data = abi.encode(address[] path, uint256 deadline)`.
contract V2RouterAdapterV151 is ReentrancyGuard {
    using SafeERC20 for IERC20;

    address public immutable router;

    error InvalidConfiguration();
    error InvalidPath();
    error InsufficientOutput();

    constructor(address router_) {
        if (router_ == address(0) || router_.code.length == 0) {
            revert InvalidConfiguration();
        }
        router = router_;
    }

    function swap(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut,
        address recipient,
        bytes calldata data
    ) external nonReentrant returns (uint256 amountOut) {
        if (
            tokenIn == address(0)
                || tokenOut == address(0)
                || tokenIn == tokenOut
                || amountIn == 0
                || minAmountOut == 0
                || recipient == address(0)
        ) revert InvalidConfiguration();

        (address[] memory path, uint256 deadline) = abi.decode(data, (address[], uint256));
        if (
            path.length < 2
                || path[0] != tokenIn
                || path[path.length - 1] != tokenOut
                || deadline < block.timestamp
        ) revert InvalidPath();

        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);
        IERC20(tokenIn).forceApprove(router, amountIn);
        uint256[] memory amounts = IV2RouterV151(router).swapExactTokensForTokens(
            amountIn,
            minAmountOut,
            path,
            recipient,
            deadline
        );
        IERC20(tokenIn).forceApprove(router, 0);

        amountOut = amounts[amounts.length - 1];
        if (amountOut < minAmountOut) revert InsufficientOutput();
    }
}

/// @notice Adapter for the canonical Uniswap V3 SwapRouter exact-input-single
/// interface. `data = abi.encode(uint24 fee, uint160 sqrtPriceLimitX96,
/// uint256 deadline)`.
contract V3RouterAdapterV151 is ReentrancyGuard {
    using SafeERC20 for IERC20;

    address public immutable router;

    error InvalidConfiguration();
    error InsufficientOutput();

    constructor(address router_) {
        if (router_ == address(0) || router_.code.length == 0) {
            revert InvalidConfiguration();
        }
        router = router_;
    }

    function swap(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut,
        address recipient,
        bytes calldata data
    ) external nonReentrant returns (uint256 amountOut) {
        if (
            tokenIn == address(0)
                || tokenOut == address(0)
                || tokenIn == tokenOut
                || amountIn == 0
                || minAmountOut == 0
                || recipient == address(0)
        ) revert InvalidConfiguration();

        (uint24 fee, uint160 sqrtPriceLimitX96, uint256 deadline) =
            abi.decode(data, (uint24, uint160, uint256));
        if (fee == 0 || deadline < block.timestamp) revert InvalidConfiguration();

        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);
        IERC20(tokenIn).forceApprove(router, amountIn);
        amountOut = IV3RouterV151(router).exactInputSingle(
            IV3RouterV151.ExactInputSingleParams({
                tokenIn: tokenIn,
                tokenOut: tokenOut,
                fee: fee,
                recipient: recipient,
                deadline: deadline,
                amountIn: amountIn,
                amountOutMinimum: minAmountOut,
                sqrtPriceLimitX96: sqrtPriceLimitX96
            })
        );
        IERC20(tokenIn).forceApprove(router, 0);

        if (amountOut < minAmountOut) revert InsufficientOutput();
    }
}
