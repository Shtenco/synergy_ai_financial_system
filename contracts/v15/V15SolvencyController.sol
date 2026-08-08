// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IV15LedgerView {
    function hardNAV1e18() external view returns (int256);
    function assetCount() external view returns (uint256);
    function assetAt(uint256) external view returns (address);
    function assetDecimals(address) external view returns (uint8);
    function assetBalance(address) external view returns (uint256);
}

interface IV15LiabilityRiskView {
    function totalRiskLiabilities1e18() external view returns (uint256);
}

interface IV15RiskOracleView {
    function baseRiskValue1e18(address token, uint256 amount, uint8 decimals_) external view returns (uint256);
    function scenarioRiskValue1e18(address token, uint256 amount, uint8 decimals_, uint256 id) external view returns (uint256);
    function scenarioCount() external view returns (uint256);
    function scenarioInfo(uint256 id) external view returns (bytes32, uint16 liabilityStressBps, uint256 fixedCost1e18, bool enabled);
}

/// @notice Stateful V15 solvency brain with hysteresis.
/// Economic HardNAV is read from V15EconomicLedger; this contract only applies
/// conservative risk marks/haircuts to decide which action classes are admissible.
contract V15SolvencyController {
    enum Mode { GREEN, YELLOW, ORANGE, RED }

    struct Thresholds {
        uint16 greenCoverageBps;
        uint16 yellowCoverageBps;
        uint16 orangeCoverageBps;
        uint16 greenSTSBps;
        uint16 yellowSTSBps;
        uint16 orangeSTSBps;
        uint16 yellowReentryBufferBps;
        uint16 greenReentryBufferBps;
        uint16 greenGradientShiftBps;
        uint16 yellowGradientShiftBps;
        uint16 distributionCoverageBps;
        uint16 distributionSTSBps;
    }

    struct PortfolioLimits {
        /// @dev Absolute base-risk-asset floor. Ratios alone are insufficient for
        /// a tiny balance sheet. Zero disables this optional policy limit.
        uint256 minRiskAssets1e18;
        /// @dev Largest single hard asset as a share of base risk assets.
        /// 10_000 disables the concentration cap; governance can tighten later.
        uint16 maxSingleAssetConcentrationBps;
    }

    address public owner;
    IV15LedgerView public immutable ledger;
    IV15LiabilityRiskView public immutable liabilities;
    IV15RiskOracleView public immutable riskOracle;
    Mode public mode = Mode.RED;
    int256 public minHardNAV1e18;
    Thresholds public thresholds;
    PortfolioLimits public portfolioLimits;

    event ModeChanged(Mode indexed oldMode, Mode indexed newMode, uint256 coverageBps, uint256 stsBps, int256 hardNAV1e18);
    event ThresholdsSet(bytes32 indexed configHash);
    event PortfolioLimitsSet(uint256 minRiskAssets1e18, uint16 maxSingleAssetConcentrationBps);
    event MinHardNAVSet(int256 value);

    error Unauthorized();
    error BadConfig();

    constructor(address owner_, address ledger_, address liabilities_, address riskOracle_) {
        if (owner_ == address(0) || ledger_ == address(0) || liabilities_ == address(0) || riskOracle_ == address(0)) {
            revert BadConfig();
        }
        owner = owner_;
        ledger = IV15LedgerView(ledger_);
        liabilities = IV15LiabilityRiskView(liabilities_);
        riskOracle = IV15RiskOracleView(riskOracle_);
        thresholds = Thresholds({
            greenCoverageBps: 13_000,
            yellowCoverageBps: 11_500,
            orangeCoverageBps: 10_500,
            greenSTSBps: 13_000,
            yellowSTSBps: 11_500,
            orangeSTSBps: 10_500,
            yellowReentryBufferBps: 300,
            greenReentryBufferBps: 500,
            greenGradientShiftBps: 5_000,
            yellowGradientShiftBps: 2_500,
            distributionCoverageBps: 13_000,
            distributionSTSBps: 13_000
        });
        // Backwards-compatible defaults. Production governance should set an
        // absolute capital floor and a stricter concentration cap before launch.
        portfolioLimits = PortfolioLimits(0, 10_000);
    }

    modifier onlyOwner() { if (msg.sender != owner) revert Unauthorized(); _; }

    function setMinHardNAV1e18(int256 value) external onlyOwner {
        minHardNAV1e18 = value;
        emit MinHardNAVSet(value);
    }

    function setThresholds(Thresholds calldata t) external onlyOwner {
        if (
            !(t.greenCoverageBps > t.yellowCoverageBps && t.yellowCoverageBps > t.orangeCoverageBps && t.orangeCoverageBps > 10_000) ||
            !(t.greenSTSBps > t.yellowSTSBps && t.yellowSTSBps > t.orangeSTSBps && t.orangeSTSBps > 10_000) ||
            t.greenGradientShiftBps == 0 || t.greenGradientShiftBps > 9_500 ||
            t.yellowGradientShiftBps == 0 || t.yellowGradientShiftBps > t.greenGradientShiftBps ||
            t.distributionCoverageBps < t.greenCoverageBps || t.distributionSTSBps < t.greenSTSBps
        ) revert BadConfig();
        thresholds = t;
        emit ThresholdsSet(keccak256(abi.encode(t)));
    }

    function setPortfolioLimits(uint256 minRiskAssets1e18_, uint16 maxSingleAssetConcentrationBps_) external onlyOwner {
        if (maxSingleAssetConcentrationBps_ == 0 || maxSingleAssetConcentrationBps_ > 10_000) revert BadConfig();
        portfolioLimits = PortfolioLimits(minRiskAssets1e18_, maxSingleAssetConcentrationBps_);
        emit PortfolioLimitsSet(minRiskAssets1e18_, maxSingleAssetConcentrationBps_);
    }

    function baseRiskAssets1e18() public view returns (uint256 total) {
        uint256 n = ledger.assetCount();
        for (uint256 i; i < n; ++i) {
            address token = ledger.assetAt(i);
            total += riskOracle.baseRiskValue1e18(token, ledger.assetBalance(token), ledger.assetDecimals(token));
        }
    }

    function maxSingleAssetConcentrationBps() public view returns (uint256) {
        uint256 n = ledger.assetCount();
        uint256 total;
        uint256 largest;
        for (uint256 i; i < n; ++i) {
            address token = ledger.assetAt(i);
            uint256 v = riskOracle.baseRiskValue1e18(token, ledger.assetBalance(token), ledger.assetDecimals(token));
            total += v;
            if (v > largest) largest = v;
        }
        if (total == 0) return 10_000;
        return (largest * 10_000) / total;
    }

    function metrics() public view returns (
        int256 hardNAV,
        uint256 riskAssets,
        uint256 riskLiabilities,
        uint256 coverageBps,
        uint256 stsBps
    ) {
        hardNAV = ledger.hardNAV1e18();
        riskAssets = baseRiskAssets1e18();
        riskLiabilities = liabilities.totalRiskLiabilities1e18();
        coverageBps = riskLiabilities == 0 ? type(uint256).max : (riskAssets * 10_000) / riskLiabilities;

        uint256 sc = riskOracle.scenarioCount();
        if (sc == 0) return (hardNAV, riskAssets, riskLiabilities, coverageBps, 0);
        stsBps = type(uint256).max;
        bool anyEnabled;
        uint256 n = ledger.assetCount();
        for (uint256 s; s < sc; ++s) {
            (, uint16 liabilityStressBps, uint256 fixedCost, bool enabled) = riskOracle.scenarioInfo(s);
            if (!enabled) continue;
            anyEnabled = true;
            uint256 stressedAssets;
            for (uint256 i; i < n; ++i) {
                address token = ledger.assetAt(i);
                stressedAssets += riskOracle.scenarioRiskValue1e18(
                    token,
                    ledger.assetBalance(token),
                    ledger.assetDecimals(token),
                    s
                );
            }
            if (stressedAssets <= fixedCost) {
                stsBps = 0;
                continue;
            }
            stressedAssets -= fixedCost;
            uint256 stressedLiabilities = (riskLiabilities * uint256(liabilityStressBps)) / 10_000;
            uint256 scenarioSTS = stressedLiabilities == 0
                ? type(uint256).max
                : (stressedAssets * 10_000) / stressedLiabilities;
            if (scenarioSTS < stsBps) stsBps = scenarioSTS;
        }
        if (!anyEnabled) stsBps = 0;
    }

    function portfolioMetrics() external view returns (
        uint256 riskAssets,
        uint256 concentrationBps,
        uint256 minRiskAssets1e18_,
        uint16 maxConcentrationBps_
    ) {
        riskAssets = baseRiskAssets1e18();
        concentrationBps = maxSingleAssetConcentrationBps();
        PortfolioLimits memory p = portfolioLimits;
        return (riskAssets, concentrationBps, p.minRiskAssets1e18, p.maxSingleAssetConcentrationBps);
    }

    function currentCoverageBps() external view returns (uint256) {
        (,,, uint256 k,) = metrics();
        return k;
    }

    function currentSTSBps() external view returns (uint256) {
        (,,,, uint256 s) = metrics();
        return s;
    }

    function _portfolioLimitsSatisfied(uint256 riskAssets) internal view returns (bool) {
        PortfolioLimits memory p = portfolioLimits;
        if (riskAssets < p.minRiskAssets1e18) return false;
        if (maxSingleAssetConcentrationBps() > p.maxSingleAssetConcentrationBps) return false;
        return true;
    }

    /// @notice Survival solvency. ORANGE may satisfy this, because ORANGE is the
    /// state in which unwind/restore is still possible. Do not use this function
    /// as permission to execute a new searcher exploitation.
    function routeSolvent() public view returns (bool) {
        (int256 nav, uint256 riskAssets,, uint256 k, uint256 s) = metrics();
        if (nav < minHardNAV1e18 || mode == Mode.RED || !_portfolioLimitsSatisfied(riskAssets)) return false;
        Thresholds memory t = thresholds;
        if (mode == Mode.GREEN) return k >= t.greenCoverageBps && s >= t.greenSTSBps;
        if (mode == Mode.YELLOW) return k >= t.yellowCoverageBps && s >= t.yellowSTSBps;
        return k >= t.orangeCoverageBps && s >= t.orangeSTSBps;
    }

    /// @notice New V13.1 searcher exploitation is permitted only in GREEN/YELLOW.
    /// V15PostRouteGate uses this stricter function, closing the ORANGE direct-call bypass.
    function searcherRouteAllowed() public view returns (bool) {
        return (mode == Mode.GREEN || mode == Mode.YELLOW) && routeSolvent();
    }

    function canExpand() external view returns (bool) {
        return searcherRouteAllowed();
    }

    function maxGradientShiftBps() external view returns (uint16) {
        if (mode == Mode.GREEN) return thresholds.greenGradientShiftBps;
        if (mode == Mode.YELLOW) return thresholds.yellowGradientShiftBps;
        return 0;
    }

    function distributionAllowed() external view returns (bool) {
        (int256 nav, uint256 riskAssets,, uint256 k, uint256 s) = metrics();
        return mode == Mode.GREEN && nav >= minHardNAV1e18 &&
            _portfolioLimitsSatisfied(riskAssets) &&
            k >= thresholds.distributionCoverageBps && s >= thresholds.distributionSTSBps;
    }

    function pokeMode() external returns (Mode next) {
        (int256 nav, uint256 riskAssets,, uint256 k, uint256 s) = metrics();
        uint256 concentration = maxSingleAssetConcentrationBps();
        Mode old = mode;
        Thresholds memory t = thresholds;
        PortfolioLimits memory p = portfolioLimits;

        if (
            nav < minHardNAV1e18 || riskAssets < p.minRiskAssets1e18 ||
            k < t.orangeCoverageBps || s < t.orangeSTSBps
        ) {
            next = Mode.RED;
        } else if (concentration > p.maxSingleAssetConcentrationBps) {
            // Concentration is a portfolio-quality breach, not necessarily insolvency.
            // Move to ORANGE: no new expansion, but unwind/restore remains available.
            next = Mode.ORANGE;
        } else if (old == Mode.RED) {
            next = (k >= uint256(t.orangeCoverageBps) + t.yellowReentryBufferBps &&
                    s >= uint256(t.orangeSTSBps) + t.yellowReentryBufferBps)
                ? Mode.ORANGE : Mode.RED;
        } else if (old == Mode.ORANGE) {
            next = (k >= uint256(t.yellowCoverageBps) + t.yellowReentryBufferBps &&
                    s >= uint256(t.yellowSTSBps) + t.yellowReentryBufferBps)
                ? Mode.YELLOW : Mode.ORANGE;
        } else if (old == Mode.YELLOW) {
            if (k < t.yellowCoverageBps || s < t.yellowSTSBps) next = Mode.ORANGE;
            else if (k >= uint256(t.greenCoverageBps) + t.greenReentryBufferBps &&
                     s >= uint256(t.greenSTSBps) + t.greenReentryBufferBps) next = Mode.GREEN;
            else next = Mode.YELLOW;
        } else {
            next = (k < t.greenCoverageBps || s < t.greenSTSBps) ? Mode.YELLOW : Mode.GREEN;
        }

        if (next != old) {
            mode = next;
            emit ModeChanged(old, next, k, s, nav);
        }
    }
}
