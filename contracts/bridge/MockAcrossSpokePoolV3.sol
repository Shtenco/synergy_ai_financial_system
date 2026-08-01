// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20AcrossMock {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
}

/// @notice Deterministic Across V3 test double used only in fork integration tests.
/// It pulls the source token from the relay, records the exact bridge message,
/// deducts the quoted bridge fee, and credits the destination recipient with the
/// quoted output amount to simulate Ethereum settlement.
contract MockAcrossSpokePoolV3 {
    struct DepositRecord {
        address depositor;
        address recipient;
        address inputToken;
        address outputToken;
        uint256 inputAmount;
        uint256 outputAmount;
        uint256 destinationChainId;
        address exclusiveRelayer;
        uint32 quoteTimestamp;
        uint32 fillDeadline;
        uint32 exclusivityDeadline;
        bytes32 messageHash;
    }

    address public immutable expectedRecipient;
    uint256 public deposits;
    uint256 public totalInput;
    uint256 public totalOutput;
    DepositRecord public lastDeposit;

    error InvalidRecipient();
    error InvalidDestination();
    error InvalidTokenRoute();
    error TransferFailed();

    event MockDestinationSettled(
        uint256 indexed depositNumber,
        address indexed recipient,
        uint256 outputAmount,
        uint256 destinationChainId
    );

    constructor(address expectedRecipient_) {
        if (expectedRecipient_ == address(0)) revert InvalidRecipient();
        expectedRecipient = expectedRecipient_;
    }

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
    ) external payable {
        if (recipient != expectedRecipient) revert InvalidRecipient();
        if (destinationChainId != 1) revert InvalidDestination();
        if (inputToken == address(0) || outputToken == address(0) || inputToken != outputToken) {
            revert InvalidTokenRoute();
        }
        if (!IERC20AcrossMock(inputToken).transferFrom(msg.sender, address(this), inputAmount)) {
            revert TransferFailed();
        }
        if (!IERC20AcrossMock(inputToken).transfer(recipient, outputAmount)) revert TransferFailed();

        deposits += 1;
        totalInput += inputAmount;
        totalOutput += outputAmount;
        lastDeposit = DepositRecord({
            depositor: depositor,
            recipient: recipient,
            inputToken: inputToken,
            outputToken: outputToken,
            inputAmount: inputAmount,
            outputAmount: outputAmount,
            destinationChainId: destinationChainId,
            exclusiveRelayer: exclusiveRelayer,
            quoteTimestamp: quoteTimestamp,
            fillDeadline: fillDeadline,
            exclusivityDeadline: exclusivityDeadline,
            messageHash: keccak256(message)
        });

        emit MockDestinationSettled(deposits, recipient, outputAmount, destinationChainId);
    }
}
