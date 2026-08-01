// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @notice V15.1 solver auction. Bonds are refundable security and are never
/// counted as execution revenue. Solvers compete by offering treasury a larger
/// share of profit that the external route actually realizes.
contract SolverAuctionV151 is ReentrancyGuard {
    uint256 public constant BPS = 10_000;
    uint16 public constant MAX_TREASURY_SHARE_BPS = 9_500;

    struct Opportunity {
        address settlementToken;
        uint128 maxPrincipal;
        uint128 minTreasuryRevenue;
        uint32 minEdgePpm;
        uint16 minTreasuryShareBps;
        uint64 closeBlock;
        uint64 expiryBlock;
        bytes32 venuesHash;
        bool published;
        bool settled;
    }

    struct WinningBid {
        address solver;
        uint128 bond;
        uint16 treasuryShareBps;
        bytes32 solutionHash;
    }

    address public immutable treasury;
    address public immutable coordinator;
    uint128 public immutable minimumBondWei;
    address public consumer;
    uint256 public currentEpoch;

    mapping(uint256 epoch => Opportunity opportunity) private opportunities;
    mapping(uint256 epoch => WinningBid winningBid) private winners;
    mapping(uint256 epoch => mapping(address solver => bool submitted)) public submitted;
    mapping(uint256 epoch => bool consumed) public consumed;
    mapping(address account => uint256 amount) public refunds;

    error Unauthorized();
    error InvalidOpportunity();
    error InvalidBid();
    error AuctionNotOpen();
    error AuctionNotClosable();
    error AuctionNotSettled();
    error AlreadyConsumed();
    error InvalidSolution();
    error TransferFailed();

    event ConsumerSet(address indexed consumer);
    event OpportunityPublished(
        uint256 indexed epoch,
        address indexed settlementToken,
        uint256 maxPrincipal,
        uint256 minTreasuryRevenue,
        uint256 minEdgePpm,
        uint256 minTreasuryShareBps,
        uint256 closeBlock,
        uint256 expiryBlock,
        bytes32 venuesHash
    );
    event BidSubmitted(
        uint256 indexed epoch,
        address indexed solver,
        uint256 treasuryShareBps,
        uint256 bond,
        bytes32 indexed solutionHash,
        bool leading
    );
    event AuctionSettled(
        uint256 indexed epoch,
        address indexed solver,
        uint256 treasuryShareBps,
        uint256 bond,
        bytes32 indexed solutionHash
    );
    event WinningSolutionConsumed(uint256 indexed epoch, bytes32 indexed solutionHash);
    event UnexecutedWinnerSlashed(uint256 indexed epoch, address indexed solver, uint256 bond);
    event RefundWithdrawn(address indexed account, uint256 amount);

    constructor(address treasury_, address coordinator_, uint128 minimumBondWei_) {
        if (treasury_ == address(0) || coordinator_ == address(0) || minimumBondWei_ == 0) {
            revert InvalidOpportunity();
        }
        treasury = treasury_;
        coordinator = coordinator_;
        minimumBondWei = minimumBondWei_;
    }

    function setConsumer(address consumer_) external {
        if (msg.sender != treasury || consumer != address(0) || consumer_ == address(0)) {
            revert Unauthorized();
        }
        consumer = consumer_;
        emit ConsumerSet(consumer_);
    }

    function publish(
        address settlementToken,
        uint128 maxPrincipal,
        uint128 minTreasuryRevenue,
        uint32 minEdgePpm,
        uint16 minTreasuryShareBps,
        uint64 closeBlock,
        uint64 expiryBlock,
        bytes32 venuesHash
    ) external returns (uint256 epoch) {
        if (msg.sender != coordinator) revert Unauthorized();
        if (
            settlementToken == address(0)
                || maxPrincipal == 0
                || minTreasuryRevenue == 0
                || minEdgePpm == 0
                || minTreasuryShareBps == 0
                || minTreasuryShareBps > MAX_TREASURY_SHARE_BPS
                || closeBlock <= block.number
                || expiryBlock <= closeBlock
                || venuesHash == bytes32(0)
        ) revert InvalidOpportunity();

        epoch = ++currentEpoch;
        opportunities[epoch] = Opportunity({
            settlementToken: settlementToken,
            maxPrincipal: maxPrincipal,
            minTreasuryRevenue: minTreasuryRevenue,
            minEdgePpm: minEdgePpm,
            minTreasuryShareBps: minTreasuryShareBps,
            closeBlock: closeBlock,
            expiryBlock: expiryBlock,
            venuesHash: venuesHash,
            published: true,
            settled: false
        });

        emit OpportunityPublished(
            epoch,
            settlementToken,
            maxPrincipal,
            minTreasuryRevenue,
            minEdgePpm,
            minTreasuryShareBps,
            closeBlock,
            expiryBlock,
            venuesHash
        );
    }

    function bid(
        uint256 epoch,
        bytes32 solutionHash,
        uint16 treasuryShareBps
    ) external payable nonReentrant {
        Opportunity storage opportunity_ = opportunities[epoch];
        if (
            !opportunity_.published
                || opportunity_.settled
                || block.number > opportunity_.closeBlock
        ) revert AuctionNotOpen();
        if (
            submitted[epoch][msg.sender]
                || solutionHash == bytes32(0)
                || msg.value < minimumBondWei
                || msg.value > type(uint128).max
                || treasuryShareBps < opportunity_.minTreasuryShareBps
                || treasuryShareBps > MAX_TREASURY_SHARE_BPS
        ) revert InvalidBid();

        submitted[epoch][msg.sender] = true;
        WinningBid storage current = winners[epoch];
        bool leading = current.solver == address(0)
            || treasuryShareBps > current.treasuryShareBps
            || (
                treasuryShareBps == current.treasuryShareBps
                    && msg.value > current.bond
            );

        if (leading) {
            if (current.solver != address(0)) {
                refunds[current.solver] += current.bond;
            }
            winners[epoch] = WinningBid({
                solver: msg.sender,
                bond: uint128(msg.value),
                treasuryShareBps: treasuryShareBps,
                solutionHash: solutionHash
            });
        } else {
            refunds[msg.sender] += msg.value;
        }

        emit BidSubmitted(
            epoch,
            msg.sender,
            treasuryShareBps,
            msg.value,
            solutionHash,
            leading
        );
    }

    function settle(uint256 epoch) external {
        Opportunity storage opportunity_ = opportunities[epoch];
        WinningBid storage winner = winners[epoch];
        if (
            !opportunity_.published
                || opportunity_.settled
                || winner.solver == address(0)
                || block.number <= opportunity_.closeBlock
                || block.number > opportunity_.expiryBlock
        ) revert AuctionNotClosable();
        opportunity_.settled = true;
        emit AuctionSettled(
            epoch,
            winner.solver,
            winner.treasuryShareBps,
            winner.bond,
            winner.solutionHash
        );
    }

    function consumeWinningSolution(uint256 epoch, bytes32 solutionHash) external {
        if (msg.sender != consumer) revert Unauthorized();
        Opportunity storage opportunity_ = opportunities[epoch];
        WinningBid storage winner = winners[epoch];
        if (!opportunity_.settled || block.number > opportunity_.expiryBlock) {
            revert AuctionNotSettled();
        }
        if (consumed[epoch]) revert AlreadyConsumed();
        if (winner.solutionHash != solutionHash) revert InvalidSolution();

        consumed[epoch] = true;
        uint256 bond = winner.bond;
        winner.bond = 0;
        refunds[winner.solver] += bond;
        emit WinningSolutionConsumed(epoch, solutionHash);
    }

    function slashExpiredWinner(uint256 epoch) external nonReentrant {
        Opportunity storage opportunity_ = opportunities[epoch];
        WinningBid storage winner = winners[epoch];
        if (
            !opportunity_.settled
                || consumed[epoch]
                || block.number <= opportunity_.expiryBlock
                || winner.solver == address(0)
                || winner.bond == 0
        ) revert AuctionNotClosable();

        consumed[epoch] = true;
        uint256 bond = winner.bond;
        winner.bond = 0;
        (bool paid,) = treasury.call{value: bond}("");
        if (!paid) revert TransferFailed();
        emit UnexecutedWinnerSlashed(epoch, winner.solver, bond);
    }

    function withdrawRefund() external nonReentrant {
        uint256 amount = refunds[msg.sender];
        if (amount == 0) revert InvalidBid();
        refunds[msg.sender] = 0;
        (bool paid,) = msg.sender.call{value: amount}("");
        if (!paid) revert TransferFailed();
        emit RefundWithdrawn(msg.sender, amount);
    }

    function best(uint256 epoch)
        external
        view
        returns (
            address solver,
            uint128 bond,
            uint16 treasuryShareBps,
            bytes32 solutionHash,
            bool settled,
            bool isConsumed
        )
    {
        WinningBid storage winner = winners[epoch];
        Opportunity storage opportunity_ = opportunities[epoch];
        return (
            winner.solver,
            winner.bond,
            winner.treasuryShareBps,
            winner.solutionHash,
            opportunity_.settled,
            consumed[epoch]
        );
    }

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
        )
    {
        Opportunity storage opportunity_ = opportunities[epoch];
        return (
            opportunity_.settlementToken,
            opportunity_.maxPrincipal,
            opportunity_.minTreasuryRevenue,
            opportunity_.minEdgePpm,
            opportunity_.minTreasuryShareBps,
            opportunity_.closeBlock,
            opportunity_.expiryBlock,
            opportunity_.venuesHash,
            opportunity_.published,
            opportunity_.settled
        );
    }
}
