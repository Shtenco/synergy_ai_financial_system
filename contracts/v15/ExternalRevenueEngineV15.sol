// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

interface IOrderflowAuctionV15 {
    function best(uint256 epoch)
        external
        view
        returns (address solver, uint128 amount, bytes32 solutionHash, bool settled);
    function isWinningSolution(uint256 epoch, bytes32 solutionHash) external view returns (bool);
    function consumeWinningSolution(uint256 epoch, bytes32 solutionHash) external;
}

interface IV2RouterV15 {
    function swapExactTokensForTokens(
        uint256 amountIn,
        uint256 amountOutMin,
        address[] calldata path,
        address to,
        uint256 deadline
    ) external returns (uint256[] memory amounts);
}

interface IV3RouterV15 {
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

interface IPrivateRFQSettlementV15 {
    struct Order {
        address maker;
        address taker;
        address tokenIn;
        address tokenOut;
        uint256 amountIn;
        uint256 amountOut;
        uint256 expiry;
        uint256 nonce;
        bytes32 salt;
    }

    function hashOrder(Order calldata order) external view returns (bytes32);
    function fill(Order calldata order, bytes calldata signature) external returns (uint256 amountOut);
}

/// @notice V15 external revenue layer. It cannot mint protocol tokens and only
/// credits treasury after a complete external round trip returns principal and
/// clears a strict minimum edge. Winning solver routes are single-use.
contract ExternalRevenueEngineV15 is ReentrancyGuard {
    using SafeERC20 for IERC20;

    uint256 public constant PPM = 1_000_000;
    bytes32 private constant V3_TO_V2_KIND = keccak256("V15_V3_TO_V2_BACKRUN");
    bytes32 private constant RFQ_TO_V2_KIND = keccak256("V15_RFQ_TO_V2_PRIVATE");

    IOrderflowAuctionV15 public immutable auction;
    address public immutable treasury;
    uint256 public immutable minimumExternalEdgePpm;

    mapping(address token => uint256 revenue) public cumulativeRevenue;
    mapping(bytes32 solutionHash => bool used) public executionUsed;

    error InvalidConfiguration();
    error NotWinningSolver();
    error InvalidSolution();
    error InsufficientExternalEdge();
    error Replay();

    event ExternalRevenueCaptured(
        bytes32 indexed solutionHash,
        uint256 indexed epoch,
        address indexed solver,
        bytes32 routeKind,
        address settlementToken,
        address intermediateToken,
        uint256 principal,
        uint256 grossOutput,
        uint256 realizedRevenue,
        uint256 realizedEdgePpm
    );

    constructor(address auction_, address treasury_, uint256 minimumExternalEdgePpm_) {
        if (
            auction_ == address(0)
                || treasury_ == address(0)
                || auction_.code.length == 0
                || minimumExternalEdgePpm_ == 0
                || minimumExternalEdgePpm_ >= PPM
        ) revert InvalidConfiguration();
        auction = IOrderflowAuctionV15(auction_);
        treasury = treasury_;
        minimumExternalEdgePpm = minimumExternalEdgePpm_;
    }

    function hashV3ToV2Solution(
        address v3Router,
        address v2Router,
        address tokenIn,
        address tokenMid,
        uint24 fee,
        uint256 amountIn,
        uint256 minMidOut,
        uint256 minFinalOut,
        uint256 minRevenue
    ) public view returns (bytes32) {
        return keccak256(
            abi.encode(
                V3_TO_V2_KIND,
                block.chainid,
                address(this),
                v3Router,
                v2Router,
                tokenIn,
                tokenMid,
                fee,
                amountIn,
                minMidOut,
                minFinalOut,
                minRevenue
            )
        );
    }

    function hashRfqToV2Solution(
        address rfqSettlement,
        bytes32 orderDigest,
        address v2Router,
        address tokenIn,
        address tokenMid,
        uint256 amountIn,
        uint256 minFinalOut,
        uint256 minRevenue
    ) public view returns (bytes32) {
        return keccak256(
            abi.encode(
                RFQ_TO_V2_KIND,
                block.chainid,
                address(this),
                rfqSettlement,
                orderDigest,
                v2Router,
                tokenIn,
                tokenMid,
                amountIn,
                minFinalOut,
                minRevenue
            )
        );
    }

    function executeV3ToV2Backrun(
        uint256 epoch,
        bytes32 solutionHash,
        address v3Router,
        address v2Router,
        address tokenIn,
        address tokenMid,
        uint24 fee,
        uint256 amountIn,
        uint256 minMidOut,
        uint256 minFinalOut,
        uint256 minRevenue,
        uint256 deadline
    ) external nonReentrant returns (uint256 revenue) {
        if (
            tokenIn == address(0)
                || tokenMid == address(0)
                || tokenIn == tokenMid
                || v3Router.code.length == 0
                || v2Router.code.length == 0
                || amountIn == 0
                || deadline < block.timestamp
        ) revert InvalidConfiguration();
        bytes32 expected = hashV3ToV2Solution(
            v3Router,
            v2Router,
            tokenIn,
            tokenMid,
            fee,
            amountIn,
            minMidOut,
            minFinalOut,
            minRevenue
        );
        if (expected != solutionHash) revert InvalidSolution();
        _consumeWinningSolution(epoch, solutionHash);

        uint256 settlementBefore = IERC20(tokenIn).balanceOf(address(this));
        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);
        IERC20(tokenIn).forceApprove(v3Router, amountIn);

        uint256 amountMid = IV3RouterV15(v3Router).exactInputSingle(
            IV3RouterV15.ExactInputSingleParams({
                tokenIn: tokenIn,
                tokenOut: tokenMid,
                fee: fee,
                recipient: address(this),
                deadline: deadline,
                amountIn: amountIn,
                amountOutMinimum: minMidOut,
                sqrtPriceLimitX96: 0
            })
        );

        IERC20(tokenMid).forceApprove(v2Router, amountMid);
        address[] memory path = new address[](2);
        path[0] = tokenMid;
        path[1] = tokenIn;
        IV2RouterV15(v2Router).swapExactTokensForTokens(
            amountMid,
            minFinalOut,
            path,
            address(this),
            deadline
        );

        revenue = _creditRevenue(
            epoch,
            solutionHash,
            V3_TO_V2_KIND,
            tokenIn,
            tokenMid,
            amountIn,
            minRevenue,
            settlementBefore
        );
    }

