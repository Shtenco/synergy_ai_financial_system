#!/usr/bin/env python3
"""Create and validate local-only SYNERGY runtime env files without printing keys."""
from __future__ import annotations

import argparse
import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Dict

from dotenv import dotenv_values
from eth_account import Account

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / "runtime" / "synergy_agent"
LOCAL = RUNTIME / "local"
PRIVATE_KEY_RE = re.compile(r"^(0x)?[0-9a-fA-F]{64}$")
ARM_PHRASE = "I_ACCEPT_MAX_20_POL_LOSS_FOR_150_BLOCKS"


def template_path(network: str) -> Path:
    return RUNTIME / ("testnet.env.example" if network == "amoy" else "mainnet.env.example")


def env_path(network: str) -> Path:
    return LOCAL / ("amoy.env" if network == "amoy" else "polygon.env")


def ensure_not_tracked(path: Path) -> None:
    try:
        relative = path.resolve().relative_to(ROOT.resolve())
    except ValueError as exc:
        raise SystemExit("env path must be inside this repository clone") from exc
    check = subprocess.run(
        ["git", "ls-files", "--error-unmatch", str(relative)],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    if check.returncode == 0:
        raise SystemExit(f"REFUSING: secret file is tracked by git: {relative}")


def init(network: str) -> None:
    source = template_path(network)
    target = env_path(network)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        raise SystemExit(f"already exists: {target}")
    target.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    if os.name == "posix":
        target.chmod(stat.S_IRUSR | stat.S_IWUSR)
    ensure_not_tracked(target)
    print(f"created local-only vault file: {target}")
    print("permissions: 0600; file is ignored by git")


def require(data: Dict[str, str], key: str) -> str:
    value = (data.get(key) or "").strip()
    if not value:
        raise SystemExit(f"missing required setting: {key}")
    return value


def parse_decimal(data: Dict[str, str], key: str) -> float:
    try:
        return float(require(data, key))
    except ValueError as exc:
        raise SystemExit(f"invalid numeric setting: {key}") from exc


def check(path: Path) -> None:
    path = path.resolve()
    ensure_not_tracked(path)
    if not path.is_file():
        raise SystemExit(f"env file not found: {path}")
    if os.name == "posix":
        mode = stat.S_IMODE(path.stat().st_mode)
        if mode & (stat.S_IRWXG | stat.S_IRWXO):
            raise SystemExit(f"unsafe permissions {oct(mode)}; run chmod 600 {path}")

    raw = {k: str(v or "") for k, v in dotenv_values(path).items()}
    network = require(raw, "NETWORK")
    chain_id = int(require(raw, "CHAIN_ID"))
    if network == "amoy" and chain_id != 80002:
        raise SystemExit("Amoy must use CHAIN_ID=80002")
    if network == "polygon" and chain_id != 137:
        raise SystemExit("Polygon mainnet must use CHAIN_ID=137")
    if network not in {"amoy", "polygon"}:
        raise SystemExit("NETWORK must be amoy or polygon")

    key = require(raw, "PRIVATE_KEY")
    if not PRIVATE_KEY_RE.fullmatch(key):
        raise SystemExit("PRIVATE_KEY must be exactly 32 bytes of hex")
    signer = Account.from_key(key).address
    expected = require(raw, "EXPECTED_SIGNER_ADDRESS")
    if signer.lower() != expected.lower():
        raise SystemExit("PRIVATE_KEY does not match EXPECTED_SIGNER_ADDRESS")

    if int(parse_decimal(raw, "BLOCK_LIMIT")) != 150:
        raise SystemExit("BLOCK_LIMIT must equal 150")
    if int(parse_decimal(raw, "ACTION_INTERVAL")) != 10:
        raise SystemExit("ACTION_INTERVAL must equal 10")
    if parse_decimal(raw, "MAX_LOSS_POL") != 20:
        raise SystemExit("MAX_LOSS_POL must equal 20")
    if parse_decimal(raw, "MIN_OWNER_POL") < 10:
        raise SystemExit("MIN_OWNER_POL cannot be below 10")
    if parse_decimal(raw, "REFILL_POL") != 2:
        raise SystemExit("REFILL_POL must equal 2")
    if parse_decimal(raw, "MAX_SINGLE_TX_GAS_POL") > 0.25:
        raise SystemExit("MAX_SINGLE_TX_GAS_POL cannot exceed 0.25")

    execution = require(raw, "EXECUTION_MODE")
    if execution not in {"dry-run", "execute"}:
        raise SystemExit("EXECUTION_MODE must be dry-run or execute")
    if network == "polygon" and execution == "execute":
        if require(raw, "TX_SUBMISSION_MODE") != "private":
            raise SystemExit("mainnet execute requires TX_SUBMISSION_MODE=private")
        if require(raw, "MAINNET_ARM_PHRASE") != ARM_PHRASE:
            raise SystemExit("mainnet arm phrase is incorrect")
        if not require(raw, "PRIVATE_TX_ENDPOINT").startswith("https://"):
            raise SystemExit("mainnet private endpoint must be HTTPS")

    print("vault check: PASS")
    print(f"network: {network}; chain_id: {chain_id}; signer: {signer}")
    print(f"mode: {execution}; blocks: 150; max loss: 20 POL; refill: 2 POL")
    print("private key: [REDACTED]")


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    p_init = sub.add_parser("init")
    p_init.add_argument("--network", choices=["amoy", "polygon"], required=True)
    p_check = sub.add_parser("check")
    p_check.add_argument("--env", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "init":
        init(args.network)
    else:
        check(args.env)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
