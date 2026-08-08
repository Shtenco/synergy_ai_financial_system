// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "../synthl1/SafeTransferLib.sol";

interface IV15RevenueLedger {
    function hardNAV1e18() external view returns (int256);
    function markValue1e18(address token, uint256 amount) external view returns (uint256);
    function isHardAsset(address token) external view returns (bool);
    function isHardAccount(address token, address account) external view returns (bool);
}

interface IV15RevenueSolvency {
    function distributionAllowed() external view returns (bool);
}

interface IERC20V15Revenue {
    function balanceOf(address account) external view returns (uint256);
}

/// @notice Hard-profit accounting and distribution router.
///
/// External capital contributions are recognized only when hard tokens are
/// physically transferred into this router and the router is an EconomicLedger
/// hard account for that token. There is deliberately no arbitrary withdrawal
/// add-back: a hard withdrawal outside this router is an economic NAV reduction,
/// not a number a reporter may neutralize by assertion.
contract V15RevenueRouter {
    using SafeTransferLib for address;

    address public owner;
    address public capitalFlowReporter;
    IV15RevenueLedger public immutable ledger;
    IV15RevenueSolvency public immutable controller;

    bool public periodOpen;
    bool public periodSettled;
    int256 public periodStartNAV1e18;
    uint256 public contributions1e18;
    uint256 public distributableBudget1e18;
    uint256 public distributed1e18;
    uint256 public lossCarryforward1e18;

    event CapitalFlowReporterSet(address indexed reporter);
    event PeriodStarted(int256 startNAV1e18);
    event ContributionRecorded(address indexed token, address indexed from, uint256 amount, uint256 value1e18);
    event PeriodSettled(
        int256 operatingPnL1e18,
        uint256 lossCarryforwardAfter1e18,
        uint256 reserveTopup1e18,
        uint256 distributable1e18
    );
    event Distributed(address indexed token, address indexed to, uint256 amount, uint256 value1e18);
    event PeriodClosed(int256 endingNAV1e18);

    error Unauthorized();
    error BadConfig();
    error InsolventDistribution();
    error BudgetExceeded();
    error UnaccountedCustody();

    constructor(address owner_, address reporter_, address ledger_, address controller_) {
        if (owner_ == address(0) || reporter_ == address(0) || ledger_ == address(0) || controller_ == address(0)) {
            revert BadConfig();
        }
        owner = owner_;
        capitalFlowReporter = reporter_;
        ledger = IV15RevenueLedger(ledger_);
        controller = IV15RevenueSolvency(controller_);
    }

    modifier onlyOwner() { if (msg.sender != owner) revert Unauthorized(); _; }
    modifier onlyReporter() { if (msg.sender != capitalFlowReporter) revert Unauthorized(); _; }

    function setCapitalFlowReporter(address next) external onlyOwner {
        if (next == address(0)) revert BadConfig();
        capitalFlowReporter = next;
        emit CapitalFlowReporterSet(next);
    }

    function startPeriod() external onlyOwner {
        if (periodOpen) revert BadConfig();
        periodOpen = true;
        periodSettled = false;
        periodStartNAV1e18 = ledger.hardNAV1e18();
        contributions1e18 = 0;
        distributableBudget1e18 = 0;
        distributed1e18 = 0;
        emit PeriodStarted(periodStartNAV1e18);
    }

    /// @notice Physically receives and values external capital. `from` must
    /// approve this router. Fee-on-transfer behavior is measured by balance delta.
    function recordContributionToken(address token, address from, uint256 amount)
        external onlyReporter returns (uint256 received, uint256 value1e18)
    {
        if (!periodOpen || periodSettled || token == address(0) || from == address(0) || amount == 0) revert BadConfig();
        if (!ledger.isHardAsset(token) || !ledger.isHardAccount(token, address(this))) revert UnaccountedCustody();

        uint256 beforeBalance = IERC20V15Revenue(token).balanceOf(address(this));
        token.safeTransferFrom(from, address(this), amount);
        uint256 afterBalance = IERC20V15Revenue(token).balanceOf(address(this));
        if (afterBalance <= beforeBalance) revert BadConfig();
        received = afterBalance - beforeBalance;
        value1e18 = ledger.markValue1e18(token, received);
        contributions1e18 += value1e18;
        emit ContributionRecorded(token, from, received, value1e18);
    }

    function settlePeriod(uint256 requiredReserveTopup1e18) external onlyOwner returns (int256 pnl, uint256 budget) {
        if (!periodOpen || periodSettled || !controller.distributionAllowed()) revert InsolventDistribution();
        int256 nowNav = ledger.hardNAV1e18();
        if (contributions1e18 > uint256(type(int256).max)) revert BadConfig();

        // No arbitrary withdrawal add-back. Hard distributions are made only
        // after settlement through distribute(), where they consume budget.
        pnl = nowNav - periodStartNAV1e18 - int256(contributions1e18);

        uint256 positiveAfterLoss;
        if (pnl <= 0) {
            if (pnl == type(int256).min) revert BadConfig();
            lossCarryforward1e18 += uint256(-pnl);
        } else {
            uint256 positive = uint256(pnl);
            if (positive <= lossCarryforward1e18) {
                lossCarryforward1e18 -= positive;
            } else {
                positiveAfterLoss = positive - lossCarryforward1e18;
                lossCarryforward1e18 = 0;
            }
        }
        if (positiveAfterLoss > requiredReserveTopup1e18) {
            budget = positiveAfterLoss - requiredReserveTopup1e18;
        }

        distributableBudget1e18 = budget;
        distributed1e18 = 0;
        periodSettled = true;
        emit PeriodSettled(pnl, lossCarryforward1e18, requiredReserveTopup1e18, budget);
    }

    function distribute(address token, address to, uint256 amount) external onlyOwner {
        if (!periodOpen || !periodSettled || to == address(0) || amount == 0 || !ledger.isHardAsset(token)) revert BadConfig();
        if (!ledger.isHardAccount(token, address(this))) revert UnaccountedCustody();
        if (!controller.distributionAllowed()) revert InsolventDistribution();

        uint256 value = ledger.markValue1e18(token, amount);
        if (distributed1e18 + value > distributableBudget1e18) revert BudgetExceeded();
        distributed1e18 += value;
        token.safeTransfer(to, amount);

        // Post-transfer solvency check. Revert rolls the token transfer back atomically.
        if (!controller.distributionAllowed()) revert InsolventDistribution();
        emit Distributed(token, to, amount, value);
    }

    function closePeriod() external onlyOwner {
        if (!periodOpen || !periodSettled) revert BadConfig();
        periodOpen = false;
        emit PeriodClosed(ledger.hardNAV1e18());
    }
}
