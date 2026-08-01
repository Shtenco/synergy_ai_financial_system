// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import {IERC20} from "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import {SafeERC20} from "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";
import {EIP712} from "@openzeppelin/contracts/utils/cryptography/EIP712.sol";
import {ECDSA} from "@openzeppelin/contracts/utils/cryptography/ECDSA.sol";
import {ReentrancyGuard} from "@openzeppelin/contracts/utils/ReentrancyGuard.sol";

/// @notice Non-custodial maker-signed RFQ settlement used by the V15 fork proof.
/// Orders are private until the winning solver reveals and fills them.
contract PrivateRFQSettlementV15 is EIP712, ReentrancyGuard {
    using SafeERC20 for IERC20;

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

    bytes32 public constant ORDER_TYPEHASH = keccak256(
        "Order(address maker,address taker,address tokenIn,address tokenOut,uint256 amountIn,uint256 amountOut,uint256 expiry,uint256 nonce,bytes32 salt)"
    );

    mapping(address maker => mapping(uint256 nonce => bool used)) public nonceUsed;

    error InvalidOrder();
    error InvalidSignature();
    error Expired();
    error Replay();

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

    constructor() EIP712("SINERGY Private RFQ V15", "1") {}

    function hashOrder(Order calldata order) public view returns (bytes32) {
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
        nonReentrant
        returns (uint256 amountOut)
    {
        if (
            order.maker == address(0)
                || order.tokenIn == address(0)
                || order.tokenOut == address(0)
                || order.tokenIn == order.tokenOut
                || order.amountIn == 0
                || order.amountOut == 0
                || (order.taker != address(0) && order.taker != msg.sender)
        ) revert InvalidOrder();
        if (block.timestamp > order.expiry) revert Expired();
        if (nonceUsed[order.maker][order.nonce]) revert Replay();

        bytes32 digest = hashOrder(order);
        if (ECDSA.recover(digest, signature) != order.maker) revert InvalidSignature();

        nonceUsed[order.maker][order.nonce] = true;
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
