// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

interface ISolverAuctionBidV151 {
    function bid(uint256 epoch, bytes32 solutionHash, uint16 treasuryShareBps) external payable;
    function withdrawRefund() external;
}

contract MockERC20V151 is ERC20 {
    constructor(string memory name_, string memory symbol_) ERC20(name_, symbol_) {}

    function issueForTest(address recipient, uint256 amount) external {
        _mint(recipient, amount);
    }
}

/// @notice Deterministic adapter for structural tests only. It is never valid
/// economic evidence because its exchange rate and inventory are test fixtures.
contract MockRateAdapterV151 {
    using SafeERC20 for IERC20;

    address public immutable configuredTokenIn;
    address public immutable configuredTokenOut;
    uint256 public immutable numerator;
    uint256 public immutable denominator;

    error InvalidConfiguration();
    error InsufficientOutput();

    constructor(
        address tokenIn_,
        address tokenOut_,
        uint256 numerator_,
        uint256 denominator_
    ) {
        if (
            tokenIn_ == address(0)
                || tokenOut_ == address(0)
                || tokenIn_ == tokenOut_
                || numerator_ == 0
                || denominator_ == 0
        ) revert InvalidConfiguration();
        configuredTokenIn = tokenIn_;
        configuredTokenOut = tokenOut_;
        numerator = numerator_;
        denominator = denominator_;
    }

    function swap(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut,
        address recipient,
        bytes calldata data
    ) external returns (uint256 amountOut) {
        if (
            tokenIn != configuredTokenIn
                || tokenOut != configuredTokenOut
                || amountIn == 0
                || recipient == address(0)
                || data.length != 0
        ) revert InvalidConfiguration();

        amountOut = amountIn * numerator / denominator;
        if (amountOut < minAmountOut) revert InsufficientOutput();
        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);
        IERC20(tokenOut).safeTransfer(recipient, amountOut);
    }
}

/// @notice A bidder that rejects native transfers. Pull refunds ensure it cannot
/// block auction settlement or another solver's execution.
contract RejectNativeBidderV151 {
    function placeBid(
        address auction,
        uint256 epoch,
        bytes32 solutionHash,
        uint16 treasuryShareBps
    ) external payable {
        ISolverAuctionBidV151(auction).bid{value: msg.value}(
            epoch,
            solutionHash,
            treasuryShareBps
        );
    }

    function withdraw(address auction) external {
        ISolverAuctionBidV151(auction).withdrawRefund();
    }

    receive() external payable {
        revert("native transfer rejected");
    }
}
