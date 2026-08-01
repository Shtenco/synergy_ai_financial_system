// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20MMReserve {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

interface ISynMM {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
}

interface IBoundaryMM {
    function isSystemAddress(address account) external view returns (bool);
}

interface ISolvencyMM {
    function canExecute(uint256 expectedExternalValue, uint256 expectedExternalCosts)
        external
        view
        returns (bool);
}

interface ILedgerMM {
    function recordCapitalInflowAndLiability(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address externalPayer,
        address systemReceiver,
        uint256 receiverBalanceBefore,
        uint256 liabilityIssued
    ) external returns (uint256);

    function recordExternalRevenue(
        bytes32 sourceId,
        address asset,
        uint256 grossAmount,
        uint256 externalCosts,
        address externalPayer,
        address systemReceiver,
        uint256 receiverBalanceBefore
    ) external returns (uint256);

    function recordExternalExpense(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address systemPayer,
        address externalRecipient
    ) external returns (uint256);

    function recordInventoryDecrease(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address systemHolder,
        address destination
    ) external returns (uint256);

    function recordInternalTransfer(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address from,
        address to
    ) external returns (uint256);
}

/// @notice Protocol-owned market maker that recognizes revenue only when a
/// counterparty is outside the consolidated boundary. Internal fills and wash
/// trades are rejected and cannot create volume, liabilities, revenue or NAV.
contract ExternalRevenueMarketMaker {
    address public admin;
    mapping(address => bool) public operator;
    IERC20MMReserve public immutable reserveAsset;
    ISynMM public immutable syn;
    IBoundaryMM public immutable registry;
    ISolvencyMM public immutable solvency;
    ILedgerMM public immutable ledger;

    uint256 public stressValuePerSynX18;
    uint256 public maximumInventory;
    uint256 public minimumPoolDepth;
    uint256 public totalExternalVolume;
    uint256 public totalRealizedSpread;

    error Unauthorized();
    error InvalidConfiguration();
    error InternalCounterparty();
    error UnprofitableTrade();
    error InventoryLimit();
    error TransferFailed();

    event OperatorSet(address indexed account, bool allowed);
    event RiskPolicySet(uint256 stressValuePerSynX18, uint256 maximumInventory, uint256 minimumPoolDepth);
    event ExternalSale(
        address indexed buyer,
        uint256 synAmount,
        uint256 payment,
        uint256 liabilityIssued,
        uint256 realizedSpread,
        uint256 externalCosts
    );
    event ExternalStrategyRevenue(address indexed payer, uint256 grossRevenue, uint256 externalCosts);
    event InternalReserveTransfer(address indexed destination, uint256 amount);

    constructor(
        address admin_,
        IERC20MMReserve reserveAsset_,
        ISynMM syn_,
        IBoundaryMM registry_,
        ISolvencyMM solvency_,
        ILedgerMM ledger_,
        uint256 stressValuePerSynX18_,
        uint256 maximumInventory_,
        uint256 minimumPoolDepth_
    ) {
        if (
            admin_ == address(0) || address(reserveAsset_) == address(0) || address(syn_) == address(0)
                || address(registry_) == address(0) || address(solvency_) == address(0)
                || address(ledger_) == address(0) || stressValuePerSynX18_ == 0
        ) revert InvalidConfiguration();
        admin = admin_;
        operator[admin_] = true;
        reserveAsset = reserveAsset_;
        syn = syn_;
        registry = registry_;
        solvency = solvency_;
        ledger = ledger_;
        stressValuePerSynX18 = stressValuePerSynX18_;
        maximumInventory = maximumInventory_;
        minimumPoolDepth = minimumPoolDepth_;
        emit OperatorSet(admin_, true);
        emit RiskPolicySet(stressValuePerSynX18_, maximumInventory_, minimumPoolDepth_);
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyOperator() {
        if (!operator[msg.sender]) revert Unauthorized();
        _;
    }

    function setOperator(address account, bool allowed) external onlyAdmin {
        if (account == address(0)) revert InvalidConfiguration();
        operator[account] = allowed;
        emit OperatorSet(account, allowed);
    }

    function setRiskPolicy(
        uint256 stressValuePerSynX18_,
        uint256 maximumInventory_,
        uint256 minimumPoolDepth_
    ) external onlyAdmin {
        if (stressValuePerSynX18_ == 0) revert InvalidConfiguration();
        stressValuePerSynX18 = stressValuePerSynX18_;
        maximumInventory = maximumInventory_;
        minimumPoolDepth = minimumPoolDepth_;
        emit RiskPolicySet(stressValuePerSynX18_, maximumInventory_, minimumPoolDepth_);
    }

    function inventory() external view returns (uint256) {
        return syn.balanceOf(address(this));
    }

    /// @notice Sells protocol inventory to a genuinely external buyer. The
    /// payment is split economically into liability backing and realized spread.
    function sellToExternalBuyer(
        address buyer,
        uint256 synAmount,
        uint256 payment,
        uint256 externalCosts,
        address externalCostRecipient,
        bytes32 capitalSourceId,
        bytes32 revenueSourceId,
        bytes32 inventorySourceId,
        bytes32 expenseSourceId
    ) external onlyOperator {
        if (buyer == address(0) || registry.isSystemAddress(buyer)) revert InternalCounterparty();
        if (synAmount == 0 || payment == 0 || syn.balanceOf(address(this)) < synAmount) {
            revert InventoryLimit();
        }
        uint256 liabilityIssued = synAmount * stressValuePerSynX18 / 1e18;
        if (payment <= liabilityIssued) revert UnprofitableTrade();
        uint256 grossSpread = payment - liabilityIssued;
        if (externalCosts >= grossSpread || !solvency.canExecute(grossSpread, externalCosts)) {
            revert UnprofitableTrade();
        }
        if (externalCosts > 0 && (externalCostRecipient == address(0) || registry.isSystemAddress(externalCostRecipient))) {
            revert InternalCounterparty();
        }
        uint256 inventoryAfter = syn.balanceOf(address(this)) - synAmount;
        if (maximumInventory > 0 && inventoryAfter > maximumInventory) revert InventoryLimit();
        if (reserveAsset.balanceOf(address(this)) < minimumPoolDepth) revert InventoryLimit();

        uint256 beforeBalance = reserveAsset.balanceOf(address(this));
        if (!reserveAsset.transferFrom(buyer, address(this), payment)) revert TransferFailed();
        if (!syn.transfer(buyer, synAmount)) revert TransferFailed();

        ledger.recordCapitalInflowAndLiability(
            capitalSourceId,
            address(reserveAsset),
            liabilityIssued,
            buyer,
            address(this),
            beforeBalance,
            liabilityIssued
        );
        ledger.recordExternalRevenue(
            revenueSourceId,
            address(reserveAsset),
            grossSpread,
            0,
            buyer,
            address(this),
            beforeBalance
        );
        ledger.recordInventoryDecrease(
            inventorySourceId,
            address(syn),
            synAmount,
            address(this),
            buyer
        );

        if (externalCosts > 0) {
            if (!reserveAsset.transfer(externalCostRecipient, externalCosts)) revert TransferFailed();
            ledger.recordExternalExpense(
                expenseSourceId,
                address(reserveAsset),
                externalCosts,
                address(this),
                externalCostRecipient
            );
        }

        totalExternalVolume += payment;
        totalRealizedSpread += grossSpread - externalCosts;
        emit ExternalSale(buyer, synAmount, payment, liabilityIssued, grossSpread, externalCosts);
    }

    /// @notice Records fees, cross-DEX arbitrage, bridge fees, yield or other
    /// strategy income only when real reserve tokens arrive from an external payer.
    function collectExternalStrategyRevenue(
        address externalPayer,
        uint256 grossRevenue,
        bytes32 revenueSourceId
    ) external onlyOperator {
        if (externalPayer == address(0) || registry.isSystemAddress(externalPayer) || grossRevenue == 0) {
            revert InternalCounterparty();
        }
        uint256 beforeBalance = reserveAsset.balanceOf(address(this));
        if (!reserveAsset.transferFrom(externalPayer, address(this), grossRevenue)) revert TransferFailed();
        ledger.recordExternalRevenue(
            revenueSourceId,
            address(reserveAsset),
            grossRevenue,
            0,
            externalPayer,
            address(this),
            beforeBalance
        );
        totalRealizedSpread += grossRevenue;
        emit ExternalStrategyRevenue(externalPayer, grossRevenue, 0);
    }

    function transferReserveInternal(address destination, uint256 amount, bytes32 sourceId)
        external
        onlyOperator
    {
        if (!registry.isSystemAddress(destination) || amount == 0) revert InternalCounterparty();
        if (!reserveAsset.transfer(destination, amount)) revert TransferFailed();
        ledger.recordInternalTransfer(sourceId, address(reserveAsset), amount, address(this), destination);
        emit InternalReserveTransfer(destination, amount);
    }
}
