// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

interface IParticipantRegistryV6 {
    function isEligible(address participant) external view returns (bool);
}

interface ISystemBoundaryV6 {
    function isSystemAddress(address account) external view returns (bool);
}

interface IRiskGateV6 {
    function latestPass() external view returns (bool);
    function latestInvariantWad() external view returns (uint256);
}

interface IProfitEngineV6 {
    function reinvestProfitFor(address beneficiary, uint256 amountPol)
        external
        returns (uint256 polUsed);

    function depositRetainedProfit(uint256 amountPol)
        external
        returns (uint256 polUsed);
}

/// @notice V6 settles external operating revenue without accepting new investor
/// capital after bootstrap. Keeper execution expense is reimbursed before net
/// profit, dividend and tax calculations. Every net dividend is reinvested.
contract AutoReinvestDividendControllerV6 {
    using SafeERC20 for IERC20;

    uint256 public constant BPS = 10_000;
    uint256 public constant WAD = 1e18;
    uint256 public constant DIVIDEND_POOL_BPS = 1_000; // 10% of net profit
    uint256 public constant OWNER_SHARE_BPS = 5_000; // half of dividend pool

    IERC20 public immutable reserveAsset;
    IParticipantRegistryV6 public immutable registry;
    ISystemBoundaryV6 public immutable boundary;
    IRiskGateV6 public immutable riskGate;
    IProfitEngineV6 public immutable engine;

    address public immutable ownerBeneficiary;
    address public immutable protocolTreasury;
    address public immutable taxEscrow;
    address public admin;

    uint256 public withholdingBps;
    uint256 public minimumInvariantWad;
    uint256 public maximumKeeperReimbursementBps;

    mapping(address => bool) public operator;
    mapping(bytes32 => bool) public sourceUsed;

    uint256 public cumulativeGrossOperatingRevenue;
    uint256 public cumulativeKeeperExpenseReimbursed;
    uint256 public cumulativeNetExternalProfit;
    uint256 public cumulativeRetainedReinvestment;
    uint256 public cumulativeGrossDividends;
    uint256 public cumulativeOwnerNetReinvestment;
    uint256 public cumulativeKeeperNetReinvestment;
    uint256 public cumulativeTaxWithheld;

    error Unauthorized();
    error InvalidAddress();
    error InvalidAmount();
    error InvalidPolicy();
    error SourceAlreadyUsed();
    error SystemPayerForbidden();
    error ParticipantNotEligible();
    error RiskInvariantNotMet();
    error BalanceDeltaMismatch();
    error KeeperExpenseTooLarge();
    error NoDistributableProfit();

    event OperatorSet(address indexed account, bool enabled);
    event PolicySet(
        uint256 withholdingBps,
        uint256 minimumInvariantWad,
        uint256 maximumKeeperReimbursementBps
    );
    event ExternalOperatingProfitCompounded(
        bytes32 indexed sourceId,
        address indexed externalPayer,
        address indexed keeperUser,
        uint256 grossOperatingRevenue,
        uint256 keeperExpenseReimbursed,
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
        uint256 withholdingBps_,
        uint256 minimumInvariantWad_,
        uint256 maximumKeeperReimbursementBps_
    ) {
        if (
            reserveAsset_ == address(0) ||
            registry_ == address(0) ||
            boundary_ == address(0) ||
            riskGate_ == address(0) ||
            engine_ == address(0) ||
            ownerBeneficiary_ == address(0) ||
            protocolTreasury_ == address(0) ||
            taxEscrow_ == address(0)
        ) revert InvalidAddress();
        if (
            withholdingBps_ > 5_000 ||
            minimumInvariantWad_ < WAD ||
            maximumKeeperReimbursementBps_ > 2_000
        ) revert InvalidPolicy();

        reserveAsset = IERC20(reserveAsset_);
        registry = IParticipantRegistryV6(registry_);
        boundary = ISystemBoundaryV6(boundary_);
        riskGate = IRiskGateV6(riskGate_);
        engine = IProfitEngineV6(engine_);
        ownerBeneficiary = ownerBeneficiary_;
        protocolTreasury = protocolTreasury_;
        taxEscrow = taxEscrow_;
        admin = msg.sender;
        withholdingBps = withholdingBps_;
        minimumInvariantWad = minimumInvariantWad_;
        maximumKeeperReimbursementBps = maximumKeeperReimbursementBps_;
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

    function setPolicy(
        uint256 nextWithholdingBps,
        uint256 nextMinimumInvariantWad,
        uint256 nextMaximumKeeperReimbursementBps
    ) external onlyAdmin {
        if (
            nextWithholdingBps > 5_000 ||
            nextMinimumInvariantWad < WAD ||
            nextMaximumKeeperReimbursementBps > 2_000
        ) revert InvalidPolicy();
        withholdingBps = nextWithholdingBps;
        minimumInvariantWad = nextMinimumInvariantWad;
        maximumKeeperReimbursementBps = nextMaximumKeeperReimbursementBps;
        emit PolicySet(
            nextWithholdingBps,
            nextMinimumInvariantWad,
            nextMaximumKeeperReimbursementBps
        );
    }

    function settleExternalOperatingRevenue(
        address externalPayer,
        uint256 grossOperatingRevenue,
        address keeperUser,
        uint256 keeperExpensePol,
        bytes32 sourceId
    ) external onlyOperator {
        if (
            externalPayer == address(0) ||
            keeperUser == address(0) ||
            sourceId == bytes32(0)
        ) revert InvalidAddress();
        if (grossOperatingRevenue == 0) revert InvalidAmount();
        if (sourceUsed[sourceId]) revert SourceAlreadyUsed();
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
            keeperExpensePol >
            Math.mulDiv(
                grossOperatingRevenue,
                maximumKeeperReimbursementBps,
                BPS
            )
        ) revert KeeperExpenseTooLarge();

        uint256 beforeBalance = reserveAsset.balanceOf(address(this));
        reserveAsset.safeTransferFrom(
            externalPayer,
            address(this),
            grossOperatingRevenue
        );
        uint256 delta = reserveAsset.balanceOf(address(this)) - beforeBalance;
        if (delta != grossOperatingRevenue) revert BalanceDeltaMismatch();

        uint256 netExternalProfit = grossOperatingRevenue - keeperExpensePol;
        if (netExternalProfit == 0) revert NoDistributableProfit();
        sourceUsed[sourceId] = true;

        if (keeperExpensePol > 0) {
            reserveAsset.safeTransfer(keeperUser, keeperExpensePol);
        }

        uint256 dividendPool = Math.mulDiv(
            netExternalProfit,
            DIVIDEND_POOL_BPS,
            BPS
        );
        uint256 ownerGross = Math.mulDiv(
            dividendPool,
            OWNER_SHARE_BPS,
            BPS
        );
        uint256 keeperGross = dividendPool - ownerGross;
        uint256 ownerTax = Math.mulDiv(ownerGross, withholdingBps, BPS);
        uint256 keeperTax = Math.mulDiv(keeperGross, withholdingBps, BPS);
        uint256 taxWithheld = ownerTax + keeperTax;
        uint256 ownerNet = ownerGross - ownerTax;
        uint256 keeperNet = keeperGross - keeperTax;
        uint256 retained = netExternalProfit - dividendPool;

        if (taxWithheld > 0) {
            reserveAsset.safeTransfer(taxEscrow, taxWithheld);
        }

        uint256 compoundAmount = retained + ownerNet + keeperNet;
        reserveAsset.forceApprove(address(engine), compoundAmount);
        if (retained > 0) engine.depositRetainedProfit(retained);
        if (ownerNet > 0) engine.reinvestProfitFor(ownerBeneficiary, ownerNet);
        if (keeperNet > 0) engine.reinvestProfitFor(keeperUser, keeperNet);

        cumulativeGrossOperatingRevenue += grossOperatingRevenue;
        cumulativeKeeperExpenseReimbursed += keeperExpensePol;
        cumulativeNetExternalProfit += netExternalProfit;
        cumulativeRetainedReinvestment += retained;
        cumulativeGrossDividends += dividendPool;
        cumulativeOwnerNetReinvestment += ownerNet;
        cumulativeKeeperNetReinvestment += keeperNet;
        cumulativeTaxWithheld += taxWithheld;

        emit ExternalOperatingProfitCompounded(
            sourceId,
            externalPayer,
            keeperUser,
            grossOperatingRevenue,
            keeperExpensePol,
            netExternalProfit,
            retained,
            ownerNet,
            keeperNet,
            taxWithheld
        );
    }
}

