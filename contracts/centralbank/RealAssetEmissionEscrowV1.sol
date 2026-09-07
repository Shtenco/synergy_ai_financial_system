// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {Math} from "@openzeppelin/contracts/utils/math/Math.sol";

interface IEmissionEscrowTokenV1 {
    function mint(address to, uint256 amount) external returns (uint256 minted);
    function burn(address from, uint256 amount) external returns (uint256 burned);
    function transfer(address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

/// @title RealAssetEmissionEscrowV1
/// @notice Target emission proposed by AI, approved by independent risk authority,
///         minted only into escrow, and released only against Financial-OS-attested
///         eligible real/external asset growth.
///
/// Authority model:
/// - AI proposer: may propose only. It cannot approve, mint, attest growth, or release.
/// - Risk authority: may approve/cap proposals and allocate verified growth credit.
/// - Financial OS authority: may attest accounting closes and create growth credit.
/// - Governance: emergency pause and role rotation. Expected to be a timelocked multisig.
///
/// Economic firewall:
/// - internal mark/rebase/own-LP repricing does not create growth credit;
/// - flash principal does not create growth credit;
/// - liability-funded asset growth is netted before credit;
/// - credited growth is additionally capped by positive HardNAV growth;
/// - one Financial OS close id can be consumed only once.
contract RealAssetEmissionEscrowV1 {
    uint256 public constant BPS = 10_000;
    uint256 public constant MAX_COVERAGE_BPS = 50_000; // 500%

    enum ProposalStatus {
        NONE,
        PROPOSED,
        LOCKED,
        RELEASED,
        CANCELLED,
        EXPIRED
    }

    struct EmissionProposal {
        address beneficiary;
        uint64 createdAt;
        uint64 expiresAt;
        ProposalStatus status;
        uint16 coverageBps;
        uint256 requestedAmount;
        uint256 approvedAmount;
        uint256 releasedAmount;
        uint256 consumedGrowthUsdE18;
        uint256 requiredGrowthUsdE18;
        uint256 unitValueUsdE18;
        bytes32 policyRef;
        bytes32 aiModelRef;
        bytes32 riskApprovalRef;
    }

    IEmissionEscrowTokenV1 public immutable token;
    uint256 public immutable tokenUnit;
    uint256 public immutable globalEmissionCap;
    address public immutable governance;

    address public aiProposer;
    address public riskAuthority;
    address public financialOsAuthority;
    uint16 public minCoverageBps;
    bool public paused;

    uint256 public proposalNonce;
    uint256 public totalMintedIntoEscrow;
    uint256 public totalLockedEmission;
    uint256 public totalReleasedEmission;
    uint256 public totalBurnedEmission;

    bool public baselineInitialized;
    uint64 public lastCloseSequence;
    uint256 public lastHardNavUsdE18;
    uint256 public lastLiabilitiesUsdE18;
    uint256 public availableGrowthCreditUsdE18;
    uint256 public cumulativeGrowthCreditUsdE18;

    mapping(uint256 => EmissionProposal) public proposals;
    mapping(bytes32 => bool) public usedCloseIds;

    uint256 private _unlocked = 1;

    event AuthoritiesUpdated(address aiProposer, address riskAuthority, address financialOsAuthority);
    event Paused(address indexed caller);
    event Unpaused(address indexed caller);
    event EmissionProposed(
        uint256 indexed proposalId,
        address indexed beneficiary,
        uint256 requestedAmount,
        uint64 expiresAt,
        bytes32 policyRef,
        bytes32 aiModelRef
    );
    event EmissionApprovedAndLocked(
        uint256 indexed proposalId,
        uint256 approvedAmount,
        uint256 unitValueUsdE18,
        uint16 coverageBps,
        uint256 requiredGrowthUsdE18,
        bytes32 riskApprovalRef
    );
    event FinancialBaselineInitialized(
        bytes32 indexed closeId,
        uint64 indexed sequence,
        uint256 hardNavUsdE18,
        uint256 liabilitiesUsdE18,
        bytes32 evidenceRef
    );
    event FinancialCloseRecorded(
        bytes32 indexed closeId,
        uint64 indexed sequence,
        uint256 hardNavUsdE18,
        uint256 liabilitiesUsdE18,
        uint256 eligibleAssetGrossGrowthUsdE18,
        uint256 liabilityIncreaseUsdE18,
        uint256 creditedGrowthUsdE18,
        int256 internalMarkChangeUsdE18,
        uint256 flashPrincipalInflowUsdE18,
        bytes32 evidenceRef
    );
    event EmissionReleased(
        uint256 indexed proposalId,
        address indexed beneficiary,
        uint256 releasedTokens,
        uint256 consumedGrowthUsdE18,
        uint256 cumulativeReleasedTokens
    );
    event EmissionCancelled(uint256 indexed proposalId, uint256 burnedTokens, bytes32 reasonRef);
    event EmissionExpired(uint256 indexed proposalId, uint256 burnedTokens);

    modifier onlyGovernance() {
        require(msg.sender == governance, "GOVERNANCE_ONLY");
        _;
    }

    modifier onlyAiProposer() {
        require(msg.sender == aiProposer, "AI_PROPOSER_ONLY");
        _;
    }

    modifier onlyRiskAuthority() {
        require(msg.sender == riskAuthority, "RISK_AUTHORITY_ONLY");
        _;
    }

    modifier onlyFinancialOs() {
        require(msg.sender == financialOsAuthority, "FINANCIAL_OS_ONLY");
        _;
    }

    modifier whenNotPaused() {
        require(!paused, "PAUSED");
        _;
    }

    modifier nonReentrant() {
        require(_unlocked == 1, "REENTRANCY");
        _unlocked = 0;
        _;
        _unlocked = 1;
    }

    constructor(
        address token_,
        uint256 tokenUnit_,
        uint256 globalEmissionCap_,
        address governance_,
        address aiProposer_,
        address riskAuthority_,
        address financialOsAuthority_,
        uint16 minCoverageBps_
    ) {
        require(token_ != address(0), "ZERO_TOKEN");
        require(tokenUnit_ > 0, "ZERO_TOKEN_UNIT");
        require(globalEmissionCap_ > 0, "ZERO_CAP");
        require(governance_ != address(0), "ZERO_GOVERNANCE");
        require(aiProposer_ != address(0), "ZERO_AI");
        require(riskAuthority_ != address(0), "ZERO_RISK");
        require(financialOsAuthority_ != address(0), "ZERO_FINANCIAL_OS");
        require(minCoverageBps_ >= BPS && minCoverageBps_ <= MAX_COVERAGE_BPS, "BAD_MIN_COVERAGE");

        token = IEmissionEscrowTokenV1(token_);
        tokenUnit = tokenUnit_;
        globalEmissionCap = globalEmissionCap_;
        governance = governance_;
        aiProposer = aiProposer_;
        riskAuthority = riskAuthority_;
        financialOsAuthority = financialOsAuthority_;
        minCoverageBps = minCoverageBps_;
    }

    /// @notice Governance is expected to be a timelocked multisig. AI cannot rotate itself.
    function setAuthorities(address aiProposer_, address riskAuthority_, address financialOsAuthority_)
        external
        onlyGovernance
    {
        require(aiProposer_ != address(0) && riskAuthority_ != address(0) && financialOsAuthority_ != address(0), "ZERO_ROLE");
        aiProposer = aiProposer_;
        riskAuthority = riskAuthority_;
        financialOsAuthority = financialOsAuthority_;
        emit AuthoritiesUpdated(aiProposer_, riskAuthority_, financialOsAuthority_);
    }

    function setMinCoverageBps(uint16 newMinCoverageBps) external onlyGovernance {
        require(newMinCoverageBps >= BPS && newMinCoverageBps <= MAX_COVERAGE_BPS, "BAD_MIN_COVERAGE");
        minCoverageBps = newMinCoverageBps;
    }

    function pause() external onlyGovernance {
        paused = true;
        emit Paused(msg.sender);
    }

    function unpause() external onlyGovernance {
        paused = false;
        emit Unpaused(msg.sender);
    }

    /// @notice AI can only submit a bounded target. No token is minted here.
    function proposeEmission(
        address beneficiary,
        uint256 requestedAmount,
        uint64 expiresAt,
        bytes32 policyRef,
        bytes32 aiModelRef
    ) external onlyAiProposer whenNotPaused returns (uint256 proposalId) {
        require(beneficiary != address(0), "ZERO_BENEFICIARY");
        require(requestedAmount > 0, "ZERO_AMOUNT");
        require(expiresAt > block.timestamp, "BAD_EXPIRY");
        require(policyRef != bytes32(0), "ZERO_POLICY_REF");
        require(aiModelRef != bytes32(0), "ZERO_MODEL_REF");

        proposalId = ++proposalNonce;
        proposals[proposalId] = EmissionProposal({
            beneficiary: beneficiary,
            createdAt: uint64(block.timestamp),
            expiresAt: expiresAt,
            status: ProposalStatus.PROPOSED,
            coverageBps: 0,
            requestedAmount: requestedAmount,
            approvedAmount: 0,
            releasedAmount: 0,
            consumedGrowthUsdE18: 0,
            requiredGrowthUsdE18: 0,
            unitValueUsdE18: 0,
            policyRef: policyRef,
            aiModelRef: aiModelRef,
            riskApprovalRef: bytes32(0)
        });

        emit EmissionProposed(proposalId, beneficiary, requestedAmount, expiresAt, policyRef, aiModelRef);
    }

    /// @notice Independent risk authority caps the AI request and mints only into escrow.
    function approveAndLockEmission(
        uint256 proposalId,
        uint256 approvedAmount,
        uint256 unitValueUsdE18,
        uint16 coverageBps,
        bytes32 riskApprovalRef
    ) external onlyRiskAuthority whenNotPaused nonReentrant {
        EmissionProposal storage p = proposals[proposalId];
        require(p.status == ProposalStatus.PROPOSED, "NOT_PROPOSED");
        require(block.timestamp < p.expiresAt, "PROPOSAL_EXPIRED");
        require(approvedAmount > 0 && approvedAmount <= p.requestedAmount, "BAD_APPROVED_AMOUNT");
        require(unitValueUsdE18 > 0, "ZERO_UNIT_VALUE");
        require(coverageBps >= minCoverageBps && coverageBps <= MAX_COVERAGE_BPS, "BAD_COVERAGE");
        require(riskApprovalRef != bytes32(0), "ZERO_RISK_REF");
        require(totalMintedIntoEscrow + approvedAmount <= globalEmissionCap, "GLOBAL_CAP");

        uint256 minted = token.mint(address(this), approvedAmount);
        require(minted > 0 && minted <= approvedAmount, "BAD_MINT_RESULT");

        uint256 baseValueUsdE18 = Math.mulDiv(minted, unitValueUsdE18, tokenUnit, Math.Rounding.Ceil);
        uint256 requiredGrowthUsdE18 = Math.mulDiv(baseValueUsdE18, coverageBps, BPS, Math.Rounding.Ceil);
        require(requiredGrowthUsdE18 > 0, "ZERO_REQUIRED_GROWTH");

        p.status = ProposalStatus.LOCKED;
        p.coverageBps = coverageBps;
        p.approvedAmount = minted;
        p.requiredGrowthUsdE18 = requiredGrowthUsdE18;
        p.unitValueUsdE18 = unitValueUsdE18;
        p.riskApprovalRef = riskApprovalRef;

        totalMintedIntoEscrow += minted;
        totalLockedEmission += minted;
        _assertEscrowSolvent();

        emit EmissionApprovedAndLocked(
            proposalId,
            minted,
            unitValueUsdE18,
            coverageBps,
            requiredGrowthUsdE18,
            riskApprovalRef
        );
    }

    /// @notice First Financial OS close creates only a baseline; it never creates emission credit.
    function initializeFinancialBaseline(
        bytes32 closeId,
        uint64 sequence,
        uint256 hardNavUsdE18,
        uint256 liabilitiesUsdE18,
        bytes32 evidenceRef
    ) external onlyFinancialOs whenNotPaused {
        require(!baselineInitialized, "BASELINE_EXISTS");
        require(closeId != bytes32(0) && evidenceRef != bytes32(0), "ZERO_EVIDENCE");
        require(sequence > 0, "ZERO_SEQUENCE");
        require(!usedCloseIds[closeId], "CLOSE_REPLAY");

        usedCloseIds[closeId] = true;
        baselineInitialized = true;
        lastCloseSequence = sequence;
        lastHardNavUsdE18 = hardNavUsdE18;
        lastLiabilitiesUsdE18 = liabilitiesUsdE18;

        emit FinancialBaselineInitialized(closeId, sequence, hardNavUsdE18, liabilitiesUsdE18, evidenceRef);
    }

    /// @notice Financial OS attests a new accounting close.
    /// @dev eligibleAssetGrossGrowthUsdE18 must exclude mint/rebase/internal LP marks and flash principal.
    ///      Runtime credit is still capped by positive HardNAV growth and netted for liability increase.
    function recordFinancialClose(
        bytes32 closeId,
        uint64 sequence,
        uint256 hardNavUsdE18,
        uint256 liabilitiesUsdE18,
        uint256 eligibleAssetGrossGrowthUsdE18,
        int256 internalMarkChangeUsdE18,
        uint256 flashPrincipalInflowUsdE18,
        bytes32 evidenceRef
    ) external onlyFinancialOs whenNotPaused returns (uint256 creditedGrowthUsdE18) {
        require(baselineInitialized, "NO_BASELINE");
        require(closeId != bytes32(0) && evidenceRef != bytes32(0), "ZERO_EVIDENCE");
        require(sequence > lastCloseSequence, "NON_MONOTONIC_CLOSE");
        require(!usedCloseIds[closeId], "CLOSE_REPLAY");

        uint256 hardNavGrowth = hardNavUsdE18 > lastHardNavUsdE18
            ? hardNavUsdE18 - lastHardNavUsdE18
            : 0;
        uint256 liabilityIncrease = liabilitiesUsdE18 > lastLiabilitiesUsdE18
            ? liabilitiesUsdE18 - lastLiabilitiesUsdE18
            : 0;
        uint256 netEligibleAssetGrowth = eligibleAssetGrossGrowthUsdE18 > liabilityIncrease
            ? eligibleAssetGrossGrowthUsdE18 - liabilityIncrease
            : 0;

        creditedGrowthUsdE18 = hardNavGrowth < netEligibleAssetGrowth
            ? hardNavGrowth
            : netEligibleAssetGrowth;

        usedCloseIds[closeId] = true;
        lastCloseSequence = sequence;
        lastHardNavUsdE18 = hardNavUsdE18;
        lastLiabilitiesUsdE18 = liabilitiesUsdE18;

        if (creditedGrowthUsdE18 > 0) {
            availableGrowthCreditUsdE18 += creditedGrowthUsdE18;
            cumulativeGrowthCreditUsdE18 += creditedGrowthUsdE18;
        }

        emit FinancialCloseRecorded(
            closeId,
            sequence,
            hardNavUsdE18,
            liabilitiesUsdE18,
            eligibleAssetGrossGrowthUsdE18,
            liabilityIncrease,
            creditedGrowthUsdE18,
            internalMarkChangeUsdE18,
            flashPrincipalInflowUsdE18,
            evidenceRef
        );
    }

    /// @notice Risk authority allocates already-verified global growth credit to one target emission.
    ///         The release amount is deterministic and proportional to consumed verified growth.
    function releaseAgainstVerifiedGrowth(uint256 proposalId, uint256 maxGrowthCreditUsdE18)
        external
        onlyRiskAuthority
        whenNotPaused
        nonReentrant
        returns (uint256 releasedTokens, uint256 usedGrowthUsdE18)
    {
        EmissionProposal storage p = proposals[proposalId];
        require(p.status == ProposalStatus.LOCKED, "NOT_LOCKED");
        require(block.timestamp < p.expiresAt, "PROPOSAL_EXPIRED");
        require(maxGrowthCreditUsdE18 > 0, "ZERO_GROWTH_LIMIT");
        _assertEscrowSolvent();

        uint256 remainingGrowth = p.requiredGrowthUsdE18 - p.consumedGrowthUsdE18;
        usedGrowthUsdE18 = availableGrowthCreditUsdE18;
        if (usedGrowthUsdE18 > maxGrowthCreditUsdE18) usedGrowthUsdE18 = maxGrowthCreditUsdE18;
        if (usedGrowthUsdE18 > remainingGrowth) usedGrowthUsdE18 = remainingGrowth;
        require(usedGrowthUsdE18 > 0, "NO_VERIFIED_GROWTH_CREDIT");

        p.consumedGrowthUsdE18 += usedGrowthUsdE18;
        availableGrowthCreditUsdE18 -= usedGrowthUsdE18;

        uint256 targetReleased = p.consumedGrowthUsdE18 == p.requiredGrowthUsdE18
            ? p.approvedAmount
            : Math.mulDiv(p.approvedAmount, p.consumedGrowthUsdE18, p.requiredGrowthUsdE18);
        releasedTokens = targetReleased - p.releasedAmount;
        require(releasedTokens > 0, "RELEASE_DUST");

        p.releasedAmount = targetReleased;
        totalLockedEmission -= releasedTokens;
        totalReleasedEmission += releasedTokens;

        _safeTransfer(p.beneficiary, releasedTokens);

        if (p.releasedAmount == p.approvedAmount) {
            p.status = ProposalStatus.RELEASED;
        }

        _assertEscrowSolvent();
        emit EmissionReleased(proposalId, p.beneficiary, releasedTokens, usedGrowthUsdE18, p.releasedAmount);
    }

    function cancelProposal(uint256 proposalId, bytes32 reasonRef)
        external
        onlyRiskAuthority
        nonReentrant
    {
        require(reasonRef != bytes32(0), "ZERO_REASON");
        EmissionProposal storage p = proposals[proposalId];
        require(
            p.status == ProposalStatus.PROPOSED || p.status == ProposalStatus.LOCKED,
            "NOT_CANCELLABLE"
        );

        uint256 burned;
        if (p.status == ProposalStatus.LOCKED) {
            burned = p.approvedAmount - p.releasedAmount;
            if (burned > 0) {
                uint256 actualBurned = token.burn(address(this), burned);
                require(actualBurned == burned, "BAD_BURN_RESULT");
                totalLockedEmission -= burned;
                totalBurnedEmission += burned;
            }
        }
        p.status = ProposalStatus.CANCELLED;
        _assertEscrowSolvent();
        emit EmissionCancelled(proposalId, burned, reasonRef);
    }

    /// @notice Anyone may finalize a deterministic expiry. Unreleased locked emission is burned.
    function expireProposal(uint256 proposalId) external nonReentrant {
        EmissionProposal storage p = proposals[proposalId];
        require(
            p.status == ProposalStatus.PROPOSED || p.status == ProposalStatus.LOCKED,
            "NOT_EXPIRABLE"
        );
        require(block.timestamp >= p.expiresAt, "NOT_EXPIRED");

        uint256 burned;
        if (p.status == ProposalStatus.LOCKED) {
            burned = p.approvedAmount - p.releasedAmount;
            if (burned > 0) {
                uint256 actualBurned = token.burn(address(this), burned);
                require(actualBurned == burned, "BAD_BURN_RESULT");
                totalLockedEmission -= burned;
                totalBurnedEmission += burned;
            }
        }
        p.status = ProposalStatus.EXPIRED;
        _assertEscrowSolvent();
        emit EmissionExpired(proposalId, burned);
    }

    function remainingRequiredGrowthUsdE18(uint256 proposalId) external view returns (uint256) {
        EmissionProposal storage p = proposals[proposalId];
        if (p.requiredGrowthUsdE18 <= p.consumedGrowthUsdE18) return 0;
        return p.requiredGrowthUsdE18 - p.consumedGrowthUsdE18;
    }

    function escrowSurplus() external view returns (uint256) {
        uint256 balance = token.balanceOf(address(this));
        return balance > totalLockedEmission ? balance - totalLockedEmission : 0;
    }

    function _assertEscrowSolvent() internal view {
        require(token.balanceOf(address(this)) >= totalLockedEmission, "ESCROW_TOKEN_INSOLVENT");
    }

    function _safeTransfer(address to, uint256 amount) internal {
        (bool ok, bytes memory data) = address(token).call(
            abi.encodeWithSelector(IEmissionEscrowTokenV1.transfer.selector, to, amount)
        );
        require(ok && (data.length == 0 || abi.decode(data, (bool))), "TOKEN_TRANSFER_FAILED");
    }
}
