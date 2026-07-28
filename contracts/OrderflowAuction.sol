// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @notice Transparent, voluntary solver auction. Searchers pay POL for the
/// right to supply a route; no trader funds are confiscated or trapped.
contract OrderflowAuction {
    uint64 public constant EPOCH_BLOCKS = 64;
    uint64 public constant PUBLISH_WINDOW_BLOCKS = 8;
    address public immutable treasury;
    address public immutable coordinator;
    address public consumer;
    struct Bid { address solver; uint128 amount; bytes32 solutionHash; bool settled; }
    mapping(uint256 => Bid) public best;
    mapping(address => uint256) public refunds;
    mapping(uint256 => bool) public consumed;
    struct Opportunity {
        address settlement;
        address loanToken;
        uint128 maxNotional;
        uint128 minProfit;
        bytes32 venuesHash;
        string metadataURI;
    }
    mapping(uint256 => Opportunity) public opportunities;

    error AuctionClosed();
    error BidTooLow();
    event BidPlaced(uint256 indexed epoch, address indexed solver, uint256 amount, bytes32 solutionHash);
    event Settled(uint256 indexed epoch, address indexed solver, uint256 revenue, bytes32 solutionHash);
    event AuctionAnnounced(
        uint256 indexed epoch, address indexed settlement, address indexed loanToken,
        uint256 maxNotional, uint256 minProfit, uint256 closeBlock, bytes32 venuesHash, string metadataURI
    );

    constructor(address treasury_, address coordinator_) {
        require(treasury_ != address(0) && coordinator_ != address(0));
        treasury = treasury_; coordinator = coordinator_;
    }

    function setConsumer(address next) external {
        if (msg.sender != treasury || consumer != address(0) || next == address(0)) revert AuctionClosed();
        consumer = next;
    }

    function currentEpoch() public view returns (uint256) { return block.number / EPOCH_BLOCKS; }

    function publish(
        address settlement, address loanToken, uint128 maxNotional, uint128 minProfit,
        bytes32 venuesHash, string calldata metadataURI
    ) external returns (uint256 epoch) {
        if (msg.sender != coordinator || settlement == address(0) || loanToken == address(0)) revert AuctionClosed();
        epoch = currentEpoch();
        if (block.number % EPOCH_BLOCKS > PUBLISH_WINDOW_BLOCKS) revert AuctionClosed();
        if (opportunities[epoch].settlement != address(0)) revert AuctionClosed();
        opportunities[epoch] = Opportunity(
            settlement, loanToken, maxNotional, minProfit, venuesHash, metadataURI
        );
        emit AuctionAnnounced(
            epoch, settlement, loanToken, maxNotional, minProfit,
            (epoch + 1) * EPOCH_BLOCKS, venuesHash, metadataURI
        );
    }

    function bid(bytes32 solutionHash) external payable {
        uint256 epoch = currentEpoch();
        if (opportunities[epoch].settlement == address(0)) revert AuctionClosed();
        Bid storage previous = best[epoch];
        if (solutionHash == bytes32(0) || msg.value <= previous.amount || msg.value > type(uint128).max) revert BidTooLow();
        if (previous.solver != address(0)) refunds[previous.solver] += previous.amount;
        best[epoch] = Bid(msg.sender, uint128(msg.value), solutionHash, false);
        emit BidPlaced(epoch, msg.sender, msg.value, solutionHash);
    }

    function settle(uint256 epoch) external {
        if (epoch >= currentEpoch()) revert AuctionClosed();
        Bid storage winning = best[epoch];
        if (winning.solver == address(0) || winning.settled) revert AuctionClosed();
        winning.settled = true;
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
