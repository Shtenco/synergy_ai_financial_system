// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./SafeTransferLib.sol";

interface IERC20GraphExec {
    function balanceOf(address) external view returns (uint256);
}

interface ICaptureGraphExec {
    function checkpoint(address token, uint256 amount) external;
}

/// @notice SystemAccounting-compatible post-trade HardNAV guard.
/// The transient executor itself MUST NOT be a registered protocol hard account.
interface IProtocolNAVAccounting {
    function consolidatedHardNAV1e18() external view returns (int256);
    function isHardAccount(address token, address account) external view returns (bool);
    function isProtocolUSDxAccount(address account) external view returns (bool);
}

/// @notice Public atomic graph router for external searchers / MEV cycles.
/// Searchers supply their own principal. Protocol tax is charged only on
/// REALIZED base-token profit after all route legs, never on principal.
///
/// V13 safety addition:
/// an optional SystemAccounting post-trade guard snapshots protocol HardNAV before
/// the route and requires the actually executed route to increase it by at least
/// `minProtocolNavGain1e18`. This is deliberately a POST-EXECUTION atomic check:
/// the protocol may self-initiate a reserve gradient first; it does not need a
/// precommitted external edge. If the resulting real-asset transfer is not
/// accretive under fresh oracle marks, the entire searcher transaction reverts.
contract GraphArbExecutor {
    using SafeTransferLib for address;

    uint256 public constant MAX_LEGS = 10;
    uint16 public constant MAX_PROFIT_TAX_BPS = 9_900;

    address public owner;
    address public immutable capture;
    uint16 public profitTaxBps;
    bool public paused;
    uint256 private lockState = 1;

    mapping(address => bool) public allowedTarget;
    mapping(address => address) public spenderForTarget;

    // Optional exact settlement binding for a permanently dedicated venue.
    mapping(address => address) public requiredBaseTokenForTarget;

    // Multi-asset settlement gate for V13-style source/destination combinations.
    mapping(address => bool) public baseTokenGateEnabled;
    mapping(address => mapping(address => bool)) public allowedBaseTokenForTarget;

    // Absolute base-token reward floor left to the solver after tax.
    mapping(address => uint256) public minSearcherReward;

    // Optional atomic protocol HardNAV guard.
    address public navAccounting;
    bool public enforceProtocolNAV;
    uint256 public minProtocolNavGain1e18;

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
    event RequiredBaseTokenSet(address indexed target, address indexed baseToken);
    event BaseTokenGateSet(address indexed target, bool enabled);
    event AllowedBaseTokenSet(address indexed target, address indexed baseToken, bool allowed);
    event ProfitTaxSet(uint16 bps);
    event MinSearcherRewardSet(address indexed baseToken, uint256 amount);
    event ProtocolNAVGuardSet(address indexed accounting, bool enabled, uint256 minGain1e18);
    event ProtocolNAVChecked(
        address indexed searcher,
        int256 navBefore1e18,
        int256 navAfter1e18,
        int256 navGain1e18
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
    error NotProfitable();
    error WrongSettlementToken();
    error Reentrancy();
    error PausedError();
    error ProtocolNAVNotImproved();
    error ExecutorMustBeUnaccounted();

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
        }
        emit VenueSet(target, spender, allowed);
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

    /// @notice Maximum share of realized profit captured by the protocol.
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

    /// @notice Enables/disables the atomic post-trade HardNAV gate.
    /// `accounting` is expected to be SystemAccounting. When enabled, this
    /// executor must not itself be registered as a hard-asset or protocol USDx
    /// account; otherwise transient solver balances would contaminate NAV.
    function setProtocolNAVGuard(address accounting, bool enabled, uint256 minGain1e18) external onlyOwner {
        if (enabled && accounting == address(0)) revert BadRoute();
        if (minGain1e18 > uint256(type(int256).max)) revert BadRoute();
        navAccounting = accounting;
        enforceProtocolNAV = enabled;
        minProtocolNavGain1e18 = minGain1e18;
        emit ProtocolNAVGuardSet(accounting, enabled, minGain1e18);
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

        int256 navBefore;
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
            if (leg.tokenIn != expected || leg.amountIn == 0 || leg.amountIn > available) revert BadRoute();
            if (!allowedTarget[leg.target] || spenderForTarget[leg.target] != leg.spender) revert VenueNotAllowed();

            address requiredBase = requiredBaseTokenForTarget[leg.target];
            if (requiredBase != address(0) && requiredBase != baseToken) revert WrongSettlementToken();
            if (baseTokenGateEnabled[leg.target] && !allowedBaseTokenForTarget[leg.target][baseToken]) {
                revert WrongSettlementToken();
            }

            leg.tokenIn.forceApprove(leg.spender, leg.amountIn);
            uint256 beforeOut = IERC20GraphExec(leg.tokenOut).balanceOf(address(this));

            (bool ok,) = leg.target.call(leg.data);
            leg.tokenIn.forceApprove(leg.spender, 0);
            if (!ok) revert ExternalCallFailed();

            uint256 afterOut = IERC20GraphExec(leg.tokenOut).balanceOf(address(this));
            uint256 received = afterOut > beforeOut ? afterOut - beforeOut : 0;
            if (received < leg.minAmountOut) revert InsufficientOutput();

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
        }

        if (enforceProtocolNAV) {
            int256 navAfter = accounting.consolidatedHardNAV1e18();
            int256 navGain = navAfter - navBefore;
            if (navGain < int256(minProtocolNavGain1e18)) revert ProtocolNAVNotImproved();
            emit ProtocolNAVChecked(msg.sender, navBefore, navAfter, navGain);
        }

        returned = principal + netProfit;
        baseToken.safeTransfer(msg.sender, returned);

        emit Cycle(msg.sender, baseToken, principal, grossReturned, grossProfit, protocolTax, netProfit, n);
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
