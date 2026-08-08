// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./SafeTransferLib.sol";

interface IERC20GraphExec {
    function balanceOf(address) external view returns (uint256);
}

interface ICaptureGraphExec {
    function checkpoint(address token, uint256 amount) external;
}

interface IProtocolNAVAccounting {
    function consolidatedHardNAV1e18() external view returns (int256);
    function isHardAccount(address token, address account) external view returns (bool);
    function isProtocolUSDxAccount(address account) external view returns (bool);
    function isHardAsset(address token) external view returns (bool);
    function markValue1e18(address token, uint256 amount) external view returns (uint256);
}

interface IActiveGradientExec {
    function active() external view returns (bool);
    function sourcePool() external view returns (address);
    function destinationPool() external view returns (address);
    function usdx() external view returns (address);
}

interface IGradientPoolExecView {
    function token0() external view returns (address);
    function token1() external view returns (address);
}

/// @notice Public atomic graph router for external searchers / MEV cycles.
/// Searchers supply their own principal. Protocol tax is charged only on
/// REALIZED base-token profit after all route legs, never on principal.
///
/// Managed-gradient mode binds the first two legs to the currently active
/// destination/source pair:
///
///   destinationQuote -> synthetic(destination)
///   synthetic -> sourceQuote(source)
///   sourceQuote -> external graph -> destinationQuote
///
/// No other protocolTarget may appear later in that cycle. Multiple searchers may
/// repeat the same active-pair geometry before ReserveGradientEngine restores the
/// accumulated equal-and-opposite synthetic reserve displacement.
contract GraphArbExecutor {
    using SafeTransferLib for address;

    uint256 public constant MAX_LEGS = 10;
    uint16 public constant MAX_PROFIT_TAX_BPS = 9_900;
    uint16 public constant MAX_ORACLE_ERROR_BPS = 1_000;

    address public owner;
    address public immutable capture;
    uint16 public profitTaxBps;
    bool public paused;
    uint256 private lockState = 1;

    mapping(address => bool) public allowedTarget;
    mapping(address => address) public spenderForTarget;
    mapping(address => bool) public protocolTarget;

    mapping(address => address) public requiredBaseTokenForTarget;
    mapping(address => bool) public baseTokenGateEnabled;
    mapping(address => mapping(address => bool)) public allowedBaseTokenForTarget;
    mapping(address => uint256) public minSearcherReward;

    address public navAccounting;
    bool public enforceProtocolNAV;
    uint256 public minProtocolNavGain1e18;
    uint16 public maxOracleErrorBps;

    address public gradientEngine;
    bool public enforceActiveGradientPair;

    struct Leg {
        address target;
        address spender;
        address tokenIn;
        address tokenOut;
        uint256 amountIn;
        uint256 minAmountOut;
        bytes data;
    }

    event VenueSet(address indexed target, address indexed spender, bool allowed);
    event ProtocolTargetSet(address indexed target, bool protocolOwned);
    event RequiredBaseTokenSet(address indexed target, address indexed baseToken);
    event BaseTokenGateSet(address indexed target, bool enabled);
    event AllowedBaseTokenSet(address indexed target, address indexed baseToken, bool allowed);
    event ProfitTaxSet(uint16 bps);
    event MinSearcherRewardSet(address indexed baseToken, uint256 amount);
    event ProtocolNAVGuardSet(address indexed accounting, bool enabled, uint256 minGain1e18);
    event MaxOracleErrorSet(uint16 bps);
    event GradientEngineSet(address indexed engine, bool enforceActivePair);
    event ProtocolNAVChecked(
        address indexed searcher,
        int256 navBefore1e18,
        int256 navAfter1e18,
        int256 navGain1e18,
        uint256 hardTurnover1e18,
        uint256 uncertaintyBuffer1e18,
        uint256 requiredGain1e18
    );
    event Cycle(
        address indexed searcher,
        address indexed baseToken,
        uint256 principal,
        uint256 grossReturned,
        uint256 grossProfit,
        uint256 protocolTax,
        uint256 netProfit,
        uint256 legs
    );

    error Unauthorized();
    error BadRoute();
    error VenueNotAllowed();
    error ExternalCallFailed();
    error InsufficientOutput();
    error InputNotConsumed();
    error NotProfitable();
    error WrongSettlementToken();
    error Reentrancy();
    error PausedError();
    error ProtocolNAVNotImproved();
    error ExecutorMustBeUnaccounted();
    error GradientRouteMismatch();

    constructor(address owner_, address capture_) {
        if (owner_ == address(0) || capture_ == address(0)) revert BadRoute();
        owner = owner_;
        capture = capture_;
    }

    modifier onlyOwner(){ if (msg.sender != owner) revert Unauthorized(); _; }
    modifier nonReentrant(){ if (lockState != 1) revert Reentrancy(); lockState = 2; _; lockState = 1; }

    function setVenue(address target, address spender, bool allowed) external onlyOwner {
        if (target == address(0) || spender == address(0)) revert BadRoute();
        allowedTarget[target] = allowed;
        spenderForTarget[target] = allowed ? spender : address(0);
        if (!allowed) {
            requiredBaseTokenForTarget[target] = address(0);
            baseTokenGateEnabled[target] = false;
            protocolTarget[target] = false;
        }
        emit VenueSet(target, spender, allowed);
    }

    function setProtocolTarget(address target, bool protocolOwned) external onlyOwner {
        if (!allowedTarget[target]) revert VenueNotAllowed();
        protocolTarget[target] = protocolOwned;
        emit ProtocolTargetSet(target, protocolOwned);
    }

    function setRequiredBaseToken(address target, address baseToken) external onlyOwner {
        if (!allowedTarget[target]) revert VenueNotAllowed();
        requiredBaseTokenForTarget[target] = baseToken;
        emit RequiredBaseTokenSet(target, baseToken);
    }

    function setBaseTokenGate(address target, bool enabled) external onlyOwner {
        if (!allowedTarget[target]) revert VenueNotAllowed();
        baseTokenGateEnabled[target] = enabled;
        emit BaseTokenGateSet(target, enabled);
    }

    function setAllowedBaseToken(address target, address baseToken, bool allowed) external onlyOwner {
        if (!allowedTarget[target] || baseToken == address(0)) revert VenueNotAllowed();
        allowedBaseTokenForTarget[target][baseToken] = allowed;
        emit AllowedBaseTokenSet(target, baseToken, allowed);
    }

    function setProfitTaxBps(uint16 bps) external onlyOwner {
        if (bps > MAX_PROFIT_TAX_BPS) revert BadRoute();
        profitTaxBps = bps;
        emit ProfitTaxSet(bps);
    }

    function setMinSearcherReward(address baseToken, uint256 amount) external onlyOwner {
        if (baseToken == address(0)) revert BadRoute();
        minSearcherReward[baseToken] = amount;
        emit MinSearcherRewardSet(baseToken, amount);
    }

    function setProtocolNAVGuard(address accounting, bool enabled, uint256 minGain1e18) external onlyOwner {
        if (enabled && accounting == address(0)) revert BadRoute();
        if (minGain1e18 > uint256(type(int256).max)) revert BadRoute();
        navAccounting = accounting;
        enforceProtocolNAV = enabled;
        minProtocolNavGain1e18 = minGain1e18;
        emit ProtocolNAVGuardSet(accounting, enabled, minGain1e18);
    }

    function setMaxOracleErrorBps(uint16 bps) external onlyOwner {
        if (bps > MAX_ORACLE_ERROR_BPS) revert BadRoute();
        maxOracleErrorBps = bps;
        emit MaxOracleErrorSet(bps);
    }

    function setGradientEngine(address engine, bool enforcePair) external onlyOwner {
        if (enforcePair && engine == address(0)) revert BadRoute();
        gradientEngine = engine;
        enforceActiveGradientPair = enforcePair;
        emit GradientEngineSet(engine, enforcePair);
    }

    function setPaused(bool value) external onlyOwner { paused = value; }

    function executeCycle(
        address baseToken,
        uint256 principal,
        uint256 minNetProfit,
        Leg[] calldata legs,
        uint256 deadline
    ) external nonReentrant returns (uint256 returned, uint256 netProfit) {
        if (paused) revert PausedError();
        if (block.timestamp > deadline || principal == 0 || baseToken == address(0)) revert BadRoute();

        uint256 n = legs.length;
        if (n < 2 || n > MAX_LEGS) revert BadRoute();
        if (legs[0].tokenIn != baseToken || legs[n-1].tokenOut != baseToken) revert BadRoute();
        if (enforceActiveGradientPair) _validateActiveGradientRoute(baseToken, legs);

        int256 navBefore;
        uint256 hardTurnover1e18;
        IProtocolNAVAccounting accounting;
        if (enforceProtocolNAV) {
            accounting = IProtocolNAVAccounting(navAccounting);
            _requireExecutorUnaccounted(accounting, baseToken, legs);
            navBefore = accounting.consolidatedHardNAV1e18();
        }

        baseToken.safeTransferFrom(msg.sender, address(this), principal);
        uint256 startingBase = IERC20GraphExec(baseToken).balanceOf(address(this));

        address expected = baseToken;
        uint256 available = principal;

        for (uint256 i = 0; i < n; ++i) {
            Leg calldata leg = legs[i];
            if (
                leg.tokenIn != expected || leg.tokenIn == leg.tokenOut ||
                leg.amountIn == 0 || leg.amountIn != available
            ) revert BadRoute();
            if (!allowedTarget[leg.target] || spenderForTarget[leg.target] != leg.spender) revert VenueNotAllowed();

            address requiredBase = requiredBaseTokenForTarget[leg.target];
            if (requiredBase != address(0) && requiredBase != baseToken) revert WrongSettlementToken();
            if (baseTokenGateEnabled[leg.target] && !allowedBaseTokenForTarget[leg.target][baseToken]) {
                revert WrongSettlementToken();
            }

            uint256 beforeIn = IERC20GraphExec(leg.tokenIn).balanceOf(address(this));
            uint256 beforeOut = IERC20GraphExec(leg.tokenOut).balanceOf(address(this));
            if (beforeIn < leg.amountIn) revert BadRoute();

            leg.tokenIn.forceApprove(leg.spender, leg.amountIn);
            (bool ok,) = leg.target.call(leg.data);
            leg.tokenIn.forceApprove(leg.spender, 0);
            if (!ok) revert ExternalCallFailed();

            uint256 afterIn = IERC20GraphExec(leg.tokenIn).balanceOf(address(this));
            uint256 afterOut = IERC20GraphExec(leg.tokenOut).balanceOf(address(this));
            if (afterIn > beforeIn || beforeIn - afterIn != leg.amountIn) revert InputNotConsumed();

            uint256 received = afterOut > beforeOut ? afterOut - beforeOut : 0;
            if (received < leg.minAmountOut) revert InsufficientOutput();

            if (enforceProtocolNAV) {
                bool explicitProtocolTarget = protocolTarget[leg.target];
                bool registeredInputAccount = accounting.isHardAccount(leg.tokenIn, leg.target);
                bool registeredOutputAccount = accounting.isHardAccount(leg.tokenOut, leg.target);

                if (
                    accounting.isHardAsset(leg.tokenIn) &&
                    (explicitProtocolTarget || registeredInputAccount)
                ) {
                    hardTurnover1e18 += accounting.markValue1e18(leg.tokenIn, leg.amountIn);
                }
                if (
                    accounting.isHardAsset(leg.tokenOut) &&
                    (explicitProtocolTarget || registeredOutputAccount)
                ) {
                    hardTurnover1e18 += accounting.markValue1e18(leg.tokenOut, received);
                }
            }

            expected = leg.tokenOut;
            available = received;
        }

        uint256 endingBase = IERC20GraphExec(baseToken).balanceOf(address(this));
        uint256 grossReturned = endingBase + principal >= startingBase
            ? endingBase + principal - startingBase
            : 0;
        if (grossReturned <= principal) revert NotProfitable();

        uint256 grossProfit = grossReturned - principal;
        uint256 rewardFloor = minSearcherReward[baseToken];
        if (grossProfit <= rewardFloor) revert NotProfitable();

        uint256 protocolTax = (grossProfit * profitTaxBps) / 10_000;
        uint256 maxTaxLeavingFloor = grossProfit - rewardFloor;
        if (protocolTax > maxTaxLeavingFloor) protocolTax = maxTaxLeavingFloor;

        netProfit = grossProfit - protocolTax;
        if (netProfit < minNetProfit) revert NotProfitable();

        if (protocolTax != 0) {
            baseToken.safeTransfer(capture, protocolTax);
            ICaptureGraphExec(capture).checkpoint(baseToken, protocolTax);
            if (enforceProtocolNAV && accounting.isHardAsset(baseToken)) {
                hardTurnover1e18 += accounting.markValue1e18(baseToken, protocolTax);
            }
        }

        if (enforceProtocolNAV) {
            int256 navAfter = accounting.consolidatedHardNAV1e18();
            int256 navGain = navAfter - navBefore;
            uint256 uncertaintyBuffer1e18 =
                (hardTurnover1e18 * uint256(maxOracleErrorBps)) / 10_000;
            uint256 requiredGain1e18 = minProtocolNavGain1e18 + uncertaintyBuffer1e18;
            if (requiredGain1e18 > uint256(type(int256).max)) revert ProtocolNAVNotImproved();
            if (navGain < int256(requiredGain1e18)) revert ProtocolNAVNotImproved();
            emit ProtocolNAVChecked(
                msg.sender,
                navBefore,
                navAfter,
                navGain,
                hardTurnover1e18,
                uncertaintyBuffer1e18,
                requiredGain1e18
            );
        }

        returned = principal + netProfit;
        baseToken.safeTransfer(msg.sender, returned);

        emit Cycle(msg.sender, baseToken, principal, grossReturned, grossProfit, protocolTax, netProfit, n);
    }

    function _validateActiveGradientRoute(address baseToken, Leg[] calldata legs) internal view {
        if (legs.length < 3 || gradientEngine == address(0)) revert GradientRouteMismatch();
        IActiveGradientExec engine = IActiveGradientExec(gradientEngine);
        if (!engine.active()) revert GradientRouteMismatch();

        address source = engine.sourcePool();
        address destination = engine.destinationPool();
        address synthetic = engine.usdx();
        if (source == address(0) || destination == address(0) || source == destination) revert GradientRouteMismatch();

        address destinationQuote = IGradientPoolExecView(destination).token1();
        address sourceQuote = IGradientPoolExecView(source).token1();
        if (IGradientPoolExecView(destination).token0() != synthetic) revert GradientRouteMismatch();
        if (IGradientPoolExecView(source).token0() != synthetic) revert GradientRouteMismatch();
        if (destinationQuote != baseToken || sourceQuote == destinationQuote) revert GradientRouteMismatch();

        Leg calldata first = legs[0];
        Leg calldata second = legs[1];
        if (
            first.target != destination || first.tokenIn != destinationQuote || first.tokenOut != synthetic ||
            second.target != source || second.tokenIn != synthetic || second.tokenOut != sourceQuote
        ) revert GradientRouteMismatch();
        if (!protocolTarget[destination] || !protocolTarget[source]) revert GradientRouteMismatch();

        for (uint256 i = 2; i < legs.length; ++i) {
            if (protocolTarget[legs[i].target]) revert GradientRouteMismatch();
        }
    }

    function _requireExecutorUnaccounted(
        IProtocolNAVAccounting accounting,
        address baseToken,
        Leg[] calldata legs
    ) internal view {
        if (accounting.isProtocolUSDxAccount(address(this))) revert ExecutorMustBeUnaccounted();
        if (accounting.isHardAccount(baseToken, address(this))) revert ExecutorMustBeUnaccounted();
        for (uint256 i = 0; i < legs.length; ++i) {
            if (
                accounting.isHardAccount(legs[i].tokenIn, address(this)) ||
                accounting.isHardAccount(legs[i].tokenOut, address(this))
            ) revert ExecutorMustBeUnaccounted();
        }
    }
}
