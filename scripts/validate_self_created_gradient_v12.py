#!/usr/bin/env python3
import csv
import json
from pathlib import Path

REPORT = Path("reports/self_created_gradient_v12_polygon_fork.json")
OUT = Path("reports")

if not REPORT.exists():
    raise SystemExit("FAIL: fork report is missing")

data = json.loads(REPORT.read_text(encoding="utf-8"))
required = {
    "externalShockApplied",
    "gradientCreatedOnlyByInternalQeQt",
    "cycles",
    "totalsBeforeReinvestment",
    "reinvestment",
    "invariants",
    "economicVerdict",
}
missing = required - set(data)
if missing:
    raise SystemExit(f"FAIL: missing report fields: {sorted(missing)}")

if data["externalShockApplied"] is not False:
    raise SystemExit("FAIL: the probe used an external shock")
if data["gradientCreatedOnlyByInternalQeQt"] is not True:
    raise SystemExit("FAIL: gradient was not created exclusively by internal QE/QT")
if not data["cycles"]:
    raise SystemExit("FAIL: no self-created-gradient cycle completed")

failed = [name for name, ok in data["invariants"].items() if ok is not True]
if failed:
    raise SystemExit(f"FAIL: invariant failures: {failed}")

cycles = data["cycles"]
with (OUT / "self_created_gradient_v12_cycles.csv").open("w", newline="", encoding="utf-8") as fh:
    writer = csv.DictWriter(fh, fieldnames=list(cycles[0].keys()))
    writer.writeheader()
    writer.writerows(cycles)

try:
    import matplotlib.pyplot as plt

    x = [row["cycle"] for row in cycles]

    def save_line(name, title, ys, ylabel):
        plt.figure(figsize=(11, 6))
        for label, values in ys:
            plt.plot(x, values, label=label)
        plt.xlabel("Cycle")
        plt.ylabel(ylabel)
        plt.title(title)
        plt.grid(True, alpha=0.3)
        plt.legend()
        plt.tight_layout()
        plt.savefig(OUT / name, dpi=180)
        plt.close()

    save_line(
        "self_created_gradient_01_wallet_vs_protocol.png",
        "Wallet profit versus consolidated protocol result",
        [
            ("Treasury wallet profit", [r["treasuryCumulativeUsdt"] for r in cycles]),
            ("Consolidated protocol delta", [r["protocolConsolidatedDeltaUsdt"] for r in cycles]),
            ("Protocol delta after gas", [r["protocolDeltaAfterGasUsdt"] for r in cycles]),
        ],
        "USDT",
    )
    save_line(
        "self_created_gradient_02_lp_and_external.png",
        "Internal LP change and external-pool value change",
        [
            ("Internal LP delta", [r["internalLpDeltaUsdt"] for r in cycles]),
            ("External pool delta", [r["externalPoolDeltaAtReferenceUsdt"] for r in cycles]),
        ],
        "USDT at initial external reference price",
    )
    save_line(
        "self_created_gradient_03_external_usdt_paid.png",
        "USDT paid by the real external pool per cycle",
        [("External USDT paid", [r["externalPoolUsdtPaid"] for r in cycles])],
        "USDT",
    )
    save_line(
        "self_created_gradient_04_internal_reserve_ratios.png",
        "Internal liquid-reserve redistribution",
        [
            ("WPOL-pool liquid remaining", [r["poolWpolLiquidRemainingRatio"] for r in cycles]),
            ("USDT-pool liquid growth", [r["poolUsdtLiquidGrowthRatio"] for r in cycles]),
        ],
        "Ratio to start",
    )
except Exception as exc:
    raise SystemExit(f"FAIL: chart generation failed: {exc}")

summary = {
    "verdict": data["economicVerdict"],
    "externalShockApplied": data["externalShockApplied"],
    "completedCycles": data["totalsBeforeReinvestment"]["completedCycles"],
    "externalPoolUsdtPaid": data["totalsBeforeReinvestment"]["externalPoolUsdtPaid"],
    "treasuryWalletProfitUsdt": data["totalsBeforeReinvestment"]["treasuryWalletProfitUsdt"],
    "internalLpDeltaUsdt": data["totalsBeforeReinvestment"]["internalLpDeltaUsdt"],
    "protocolConsolidatedDeltaUsdt": data["totalsBeforeReinvestment"]["protocolConsolidatedDeltaUsdt"],
    "protocolDeltaAfterGasUsdt": data["totalsBeforeReinvestment"]["protocolDeltaAfterGasUsdt"],
    "externalPoolDeltaAtReferenceUsdt": data["totalsBeforeReinvestment"]["externalPoolDeltaAtReferenceUsdt"],
    "reinvestmentNavChangeUsdt": data["reinvestment"]["navChangeUsdt"],
    "invariants": data["invariants"],
}
(OUT / "self_created_gradient_v12_verdict.json").write_text(
    json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
)

print(json.dumps(summary, indent=2, ensure_ascii=False))
print("FORK PROBE COMPLETE: accounting invariants PASS")
print(f"ECONOMIC VERDICT: {data['economicVerdict']}")
