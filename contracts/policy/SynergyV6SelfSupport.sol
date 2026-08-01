// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

interface IParticipantTaxRegistryV6 {
    function isEligible(address participant) external view returns (bool);
}

interface ISystemBoundaryV6 {
    function isSystemAddress(address account) external view returns (bool);
}

interface IRealLiquidityRiskGateV6 {
    function latestPass() external view returns (bool);
    function latestInvariantWad() external view returns (uint256);
}

interface IProfitReinvestmentEngineV6 {
    function reinvestProfitFor(address beneficiary, uint256 amountPol)
        external
        returns (uint256 polUsed);
    function depositRetainedProfit(uint256 amountPol)
        external
        returns (uint256 polUsed);
    function originalExternalCapitalPol() external view returns (uint256);
    function totalBackedCapitalPol() external view returns (uint256);
    function internalTransferRevenuePol() external view returns (uint256);
}

/// @notice Revenue first covers a bounded keeper reimbursement. Only the
/// remaining realised external profit is eligible for tax and compounding.
contract AutoReinvestDividendControllerV6 {
    using SafeERC20 for IERC20;

    uint256 public constant BPS = 10_000;
    uint256 public constant DIVIDEND_POOL_BPS = 1_000;
    uint256 public constant OWNER_SHARE_OF_DIVIDEND_BPS = 5_000;
    uint256 public constant WAD = 1e18;

    IERC20 public immutable reserveAsset;
    IParticipantTaxRegistryV6 public immutable registry;
    ISystemBoundaryV6 public immutable boundary;
    IRealLiquidityRiskGateV6 public immutable riskGate;
    IProfitReinvestmentEngineV6 public immutable engine;
    address public immutable ownerBeneficiary;
    address public immutable protocolTreasury;
    address public immutable taxEscrow;
    uint256 public immutable bootstrapOriginalCapitalPol;
    uint256 public immutable maxKeeperCostBps;

    address public admin;
    uint256 public withholdingBps;
    uint256 public minimumInvariantWad;
    mapping(address => bool) public operator;
    mapping(bytes32 => bool) public sourceUsed;

    uint256 public cumulativeGrossExternalRevenue;
    uint256 public cumulativeKeeperCostReimbursed;
    uint256 public cumulativeNetExternalProfit;
    uint256 public cumulativeRetainedReinvestment;
    uint256 public cumulativeGrossDividends;
    uint256 public cumulativeOwnerNetReinvestment;
    uint256 public cumulativeKeeperNetReinvestment;
    uint256 public cumulativeTaxWithheld;
    uint256 public cumulativeCashDividendPaid;

    error Unauthorized();
    error InvalidAddress();
    error InvalidAmount();
    error InvalidPolicy();
    error SourceAlreadyUsed();
    error SystemPayerForbidden();
    error ParticipantNotEligible();
    error RiskInvariantNotMet();
    error BalanceDeltaMismatch();
    error BootstrapCapitalChanged();
    error KeeperCostTooHigh();
    error NoNetProfit();
    error InternalRevenueForbidden();

    event OperatorSet(address indexed account, bool enabled);
    event ExternalRevenueCompounded(
        bytes32 indexed sourceId,
        address indexed externalPayer,
        address indexed keeperUser,
        uint256 grossExternalRevenue,
        uint256 keeperCostReimbursed,
        uint256 netExternalProfit,
        uint256 retainedReinvestment,
        uint256 ownerNetReinvestment,
        uint256 keeperNetReinvestment,
        uint256 taxWithheld
    );

    constructor(
        address reserveAsset_,
        address registry_,
        address boundary_,
        address riskGate_,
        address engine_,
        address ownerBeneficiary_,
        address protocolTreasury_,
        address taxEscrow_,
        uint256 bootstrapOriginalCapitalPol_,
        uint256 withholdingBps_,
        uint256 minimumInvariantWad_,
        uint256 maxKeeperCostBps_
    ) {
        if (
            reserveAsset_ == address(0) || registry_ == address(0) ||
            boundary_ == address(0) || riskGate_ == address(0) ||
            engine_ == address(0) || ownerBeneficiary_ == address(0) ||
            protocolTreasury_ == address(0) || taxEscrow_ == address(0)
        ) revert InvalidAddress();
        if (
            bootstrapOriginalCapitalPol_ == 0 || withholdingBps_ > 5_000 ||
            minimumInvariantWad_ < WAD || maxKeeperCostBps_ == 0 ||
            maxKeeperCostBps_ > 2_000
        ) revert InvalidPolicy();

        reserveAsset = IERC20(reserveAsset_);
        registry = IParticipantTaxRegistryV6(registry_);
        boundary = ISystemBoundaryV6(boundary_);
        riskGate = IRealLiquidityRiskGateV6(riskGate_);
        engine = IProfitReinvestmentEngineV6(engine_);
        ownerBeneficiary = ownerBeneficiary_;
        protocolTreasury = protocolTreasury_;
        taxEscrow = taxEscrow_;
        bootstrapOriginalCapitalPol = bootstrapOriginalCapitalPol_;
        withholdingBps = withholdingBps_;
        minimumInvariantWad = minimumInvariantWad_;
        maxKeeperCostBps = maxKeeperCostBps_;
        admin = msg.sender;
        operator[msg.sender] = true;
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyOperator() {
        if (!operator[msg.sender]) revert Unauthorized();
        _;
    }

    function setOperator(address account, bool enabled) external onlyAdmin {
        if (account == address(0)) revert InvalidAddress();
        operator[account] = enabled;
        emit OperatorSet(account, enabled);
    }

    function bootstrapCapitalIntact() public view returns (bool) {
        return engine.originalExternalCapitalPol() == bootstrapOriginalCapitalPol;
    }

    function settleExternalRevenue(
        address externalPayer,
        uint256 grossExternalRevenue,
        uint256 approvedKeeperCost,
        address keeperUser,
        bytes32 sourceId
    ) external onlyOperator {
        if (
            externalPayer == address(0) || keeperUser == address(0) ||
            sourceId == bytes32(0)
        ) revert InvalidAddress();
        if (grossExternalRevenue == 0) revert InvalidAmount();
        if (sourceUsed[sourceId]) revert SourceAlreadyUsed();
        if (!bootstrapCapitalIntact()) revert BootstrapCapitalChanged();
        if (engine.internalTransferRevenuePol() != 0) {
            revert InternalRevenueForbidden();
        }
        if (boundary.isSystemAddress(externalPayer)) revert SystemPayerForbidden();
        if (
            !registry.isEligible(ownerBeneficiary) ||
            !registry.isEligible(keeperUser)
        ) revert ParticipantNotEligible();
        if (
            !riskGate.latestPass() ||
            riskGate.latestInvariantWad() < minimumInvariantWad
        ) revert RiskInvariantNotMet();
        if (
            approvedKeeperCost >
            Math.mulDiv(grossExternalRevenue, maxKeeperCostBps, BPS)
        ) revert KeeperCostTooHigh();
        if (approvedKeeperCost >= grossExternalRevenue) revert NoNetProfit();

        uint256 beforeBalance = reserveAsset.balanceOf(address(this));
        reserveAsset.safeTransferFrom(
            externalPayer,
            address(this),
            grossExternalRevenue
        );
        uint256 delta = reserveAsset.balanceOf(address(this)) - beforeBalance;
        if (delta != grossExternalRevenue) revert BalanceDeltaMismatch();

        sourceUsed[sourceId] = true;
        if (approvedKeeperCost > 0) {
            reserveAsset.safeTransfer(keeperUser, approvedKeeperCost);
        }

        uint256 netExternalProfit = grossExternalRevenue - approvedKeeperCost;
        uint256 grossDividendPool =
            Math.mulDiv(netExternalProfit, DIVIDEND_POOL_BPS, BPS);
        uint256 ownerGross = Math.mulDiv(
            grossDividendPool,
            OWNER_SHARE_OF_DIVIDEND_BPS,
            BPS
        );
        uint256 keeperGross = grossDividendPool - ownerGross;
        uint256 ownerTax = Math.mulDiv(ownerGross, withholdingBps, BPS);
        uint256 keeperTax = Math.mulDiv(keeperGross, withholdingBps, BPS);
        uint256 taxWithheld = ownerTax + keeperTax;
        uint256 ownerNet = ownerGross - ownerTax;
        uint256 keeperNet = keeperGross - keeperTax;
        uint256 retained = netExternalProfit - grossDividendPool;

        if (taxWithheld > 0) reserveAsset.safeTransfer(taxEscrow, taxWithheld);
        uint256 compoundAmount = retained + ownerNet + keeperNet;
        reserveAsset.forceApprove(address(engine), compoundAmount);
        if (retained > 0) engine.depositRetainedProfit(retained);
        if (ownerNet > 0) engine.reinvestProfitFor(ownerBeneficiary, ownerNet);
        if (keeperNet > 0) engine.reinvestProfitFor(keeperUser, keeperNet);

        cumulativeGrossExternalRevenue += grossExternalRevenue;
        cumulativeKeeperCostReimbursed += approvedKeeperCost;
        cumulativeNetExternalProfit += netExternalProfit;
        cumulativeRetainedReinvestment += retained;
        cumulativeGrossDividends += grossDividendPool;
        cumulativeOwnerNetReinvestment += ownerNet;
        cumulativeKeeperNetReinvestment += keeperNet;
        cumulativeTaxWithheld += taxWithheld;

        emit ExternalRevenueCompounded(
            sourceId,
            externalPayer,
            keeperUser,
            grossExternalRevenue,
            approvedKeeperCost,
            netExternalProfit,
            retained,
            ownerNet,
            keeperNet,
            taxWithheld
        );
    }
}

/// @notice One scalar proof of no-new-capital self-support.
contract DividendSelfSupportInvariantV6 {
    uint256 public constant WAD = 1e18;
    uint256 public constant MIN_MULTIPLIER_WAD = 3e18;

    struct Metrics {
        uint256 bootstrapOriginalCapitalPol;
        uint256 currentOriginalExternalCapitalPol;
        uint256 totalBackedCapitalPol;
        uint256 cumulativeGrossExternalRevenuePol;
        uint256 cumulativeKeeperCostReimbursedPol;
        uint256 cumulativeTaxWithheldPol;
        uint256 retainedReinvestedPol;
        uint256 ownerReinvestedPol;
        uint256 keeperReinvestedPol;
        uint256 cashDividendPaidPol;
        uint256 internalTransferRevenuePol;
        uint256 recognisedMultiplierWad;
        uint256 riskInvariantWad;
        uint256 actualKeeperGasCostPol;
    }

    function preview(Metrics calldata m)
        external
        pure
        returns (uint256 invariantWad, bool pass)
    {
        if (
            m.bootstrapOriginalCapitalPol == 0 ||
            m.cumulativeGrossExternalRevenuePol <
                m.cumulativeKeeperCostReimbursedPol
        ) return (0, false);

        uint256 netExternalProfit =
            m.cumulativeGrossExternalRevenuePol -
            m.cumulativeKeeperCostReimbursedPol;
        if (netExternalProfit < m.cumulativeTaxWithheldPol) return (0, false);

        uint256 expectedReinvestment =
            netExternalProfit - m.cumulativeTaxWithheldPol;
        uint256 actualReinvestment =
            m.retainedReinvestedPol + m.ownerReinvestedPol +
            m.keeperReinvestedPol;
        uint256 expectedCapital =
            m.bootstrapOriginalCapitalPol + expectedReinvestment;

        bool hardGates =
            m.currentOriginalExternalCapitalPol ==
                m.bootstrapOriginalCapitalPol &&
            m.cashDividendPaidPol == 0 &&
            m.internalTransferRevenuePol == 0 &&
            m.recognisedMultiplierWad >= MIN_MULTIPLIER_WAD &&
            m.riskInvariantWad >= WAD &&
            m.cumulativeKeeperCostReimbursedPol >=
                m.actualKeeperGasCostPol;
        if (!hardGates) return (0, false);

        uint256 multiplierScore = Math.mulDiv(
            m.recognisedMultiplierWad,
            WAD,
            MIN_MULTIPLIER_WAD
        );
        uint256 costCoverageScore = _coverage(
            m.cumulativeGrossExternalRevenuePol,
            m.cumulativeKeeperCostReimbursedPol
        );
        uint256 keeperCoverageScore = _coverage(
            m.cumulativeKeeperCostReimbursedPol,
            m.actualKeeperGasCostPol
        );
        uint256 capitalIdentityScore = _symmetryScore(
            m.totalBackedCapitalPol,
            expectedCapital
        );
        uint256 reinvestmentIdentityScore = _symmetryScore(
            actualReinvestment,
            expectedReinvestment
        );

        invariantWad = m.riskInvariantWad;
        invariantWad = Math.min(invariantWad, multiplierScore);
        invariantWad = Math.min(invariantWad, costCoverageScore);
        invariantWad = Math.min(invariantWad, keeperCoverageScore);
        invariantWad = Math.min(invariantWad, capitalIdentityScore);
        invariantWad = Math.min(invariantWad, reinvestmentIdentityScore);
        pass = invariantWad >= WAD;
    }

    function _coverage(uint256 numerator, uint256 denominator)
        private
        pure
        returns (uint256)
    {
        if (denominator == 0) return 2 * WAD;
        return Math.mulDiv(numerator, WAD, denominator);
    }

    function _symmetryScore(uint256 a, uint256 b)
        private
        pure
        returns (uint256)
    {
        if (a == b) return WAD;
        if (a == 0 || b == 0) return 0;
        return Math.min(
            Math.mulDiv(a, WAD, b),
            Math.mulDiv(b, WAD, a)
        );
    }
}
