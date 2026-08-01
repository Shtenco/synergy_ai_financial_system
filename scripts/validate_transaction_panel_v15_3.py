#!/usr/bin/env python3
"""Fail-closed validator for V15.3 transaction panel, coefficients and policy."""
from __future__ import annotations

import json
import math
import os
from pathlib import Path
from typing import Any

SPEC_PATH = Path(os.getenv("V153_PANEL_SPEC", "economics/v15_3_transaction_panel_spec.json"))
RAW_PATH = Path(os.getenv("V153_RAW_PANEL", "reports/v15_3_transaction_panel_raw.jsonl"))
REPLAY_PATH = Path(os.getenv("V153_REPLAYED_PANEL", "reports/v15_3_transaction_panel_replayed.jsonl"))
REPLAY_SUMMARY_PATH = Path(os.getenv("V153_REPLAY_SUMMARY", "reports/v15_3_transaction_panel_replay_summary.json"))
MODEL_PATH = Path(os.getenv("V153_COEFFICIENT_REPORT", "reports/v15_3_transaction_coefficients.json"))
PREDICTIONS_PATH = Path(os.getenv("V153_HOLDOUT_PREDICTIONS", "reports/v15_3_holdout_predictions.jsonl"))
VERDICT_PATH = Path(os.getenv("V153_VERDICT", "reports/v15_3_strict_empirical_verdict.json"))


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not an object")
    return value


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path}:{line_number} is not an object")
        rows.append(value)
    return rows