    function executePrivateRfqToV2(
        uint256 epoch,
        bytes32 solutionHash,
        address rfqSettlement,
        IPrivateRFQSettlementV15.Order calldata order,
        bytes calldata makerSignature,
        address v2Router,
        address tokenIn,
        address tokenMid,
        uint256 amountIn,
        uint256 minFinalOut,
        uint256 minRevenue,
        uint256 deadline
    ) external nonReentrant returns (uint256 revenue) {
        if (
            rfqSettlement.code.length == 0
                || v2Router.code.length == 0
                || tokenIn == address(0)
                || tokenMid == address(0)
                || tokenIn == tokenMid
                || amountIn == 0
                || deadline < block.timestamp
                || order.taker != address(this)
                || order.tokenIn != tokenIn
                || order.tokenOut != tokenMid
                || order.amountIn != amountIn
        ) revert InvalidConfiguration();

        bytes32 orderDigest = IPrivateRFQSettlementV15(rfqSettlement).hashOrder(order);
        bytes32 expected = hashRfqToV2Solution(
            rfqSettlement,
            orderDigest,
            v2Router,
            tokenIn,
            tokenMid,
            amountIn,
            minFinalOut,
            minRevenue
        );
        if (expected != solutionHash) revert InvalidSolution();
        _consumeWinningSolution(epoch, solutionHash);

        uint256 settlementBefore = IERC20(tokenIn).balanceOf(address(this));
        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);
        IERC20(tokenIn).forceApprove(rfqSettlement, amountIn);
        uint256 amountMid = IPrivateRFQSettlementV15(rfqSettlement).fill(order, makerSignature);

        IERC20(tokenMid).forceApprove(v2Router, amountMid);
        address[] memory path = new address[](2);
        path[0] = tokenMid;
        path[1] = tokenIn;
        IV2RouterV15(v2Router).swapExactTokensForTokens(
            amountMid,
            minFinalOut,
            path,
            address(this),
            deadline
        );

        revenue = _creditRevenue(
            epoch,
            solutionHash,
            RFQ_TO_V2_KIND,
            tokenIn,
            tokenMid,
            amountIn,
            minRevenue,
            settlementBefore
        );
    }

    function _consumeWinningSolution(uint256 epoch, bytes32 solutionHash) internal {
        if (executionUsed[solutionHash]) revert Replay();
        (address solver,, bytes32 winningHash, bool settled) = auction.best(epoch);
        if (
            solver != msg.sender
                || !settled
                || winningHash != solutionHash
                || !auction.isWinningSolution(epoch, solutionHash)
        ) revert NotWinningSolver();
        executionUsed[solutionHash] = true;
        auction.consumeWinningSolution(epoch, solutionHash);
    }

    function _creditRevenue(
        uint256 epoch,
        bytes32 solutionHash,
        bytes32 routeKind,
        address tokenIn,
        address tokenMid,
        uint256 principal,
        uint256 minRevenue,
        uint256 settlementBefore
    ) internal returns (uint256 revenue) {
        uint256 settlementAfter = IERC20(tokenIn).balanceOf(address(this));
        uint256 grossOutput = settlementAfter - settlementBefore;
        if (grossOutput <= principal) revert InsufficientExternalEdge();
        revenue = grossOutput - principal;
        uint256 edgePpm = revenue * PPM / principal;
        if (revenue < minRevenue || edgePpm < minimumExternalEdgePpm) {
            revert InsufficientExternalEdge();
        }

        IERC20(tokenIn).safeTransfer(msg.sender, principal);
        IERC20(tokenIn).safeTransfer(treasury, revenue);
        cumulativeRevenue[tokenIn] += revenue;

        emit ExternalRevenueCaptured(
            solutionHash,
            epoch,
            msg.sender,
            routeKind,
            tokenIn,
            tokenMid,
            principal,
            grossOutput,
            revenue,
            edgePpm
        );
    }
}
