// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/// @notice Opt-in trade-output escrow. It mitigates rapid extraction on routes
/// integrated with this vault; it cannot identify or stop all MEV globally.
contract MEV24hVault {
    using SafeERC20 for IERC20;
    uint64 public constant VESTING = 24 hours;
    uint16 public constant EARLY_BURN_BPS = 4_000;
    uint64 public constant MIN_REVEAL_BLOCKS = 2;
    uint64 public constant MAX_REVEAL_BLOCKS = 120;
    uint256 public constant MIN_SOLVER_BOND = 1 ether;
    address public constant BURN_SINK = 0x000000000000000000000000000000000000dEaD;
    address public immutable governor;
    address public immutable treasury;
    mapping(address => bool) public routers;

    struct Position { address token; address beneficiary; uint128 amount; uint64 unlockAt; bool claimed; }
    Position[] public positions;
    struct Commitment { bytes32 digest; uint64 blockNumber; uint128 bond; }
    mapping(address => Commitment) public commitments;
    error Unauthorized();
    error Locked();
    error InvalidCommitment();
    event SolverCommitted(address indexed solver, bytes32 indexed digest, uint256 bond);
    event SolverRevealed(address indexed solver, bytes32 indexed routeHash);
    event SolverSlashed(address indexed solver, uint256 bond);

    constructor(address governor_, address treasury_) {
        require(governor_ != address(0) && treasury_ != address(0));
        governor = governor_;
        treasury = treasury_;
    }

    function setRouter(address router, bool enabled) external {
        if (msg.sender != governor) revert Unauthorized();
        routers[router] = enabled;
    }

    function lock(address token, address beneficiary, uint128 amount) external returns (uint256 id) {
        if (!routers[msg.sender]) revert Unauthorized();
        IERC20(token).safeTransferFrom(msg.sender, address(this), amount);
        id = positions.length;
        positions.push(Position(token, beneficiary, amount, uint64(block.timestamp + VESTING), false));
    }

    function claim(uint256 id) external {
        Position storage p = positions[id];
        if (msg.sender != p.beneficiary || p.claimed) revert Unauthorized();
        if (block.timestamp < p.unlockAt) revert Locked();
        p.claimed = true;
        IERC20(p.token).safeTransfer(p.beneficiary, p.amount);
    }

    function earlyExitAndBurn(uint256 id) external {
        Position storage p = positions[id];
        if (msg.sender != p.beneficiary || p.claimed) revert Unauthorized();
        p.claimed = true;
        uint256 burned = uint256(p.amount) * EARLY_BURN_BPS / 10_000;
        IERC20(p.token).safeTransfer(BURN_SINK, burned);
        IERC20(p.token).safeTransfer(p.beneficiary, uint256(p.amount) - burned);
    }

    /// @notice Solvers voluntarily bond before revealing a route. This hides
    /// actionable calldata for at least two blocks; it does not slash observers.
    function commit(bytes32 digest) external payable {
        if (
            msg.value < MIN_SOLVER_BOND || msg.value > type(uint128).max
                || commitments[msg.sender].digest != bytes32(0)
        ) {
            revert InvalidCommitment();
        }
        commitments[msg.sender] = Commitment(digest, uint64(block.number), uint128(msg.value));
        emit SolverCommitted(msg.sender, digest, msg.value);
    }

    function reveal(bytes32 routeHash, bytes32 salt, uint64 deadline) external {
        Commitment memory c = commitments[msg.sender];
        if (
            c.digest != keccak256(abi.encode(msg.sender, routeHash, salt, deadline))
                || block.number < c.blockNumber + MIN_REVEAL_BLOCKS
                || block.number > c.blockNumber + MAX_REVEAL_BLOCKS
                || block.timestamp > deadline
        ) revert InvalidCommitment();
        delete commitments[msg.sender];
        (bool ok,) = msg.sender.call{value: c.bond}("");
        require(ok, "bond refund failed");
        emit SolverRevealed(msg.sender, routeHash);
    }

    /// @notice Anyone can move an objectively expired solver bond to treasury.
    function slashExpired(address solver) external {
        Commitment memory c = commitments[solver];
        if (c.digest == bytes32(0) || block.number <= c.blockNumber + MAX_REVEAL_BLOCKS) {
            revert InvalidCommitment();
        }
        delete commitments[solver];
        (bool ok,) = treasury.call{value: c.bond}("");
        require(ok, "slash transfer failed");
        emit SolverSlashed(solver, c.bond);
    }
}
