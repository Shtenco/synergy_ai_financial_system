// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface ISystemBoundaryRegistryLedger {
    function isSystemAddress(address account) external view returns (bool);
    function isInternalTransfer(address from, address to) external view returns (bool);
}

interface IERC20BalanceLedger {
    function balanceOf(address account) external view returns (uint256);
}

/// @notice Consolidated double-entry ledger. Internal transfers can never
/// modify external PnL or NAV. External revenue requires a proven token balance
/// delta and every sourceId can be consumed only once.
contract ConsolidatedLedger {
    enum Classification {
        INTERNAL_TRANSFER,
        EXTERNAL_REVENUE,
        EXTERNAL_EXPENSE,
        CAPITAL_INFLOW,
        CAPITAL_OUTFLOW,
        LIABILITY_ISSUANCE,
        LIABILITY_REDEMPTION,
        INVENTORY_TRANSFER,
        REALIZED_TRADING_PNL,
        UNREALIZED_REVALUATION,
        RESERVE_RECLASSIFICATION,
        DIVIDEND,
        LOSS
    }

    struct Entry {
        address asset;
        uint256 debit;
        uint256 credit;
        address from;
        address to;
        Classification classification;
        bytes32 sourceId;
        address externalCounterparty;
        int256 liabilityDelta;
        int256 realizedPnLDelta;
        int256 navDelta;
        uint64 timestamp;
    }

    address public admin;
    ISystemBoundaryRegistryLedger public immutable registry;
    mapping(address => bool) public recorder;
    mapping(bytes32 => bool) public sourceUsed;
    mapping(uint256 => Entry) public entries;
    uint256 public entryCount;

    uint256 public internalTransferVolume;
    uint256 public cumulativeExternalRevenue;
    uint256 public cumulativeExternalExpense;
    uint256 public externalLiabilities;
    uint256 public protocolInventory;
    uint256 public totalDividends;
    uint256 public realizedLosses;
    int256 public realizedExternalPnL;
    int256 public consolidatedNavDelta;

    error Unauthorized();
    error InvalidAddress();
    error InvalidEntry();
    error SourceAlreadyUsed();
    error BoundaryViolation();
    error BalanceDeltaNotProven();
    error LiabilityUnderflow();
    error InventoryUnderflow();

    event RecorderSet(address indexed account, bool allowed);
    event EntryRecorded(
        uint256 indexed id,
        Classification indexed classification,
        bytes32 indexed sourceId,
        address asset,
        uint256 amount,
        address from,
        address to,
        address externalCounterparty,
        int256 liabilityDelta,
        int256 realizedPnLDelta,
        int256 navDelta
    );

    constructor(address admin_, ISystemBoundaryRegistryLedger registry_) {
        if (admin_ == address(0) || address(registry_) == address(0)) revert InvalidAddress();
        admin = admin_;
        registry = registry_;
        recorder[admin_] = true;
        emit RecorderSet(admin_, true);
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyRecorder() {
        if (!recorder[msg.sender]) revert Unauthorized();
        _;
    }

    function setRecorder(address account, bool allowed) external onlyAdmin {
        if (account == address(0)) revert InvalidAddress();
        recorder[account] = allowed;
        emit RecorderSet(account, allowed);
    }

    function transferAdmin(address nextAdmin) external onlyAdmin {
        if (nextAdmin == address(0)) revert InvalidAddress();
        admin = nextAdmin;
        recorder[nextAdmin] = true;
        emit RecorderSet(nextAdmin, true);
    }

    function recordInternalTransfer(bytes32 sourceId, address asset, uint256 amount, address from, address to)
        external
        onlyRecorder
        returns (uint256)
    {
        if (!registry.isInternalTransfer(from, to)) revert BoundaryViolation();
        internalTransferVolume += amount;
        return _entry(sourceId, asset, amount, from, to, Classification.INTERNAL_TRANSFER, address(0), 0, 0, 0);
    }

    function recordExternalRevenue(
        bytes32 sourceId,
        address asset,
        uint256 grossAmount,
        uint256 externalCosts,
        address externalPayer,
        address systemReceiver,
        uint256 receiverBalanceBefore
    ) external onlyRecorder returns (uint256) {
        if (
            registry.isSystemAddress(externalPayer) || !registry.isSystemAddress(systemReceiver)
                || grossAmount == 0 || externalCosts > grossAmount
        ) revert BoundaryViolation();
        if (IERC20BalanceLedger(asset).balanceOf(systemReceiver) < receiverBalanceBefore + grossAmount) {
            revert BalanceDeltaNotProven();
        }
        uint256 net = grossAmount - externalCosts;
        cumulativeExternalRevenue += grossAmount;
        cumulativeExternalExpense += externalCosts;
        realizedExternalPnL += int256(net);
        consolidatedNavDelta += int256(net);
        return _entry(
            sourceId,
            asset,
            grossAmount,
            externalPayer,
            systemReceiver,
            Classification.EXTERNAL_REVENUE,
            externalPayer,
            0,
            int256(net),
            int256(net)
        );
    }

    /// @notice Capital received against a matching external obligation. It is
    /// neither revenue nor NAV growth.
    function recordCapitalInflowAndLiability(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address externalPayer,
        address systemReceiver,
        uint256 receiverBalanceBefore,
        uint256 liabilityIssued
    ) external onlyRecorder returns (uint256) {
        if (
            registry.isSystemAddress(externalPayer) || !registry.isSystemAddress(systemReceiver)
                || amount == 0 || liabilityIssued == 0
        ) revert BoundaryViolation();
        if (IERC20BalanceLedger(asset).balanceOf(systemReceiver) < receiverBalanceBefore + amount) {
            revert BalanceDeltaNotProven();
        }
        externalLiabilities += liabilityIssued;
        return _entry(
            sourceId,
            asset,
            amount,
            externalPayer,
            systemReceiver,
            Classification.LIABILITY_ISSUANCE,
            externalPayer,
            int256(liabilityIssued),
            0,
            0
        );
    }

    function recordExternalExpense(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address systemPayer,
        address externalRecipient
    ) external onlyRecorder returns (uint256) {
        if (!registry.isSystemAddress(systemPayer) || registry.isSystemAddress(externalRecipient) || amount == 0) {
            revert BoundaryViolation();
        }
        cumulativeExternalExpense += amount;
        realizedExternalPnL -= int256(amount);
        consolidatedNavDelta -= int256(amount);
        return _entry(
            sourceId,
            asset,
            amount,
            systemPayer,
            externalRecipient,
            Classification.EXTERNAL_EXPENSE,
            externalRecipient,
            0,
            -int256(amount),
            -int256(amount)
        );
    }

    /// @notice Atomic discounted redemption accounting. Paying 0.75 reserve
    /// units to retire a 1.00 reserve-unit liability realizes +0.25 PnL.
    function recordDiscountedLiabilityRedemption(
        bytes32 sourceId,
        address asset,
        uint256 liabilityRetired,
        uint256 payment,
        address externalHolder,
        address systemPayer
    ) external onlyRecorder returns (uint256) {
        if (
            registry.isSystemAddress(externalHolder) || !registry.isSystemAddress(systemPayer)
                || liabilityRetired == 0 || payment > liabilityRetired
        ) revert BoundaryViolation();
        if (liabilityRetired > externalLiabilities) revert LiabilityUnderflow();
        externalLiabilities -= liabilityRetired;
        cumulativeExternalExpense += payment;
        uint256 discountProfit = liabilityRetired - payment;
        realizedExternalPnL += int256(discountProfit);
        consolidatedNavDelta += int256(discountProfit);
        return _entry(
            sourceId,
            asset,
            payment == 0 ? liabilityRetired : payment,
            systemPayer,
            externalHolder,
            Classification.LIABILITY_REDEMPTION,
            externalHolder,
            -int256(liabilityRetired),
            int256(discountProfit),
            int256(discountProfit)
        );
    }

    function recordLiabilityRedemption(
        bytes32 sourceId,
        address asset,
        uint256 liabilityRetired,
        address externalHolder,
        address systemReceiver
    ) external onlyRecorder returns (uint256) {
        if (
            registry.isSystemAddress(externalHolder) || !registry.isSystemAddress(systemReceiver)
                || liabilityRetired == 0
        ) revert BoundaryViolation();
        if (liabilityRetired > externalLiabilities) revert LiabilityUnderflow();
        externalLiabilities -= liabilityRetired;
        return _entry(
            sourceId,
            asset,
            liabilityRetired,
            externalHolder,
            systemReceiver,
            Classification.LIABILITY_REDEMPTION,
            externalHolder,
            -int256(liabilityRetired),
            0,
            0
        );
    }

    function recordInventoryIncrease(bytes32 sourceId, address asset, uint256 amount, address systemHolder)
        external
        onlyRecorder
        returns (uint256)
    {
        if (!registry.isSystemAddress(systemHolder) || amount == 0) revert BoundaryViolation();
        protocolInventory += amount;
        return _entry(
            sourceId,
            asset,
            amount,
            address(0),
            systemHolder,
            Classification.INVENTORY_TRANSFER,
            address(0),
            0,
            0,
            0
        );
    }

    function recordInventoryDecrease(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address systemHolder,
        address destination
    ) external onlyRecorder returns (uint256) {
        if (!registry.isSystemAddress(systemHolder) || amount == 0) revert BoundaryViolation();
        if (amount > protocolInventory) revert InventoryUnderflow();
        protocolInventory -= amount;
        return _entry(
            sourceId,
            asset,
            amount,
            systemHolder,
            destination,
            Classification.INVENTORY_TRANSFER,
            registry.isSystemAddress(destination) ? address(0) : destination,
            0,
            0,
            0
        );
    }

    function recordLoss(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address systemAccount,
        address externalCounterparty
    ) external onlyRecorder returns (uint256) {
        if (!registry.isSystemAddress(systemAccount) || amount == 0) revert BoundaryViolation();
        realizedLosses += amount;
        realizedExternalPnL -= int256(amount);
        consolidatedNavDelta -= int256(amount);
        return _entry(
            sourceId,
            asset,
            amount,
            systemAccount,
            externalCounterparty,
            Classification.LOSS,
            externalCounterparty,
            0,
            -int256(amount),
            -int256(amount)
        );
    }

    function recordDividend(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address systemPayer,
        address externalRecipient
    ) external onlyRecorder returns (uint256) {
        if (!registry.isSystemAddress(systemPayer) || registry.isSystemAddress(externalRecipient) || amount == 0) {
            revert BoundaryViolation();
        }
        totalDividends += amount;
        consolidatedNavDelta -= int256(amount);
        return _entry(
            sourceId,
            asset,
            amount,
            systemPayer,
            externalRecipient,
            Classification.DIVIDEND,
            externalRecipient,
            0,
            0,
            -int256(amount)
        );
    }

    function _entry(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address from,
        address to,
        Classification classification,
        address externalCounterparty,
        int256 liabilityDelta,
        int256 pnlDelta,
        int256 navDelta
    ) private returns (uint256 id) {
        if (sourceId == bytes32(0) || asset == address(0) || amount == 0) revert InvalidEntry();
        if (sourceUsed[sourceId]) revert SourceAlreadyUsed();
        sourceUsed[sourceId] = true;
        id = entryCount++;
        entries[id] = Entry({
            asset: asset,
            debit: amount,
            credit: amount,
            from: from,
            to: to,
            classification: classification,
            sourceId: sourceId,
            externalCounterparty: externalCounterparty,
            liabilityDelta: liabilityDelta,
            realizedPnLDelta: pnlDelta,
            navDelta: navDelta,
            timestamp: uint64(block.timestamp)
        });
        emit EntryRecorded(
            id,
            classification,
            sourceId,
            asset,
            amount,
            from,
            to,
            externalCounterparty,
            liabilityDelta,
            pnlDelta,
            navDelta
        );
    }
}
