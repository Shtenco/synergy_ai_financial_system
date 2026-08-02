#!/usr/bin/env python3
import json
import os
import time
import urllib.request
from pathlib import Path

RPC_URLS = [
    os.environ.get("POLYGON_RPC_URL", "https://polygon.drpc.org"),
    "https://polygon-bor-rpc.publicnode.com",
]
PACKAGE_DIR = Path("runtime/synergy_agent/signed/syna_mainnet")
REPORT_PATH = Path("reports/syna_polygon_mainnet_deployment.json")
USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
EVENT_TOPIC = "0xd50d8e944d94ea1cadaea69b894ac4f7fd05b4c70fccf7b876f0107ae82abf6a"


def rpc(method, params):
    last = None
    for url in RPC_URLS:
        try:
            body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
            req = urllib.request.Request(url, data=body, headers={"content-type": "application/json"})
            with urllib.request.urlopen(req, timeout=45) as response:
                data = json.load(response)
            if "error" in data:
                raise RuntimeError(data["error"])
            return data["result"]
        except Exception as exc:
            last = exc
    raise RuntimeError(f"RPC failure for {method}: {last}")


def call(to, data):
    return rpc("eth_call", [{"to": to, "data": data}, "latest"])


def padded_address(address):
    return address.lower().replace("0x", "").rjust(64, "0")


def balance_of(token, account):
    return int(call(token, "0x70a08231" + padded_address(account)), 16)


def allowance(token, owner, spender):
    return int(call(token, "0xdd62ed3e" + padded_address(owner) + padded_address(spender)), 16)


def wait_receipt(tx_hash, attempts=240):
    for _ in range(attempts):
        receipt = rpc("eth_getTransactionReceipt", [tx_hash])
        if receipt:
            if int(receipt["status"], 16) != 1:
                raise RuntimeError(f"Transaction reverted: {tx_hash}")
            return receipt
        time.sleep(2)
    raise TimeoutError(f"Receipt timeout: {tx_hash}")


def existing_receipt(tx_hash):
    receipt = rpc("eth_getTransactionReceipt", [tx_hash])
    if receipt and int(receipt["status"], 16) != 1:
        raise RuntimeError(f"Previously broadcast transaction reverted: {tx_hash}")
    return receipt


def send_or_resume(raw, expected_hash):
    receipt = existing_receipt(expected_hash)
    if receipt:
        return receipt
    try:
        tx_hash = rpc("eth_sendRawTransaction", [raw])
        if tx_hash.lower() != expected_hash.lower():
            raise RuntimeError(f"Hash mismatch: {tx_hash} != {expected_hash}")
    except Exception as exc:
        text = str(exc).lower()
        if not any(x in text for x in ("already known", "known transaction", "nonce too low")):
            raise
        tx_hash = expected_hash
    return wait_receipt(tx_hash)


def decode_address_word(value):
    return "0x" + value[-40:]


def decode_string(value):
    raw = bytes.fromhex(value[2:])
    if len(raw) < 64:
        return ""
    offset = int.from_bytes(raw[:32], "big")
    length = int.from_bytes(raw[offset:offset + 32], "big")
    return raw[offset + 32:offset + 32 + length].decode("utf-8")


def load_signed_package():
    if not (PACKAGE_DIR / "READY").exists():
        raise RuntimeError("Signed package is not armed: READY is missing")
    signed = json.loads((PACKAGE_DIR / "metadata.json").read_text())
    signed["rawSwap"] = (PACKAGE_DIR / "raw_swap.txt").read_text().strip()
    signed["rawApprove"] = (PACKAGE_DIR / "raw_approve.txt").read_text().strip()
    deploy_parts = sorted(PACKAGE_DIR.glob("raw_deploy_*.txt"))
    if not deploy_parts:
        raise RuntimeError("Deploy transaction chunks are missing")
    signed["rawDeploy"] = "".join(p.read_text().strip() for p in deploy_parts)
    for key in ("rawSwap", "rawApprove", "rawDeploy"):
        value = signed[key]
        if not value.startswith("0x") or len(value) < 10:
            raise RuntimeError(f"Invalid signed transaction field: {key}")
    return signed


