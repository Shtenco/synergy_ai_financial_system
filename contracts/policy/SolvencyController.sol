// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IConsolidatedLedgerSolvency {
    function externalLiabilities() external view returns (uint256);
    function realizedExternalPnL() external view returns (int256);
    function totalDividends() external view returns (uint256);
    function realizedLosses() external view returns (uint256);
}

/// @notice Conservative solvency controller based on realizable haircut assets,
/// stress liabilities, 30-day liquidity coverage and the historical 120% gas
/// coverage rule. Market capitalization is deliberately excluded from NAV.
contract SolvencyController {
    uint256 public constant BPS = 10_000;
    uint256 public constant NORMAL_SOLVENCY_BPS = 12_000;
    uint256 public constant DEFENSIVE_SOLVENCY_BPS = 10_500;
    uint256 public constant NORMAL_LIQUIDITY_BPS = 12_000;
    uint256 public constant MIN_GAS_COVERAGE_BPS = 12_000;
    uint256 public constant MIN_RESERVE_POLICY_BPS = 7_000;

    uint256 public constant STABLE_LP_HAIRCUT_BPS = 8_500;
    uint256 public constant VOLATILE_LP_HAIRCUT_BPS = 6_500;
    uint256 public constant BRIDGE_HAIRCUT_BPS = 7_000;
    uint256 public constant INSURANCE_HAIRCUT_BPS = 9_000;
    uint256 public constant YIELD_HAIRCUT_BPS = 8_000;
    uint256 public constant INVENTORY_HAIRCUT_BPS = 2_500;

    enum Mode {
        BOOTSTRAP,
        RECOVERY,
        NORMAL,
        DEFENSIVE,
        PAUSED,
        DIVIDEND,
        EMERGENCY
    }

    struct Assets {
        uint256 liquidReserves;
        uint256 stableLpNav;
        uint256 volatileLpNav;
        uint256 bridgeCapital;
        uint256 insuranceAssets;
        uint256 yieldPositions;
        uint256 gasReserve;
        uint256 unrealizedInventoryValue;
    }

    struct OtherLiabilities {
        uint256 externalSynrClaims;
        uint256 vestedMevClaims;
        uint256 bridgeObligations;
        uint256 keeperReimbursementsAccrued;
        uint256 externalDebt;
        uint256 expectedThirtyDayOperatingCosts;
        uint256 modeledRedemptionShock;
    }

    address public admin;
    mapping(address => bool) public reporter;
    IConsolidatedLedgerSolvency public immutable ledger;
    Assets public assets;
    OtherLiabilities public otherLiabilities;

    uint256 public immediatelyAvailableLiquidAssets;
    uint256 public stressedThirtyDayOutflows;
    uint256 public reservePolicyCapital;
    uint256 public conservativeTokenObligations;
    uint256 public totalReimbursedGas;
    uint256 public gasSkippedActions;
    uint256 public usefulActionsExecuted;
    uint256 public liquidityBuffer;
    uint256 public gasBuffer;
    uint256 public insuranceBuffer;
    uint256 public minimumNetMargin;
    bool public oracleFresh = true;
    bool public bridgeAvailable = true;
    bool public externalOpportunity;
    Mode public mode = Mode.BOOTSTRAP;

    error Unauthorized();
    error InvalidAddress();
    error InvalidMode();

    event ReporterSet(address indexed reporter, bool allowed);
    event MetricsUpdated(uint256 haircutAssets, uint256 stressLiabilities);
    event ModeChanged(Mode indexed previousMode, Mode indexed newMode);
    event EnvironmentUpdated(bool externalOpportunity, bool oracleFresh, bool bridgeAvailable);

    constructor(address admin_, IConsolidatedLedgerSolvency ledger_) {
        if (admin_ == address(0) || address(ledger_) == address(0)) revert InvalidAddress();
        admin = admin_;
        ledger = ledger_;
        reporter[admin_] = true;
        minimumNetMargin = 1e14; // 0.0001 reserve asset units at 18 decimals.
        emit ReporterSet(admin_, true);
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyReporter() {
        if (!reporter[msg.sender]) revert Unauthorized();
        _;
    }

    function setReporter(address account, bool allowed) external onlyAdmin {
        if (account == address(0)) revert InvalidAddress();
        reporter[account] = allowed;
        emit ReporterSet(account, allowed);
    }

    function setBuffers(
        uint256 liquidityBuffer_,
        uint256 gasBuffer_,
        uint256 insuranceBuffer_,
        uint256 minimumNetMargin_
    ) external onlyAdmin {
        liquidityBuffer = liquidityBuffer_;
        gasBuffer = gasBuffer_;
        insuranceBuffer = insuranceBuffer_;
        minimumNetMargin = minimumNetMargin_;
    }

    function updateAssets(Assets calldata value) external onlyReporter {
        assets = value;
        emit MetricsUpdated(haircutAssets(), stressLiabilities());
    }

    function updateOtherLiabilities(OtherLiabilities calldata value) external onlyReporter {
        otherLiabilities = value;
        emit MetricsUpdated(haircutAssets(), stressLiabilities());
    }

    function updateCoverageInputs(
        uint256 immediatelyAvailableLiquidAssets_,
        uint256 stressedThirtyDayOutflows_,
        uint256 reservePolicyCapital_,
        uint256 conservativeTokenObligations_,
        uint256 totalReimbursedGas_,
        uint256 gasSkippedActions_,
        uint256 usefulActionsExecuted_
    ) external onlyReporter {
        immediatelyAvailableLiquidAssets = immediatelyAvailableLiquidAssets_;
        stressedThirtyDayOutflows = stressedThirtyDayOutflows_;
        reservePolicyCapital = reservePolicyCapital_;
        conservativeTokenObligations = conservativeTokenObligations_;
        totalReimbursedGas = totalReimbursedGas_;
        gasSkippedActions = gasSkippedActions_;
        usefulActionsExecuted = usefulActionsExecuted_;
    }

    function updateEnvironment(
        bool externalOpportunity_,
        bool oracleFresh_,
        bool bridgeAvailable_
    ) external onlyReporter returns (Mode) {
        externalOpportunity = externalOpportunity_;
        oracleFresh = oracleFresh_;
        bridgeAvailable = bridgeAvailable_;
        emit EnvironmentUpdated(externalOpportunity_, oracleFresh_, bridgeAvailable_);
        return refreshMode();
    }

    function setRecoveryMode() external onlyAdmin {
        _setMode(Mode.RECOVERY);
    }

    function setEmergencyMode() external onlyAdmin {
        _setMode(Mode.EMERGENCY);
    }

    function haircutAssets() public view returns (uint256) {
        Assets memory a = assets;
        return a.liquidReserves + a.gasReserve
            + a.stableLpNav * STABLE_LP_HAIRCUT_BPS / BPS
            + a.volatileLpNav * VOLATILE_LP_HAIRCUT_BPS / BPS
            + a.bridgeCapital * BRIDGE_HAIRCUT_BPS / BPS
            + a.insuranceAssets * INSURANCE_HAIRCUT_BPS / BPS
            + a.yieldPositions * YIELD_HAIRCUT_BPS / BPS
            + a.unrealizedInventoryValue * INVENTORY_HAIRCUT_BPS / BPS;
    }

    function stressLiabilities() public view returns (uint256) {
        OtherLiabilities memory l = otherLiabilities;
        return ledger.externalLiabilities() + l.externalSynrClaims + l.vestedMevClaims
            + l.bridgeObligations + l.keeperReimbursementsAccrued + l.externalDebt
            + l.expectedThirtyDayOperatingCosts + l.modeledRedemptionShock;
    }

    function consolidatedNav() public view returns (int256) {
        return int256(haircutAssets()) - int256(stressLiabilities());
    }

    function economicSolvencyBps() public view returns (uint256) {
        uint256 liabilities = stressLiabilities();
        if (liabilities == 0) return type(uint256).max;
        return haircutAssets() * BPS / liabilities;
    }

    function liquidityCoverageBps() public view returns (uint256) {
        if (stressedThirtyDayOutflows == 0) return type(uint256).max;
        return immediatelyAvailableLiquidAssets * BPS / stressedThirtyDayOutflows;
    }

    function gasCoverageBps() public view returns (uint256) {
        if (totalReimbursedGas == 0) return type(uint256).max;
        return (totalReimbursedGas + assets.gasReserve) * BPS / totalReimbursedGas;
    }

    function reservePolicyRatioBps() public view returns (uint256) {
        if (conservativeTokenObligations == 0) return type(uint256).max;
        return reservePolicyCapital * BPS / conservativeTokenObligations;
    }

    function requiredSolvencyCapital() public view returns (uint256) {
        return stressLiabilities() * NORMAL_SOLVENCY_BPS / BPS;
    }

    function excessReserve() public view returns (uint256) {
        uint256 required = requiredSolvencyCapital() + liquidityBuffer + gasBuffer + insuranceBuffer;
        return assets.liquidReserves > required ? assets.liquidReserves - required : 0;
    }

    function dividendableCapital() public view returns (uint256) {
        int256 pnl = ledger.realizedExternalPnL();
        if (pnl <= 0) return 0;
        uint256 realizedBound = uint256(pnl);
        uint256 paid = ledger.totalDividends();
        if (realizedBound <= paid) return 0;
        realizedBound -= paid;

        int256 nav = consolidatedNav();
        if (nav <= 0) return 0;
        uint256 required = liquidityBuffer + gasBuffer + insuranceBuffer
            + otherLiabilities.expectedThirtyDayOperatingCosts;
        uint256 navBound = uint256(nav) > required ? uint256(nav) - required : 0;
        return realizedBound < navBound ? realizedBound : navBound;
    }

    function canExecute(uint256 expectedExternalValue, uint256 expectedExternalCosts)
        external
        view
        returns (bool)
    {
        if (mode != Mode.NORMAL && mode != Mode.RECOVERY) return false;
        if (!oracleFresh || !bridgeAvailable || !externalOpportunity) return false;
        if (expectedExternalValue <= expectedExternalCosts + minimumNetMargin) return false;
        return economicSolvencyBps() >= DEFENSIVE_SOLVENCY_BPS
            && liquidityCoverageBps() >= NORMAL_LIQUIDITY_BPS
            && gasCoverageBps() >= MIN_GAS_COVERAGE_BPS
            && reservePolicyRatioBps() >= MIN_RESERVE_POLICY_BPS;
    }

    function canPayDividend(uint256 amount) external view returns (bool) {
        if (amount == 0 || amount > dividendableCapital()) return false;
        return economicSolvencyBps() >= NORMAL_SOLVENCY_BPS
            && liquidityCoverageBps() >= NORMAL_LIQUIDITY_BPS
            && gasCoverageBps() >= MIN_GAS_COVERAGE_BPS
            && reservePolicyRatioBps() >= MIN_RESERVE_POLICY_BPS
            && oracleFresh && bridgeAvailable;
    }

    function refreshMode() public returns (Mode) {
        if (mode == Mode.EMERGENCY) return mode;
        uint256 solvency = economicSolvencyBps();
        uint256 liquidity = liquidityCoverageBps();
        uint256 gas = gasCoverageBps();
        uint256 policy = reservePolicyRatioBps();

        if (
            !oracleFresh || !bridgeAvailable || !externalOpportunity
                || solvency < DEFENSIVE_SOLVENCY_BPS || liquidity < DEFENSIVE_SOLVENCY_BPS
                || gas < MIN_GAS_COVERAGE_BPS
        ) {
            _setMode(Mode.PAUSED);
        } else if (
            solvency < NORMAL_SOLVENCY_BPS || liquidity < NORMAL_LIQUIDITY_BPS
                || policy < MIN_RESERVE_POLICY_BPS
        ) {
            _setMode(Mode.DEFENSIVE);
        } else {
            _setMode(Mode.NORMAL);
        }
        return mode;
    }

    function _setMode(Mode next) private {
        if (next == mode) return;
        Mode previous = mode;
        mode = next;
        emit ModeChanged(previous, next);
    }
}
