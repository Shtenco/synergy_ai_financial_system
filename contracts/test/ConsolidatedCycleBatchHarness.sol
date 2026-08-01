// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface ILedgerBatch {
    function recordInternalTransfer(
        bytes32 sourceId,
        address asset,
        uint256 amount,
        address from,
        address to
    ) external returns (uint256);
}

interface IMMExternalBatch {
    function sellToExternalBuyer(
        address buyer,
        uint256 synAmount,
        uint256 payment,
        uint256 externalCosts,
        address externalCostRecipient,
        bytes32 capitalSourceId,
        bytes32 revenueSourceId,
        bytes32 inventorySourceId,
        bytes32 expenseSourceId
    ) external;
}

interface IQTExternalBatch {
    function externalTenderAndBurn(
        address holder,
        uint256 synAmount,
        uint256 externalExecutionCost,
        address externalCostRecipient,
        bytes32 redemptionSourceId,
        bytes32 expenseSourceId
    ) external;
}

/// @notice Test-only batching adapter. It changes transaction transport, not
/// economics: every loop still creates separate ledger source IDs and executes
/// the same MM issuance and QT redemption calls.
contract ConsolidatedCycleBatchHarness {
    ILedgerBatch public immutable ledger;
    IMMExternalBatch public immutable marketMaker;
    IQTExternalBatch public immutable qt;

    constructor(ILedgerBatch ledger_, IMMExternalBatch marketMaker_, IQTExternalBatch qt_) {
        ledger = ledger_;
        marketMaker = marketMaker_;
        qt = qt_;
    }

    function batchInternalTransfers(
        uint256 start,
        uint256 count,
        address asset,
        uint256 amount,
        address accountA,
        address accountB
    ) external {
        for (uint256 offset; offset < count; ++offset) {
            uint256 index = start + offset;
            address from = index % 2 == 0 ? accountA : accountB;
            address to = index % 2 == 0 ? accountB : accountA;
            ledger.recordInternalTransfer(
                keccak256(abi.encodePacked("internal-cycle", index)), asset, amount, from, to
            );
        }
    }

    function batchExternalIssueRedeem(
        uint256 start,
        uint256 count,
        address buyer,
        uint256 synAmount,
        uint256 payment,
        uint256 externalCost,
        address externalCostRecipient
    ) external {
        for (uint256 offset; offset < count; ++offset) {
            uint256 index = start + offset;
            marketMaker.sellToExternalBuyer(
                buyer,
                synAmount,
                payment,
                externalCost,
                externalCostRecipient,
                keccak256(abi.encodePacked("capital", index)),
                keccak256(abi.encodePacked("spread", index)),
                keccak256(abi.encodePacked("inventory-out", index)),
                keccak256(abi.encodePacked("execution-cost", index))
            );
            qt.externalTenderAndBurn(
                buyer,
                synAmount,
                0,
                address(0),
                keccak256(abi.encodePacked("qt-redemption", index)),
                keccak256(abi.encodePacked("unused-qt-cost", index))
            );
        }
    }
}
