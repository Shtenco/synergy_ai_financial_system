// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./SafeTransferLib.sol";

interface IUSDxGradient {
    function mint(address to, uint256 amount) external;
    function burnHeld(uint256 amount) external;
    function totalSupply() external view returns (uint256);
    function balanceOf(address account) external view returns (uint256);
}

interface IGradientExecutorRegistry {
    function protocolTarget(address target) external view returns (bool);
}

interface IGraphPoolGradient {
    function token0() external view returns (address);
    function token1() external view returns (address);
    function reserve0() external view returns (uint256);
    function reserve1() external view returns (uint256);
    function totalShares() external view returns (uint256);
    function shares(address account) external view returns (uint256);
    function liquidityManager() external view returns (address);
    function restrictLiquidityProviders() external view returns (bool);
    function gradientController() external view returns (address);
    function arbExecutor() external view returns (address);
    function executorOnlyAllSwaps() external view returns (bool);
    function gradientDebitToken0(uint256 amount, address to) external;
    function syncManagedReserves() external;
    function spot1Per0() external view returns (uint256);
}

interface ICaptureGradient {
    function available(address token) external view returns (uint256);
    function pullForReinvestment(address token, address to, uint256 amount) external;
}

interface IAccountingGradient {
    function externalCoverageBps() external view returns (uint256);
    function isProtocolUSDxAccount(address account) external view returns (bool);
    function isProtocolUSDxPoolAccount(address account) external view returns (bool);
    function protocolLiquidityOwner() external view returns (address);
}

