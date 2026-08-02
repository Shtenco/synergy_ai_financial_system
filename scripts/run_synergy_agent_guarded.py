#!/usr/bin/env python3
"""Guarded chain runner scaffold.

This entry point currently supports read-only shadow operation. A transaction
adapter must be implemented and independently reviewed before `execute` can send
anything. The deliberate fail-closed placeholder prevents accidental mainnet
broadcast from an incomplete integration.
"""
from __future__ import annotations

import argparse
import json
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict

from dotenv import dotenv_values
from eth_account import Account
from web3 import Web3

from ai_centrobank.synergy_runtime_guard import (
    GuardConfig,
    GuardedLoop,
    RiskLedger,
    RuntimeGuard,
    SafetyViolation,
)


class ShadowPolicy:
    def learn(self, block: int) -> None:
        return None

    def propose(self, block: int) -> Dict[str, Any]:
        return {"kind": "HOLD", "block": block, "notional_pol": "0"}


class MissingReviewedExecutionAdapter:
    def execute(self, action: Dict[str, Any]) -> Dict[str, Decimal]:
        raise SafetyViolation(
            "live execution adapter is intentionally absent; complete testnet contract integration first"
        )

    def refill(self, amount: Decimal) -> Decimal:
        raise SafetyViolation(
            "gas-refill swap adapter is intentionally absent; complete and audit it on Amoy first"
        )


def d(data: dict[str, str], key: str) -> Decimal:
    return Decimal(str(data[key]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, required=True)
    parser.add_argument("--poll-seconds", type=float, default=2.0)
    args = parser.parse_args()
    data = {k: str(v or "") for k, v in dotenv_values(args.env).items()}
    account = Account.from_key(data["PRIVATE_KEY"])
    config = GuardConfig(
        network=data["NETWORK"],
        chain_id=int(data["CHAIN_ID"]),
        execution_mode=data["EXECUTION_MODE"],
        tx_submission_mode=data["TX_SUBMISSION_MODE"],
        block_limit=int(data["BLOCK_LIMIT"]),
        action_interval=int(data["ACTION_INTERVAL"]),
        max_loss_pol=d(data, "MAX_LOSS_POL"),
        min_owner_pol=d(data, "MIN_OWNER_POL"),
        refill_pol=d(data, "REFILL_POL"),
        max_single_tx_gas_pol=d(data, "MAX_SINGLE_TX_GAS_POL"),
        max_single_action_notional_pol=d(data, "MAX_SINGLE_ACTION_NOTIONAL_POL"),
        private_tx_endpoint=data.get("PRIVATE_TX_ENDPOINT", ""),
        mainnet_arm_phrase=data.get("MAINNET_ARM_PHRASE", "DISABLED"),
    )
    web3 = Web3(Web3.HTTPProvider(data["RPC_URL"], request_kwargs={"timeout": 20}))
    if not web3.is_connected():
        raise SystemExit("RPC connection failed")
    block = int(web3.eth.block_number)
    owner_pol = Decimal(web3.eth.get_balance(account.address)) / Decimal(10**18)
    ledger = RiskLedger(block, owner_pol, owner_pol, last_block=block)
    guard = RuntimeGuard(config, ledger)
    guard.assert_chain(int(web3.eth.chain_id))
    guard.assert_signer(account.address, data["EXPECTED_SIGNER_ADDRESS"])
    policy = ShadowPolicy()
    adapter = MissingReviewedExecutionAdapter()

    def get_owner_pol() -> Decimal:
        return Decimal(web3.eth.get_balance(account.address)) / Decimal(10**18)

    # Until token and LP valuation adapters are reviewed, NAV is conservatively
    # the native POL balance only. Execute mode is intentionally blocked.
    loop = GuardedLoop(
        guard=guard,
        get_block=lambda: int(web3.eth.block_number),
        get_owner_pol=get_owner_pol,
        get_nav_pol=get_owner_pol,
        learn_one_block=policy.learn,
        propose_action=policy.propose,
        execute_action=adapter.execute,
        refill_gas=adapter.refill,
        state_path=Path("runtime/synergy_agent/local/run_state.json"),
        poll_seconds=args.poll_seconds,
    )
    result = loop.run()
    print(json.dumps(result.to_json(), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
