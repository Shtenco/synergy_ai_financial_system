// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

interface ISolverAuctionV151 {
    function best(uint256 epoch)
        external
        view
        returns (
            address solver,
            uint128 bond,
            uint16 treasuryShareBps,
            bytes32 solutionHash,
            bool settled,
            bool consumed
        );

    function opportunityDetails(uint256 epoch)
        external
        view
        returns (
            address settlementToken,
            uint128 maxPrincipal,
            uint128 minTreasuryRevenue,
            uint32 minEdgePpm,
            uint16 minTreasuryShareBps,
            uint64 closeBlock,
            uint64 expiryBlock,
            bytes32 venuesHash,
            bool published,
            bool settled
        );

    function consumeWinningSolution(uint256 epoch, bytes32 solutionHash) external;
}

interface ISwapAdapterV151 {
    /// @dev Adapter pulls exactly `amountIn` from msg.sender and transfers the
    /// resulting tokenOut directly to `recipient`.
    function swap(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut,
        address recipient,
        bytes calldata data
    ) external returns (uint256 amountOut);
}

/// @notice Strict V15.1 external-revenue executor. It has no mint/burn surface
/// and no protocol-internal LP surface. Profit is recognized only after a full
/// external route returns to the settlement token.
contract ExternalRevenueEngineV151 is ReentrancyGuard {
    using SafeERC20 for IERC20;

    uint256 public constant PPM = 1_000_000;
    uint256 public constant BPS = 10_000;
    uint256 public constant MAX_ROUTE_STEPS = 8;
    bytes32 public constant ROUTE_KIND = keccak256("SYNERGY_V15_1_EXTERNAL_ROUTE");

    struct Step {
        address adapter;
        address tokenIn;
        address tokenOut;
        uint256 minAmountOut;
        bytes data;
    }

    ISolverAuctionV151 public immutable auction;
    address public immutable treasury;
    address public immutable governor;

    mapping(address adapter => bytes32 codehash) public allowedAdapterCodehash;
    mapping(address settlementToken => uint256 revenue) public cumulativeTreasuryRevenue;
    mapping(address settlementToken => uint256 revenue) public cumulativeSolverRevenue;

    error Unauthorized();
    error InvalidConfiguration();
    error InvalidRoute();
    error AdapterNotAllowed();
    error NotWinningSolver();
    error AuctionTermsMismatch();
    error TokenFlowMismatch();
    error InsufficientExternalEdge();

    event AdapterPermissionSet(address indexed adapter, bytes32 indexed codehash);
    event ExternalRevenueCaptured(
        uint256 indexed epoch,
        bytes32 indexed solutionHash,
        address indexed solver,
        address settlementToken,
        uint256 principal,
        uint256 grossOutput,
        uint256 grossProfit,
        uint256 treasuryRevenue,
        uint256 solverRevenue,
        uint256 realizedEdgePpm,
        uint256 treasuryShareBps,
        bytes32 venuesHash
    );

    constructor(address auction_, address treasury_, address governor_) {
        if (
            auction_ == address(0)
                || treasury_ == address(0)
                || governor_ == address(0)
                || auction_.code.length == 0
        ) revert InvalidConfiguration();
        auction = ISolverAuctionV151(auction_);
        treasury = treasury_;
        governor = governor_;
    }

    function setAdapter(address adapter, bool allowed) external {
        if (msg.sender != governor) revert Unauthorized();
        if (adapter == address(0)) revert InvalidConfiguration();
        bytes32 codehash = allowed ? adapter.codehash : bytes32(0);
        if (allowed && codehash == bytes32(0)) revert InvalidConfiguration();
        allowedAdapterCodehash[adapter] = codehash;
        emit AdapterPermissionSet(adapter, codehash);
    }

    function hashRoute(
        uint256 epoch,
        address settlementToken,
        uint256 principal,
        Step[] calldata steps
    ) public view returns (bytes32) {
        bytes32 stepsHash = keccak256(bytes(""));
        for (uint256 i = 0; i < steps.length; ++i) {
            Step calldata step = steps[i];
            stepsHash = keccak256(
                abi.encode(
                    stepsHash,
                    step.adapter,
                    step.tokenIn,
                    step.tokenOut,
                    step.minAmountOut,
                    keccak256(step.data)
                )
            );
        }
        return keccak256(
            abi.encode(
                ROUTE_KIND,
                block.chainid,
                address(this),
                epoch,
                settlementToken,
                principal,
                stepsHash
            )
        );
    }

    function execute(
        uint256 epoch,
        bytes32 solutionHash,
        address settlementToken,
        uint256 principal,
        Step[] calldata steps
    ) external nonReentrant returns (
        uint256 treasuryRevenue,
        uint256 solverRevenue
    ) {
        if (
            settlementToken == address(0)
                || principal == 0
                || steps.length < 2
                || steps.length > MAX_ROUTE_STEPS
        ) revert InvalidRoute();

        (
            address winningSolver,
            ,
            uint16 treasuryShareBps,
            bytes32 winningHash,
            bool auctionSettled,
            bool auctionConsumed
        ) = auction.best(epoch);
        if (
            winningSolver != msg.sender
                || !auctionSettled
                || auctionConsumed
                || winningHash != solutionHash
        ) revert NotWinningSolver();

        (
            address requiredSettlementToken,
            uint128 maxPrincipal,
            uint128 minTreasuryRevenue,
            uint32 minEdgePpm,
            uint16 minTreasuryShareBps,
            ,
            uint64 expiryBlock,
            bytes32 venuesHash,
            bool published,
            bool opportunitySettled
        ) = auction.opportunityDetails(epoch);

        if (
            !published
                || !opportunitySettled
                || block.number > expiryBlock
                || requiredSettlementToken != settlementToken
                || principal > maxPrincipal
                || treasuryShareBps < minTreasuryShareBps
                || venuesHash == bytes32(0)
        ) revert AuctionTermsMismatch();

        if (hashRoute(epoch, settlementToken, principal, steps) != solutionHash) {
            revert InvalidRoute();
        }

        uint256 settlementBalanceBefore = IERC20(settlementToken).balanceOf(address(this));
        IERC20(settlementToken).safeTransferFrom(msg.sender, address(this), principal);

        address currentToken = settlementToken;
        uint256 currentAmount = principal;

        for (uint256 i = 0; i < steps.length; ++i) {
            Step calldata step = steps[i];
            bytes32 expectedCodehash = allowedAdapterCodehash[step.adapter];
            if (
                expectedCodehash == bytes32(0)
                    || step.adapter.codehash != expectedCodehash
            ) revert AdapterNotAllowed();
            if (
                step.tokenIn != currentToken
                    || step.tokenOut == address(0)
                    || step.tokenOut == step.tokenIn
                    || step.minAmountOut == 0
            ) revert InvalidRoute();

            uint256 tokenInBefore = IERC20(step.tokenIn).balanceOf(address(this));
            uint256 tokenOutBefore = IERC20(step.tokenOut).balanceOf(address(this));
            if (tokenInBefore < currentAmount) revert TokenFlowMismatch();

            IERC20(step.tokenIn).forceApprove(step.adapter, currentAmount);
            uint256 reportedAmountOut = ISwapAdapterV151(step.adapter).swap(
                step.tokenIn,
                step.tokenOut,
                currentAmount,
                step.minAmountOut,
                address(this),
                step.data
            );
            IERC20(step.tokenIn).forceApprove(step.adapter, 0);

            uint256 tokenInAfter = IERC20(step.tokenIn).balanceOf(address(this));
            uint256 tokenOutAfter = IERC20(step.tokenOut).balanceOf(address(this));
            if (
                tokenInBefore - tokenInAfter != currentAmount
                    || tokenOutAfter < tokenOutBefore
                    || tokenOutAfter - tokenOutBefore != reportedAmountOut
                    || reportedAmountOut < step.minAmountOut
            ) revert TokenFlowMismatch();

            currentToken = step.tokenOut;
            currentAmount = reportedAmountOut;
        }

        if (currentToken != settlementToken || currentAmount <= principal) {
            revert InsufficientExternalEdge();
        }

        uint256 grossProfit = currentAmount - principal;
        uint256 edgePpm = grossProfit * PPM / principal;
        treasuryRevenue = grossProfit * treasuryShareBps / BPS;
        solverRevenue = grossProfit - treasuryRevenue;

        if (
            edgePpm < minEdgePpm
                || treasuryRevenue < minTreasuryRevenue
                || solverRevenue == 0
        ) revert InsufficientExternalEdge();

        auction.consumeWinningSolution(epoch, solutionHash);
        IERC20(settlementToken).safeTransfer(msg.sender, principal + solverRevenue);
        IERC20(settlementToken).safeTransfer(treasury, treasuryRevenue);

        if (IERC20(settlementToken).balanceOf(address(this)) != settlementBalanceBefore) {
            revert TokenFlowMismatch();
        }

        cumulativeTreasuryRevenue[settlementToken] += treasuryRevenue;
        cumulativeSolverRevenue[settlementToken] += solverRevenue;

        emit ExternalRevenueCaptured(
            epoch,
            solutionHash,
            msg.sender,
            settlementToken,
            principal,
            currentAmount,
            grossProfit,
            treasuryRevenue,
            solverRevenue,
            edgePpm,
            treasuryShareBps,
            venuesHash
        );
    }
}
