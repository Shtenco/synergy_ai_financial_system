// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20AcrossRelay {
    function balanceOf(address account) external view returns (uint256);
    function approve(address spender, uint256 amount) external returns (bool);
}

interface IAcrossSpokePoolV3 {
    function depositV3(
        address depositor,
        address recipient,
        address inputToken,
        address outputToken,
        uint256 inputAmount,
        uint256 outputAmount,
        uint256 destinationChainId,
        address exclusiveRelayer,
        uint32 quoteTimestamp,
        uint32 fillDeadline,
        uint32 exclusivityDeadline,
        bytes calldata message
    ) external payable;
}

/// @notice Ownerless source-chain adapter that relays every WPOL dividend
/// accumulated by the solvency controller to one immutable Ethereum recipient.
///
/// The adapter is intentionally narrow:
/// - destination chain is permanently Ethereum mainnet (chain id 1);
/// - recipient, WPOL, output token and Across SpokePool are immutable;
/// - anyone can submit a fresh Across quote and pay gas;
/// - output amount must respect the immutable maximum relay fee;
/// - refunds return to this adapter and can be relayed again;
/// - no arbitrary calls, withdrawals, owner or upgrade hooks exist.
contract AcrossMainnetDividendRelay {
    uint256 public constant BPS = 10_000;
    uint256 public constant ETHEREUM_MAINNET_CHAIN_ID = 1;
    uint32 public constant MAX_QUOTE_AGE = 10 minutes;
    uint32 public constant MIN_FILL_WINDOW = 5 minutes;
    uint32 public constant MAX_FILL_WINDOW = 2 hours;

    IERC20AcrossRelay public immutable wpol;
    IAcrossSpokePoolV3 public immutable spokePool;
    address public immutable ethereumRecipient;
    address public immutable ethereumOutputToken;
    uint16 public immutable maxRelayFeeBps;

    uint256 public relayNonce;
    uint256 public totalRelayedWPOL;
    bytes32 public lastRelayId;
    bool private entered;

    error InvalidConfiguration();
    error NoPendingDividend();
    error RelayFeeTooHigh(uint256 outputAmount, uint256 minimumOutputAmount);
    error InvalidQuoteTimestamp();
    error InvalidFillDeadline();
    error ApprovalFailed();
    error Reentrancy();

    event DividendRelayInitiated(
        bytes32 indexed relayId,
        uint256 indexed nonce,
        address indexed caller,
        address ethereumRecipient,
        address inputToken,
        address outputToken,
        uint256 inputAmount,
        uint256 outputAmount,
        uint256 destinationChainId,
        address exclusiveRelayer,
        uint32 quoteTimestamp,
        uint32 fillDeadline,
        uint32 exclusivityDeadline
    );

    constructor(
        IERC20AcrossRelay wpol_,
        IAcrossSpokePoolV3 spokePool_,
        address ethereumRecipient_,
        address ethereumOutputToken_,
        uint16 maxRelayFeeBps_
    ) {
        if (
            address(wpol_) == address(0) || address(spokePool_) == address(0)
                || ethereumRecipient_ == address(0) || maxRelayFeeBps_ > 1_000
        ) revert InvalidConfiguration();

        wpol = wpol_;
        spokePool = spokePool_;
        ethereumRecipient = ethereumRecipient_;
        ethereumOutputToken = ethereumOutputToken_;
        maxRelayFeeBps = maxRelayFeeBps_;
    }

    function pendingDividendWPOL() public view returns (uint256) {
        return wpol.balanceOf(address(this));
    }

    /// @notice Sends the full pending WPOL balance into Across V3 for delivery
    /// to the immutable Ethereum recipient. The quote parameters must be taken
    /// from a fresh Across quote for the configured token route.
    function relayPending(
        uint256 outputAmount,
        address exclusiveRelayer,
        uint32 quoteTimestamp,
        uint32 fillDeadline,
        uint32 exclusivityDeadline
    ) external returns (bytes32 relayId) {
        if (entered) revert Reentrancy();
        entered = true;

        uint256 inputAmount = pendingDividendWPOL();
        if (inputAmount == 0) revert NoPendingDividend();

        uint256 minimumOutputAmount = inputAmount * (BPS - maxRelayFeeBps) / BPS;
        if (outputAmount < minimumOutputAmount || outputAmount > inputAmount) {
            revert RelayFeeTooHigh(outputAmount, minimumOutputAmount);
        }

        if (quoteTimestamp > block.timestamp || block.timestamp - quoteTimestamp > MAX_QUOTE_AGE) {
            revert InvalidQuoteTimestamp();
        }
        if (
            fillDeadline < block.timestamp + MIN_FILL_WINDOW
                || fillDeadline > block.timestamp + MAX_FILL_WINDOW
                || (exclusivityDeadline != 0 && exclusivityDeadline > fillDeadline)
        ) revert InvalidFillDeadline();

        if (!wpol.approve(address(spokePool), 0)) revert ApprovalFailed();
        if (!wpol.approve(address(spokePool), inputAmount)) revert ApprovalFailed();

        uint256 nonce = ++relayNonce;
        relayId = keccak256(
            abi.encode(
                block.chainid,
                address(this),
                nonce,
                ethereumRecipient,
                ethereumOutputToken,
                inputAmount,
                outputAmount,
                exclusiveRelayer,
                quoteTimestamp,
                fillDeadline,
                exclusivityDeadline
            )
        );

        spokePool.depositV3(
            address(this),
            ethereumRecipient,
            address(wpol),
            ethereumOutputToken,
            inputAmount,
            outputAmount,
            ETHEREUM_MAINNET_CHAIN_ID,
            exclusiveRelayer,
            quoteTimestamp,
            fillDeadline,
            exclusivityDeadline,
            bytes("")
        );

        totalRelayedWPOL += inputAmount;
        lastRelayId = relayId;
        entered = false;

        emit DividendRelayInitiated(
            relayId,
            nonce,
            msg.sender,
            ethereumRecipient,
            address(wpol),
            ethereumOutputToken,
            inputAmount,
            outputAmount,
            ETHEREUM_MAINNET_CHAIN_ID,
            exclusiveRelayer,
            quoteTimestamp,
            fillDeadline,
            exclusivityDeadline
        );
    }
}
