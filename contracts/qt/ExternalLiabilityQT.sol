// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20QTReserveV3 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
}

interface ISynQTV3 {
    function balanceOf(address account) external view returns (uint256);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function burn(uint256 amount) external;
}

interface IBoundaryQTV3 {
    function isSystemAddress(address account) external view returns (bool);
}

interface ISolvencyQTV3 {
    function canExecute(uint256 expectedExternalValue, uint256 expectedExternalCosts)
        external
        view
        returns (bool);
    function economicSolvencyBps() external view returns (uint256);
    function liquidityCoverageBps() external view returns (uint256);
    function gasCoverageBps() external view returns (uint256);
}

interface ILedgerQTV3 {
    function recordDiscountedLiabilityRedemption(
        bytes32 sourceId,
        address asset,
        uint256 liabilityRetired,
        uint256 payment,
        address externalHolder,
        address systemPayer
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
}

/// @notice QT distinguishes external liability redemption from protocol
/// inventory retirement. Only the former can reduce external liabilities and
/// realize the discount between stress liability and cash payment.
contract ExternalLiabilityQT {
    address public admin;
    mapping(address => bool) public operator;
    IERC20QTReserveV3 public immutable reserveAsset;
    ISynQTV3 public immutable syn;
    IBoundaryQTV3 public immutable registry;
    ISolvencyQTV3 public immutable solvency;
    ILedgerQTV3 public immutable ledger;

    uint256 public stressValuePerSynX18;
    uint256 public qtPricePerSynX18;
    uint256 public totalExternalSynBurned;
    uint256 public totalInventoryBurned;
    uint256 public totalReservePaid;

    error Unauthorized();
    error InvalidConfiguration();
    error WrongBoundary();
    error SolvencyGateFailed();
    error TransferFailed();

    event OperatorSet(address indexed account, bool allowed);
    event QTPolicySet(uint256 stressValuePerSynX18, uint256 qtPricePerSynX18);
    event ExternalLiabilityRedeemed(
        address indexed holder,
        uint256 synAmount,
        uint256 liabilityRetired,
        uint256 reservePaid,
        uint256 discountProfit
    );
    event InternalInventoryRetired(address indexed holder, uint256 synAmount);

    constructor(
        address admin_,
        IERC20QTReserveV3 reserveAsset_,
        ISynQTV3 syn_,
        IBoundaryQTV3 registry_,
        ISolvencyQTV3 solvency_,
        ILedgerQTV3 ledger_,
        uint256 stressValuePerSynX18_,
        uint256 qtPricePerSynX18_
    ) {
        if (
            admin_ == address(0) || address(reserveAsset_) == address(0) || address(syn_) == address(0)
                || address(registry_) == address(0) || address(solvency_) == address(0)
                || address(ledger_) == address(0) || stressValuePerSynX18_ == 0
                || qtPricePerSynX18_ == 0 || qtPricePerSynX18_ > stressValuePerSynX18_
        ) revert InvalidConfiguration();
        admin = admin_;
        operator[admin_] = true;
        reserveAsset = reserveAsset_;
        syn = syn_;
        registry = registry_;
        solvency = solvency_;
        ledger = ledger_;
        stressValuePerSynX18 = stressValuePerSynX18_;
        qtPricePerSynX18 = qtPricePerSynX18_;
        emit OperatorSet(admin_, true);
        emit QTPolicySet(stressValuePerSynX18_, qtPricePerSynX18_);
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

    function setPolicy(uint256 stressValuePerSynX18_, uint256 qtPricePerSynX18_) external onlyAdmin {
        if (
            stressValuePerSynX18_ == 0 || qtPricePerSynX18_ == 0
                || qtPricePerSynX18_ > stressValuePerSynX18_
        ) revert InvalidConfiguration();
        stressValuePerSynX18 = stressValuePerSynX18_;
        qtPricePerSynX18 = qtPricePerSynX18_;
        emit QTPolicySet(stressValuePerSynX18_, qtPricePerSynX18_);
    }

    function externalTenderAndBurn(
        address holder,
        uint256 synAmount,
        uint256 externalExecutionCost,
        address externalCostRecipient,
        bytes32 redemptionSourceId,
        bytes32 expenseSourceId
    ) external onlyOperator {
        if (holder == address(0) || registry.isSystemAddress(holder) || synAmount == 0) {
            revert WrongBoundary();
        }
        if (
            externalExecutionCost > 0
                && (externalCostRecipient == address(0) || registry.isSystemAddress(externalCostRecipient))
        ) revert WrongBoundary();

        uint256 liabilityRetired = synAmount * stressValuePerSynX18 / 1e18;
        uint256 payment = synAmount * qtPricePerSynX18 / 1e18;
        uint256 discountProfit = liabilityRetired - payment;
        if (
            !solvency.canExecute(discountProfit, externalExecutionCost)
                || solvency.economicSolvencyBps() < 10_500 || solvency.liquidityCoverageBps() < 12_000
                || solvency.gasCoverageBps() < 12_000
                || reserveAsset.balanceOf(address(this)) < payment + externalExecutionCost
        ) revert SolvencyGateFailed();

        if (!syn.transferFrom(holder, address(this), synAmount)) revert TransferFailed();
        syn.burn(synAmount);
        if (!reserveAsset.transfer(holder, payment)) revert TransferFailed();
        ledger.recordDiscountedLiabilityRedemption(
            redemptionSourceId,
            address(reserveAsset),
            liabilityRetired,
            payment,
            holder,
            address(this)
        );

        if (externalExecutionCost > 0) {
            if (!reserveAsset.transfer(externalCostRecipient, externalExecutionCost)) revert TransferFailed();
            ledger.recordExternalExpense(
                expenseSourceId,
                address(reserveAsset),
                externalExecutionCost,
                address(this),
                externalCostRecipient
            );
        }

        totalExternalSynBurned += synAmount;
        totalReservePaid += payment;
        emit ExternalLiabilityRedeemed(holder, synAmount, liabilityRetired, payment, discountProfit);
    }

    /// @notice Burns protocol inventory without claiming an external liability
    /// reduction, external revenue or realized PnL.
    function retireInternalInventory(
        address systemHolder,
        uint256 synAmount,
        bytes32 inventorySourceId
    ) external onlyOperator {
        if (!registry.isSystemAddress(systemHolder) || synAmount == 0) revert WrongBoundary();
        if (!syn.transferFrom(systemHolder, address(this), synAmount)) revert TransferFailed();
        syn.burn(synAmount);
        ledger.recordInventoryDecrease(
            inventorySourceId,
            address(syn),
            synAmount,
            systemHolder,
            address(0)
        );
        totalInventoryBurned += synAmount;
        emit InternalInventoryRetired(systemHolder, synAmount);
    }
}
