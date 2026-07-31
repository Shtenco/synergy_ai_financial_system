// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

/// @notice One scalar gate for the SYNERGY 3-5x real-liquidity policy.
/// @dev "Liquidity" means recognised stress V2-equivalent executable depth.
/// It never means withdrawable POL, token market cap or nominal TVL.
contract RealLiquidityMultiplierInvariant {
    using Math for uint256;

    uint256 public constant WAD = 1e18;
    uint256 public constant LOW_VOL_TARGET = 5e18;
    uint256 public constant NORMAL_VOL_TARGET = 4e18;
    uint256 public constant HIGH_VOL_TARGET = 3e18;
    uint256 public constant MAX_RECOGNISED_MULTIPLIER = 5e18;

    uint256 public constant LOW_VOL_MAX_SIGMA = 0.025e18;
    uint256 public constant NORMAL_VOL_MAX_SIGMA = 0.070e18;
    uint256 public constant MAX_SUPPORTED_SIGMA = 0.120e18;

    uint256 public constant SOLVENCY_FLOOR = 1.20e18;
    uint256 public constant LIQUIDITY_FLOOR = 1.20e18;
    uint256 public constant GAS_FLOOR = 1.20e18;
    uint256 public constant EMISSION_COVERAGE_FLOOR = 1.20e18;

    struct Metrics {
        uint256 sigmaWad;
        uint256 stressEquivalentLiquidityPol;
        uint256 netExternalCapitalPol;
        uint256 haircutAssetsPol;
        uint256 stressLiabilitiesPol;
        uint256 immediateLiquidityPol;
        uint256 stressedOutflowsPol;
        uint256 gasReservePlusSpentPol;
        uint256 gasSpentPol;
        uint256 externalEmissionBackingPol;
        uint256 externalEmissionLiabilityPol;
        uint256 minimumAnchorPoolPol;
        uint256 poolFloorPol;
        uint256 crossPoolInternalNotional;
        uint256 internalTransferRevenuePol;
    }

    address public admin;
    address public reporter;
    mapping(bytes32 => bool) public snapshotUsed;

    Metrics public latestMetrics;
    bytes32 public latestSnapshotId;
    uint256 public latestInvariantWad;
    uint256 public latestTargetMultiplierWad;
    bool public latestPass;

    error Unauthorized();
    error InvalidAddress();
    error InvalidMetrics();
    error SnapshotAlreadyUsed();
    error InternalRevenueForbidden();
    error MultiplierOverclaim();

    event ReporterSet(address indexed reporter);
    event SnapshotRecorded(
        bytes32 indexed snapshotId,
        uint256 targetMultiplierWad,
        uint256 invariantWad,
        bool pass,
        uint256 recognisedMultiplierWad,
        uint256 crossPoolInternalNotional
    );

    constructor(address admin_, address reporter_) {
        if (admin_ == address(0) || reporter_ == address(0)) revert InvalidAddress();
        admin = admin_;
        reporter = reporter_;
        emit ReporterSet(reporter_);
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyReporter() {
        if (msg.sender != reporter) revert Unauthorized();
        _;
    }

    function setReporter(address nextReporter) external onlyAdmin {
        if (nextReporter == address(0)) revert InvalidAddress();
        reporter = nextReporter;
        emit ReporterSet(nextReporter);
    }

    function transferAdmin(address nextAdmin) external onlyAdmin {
        if (nextAdmin == address(0)) revert InvalidAddress();
        admin = nextAdmin;
    }

    function targetMultiplier(uint256 sigmaWad) public pure returns (uint256) {
        if (sigmaWad <= LOW_VOL_MAX_SIGMA) return LOW_VOL_TARGET;
        if (sigmaWad <= NORMAL_VOL_MAX_SIGMA) return NORMAL_VOL_TARGET;
        if (sigmaWad <= MAX_SUPPORTED_SIGMA) return HIGH_VOL_TARGET;
        return type(uint256).max;
    }

    function recognisedMultiplierWad(Metrics memory m) public pure returns (uint256) {
        if (m.netExternalCapitalPol == 0) return 0;
        return Math.mulDiv(m.stressEquivalentLiquidityPol, WAD, m.netExternalCapitalPol);
    }

    function preview(Metrics memory m)
        public
        pure
        returns (uint256 invariantWad, uint256 targetWad, bool pass)
    {
        if (m.netExternalCapitalPol == 0 || m.poolFloorPol == 0) revert InvalidMetrics();
        if (m.internalTransferRevenuePol != 0) revert InternalRevenueForbidden();

        uint256 maximumRecognised = Math.mulDiv(
            m.netExternalCapitalPol,
            MAX_RECOGNISED_MULTIPLIER,
            WAD
        );
        if (m.stressEquivalentLiquidityPol > maximumRecognised) {
            revert MultiplierOverclaim();
        }

        targetWad = targetMultiplier(m.sigmaWad);
        if (targetWad == type(uint256).max) return (0, targetWad, false);

        uint256 requiredLiquidity = Math.mulDiv(
            m.netExternalCapitalPol,
            targetWad,
            WAD
        );
        uint256 multiplierScore = _score(
            m.stressEquivalentLiquidityPol,
            requiredLiquidity
        );
        uint256 solvencyScore = _floorScore(
            m.haircutAssetsPol,
            m.stressLiabilitiesPol,
            SOLVENCY_FLOOR
        );
        uint256 liquidityScore = _floorScore(
            m.immediateLiquidityPol,
            m.stressedOutflowsPol,
            LIQUIDITY_FLOOR
        );
        uint256 gasScore = _floorScore(
            m.gasReservePlusSpentPol,
            m.gasSpentPol,
            GAS_FLOOR
        );
        uint256 emissionScore = _floorScore(
            m.externalEmissionBackingPol,
            m.externalEmissionLiabilityPol,
            EMISSION_COVERAGE_FLOOR
        );
        uint256 poolScore = _score(m.minimumAnchorPoolPol, m.poolFloorPol);

        invariantWad = multiplierScore;
        invariantWad = Math.min(invariantWad, solvencyScore);
        invariantWad = Math.min(invariantWad, liquidityScore);
        invariantWad = Math.min(invariantWad, gasScore);
        invariantWad = Math.min(invariantWad, emissionScore);
        invariantWad = Math.min(invariantWad, poolScore);
        pass = invariantWad >= WAD;
    }

    function record(bytes32 snapshotId, Metrics calldata m)
        external
        onlyReporter
        returns (uint256 invariantWad, bool pass)
    {
        if (snapshotId == bytes32(0)) revert InvalidMetrics();
        if (snapshotUsed[snapshotId]) revert SnapshotAlreadyUsed();

        uint256 targetWad;
        (invariantWad, targetWad, pass) = preview(m);
        snapshotUsed[snapshotId] = true;
        latestMetrics = m;
        latestSnapshotId = snapshotId;
        latestInvariantWad = invariantWad;
        latestTargetMultiplierWad = targetWad;
        latestPass = pass;

        emit SnapshotRecorded(
            snapshotId,
            targetWad,
            invariantWad,
            pass,
            recognisedMultiplierWad(m),
            m.crossPoolInternalNotional
        );
    }

    function _floorScore(uint256 numerator, uint256 baseDenominator, uint256 floorWad)
        private
        pure
        returns (uint256)
    {
        if (baseDenominator == 0) return type(uint256).max;
        uint256 required = Math.mulDiv(baseDenominator, floorWad, WAD);
        return _score(numerator, required);
    }

    function _score(uint256 numerator, uint256 denominator)
        private
        pure
        returns (uint256)
    {
        if (denominator == 0) return type(uint256).max;
        return Math.mulDiv(numerator, WAD, denominator);
    }
}
