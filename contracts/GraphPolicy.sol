// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @notice Timelocked, bounded policy queue. "AI" scoring is supplied by an
/// off-chain simulator; this contract only enforces measurable LNAV improvement.
contract GraphPolicy {
    enum Action { Hold, Buyback, SellReserve, RecycleLiquidity, FlashArbitrage }
    struct Proposal {
        Action action;
        address target;
        uint256 amount;
        uint256 minOut;
        uint256 baselineLnav;
        uint256 expectedLnav;
        uint64 executableAt;
        uint64 expiresAt;
        bool executed;
    }

    uint64 public constant MIN_DELAY = 1 hours;
    uint64 public constant MAX_WINDOW = 24 hours;
    address public immutable governor;
    address public operator;
    uint256 public nonce;
    mapping(uint256 => Proposal) public proposals;
    mapping(address => bool) public consumers;

    event Proposed(uint256 indexed id, Action action, uint256 baselineLnav, uint256 expectedLnav);
    event Executed(uint256 indexed id);

    error Unauthorized();
    error NoImprovement();
    error InvalidWindow();
    error NotExecutable();

    constructor(address governor_, address operator_) {
        require(governor_ != address(0) && operator_ != address(0));
        governor = governor_;
        operator = operator_;
    }

    function setOperator(address next) external {
        if (msg.sender != governor) revert Unauthorized();
        require(next != address(0));
        operator = next;
    }

    function setConsumer(address consumer, bool enabled) external {
        if (msg.sender != governor) revert Unauthorized();
        consumers[consumer] = enabled;
    }

    function propose(
        Action action,
        address target,
        uint256 amount,
        uint256 minOut,
        uint256 baselineLnav,
        uint256 expectedLnav,
        uint64 delay
    ) external returns (uint256 id) {
        if (msg.sender != operator) revert Unauthorized();
        if (expectedLnav <= baselineLnav) revert NoImprovement();
        if (delay < MIN_DELAY) revert InvalidWindow();
        id = ++nonce;
        uint64 executableAt = uint64(block.timestamp) + delay;
        proposals[id] = Proposal({
            action: action, target: target, amount: amount, minOut: minOut,
            baselineLnav: baselineLnav, expectedLnav: expectedLnav,
            executableAt: executableAt, expiresAt: executableAt + MAX_WINDOW,
            executed: false
        });
        emit Proposed(id, action, baselineLnav, expectedLnav);
    }

    function consume(uint256 id, address executor) external returns (Proposal memory proposal) {
        proposal = proposals[id];
        if (!consumers[msg.sender] || executor != proposal.target) revert Unauthorized();
        if (proposal.executed || block.timestamp < proposal.executableAt || block.timestamp > proposal.expiresAt) {
            revert NotExecutable();
        }
        proposals[id].executed = true;
        emit Executed(id);
    }
}
