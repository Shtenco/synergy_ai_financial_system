import json
from pathlib import Path

from sinergy_rnd_handoff import MarketExperimentResult


ROOT = Path(__file__).resolve().parents[1]
SCHEMA_PATH = ROOT / "schemas/market_experiment_result_v1.schema.json"


def _payload() -> dict:
    result = MarketExperimentResult(
        experiment_id="schema-001",
        experiment_class="FLASH",
        mode="FORK",
        network="Base",
        reporting_asset="USDC",
        external_assets_before="10",
        external_liabilities_before="0",
        external_assets_after="10.1",
        external_liabilities_after="0",
        net_new_external_capital="0",
        externally_observed_revenue="0.2",
        gas_cost="0.03",
        venue_fees="0.01",
        bridge_fees="0",
        flash_fees="0.02",
        other_external_costs="0",
        mint_notional="100",
        flash_principal_peak="1000",
        internal_mark_change="50",
        self_token_mark_change="70",
        revenue_evidence_digest="aa" * 32,
        execution_evidence_digest="bb" * 32,
    )
    return result.to_dict()


def test_runtime_emits_exact_declared_shape() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    payload = _payload()
    assert set(payload) == set(schema["required"])
    assert set(payload) <= set(schema["properties"])
    assert payload["schema"] == "market.experiment-result/v1"


def test_schema_locks_rnd_and_financial_os_authority() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    assert schema["properties"]["classification"] == {"const": "RND_ONLY"}
    assert schema["properties"]["accounting_authority"] == {
        "const": "Shtenco/synergy_financial_os"
    }
