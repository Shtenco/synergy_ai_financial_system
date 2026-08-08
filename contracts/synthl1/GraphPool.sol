// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./SafeTransferLib.sol";

interface IMEVCapturePool {
    function tollBps(address pool, bool zeroToOne) external view returns (uint16);
    function checkpoint(address token, uint256 amount) external;
}

interface IERC20ManagedPool {
    function balanceOf(address account) external view returns (uint256);
}

/// @notice Generic constant-product graph pool used by the SynthL1 internal graph.
/// token0 is the protocol-controlled synthetic reserve in managed gradient pools.
/// token1 is the real/quote asset (USDT/USDC/WPOL/WETH/DAI/... ).
contract GraphPool {
    using SafeTransferLib for address;

    address public immutable token0;
    address public immutable token1;
    IMEVCapturePool public immutable capture;

    address public owner;
    address public arbExecutor;
    bool public restrictZeroToOne;
    bool public executorOnlyAllSwaps;

    address public liquidityManager;
    bool public restrictLiquidityProviders;
    address public gradientController;

    uint16 public lpFeeBps = 30;
    bool public paused;
    uint256 private lockState = 1;

    uint256 public reserve0;
    uint256 public reserve1;
    uint256 public totalShares;
    mapping(address => uint256) public shares;

    event LiquidityAdded(address indexed provider, uint256 amount0, uint256 amount1, uint256 sharesOut);
    event LiquidityRemoved(address indexed provider, uint256 amount0, uint256 amount1, uint256 sharesBurned);
    event Swap(address indexed trader, bool zeroToOne, uint256 amountIn, uint256 grossOut, uint256 tollOut, uint256 netOut);
    event LPFeeSet(uint16 bps);
    event Paused(bool value);
    event ArbExecutorSet(address indexed executor, bool restrictZeroToOne);
    event ExecutorOnlyAllSwapsSet(bool enabled);
    event LiquidityManagerSet(address indexed manager, bool restricted);
    event GradientControllerSet(address indexed controller);
    event GradientDebit(uint256 token0Amount, address indexed to, uint256 reserve0After);
    event ManagedSync(uint256 reserve0, uint256 reserve1);

    error Unauthorized();
    error BadConfig();
    error Slippage();
    error Reentrancy();
    error PausedError();
    error InsufficientLiquidity();

    constructor(address token0_, address token1_, address capture_, address owner_) {
        if (
            token0_ == address(0) || token1_ == address(0) || token0_ == token1_ ||
            capture_ == address(0) || owner_ == address(0)
        ) revert BadConfig();
        token0 = token0_;
        token1 = token1_;
        capture = IMEVCapturePool(capture_);
        owner = owner_;
        liquidityManager = owner_;
    }

    modifier onlyOwner(){ if (msg.sender != owner) revert Unauthorized(); _; }
    modifier onlyGradientController(){ if (msg.sender != gradientController) revert Unauthorized(); _; }
    modifier active(){ if (paused) revert PausedError(); _; }
    modifier nonReentrant(){ if (lockState != 1) revert Reentrancy(); lockState = 2; _; lockState = 1; }

    function setLPFeeBps(uint16 bps) external onlyOwner {
        if (bps > 100) revert BadConfig();
        lpFeeBps = bps;
        emit LPFeeSet(bps);
    }

    function setPaused(bool value) external onlyOwner {
        paused = value;
        emit Paused(value);
    }

    function setArbExecutor(address executor, bool restrictDirection) external onlyOwner {
        if ((restrictDirection || executorOnlyAllSwaps) && executor == address(0)) revert BadConfig();
        arbExecutor = executor;
        restrictZeroToOne = restrictDirection;
        emit ArbExecutorSet(executor, restrictDirection);
    }

    /// @notice Production managed-gradient mode. When enabled, BOTH swap
    /// directions must pass through GraphArbExecutor. This prevents a third party
    /// from griefing source/destination synthetic restoration by directly buying
    /// or selling synthetic between the searcher cycle and restoreGradient().
    function setExecutorOnlyAllSwaps(bool enabled) external onlyOwner {
        if (enabled && arbExecutor == address(0)) revert BadConfig();
        executorOnlyAllSwaps = enabled;
        emit ExecutorOnlyAllSwapsSet(enabled);
    }

    function setLiquidityManager(address manager, bool restricted) external onlyOwner {
        if (restricted && manager == address(0)) revert BadConfig();
        liquidityManager = manager;
        restrictLiquidityProviders = restricted;
        emit LiquidityManagerSet(manager, restricted);
    }

    /// @notice Grants only the reserve-gradient controller the ability to move
    /// the protocol-controlled token0 reserve. It never grants token1 withdrawal rights.
    function setGradientController(address controller) external onlyOwner {
        if (controller == address(0)) revert BadConfig();
        gradientController = controller;
        emit GradientControllerSet(controller);
    }

    function addLiquidity(uint256 amount0, uint256 amount1, uint256 minShares)
        external nonReentrant active returns (uint256 s)
    {
        if (restrictLiquidityProviders && msg.sender != liquidityManager) revert Unauthorized();
        if (amount0 == 0 || amount1 == 0) revert BadConfig();

        if (totalShares == 0) {
            s = _sqrt(amount0 * amount1);
        } else {
            uint256 s0 = (amount0 * totalShares) / reserve0;
            uint256 s1 = (amount1 * totalShares) / reserve1;
            s = s0 < s1 ? s0 : s1;
        }
        if (s == 0 || s < minShares) revert Slippage();

        token0.safeTransferFrom(msg.sender, address(this), amount0);
        token1.safeTransferFrom(msg.sender, address(this), amount1);

        reserve0 += amount0;
        reserve1 += amount1;
        totalShares += s;
        shares[msg.sender] += s;
        emit LiquidityAdded(msg.sender, amount0, amount1, s);
    }

    function removeLiquidity(uint256 s, uint256 min0, uint256 min1)
        external nonReentrant returns (uint256 amount0, uint256 amount1)
    {
        if (s == 0 || s > shares[msg.sender]) revert BadConfig();
        amount0 = (reserve0 * s) / totalShares;
        amount1 = (reserve1 * s) / totalShares;
        if (amount0 < min0 || amount1 < min1) revert Slippage();

        shares[msg.sender] -= s;
        totalShares -= s;
        reserve0 -= amount0;
        reserve1 -= amount1;

        token0.safeTransfer(msg.sender, amount0);
        token1.safeTransfer(msg.sender, amount1);
        emit LiquidityRemoved(msg.sender, amount0, amount1, s);
    }

    function gradientDebitToken0(uint256 amount, address to)
        external onlyGradientController nonReentrant active
    {
        if (to == address(0) || amount == 0 || amount >= reserve0) revert BadConfig();
        reserve0 -= amount;
        token0.safeTransfer(to, amount);
        emit GradientDebit(amount, to, reserve0);
    }

    function syncManagedReserves() external onlyGradientController nonReentrant active {
        uint256 b0 = IERC20ManagedPool(token0).balanceOf(address(this));
        uint256 b1 = IERC20ManagedPool(token1).balanceOf(address(this));
        if (b0 == 0 || b1 == 0) revert InsufficientLiquidity();
        reserve0 = b0;
        reserve1 = b1;
        emit ManagedSync(b0, b1);
    }

    function quoteExactIn(bool zeroToOne, uint256 amountIn)
        public view returns (uint256 netOut, uint256 grossOut, uint256 tollOut)
    {
        if (amountIn == 0 || reserve0 == 0 || reserve1 == 0) return (0,0,0);
        uint256 lpFee = (amountIn * lpFeeBps) / 10_000;
        if (lpFee >= amountIn) return (0,0,0);
        uint256 effective = amountIn - lpFee;

        if (zeroToOne) {
            grossOut = (reserve1 * effective) / (reserve0 + effective);
        } else {
            grossOut = (reserve0 * effective) / (reserve1 + effective);
        }

        uint16 bps = capture.tollBps(address(this), zeroToOne);
        tollOut = (grossOut * bps) / 10_000;
        netOut = grossOut - tollOut;
    }

    function swapExactIn(bool zeroToOne, uint256 amountIn, uint256 minNetOut, address to)
        external nonReentrant active returns (uint256 netOut)
    {
        if (to == address(0) || amountIn == 0) revert BadConfig();
        if (executorOnlyAllSwaps && msg.sender != arbExecutor) revert Unauthorized();
        if (zeroToOne && restrictZeroToOne && msg.sender != arbExecutor) revert Unauthorized();

        uint256 grossOut;
        uint256 tollOut;
        (netOut, grossOut, tollOut) = quoteExactIn(zeroToOne, amountIn);
        if (netOut == 0 || netOut < minNetOut) revert Slippage();

        address inToken = zeroToOne ? token0 : token1;
        address outToken = zeroToOne ? token1 : token0;

        inToken.safeTransferFrom(msg.sender, address(this), amountIn);

        if (zeroToOne) {
            reserve0 += amountIn;
            reserve1 -= grossOut;
        } else {
            reserve1 += amountIn;
            reserve0 -= grossOut;
        }

        if (tollOut != 0) {
            outToken.safeTransfer(address(capture), tollOut);
            capture.checkpoint(outToken, tollOut);
        }
        outToken.safeTransfer(to, netOut);

        emit Swap(msg.sender, zeroToOne, amountIn, grossOut, tollOut, netOut);
    }

    function spot1Per0() external view returns (uint256) {
        return reserve0 == 0 ? 0 : (reserve1 * 1e18) / reserve0;
    }

    function actualBalances() external view returns (uint256 balance0, uint256 balance1) {
        balance0 = IERC20ManagedPool(token0).balanceOf(address(this));
        balance1 = IERC20ManagedPool(token1).balanceOf(address(this));
    }

    function _sqrt(uint256 y) private pure returns (uint256 z) {
        if (y == 0) return 0;
        z = y;
        uint256 x = y / 2 + 1;
        while (x < z) {
            z = x;
            x = (y / x + x) / 2;
        }
    }
}
