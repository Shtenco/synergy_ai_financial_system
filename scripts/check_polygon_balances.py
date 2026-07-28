#!/usr/bin/env python3
"""Read Polygon native and ERC-20 balances without handling private keys."""

from __future__ import annotations

import argparse
import json
import os
import ssl
import urllib.error
import urllib.request


DEFAULT_OWNER = "0x6946999DBCE63b140B1bB9D475F7c357130909E5"
TOKENS = {
    "SYNA": "0xaeB98101e29E791A2482C2A5B55F444F6C9E44a4",
    "SYNR": "0xe3e6944BcE4A92648B37f6F578600b0D0288E935",
}


class RPCConnectionError(RuntimeError):
    """An actionable error raised when the RPC transport cannot be established."""


def explain_connection_error(error: BaseException) -> str:
    detail = str(error)
    if "Tunnel connection failed: 403" in detail or "CONNECT tunnel failed" in detail:
        return (
            "the configured proxy rejected the HTTPS CONNECT tunnel (HTTP 403) "
            "before TLS started; disabling certificate verification cannot fix this. "
            "Ask the proxy administrator to allowlist the RPC host or use an "
            "approved Polygon RPC endpoint"
        )
    return f"could not connect to Polygon RPC: {detail}"


def rpc(
    url: str,
    method: str,
    params: list[object],
    ssl_context: ssl.SSLContext | None = None,
) -> str:
    payload = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    ).encode()
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=20, context=ssl_context) as response:
            result = json.load(response)
    except (urllib.error.URLError, TimeoutError) as error:
        raise RPCConnectionError(explain_connection_error(error)) from error
    if "error" in result:
        raise RuntimeError(f"RPC error: {result['error']}")
    return result["result"]


def uint_call(
    url: str, contract: str, data: str, ssl_context: ssl.SSLContext | None = None
) -> int:
    return int(
        rpc(
            url,
            "eth_call",
            [{"to": contract, "data": data}, "latest"],
            ssl_context,
        ),
        16,
    )


def balance_of_data(address: str) -> str:
    # balanceOf(address) selector followed by the 32-byte ABI-encoded address.
    raw_address = address.removeprefix("0x")
    if len(raw_address) != 40 or any(c not in "0123456789abcdefABCDEF" for c in raw_address):
        raise ValueError("address must contain exactly 20 hexadecimal bytes")
    return "0x70a08231" + raw_address.lower().zfill(64)


def make_ssl_context(ca_certificate: str | None) -> ssl.SSLContext:
    """Build a verified TLS context, optionally trusting a private gateway CA."""
    if ca_certificate:
        return ssl.create_default_context(cafile=ca_certificate)
    return ssl.create_default_context()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rpc-url", default=os.getenv("POLYGON_RPC_URL"))
    parser.add_argument("--address", default=DEFAULT_OWNER)
    parser.add_argument(
        "--ca-certificate",
        default=os.getenv("POLYGON_CA_CERT"),
        help="PEM CA certificate for an HTTPS inspection gateway",
    )
    args = parser.parse_args()
    if not args.rpc_url:
        parser.error("set POLYGON_RPC_URL or pass --rpc-url")

    ssl_context = make_ssl_context(args.ca_certificate)
    chain_id = int(rpc(args.rpc_url, "eth_chainId", [], ssl_context), 16)
    if chain_id != 137:
        raise SystemExit(f"refusing non-Polygon endpoint (chain id {chain_id})")

    native = int(
        rpc(args.rpc_url, "eth_getBalance", [args.address, "latest"], ssl_context),
        16,
    )
    report: dict[str, object] = {
        "chain_id": chain_id,
        "address": args.address,
        "POL": native / 10**18,
        "tokens": {},
    }
    for symbol, contract in TOKENS.items():
        decimals = uint_call(args.rpc_url, contract, "0x313ce567", ssl_context)
        raw_balance = uint_call(
            args.rpc_url, contract, balance_of_data(args.address), ssl_context
        )
        report["tokens"][symbol] = {  # type: ignore[index]
            "contract": contract,
            "balance": raw_balance / 10**decimals,
            "decimals": decimals,
        }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    try:
        main()
    except RPCConnectionError as error:
        raise SystemExit(f"connection error: {error}") from error
