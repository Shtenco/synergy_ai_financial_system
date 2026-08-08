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
    function distributionHeadroom1e18() external view returns (uint256);
}

interface IERC20V15Revenue {
    function balanceOf(address account) external view returns (uint256);
}

/// @notice Hard-profit accounting and distribution router.
/// Distribution requires:
/// 1. HWM Economic HardNAV profit after capital-flow adjustment/loss carry;
/// 2. physically swept hard revenue from an allowlisted protocol contract;
/// 3. a monotonic source-side evidence counter proving that the swept amount was
///    actually recognized as fee/tax/service revenue by that source;
/// 4. controller-derived solvency headroom.
contract V15RevenueRouter {
    using SafeTransferLib for address;

    struct RevenueSourceConfig {
        bool enabled;
        bytes4 cumulativeEvidenceSelector;
    }

    address public owner;
    address public capitalFlowReporter;
    IV15RevenueLedger public immutable ledger;
    IV15RevenueSolvency public immutable controller;

    bool public periodOpen;
    bool public periodSettled;
    int256 public periodStartNAV1e18;
    uint256 public contributions1e18;
    uint256 public eligibleRevenue1e18;
    uint256 public distributableBudget1e18;
    uint256 public distributed1e18;
    uint256 public lossCarryforward1e18;

    mapping(address => RevenueSourceConfig) public revenueSource;
    mapping(address => mapping(address => uint256)) public recognizedRevenueUnits;

    event CapitalFlowReporterSet(address indexed reporter);
    event RevenueSourceSet(address indexed source, bytes4 indexed evidenceSelector, bool enabled);
    event PeriodStarted(int256 startNAV1e18);
    event ContributionRecorded(address indexed token, address indexed from, uint256 amount, uint256 value1e18);
    event EligibleRevenueRecorded(
        address indexed token,
        address indexed from,
        uint256 amount,
        uint256 value1e18,
        uint256 cumulativeEvidenceAfter
    );
    event PeriodSettled(
        int256 operatingPnL1e18,
        uint256 eligibleRevenue1e18,
        uint256 solvencyHeadroom1e18,
        uint256 lossCarryforwardAfter1e18,
        uint256 distributable1e18
    );
    event Distributed(address indexed token, address indexed to, uint256 amount, uint256 value1e18);
    event PeriodClosed(int256 endingNAV1e18);

    error Unauthorized();
    error BadConfig();
    error InsolventDistribution();
    error BudgetExceeded();
    error UnaccountedCustody();
    error IneligibleRevenueSource();
    error RevenueEvidenceInvalid();

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

    /// @notice Configure a protocol CONTRACT as an eligible revenue source.
    /// `evidenceSelector` must implement `selector(address token) -> uint256 cumulative`.
    /// Example for frozen MEVCaptureReinvestor: `cumulativeCaptured(address)`.
    function setRevenueSource(address source, bytes4 evidenceSelector, bool enabled) external onlyOwner {
        if (source == address(0)) revert BadConfig();
        if (enabled) {
            if (source.code.length == 0 || evidenceSelector == bytes4(0)) revert BadConfig();
            revenueSource[source] = RevenueSourceConfig(true, evidenceSelector);
        } else {
            revenueSource[source].enabled = false;
        }
        emit RevenueSourceSet(source, evidenceSelector, enabled);
    }

    function startPeriod() external onlyOwner {
        if (periodOpen) revert BadConfig();
        periodOpen = true;
        periodSettled = false;
        periodStartNAV1e18 = ledger.hardNAV1e18();
        contributions1e18 = 0;
        eligibleRevenue1e18 = 0;
        distributableBudget1e18 = 0;
        distributed1e18 = 0;
        emit PeriodStarted(periodStartNAV1e18);
    }

    /// @notice Physically receives external investment/capital. It increases NAV
    /// but is subtracted from operating PnL and never becomes revenue by itself.
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

    /// @notice Sweeps already-protocol-owned realized hard revenue into this router.
    /// The transfer is HardNAV-neutral because source and router are both accounted.
    /// A direct token donation to the source is NOT eligible unless the source's
    /// cumulative revenue evidence counter also increased.
    function recordEligibleRevenueToken(address token, address from, uint256 amount)
        external onlyReporter returns (uint256 received, uint256 value1e18)
    {
        if (!periodOpen || periodSettled || token == address(0) || from == address(0) || amount == 0) revert BadConfig();
        RevenueSourceConfig memory cfg = revenueSource[from];
        if (!cfg.enabled) revert IneligibleRevenueSource();
        if (
            !ledger.isHardAsset(token) ||
            !ledger.isHardAccount(token, address(this)) ||
            !ledger.isHardAccount(token, from)
        ) revert UnaccountedCustody();

        uint256 cumulative = _cumulativeRevenueEvidence(from, cfg.cumulativeEvidenceSelector, token);
        uint256 recognized = recognizedRevenueUnits[from][token];
        if (cumulative < recognized || amount > cumulative - recognized) revert RevenueEvidenceInvalid();

        uint256 beforeBalance = IERC20V15Revenue(token).balanceOf(address(this));
        token.safeTransferFrom(from, address(this), amount);
        uint256 afterBalance = IERC20V15Revenue(token).balanceOf(address(this));
        if (afterBalance <= beforeBalance) revert BadConfig();
        received = afterBalance - beforeBalance;

        // Consume the gross source-side evidence amount. Fee-on-transfer loss, if
        // any, can never be reused as eligible revenue in a later sweep.
        recognizedRevenueUnits[from][token] = recognized + amount;
        value1e18 = ledger.markValue1e18(token, received);
        eligibleRevenue1e18 += value1e18;
        emit EligibleRevenueRecorded(token, from, received, value1e18, cumulative);
    }

    function _cumulativeRevenueEvidence(address source, bytes4 selector, address token)
        internal view returns (uint256 cumulative)
    {
        (bool ok, bytes memory data) = source.staticcall(abi.encodeWithSelector(selector, token));
        if (!ok || data.length < 32) revert RevenueEvidenceInvalid();
        cumulative = abi.decode(data, (uint256));
    }

    /// @notice Accounting settlement is always allowed when ledgers are readable,
    /// including RED. Crisis losses must enter loss carry-forward instead of hiding.
    function settlePeriod() external onlyOwner returns (int256 pnl, uint256 budget) {
        if (!periodOpen || periodSettled) revert BadConfig();
        int256 nowNav = ledger.hardNAV1e18();
        if (contributions1e18 > uint256(type(int256).max)) revert BadConfig();

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

        uint256 eligibleProfit = positiveAfterLoss < eligibleRevenue1e18
            ? positiveAfterLoss
            : eligibleRevenue1e18;
        uint256 solvencyHeadroom = controller.distributionHeadroom1e18();
        budget = eligibleProfit < solvencyHeadroom ? eligibleProfit : solvencyHeadroom;

        distributableBudget1e18 = budget;
        distributed1e18 = 0;
        periodSettled = true;
        emit PeriodSettled(pnl, eligibleRevenue1e18, solvencyHeadroom, lossCarryforward1e18, budget);
    }

    function distribute(address token, address to, uint256 amount) external onlyOwner {
        if (!periodOpen || !periodSettled || to == address(0) || amount == 0 || !ledger.isHardAsset(token)) revert BadConfig();
        if (!ledger.isHardAccount(token, address(this))) revert UnaccountedCustody();
        if (!controller.distributionAllowed()) revert InsolventDistribution();

        uint256 value = ledger.markValue1e18(token, amount);
        if (distributed1e18 + value > distributableBudget1e18) revert BudgetExceeded();
        distributed1e18 += value;
        token.safeTransfer(to, amount);

        // Final post-transfer solvency gate. Revert rolls the transfer back.
        if (!controller.distributionAllowed()) revert InsolventDistribution();
        emit Distributed(token, to, amount, value);
    }

    function closePeriod() external onlyOwner {
        if (!periodOpen || !periodSettled) revert BadConfig();
        periodOpen = false;
        emit PeriodClosed(ledger.hardNAV1e18());
    }
}
