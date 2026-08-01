#!/usr/bin/env python3
"""Estimate V15.3 transaction-level coefficients with a time-split ridge model.

The model predicts aggregate net route edge after all attributable costs. It
uses only covariates observable or simulatable before bundle submission. The
execution rule is deliberately conservative: the one-sided 95% bootstrap lower
prediction bound must clear 2.685148 bps. Eighty percent of realized net
protocol revenue is reinvested; marked or predicted profit is never reinvested.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import math
import os
from pathlib import Path
import random
from statistics import mean
from typing import Any, Iterable

SPEC_PATH = Path(os.getenv("V153_PANEL_SPEC", "economics/v15_3_transaction_panel_spec.json"))
PANEL_PATH = Path(os.getenv("V153_REPLAYED_PANEL", "reports/v15_3_transaction_panel_replayed.jsonl"))
REPORT_PATH = Path(os.getenv("V153_COEFFICIENT_REPORT", "reports/v15_3_transaction_coefficients.json"))
PREDICTIONS_PATH = Path(os.getenv("V153_HOLDOUT_PREDICTIONS", "reports/v15_3_holdout_predictions.jsonl"))
SEED = int(os.getenv("V153_ESTIMATION_SEED", "153"))


@dataclass
class Standardization:
    means: list[float]
    scales: list[float]


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    if not path.exists():
        return rows
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"row {line_number} is not an object")
        rows.append(value)
    return rows


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> None:
    values = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(row, sort_keys=True) for row in values)
        + ("\n" if values else ""),
        encoding="utf-8",
    )


def finite(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def nested(row: dict[str, Any], *keys: str, default: Any = None) -> Any:
    value: Any = row
    for key in keys:
        if not isinstance(value, dict) or key not in value:
            return default
        value = value[key]
    return value


def feature_vector(row: dict[str, Any]) -> dict[str, float] | None:
    amount = finite(nested(row, "victim", "amountInUsdc"), -1.0)
    tvl = finite(nested(row, "targetVenue", "preTvlUsdc"), -1.0)
    pre_quote = nested(row, "probe", "preVictimBlockRoundtrip")
    outcome = row.get("forkReplayOutcome") or {}
    if amount <= 0 or tvl <= 0 or not isinstance(pre_quote, dict):
        return None
    target = finite(outcome.get("aggregateNetEdgeBpsAfterAllCosts"), math.nan)
    if not math.isfinite(target) or outcome.get("evidenceStatusV151") == "REPLAY_ERROR":
        return None
    return {
        "log_victim_notional_usdc": math.log(amount),
        "log_target_tvl_usdc": math.log(tvl),
        "victim_amount_to_tvl_bps": finite(nested(row, "victim", "amountToTargetTvlBps")),
        "victim_price_impact_bps": finite(nested(row, "victim", "priceImpactBps")),
        "pre_roundtrip_gross_edge_bps": finite(pre_quote.get("grossEdgeBps")),
        "realized_volatility_bps": finite(nested(row, "volatility", "realizedLogReturnVolatilityBps")),
        "estimated_route_gas_bps": finite(nested(row, "gas", "estimatedRouteGasBps")),
        "base_fee_gwei": finite(nested(row, "gas", "baseFeeGwei")),
        "priority_fee_gwei": finite(nested(row, "gas", "priorityFeeGwei")),
        "target": target,
    }


def quantile(values: list[float], q: float) -> float:
    if not values:
        return math.nan
    ordered = sorted(values)
    position = (len(ordered) - 1) * q
    low = int(math.floor(position))
    high = int(math.ceil(position))
    if low == high:
        return ordered[low]
    weight = position - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


def solve_linear(matrix: list[list[float]], vector: list[float]) -> list[float]:
    n = len(vector)
    augmented = [matrix[i][:] + [vector[i]] for i in range(n)]
    for column in range(n):
        pivot = max(range(column, n), key=lambda row: abs(augmented[row][column]))
        if abs(augmented[pivot][column]) < 1e-12:
            raise ValueError("singular design matrix")
        augmented[column], augmented[pivot] = augmented[pivot], augmented[column]
        scale = augmented[column][column]
        augmented[column] = [value / scale for value in augmented[column]]
        for row in range(n):
            if row == column:
                continue
            factor = augmented[row][column]
            if factor == 0:
                continue
            augmented[row] = [
                augmented[row][index] - factor * augmented[column][index]
                for index in range(n + 1)
            ]
    return [augmented[index][-1] for index in range(n)]


def standardize_fit(x: list[list[float]]) -> Standardization:
    columns = len(x[0])
    means: list[float] = []
    scales: list[float] = []
    for column in range(columns):
        values = [row[column] for row in x]
        avg = mean(values)
        variance = sum((value - avg) ** 2 for value in values) / max(len(values) - 1, 1)
        scale = math.sqrt(variance)
        means.append(avg)
        scales.append(scale if scale > 1e-12 else 1.0)
    return Standardization(means, scales)


def standardize_apply(x: list[list[float]], transform: Standardization) -> list[list[float]]:
    return [
        [
            (value - transform.means[index]) / transform.scales[index]
            for index, value in enumerate(row)
        ]
        for row in x
    ]


def ridge_fit(x: list[list[float]], y: list[float], penalty: float) -> list[float]:
    design = [[1.0] + row for row in x]
    columns = len(design[0])
    xtx = [[0.0 for _ in range(columns)] for _ in range(columns)]
    xty = [0.0 for _ in range(columns)]
    for row, target in zip(design, y):
        for i in range(columns):
            xty[i] += row[i] * target
            for j in range(columns):
                xtx[i][j] += row[i] * row[j]
    for index in range(1, columns):
        xtx[index][index] += penalty
    return solve_linear(xtx, xty)


def predict(beta: list[float], x: list[list[float]]) -> list[float]:
    return [beta[0] + sum(coef * value for coef, value in zip(beta[1:], row)) for row in x]


def original_scale_coefficients(
    beta: list[float], transform: Standardization, names: list[str]
) -> dict[str, float]:
    coefficients = {
        name: beta[index + 1] / transform.scales[index]
        for index, name in enumerate(names)
    }
    intercept = beta[0] - sum(
        beta[index + 1] * transform.means[index] / transform.scales[index]
        for index in range(len(names))
    )
    return {"intercept": intercept, **coefficients}


def metric_report(actual: list[float], predicted: list[float]) -> dict[str, float]:
    if not actual:
        return {"mae": math.nan, "rmse": math.nan, "r2": math.nan}
    errors = [prediction - target for prediction, target in zip(predicted, actual)]
    mae = mean(abs(error) for error in errors)
    rmse = math.sqrt(mean(error * error for error in errors))
    baseline = mean(actual)
    denominator = sum((target - baseline) ** 2 for target in actual)
    r2 = 1 - sum(error * error for error in errors) / denominator if denominator > 0 else 0.0
    return {"mae": mae, "rmse": rmse, "r2": r2}


def block_bootstrap_indices(length: int, rng: random.Random) -> list[int]:
    block_length = max(2, int(round(math.sqrt(length))))
    indices: list[int] = []
    while len(indices) < length:
        start = rng.randrange(length)
        for offset in range(block_length):
            indices.append((start + offset) % length)
            if len(indices) == length:
                break
    return indices


def confusion(actual: list[float], decision: list[bool], threshold: float) -> dict[str, float | int]:
    tp = fp = tn = fn = 0
    for value, accepted in zip(actual, decision):
        positive = value >= threshold
        if accepted and positive:
            tp += 1
        elif accepted and not positive:
            fp += 1
        elif not accepted and positive:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "truePositive": tp,
        "falsePositive": fp,
        "trueNegative": tn,
        "falseNegative": fn,
        "precision": precision,
        "recall": recall,
    }


def insufficient_report(spec: dict[str, Any], reason: str, rows: int) -> dict[str, Any]:
    return {
        "model": "SYNERGY V15.3 transaction-level ridge coefficients",
        "empiricalStatus": "INSUFFICIENT_REPLAY_ROWS",
        "reason": reason,
        "validRows": rows,
        "minimumReplayRows": spec["estimation"]["minimumReplayRows"],
        "strictNetEdgeThresholdBps": spec["policy"]["strictNetEdgeBps"],
        "reinvestmentShare": spec["policy"]["reinvestmentShare"],
        "coefficients": None,
        "countedRevenueUsdc": 0.0,
        "reinvestedUsdc": 0.0,
        "interpretation": "No empirical coefficient or revenue claim is permitted until the minimum strict replay sample exists.",
    }


def main() -> None:
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    names = list(spec["estimation"]["features"])
    raw_rows = load_jsonl(PANEL_PATH)
    prepared: list[tuple[dict[str, Any], dict[str, float]]] = []
    for row in sorted(raw_rows, key=lambda item: (int(item["blockNumber"]), int(item["transactionIndex"]))):
        features = feature_vector(row)
        if features is not None:
            prepared.append((row, features))

    minimum = int(spec["estimation"]["minimumReplayRows"])
    if len(prepared) < minimum:
        report = insufficient_report(spec, "strict replay sample below minimum", len(prepared))
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
        write_jsonl(PREDICTIONS_PATH, [])
        print(json.dumps(report, indent=2))
        return

    holdout_fraction = float(spec["estimation"]["holdoutFraction"])
    holdout_size = max(int(spec["estimation"]["minimumHoldoutRows"]), round(len(prepared) * holdout_fraction))
    holdout_size = min(holdout_size, len(prepared) - int(spec["estimation"]["minimumTrainingRows"]))
    split = len(prepared) - holdout_size
    training = prepared[:split]
    holdout = prepared[split:]

    x_train = [[features[name] for name in names] for _, features in training]
    y_train = [features["target"] for _, features in training]
    x_holdout = [[features[name] for name in names] for _, features in holdout]
    y_holdout = [features["target"] for _, features in holdout]
    transform = standardize_fit(x_train)
    x_train_z = standardize_apply(x_train, transform)
    x_holdout_z = standardize_apply(x_holdout, transform)
    penalty = float(spec["estimation"]["ridgePenalty"])
    beta = ridge_fit(x_train_z, y_train, penalty)
    train_predictions = predict(beta, x_train_z)
    holdout_predictions = predict(beta, x_holdout_z)

    replications = int(spec["estimation"]["bootstrapReplications"])
    rng = random.Random(SEED)
    bootstrap_betas: list[list[float]] = []
    bootstrap_holdout_predictions: list[list[float]] = [[] for _ in holdout]
    for _ in range(replications):
        indices = block_bootstrap_indices(len(training), rng)
        bx = [x_train_z[index] for index in indices]
        by = [y_train[index] for index in indices]
        try:
            b_beta = ridge_fit(bx, by, penalty)
        except ValueError:
            continue
        bootstrap_betas.append(b_beta)
        values = predict(b_beta, x_holdout_z)
        for index, value in enumerate(values):
            bootstrap_holdout_predictions[index].append(value)

    lower_quantile = 1 - 0.95
    lower_bounds = [
        quantile(values, lower_quantile) if values else prediction
        for values, prediction in zip(bootstrap_holdout_predictions, holdout_predictions)
    ]
    threshold = float(spec["policy"]["strictNetEdgeBps"])
    decisions = [bound >= threshold for bound in lower_bounds]
    confusion_report = confusion(y_holdout, decisions, threshold)

    coefficient_original = original_scale_coefficients(beta, transform, names)
    coefficient_rows: dict[str, dict[str, float]] = {}
    for index, name in enumerate(["intercept"] + names):
        samples = [item[index] for item in bootstrap_betas]
        point = beta[index]
        coefficient_rows[name] = {
            "standardizedPoint": point,
            "standardizedP05": quantile(samples, 0.05),
            "standardizedP95": quantile(samples, 0.95),
            "originalUnitPoint": coefficient_original[name],
        }

    prediction_rows: list[dict[str, Any]] = []
    executed_net_protocol = 0.0
    reinvested = 0.0
    false_positive_cost = 0.0
    for (row, features), prediction, lower, accepted in zip(
        holdout, holdout_predictions, lower_bounds, decisions
    ):
        outcome = row["forkReplayOutcome"]
        actual_pass = features["target"] >= threshold
        counted = finite(outcome.get("countedRevenueUsdc")) if accepted and actual_pass else 0.0
        retained = counted * float(spec["policy"]["reinvestmentShare"])
        if accepted and not actual_pass:
            false_positive_cost += finite(outcome.get("operationalGasUsdc"))
        executed_net_protocol += counted
        reinvested += retained
        prediction_rows.append({
            "transactionHash": row["transactionHash"],
            "blockNumber": row["blockNumber"],
            "actualNetEdgeBps": features["target"],
            "predictedNetEdgeBps": prediction,
            "predictedLowerBoundBps": lower,
            "modelWouldExecute": accepted,
            "actualClearsStrictThreshold": actual_pass,
            "countedProtocolRevenueUsdc": counted,
            "reinvestedUsdc": retained,
        })
    write_jsonl(PREDICTIONS_PATH, prediction_rows)

    actual_pass_rate = sum(value >= threshold for value in y_holdout) / len(y_holdout)
    model_execute_rate = sum(decisions) / len(decisions)
    report = {
        "model": "SYNERGY V15.3 transaction-level ridge coefficients",
        "empiricalStatus": "TRANSACTION_LEVEL_COEFFICIENTS_ESTIMATED",
        "chainId": spec["chainId"],
        "marketId": spec["market"]["id"],
        "sample": {
            "validReplayRows": len(prepared),
            "trainingRows": len(training),
            "holdoutRows": len(holdout),
            "firstTrainingBlock": training[0][0]["blockNumber"],
            "lastTrainingBlock": training[-1][0]["blockNumber"],
            "firstHoldoutBlock": holdout[0][0]["blockNumber"],
            "lastHoldoutBlock": holdout[-1][0]["blockNumber"],
            "timeOrderedSplit": True,
        },
        "policy": {
            "strictNetEdgeThresholdBps": threshold,
            "oneSidedBootstrapConfidence": 0.95,
            "gate": "bootstrap prediction P05 >= 2.685148 bps",
            "reinvestmentShare": spec["policy"]["reinvestmentShare"],
            "actualHoldoutPassRate": actual_pass_rate,
            "modelExecutionRate": model_execute_rate,
        },
        "features": names,
        "diagnosticOnlyFeaturesExcludedFromExecutionModel": spec["estimation"]["diagnosticOnlyFeatures"],
        "coefficients": coefficient_rows,
        "trainingMetrics": metric_report(y_train, train_predictions),
        "holdoutMetrics": metric_report(y_holdout, holdout_predictions),
        "holdoutGateConfusion": confusion_report,
        "bootstrap": {
            "requestedReplications": replications,
            "successfulReplications": len(bootstrap_betas),
            "method": "contiguous circular block bootstrap",
        },
        "holdoutEconomics": {
            "countedNetProtocolRevenueUsdc": executed_net_protocol,
            "reinvestedUsdc": reinvested,
            "retainedButNotReinvestedUsdc": executed_net_protocol - reinvested,
            "falsePositiveOperationalGasUsdc": false_positive_cost,
        },
        "strictAccounting": {
            "predictedProfitCountedAsRevenue": False,
            "blockBoundaryMarkedProfitCountedAsRevenue": False,
            "fixturePrincipalCountedAsRevenue": False,
            "onlyRealizedStrictPassProtocolRevenueReinvested": True,
        },
        "limitations": [
            "The initial panel covers one Polygon market and one V15.1 route family.",
            "Historical fork replay cannot guarantee future inclusion, latency or solver competition.",
            "Coefficients are conditional on the sampled block range and must be re-estimated on a rolling window.",
            "A model PASS is not enough: every live trade still requires atomic realized accounting and the 2.685148 bps post-cost gate."
        ],
    }
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
