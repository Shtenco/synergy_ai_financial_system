#!/usr/bin/env python3
import json
import os
import urllib.request
from pathlib import Path

RPC = os.environ.get("POLYGON_RPC_URL", "https://polygon.drpc.org")
DEPLOYER = "0x6946999DBCE63b140B1bB9D475F7c357130909E5"
ROUTER = "0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff"
FACTORY = "0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32"
USDT = "0xc2132D05D31c914a87C6611C10748AEb04B58e8F"
WPOL = "0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"


def rpc(method, params):
    payload = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    req = urllib.request.Request(RPC, data=payload, headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=45) as response:
        data = json.load(response)
    if "error" in data:
        raise RuntimeError(data["error"])
    return data["result"]


def call(to, data):
    return rpc("eth_call", [{"to": to, "data": data}, "latest"])


def address_result(value):
    return "0x" + value[-40:]


def code_bytes(address):
    return max(0, (len(rpc("eth_getCode", [address, "latest"])) - 2) // 2)


latest_block = rpc("eth_getBlockByNumber", ["latest", False])
nonce_latest = int(rpc("eth_getTransactionCount", [DEPLOYER, "latest"]), 16)
nonce_pending = int(rpc("eth_getTransactionCount", [DEPLOYER, "pending"]), 16)
pol_balance = int(rpc("eth_getBalance", [DEPLOYER, "latest"]), 16)
gas_price = int(rpc("eth_gasPrice", []), 16)
usdt_balance = int(call(USDT, "0x70a082310000000000000000000000006946999dbce63b140b1bb9d475f7c357130909e5"), 16)
router_factory = address_result(call(ROUTER, "0xc45a0155"))
router_wpol = address_result(call(ROUTER, "0xad5c4648"))

result = {
    "chainId": int(rpc("eth_chainId", []), 16),
    "blockNumber": int(latest_block["number"], 16),
    "blockTimestamp": int(latest_block["timestamp"], 16),
    "blockGasLimit": int(latest_block["gasLimit"], 16),
    "baseFeePerGasWei": int(latest_block.get("baseFeePerGas", "0x0"), 16),
    "gasPriceWei": gas_price,
    "deployer": DEPLOYER,
    "nonceLatest": nonce_latest,
    "noncePending": nonce_pending,
    "polBalanceWei": pol_balance,
    "polBalance": pol_balance / 10**18,
    "usdt": USDT,
    "usdtBalanceRaw": usdt_balance,
    "usdtBalance": usdt_balance / 10**6,
    "router": ROUTER,
    "factory": FACTORY,
    "wpol": WPOL,
    "routerFactory": router_factory,
    "routerWpol": router_wpol,
    "routerCodeBytes": code_bytes(ROUTER),
    "factoryCodeBytes": code_bytes(FACTORY),
    "usdtCodeBytes": code_bytes(USDT),
    "wpolCodeBytes": code_bytes(WPOL),
}
result["ready"] = (
    result["chainId"] == 137
    and nonce_latest == nonce_pending
    and usdt_balance >= 2_000_000
    and router_factory.lower() == FACTORY.lower()
    and router_wpol.lower() == WPOL.lower()
    and min(result["routerCodeBytes"], result["factoryCodeBytes"], result["usdtCodeBytes"], result["wpolCodeBytes"]) > 0
)
Path("reports").mkdir(exist_ok=True)
Path("reports/synergy_polygon_mainnet_preflight.json").write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
