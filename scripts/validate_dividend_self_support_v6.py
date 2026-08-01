"""Mandatory acceptance gate for SYNERGY V6 self-support."""
from __future__ import annotations
import json
from pathlib import Path

REPORTS = Path("reports")


def load(name: str):
    return json.loads((REPORTS / name).read_text(encoding="utf-8"))


def main() -> None:
    model = load("dividend_self_support_v6.json")
    fork = load("dividend_self_support_v6_polygon_fork.json")
    active = model["profit_only_compounding"]
    zero = model["zero_external_profit"]
    recycled = model["internal_recycling_only"]
    monte = model["monte_carlo"]
    identities = model["identities"]

    checks = {
        "model_pass": model["verdict"] == "PASS",
        "model_no_new_capital": identities["no_new_investor_capital"],
        "model_capital_identity": identities["capital_identity"],
        "model_reinvestment_identity": identities["reinvestment_identity"],
        "model_multiplier_above_3": active["minimum_multiplier"] >= 3.0,
        "model_risk_invariant": active["minimum_risk_invariant"] >= 1.0,
        "model_self_support_invariant": (
            active["minimum_self_support_invariant"] >= 1.0
        ),
        "model_profit_only_growth": active["backed_capital"] > 120.0,
        "model_zero_profit_no_growth": identities["zero_profit_no_growth"],
        "model_internal_recycling_no_growth": (
            identities["internal_recycling_no_growth"]
        ),
        "model_no_cash_dividend": identities["cash_dividend_zero"],
        "monte_carlo_p05_growth": monte["p05_growth_factor"] > 1.0,
        "monte_carlo_multiplier": monte["minimum_multiplier"] >= 3.0,
        "monte_carlo_risk": monte["minimum_risk_invariant"] >= 1.0,
        "monte_carlo_self_support": (
            monte["minimum_self_support_invariant"] >= 1.0
        ),
        "monte_carlo_cost_coverage": (
            monte["minimum_revenue_cost_coverage"] >= 1.0
        ),
        "monte_carlo_zero_insolvency": (
            monte["insolvency_probability"] == 0.0
        ),
        "monte_carlo_capital_identity": monte["capital_identity_all_paths"],
        "fork_pass": fork["pass"],
        "fork_no_new_capital": (
            fork["newInvestorCapitalAfterBootstrapPOL"] == 0
        ),
        "fork_growth_from_profit_only": (
            abs(
                fork["endingBackedCapitalPOL"]
                - (
                    fork["bootstrapCapitalPOL"]
                    + fork["netExternalProfitPOL"]
                    - fork["taxEscrowPOL"]
                )
            ) < 1e-9
        ),
        "fork_reinvestment_identity": (
            abs(
                fork["retainedReinvestedPOL"]
                + fork["ownerReinvestedPOL"]
                + fork["keeperReinvestedPOL"]
                - (fork["netExternalProfitPOL"] - fork["taxEscrowPOL"])
            ) < 1e-9
        ),
        "fork_multiplier_above_3": fork["recognisedMultiplier"] >= 3.0,
        "fork_risk_invariant": fork["riskInvariant"] >= 1.0,
        "fork_self_support_invariant": fork["selfSupportInvariant"] >= 1.0,
        "fork_keeper_cost_covered": fork["keeperCostCoverage"] >= 1.0,
        "fork_cash_dividend_zero": fork["cashDividendPOL"] == 0,
        "fork_late_capital_rejected": (
            fork["lateInvestorCapitalRejectedByController"]
        ),
        "fork_internal_revenue_rejected": fork["internalRevenueRejected"],
        "fork_quickswap_positions_grew": (
            int(fork["quickSwapPositionGrowth"]["polSynaAfter"])
            > int(fork["quickSwapPositionGrowth"]["polSynaBefore"])
            and int(fork["quickSwapPositionGrowth"]["polSynrAfter"])
            > int(fork["quickSwapPositionGrowth"]["polSynrBefore"])
        ),
    }
    failed = [name for name, passed in checks.items() if not passed]
    verdict = (
        "SYNERGY V6 SELF-SUPPORT: PASS"
        if not failed
        else "SYNERGY V6 SELF-SUPPORT: FAIL"
    )
    result = {
        "verdict": verdict,
        "checks": checks,
        "failed_invariants": failed,
        "metrics": {
            "model_ending_capital_pol": active["backed_capital"],
            "model_growth_factor": active["backed_capital"] / 120.0,
            "model_minimum_multiplier": active["minimum_multiplier"],
            "model_minimum_self_support_invariant": (
                active["minimum_self_support_invariant"]
            ),
            "model_zero_profit_ending_capital_pol": zero["backed_capital"],
            "model_internal_recycling_ending_capital_pol": (
                recycled["backed_capital"]
            ),
            "monte_carlo_p05_growth_factor": monte["p05_growth_factor"],
            "monte_carlo_minimum_multiplier": monte["minimum_multiplier"],
            "monte_carlo_minimum_self_support_invariant": (
                monte["minimum_self_support_invariant"]
            ),
            "fork_ending_capital_pol": fork["endingBackedCapitalPOL"],
            "fork_growth_factor": fork["capitalGrowthFactor"],
            "fork_multiplier": fork["recognisedMultiplier"],
            "fork_self_support_invariant": fork["selfSupportInvariant"],
            "fork_keeper_cost_coverage": fork["keeperCostCoverage"],
        },
        "economic_verdict": (
            "The system is self-supporting in the strict no-new-investor-capital "
            "sense only while productive capital continues to earn real external "
            "operating revenue. Reinvestment compounds earned profit. With zero "
            "external profit, both the model and the fork policy forbid false growth."
        ),
    }
    (REPORTS / "dividend_self_support_v6_verdict.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
