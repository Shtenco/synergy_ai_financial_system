// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./SafeTransferLib.sol";

interface IUSDxRecursive {
    function mint(address,uint256) external;
    function burnHeld(uint256) external;
    function balanceOf(address) external view returns(uint256);
}

interface ICORERecursive {
    function balanceOf(address) external view returns(uint256);
    function burn(uint256) external;
}

interface IGraphPoolRecursive {
    function token0() external view returns(address);
    function token1() external view returns(address);
    function swapExactIn(bool zeroToOne,uint256 amountIn,uint256 minNetOut,address to) external returns(uint256);
    function spot1Per0() external view returns(uint256);
}

interface ICaptureRecursive {
    function available(address token) external view returns(uint256);
    function pullForReinvestment(address token,address to,uint256 amount) external;
    function setOutputToll(address pool,bool zeroToOne,uint16 bps) external;
}

/// @notice Recursive SynthL1 loop:
/// initial USDx QE -> CORE buyback + burn -> internal graph wedge ->
/// public MEV/searcher closure -> USDx toll capture -> toll reinvestment -> repeat.
contract RecursiveElasticEngine {
    using SafeTransferLib for address;

    address public owner;
    address public operator;

    address public immutable core;
    address public immutable usdx;
    ICaptureRecursive public immutable capture;

    mapping(address => bool) public pulsePool;
    bool public active;
    uint64 public epoch;

    uint256 public initialQEMinted;
    uint256 public cumulativeReinvestedUSDx;
    uint256 public cumulativeCOREBurned;
    uint256 public pulses;
    uint256 public lastPulseUSDx;

    uint256 public minReinvestUSDx = 1e12;

    event PoolSet(address indexed pool, bool allowed);
    event EpochStarted(uint64 indexed epoch, address indexed pool, uint256 qeUSDx, uint256 coreBurned, uint256 newPrice);
    event Reinvested(uint64 indexed epoch, address indexed pool, uint256 usdReused, uint256 coreBurned, uint256 newPrice);
    event EpochStopped(uint64 indexed epoch);
    event TollSet(address indexed pool, bool zeroToOne, uint16 bps);

    error Unauthorized();
    error BadConfig();
    error NotActive();
    error ActiveEpoch();
    error InsufficientCaptured();

    constructor(address core_, address usdx_, address capture_, address owner_, address operator_) {
        if (core_ == address(0) || usdx_ == address(0) || capture_ == address(0) || owner_ == address(0) || operator_ == address(0)) {
            revert BadConfig();
        }
        core = core_;
        usdx = usdx_;
        capture = ICaptureRecursive(capture_);
        owner = owner_;
        operator = operator_;
    }

    modifier onlyOwner(){ if(msg.sender != owner) revert Unauthorized(); _; }
    modifier onlyOperator(){ if(msg.sender != operator) revert Unauthorized(); _; }

    function setOperator(address newOperator) external onlyOwner {
        if (newOperator == address(0)) revert BadConfig();
        operator = newOperator;
    }

    function setPulsePool(address pool, bool allowed) external onlyOwner {
        if (pool == address(0)) revert BadConfig();
        if (allowed) {
            if (IGraphPoolRecursive(pool).token0() != core || IGraphPoolRecursive(pool).token1() != usdx) revert BadConfig();
        }
        pulsePool[pool] = allowed;
        emit PoolSet(pool, allowed);
    }

    function setMinReinvestUSDx(uint256 amount) external onlyOwner {
        minReinvestUSDx = amount;
    }

    function setPoolToll(address pool, bool zeroToOne, uint16 bps) external onlyOperator {
        if (!pulsePool[pool]) revert BadConfig();
        capture.setOutputToll(pool, zeroToOne, bps);
        emit TollSet(pool, zeroToOne, bps);
    }

    function initializeQE(address pool, uint256 qeUSDx, uint256 minCoreOut) external onlyOperator returns (uint256 coreBurned) {
        if (active) revert ActiveEpoch();
        if (!pulsePool[pool] || qeUSDx == 0) revert BadConfig();

        active = true;
        epoch += 1;
        initialQEMinted = qeUSDx;
        cumulativeReinvestedUSDx = 0;
        cumulativeCOREBurned = 0;
        pulses = 0;

        IUSDxRecursive(usdx).mint(address(this), qeUSDx);
        coreBurned = _buybackAndBurn(pool, qeUSDx, minCoreOut);

        lastPulseUSDx = qeUSDx;
        pulses = 1;
        cumulativeCOREBurned = coreBurned;

        emit EpochStarted(epoch, pool, qeUSDx, coreBurned, IGraphPoolRecursive(pool).spot1Per0());
    }

    function reinvestCaptured(address nextPool, uint256 amount, uint256 minCoreOut)
        external onlyOperator returns (uint256 coreBurned)
    {
        if (!active) revert NotActive();
        if (!pulsePool[nextPool] || amount < minReinvestUSDx) revert BadConfig();
        if (capture.available(usdx) < amount) revert InsufficientCaptured();

        capture.pullForReinvestment(usdx, address(this), amount);
        coreBurned = _buybackAndBurn(nextPool, amount, minCoreOut);

        cumulativeReinvestedUSDx += amount;
        cumulativeCOREBurned += coreBurned;
        lastPulseUSDx = amount;
        pulses += 1;

        emit Reinvested(epoch, nextPool, amount, coreBurned, IGraphPoolRecursive(nextPool).spot1Per0());
    }

    function reinvestAll(address nextPool, uint256 minCoreOut)
        external onlyOperator returns (uint256 usdReused, uint256 coreBurned)
    {
        if (!active) revert NotActive();
        if (!pulsePool[nextPool]) revert BadConfig();

        usdReused = capture.available(usdx);
        if (usdReused < minReinvestUSDx) revert InsufficientCaptured();

        capture.pullForReinvestment(usdx, address(this), usdReused);
        coreBurned = _buybackAndBurn(nextPool, usdReused, minCoreOut);

        cumulativeReinvestedUSDx += usdReused;
        cumulativeCOREBurned += coreBurned;
        lastPulseUSDx = usdReused;
        pulses += 1;

        emit Reinvested(epoch, nextPool, usdReused, coreBurned, IGraphPoolRecursive(nextPool).spot1Per0());
    }

    function stopEpoch() external onlyOperator {
        if (!active) revert NotActive();
        active = false;
        emit EpochStopped(epoch);
    }

    function capturedUSDxAvailable() external view returns (uint256) {
        return capture.available(usdx);
    }

    function recycleTurnoverMultiple1e18() external view returns (uint256) {
        if (initialQEMinted == 0) return 0;
        return (cumulativeReinvestedUSDx * 1e18) / initialQEMinted;
    }

    function _buybackAndBurn(address pool, uint256 usdAmount, uint256 minCoreOut) internal returns (uint256 coreOut) {
        usdx.forceApprove(pool, usdAmount);
        coreOut = IGraphPoolRecursive(pool).swapExactIn(false, usdAmount, minCoreOut, address(this));
        usdx.forceApprove(pool, 0);

        if (ICORERecursive(core).balanceOf(address(this)) < coreOut) revert BadConfig();
        ICORERecursive(core).burn(coreOut);
    }
}
