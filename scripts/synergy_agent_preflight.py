#!/usr/bin/env python3
"""Read-only chain, signer and risk-limit preflight. Never sends a transaction."""
from __future__ import annotations

import argparse
from decimal import Decimal
from pathlib import Path

from dotenv import dotenv_values
from eth_account import Account
from web3 import Web3

from ai_centrobank.synergy_runtime_guard import GuardConfig, RiskLedger, RuntimeGuard


def env_decimal(data: dict[str, str], name: str) -> Decimal:
    return Decimal(str(data[name]))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env", type=Path, required=True)
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
        max_loss_pol=env_decimal(data, "MAX_LOSS_POL"),
        min_owner_pol=env_decimal(data, "MIN_OWNER_POL"),
        refill_pol=env_decimal(data, "REFILL_POL"),
        max_single_tx_gas_pol=env_decimal(data, "MAX_SINGLE_TX_GAS_POL"),
        max_single_action_notional_pol=env_decimal(data, "MAX_SINGLE_ACTION_NOTIONAL_POL"),
        private_tx_endpoint=data.get("PRIVATE_TX_ENDPOINT", ""),
        mainnet_arm_phrase=data.get("MAINNET_ARM_PHRASE", "DISABLED"),
    )
    config.validate_static()
    web3 = Web3(Web3.HTTPProvider(data["RPC_URL"], request_kwargs={"timeout": 20}))
    if not web3.is_connected():
        raise SystemExit("RPC connection failed")
    observed_chain = int(web3.eth.chain_id)
    balance_pol = Decimal(web3.eth.get_balance(account.address)) / Decimal(10**18)
    block = int(web3.eth.block_number)
    ledger = RiskLedger(block, balance_pol, balance_pol, last_block=block)
    guard = RuntimeGuard(config, ledger)
    guard.assert_chain(observed_chain)
    guard.assert_signer(account.address, data["EXPECTED_SIGNER_ADDRESS"])
    if balance_pol < config.min_owner_pol:
        raise SystemExit(
            f"owner balance {balance_pol} POL is below the required 10 POL start floor"
        )

    print("READ-ONLY PREFLIGHT PASS")
    print(f"network={config.network} chain_id={observed_chain} block={block}")
    print(f"signer={account.address} owner_pol={balance_pol}")
    print("hard limits: 150 blocks; 20 POL loss; action interval 10; refill 2 POL")
    print("no transaction was signed or broadcast")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
