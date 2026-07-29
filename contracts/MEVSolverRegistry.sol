// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

/// @notice Bonded solver registry with objective commit/reveal expiry slashing.
/// @dev Native POL is used as the bond on Polygon. Solvers keep custody of the
/// remainder and can exit after a cooldown when no commitment is outstanding.
contract MEVSolverRegistry {
    uint64 public constant MIN_REVEAL_BLOCKS = 2;
    uint64 public constant MAX_REVEAL_BLOCKS = 120;
    uint64 public constant EXIT_DELAY = 24 hours;

    struct Solver {
        uint128 bond;
        uint64 exitAfter;
        bool active;
    }

    struct Commitment {
        bytes32 digest;
        uint64 blockNumber;
        uint128 lockedBond;
    }

    address public immutable governor;
    address public immutable treasury;
    uint128 public immutable minBond;
    mapping(address => Solver) public solvers;
    mapping(address => Commitment) public commitments;
    mapping(address => bool) public routers;
    bool private entered;

    error Unauthorized();
    error InvalidBond();
    error InvalidCommitment();
    error ExitLocked();
    error TransferFailed();

    event RouterSet(address indexed router, bool enabled);
    event SolverRegistered(address indexed solver, uint256 bond);
    event BondAdded(address indexed solver, uint256 amount, uint256 totalBond);
    event ExitRequested(address indexed solver, uint256 exitAfter);
    event BondWithdrawn(address indexed solver, uint256 amount);
    event RouteCommitted(address indexed solver, bytes32 indexed digest, uint256 lockedBond);
    event RouteConsumed(address indexed solver, bytes32 indexed routeHash);
    event CommitmentSlashed(address indexed solver, uint256 amount);

    constructor(address governor_, address treasury_, uint128 minBond_) {
        if (governor_ == address(0) || treasury_ == address(0) || minBond_ == 0) revert InvalidBond();
        governor = governor_;
        treasury = treasury_;
        minBond = minBond_;
    }

    modifier nonReentrant() {
        if (entered) revert Unauthorized();
        entered = true;
        _;
        entered = false;
    }

    function setRouter(address router, bool enabled) external {
        if (msg.sender != governor) revert Unauthorized();
        if (router == address(0)) revert Unauthorized();
        routers[router] = enabled;
        emit RouterSet(router, enabled);
    }

    function register() external payable {
        Solver storage solver = solvers[msg.sender];
        if (solver.active || msg.value < minBond || uint256(solver.bond) + msg.value > type(uint128).max) {
            revert InvalidBond();
        }
        solver.bond += uint128(msg.value);
        solver.exitAfter = 0;
        solver.active = true;
        emit SolverRegistered(msg.sender, solver.bond);
    }

    function addBond() external payable {
        Solver storage solver = solvers[msg.sender];
        if (msg.value == 0 || uint256(solver.bond) + msg.value > type(uint128).max) revert InvalidBond();
        solver.bond += uint128(msg.value);
        if (!solver.active && solver.exitAfter == 0 && solver.bond >= minBond) solver.active = true;
        emit BondAdded(msg.sender, msg.value, solver.bond);
    }

    function requestExit() external {
        Solver storage solver = solvers[msg.sender];
        if (!solver.active) revert Unauthorized();
        solver.active = false;
        solver.exitAfter = uint64(block.timestamp + EXIT_DELAY);
        emit ExitRequested(msg.sender, solver.exitAfter);
    }

    function withdrawBond(uint256 amount) external nonReentrant {
        Solver storage solver = solvers[msg.sender];
        if (
            solver.active || solver.exitAfter == 0 || block.timestamp < solver.exitAfter
                || commitments[msg.sender].digest != bytes32(0) || amount == 0 || amount > solver.bond
        ) revert ExitLocked();
        solver.bond -= uint128(amount);
        if (solver.bond == 0) solver.exitAfter = 0;
        _sendNative(msg.sender, amount);
        emit BondWithdrawn(msg.sender, amount);
    }

    function commit(bytes32 digest, uint128 lockAmount) external {
        Solver memory solver = solvers[msg.sender];
        if (
            !solver.active || solver.bond < minBond || digest == bytes32(0)
                || commitments[msg.sender].digest != bytes32(0) || lockAmount < minBond
                || lockAmount > solver.bond
        ) revert InvalidCommitment();
        commitments[msg.sender] = Commitment(digest, uint64(block.number), lockAmount);
        emit RouteCommitted(msg.sender, digest, lockAmount);
    }

    function consumeCommitment(address solver, bytes32 routeHash, bytes32 salt, uint64 deadline)
        external
        returns (uint256 lockedBond)
    {
        if (!routers[msg.sender]) revert Unauthorized();
        Commitment memory c = commitments[solver];
        if (
            c.digest != keccak256(abi.encode(solver, routeHash, salt, deadline))
                || block.number < c.blockNumber + MIN_REVEAL_BLOCKS
                || block.number > c.blockNumber + MAX_REVEAL_BLOCKS || block.timestamp > deadline
                || !solvers[solver].active
        ) revert InvalidCommitment();
        delete commitments[solver];
        lockedBond = c.lockedBond;
        emit RouteConsumed(solver, routeHash);
    }

    function slashExpired(address solver) external nonReentrant {
        Commitment memory c = commitments[solver];
        if (c.digest == bytes32(0) || block.number <= c.blockNumber + MAX_REVEAL_BLOCKS) {
            revert InvalidCommitment();
        }
        delete commitments[solver];
        Solver storage record = solvers[solver];
        uint256 amount = c.lockedBond > record.bond ? record.bond : c.lockedBond;
        record.bond -= uint128(amount);
        if (record.bond < minBond) {
            record.active = false;
            record.exitAfter = uint64(block.timestamp + EXIT_DELAY);
        }
        _sendNative(treasury, amount);
        emit CommitmentSlashed(solver, amount);
    }

    function isActive(address solver) external view returns (bool) {
        Solver memory record = solvers[solver];
        return record.active && record.bond >= minBond;
    }

    function _sendNative(address to, uint256 amount) private {
        (bool ok,) = to.call{value: amount}("");
        if (!ok) revert TransferFailed();
    }
}
