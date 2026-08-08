from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
import random
from statistics import median

from financial_os_v4.real_economy_bridge import FXSettlementProfile


@dataclass(frozen=True)
class Config:
    # Public 2025 calibration anchors; see docs/REAL_ECONOMY_MARKETPLACE_BANK_BRIDGE_20260809.md
    annual_ecommerce_rub: float = 11.5e12
    local_channel_share: float = 0.962
    crossborder_share: float = 0.038
    annual_household_financial_savings_rub: float = 13.2e12

    # Scenario assumptions, not empirical facts.
    domestic_channel_import_content: float = 0.35
    os_capture_share_of_new_savings: float = 0.001
    term_eligible_share: float = 0.40
    bank_transform_cap: float = 0.45
    max_weekly_target_authorization: float = 60e6
    bank_bid_fill_min: float = 0.55
    bank_bid_fill_max: float = 1.00
    project_duration_min: int = 8
    project_duration_max: int = 20
    project_success_probability: float = 0.88
    domestic_project_share: float = 0.68
    domestic_goods_ratio: float = 0.55
    import_goods_ratio: float = 0.85
    domestic_productive_base_ratio: float = 0.35
    import_productive_base_ratio: float = 0.12
    import_goods_unlock_haircut: float = 0.30
    annual_bank_yield: float = 0.16
    failure_lgd: float = 0.30
    os_success_fee: float = 0.002
    fx_profile: FXSettlementProfile = FXSettlementProfile(0.55, 0.30, 0.12, 0.03)


@dataclass
class Project:
    investment: float
    authorization: float
    start: int
    due: int
    domestic: bool
    success_draw: float
    resolved: bool = False


def import_origin_share(cfg: Config) -> float:
    return cfg.crossborder_share + cfg.local_channel_share * cfg.domestic_channel_import_content


def run(cycles: int, seed: int, *, stress: bool = False, cfg: Config | None = None) -> dict[str, float]:
    if cycles not in (100, 250, 500):
        raise ValueError("cycles must be 100, 250 or 500")
    cfg = cfg or Config()
    rng = random.Random(seed)

    weekly_new_savings = cfg.annual_household_financial_savings_rub / 52.0
    savings_capacity = (
        weekly_new_savings
        * cfg.os_capture_share_of_new_savings
        * cfg.term_eligible_share
        * cfg.bank_transform_cap
    )

    result = {
        "private_investment": 0.0,
        "target_authorization": 0.0,
        "authorization_unlocked": 0.0,
        "authorization_cancelled": 0.0,
        "verified_domestic_goods": 0.0,
        "verified_import_goods": 0.0,
        "verified_productive_base": 0.0,
        "import_fx_replenishment": 0.0,
        "bank_interest": 0.0,
        "bank_credit_loss": 0.0,
        "os_external_fee_revenue": 0.0,
    }
    projects: list[Project] = []

    for week in range(cycles):
        for project in projects:
            if project.resolved or project.due > week:
                continue
            project.resolved = True
            duration = project.due - project.start
            success_probability = cfg.project_success_probability * (0.82 if stress else 1.0)
            success = project.success_draw < success_probability
            if not success:
                result["authorization_cancelled"] += project.authorization
                result["bank_credit_loss"] += (
                    project.investment * cfg.failure_lgd * (1.25 if stress else 1.0)
                )
                continue

            if project.domestic:
                domestic_goods = (
                    project.investment * cfg.domestic_goods_ratio * rng.uniform(0.75, 1.25)
                )
                import_goods = 0.0
                productive = (
                    project.investment
                    * cfg.domestic_productive_base_ratio
                    * rng.uniform(0.75, 1.25)
                )
            else:
                domestic_goods = 0.0
                import_goods = (
                    project.investment * cfg.import_goods_ratio * rng.uniform(0.75, 1.25)
                )
                productive = (
                    project.investment
                    * cfg.import_productive_base_ratio
                    * rng.uniform(0.60, 1.40)
                )
                result["import_fx_replenishment"] += project.investment

            eligible_growth = (
                domestic_goods
                + cfg.import_goods_unlock_haircut * import_goods
                + productive
            )
            unlocked = min(project.authorization, eligible_growth)
            result["authorization_unlocked"] += unlocked
            result["authorization_cancelled"] += project.authorization - unlocked
            result["verified_domestic_goods"] += domestic_goods
            result["verified_import_goods"] += import_goods
            result["verified_productive_base"] += productive
            result["bank_interest"] += (
                project.investment * cfg.annual_bank_yield * duration / 52.0
            )
            result["os_external_fee_revenue"] += project.investment * cfg.os_success_fee

        capacity = savings_capacity * (0.65 if stress else 1.0)
        bid_fill = rng.uniform(cfg.bank_bid_fill_min, cfg.bank_bid_fill_max)
        private_investment = min(cfg.max_weekly_target_authorization, capacity) * bid_fill
        if private_investment <= 100_000:
            continue
        project = Project(
            investment=private_investment,
            authorization=private_investment,
            start=week,
            due=week + rng.randint(cfg.project_duration_min, cfg.project_duration_max),
            domestic=rng.random() < cfg.domestic_project_share,
            success_draw=rng.random(),
        )
        projects.append(project)
        result["private_investment"] += private_investment
        result["target_authorization"] += private_investment

    result["authorization_outstanding"] = sum(
        project.authorization for project in projects if not project.resolved
    )
    result["verified_goods"] = (
        result["verified_domestic_goods"] + result["verified_import_goods"]
    )
    result["bank_net_result"] = result["bank_interest"] - result["bank_credit_loss"]
    result["unlock_ratio"] = (
        result["authorization_unlocked"] / result["target_authorization"]
        if result["target_authorization"] > 0
        else 0.0
    )
    fx = cfg.fx_profile.allocate(result["import_fx_replenishment"])
    result.update({f"import_settlement_{key.lower()}": value for key, value in fx.items()})
    return result


def monte_carlo(cycles: int, *, stress: bool, seeds: int = 300) -> dict[str, float]:
    rows = [run(cycles, seed + 1, stress=stress) for seed in range(seeds)]
    keys = rows[0].keys()
    summary: dict[str, float] = {}
    for key in keys:
        values = sorted(row[key] for row in rows)
        summary[f"{key}_median"] = median(values)
        summary[f"{key}_p10"] = values[int(0.10 * (len(values) - 1))]
        summary[f"{key}_p90"] = values[int(0.90 * (len(values) - 1))]
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seeds", type=int, default=300)
    args = parser.parse_args()
    cfg = Config()
    payload = {
        "status": "LOCAL_RESEARCH_CALIBRATION_NOT_FORECAST",
        "config": {
            **{k: v for k, v in asdict(cfg).items() if k != "fx_profile"},
            "fx_profile": asdict(cfg.fx_profile),
            "implied_ecommerce_import_origin_share": import_origin_share(cfg),
        },
        "runs": {},
    }
    for cycles in (100, 250, 500):
        for stress in (False, True):
            name = f"{cycles}_{'stress' if stress else 'base'}"
            payload["runs"][name] = monte_carlo(cycles, stress=stress, seeds=args.seeds)
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
