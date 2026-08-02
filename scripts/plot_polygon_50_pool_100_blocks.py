#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import matplotlib.pyplot as plt

REPORTS = Path("reports")
data = json.loads((REPORTS / "polygon_50_pool_100_block_scan.json").read_text(encoding="utf-8"))
blocks = data["blocks"]
xs = [b["block"] for b in blocks]
profits = [b["best"]["netProfitUsdt"] if b.get("best") else 0.0 for b in blocks]
accepted = [1 if b.get("accepted") else 0 for b in blocks]

plt.figure(figsize=(14, 6))
plt.plot(xs, profits, marker=".")
plt.axhline(data["internalModel"]["minimumNetProfitUsdt"], linestyle="--")
plt.xlabel("Polygon block")
plt.ylabel("Best net profit, USDT")
plt.title("SYNERGY V9 — best fully costed opportunity across 50 DEX pools")
plt.tight_layout()
plt.savefig(REPORTS / "polygon_50_pool_01_best_net_profit.png", dpi=180)
plt.close()

plt.figure(figsize=(14, 3.5))
plt.step(xs, accepted, where="mid")
plt.yticks([0, 1], ["pause", "execute"])
plt.xlabel("Polygon block")
plt.title("Blocks passing full QE/QT + fees + gas acceptance gate")
plt.tight_layout()
plt.savefig(REPORTS / "polygon_50_pool_02_opportunity_blocks.png", dpi=180)
plt.close()

routes = Counter(b["best"]["route"] for b in blocks if b.get("accepted"))
if routes:
    names, counts = zip(*routes.most_common(12))
    plt.figure(figsize=(14, 7))
    plt.barh(range(len(names)), counts)
    plt.yticks(range(len(names)), names)
    plt.xlabel("Profitable blocks")
    plt.title("Most frequent profitable real DEX routes")
    plt.tight_layout()
    plt.savefig(REPORTS / "polygon_50_pool_03_top_routes.png", dpi=180)
    plt.close()

selected = data["selectedPools"][:20]
plt.figure(figsize=(14, 8))
labels = [f'{p["symbol0"]}/{p["symbol1"]} {p["kind"]}' for p in selected]
values = [p["tvlUsd"] for p in selected]
plt.barh(range(len(labels)), values)
plt.yticks(range(len(labels)), labels)
plt.xscale("log")
plt.xlabel("Estimated TVL, USD (log scale)")
plt.title("Top 20 of 50 selected real Polygon pools")
plt.tight_layout()
plt.savefig(REPORTS / "polygon_50_pool_04_selected_pool_depth.png", dpi=180)
plt.close()
