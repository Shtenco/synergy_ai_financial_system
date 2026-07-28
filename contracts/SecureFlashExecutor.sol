// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {GraphPolicy} from "./GraphPolicy.sol";

interface IERC3156Lender {
    function flashLoan(address receiver, address token, uint256 amount, bytes calldata data) external returns (bool);
}
interface IPriceGuard { function latestPrice() external view returns (uint256 price, uint256 updatedAt); }

/// @notice ERC-3156 lender-specific executor that atomically consumes policy,
/// validates TWAP freshness/deviation, repays principal+fee, and retains profit.
contract SecureFlashExecutor {
    using SafeERC20 for IERC20;
    bytes32 private constant CALLBACK_SUCCESS = keccak256("ERC3156FlashBorrower.onFlashLoan");
    uint256 public constant MAX_ORACLE_AGE = 15 minutes;
    uint256 public constant MAX_DEVIATION_BPS = 300;
    uint256 public constant PROFIT_TAX_BPS = 2_000;

    address public immutable controller;
    address public immutable guardian;
    address public immutable treasury;
    IERC3156Lender public immutable lender;
    GraphPolicy public immutable policy;
    mapping(address => bytes32) public targetCodehash;
    bool public paused;
    bool private active;
    bytes32 private activeDataHash;
    uint256 public dailyLimit;
    uint256 public dailyUsed;
    uint64 public day;

    error Unauthorized();
    error InvalidCallback();
    error OracleUnsafe();
    error InsufficientProfit();

    constructor(
        address controller_, address guardian_, address treasury_,
        IERC3156Lender lender_, GraphPolicy policy_, uint256 dailyLimit_
    ) {
        require(controller_ != address(0) && guardian_ != address(0) && treasury_ != address(0));
        controller = controller_; guardian = guardian_; treasury = treasury_;
        lender = lender_; policy = policy_; dailyLimit = dailyLimit_;
    }

    function setPaused(bool next) external {
        if (msg.sender != guardian && msg.sender != controller) revert Unauthorized();
        paused = next;
    }

    function setTarget(address target, bool allowed) external {
        if (msg.sender != controller) revert Unauthorized();
        targetCodehash[target] = allowed ? target.codehash : bytes32(0);
    }

    function setDailyLimit(uint256 next) external {
        if (msg.sender != controller) revert Unauthorized();
        dailyLimit = next;
    }

    function start(
        uint256 proposalId, address token, uint256 amount, bytes calldata routeData
    ) external {
        if (msg.sender != controller || paused || active) revert Unauthorized();
        GraphPolicy.Proposal memory p = policy.consume(proposalId, msg.sender);
        require(p.action == GraphPolicy.Action.FlashArbitrage && p.amount == amount, "policy mismatch");
        (,,, uint256 routeMinProfit,,) =
            abi.decode(routeData, (address,uint256,uint256,uint256,address[],bytes[]));
        require(p.minOut == routeMinProfit, "profit policy mismatch");
        uint64 today = uint64(block.timestamp / 1 days);
        if (today != day) { day = today; dailyUsed = 0; }
        require(dailyUsed + amount <= dailyLimit, "daily limit");
        dailyUsed += amount;
        active = true;
        activeDataHash = keccak256(routeData);
        require(lender.flashLoan(address(this), token, amount, routeData), "flash failed");
        active = false;
        activeDataHash = bytes32(0);
    }

    function onFlashLoan(address initiator, address token, uint256 amount, uint256 fee, bytes calldata data)
        external returns (bytes32)
    {
        if (msg.sender != address(lender) || initiator != address(this) || !active || keccak256(data) != activeDataHash) {
            revert InvalidCallback();
        }
        (address oracle, uint256 expectedPrice, uint256 maxDeviationBps, uint256 minProfit,
         address[] memory targets, bytes[] memory calls) =
            abi.decode(data, (address,uint256,uint256,uint256,address[],bytes[]));
        (uint256 price, uint256 updatedAt) = IPriceGuard(oracle).latestPrice();
        if (maxDeviationBps > MAX_DEVIATION_BPS) revert OracleUnsafe();
        if (block.timestamp > updatedAt + MAX_ORACLE_AGE) revert OracleUnsafe();
        uint256 delta = price > expectedPrice ? price - expectedPrice : expectedPrice - price;
        if (expectedPrice == 0 || delta * 10_000 > expectedPrice * maxDeviationBps) revert OracleUnsafe();
        uint256 beforeBalance = IERC20(token).balanceOf(address(this));
        require(targets.length == calls.length, "route length");
        for (uint256 i; i < targets.length; ++i) {
            bytes32 expectedCodehash = targetCodehash[targets[i]];
            if (expectedCodehash == bytes32(0) || targets[i].codehash != expectedCodehash) revert Unauthorized();
            (bool ok,) = targets[i].call(calls[i]);
            require(ok, "route call failed");
        }
        uint256 repayment = amount + fee;
        uint256 afterBalance = IERC20(token).balanceOf(address(this));
        if (afterBalance < beforeBalance + fee + minProfit || afterBalance < repayment) revert InsufficientProfit();
        uint256 profit = afterBalance - beforeBalance - fee;
        IERC20(token).safeTransfer(treasury, profit * PROFIT_TAX_BPS / 10_000);
        IERC20(token).forceApprove(address(lender), repayment);
        return CALLBACK_SUCCESS;
    }
}