def number(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def close(a: float, b: float, tolerance: float = 1e-8) -> bool:
    return abs(a - b) <= tolerance * max(1.0, abs(a), abs(b))


def main() -> None:
    spec = load_json(SPEC_PATH)
    raw_rows = load_jsonl(RAW_PATH)
    replay_rows = load_jsonl(REPLAY_PATH)
    replay_summary = load_json(REPLAY_SUMMARY_PATH)
    model = load_json(MODEL_PATH)
    predictions = load_jsonl(PREDICTIONS_PATH)
    checks: dict[str, bool] = {}

    policy = spec.get("policy", {})
    estimation = spec.get("estimation", {})
    threshold = number(policy.get("strictNetEdgeBps"), -1)
    reinvestment_share = number(policy.get("reinvestmentShare"), -1)
    checks["strict_threshold_exact"] = close(threshold, 2.685148, 1e-10)
    checks["reinvestment_share_exact"] = close(reinvestment_share, 0.8, 1e-12)
    checks["raw_panel_present"] = bool(raw_rows)
    checks["raw_rows_never_count_revenue"] = all(
        str(row.get("countedRevenueRaw", "0")) == "0"
        and row.get("forkReplayOutcome") is None
        for row in raw_rows
    )
    checks["raw_rows_are_actual_transactions"] = all(
        row.get("evidenceClass") == "ACTUAL_POLYGON_TRANSACTION_BLOCK_BOUNDARY_FEATURES"
        and bool(row.get("transactionHash"))
        and int(row.get("blockNumber", 0)) > 0
        for row in raw_rows
    )

    replay_valid = 0
    replay_pass = 0
    replay_arithmetic_ok = True
    replay_policy_ok = True
    for row in replay_rows:
        outcome = row.get("forkReplayOutcome") or {}
        if outcome.get("evidenceStatusV151") == "REPLAY_ERROR":
            if number(outcome.get("countedRevenueUsdc")) != 0:
                replay_policy_ok = False
            continue
        replay_valid += 1
        principal = number(outcome.get("principalUsdc"))
        gross = number(outcome.get("grossRouteProfitUsdc"))
        costs = sum(number(outcome.get(key)) for key in (
            "operationalGasUsdc",
            "flashPremiumUsdc",
            "bridgeCostUsdc",
            "mevLossUsdc",
            "protocolLpDamageUsdc",
            "liabilityIncreaseUsdc",
        ))
        net = number(outcome.get("aggregateNetProfitUsdc"))
        edge = number(outcome.get("aggregateNetEdgeBpsAfterAllCosts"))
        treasury_net = number(outcome.get("treasuryNetAfterSharedCostsUsdc"))
        counted = number(outcome.get("countedRevenueUsdc"))
        reinvested = number(outcome.get("reinvestedUsdc"))
        computed_net = max(gross - costs, 0.0)
        computed_edge = computed_net / principal * 10_000 if principal > 0 else 0.0
        arithmetic = close(net, computed_net, 2e-6) and close(edge, computed_edge, 2e-6)
        replay_arithmetic_ok = replay_arithmetic_ok and arithmetic
        strict_conditions = all([
            computed_edge >= threshold,
            number(outcome.get("solverNetAfterGasUsdc")) > 0,
            outcome.get("sameBlockVictimBeforeBackrun") is True,
            outcome.get("fixturePrincipalCountedAsRevenue") is False,
            outcome.get("refundableBondCountedAsRevenue") is False,
            outcome.get("internalMintBurnCountedAsRevenue") is False,
            int(outcome.get("engineSettlementResidueRaw", 1)) == 0,
        ])
        reported_pass = outcome.get("strictStatusV153") == "STRICT_NET_EDGE_PASS"
        replay_policy_ok = replay_policy_ok and (reported_pass == strict_conditions)
        if reported_pass:
            replay_pass += 1
            replay_policy_ok = replay_policy_ok and close(counted, treasury_net, 2e-6)
            replay_policy_ok = replay_policy_ok and close(reinvested, counted * 0.8, 2e-6)
        else:
            replay_policy_ok = replay_policy_ok and counted == 0 and reinvested == 0

    checks["replay_rows_present"] = bool(replay_rows)
    checks["replay_arithmetic_recomputed"] = replay_arithmetic_ok
    checks["strict_replay_gate_recomputed"] = replay_policy_ok
    checks["replay_summary_matches_rows"] = (
        int(replay_summary.get("validReplayRows", -1)) == replay_valid
        and int(replay_summary.get("strictPassRows", -1)) == replay_pass
    )

    features = set(estimation.get("features", []))
    diagnostic = set(estimation.get("diagnosticOnlyFeatures", []))
    checks["no_diagnostic_feature_leakage"] = not features.intersection(diagnostic)
    checks["no_post_block_feature_in_execution_model"] = all(
        token not in " ".join(sorted(features)).lower()
        for token in ("post_", "block_boundary", "transaction_index")
    )

    empirical_status = model.get("empiricalStatus", "MISSING_MODEL_REPORT")
    minimum_rows = int(estimation.get("minimumReplayRows", 0))
    if replay_valid < minimum_rows:
        checks["insufficient_sample_classified_honestly"] = empirical_status == "INSUFFICIENT_REPLAY_ROWS"
        checks["no_coefficients_on_insufficient_sample"] = model.get("coefficients") is None
        checks["no_reinvestment_on_insufficient_sample"] = number(model.get("reinvestedUsdc")) == 0
        checks["predictions_empty_on_insufficient_sample"] = not predictions
    else:
        checks["coefficient_status_present"] = empirical_status == "TRANSACTION_LEVEL_COEFFICIENTS_ESTIMATED"
        checks["coefficient_sample_matches"] = int(model.get("sample", {}).get("validReplayRows", -1)) == replay_valid
        checks["time_ordered_split"] = model.get("sample", {}).get("timeOrderedSplit") is True
        checks["coefficients_present"] = isinstance(model.get("coefficients"), dict) and bool(model.get("coefficients"))
        checks["prediction_rows_match_holdout"] = (
            len(predictions) == int(model.get("sample", {}).get("holdoutRows", -1))
        )
        prediction_policy_ok = True
        summed_counted = 0.0
        summed_reinvested = 0.0
        for row in predictions:
            lower = number(row.get("predictedLowerBoundBps"))
            actual = number(row.get("actualNetEdgeBps"))
            execute = row.get("modelWouldExecute") is True
            actual_pass = row.get("actualClearsStrictThreshold") is True
            prediction_policy_ok = prediction_policy_ok and (execute == (lower >= threshold))
            prediction_policy_ok = prediction_policy_ok and (actual_pass == (actual >= threshold))
            counted = number(row.get("countedProtocolRevenueUsdc"))
            reinvested = number(row.get("reinvestedUsdc"))
            if not (execute and actual_pass):
                prediction_policy_ok = prediction_policy_ok and counted == 0 and reinvested == 0
            else:
                prediction_policy_ok = prediction_policy_ok and close(reinvested, counted * 0.8, 2e-6)
            summed_counted += counted
            summed_reinvested += reinvested
        checks["holdout_lcb_gate_recomputed"] = prediction_policy_ok
        economics = model.get("holdoutEconomics", {})
        checks["holdout_counted_revenue_recomputed"] = close(
            summed_counted, number(economics.get("countedNetProtocolRevenueUsdc")), 2e-6
        )
        checks["holdout_reinvestment_recomputed"] = close(
            summed_reinvested, number(economics.get("reinvestedUsdc")), 2e-6
        )

    verdict = "PASS" if all(checks.values()) else "FAIL"
    result = {
        "verdict": verdict,
        "empiricalStatus": empirical_status,
        "checks": checks,
        "counts": {
            "rawRows": len(raw_rows),
            "replayRows": len(replay_rows),
            "validReplayRows": replay_valid,
            "strictReplayPassRows": replay_pass,
            "predictionRows": len(predictions),
        },
        "policy": {
            "strictNetEdgeThresholdBps": threshold,
            "reinvestmentShare": reinvestment_share,
        },
        "interpretation": (
            "PASS proves source and accounting consistency. Only empiricalStatus="
            "TRANSACTION_LEVEL_COEFFICIENTS_ESTIMATED plus strict replay rows establishes "
            "estimated real coefficients; an insufficient sample remains an honest negative result."
        ),
    }
    VERDICT_PATH.parent.mkdir(parents=True, exist_ok=True)
    VERDICT_PATH.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))
    if verdict != "PASS":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
