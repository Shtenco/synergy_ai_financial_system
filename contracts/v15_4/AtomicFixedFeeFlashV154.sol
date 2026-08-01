// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {ERC20} from "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

interface IAtomicFlashBorrowerV154 {
    function onAtomicFlashLoanV154(
        address initiator,
        address token,
        uint256 amount,
        uint256 fixedFee,
        bytes calldata data
    ) external returns (bytes32);
}

interface IAtomicFlashRouteV154 {
    function executeFlashRouteV154(
        address token,
        uint256 amount,
        address recipient,
        bytes calldata data
    ) external returns (uint256 amountReturned);
}

/// @notice Structural flash lender for the exact stress requested by the
/// project: every successful loan costs exactly 5 WPOL, independent of size.
/// This is not represented as an Aave production premium. It is a deliberately
/// harsher fixed-cost acceptance harness.
contract AtomicFixedFeeFlashLenderV154 {
    using SafeERC20 for IERC20;

    bytes32 public constant CALLBACK_MAGIC = keccak256("SYNERGY_ATOMIC_FLASH_V15_4");

    IERC20 public immutable asset;
    uint256 public immutable fixedFee;
    uint256 public completedLoans;
    uint256 public cumulativeFees;
    bool private entered;

    error InvalidConfiguration();
    error Reentrancy();
    error InsufficientLiquidity();
    error InvalidCallback();
    error RepaymentInvariantFailed();

    event FlashLoanClosed(
        address indexed borrower,
        uint256 principal,
        uint256 fixedFee,
        uint256 lenderBalanceAfter
    );

    constructor(address asset_, uint256 fixedFee_) {
        if (asset_ == address(0) || fixedFee_ == 0) revert InvalidConfiguration();
        asset = IERC20(asset_);
        fixedFee = fixedFee_;
    }

    function flashLoan(
        address borrower,
        uint256 amount,
        bytes calldata data
    ) external returns (uint256 feePaid) {
        if (entered) revert Reentrancy();
        if (borrower.code.length == 0 || amount == 0) revert InvalidConfiguration();

        uint256 lenderBefore = asset.balanceOf(address(this));
        if (lenderBefore < amount) revert InsufficientLiquidity();

        entered = true;
        asset.safeTransfer(borrower, amount);

        bytes32 callback = IAtomicFlashBorrowerV154(borrower).onAtomicFlashLoanV154(
            msg.sender,
            address(asset),
            amount,
            fixedFee,
            data
        );
        if (callback != CALLBACK_MAGIC) revert InvalidCallback();

        asset.safeTransferFrom(borrower, address(this), amount + fixedFee);
        uint256 lenderAfter = asset.balanceOf(address(this));
        if (lenderAfter < lenderBefore + fixedFee) revert RepaymentInvariantFailed();

        completedLoans += 1;
        cumulativeFees += fixedFee;
        entered = false;

        emit FlashLoanClosed(borrower, amount, fixedFee, lenderAfter);
        return fixedFee;
    }
}

