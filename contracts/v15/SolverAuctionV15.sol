// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @notice Explicit-close solver auction for the V15 fork proof. It avoids
/// artificial block advancement while preserving committed-solution bidding,
/// winner settlement, losing-bid refunds, treasury revenue and single-use execution.
contract SolverAuctionV15 {
    struct AuctionState {
        address tokenIn;
        address tokenOut;
        uint256 maxInput;
        uint256 minProfit;
        bytes32 venuesHash;
        string metadataUri;
        address solver;
        uint128 amount;
        bytes32 solutionHash;
        bool published;
        bool settled;
    }

    address public immutable treasury;
    address public immutable coordinator;
    address public consumer;
    uint256 public currentEpoch;

    mapping(uint256 epoch => AuctionState state) private auctions;
    mapping(uint256 epoch => bool) public consumed;
    mapping(uint256 epoch => mapping(address solver => uint256 bidAmount)) public bids;
    mapping(uint256 epoch => address[] bidders) private bidderList;

    error Unauthorized();
    error InvalidAuction();
    error InvalidBid();
    error AlreadySettled();
    error NotSettled();
    error AlreadyConsumed();
    error NotWinningSolution();
    error TransferFailed();

    event ConsumerSet(address indexed consumer);
    event AuctionPublished(
        uint256 indexed epoch,
        address indexed tokenIn,
        address indexed tokenOut,
        uint256 maxInput,
        uint256 minProfit,
        bytes32 venuesHash,
        string metadataUri
    );
    event BidSubmitted(
        uint256 indexed epoch,
        address indexed solver,
        uint256 amount,
        bytes32 indexed solutionHash
    );
    event BidRefunded(uint256 indexed epoch, address indexed solver, uint256 amount);
    event AuctionSettled(
        uint256 indexed epoch,
        address indexed solver,
        uint256 amount,
        bytes32 indexed solutionHash
    );
    event WinningSolutionConsumed(uint256 indexed epoch, bytes32 indexed solutionHash);

    constructor(address treasury_, address coordinator_) {
        if (treasury_ == address(0) || coordinator_ == address(0)) revert InvalidAuction();
        treasury = treasury_;
        coordinator = coordinator_;
    }

    function setConsumer(address consumer_) external {
        if (msg.sender != treasury) revert Unauthorized();
        if (consumer_ == address(0)) revert InvalidAuction();
        consumer = consumer_;
        emit ConsumerSet(consumer_);
    }

    function publish(
        address tokenIn,
        address tokenOut,
        uint256 maxInput,
        uint256 minProfit,
        bytes32 venuesHash,
        string calldata metadataUri
    ) external returns (uint256 epoch) {
        if (msg.sender != coordinator) revert Unauthorized();
        if (
            tokenIn == address(0)
                || tokenOut == address(0)
                || tokenIn == tokenOut
                || maxInput == 0
                || minProfit == 0
                || venuesHash == bytes32(0)
        ) revert InvalidAuction();
        epoch = currentEpoch + 1;
        currentEpoch = epoch;
        auctions[epoch] = AuctionState({
            tokenIn: tokenIn,
            tokenOut: tokenOut,
            maxInput: maxInput,
            minProfit: minProfit,
            venuesHash: venuesHash,
            metadataUri: metadataUri,
            solver: address(0),
            amount: 0,
            solutionHash: bytes32(0),
            published: true,
            settled: false
        });
        emit AuctionPublished(
            epoch,
            tokenIn,
            tokenOut,
            maxInput,
            minProfit,
            venuesHash,
            metadataUri
        );
    }

    function bid(bytes32 solutionHash) external payable {
        uint256 epoch = currentEpoch;
        AuctionState storage state = auctions[epoch];
        if (!state.published || state.settled) revert InvalidAuction();
        if (solutionHash == bytes32(0) || msg.value == 0 || msg.value > type(uint128).max) {
            revert InvalidBid();
        }
        if (bids[epoch][msg.sender] != 0) revert InvalidBid();
        bids[epoch][msg.sender] = msg.value;
        bidderList[epoch].push(msg.sender);
        if (msg.value > state.amount) {
            state.solver = msg.sender;
            state.amount = uint128(msg.value);
            state.solutionHash = solutionHash;
        }
        emit BidSubmitted(epoch, msg.sender, msg.value, solutionHash);
    }

    function settle(uint256 epoch) external {
        if (msg.sender != coordinator) revert Unauthorized();
        AuctionState storage state = auctions[epoch];
        if (!state.published || state.solver == address(0)) revert InvalidAuction();
        if (state.settled) revert AlreadySettled();
        state.settled = true;

        uint256 winningBid = state.amount;
        (bool paid,) = treasury.call{value: winningBid}("");
        if (!paid) revert TransferFailed();

        address[] storage epochBidders = bidderList[epoch];
        for (uint256 i = 0; i < epochBidders.length; i++) {
            address bidder = epochBidders[i];
            if (bidder == state.solver) continue;
            uint256 refund = bids[epoch][bidder];
            if (refund == 0) continue;
            bids[epoch][bidder] = 0;
            (bool refunded,) = bidder.call{value: refund}("");
            if (!refunded) revert TransferFailed();
            emit BidRefunded(epoch, bidder, refund);
        }

        emit AuctionSettled(epoch, state.solver, winningBid, state.solutionHash);
    }

    function best(uint256 epoch)
        external
        view
        returns (address solver, uint128 amount, bytes32 solutionHash, bool settled)
    {
        AuctionState storage state = auctions[epoch];
        return (state.solver, state.amount, state.solutionHash, state.settled);
    }

    function isWinningSolution(uint256 epoch, bytes32 solutionHash) external view returns (bool) {
        AuctionState storage state = auctions[epoch];
        return state.settled && !consumed[epoch] && state.solutionHash == solutionHash;
    }

    function consumeWinningSolution(uint256 epoch, bytes32 solutionHash) external {
        if (msg.sender != consumer) revert Unauthorized();
        AuctionState storage state = auctions[epoch];
        if (!state.settled) revert NotSettled();
        if (consumed[epoch]) revert AlreadyConsumed();
        if (state.solutionHash != solutionHash) revert NotWinningSolution();
        consumed[epoch] = true;
        emit WinningSolutionConsumed(epoch, solutionHash);
    }

    function bidderCount(uint256 epoch) external view returns (uint256) {
        return bidderList[epoch].length;
    }

    function auctionDetails(uint256 epoch)
        external
        view
        returns (
            address tokenIn,
            address tokenOut,
            uint256 maxInput,
            uint256 minProfit,
            bytes32 venuesHash,
            string memory metadataUri
        )
    {
        AuctionState storage state = auctions[epoch];
        return (
            state.tokenIn,
            state.tokenOut,
            state.maxInput,
            state.minProfit,
            state.venuesHash,
            state.metadataUri
        );
    }
}