/// @notice One scalar for the exact V6 claim:
/// no post-bootstrap investor capital, multiplier/risk gate remains valid,
/// operating revenue covers external expense, and backed capital does not fall.
contract DividendSelfSustainInvariantV6 {
    using Math for uint256;

    uint256 public constant WAD = 1e18;

    struct Metrics {
        uint256 baseLiquidityRiskInvariantWad;
        uint256 bootstrapExternalCapitalPol;
        uint256 currentOriginalExternalCapitalPol;
        uint256 totalBackedCapitalPol;
        uint256 cumulativeGrossOperatingRevenuePol;
        uint256 cumulativeExternalExpensePol;
        uint256 internalTransferRevenuePol;
    }

    error InvalidMetrics();
    error NewInvestorCapitalForbidden();
    error InternalRevenueForbidden();

    function preview(Metrics calldata m)
        external
        pure
        returns (uint256 invariantWad, bool pass)
    {
        if (
            m.bootstrapExternalCapitalPol == 0 ||
            m.currentOriginalExternalCapitalPol == 0
        ) revert InvalidMetrics();
        if (
            m.currentOriginalExternalCapitalPol !=
            m.bootstrapExternalCapitalPol
        ) revert NewInvestorCapitalForbidden();
        if (m.internalTransferRevenuePol != 0) {
            revert InternalRevenueForbidden();
        }

        uint256 capitalScore = Math.mulDiv(
            m.totalBackedCapitalPol,
            WAD,
            m.bootstrapExternalCapitalPol
        );
        uint256 operatingScore;
        if (m.cumulativeGrossOperatingRevenuePol == 0) {
            operatingScore = 0;
        } else if (m.cumulativeExternalExpensePol == 0) {
            operatingScore = type(uint256).max;
        } else {
            operatingScore = Math.mulDiv(
                m.cumulativeGrossOperatingRevenuePol,
                WAD,
                m.cumulativeExternalExpensePol
            );
        }

        invariantWad = Math.min(
            m.baseLiquidityRiskInvariantWad,
            Math.min(capitalScore, operatingScore)
        );
        pass = invariantWad >= WAD;
    }
}
