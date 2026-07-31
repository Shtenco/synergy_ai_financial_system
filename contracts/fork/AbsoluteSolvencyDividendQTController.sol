// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import "./SynergyQTBuybackHarness.sol";
import "./ForkFlashLender.sol";
import "./AaveFlashQESolverV2.sol";

contract SolvencyReserveVault {
    IERC20QTLike public immutable wpol;
    address public immutable controller;

    error Unauthorized();
    error TransferFailed();

    constructor(IERC20QTLike wpol_, address controller_) {
        wpol = wpol_;
        controller = controller_;
    }

    function withdraw(uint256 amount, address receiver) external {
        if (msg.sender != controller) revert Unauthorized();
        if (!wpol.transfer(receiver, amount)) revert TransferFailed();
    }
}

/// @notice Ownerless, permissionless QT recovery machine.
/// It recycles auction proceeds and solver surplus, pays keepers, restores the
/// buyback float, and distributes only excess capital above a 101% reserve
/// target to an immutable dividend recipient.
contract AbsoluteSolvencyDividendQTController {
    uint256 public constant BPS = 10_000;
    uint256 public constant PAR_PRICE_X18 = 1e18;
    uint256 public constant INITIAL_SUPPLY = 100e18;
    uint256 public constant INITIAL_INVENTORY = 72e18;
    uint256 public constant MAX_CYCLE_BASE = 2e18;
    uint256 public constant INITIAL_PROTOCOL_WPOL = 43e18;
    uint256 public constant INITIAL_DEMAND_FLOAT = 2e18;
    uint256 public constant INITIAL_TREASURY = 13_500_000_000_000_000_000;
    uint256 public constant INITIAL_BRIDGE = 13_500_000_000_000_000_000;
    uint256 public constant INITIAL_CONTROLLER_BUFFER = 14e18;
    uint256 public constant LENDER_LIQUIDITY = 3e18;
    uint256 public constant KEEPER_REWARD = 380_000_000_000_000_000;
    uint256 public constant SOLVENCY_TARGET_BPS = 10_100;
    uint16 public constant QT_BPS = 5_000;
    uint16 public constant DISCOUNT_BPS = 2_500;
    uint16 public constant BRIDGE_COVER_BPS = 5_000;
    uint16 public constant BRIDGE_SHARE_BPS = 5_000;
    uint64 public constant WINDOW_SECONDS = 3_600;
    uint64 public constant REVEAL_BLOCKS = 2;

    IERC20QTLike public immutable wpol;
    address public immutable dividendRecipient;
    ForkSynQTToken public immutable syn;
    L1BuybackBurnEscrowQT public immutable demand;
    SynergyQTInventoryAuction public immutable auction;
    ForkFlashLender public immutable lender;
    AaveFlashQESolverV2 public immutable solver;
    SolvencyReserveVault public immutable treasury;
    SolvencyReserveVault public immutable bridge;

    address public bootstrapper;
    bool public bootstrapped;
    bool public halted;
    bool public solventHalt;
    uint256 public completedCycles;
    uint256 public totalBurned;
    uint256 public totalKeeperRewards;
    uint256 public totalDividends;

    struct PendingCycle {
        uint256 windowId;
        uint256 baseAmount;
        uint256 payment;
        uint256 bridgePart;
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

    event Bootstrapped(uint256 assets, uint256 liabilities, address indexed dividendRecipient);
    event CyclePrepared(uint256 indexed cycle, uint256 baseAmount, uint256 payment, address indexed keeper);
    event CycleExecuted(
        uint256 indexed cycle,
        uint256 burned,
        uint256 keeperReward,
        uint256 protocolAssets,
        uint256 liabilities
    );
    event DividendPaid(address indexed recipient, uint256 amount, uint256 postDividendCoverageBps);
    event TerminalHalt(bool solvent, uint256 assets, uint256 liabilities, uint256 cycles);

    constructor(IERC20QTLike wpol_, address dividendRecipient_, uint16 flashPremiumBps_) {
        if (address(wpol_) == address(0) || dividendRecipient_ == address(0)) revert InvalidConfiguration();
        wpol = wpol_;
        dividendRecipient = dividendRecipient_;
        bootstrapper = msg.sender;

        syn = new ForkSynQTToken();
        demand = new L1BuybackBurnEscrowQT(syn, wpol_, PAR_PRICE_X18, INITIAL_INVENTORY);
        treasury = new SolvencyReserveVault(wpol_, address(this));
        bridge = new SolvencyReserveVault(wpol_, address(this));
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

    function bootstrap(address externalHolder) external {
        if (msg.sender != bootstrapper) revert Unauthorized();
        if (bootstrapped) revert AlreadyBootstrapped();
        if (externalHolder == address(0)) revert InvalidConfiguration();

        uint256 totalFunding = INITIAL_PROTOCOL_WPOL + LENDER_LIQUIDITY;
        if (!wpol.transferFrom(msg.sender, address(this), totalFunding)) revert TransferFailed();
        if (!wpol.transfer(address(demand), INITIAL_DEMAND_FLOAT)) revert TransferFailed();
        if (!wpol.transfer(address(treasury), INITIAL_TREASURY)) revert TransferFailed();
        if (!wpol.transfer(address(bridge), INITIAL_BRIDGE)) revert TransferFailed();
        if (!wpol.transfer(address(lender), LENDER_LIQUIDITY)) revert TransferFailed();

        syn.mint(address(auction), INITIAL_INVENTORY);
        syn.mint(externalHolder, INITIAL_SUPPLY - INITIAL_INVENTORY);

        if (wpol.balanceOf(address(this)) != INITIAL_CONTROLLER_BUFFER) revert InvalidConfiguration();
        bootstrapped = true;
        bootstrapper = address(0);

        emit Bootstrapped(protocolAssets(), liabilitiesAtPar(), dividendRecipient);
    }

    function step() external {
        if (!bootstrapped) revert NotBootstrapped();
        if (halted) revert Halted();
        if (pending.preparedBlock == 0) _prepare(msg.sender);
        else _execute(msg.sender);
    }

    function phase() external view returns (uint8) {
        if (!bootstrapped) return 0;
        if (halted) return 3;
        return pending.preparedBlock == 0 ? 1 : 2;
    }

    function liabilitiesAtPar() public view returns (uint256) {
        return syn.totalSupply() * PAR_PRICE_X18 / 1e18;
    }

    function protocolAssets() public view returns (uint256) {
        return wpol.balanceOf(address(this)) + wpol.balanceOf(address(treasury))
            + wpol.balanceOf(address(bridge)) + wpol.balanceOf(address(demand))
            + wpol.balanceOf(address(auction));
    }

    function reserveCoverageBps() public view returns (uint256) {
        uint256 liabilities = liabilitiesAtPar();
        if (liabilities == 0) return type(uint256).max;
        return protocolAssets() * BPS / liabilities;
    }

    function equityAtPar() public view returns (int256) {
        return int256(protocolAssets()) - int256(liabilitiesAtPar());
    }

    function _prepare(address keeper) private {
        uint256 inventory = syn.balanceOf(address(auction));
        uint256 remaining = demand.remainingBase();
        if (inventory == 0 || remaining == 0) {
            _finishOrFail();
            return;
        }

        uint256 cappedBase = MAX_CYCLE_BASE;
        if (cappedBase > inventory) cappedBase = inventory;
        if (cappedBase > remaining) cappedBase = remaining;

        (uint256 windowId, uint256 baseAmount) = auction.openProportionalWindow(
            QT_BPS,
            DISCOUNT_BPS,
            BRIDGE_COVER_BPS,
            BRIDGE_SHARE_BPS,
            cappedBase,
            uint64(block.timestamp + WINDOW_SECONDS)
        );
        uint256 payment = baseAmount * 75 / 100;
        uint256 bridgePart = payment * BRIDGE_SHARE_BPS / BPS;
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
            bridgePart: bridgePart,
            salt: salt,
            deadline: deadline,
            preparedBlock: uint64(block.number),
            preparer: keeper
        });

        emit CyclePrepared(completedCycles + 1, baseAmount, payment, keeper);
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
        solver.claimProfit(address(this));

        bridge.withdraw(p.bridgePart, address(this));
        treasury.withdraw(p.payment - p.bridgePart, address(this));

        uint256 preparerReward = KEEPER_REWARD / 2;
        uint256 executorReward = KEEPER_REWARD - preparerReward;
        if (!wpol.transfer(p.preparer, preparerReward)) revert TransferFailed();
        if (!wpol.transfer(executor, executorReward)) revert TransferFailed();

        uint256 burned = supplyBefore - syn.totalSupply();
        completedCycles += 1;
        totalBurned += burned;
        totalKeeperRewards += KEEPER_REWARD;
        delete pending;

        uint256 liabilities = liabilitiesAtPar();
        uint256 assets = protocolAssets();
        emit CycleExecuted(completedCycles, burned, KEEPER_REWARD, assets, liabilities);

        uint256 targetAssets = liabilities * SOLVENCY_TARGET_BPS / BPS;
        if (assets >= targetAssets) {
            uint256 dividend = assets - targetAssets;
            if (dividend > 0) {
                if (!wpol.transfer(dividendRecipient, dividend)) revert TransferFailed();
                totalDividends += dividend;
                emit DividendPaid(dividendRecipient, dividend, reserveCoverageBps());
            }
            halted = true;
            solventHalt = true;
            emit TerminalHalt(true, protocolAssets(), liabilitiesAtPar(), completedCycles);
            return;
        }

        uint256 remaining = demand.remainingBase();
        uint256 inventory = syn.balanceOf(address(auction));
        if (remaining == 0 || inventory == 0) {
            _finishOrFail();
            return;
        }

        uint256 nextFloat = MAX_CYCLE_BASE * PAR_PRICE_X18 / 1e18;
        if (!wpol.transfer(address(demand), nextFloat)) revert TransferFailed();
    }

    function _finishOrFail() private {
        halted = true;
        uint256 liabilities = liabilitiesAtPar();
        uint256 assets = protocolAssets();
        uint256 targetAssets = liabilities * SOLVENCY_TARGET_BPS / BPS;
        solventHalt = assets >= targetAssets;
        if (solventHalt) {
            uint256 dividend = assets - targetAssets;
            if (dividend > 0) {
                if (!wpol.transfer(dividendRecipient, dividend)) revert TransferFailed();
                totalDividends += dividend;
                emit DividendPaid(dividendRecipient, dividend, reserveCoverageBps());
            }
        }
        emit TerminalHalt(solventHalt, protocolAssets(), liabilitiesAtPar(), completedCycles);
    }
}