def main():
    signed = load_signed_package()
    deployer = signed["deployer"]
    bootstrap = signed["bootstrapAddress"]
    if int(rpc("eth_chainId", []), 16) != 137:
        raise RuntimeError("Wrong chain")

    nonce_pending = int(rpc("eth_getTransactionCount", [deployer, "pending"]), 16)
    first_nonce = int(signed["nonceSwap"])
    if nonce_pending < first_nonce or nonce_pending > int(signed["nonceDeploy"]) + 1:
        raise RuntimeError(f"Unexpected pending nonce: {nonce_pending}")

    swap_receipt = existing_receipt(signed["swapTxHash"])
    if not swap_receipt:
        if nonce_pending != first_nonce:
            raise RuntimeError("Swap receipt missing but nonce already advanced")
        swap_receipt = send_or_resume(signed["rawSwap"], signed["swapTxHash"])
    funded_usdt = balance_of(USDT, deployer)
    if funded_usdt < 2_000_000:
        raise RuntimeError(f"POL swap funded only {funded_usdt} raw USDT")

    approve_receipt = existing_receipt(signed["approveTxHash"])
    if not approve_receipt:
        approve_receipt = send_or_resume(signed["rawApprove"], signed["approveTxHash"])
    approved = allowance(USDT, deployer, bootstrap)
    if approved < 2_000_000:
        raise RuntimeError(f"Allowance is only {approved}")

    deploy_receipt = existing_receipt(signed["deployTxHash"])
    if not deploy_receipt:
        deploy_receipt = send_or_resume(signed["rawDeploy"], signed["deployTxHash"])
    if rpc("eth_getCode", [bootstrap, "latest"]) == "0x":
        raise RuntimeError("Bootstrap has no code after successful receipt")

    event_log = None
    for log in deploy_receipt.get("logs", []):
        topics = log.get("topics", [])
        if log.get("address", "").lower() == bootstrap.lower() and topics and topics[0].lower() == EVENT_TOPIC:
            event_log = log
            break
    if not event_log or len(event_log["topics"]) < 4:
        raise RuntimeError("SynergyBootstrapped event not found")
    token = decode_address_word(event_log["topics"][1])
    controller = decode_address_word(event_log["topics"][2])
    pair = decode_address_word(event_log["topics"][3])
    for label, address in (("token", token), ("controller", controller), ("pair", pair)):
        if rpc("eth_getCode", [address, "latest"]) == "0x":
            raise RuntimeError(f"{label} has no code: {address}")

    name = decode_string(call(token, "0x06fdde03"))
    symbol = decode_string(call(token, "0x95d89b41"))
    if name != "Synergy Coin" or symbol != "SYNA":
        raise RuntimeError(f"Token identity mismatch: {name}/{symbol}")
    reserve_data = call(pair, "0x0902f1ac")
    reserve_bytes = bytes.fromhex(reserve_data[2:])
    reserve0 = int.from_bytes(reserve_bytes[0:32], "big")
    reserve1 = int.from_bytes(reserve_bytes[32:64], "big")
    if reserve0 == 0 or reserve1 == 0:
        raise RuntimeError("QuickSwap pair has zero reserve")

    report = {
        "chainId": 137,
        "deployer": deployer,
        "swapTxHash": signed["swapTxHash"],
        "approveTxHash": signed["approveTxHash"],
        "deployTxHash": signed["deployTxHash"],
        "swapBlock": int(swap_receipt["blockNumber"], 16),
        "approveBlock": int(approve_receipt["blockNumber"], 16),
        "deployBlock": int(deploy_receipt["blockNumber"], 16),
        "bootstrap": bootstrap,
        "token": token,
        "controller": controller,
        "pair": pair,
        "tokenName": name,
        "tokenSymbol": symbol,
        "fundedUsdtRaw": funded_usdt,
        "pairReserve0": str(reserve0),
        "pairReserve1": str(reserve1),
        "status": "DEPLOYED_AND_VERIFIED",
        "privateKeyLoaded": False,
    }
    REPORT_PATH.parent.mkdir(exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
