// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {
    BullishQuickSwapCentralBankV2,
    IERC20QS,
    IQuickSwapPairV2
} from "./BullishQuickSwapRefillV2.sol";

/// @notice Hardened QuickSwap V2 controller for Synergy Coin (SYNA).
/// @dev Security model:
///      - every router quote is independently recomputed from pair reserves;
///      - zero/nonexistent routes and quote mismatches fail closed;
///      - protected actions are bound to an exact state hash and parent block;
///      - a pre-trade reserve change causes the whole transaction to revert;
///      - transaction gas price is capped on-chain;
///      - the selected cycle remains 2x0.175 USDT buys + 5x0.07 USDT sells.
contract BullishQuickSwapShieldedV5 is BullishQuickSwapCentralBankV2 {
    uint256 public constant SCALED_BUY_USDT = 175_000;
    uint256 public constant SCALED_SELL_NOTIONAL_USDT = 70_000;
    uint256 public constant DEAL_SCALE_BPS = 17_500;
    uint256 public constant QUICKSWAP_FEE_NUMERATOR = 997;
    uint256 public constant QUICKSWAP_FEE_DENOMINATOR = 1_000;
    uint256 public constant MAX_SECURITY_BPS = 3_000;
    uint256 public constant MAX_GAS_PRICE_HARD_CAP = 2_000 gwei;
    uint256 public constant MAX_DEADLINE_WINDOW = 120 seconds;

    address public immutable gasRecipient;

    uint256 public maxTradeInputBps = 2_500;
    uint256 public maxTradeOutputBps = 2_500;
    uint256 public gasPriceCeilingWei = 500 gwei;

    event SecurityConfigUpdated(
        uint256 maxTradeInputBps,
        uint256 maxTradeOutputBps,
        uint256 gasPriceCeilingWei
    );
    event ProtectedCycleExecuted(
        uint256 indexed nonce,
        bytes32 indexed committedState,
        bytes32 indexed parentHash,
        uint256 buyUsdt,
        uint256 sellNotionalUsdt,
        uint256 finalMetricUsdt,
        uint256 finalPriceX18
    );
    event ProtectedRobotRefill(uint256 targetUsdt, uint256 resultingRobotUsdt);
    event ProtectedGasRefill(uint256 exactPolOut, uint256 usdtSpent, address indexed recipient);

    constructor(
        address owner_,
        address router_,
        address usdt_,
        address wpol_,
        address syna_,
        address gasRecipient_
    ) BullishQuickSwapCentralBankV2(owner_, router_, usdt_, wpol_, syna_) {
        require(gasRecipient_ != address(0), "ZERO_GAS_RECIPIENT");
        gasRecipient = gasRecipient_;
    }

    function setSecurityConfig(
        uint256 maxTradeInputBps_,
        uint256 maxTradeOutputBps_,
        uint256 gasPriceCeilingWei_
    ) external onlyOwner {
        require(
            maxTradeInputBps_ > 0 && maxTradeInputBps_ <= MAX_SECURITY_BPS,
            "INPUT_IMPACT"
        );
        require(
            maxTradeOutputBps_ > 0 && maxTradeOutputBps_ <= MAX_SECURITY_BPS,
            "OUTPUT_IMPACT"
        );
        require(
            gasPriceCeilingWei_ > 0 && gasPriceCeilingWei_ <= MAX_GAS_PRICE_HARD_CAP,
            "GAS_CEILING"
        );
        maxTradeInputBps = maxTradeInputBps_;
        maxTradeOutputBps = maxTradeOutputBps_;
        gasPriceCeilingWei = gasPriceCeilingWei_;
        emit SecurityConfigUpdated(
            maxTradeInputBps_,
            maxTradeOutputBps_,
            gasPriceCeilingWei_
        );
    }

    function currentExecutionStateHash() public view returns (bytes32) {
        (uint256 tokenReserve, uint256 usdtReserve) = pairReserves();
        return keccak256(
            abi.encode(
                block.chainid,
                address(this),
                address(pair),
                tokenReserve,
                usdtReserve,
                pair.balanceOf(address(this)),
                syna.totalSupply(),
                syna.balanceOf(address(this)),
                usdt.balanceOf(address(this)),
                robotUsdt,
                treasuryUsdt,
                nonce,
                cooldown,
                priceSum,
                priceCursor
            )
        );
    }

    function currentGasRouteStateHash() public view returns (bytes32) {
        (address pairAddress, uint256 reserveIn, uint256 reserveOut) =
            _orderedReserves(address(usdt), wpol);
        return keccak256(
            abi.encode(
                block.chainid,
                address(this),
                pairAddress,
                address(usdt),
                wpol,
                reserveIn,
                reserveOut,
                treasuryUsdt,
                cumulativeGasRefillUsdt,
                lastGasRefillBlock
            )
        );
    }

    function checkedQuoteOut(address tokenIn, address tokenOut, uint256 amountIn)
        external
        view
        returns (uint256 amountOut)
    {
        return _checkedAmountOut(tokenIn, tokenOut, amountIn);
    }

    function checkedQuoteIn(address tokenIn, address tokenOut, uint256 amountOut)
        external
        view
        returns (uint256 amountIn)
    {
        return _checkedAmountIn(tokenIn, tokenOut, amountOut);
    }

    function executeProtectedCycle(
        uint256 expectedNonce,
        bytes32 expectedStateHash,
        bytes32 expectedParentHash,
        uint256 deadline,
        uint256 maxGasPriceWei,
        uint256 minSystemMetricUsdt
    ) external onlyOperator whenNotPaused lock {
        _enforceEnvelope(
            expectedStateHash,
            expectedParentHash,
            deadline,
            maxGasPriceWei,
            currentExecutionStateHash()
        );
        require(initialized, "NOT_INITIALIZED");
        require(expectedNonce == nonce, "NONCE");
        nonce = expectedNonce + 1;

        _secureEnsureRobotCapital(robotTargetUsdt, deadline);
        require(robotUsdt >= MIN_CYCLE_USDT, "ROBOT_CAPITAL");

        _secureBuy(SCALED_BUY_USDT, deadline);
        _secureBuy(SCALED_BUY_USDT, deadline);
        for (uint256 i = 0; i < 5; ++i) {
            _secureSellNotional(SCALED_SELL_NOTIONAL_USDT, deadline);
        }

        _assertLedger();
        uint256 metric = systemMetricUsdt();
        require(metric >= minSystemMetricUsdt, "METRIC_FLOOR");
        emit ProtectedCycleExecuted(
            expectedNonce,
            expectedStateHash,
            expectedParentHash,
            SCALED_BUY_USDT,
            SCALED_SELL_NOTIONAL_USDT,
            metric,
            spotPriceX18()
        );
    }

    function refillRobotCapitalProtected(
        uint256 targetUsdt,
        bytes32 expectedStateHash,
        bytes32 expectedParentHash,
        uint256 deadline,
        uint256 maxGasPriceWei
    ) external onlyOperator whenNotPaused lock {
        _enforceEnvelope(
            expectedStateHash,
            expectedParentHash,
            deadline,
            maxGasPriceWei,
            currentExecutionStateHash()
        );
        require(targetUsdt >= MIN_CYCLE_USDT, "BAD_REFILL");
        _secureEnsureRobotCapital(targetUsdt, deadline);
        _assertLedger();
        emit ProtectedRobotRefill(targetUsdt, robotUsdt);
    }

    function refillKeeperGasProtected(
        uint256 exactPolOut,
        uint256 maxUsdtIn,
        bytes32 expectedGasRouteStateHash,
        bytes32 expectedParentHash,
        uint256 deadline,
        uint256 maxGasPriceWei
    ) external onlyOperator whenNotPaused lock returns (uint256 usdtSpent) {
        _enforceEnvelope(
            expectedGasRouteStateHash,
            expectedParentHash,
            deadline,
            maxGasPriceWei,
            currentGasRouteStateHash()
        );
        require(exactPolOut > 0 && exactPolOut <= MAX_EXACT_GAS_REFILL_POL, "POL_AMOUNT");
        require(block.number >= lastGasRefillBlock + gasRefillCooldownBlocks, "GAS_COOLDOWN");

        uint256 requiredUsdt = _checkedAmountIn(address(usdt), wpol, exactPolOut);
        require(requiredUsdt > 0 && requiredUsdt <= maxUsdtIn, "GAS_QUOTE_LIMIT");
        require(treasuryUsdt >= maxUsdtIn, "TREASURY_GAS");

        address[] memory path = _path(address(usdt), wpol);
        uint256[] memory amounts = router.swapTokensForExactETH(
            exactPolOut,
            maxUsdtIn,
            path,
            payable(gasRecipient),
            deadline
        );
        require(amounts.length == 2 && amounts[1] == exactPolOut, "GAS_ROUTER_RESULT");
        usdtSpent = amounts[0];
        require(
            usdtSpent > 0 && usdtSpent == requiredUsdt && usdtSpent <= treasuryUsdt,
            "GAS_SPEND"
        );
        treasuryUsdt -= usdtSpent;
        cumulativeGasRefillUsdt += usdtSpent;
        lastGasRefillBlock = block.number;
        _assertLedger();
        emit ProtectedGasRefill(exactPolOut, usdtSpent, gasRecipient);
    }

    function _enforceEnvelope(
        bytes32 expectedStateHash,
        bytes32 expectedParentHash,
        uint256 deadline,
        uint256 maxGasPriceWei,
        bytes32 actualStateHash
    ) internal view {
        require(expectedStateHash != bytes32(0), "ZERO_STATE_COMMIT");
        require(expectedParentHash != bytes32(0), "ZERO_PARENT_COMMIT");
        require(block.timestamp <= deadline, "DEADLINE");
        require(deadline <= block.timestamp + MAX_DEADLINE_WINDOW, "DEADLINE_TOO_LONG");
        require(blockhash(block.number - 1) == expectedParentHash, "PARENT_BLOCK_CHANGED");
        require(actualStateHash == expectedStateHash, "STATE_CHANGED");
        require(
            maxGasPriceWei > 0 && maxGasPriceWei <= gasPriceCeilingWei,
            "GAS_PRICE_LIMIT"
        );
        require(tx.gasprice <= maxGasPriceWei, "GAS_PRICE_EXCEEDED");
    }

    function _secureBuy(uint256 amountUsdt, uint256 deadline) internal {
        require(robotUsdt >= amountUsdt, "ROBOT_USDT");
        uint256 fee = amountUsdt * FEE_BPS / 10_000;
        uint256 net = amountUsdt - fee;
        uint256 quotedOut = _checkedAmountOut(address(usdt), address(syna), net);
        uint256 minOut = quotedOut * (10_000 - maxSlippageBps) / 10_000;
        require(minOut > 0, "BUY_ZERO_MIN_OUT");

        robotUsdt -= amountUsdt;
        treasuryUsdt += fee;
        uint256[] memory amounts = router.swapExactTokensForTokens(
            net,
            minOut,
            _path(address(usdt), address(syna)),
            address(this),
            deadline
        );
        require(
            amounts.length == 2 && amounts[0] == net && amounts[1] >= minOut
                && amounts[1] > 0,
            "BUY_ROUTER_RESULT"
        );
        _stabilize(deadline);
    }

    function _secureSellNotional(uint256 targetUsdt, uint256 deadline) internal {
        uint256 price = spotPriceX18();
        require(price > 0, "ZERO_SELL_PRICE");
        uint256 tokenIn = targetUsdt * PRICE_SCALE / price;
        uint256 available = syna.balanceOf(address(this));
        if (tokenIn > available) tokenIn = available;
        require(tokenIn > 0, "ROBOT_SYNA");

        uint256 quotedOut = _checkedAmountOut(address(syna), address(usdt), tokenIn);
        uint256 minOut = quotedOut * (10_000 - maxSlippageBps) / 10_000;
        require(minOut > 0, "SELL_ZERO_MIN_OUT");
        uint256[] memory amounts = router.swapExactTokensForTokens(
            tokenIn,
            minOut,
            _path(address(syna), address(usdt)),
            address(this),
            deadline
        );
        require(
            amounts.length == 2 && amounts[0] == tokenIn && amounts[1] >= minOut
                && amounts[1] > 0,
            "SELL_ROUTER_RESULT"
        );
        uint256 gross = amounts[1];
        uint256 fee = gross * FEE_BPS / 10_000;
        robotUsdt += gross - fee;
        treasuryUsdt += fee;
        _stabilize(deadline);
    }

    function _secureEnsureRobotCapital(uint256 targetUsdt, uint256 deadline) internal {
        if (robotUsdt >= targetUsdt) return;
        uint256 deficit = targetUsdt - robotUsdt;

        uint256 treasuryMovable = treasuryUsdt > treasuryGasFloorUsdt
            ? treasuryUsdt - treasuryGasFloorUsdt
            : 0;
        uint256 fromTreasury = deficit > treasuryMovable ? treasuryMovable : deficit;
        if (fromTreasury > 0) {
            treasuryUsdt -= fromTreasury;
            robotUsdt += fromTreasury;
            deficit -= fromTreasury;
            emit RobotRefill("TREASURY", fromTreasury, 0, 0);
        }
        if (deficit == 0) return;

        if (!_secureSellRobotTokenForExactUsdt(deficit, deadline)) {
            _secureRemoveBoundedLiquidityForRobot(deficit, deadline);
            if (robotUsdt < targetUsdt) {
                deficit = targetUsdt - robotUsdt;
                _secureSellRobotTokenForExactUsdt(deficit, deadline);
            }
        }
        require(robotUsdt >= MIN_CYCLE_USDT, "REFILL_INSUFFICIENT");
    }

    function _secureSellRobotTokenForExactUsdt(uint256 exactUsdtOut, uint256 deadline)
        internal
        returns (bool completed)
    {
        if (exactUsdtOut == 0) return true;
        uint256 requiredToken = _checkedAmountIn(address(syna), address(usdt), exactUsdtOut);
        uint256 maxTokenIn = requiredToken * (10_000 + maxSlippageBps) / 10_000 + 1;
        if (syna.balanceOf(address(this)) < maxTokenIn) return false;
        uint256[] memory amounts = router.swapTokensForExactTokens(
            exactUsdtOut,
            maxTokenIn,
            _path(address(syna), address(usdt)),
            address(this),
            deadline
        );
        require(
            amounts.length == 2 && amounts[0] > 0 && amounts[0] <= maxTokenIn
                && amounts[1] == exactUsdtOut,
            "REFILL_ROUTER_RESULT"
        );
        robotUsdt += exactUsdtOut;
        emit RobotRefill("ROBOT_SYNA", exactUsdtOut, amounts[0], 0);
        return true;
    }

    function _secureRemoveBoundedLiquidityForRobot(uint256 desiredUsdt, uint256 deadline)
        internal
    {
        uint256 lpBalance = pair.balanceOf(address(this));
        require(lpBalance > 0, "NO_LP_REFILL");
        (uint256 tokenReserve, uint256 usdtReserve) = pairReserves();
        uint256 lpSupply = pair.totalSupply();
        require(lpSupply > 0, "ZERO_LP_SUPPLY");

        uint256 liquidity = (desiredUsdt * lpSupply + usdtReserve - 1) / usdtReserve;
        liquidity = liquidity * (10_000 + maxSlippageBps) / 10_000 + 1;
        uint256 maxLiquidity = lpBalance * maxLpRefillBps / 10_000;
        if (liquidity > maxLiquidity) liquidity = maxLiquidity;
        require(liquidity > 0, "LP_REFILL_DUST");

        uint256 expectedToken = tokenReserve * liquidity / lpSupply;
        uint256 expectedUsdt = usdtReserve * liquidity / lpSupply;
        require(expectedToken > 0 && expectedUsdt > 0, "LP_ZERO_QUOTE");
        (uint256 amountToken, uint256 amountUsdt) = router.removeLiquidity(
            address(syna),
            address(usdt),
            liquidity,
            expectedToken * (10_000 - maxSlippageBps) / 10_000,
            expectedUsdt * (10_000 - maxSlippageBps) / 10_000,
            address(this),
            deadline
        );
        require(amountToken > 0 && amountUsdt > 0, "LP_REFILL_ZERO");
        robotUsdt += amountUsdt;
        emit RobotRefill("LP_UNWIND", amountUsdt, 0, liquidity);
    }

    function _checkedAmountOut(address tokenIn, address tokenOut, uint256 amountIn)
        internal
        view
        returns (uint256 amountOut)
    {
        require(amountIn > 0, "ZERO_AMOUNT_IN");
        (, uint256 reserveIn, uint256 reserveOut) = _orderedReserves(tokenIn, tokenOut);
        require(amountIn * 10_000 <= reserveIn * maxTradeInputBps, "INPUT_PRICE_IMPACT");

        uint256 amountInWithFee = amountIn * QUICKSWAP_FEE_NUMERATOR;
        uint256 denominator = reserveIn * QUICKSWAP_FEE_DENOMINATOR + amountInWithFee;
        require(denominator > 0, "ZERO_QUOTE_DENOMINATOR");
        uint256 localAmountOut = amountInWithFee * reserveOut / denominator;
        require(localAmountOut > 0, "ZERO_LOCAL_PRICE");
        require(
            localAmountOut * 10_000 <= reserveOut * maxTradeOutputBps,
            "OUTPUT_PRICE_IMPACT"
        );

        address[] memory route = _path(tokenIn, tokenOut);
        try router.getAmountsOut(amountIn, route) returns (uint256[] memory amounts) {
            require(amounts.length == 2, "ROUTER_OUT_LENGTH");
            require(amounts[0] == amountIn, "ROUTER_OUT_INPUT");
            require(amounts[1] > 0, "ZERO_ROUTER_PRICE");
            require(amounts[1] == localAmountOut, "ROUTER_OUT_MISMATCH");
            amountOut = amounts[1];
        } catch {
            revert("ROUTER_OUT_REVERT");
        }
    }

    function _checkedAmountIn(address tokenIn, address tokenOut, uint256 amountOut)
        internal
        view
        returns (uint256 amountIn)
    {
        require(amountOut > 0, "ZERO_AMOUNT_OUT");
        (, uint256 reserveIn, uint256 reserveOut) = _orderedReserves(tokenIn, tokenOut);
        require(amountOut < reserveOut, "INSUFFICIENT_ROUTE_LIQUIDITY");
        require(
            amountOut * 10_000 <= reserveOut * maxTradeOutputBps,
            "OUTPUT_PRICE_IMPACT"
        );

        uint256 numerator = reserveIn * amountOut * QUICKSWAP_FEE_DENOMINATOR;
        uint256 denominator = (reserveOut - amountOut) * QUICKSWAP_FEE_NUMERATOR;
        require(denominator > 0, "ZERO_QUOTE_DENOMINATOR");
        uint256 localAmountIn = numerator / denominator + 1;
        require(localAmountIn > 0, "ZERO_LOCAL_PRICE");
        require(
            localAmountIn * 10_000 <= reserveIn * maxTradeInputBps,
            "INPUT_PRICE_IMPACT"
        );

        address[] memory route = _path(tokenIn, tokenOut);
        try router.getAmountsIn(amountOut, route) returns (uint256[] memory amounts) {
            require(amounts.length == 2, "ROUTER_IN_LENGTH");
            require(amounts[1] == amountOut, "ROUTER_IN_OUTPUT");
            require(amounts[0] > 0, "ZERO_ROUTER_PRICE");
            require(amounts[0] == localAmountIn, "ROUTER_IN_MISMATCH");
            amountIn = amounts[0];
        } catch {
            revert("ROUTER_IN_REVERT");
        }
    }

    function _orderedReserves(address tokenIn, address tokenOut)
        internal
        view
        returns (address pairAddress, uint256 reserveIn, uint256 reserveOut)
    {
        require(tokenIn != address(0) && tokenOut != address(0) && tokenIn != tokenOut, "BAD_ROUTE");
        pairAddress = factory.getPair(tokenIn, tokenOut);
        require(pairAddress != address(0) && pairAddress.code.length > 0, "ROUTE_NOT_FOUND");
        IQuickSwapPairV2 routePair = IQuickSwapPairV2(pairAddress);
        (uint112 reserve0, uint112 reserve1,) = routePair.getReserves();
        address token0 = routePair.token0();
        address token1 = routePair.token1();
        require(
            (token0 == tokenIn && token1 == tokenOut)
                || (token0 == tokenOut && token1 == tokenIn),
            "ROUTE_PAIR_MISMATCH"
        );
        if (token0 == tokenIn) {
            reserveIn = uint256(reserve0);
            reserveOut = uint256(reserve1);
        } else {
            reserveIn = uint256(reserve1);
            reserveOut = uint256(reserve0);
        }
        require(reserveIn > 0 && reserveOut > 0, "ZERO_ROUTE_RESERVE");
    }

    function _path(address tokenIn, address tokenOut)
        internal
        pure
        returns (address[] memory route)
    {
        route = new address[](2);
        route[0] = tokenIn;
        route[1] = tokenOut;
    }
}
