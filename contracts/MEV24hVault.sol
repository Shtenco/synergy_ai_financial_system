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
    address public immutable governor;
    mapping(address => bool) public routers;

    struct Position { address token; address beneficiary; uint128 amount; uint64 unlockAt; bool claimed; }
    Position[] public positions;
    error Unauthorized();
    error Locked();

    constructor(address governor_) { governor = governor_; }

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
        if (msg.sender != p.beneficiary) revert Unauthorized();
        if (block.timestamp < p.unlockAt) revert Locked();
        p.claimed = true;
        IERC20(p.token).safeTransfer(p.beneficiary, p.amount);
    }

    function earlyExitAndBurn(uint256 id, address burnSink) external {
        Position storage p = positions[id];
        if (msg.sender != p.beneficiary || p.claimed) revert Unauthorized();
        p.claimed = true;
        uint256 burned = uint256(p.amount) * EARLY_BURN_BPS / 10_000;
        IERC20(p.token).safeTransfer(burnSink, burned);
        IERC20(p.token).safeTransfer(p.beneficiary, uint256(p.amount) - burned);
    }
}