/// @notice Executes one or ten exact fixed-fee flash cycles. There is no
/// pre-funded subsidy: the receiver must be empty before every cycle. If any
/// cycle in runTenCycles fails, the whole transaction, including prior cycles,
/// transfers and counters, reverts atomically.
contract AtomicFlashCompoundV154 is IAtomicFlashBorrowerV154 {
    using SafeERC20 for IERC20;

    uint256 public constant BPS = 10_000;
    uint256 public constant REINVESTMENT_BPS = 8_000;
    uint256 public constant EDGE_SCALE_PPT = 1_000_000_000_000;
    uint256 public constant MIN_NET_EDGE_PPT = 268_514_800; // 2.685148 bps

    AtomicFixedFeeFlashLenderV154 public immutable lender;
    IERC20 public immutable asset;
    address public immutable reinvestmentVault;
    address public immutable retainedTreasury;
    address public immutable operator;

    bool private callbackActive;
    uint256 private callbackNetProfit;
    uint256 private callbackGrossProfit;

    uint256 public completedCycles;
    uint256 public cumulativeGrossRouteProfit;
    uint256 public cumulativeFlashFees;
    uint256 public cumulativeNetProtocolProfit;
    uint256 public cumulativeReinvested;
    uint256 public cumulativeRetained;

    error Unauthorized();
    error InvalidConfiguration();
    error ReceiverSubsidyDetected();
    error InvalidCallback();
    error RouteUnderpaid();
    error FlashFeeNotCovered();
    error NetEdgeBelowFloor();
    error SettlementResidueMismatch();

    event AtomicFlashCycleClosed(
        uint256 indexed cycle,
        uint256 principal,
        uint256 grossRouteProfit,
        uint256 fixedFlashFee,
        uint256 netProtocolProfit,
        uint256 realizedNetEdgePpt,
        uint256 reinvested,
        uint256 retained
    );

    event TenCycleBatchClosed(
        uint256 firstCycle,
        uint256 lastCycle,
        uint256 batchNetProtocolProfit,
        uint256 batchReinvested
    );

    constructor(
        address lender_,
        address reinvestmentVault_,
        address retainedTreasury_,
        address operator_
    ) {
        if (
            lender_ == address(0)
                || reinvestmentVault_ == address(0)
                || retainedTreasury_ == address(0)
                || operator_ == address(0)
        ) revert InvalidConfiguration();
        lender = AtomicFixedFeeFlashLenderV154(lender_);
        asset = lender.asset();
        reinvestmentVault = reinvestmentVault_;
        retainedTreasury = retainedTreasury_;
        operator = operator_;
    }

    function runCycle(
        uint256 principal,
        address route,
        uint256 minimumGrossRouteProfit,
        bytes calldata routeData
    ) external returns (uint256 netProtocolProfit) {
        if (msg.sender != operator) revert Unauthorized();
        return _runCycle(principal, route, minimumGrossRouteProfit, routeData);
    }

    function runTenCycles(
        uint256 principal,
        address route,
        uint256 minimumGrossRouteProfit,
        bytes calldata routeData
    ) external returns (uint256 batchNetProtocolProfit) {
        if (msg.sender != operator) revert Unauthorized();
        uint256 firstCycle = completedCycles + 1;
        uint256 reinvestedBefore = cumulativeReinvested;
        for (uint256 index = 0; index < 10; index += 1) {
            batchNetProtocolProfit += _runCycle(
                principal,
                route,
                minimumGrossRouteProfit,
                routeData
            );
        }
        emit TenCycleBatchClosed(
            firstCycle,
            completedCycles,
            batchNetProtocolProfit,
            cumulativeReinvested - reinvestedBefore
        );
    }

    function onAtomicFlashLoanV154(
        address initiator,
        address token,
        uint256 amount,
        uint256 fixedFee,
        bytes calldata data
    ) external returns (bytes32) {
        if (
            msg.sender != address(lender)
                || !callbackActive
                || initiator != address(this)
                || token != address(asset)
        ) revert InvalidCallback();

        (address route, uint256 minimumGrossRouteProfit, bytes memory routeData) =
            abi.decode(data, (address, uint256, bytes));
        if (route.code.length == 0) revert InvalidConfiguration();

        uint256 balanceAtCallback = asset.balanceOf(address(this));
        if (balanceAtCallback != amount) revert ReceiverSubsidyDetected();

        asset.forceApprove(route, amount);
        uint256 reportedReturned = IAtomicFlashRouteV154(route).executeFlashRouteV154(
            address(asset),
            amount,
            address(this),
            routeData
        );
        asset.forceApprove(route, 0);

        uint256 balanceAfterRoute = asset.balanceOf(address(this));
        if (balanceAfterRoute < amount || reportedReturned != balanceAfterRoute) {
            revert RouteUnderpaid();
        }

        uint256 grossRouteProfit = balanceAfterRoute - amount;
        if (grossRouteProfit < minimumGrossRouteProfit) revert RouteUnderpaid();
        if (grossRouteProfit < fixedFee) revert FlashFeeNotCovered();

        uint256 netProtocolProfit = grossRouteProfit - fixedFee;
        uint256 realizedNetEdgePpt = netProtocolProfit * EDGE_SCALE_PPT / amount;
        if (realizedNetEdgePpt < MIN_NET_EDGE_PPT) revert NetEdgeBelowFloor();

        callbackGrossProfit = grossRouteProfit;
        callbackNetProfit = netProtocolProfit;
        asset.forceApprove(address(lender), amount + fixedFee);
        return lender.CALLBACK_MAGIC();
    }

    function _runCycle(
        uint256 principal,
        address route,
        uint256 minimumGrossRouteProfit,
        bytes memory routeData
    ) private returns (uint256 netProtocolProfit) {
        if (
            principal == 0
                || route == address(0)
                || callbackActive
                || asset.balanceOf(address(this)) != 0
        ) revert InvalidConfiguration();

        callbackActive = true;
        callbackNetProfit = 0;
        callbackGrossProfit = 0;

        lender.flashLoan(
            address(this),
            principal,
            abi.encode(route, minimumGrossRouteProfit, routeData)
        );

        callbackActive = false;
        netProtocolProfit = callbackNetProfit;
        uint256 grossRouteProfit = callbackGrossProfit;
        callbackNetProfit = 0;
        callbackGrossProfit = 0;

        if (asset.balanceOf(address(this)) != netProtocolProfit) {
            revert SettlementResidueMismatch();
        }

        uint256 reinvested = netProtocolProfit * REINVESTMENT_BPS / BPS;
        uint256 retained = netProtocolProfit - reinvested;
        if (reinvested > 0) asset.safeTransfer(reinvestmentVault, reinvested);
        if (retained > 0) asset.safeTransfer(retainedTreasury, retained);
        if (asset.balanceOf(address(this)) != 0) revert SettlementResidueMismatch();

        completedCycles += 1;
        cumulativeGrossRouteProfit += grossRouteProfit;
        cumulativeFlashFees += lender.fixedFee();
        cumulativeNetProtocolProfit += netProtocolProfit;
        cumulativeReinvested += reinvested;
        cumulativeRetained += retained;

        emit AtomicFlashCycleClosed(
            completedCycles,
            principal,
            grossRouteProfit,
            lender.fixedFee(),
            netProtocolProfit,
            netProtocolProfit * EDGE_SCALE_PPT / principal,
            reinvested,
            retained
        );
    }
}

