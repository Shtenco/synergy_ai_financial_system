// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "./SafeTransferLib.sol";

interface IERC20GraphExec {
    function balanceOf(address) external view returns (uint256);
}

interface ICaptureGraphExec {
    function checkpoint(address token, uint256 amount) external;
}

/// @notice Public atomic graph router for MEV/searcher cycles.
/// The searcher supplies its own principal. Every venue must be allowlisted.
/// A configurable tax is charged only on REALIZED base-token profit, never on
/// principal or gross swap output.
///
/// Managed pulse pools may additionally require one settlement/base token (USDx
/// in the recursive engine). This prevents closing the QE wedge with a CORE-based
/// cycle that would pay the protocol tax in the wrong asset and bypass USDx recycling.
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
    mapping(address => address) public requiredBaseTokenForTarget;

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
    event ProfitTaxSet(uint16 bps);
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
        if (!allowed) requiredBaseTokenForTarget[target] = address(0);
        emit VenueSet(target, spender, allowed);
    }

    /// @notice Set to zero for unrestricted settlement; set to USDx for managed pulse pools.
    function setRequiredBaseToken(address target, address baseToken) external onlyOwner {
        if (!allowedTarget[target]) revert VenueNotAllowed();
        requiredBaseTokenForTarget[target] = baseToken;
        emit RequiredBaseTokenSet(target, baseToken);
    }

    function setProfitTaxBps(uint16 bps) external onlyOwner {
        if (bps > MAX_PROFIT_TAX_BPS) revert BadRoute();
        profitTaxBps = bps;
        emit ProfitTaxSet(bps);
    }

    function setPaused(bool value) external onlyOwner { paused = value; }

    /// @param minNetProfit Minimum profit retained by the searcher AFTER protocol tax.
    function executeCycle(
        address baseToken,
        uint256 principal,
        uint256 minNetProfit,
        Leg[] calldata legs,
        uint256 deadline
    ) external nonReentrant returns (uint256 returned, uint256 netProfit) {
        if (paused) revert PausedError();
        if (block.timestamp > deadline || principal == 0) revert BadRoute();

        uint256 n = legs.length;
        if (n < 2 || n > MAX_LEGS) revert BadRoute();
        if (legs[0].tokenIn != baseToken || legs[n-1].tokenOut != baseToken) revert BadRoute();

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
        uint256 grossReturned = endingBase + principal >= startingBase ? endingBase + principal - startingBase : 0;
        if (grossReturned <= principal) revert NotProfitable();

        uint256 grossProfit = grossReturned - principal;
        uint256 protocolTax = (grossProfit * profitTaxBps) / 10_000;
        netProfit = grossProfit - protocolTax;
        if (netProfit < minNetProfit) revert NotProfitable();

        if (protocolTax != 0) {
            baseToken.safeTransfer(capture, protocolTax);
            ICaptureGraphExec(capture).checkpoint(baseToken, protocolTax);
        }

        returned = principal + netProfit;
        baseToken.safeTransfer(msg.sender, returned);

        emit Cycle(msg.sender, baseToken, principal, grossReturned, grossProfit, protocolTax, netProfit, n);
    }
}
