"""Validate all generated V3 reports and emit a single PASS/FAIL verdict."""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPORTS = Path("reports")


def load(name: str) -> dict:
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def main() -> None:
    deterministic = load("consolidated_summary.json")
    monte = load("formal_invariants.json")
    stress = load("stress_matrix.json")
    fork_path = REPORTS / "qe_qt_integrated_solvency_polygon_fork.json"
    fork = json.loads(fork_path.read_text(encoding="utf-8")) if fork_path.exists() else {}

    dm = deterministic["metrics"]
    checks = {
        "deterministic_solvency_normal": dm["economic_solvency_ratio"] >= 1.20,
        "deterministic_liquidity_normal": dm["liquidity_coverage"] >= 1.20,
        "deterministic_gas_normal": dm["gas_coverage"] >= 1.20,
        "deterministic_policy_ratio": dm["reserve_policy_ratio"] >= 0.70,
        "deterministic_dividend_bound": bool(dm["dividend_invariant"]),
        "monte_carlo_zero_insolvency": monte["insolvency_probability"] == 0.0,
        "monte_carlo_dividend_bound": bool(monte["dividend_invariant_all_paths"]),
        "monte_carlo_no_negative_reserve": bool(monte["no_negative_reserve_all_paths"]),
        "monte_carlo_gas_floor": monte["minimum_gas_coverage"] >= 1.20,
        "monte_carlo_pool_floor": monte["minimum_pool_depth"] >= 25.0,
        "internal_transfer_revenue_zero": monte["internal_transfer_revenue"] == 0.0,
        "stress_all_safe": stress["safe_scenarios"] == stress["scenarios"],
        "fork_integration_pass": bool(fork.get("pass", False)),
        "fork_zero_final_liability": fork.get("externalLiabilitiesFinal") == 0,
        "fork_dividend_bounded": fork.get("dividendWPOL", 0) <= fork.get("realizedExternalPnLWPOL", -1),
    }
    failed = [name for name, passed in checks.items() if not passed]
    passed = not failed
    verdict = "SOLVENT SYSTEM: PASS" if passed else "SOLVENT SYSTEM: FAIL"

    result = {
        "verdict": verdict,
        "checks": checks,
        "failed_invariants": failed,
        "metrics": {
            "minimum_solvency_ratio": monte["minimum_solvency_ratio"],
            "minimum_liquidity_coverage": monte["minimum_liquidity_coverage"],
            "minimum_gas_coverage": monte["minimum_gas_coverage"],
            "maximum_drawdown": monte["maximum_drawdown"],
            "median_external_realized_pnl": monte["median_external_realized_pnl"],
            "median_internal_transfer_volume": monte["median_internal_transfer_volume"],
            "median_dividends": monte["median_dividends"],
            "minimum_pool_depth": monte["minimum_pool_depth"],
            "insolvency_probability": monte["insolvency_probability"],
            "successful_stress_scenarios": stress["safe_scenarios"],
            "total_stress_scenarios": stress["scenarios"],
            "fork_realized_external_pnl_wpol": fork.get("realizedExternalPnLWPOL"),
            "fork_dividend_wpol": fork.get("dividendWPOL"),
            "fork_gas_used": fork.get("gasUsed"),
        },
        "limitations": [
            "The integrated fork test uses real Polygon WPOL but a locally deployed SYN token.",
            "QuickSwap swaps, Aave positions and a production bridge are not yet invoked by the consolidated V3 fork test.",
            "Monte Carlo is a model validation, not proof of future market demand or future revenue.",
        ],
    }
    (REPORTS / "solvent_system_verdict.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    status_rows = "\n".join(
        f"- {'PASS' if value else 'FAIL'} — `{name}`" for name, value in checks.items()
    )
    report = f"""# Консолидированный аудит SYNERGY QE/QT V3

## Вердикт

**{verdict}**

## Проверенные инварианты

{status_rows}

## Ключевые метрики Monte Carlo

- Траекторий: **{monte['paths']}**
- Блоков на траекторию: **{monte['blocks_per_path']}**
- Минимальный Economic Solvency Ratio: **{monte['minimum_solvency_ratio']:.6f}**
- Минимальный Liquidity Coverage: **{monte['minimum_liquidity_coverage']:.6f}**
- Минимальный Gas Coverage: **{monte['minimum_gas_coverage']:.6f}**
- Максимальная просадка NAV: **{monte['maximum_drawdown']:.6%}**
- Медианный realized external PnL: **{monte['median_external_realized_pnl']:.6f}**
- Медианный внутренний оборот: **{monte['median_internal_transfer_volume']:.6f}**
- Медианные дивиденды: **{monte['median_dividends']:.6f}**
- Минимальная глубина пула: **{monte['minimum_pool_depth']:.6f}**
- Вероятность insolvency: **{monte['insolvency_probability']:.6%}**

## Stress matrix

- Безопасно пройдено: **{stress['safe_scenarios']} / {stress['scenarios']}**
- Не пройдены: **{', '.join(stress['failed_scenarios']) if stress['failed_scenarios'] else 'нет'}**

## Polygon fork

- Реальный WPOL: **{fork.get('realPolygonWPOL', False)}**
- Внешних циклов: **{fork.get('cycles', 0)}**
- Финальные liabilities: **{fork.get('externalLiabilitiesFinal')}**
- Realized external PnL: **{fork.get('realizedExternalPnLWPOL')} WPOL**
- Dividend: **{fork.get('dividendWPOL')} WPOL**
- Gas used: **{fork.get('gasUsed')}**

## Ограничения текущего доказательства

1. В fork-тесте используется реальный Polygon WPOL, но локально развёрнутый SYN.
2. Consolidated V3 пока не выполняет реальные QuickSwap swap/add/remove LP и Aave supply/withdraw.
3. Bridge остаётся моделируемым системным bucket, а не доказанным production bridge.
4. Monte Carlo подтверждает инварианты модели, но не гарантирует будущий внешний спрос.

## Минимальный counterexample при FAIL

{'; '.join(failed) if failed else 'Нарушенных инвариантов в выполненном наборе тестов не обнаружено.'}
"""
    (REPORTS / "CONSOLIDATED_SOLVENCY_REPORT_RU.md").write_text(report, encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not passed:
        sys.exit(1)


if __name__ == "__main__":
    main()
