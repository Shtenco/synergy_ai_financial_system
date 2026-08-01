// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @notice Deterministic solver auction for the V15 fork proof.
/// It preserves funded competitive bids, losing-bid refunds, treasury settlement
/// and single-use solution consumption without depending on long block epochs.
contract OrderflowAuctionV15 {
    address public immutable treasury;
    address public immutable coordinator;
    address public consumer;

    struct Bid {
        address solver;
        uint128 amount;
        bytes32 solutionHash;
        bool settled;
    }

    struct Opportunity {
        address settlement;
        address loanToken;
        uint128 maxNotional;
        uint128 minProfit;
        bytes32 venuesHash;
        string metadataURI;
    }

    mapping(uint256 => Bid) public best;
    mapping(uint256 => Opportunity) public opportunities;
    mapping(uint256 => uint256) public bidCount;
    mapping(address => uint256) public refunds;
    mapping(uint256 => bool) public consumed;

    uint256 public nextEpoch;
    uint256 public activeEpoch;
    bool public auctionOpen;

    error AuctionClosed();
    error BidTooLow();

    event AuctionAnnounced(
        uint256 indexed epoch,
        address indexed settlement,
        address indexed loanToken,
        uint256 maxNotional,
        uint256 minProfit,
        bytes32 venuesHash,
        string metadataURI
    );
    event BidPlaced(uint256 indexed epoch, address indexed solver, uint256 amount, bytes32 solutionHash);
    event Settled(uint256 indexed epoch, address indexed solver, uint256 revenue, bytes32 solutionHash);

    constructor(address treasury_, address coordinator_) {
        require(treasury_ != address(0) && coordinator_ != address(0), "zero address");
        treasury = treasury_;
        coordinator = coordinator_;
    }

    function setConsumer(address next) external {
        if (msg.sender != treasury || consumer != address(0) || next == address(0)) {
            revert AuctionClosed();
        }
        consumer = next;
    }

    function currentEpoch() public view returns (uint256) {
        return auctionOpen ? activeEpoch : nextEpoch;
    }

    function publish(
        address settlement,
        address loanToken,
        uint128 maxNotional,
        uint128 minProfit,
        bytes32 venuesHash,
        string calldata metadataURI
    ) external returns (uint256 epoch) {
        if (
            msg.sender != coordinator
                || auctionOpen
                || settlement == address(0)
                || loanToken == address(0)
        ) revert AuctionClosed();

        epoch = nextEpoch;
        nextEpoch = epoch + 1;
        activeEpoch = epoch;
        auctionOpen = true;
        opportunities[epoch] = Opportunity(
            settlement,
            loanToken,
            maxNotional,
            minProfit,
            venuesHash,
            metadataURI
        );
        emit AuctionAnnounced(
            epoch,
            settlement,
            loanToken,
            maxNotional,
            minProfit,
            venuesHash,
            metadataURI
        );
    }

    function bid(bytes32 solutionHash) external payable {
        if (!auctionOpen) revert AuctionClosed();
        uint256 epoch = activeEpoch;
        Bid storage previous = best[epoch];
        if (
            solutionHash == bytes32(0)
                || msg.value <= previous.amount
                || msg.value > type(uint128).max
        ) revert BidTooLow();

        if (previous.solver != address(0)) {
            refunds[previous.solver] += previous.amount;
        }
        best[epoch] = Bid(msg.sender, uint128(msg.value), solutionHash, false);
        bidCount[epoch] += 1;
        emit BidPlaced(epoch, msg.sender, msg.value, solutionHash);
    }

    function settle(uint256 epoch) external {
        if (
            msg.sender != coordinator
                || !auctionOpen
                || epoch != activeEpoch
                || bidCount[epoch] < 3
        ) revert AuctionClosed();

        Bid storage winning = best[epoch];
        if (winning.solver == address(0) || winning.settled) revert AuctionClosed();
        winning.settled = true;
        auctionOpen = false;
        (bool ok,) = treasury.call{value: winning.amount}("");
        require(ok, "treasury transfer failed");
        emit Settled(epoch, winning.solver, winning.amount, winning.solutionHash);
    }

    function isWinningSolution(uint256 epoch, bytes32 solutionHash) external view returns (bool) {
        Bid memory winning = best[epoch];
        return winning.settled && !consumed[epoch] && winning.solutionHash == solutionHash;
    }

    function consumeWinningSolution(uint256 epoch, bytes32 solutionHash) external {
        if (msg.sender != consumer || consumed[epoch]) revert AuctionClosed();
        Bid memory winning = best[epoch];
        if (!winning.settled || winning.solutionHash != solutionHash) revert AuctionClosed();
        consumed[epoch] = true;
    }

    function withdrawRefund() external {
        uint256 amount = refunds[msg.sender];
        refunds[msg.sender] = 0;
        (bool ok,) = msg.sender.call{value: amount}("");
        require(ok, "refund failed");
    }
}
