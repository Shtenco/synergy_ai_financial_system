#!/usr/bin/env python3
"""Replay V15.3 transaction rows through the strict V15.1 fork harness.

Every selected raw row starts a fresh Polygon fork at block N-1, replays the
actual transaction and executes the V15.1 backrun in the same mined fork block.
The orchestrator recomputes the stricter V15.3 gate: at least 2.685148 bps of
aggregate route profit after all attributable operational gas. Only the net
protocol share is eligible for 80% reinvestment.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any
from urllib.request import Request, urlopen

SPEC_PATH = Path(os.getenv("V153_PANEL_SPEC", "economics/v15_3_transaction_panel_spec.json"))
RAW_PATH = Path(os.getenv("V153_RAW_PANEL", "reports/v15_3_transaction_panel_raw.jsonl"))
OUTPUT_PATH = Path(os.getenv("V153_REPLAYED_PANEL", "reports/v15_3_transaction_panel_replayed.jsonl"))
SUMMARY_PATH = Path(os.getenv("V153_REPLAY_SUMMARY", "reports/v15_3_transaction_panel_replay_summary.json"))
REPORT_PATH = Path("reports/v15_1_historical_polygon_fork.json")
LOG_DIR = Path("reports/v15_3_replay_logs")
RPC_URL = os.getenv("POLYGON_RPC_URL", "").strip()
REPLAY_LIMIT = int(os.getenv("V153_REPLAY_LIMIT", "40"))
PORT = int(os.getenv("V153_ANVIL_PORT", "8545"))
TIMEOUT_SECONDS = int(os.getenv("V153_REPLAY_TIMEOUT_SECONDS", "900"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"row {line_number} is not an object")
        rows.append(value)
    return rows


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(json.dumps(row, sort_keys=True) for row in rows)
    path.write_text(text + ("\n" if rows else ""), encoding="utf-8")


def select_evenly(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (int(row["blockNumber"]), int(row["transactionIndex"])))
    if limit <= 0 or len(ordered) <= limit:
        return ordered
    if limit == 1:
        return [ordered[len(ordered) // 2]]
    indices = sorted({round(index * (len(ordered) - 1) / (limit - 1)) for index in range(limit)})
    return [ordered[index] for index in indices]


def rpc_ready(url: str) -> bool:
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}).encode()
    request = Request(url, data=body, headers={"content-type": "application/json"})
    try:
        with urlopen(request, timeout=2) as response:
            payload = json.loads(response.read().decode())
        return payload.get("result") == "0x89"
    except Exception:
        return False


def start_anvil(block_number: int, log_path: Path) -> subprocess.Popen[str]:
    command = [
        "anvil",
        "--fork-url", RPC_URL,
        "--fork-block-number", str(block_number),
        "--timeout", "180000",
        "--chain-id", "137",
        "--hardfork", "cancun",
        "--host", "127.0.0.1",
        "--port", str(PORT),
        "--silent",
    ]
    log_handle = log_path.open("w", encoding="utf-8")
    process = subprocess.Popen(
        command,
        stdout=log_handle,
        stderr=subprocess.STDOUT,
        text=True,
        start_new_session=True,
    )
    setattr(process, "_synergy_log_handle", log_handle)
    local_url = f"http://127.0.0.1:{PORT}"
    for _ in range(90):
        if process.poll() is not None:
            break
        if rpc_ready(local_url):
            return process
        time.sleep(1)
    stop_anvil(process)
    raise RuntimeError(f"anvil did not become ready for block {block_number}")


def stop_anvil(process: subprocess.Popen[str] | None) -> None:
    if process is None:
        return
    if process.poll() is None:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            process.wait(timeout=5)
    log_handle = getattr(process, "_synergy_log_handle", None)
    if log_handle:
        log_handle.close()


def raw_int(container: dict[str, Any], key: str) -> int:
    value = container.get(key, 0)
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def transform_outcome(
    row: dict[str, Any], report: dict[str, Any], spec: dict[str, Any]
) -> dict[str, Any]:
    policy = spec["policy"]
    threshold_bps = float(policy["strictNetEdgeBps"])
    reinvestment_share = float(policy["reinvestmentShare"])
    accounting = report.get("rawAccounting") or {}
    auction = report.get("auction") or {}
    victim = report.get("historicalVictim") or {}
    fixture = report.get("fixtureFunding") or {}
    invariants = report.get("invariants") or {}

    principal_raw = raw_int(accounting, "principalUsdcRaw")
    gross_profit_raw = raw_int(accounting, "grossProfitUsdcRaw")
    gas_raw = raw_int(accounting, "operationalGasUsdcRaw")
    aggregate_net_raw = raw_int(accounting, "aggregateNetAfterGasUsdcRaw")
    treasury_gross_raw = raw_int(accounting, "treasuryRevenueUsdcRaw")
    solver_gross_raw = raw_int(accounting, "solverRevenueUsdcRaw")
    solver_gas_raw = raw_int(accounting, "solverGasUsdcRaw")
    solver_net_raw = raw_int(accounting, "solverNetAfterGasUsdcRaw")
    treasury_share_bps = int(
        auction.get("treasuryShareBps")
        or round(policy["defaultTreasuryShare"] * 10_000)
    )

    aggregate_net_edge_bps = (
        aggregate_net_raw / principal_raw * 10_000 if principal_raw > 0 else 0.0
    )
    treasury_net_raw = aggregate_net_raw * treasury_share_bps // 10_000
    solver_net_allocated_raw = max(aggregate_net_raw - treasury_net_raw, 0)
    reinvested_raw = int(treasury_net_raw * reinvestment_share)
    same_block = victim.get("sameBlock") is True and victim.get("victimBeforeBackrun") is True
    fixture_excluded = fixture.get("countedAsRevenue") is False
    bond_excluded = invariants.get("solverBondCountedAsRevenue") is False
    no_synthetic = invariants.get("syntheticMintBurnInterfaceUsed") is False
    route_closed = raw_int(invariants, "engineSettlementBalanceAfter") == 0

    strict_pass = all([
        principal_raw > 0,
        aggregate_net_edge_bps >= threshold_bps,
        aggregate_net_raw > 0,
        treasury_net_raw > 0,
        solver_net_raw > 0,
        same_block,
        fixture_excluded,
        bond_excluded,
        no_synthetic,
        route_closed,
    ])

    outcome = {
        "evidenceStatusV151": report.get("evidenceStatus", "MISSING_REPORT"),
        "strictStatusV153": "STRICT_NET_EDGE_PASS" if strict_pass else "STRICT_NET_EDGE_REJECTED",
        "principalUsdc": principal_raw / 1_000_000,
        "grossRouteProfitUsdc": gross_profit_raw / 1_000_000,
        "operationalGasUsdc": gas_raw / 1_000_000,
        "flashPremiumUsdc": 0.0,
        "bridgeCostUsdc": 0.0,
        "mevLossUsdc": 0.0,
        "protocolLpDamageUsdc": 0.0,
        "liabilityIncreaseUsdc": 0.0,
        "aggregateNetProfitUsdc": aggregate_net_raw / 1_000_000,
        "aggregateNetEdgeBpsAfterAllCosts": aggregate_net_edge_bps,
        "treasuryShareBps": treasury_share_bps,
        "treasuryGrossRevenueUsdc": treasury_gross_raw / 1_000_000,
        "treasuryNetAfterSharedCostsUsdc": treasury_net_raw / 1_000_000,
        "solverGrossRevenueUsdc": solver_gross_raw / 1_000_000,
        "solverGasUsdc": solver_gas_raw / 1_000_000,
        "solverNetAfterGasUsdc": solver_net_raw / 1_000_000,
        "solverNetAllocatedFromAggregateUsdc": solver_net_allocated_raw / 1_000_000,
        "reinvestmentShare": reinvestment_share,
        "reinvestedUsdc": reinvested_raw / 1_000_000,
        "retainedButNotReinvestedUsdc": (treasury_net_raw - reinvested_raw) / 1_000_000,
        "strictNetEdgeThresholdBps": threshold_bps,
        "sameBlockVictimBeforeBackrun": same_block,
        "fixturePrincipalCountedAsRevenue": not fixture_excluded,
        "refundableBondCountedAsRevenue": not bond_excluded,
        "internalMintBurnCountedAsRevenue": not no_synthetic,
        "engineSettlementResidueRaw": raw_int(invariants, "engineSettlementBalanceAfter"),
        "countedRevenueUsdc": treasury_net_raw / 1_000_000 if strict_pass else 0.0,
    }
    merged = dict(row)
    merged["forkReplayOutcome"] = outcome
    merged["countedRevenueRaw"] = str(treasury_net_raw if strict_pass else 0)
    return merged


def replay_one(row: dict[str, Any], spec: dict[str, Any], index: int) -> dict[str, Any]:
    block_number = int(row["blockNumber"])
    tx_hash = str(row["transactionHash"])
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    anvil_log = LOG_DIR / f"{index:04d}_{block_number}_{tx_hash[2:10]}_anvil.log"
    test_log = LOG_DIR / f"{index:04d}_{block_number}_{tx_hash[2:10]}_test.log"
    REPORT_PATH.unlink(missing_ok=True)
    process: subprocess.Popen[str] | None = None
    try:
        process = start_anvil(block_number - 1, anvil_log)
        environment = os.environ.copy()
        environment.update({
            "LOCAL_FORK_URL": f"http://127.0.0.1:{PORT}",
            "SELECTED_POLYGON_RPC": RPC_URL,
            "POLYGON_RPC_URL": RPC_URL,
            "HISTORICAL_VICTIM_TX_HASH": tx_hash,
            "HISTORICAL_VICTIM_BLOCK": str(block_number),
            "HISTORICAL_TOKEN_MID": spec["market"]["intermediateToken"],
            "FORK_BLOCK_NUMBER": str(block_number - 1),
        })
        completed = subprocess.run(
            [
                "npx", "hardhat", "test",
                "test/external_revenue_v15_1_historical_polygon_fork.js",
                "--network", "polygonFork",
            ],
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
        test_log.write_text(completed.stdout, encoding="utf-8")
        if not REPORT_PATH.exists():
            raise RuntimeError(f"historical test produced no report; exit={completed.returncode}")
        report = json.loads(REPORT_PATH.read_text(encoding="utf-8"))
        transformed = transform_outcome(row, report, spec)
        transformed["replayProcess"] = {
            "exitCode": completed.returncode,
            "anvilLog": str(anvil_log),
            "testLog": str(test_log),
        }
        return transformed
    except Exception as error:
        failed = dict(row)
        failed["forkReplayOutcome"] = {
            "evidenceStatusV151": "REPLAY_ERROR",
            "strictStatusV153": "STRICT_NET_EDGE_REJECTED",
            "strictNetEdgeThresholdBps": spec["policy"]["strictNetEdgeBps"],
            "aggregateNetEdgeBpsAfterAllCosts": 0.0,
            "reinvestmentShare": spec["policy"]["reinvestmentShare"],
            "reinvestedUsdc": 0.0,
            "countedRevenueUsdc": 0.0,
            "error": str(error),
        }
        failed["countedRevenueRaw"] = "0"
        return failed
    finally:
        stop_anvil(process)


def main() -> None:
    if not RPC_URL:
        raise SystemExit("POLYGON_RPC_URL is required for strict replay")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    raw_rows = load_jsonl(RAW_PATH)
    selected = select_evenly(raw_rows, REPLAY_LIMIT)
    output: list[dict[str, Any]] = []
    for index, row in enumerate(selected, 1):
        print(
            f"V15_3_REPLAY {index}/{len(selected)} "
            f"block={row['blockNumber']} tx={row['transactionHash']}"
        )
        output.append(replay_one(row, spec, index))
        write_jsonl(OUTPUT_PATH, output)

    outcomes = [row.get("forkReplayOutcome") or {} for row in output]
    pass_rows = [row for row in outcomes if row.get("strictStatusV153") == "STRICT_NET_EDGE_PASS"]
    valid_rows = [row for row in outcomes if row.get("evidenceStatusV151") != "REPLAY_ERROR"]
    total_reinvested = sum(float(row.get("reinvestedUsdc", 0.0)) for row in pass_rows)
    summary = {
        "scenario": "synergy_v15_3_strict_transaction_panel_replay",
        "rawRowsAvailable": len(raw_rows),
        "rowsSelected": len(selected),
        "validReplayRows": len(valid_rows),
        "strictPassRows": len(pass_rows),
        "strictPassRate": len(pass_rows) / len(valid_rows) if valid_rows else 0.0,
        "strictNetEdgeThresholdBps": spec["policy"]["strictNetEdgeBps"],
        "reinvestmentShare": spec["policy"]["reinvestmentShare"],
        "totalReinvestedUsdc": total_reinvested,
        "minimumRequiredReplayRows": spec["estimation"]["minimumReplayRows"],
        "enoughRowsForEstimation": len(valid_rows) >= spec["estimation"]["minimumReplayRows"],
        "evidenceStatus": (
            "REPLAY_PANEL_READY_FOR_ESTIMATION"
            if len(valid_rows) >= spec["estimation"]["minimumReplayRows"]
            else "INSUFFICIENT_REPLAY_ROWS"
        ),
        "interpretation": (
            "Only rows whose realized aggregate net edge after operational gas clears "
            "2.685148 bps can contribute counted protocol revenue and 80% reinvestment."
        ),
    }
    SUMMARY_PATH.parent.mkdir(parents=True, exist_ok=True)
    SUMMARY_PATH.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    if not valid_rows:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