/// @notice Supply-neutral self-created edge initiator recovered from the V12/V13 line.
///
/// Core loop:
///   1. debit controlled synthetic reserve from source pool;
///   2. burn it;
///   3. mint the exact same amount into destination pool;
///   4. searchers exploit the resulting cross-pool/cross-asset gradient through
///      GraphArbExecutor, which taxes REALIZED arbitrage profit and enforces a
///      post-trade consolidated HardNAV increase with an oracle-error buffer;
///   5. restore the exact synthetic reserve targets by another equal burn/mint shift;
///   6. reinvest physically captured quote assets into selected protocol pools;
///   7. exploit the gradient again or rotate it.
///
/// No real token1 reserve can be administratively withdrawn by this contract.
/// The controlled synthetic total supply must be identical before/after every shift.
contract ReserveGradientEngine {
    using SafeTransferLib for address;

    address public owner;
    address public operator;

    address public immutable usdx;
    address public immutable protocolLiquidityOwner;
    ICaptureGradient public immutable capture;
    IAccountingGradient public immutable accounting;

    mapping(address => bool) public gradientPool;
    mapping(address => uint256) public cumulativeQuoteReinvested;

    bool public active;
    uint64 public epoch;
    address public sourcePool;
    address public destinationPool;

    uint256 public baselineSourceSynthetic;
    uint256 public baselineDestinationSynthetic;
    uint256 public targetSourceSynthetic;
    uint256 public targetDestinationSynthetic;
    uint256 public initialGradientShift;
    uint256 public lastRestoreShift;
    uint256 public exploitations;

    uint16 public minExternalCoverageBps = 12_000;
    uint16 public maxGradientShiftBps = 9_500;
    uint256 public maxRestoreDust = 10;

    event GradientPoolSet(address indexed pool, bool allowed);
    event GradientInitialized(
        uint64 indexed epoch,
        address indexed sourcePool,
        address indexed destinationPool,
        uint256 shift,
        uint256 sourceSynthetic,
        uint256 destinationSynthetic,
        uint256 sourceSpot,
        uint256 destinationSpot
    );
    event GradientRestored(
        uint64 indexed epoch,
        uint256 indexed exploitation,
        uint256 shift,
        uint256 sourceSynthetic,
        uint256 destinationSynthetic
    );
    event CapturedQuoteReinvested(
        uint64 indexed epoch,
        address indexed pool,
        address indexed quoteToken,
        uint256 amount,
        uint256 quoteReserveAfter
    );
    event GradientClosed(uint64 indexed epoch, uint256 reverseShift);
    event OperatorSet(address indexed operator);
    event CoverageFloorSet(uint16 bps);
    event MaxGradientShiftSet(uint16 bps);
    event MaxRestoreDustSet(uint256 dust);

    error Unauthorized();
    error BadConfig();
    error ActiveGradient();
    error NoActiveGradient();
    error PoolNotManaged();
    error ExecutorMismatch();
    error AccountingNotConfigured();
    error ExternalUSDxUndercovered();
    error GradientTooLarge();
    error InvalidGradientState();
    error SupplyInvariant();
    error RestoreMismatch();
    error InsufficientCaptured();

    constructor(
        address usdx_,
        address capture_,
        address accounting_,
        address protocolLiquidityOwner_,
        address owner_,
        address operator_
    ) {
        if (
            usdx_ == address(0) || capture_ == address(0) || accounting_ == address(0) ||
            protocolLiquidityOwner_ == address(0) || owner_ == address(0) || operator_ == address(0)
        ) revert BadConfig();
        usdx = usdx_;
        capture = ICaptureGradient(capture_);
        accounting = IAccountingGradient(accounting_);
        protocolLiquidityOwner = protocolLiquidityOwner_;
        owner = owner_;
        operator = operator_;
    }

    modifier onlyOwner() { if (msg.sender != owner) revert Unauthorized(); _; }
    modifier onlyOperator() { if (msg.sender != operator) revert Unauthorized(); _; }

    function setOperator(address newOperator) external onlyOwner {
        if (newOperator == address(0)) revert BadConfig();
        operator = newOperator;
        emit OperatorSet(newOperator);
    }

    function setCoverageFloorBps(uint16 bps) external onlyOwner {
        if (bps < 10_000 || bps > 50_000) revert BadConfig();
        minExternalCoverageBps = bps;
        emit CoverageFloorSet(bps);
    }

    function setMaxGradientShiftBps(uint16 bps) external onlyOwner {
        if (bps < 100 || bps > 9_900) revert BadConfig();
        maxGradientShiftBps = bps;
        emit MaxGradientShiftSet(bps);
    }

    function setMaxRestoreDust(uint256 dust) external onlyOwner {
        maxRestoreDust = dust;
        emit MaxRestoreDustSet(dust);
    }

    function setGradientPool(address pool, bool allowed) external onlyOwner {
        if (pool == address(0)) revert BadConfig();
        if (allowed) _requireManagedPool(pool);
        gradientPool[pool] = allowed;
        emit GradientPoolSet(pool, allowed);
    }

    function initializeGradient(address source, address destination, uint256 shift)
        external onlyOperator
    {
        if (active) revert ActiveGradient();
        if (
            source == address(0) || destination == address(0) || source == destination ||
            !gradientPool[source] || !gradientPool[destination] || shift == 0
        ) revert BadConfig();

        _requireManagedPool(source);
        _requireManagedPool(destination);
        if (IGraphPoolGradient(source).arbExecutor() != IGraphPoolGradient(destination).arbExecutor()) {
            revert ExecutorMismatch();
        }
        _requireSolvent();

        uint256 sourceBefore = IGraphPoolGradient(source).reserve0();
        uint256 destinationBefore = IGraphPoolGradient(destination).reserve0();
        if (shift >= sourceBefore) revert GradientTooLarge();
        if (shift * 10_000 > sourceBefore * uint256(maxGradientShiftBps)) revert GradientTooLarge();

        uint256 supplyBefore = IUSDxGradient(usdx).totalSupply();
        _shiftSynthetic(source, destination, shift);
        if (IUSDxGradient(usdx).totalSupply() != supplyBefore) revert SupplyInvariant();

        baselineSourceSynthetic = sourceBefore;
        baselineDestinationSynthetic = destinationBefore;
        targetSourceSynthetic = sourceBefore - shift;
        targetDestinationSynthetic = destinationBefore + shift;
        initialGradientShift = shift;
        lastRestoreShift = 0;
        exploitations = 0;
        sourcePool = source;
        destinationPool = destination;
        active = true;
        epoch += 1;

        _requireReserveNear(IGraphPoolGradient(source).reserve0(), targetSourceSynthetic);
        _requireReserveNear(IGraphPoolGradient(destination).reserve0(), targetDestinationSynthetic);

        emit GradientInitialized(
            epoch,
            source,
            destination,
            shift,
            targetSourceSynthetic,
            targetDestinationSynthetic,
            IGraphPoolGradient(source).spot1Per0(),
            IGraphPoolGradient(destination).spot1Per0()
        );
    }

    function restoreGradient() external onlyOperator returns (uint256 restored) {
        if (!active) revert NoActiveGradient();
        _requireSolvent();

        uint256 sourceCurrent = IGraphPoolGradient(sourcePool).reserve0();
        uint256 destinationCurrent = IGraphPoolGradient(destinationPool).reserve0();
        if (sourceCurrent < targetSourceSynthetic || destinationCurrent > targetDestinationSynthetic) {
            revert InvalidGradientState();
        }

        uint256 sourceExcess = sourceCurrent - targetSourceSynthetic;
        uint256 destinationDeficit = targetDestinationSynthetic - destinationCurrent;
        if (sourceExcess == 0 || destinationDeficit == 0) revert InvalidGradientState();

        uint256 mismatch = sourceExcess > destinationDeficit
            ? sourceExcess - destinationDeficit
            : destinationDeficit - sourceExcess;
        if (mismatch > maxRestoreDust) revert RestoreMismatch();

        restored = sourceExcess < destinationDeficit ? sourceExcess : destinationDeficit;
        uint256 supplyBefore = IUSDxGradient(usdx).totalSupply();
        _shiftSynthetic(sourcePool, destinationPool, restored);
        if (IUSDxGradient(usdx).totalSupply() != supplyBefore) revert SupplyInvariant();

        _requireReserveNear(IGraphPoolGradient(sourcePool).reserve0(), targetSourceSynthetic);
        _requireReserveNear(IGraphPoolGradient(destinationPool).reserve0(), targetDestinationSynthetic);

        lastRestoreShift = restored;
        exploitations += 1;
        emit GradientRestored(
            epoch,
            exploitations,
            restored,
            IGraphPoolGradient(sourcePool).reserve0(),
            IGraphPoolGradient(destinationPool).reserve0()
        );
    }

    function reinvestCapturedQuote(address pool, uint256 amount) external onlyOperator {
        if (!active) revert NoActiveGradient();
        if (!gradientPool[pool] || amount == 0) revert BadConfig();
        _requireManagedPool(pool);

        address quote = IGraphPoolGradient(pool).token1();
        if (capture.available(quote) < amount) revert InsufficientCaptured();
        capture.pullForReinvestment(quote, address(this), amount);
        quote.safeTransfer(pool, amount);
        IGraphPoolGradient(pool).syncManagedReserves();
        cumulativeQuoteReinvested[quote] += amount;

        emit CapturedQuoteReinvested(
            epoch,
            pool,
            quote,
            amount,
            IGraphPoolGradient(pool).reserve1()
        );
    }

    function closeGradient() external onlyOperator {
        if (!active) revert NoActiveGradient();
        _requireReserveNear(IGraphPoolGradient(sourcePool).reserve0(), targetSourceSynthetic);
        _requireReserveNear(IGraphPoolGradient(destinationPool).reserve0(), targetDestinationSynthetic);

        uint256 supplyBefore = IUSDxGradient(usdx).totalSupply();
        _shiftSynthetic(destinationPool, sourcePool, initialGradientShift);
        if (IUSDxGradient(usdx).totalSupply() != supplyBefore) revert SupplyInvariant();

        _requireReserveNear(IGraphPoolGradient(sourcePool).reserve0(), baselineSourceSynthetic);
        _requireReserveNear(IGraphPoolGradient(destinationPool).reserve0(), baselineDestinationSynthetic);

        active = false;
        emit GradientClosed(epoch, initialGradientShift);
    }

    function gradientPriceRatio1e18() external view returns (uint256) {
        if (!active) return 0;
        uint256 sourceSpot = IGraphPoolGradient(sourcePool).spot1Per0();
        uint256 destinationSpot = IGraphPoolGradient(destinationPool).spot1Per0();
        if (destinationSpot == 0) return 0;
        return (sourceSpot * 1e18) / destinationSpot;
    }

    function _shiftSynthetic(address fromPool, address toPool, uint256 amount) internal {
        IGraphPoolGradient(fromPool).gradientDebitToken0(amount, address(this));
        if (IUSDxGradient(usdx).balanceOf(address(this)) < amount) revert SupplyInvariant();
        IUSDxGradient(usdx).burnHeld(amount);
        IUSDxGradient(usdx).mint(toPool, amount);
        IGraphPoolGradient(fromPool).syncManagedReserves();
        IGraphPoolGradient(toPool).syncManagedReserves();
    }

    function _requireManagedPool(address pool) internal view {
        IGraphPoolGradient p = IGraphPoolGradient(pool);
        if (p.token0() != usdx) revert PoolNotManaged();
        uint256 total = p.totalShares();
        if (total == 0 || p.shares(protocolLiquidityOwner) != total) revert PoolNotManaged();
        if (!p.restrictLiquidityProviders() || p.liquidityManager() != protocolLiquidityOwner) revert PoolNotManaged();
        if (p.gradientController() != address(this)) revert PoolNotManaged();

        address executor = p.arbExecutor();
        if (!p.executorOnlyAllSwaps() || executor == address(0)) revert PoolNotManaged();
        // Ensures the executor's oracle-error turnover buffer cannot silently omit
        // this managed internal pool.
        if (!IGradientExecutorRegistry(executor).protocolTarget(pool)) revert PoolNotManaged();

        if (!accounting.isProtocolUSDxPoolAccount(pool)) revert AccountingNotConfigured();
        if (accounting.protocolLiquidityOwner() != protocolLiquidityOwner) revert AccountingNotConfigured();
        if (!accounting.isProtocolUSDxAccount(address(capture))) revert AccountingNotConfigured();
    }

    function _requireSolvent() internal view {
        if (accounting.externalCoverageBps() < minExternalCoverageBps) revert ExternalUSDxUndercovered();
    }

    function _requireReserveNear(uint256 actual, uint256 expected) internal view {
        uint256 d = actual > expected ? actual - expected : expected - actual;
        if (d > maxRestoreDust) revert RestoreMismatch();
    }
}
