// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

interface IPrivateRFQSettlementV151 {
    struct Order {
        address maker;
        address taker;
        address tokenIn;
        address tokenOut;
        uint256 amountIn;
        uint256 amountOut;
        uint256 expiry;
        uint256 nonce;
        bytes32 salt;
    }

    function hashOrder(Order calldata order) external view returns (bytes32);
    function fill(Order calldata order, bytes calldata signature) external returns (uint256 amountOut);
}

/// @notice Maker-signed, full-fill RFQ settlement. Availability of a quote is
/// not assumed: strict evidence may count it only when quote provenance is
/// independently supplied and authenticated.
contract PrivateRFQSettlementV151 is EIP712, ReentrancyGuard, IPrivateRFQSettlementV151 {
    using SafeERC20 for IERC20;

    bytes32 public constant ORDER_TYPEHASH = keccak256(
        "Order(address maker,address taker,address tokenIn,address tokenOut,uint256 amountIn,uint256 amountOut,uint256 expiry,uint256 nonce,bytes32 salt)"
    );

    mapping(address maker => mapping(uint256 nonce => bool unavailable)) public nonceUnavailable;

    error InvalidOrder();
    error InvalidSignature();
    error Expired();
    error Replay();

    event NonceCancelled(address indexed maker, uint256 indexed nonce);
    event RFQFilled(
        bytes32 indexed orderHash,
        address indexed maker,
        address indexed taker,
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 amountOut,
        uint256 nonce
    );

    constructor() EIP712("SINERGY Private RFQ V15.1", "1") {}

    function cancelNonce(uint256 nonce) external {
        if (nonceUnavailable[msg.sender][nonce]) revert Replay();
        nonceUnavailable[msg.sender][nonce] = true;
        emit NonceCancelled(msg.sender, nonce);
    }

    function hashOrder(Order calldata order) public view override returns (bytes32) {
        bytes32 structHash = keccak256(
            abi.encode(
                ORDER_TYPEHASH,
                order.maker,
                order.taker,
                order.tokenIn,
                order.tokenOut,
                order.amountIn,
                order.amountOut,
                order.expiry,
                order.nonce,
                order.salt
            )
        );
        return _hashTypedDataV4(structHash);
    }

    function fill(Order calldata order, bytes calldata signature)
        external
        override
        nonReentrant
        returns (uint256 amountOut)
    {
        if (
            order.maker == address(0)
                || order.taker == address(0)
                || order.taker != msg.sender
                || order.tokenIn == address(0)
                || order.tokenOut == address(0)
                || order.tokenIn == order.tokenOut
                || order.amountIn == 0
                || order.amountOut == 0
        ) revert InvalidOrder();
        if (block.timestamp > order.expiry) revert Expired();
        if (nonceUnavailable[order.maker][order.nonce]) revert Replay();

        bytes32 digest = hashOrder(order);
        if (ECDSA.recover(digest, signature) != order.maker) revert InvalidSignature();

        nonceUnavailable[order.maker][order.nonce] = true;
        IERC20(order.tokenIn).safeTransferFrom(msg.sender, order.maker, order.amountIn);
        IERC20(order.tokenOut).safeTransferFrom(order.maker, msg.sender, order.amountOut);

        emit RFQFilled(
            digest,
            order.maker,
            msg.sender,
            order.tokenIn,
            order.tokenOut,
            order.amountIn,
            order.amountOut,
            order.nonce
        );
        return order.amountOut;
    }
}

/// @notice Adapter for `PrivateRFQSettlementV151`.
/// `data = abi.encode(Order order, bytes makerSignature)` and the order taker
/// must be this adapter.
contract PrivateRFQAdapterV151 is ReentrancyGuard {
    using SafeERC20 for IERC20;

    IPrivateRFQSettlementV151 public immutable settlement;

    error InvalidConfiguration();
    error InsufficientOutput();

    constructor(address settlement_) {
        if (settlement_ == address(0) || settlement_.code.length == 0) {
            revert InvalidConfiguration();
        }
        settlement = IPrivateRFQSettlementV151(settlement_);
    }

    function swap(
        address tokenIn,
        address tokenOut,
        uint256 amountIn,
        uint256 minAmountOut,
        address recipient,
        bytes calldata data
    ) external nonReentrant returns (uint256 amountOut) {
        (
            IPrivateRFQSettlementV151.Order memory order,
            bytes memory makerSignature
        ) = abi.decode(data, (IPrivateRFQSettlementV151.Order, bytes));

        if (
            tokenIn == address(0)
                || tokenOut == address(0)
                || tokenIn == tokenOut
                || recipient == address(0)
                || amountIn == 0
                || minAmountOut == 0
                || order.taker != address(this)
                || order.tokenIn != tokenIn
                || order.tokenOut != tokenOut
                || order.amountIn != amountIn
        ) revert InvalidConfiguration();

        IERC20(tokenIn).safeTransferFrom(msg.sender, address(this), amountIn);
        IERC20(tokenIn).forceApprove(address(settlement), amountIn);
        amountOut = settlement.fill(order, makerSignature);
        IERC20(tokenIn).forceApprove(address(settlement), 0);
        if (amountOut < minAmountOut || amountOut != order.amountOut) {
            revert InsufficientOutput();
        }
        IERC20(tokenOut).safeTransfer(recipient, amountOut);
    }
}