contract MockWPOLV154 is ERC20 {
    constructor() ERC20("Mock Wrapped POL V15.4", "mWPOL") {}

    function issueForTest(address recipient, uint256 amount) external {
        _mint(recipient, amount);
    }
}

/// @notice Structural-only route. The route is funded with external test
/// inventory and returns principal plus a configured per-call profit. It is not
/// market evidence and can never be counted as transaction-panel revenue.
contract MockSequencedFlashRouteV154 is IAtomicFlashRouteV154 {
    using SafeERC20 for IERC20;

    IERC20 public immutable asset;
    address public immutable admin;
    uint256 public highProfit;
    uint256 public lowProfit;
    uint256 public highProfitCycles;
    uint256 public calls;

    error Unauthorized();
    error InvalidRoute();

    constructor(address asset_, address admin_) {
        if (asset_ == address(0) || admin_ == address(0)) revert InvalidRoute();
        asset = IERC20(asset_);
        admin = admin_;
    }

    function configure(
        uint256 highProfit_,
        uint256 lowProfit_,
        uint256 highProfitCycles_
    ) external {
        if (msg.sender != admin) revert Unauthorized();
        highProfit = highProfit_;
        lowProfit = lowProfit_;
        highProfitCycles = highProfitCycles_;
        calls = 0;
    }

    function executeFlashRouteV154(
        address token,
        uint256 amount,
        address recipient,
        bytes calldata data
    ) external returns (uint256 amountReturned) {
        if (
            token != address(asset)
                || amount == 0
                || recipient != msg.sender
                || data.length != 0
        ) revert InvalidRoute();

        calls += 1;
        uint256 profit = calls <= highProfitCycles ? highProfit : lowProfit;
        asset.safeTransferFrom(msg.sender, address(this), amount);
        amountReturned = amount + profit;
        asset.safeTransfer(recipient, amountReturned);
    }
}
