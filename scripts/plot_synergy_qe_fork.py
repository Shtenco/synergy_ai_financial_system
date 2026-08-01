#!/usr/bin/env python3
import json
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / "reports"
SOURCE = REPORTS / "synergy_qe_polygon_fork_results.json"


def load_rows():
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    return {row["scenario"]: row for row in payload["results"]}


def save_value_capture(rows):
    open_row = rows["open_amm"]
    closed_row = rows["closed_qe_vault"]
    labels = ["Open AMM: treasury", "Open AMM: LVR", "Closed vault: treasury", "Closed vault: bridge"]
    values = [
        open_row.get("treasuryGainWPOL", 0),
        open_row.get("protocolLvrWPOL", 0),
        closed_row.get("treasuryGainWPOL", 0),
        closed_row.get("bridgeGainWPOL", 0),
    ]
    fig, ax = plt.subplots(figsize=(10, 6))
    ax.bar(labels, values)
    ax.set_ylabel("WPOL")
    ax.set_title("Synergy QE value capture: open AMM vs closed vault")
    ax.tick_params(axis="x", rotation=20)
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(REPORTS / "synergy_qe_value_capture.png", dpi=180)
    plt.close(fig)


def save_solver_economics(rows):
    open_row = rows["open_amm"]
    closed_row = rows["closed_qe_vault"]
    labels = ["Open AMM", "Closed QE vault"]
    profit = [open_row["solverProfitWPOL"], closed_row["solverProfitWPOL"]]
    gas = [open_row["gasCostPOLAt274Gwei"], closed_row["gasCostPOLAt274Gwei"]]
    x = range(len(labels))
    width = 0.35
    fig, ax = plt.subplots(figsize=(9, 6))
    ax.bar([i - width / 2 for i in x], profit, width, label="Solver profit")
    ax.bar([i + width / 2 for i in x], gas, width, label="Gas cost")
    ax.set_xticks(list(x), labels)
    ax.set_ylabel("POL / WPOL")
    ax.set_title("Flash-loan solver economics after observed gas")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(REPORTS / "synergy_qe_solver_economics.png", dpi=180)
    plt.close(fig)


def save_summary(rows):
    open_row = rows["open_amm"]
    closed_row = rows["closed_qe_vault"]
    summary = {
        "forkBlock": closed_row["forkBlock"],
        "openAMM": {
            "solverProfitWPOL": open_row["solverProfitWPOL"],
            "protocolLvrWPOL": open_row["protocolLvrWPOL"],
            "gasCostPOLAt274Gwei": open_row["gasCostPOLAt274Gwei"],
        },
        "closedQEVault": {
            "treasuryGainWPOL": closed_row["treasuryGainWPOL"],
            "bridgeGainWPOL": closed_row["bridgeGainWPOL"],
            "solverProfitWPOL": closed_row["solverProfitWPOL"],
            "gasCostPOLAt274Gwei": closed_row["gasCostPOLAt274Gwei"],
        },
        "security": rows.get("security_guards", {}),
    }
    (REPORTS / "synergy_qe_fork_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main():
    REPORTS.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    save_value_capture(rows)
    save_solver_economics(rows)
    save_summary(rows)
    print("Saved fork charts and summary to reports/")


if __name__ == "__main__":
    main()
