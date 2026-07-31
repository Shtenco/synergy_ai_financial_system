// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import "./SynergyQTBuybackHarness.sol";
import "./ForkFlashLender.sol";
import "./AaveFlashQESolverV2.sol";

/// @notice Passive reserve address. It intentionally exposes no withdrawal API.
contract QTReserveVault {}

/// @notice Permissionless two-phase QT state machine.
/// After one-time funding, any keeper can advance it without an administrator:
/// PREPARE opens a bounded QT window and commits; EXECUTE waits two blocks,
/// flash-settles the buyback, burns existing SYN, and distributes solver profit.
contract AutonomousQTController {
    uint16 public constant QT_BPS = 5_000;
    uint16 public constant DISCOUNT_BPS = 2_500;
    uint16 public constant BRIDGE_COVER_BPS = 5_000;
    uint16 public constant BRIDGE_SHARE_BPS = 5_000;
    uint64 public constant WINDOW_SECONDS = 3_600;
    uint64 public constant REVEAL_BLOCKS = 2;

    IERC20QTLike public immutable wpol;
    ForkSynQTToken public immutable syn;
    L1BuybackBurnEscrowQT public immutable demand;
    SynergyQTInventoryAuction public immutable auction;
    ForkFlashLender public immutable lender;
    AaveFlashQESolverV2 public immutable solver;
    QTReserveVault public immutable treasury;
    QTReserveVault public immutable bridge;

    uint256 public immutable maxCycleBase;
    uint256 public immutable referencePriceX18;
    uint256 public immutable auctionPriceX18;

    address public bootstrapper;
    bool public bootstrapped;
    bool public halted;
    uint256 public completedCycles;
    uint256 public totalBurned;
    uint256 public totalKeeperRewards;

    struct PendingCycle {
        uint256 windowId;
        uint256 baseAmount;
        uint256 payment;
        bytes32 salt;
        uint64 deadline;
        uint64 preparedBlock;
        address preparer;
    }

    PendingCycle public pending;

    error Unauthorized();
    error AlreadyBootstrapped();
    error NotBootstrapped();
    error Halted();
    error RevealTooEarly();
    error TransferFailed();
    error InvalidConfiguration();

    event Bootstrapped(
        uint256 initialSupply,
        uint256 inventory,
        uint256 demandWpol,
        uint256 treasuryWpol,
        uint256 bridgeWpol,
        uint256 lenderWpol
    );
    event CyclePrepared(
        uint256 indexed cycle,
        uint256 indexed windowId,
        uint256 baseAmount,
        uint256 payment,
        address indexed keeper,
        uint256 revealBlock
    );
    event CycleExecuted(
        uint256 indexed cycle,
        uint256 baseBurned,
        uint256 grossSolverProfit,
        address indexed preparer,
        address indexed executor,
        uint256 preparerReward,
        uint256 executorReward
    );
    event AutoHalted(uint256 completedCycles, uint256 remainingInventory, uint256 remainingDemand);

    constructor(
        IERC20QTLike wpol_,
        uint256 referencePriceX18_,
        uint256 maxCycleBase_,
        uint256 maxDemandBase_,
        uint16 flashPremiumBps_
    ) {
        if (
            address(wpol_) == address(0) || referencePriceX18_ == 0 || maxCycleBase_ == 0
                || maxDemandBase_ == 0
        ) revert InvalidConfiguration();

        bootstrapper = msg.sender;
        wpol = wpol_;
        referencePriceX18 = referencePriceX18_;
        maxCycleBase = maxCycleBase_;
        auctionPriceX18 = referencePriceX18_ * (10_000 - DISCOUNT_BPS) / 10_000;

        syn = new ForkSynQTToken();
        demand = new L1BuybackBurnEscrowQT(syn, wpol_, referencePriceX18_, maxDemandBase_);
        treasury = new QTReserveVault();
        bridge = new QTReserveVault();
        auction = new SynergyQTInventoryAuction(
            syn,
            wpol_,
            demand,
            address(this),
            address(treasury),
            address(bridge)
        );
        lender = new ForkFlashLender(IERC20ForkLender(address(wpol_)), flashPremiumBps_);
        solver = new AaveFlashQESolverV2(
            IAavePoolSolverV2(address(lender)),
            IERC20SolverV2(address(wpol_)),
            ISynSolverV2(address(syn)),
            IDemandSolverV2(address(demand)),
            IAuctionSolverV2(address(auction))
        );
    }

    /// @notice One-time capitalisation. Authority is irreversibly removed after success.
    function bootstrap(
        uint256 initialSupply,
        uint256 inventory,
        uint256 demandWpol,
        uint256 treasuryWpol,
        uint256 bridgeWpol,
        uint256 lenderWpol
    ) external {
        if (msg.sender != bootstrapper) revert Unauthorized();
        if (bootstrapped) revert AlreadyBootstrapped();
        if (
            initialSupply == 0 || inventory == 0 || inventory > initialSupply || demandWpol == 0
                || treasuryWpol == 0 || bridgeWpol == 0 || lenderWpol == 0
        ) revert InvalidConfiguration();

        uint256 totalWpol = demandWpol + treasuryWpol + bridgeWpol + lenderWpol;
        if (!wpol.transferFrom(msg.sender, address(this), totalWpol)) revert TransferFailed();
        if (!wpol.transfer(address(demand), demandWpol)) revert TransferFailed();
        if (!wpol.transfer(address(treasury), treasuryWpol)) revert TransferFailed();
        if (!wpol.transfer(address(bridge), bridgeWpol)) revert TransferFailed();
        if (!wpol.transfer(address(lender), lenderWpol)) revert TransferFailed();

        syn.mint(address(auction), inventory);
        if (initialSupply > inventory) syn.mint(msg.sender, initialSupply - inventory);

        bootstrapped = true;
        bootstrapper = address(0);

        emit Bootstrapped(initialSupply, inventory, demandWpol, treasuryWpol, bridgeWpol, lenderWpol);
    }

    /// @notice Advances exactly one state transition. No parameters and no privileged caller.
    /// First call prepares a cycle; after two blocks, the next call executes it.
    function step() external {
        if (!bootstrapped) revert NotBootstrapped();
        if (halted) revert Halted();

        if (pending.preparedBlock == 0) {
            _prepare(msg.sender);
        } else {
            _execute(msg.sender);
        }
    }

    function phase() external view returns (uint8) {
        if (!bootstrapped) return 0;
        if (halted) return 3;
        if (pending.preparedBlock == 0) return 1;
        return 2;
    }

    function protocolWpol() public view returns (uint256) {
        return wpol.balanceOf(address(treasury)) + wpol.balanceOf(address(bridge))
            + wpol.balanceOf(address(demand)) + wpol.balanceOf(address(auction));
    }

    function remainingInventory() public view returns (uint256) {
        return syn.balanceOf(address(auction));
    }

    function _prepare(address keeper) private {
        uint256 inventory = remainingInventory();
        uint256 remainingDemand = demand.remainingBase();
        uint256 demandLiquidity = wpol.balanceOf(address(demand));
        if (inventory == 0 || remainingDemand == 0 || demandLiquidity < referencePriceX18) {
            _halt(inventory, remainingDemand);
            return;
        }

        uint256 cappedBase = maxCycleBase;
        if (cappedBase > inventory) cappedBase = inventory;
        if (cappedBase > remainingDemand) cappedBase = remainingDemand;
        uint256 liquidityBase = demandLiquidity * 1e18 / referencePriceX18;
        if (cappedBase > liquidityBase) cappedBase = liquidityBase;
        if (cappedBase == 0) {
            _halt(inventory, remainingDemand);
            return;
        }

        (uint256 windowId, uint256 baseAmount) = auction.openProportionalWindow(
            QT_BPS,
            DISCOUNT_BPS,
            BRIDGE_COVER_BPS,
            BRIDGE_SHARE_BPS,
            cappedBase,
            uint64(block.timestamp + WINDOW_SECONDS)
        );

        uint256 payment = baseAmount * auctionPriceX18 / 1e18;
        uint64 deadline = uint64(block.timestamp + WINDOW_SECONDS - 60);
        bytes32 salt = keccak256(
            abi.encode(block.chainid, address(this), completedCycles, windowId, baseAmount, payment)
        );
        bytes32 digest = keccak256(
            abi.encode(address(solver), windowId, baseAmount, payment, salt, deadline)
        );
        solver.commitClosed(digest);

        pending = PendingCycle({
            windowId: windowId,
            baseAmount: baseAmount,
            payment: payment,
            salt: salt,
            deadline: deadline,
            preparedBlock: uint64(block.number),
            preparer: keeper
        });

        emit CyclePrepared(
            completedCycles + 1,
            windowId,
            baseAmount,
            payment,
            keeper,
            block.number + REVEAL_BLOCKS
        );
    }

    function _execute(address executor) private {
        PendingCycle memory p = pending;
        if (block.number < uint256(p.preparedBlock) + REVEAL_BLOCKS) revert RevealTooEarly();

        uint256 supplyBefore = syn.totalSupply();
        solver.runClosed(
            p.payment,
            p.windowId,
            p.baseAmount,
            p.payment,
            p.salt,
            p.deadline,
            0
        );
        uint256 grossProfit = solver.claimProfit(address(this));
        uint256 supplyAfter = syn.totalSupply();
        uint256 burned = supplyBefore - supplyAfter;

        uint256 preparerReward = grossProfit / 2;
        uint256 executorReward = grossProfit - preparerReward;
        if (preparerReward > 0 && !wpol.transfer(p.preparer, preparerReward)) revert TransferFailed();
        if (executorReward > 0 && !wpol.transfer(executor, executorReward)) revert TransferFailed();

        completedCycles += 1;
        totalBurned += burned;
        totalKeeperRewards += grossProfit;
        delete pending;

        emit CycleExecuted(
            completedCycles,
            burned,
            grossProfit,
            p.preparer,
            executor,
            preparerReward,
            executorReward
        );

        uint256 inventory = remainingInventory();
        uint256 remainingDemand = demand.remainingBase();
        if (inventory == 0 || remainingDemand == 0 || wpol.balanceOf(address(demand)) < referencePriceX18) {
            _halt(inventory, remainingDemand);
        }
    }

    function _halt(uint256 inventory, uint256 remainingDemand) private {
        halted = true;
        emit AutoHalted(completedCycles, inventory, remainingDemand);
    }
}
