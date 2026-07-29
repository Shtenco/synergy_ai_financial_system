// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20SolverV2 {
    function balanceOf(address account) external view returns (uint256);
    function transfer(address to, uint256 amount) external returns (bool);
    function approve(address spender, uint256 amount) external returns (bool);
}

interface ISynSolverV2 is IERC20SolverV2 {}

interface IDemandSolverV2 {
    function redeem(uint256 baseAmount, address receiver) external returns (uint256 quoteAmount);
}

interface IAuctionSolverV2 {
    function commit(bytes32 digest) external;
    function fill(
        uint256 id,
        uint256 baseAmount,
        uint256 maxPayment,
        bytes32 salt,
        uint64 deadline
    ) external returns (uint256 payment);
}

interface IQuickSwapPairSolverV2 {
    function token0() external view returns (address);
    function token1() external view returns (address);
    function getReserves() external view returns (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast);
    function swap(uint256 amount0Out, uint256 amount1Out, address to, bytes calldata data) external;
}

interface IAavePoolSolverV2 {
    function ADDRESSES_PROVIDER() external view returns (address);
    function flashLoanSimple(
        address receiverAddress,
        address asset,
        uint256 amount,
        bytes calldata params,
        uint16 referralCode
    ) external;
}

/// @notice Aave V3-compatible flash-loan receiver used by the fork audit.
contract AaveFlashQESolverV2 {
    IAavePoolSolverV2 public immutable pool;
    address public immutable addressesProvider;
    address public immutable operator;
    IERC20SolverV2 public immutable wpol;
    ISynSolverV2 public immutable syn;
    IDemandSolverV2 public immutable demand;
    IAuctionSolverV2 public immutable auction;

    uint256 public lastAmount;
    uint256 public lastPremium;
    uint256 public lastBeforeBalance;
    uint256 public lastAfterBalance;
    uint256 public lastProfit;
    uint256 public lastSynAmount;
    uint8 public lastMode;

    error Unauthorized();
    error Unprofitable(uint256 afterBalance, uint256 requiredBalance);
    error TransferFailed();

    event FlashSettled(
        uint8 indexed mode,
        uint256 amount,
        uint256 premium,
        uint256 beforeBalance,
        uint256 afterBalance,
        uint256 profit,
        uint256 synAmount
    );
    event ProfitClaimed(address indexed receiver, uint256 amount);

    constructor(
        IAavePoolSolverV2 pool_,
        IERC20SolverV2 wpol_,
        ISynSolverV2 syn_,
        IDemandSolverV2 demand_,
        IAuctionSolverV2 auction_
    ) {
        operator = msg.sender;
        pool = pool_;
        addressesProvider = pool_.ADDRESSES_PROVIDER();
        wpol = wpol_;
        syn = syn_;
        demand = demand_;
        auction = auction_;
    }

    modifier onlyOperator() {
        if (msg.sender != operator) revert Unauthorized();
        _;
    }

    function ADDRESSES_PROVIDER() external view returns (address) {
        return addressesProvider;
    }

    function POOL() external view returns (address) {
        return address(pool);
    }

    function commitClosed(bytes32 digest) external onlyOperator {
        auction.commit(digest);
    }

    function runClosed(
        uint256 borrowAmount,
        uint256 windowId,
        uint256 baseAmount,
        uint256 maxPayment,
        bytes32 salt,
        uint64 deadline,
        uint256 minProfit
    ) external onlyOperator {
        bytes memory params = abi.encode(
            uint8(1), windowId, baseAmount, maxPayment, salt, deadline, minProfit, address(0)
        );
        pool.flashLoanSimple(address(this), address(wpol), borrowAmount, params, 0);
    }

    function runOpen(uint256 borrowAmount, address pair, uint256 minProfit) external onlyOperator {
        bytes memory params = abi.encode(
            uint8(2), uint256(0), uint256(0), uint256(0), bytes32(0), uint64(0), minProfit, pair
        );
        pool.flashLoanSimple(address(this), address(wpol), borrowAmount, params, 0);
    }

    /// @notice Transfers all settled WPOL profit to the operator-selected receiver.
    /// The autonomous controller uses this immediately after every completed cycle.
    function claimProfit(address receiver) external onlyOperator returns (uint256 amount) {
        if (receiver == address(0)) revert Unauthorized();
        amount = wpol.balanceOf(address(this));
        if (amount > 0 && !wpol.transfer(receiver, amount)) revert TransferFailed();
        emit ProfitClaimed(receiver, amount);
    }

    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external returns (bool) {
        if (msg.sender != address(pool) || initiator != address(this) || asset != address(wpol)) {
            revert Unauthorized();
        }

        (
            uint8 mode,
            uint256 windowId,
            uint256 baseAmount,
            uint256 maxPayment,
            bytes32 salt,
            uint64 deadline,
            uint256 minProfit,
            address pair
        ) = abi.decode(params, (uint8, uint256, uint256, uint256, bytes32, uint64, uint256, address));

        uint256 beforeBalance = wpol.balanceOf(address(this));
        uint256 synAmount;

        if (mode == 1) {
            if (!wpol.approve(address(auction), maxPayment)) revert TransferFailed();
            auction.fill(windowId, baseAmount, maxPayment, salt, deadline);
            if (!syn.approve(address(demand), baseAmount)) revert TransferFailed();
            demand.redeem(baseAmount, address(this));
            synAmount = baseAmount;
        } else if (mode == 2) {
            synAmount = _buyFromPairAndRedeem(pair, amount);
        } else {
            revert Unauthorized();
        }

        uint256 owing = amount + premium;
        uint256 afterBalance = wpol.balanceOf(address(this));
        if (beforeBalance < amount) revert Unprofitable(afterBalance, owing);
        uint256 preexisting = beforeBalance - amount;
        uint256 requiredBalance = owing + preexisting + minProfit;
        if (afterBalance < requiredBalance) revert Unprofitable(afterBalance, requiredBalance);

        uint256 profit = afterBalance - owing - preexisting;
        lastMode = mode;
        lastAmount = amount;
        lastPremium = premium;
        lastBeforeBalance = beforeBalance;
        lastAfterBalance = afterBalance;
        lastProfit = profit;
        lastSynAmount = synAmount;

        emit FlashSettled(mode, amount, premium, beforeBalance, afterBalance, profit, synAmount);

        if (!wpol.approve(address(pool), owing)) revert TransferFailed();
        return true;
    }

    function _buyFromPairAndRedeem(address pairAddress, uint256 amountIn) private returns (uint256 synOut) {
        IQuickSwapPairSolverV2 pair = IQuickSwapPairSolverV2(pairAddress);
        address t0 = pair.token0();
        address t1 = pair.token1();
        if (!((t0 == address(wpol) && t1 == address(syn)) || (t1 == address(wpol) && t0 == address(syn)))) {
            revert Unauthorized();
        }

        (uint112 r0, uint112 r1,) = pair.getReserves();
        uint256 reserveIn = t0 == address(wpol) ? r0 : r1;
        uint256 reserveOut = t0 == address(syn) ? r0 : r1;
        uint256 amountInWithFee = amountIn * 997;
        synOut = amountInWithFee * reserveOut / (reserveIn * 1000 + amountInWithFee);
        if (synOut == 0 || !wpol.transfer(pairAddress, amountIn)) revert TransferFailed();

        if (t0 == address(syn)) pair.swap(synOut, 0, address(this), "");
        else pair.swap(0, synOut, address(this), "");

        if (!syn.approve(address(demand), synOut)) revert TransferFailed();
        demand.redeem(synOut, address(this));
    }
}
