#!/usr/bin/env python3
"""Deterministic economics for the V15.4 fixed 5 WPOL flash stress.

This model answers a narrow question: for ten atomic flash cycles, does the
transaction revert or leave strict external profit after an exact 5 WPOL fee per
cycle? It does not assume or invent a live market opportunity.
"""
from __future__ import annotations

from decimal import Decimal, getcontext
import json
from pathlib import Path

getcontext().prec = 50

REPORT = Path("reports/v15_4_atomic_flashloan_5pol_10x_economics.json")
FEE_WPOL = Decimal("5")
CYCLES = 10
REINVESTMENT_SHARE = Decimal("0.80")
STRICT_NET_EDGE_BPS = Decimal("2.685148")
BPS = Decimal("10000")


def evaluate_cycle(principal: Decimal, gross_route_profit: Decimal) -> dict[str, object]:
    if principal <= 0:
        raise ValueError("principal must be positive")
    if gross_route_profit < FEE_WPOL:
        return {
            "status": "ATOMIC_REVERT_FLASH_FEE_NOT_COVERED",
            "principalWpol": str(principal),
            "grossRouteProfitWpol": str(gross_route_profit),
            "flashFeeWpol": str(FEE_WPOL),
            "netProtocolProfitWpol": "0",
            "netEdgeBps": "0",
            "countedRevenueWpol": "0",
            "reinvestedWpol": "0",
        }

    net = gross_route_profit - FEE_WPOL
    edge_bps = net / principal * BPS
    if edge_bps < STRICT_NET_EDGE_BPS:
        return {
            "status": "ATOMIC_REVERT_STRICT_EDGE_NOT_CLEARED",
            "principalWpol": str(principal),
            "grossRouteProfitWpol": str(gross_route_profit),
            "flashFeeWpol": str(FEE_WPOL),
            "netProtocolProfitWpol": str(net),
            "netEdgeBps": str(edge_bps),
            "countedRevenueWpol": "0",
            "reinvestedWpol": "0",
        }

    reinvested = net * REINVESTMENT_SHARE
    retained = net - reinvested
    return {
        "status": "STRICT_NET_EDGE_PASS",
        "principalWpol": str(principal),
        "grossRouteProfitWpol": str(gross_route_profit),
        "flashFeeWpol": str(FEE_WPOL),
        "netProtocolProfitWpol": str(net),
        "netEdgeBps": str(edge_bps),
        "countedRevenueWpol": str(net),
        "reinvestedWpol": str(reinvested),
        "retainedWpol": str(retained),
    }


def evaluate_atomic_batch(principal: Decimal, gross_profits: list[Decimal]) -> dict[str, object]:
    if len(gross_profits) != CYCLES:
        raise ValueError(f"exactly {CYCLES} cycle outcomes are required")
    rows = [evaluate_cycle(principal, gross) for gross in gross_profits]
    first_failure = next((index for index, row in enumerate(rows) if row["status"] != "STRICT_NET_EDGE_PASS"), None)
    if first_failure is not None:
        return {
            "status": "ATOMIC_BATCH_REVERT",
            "failedCycleOneBased": first_failure + 1,
            "failureStatus": rows[first_failure]["status"],
            "attemptedRows": rows,
            "completedCycles": 0,
            "cumulativeFlashFeesWpol": "0",
            "countedRevenueWpol": "0",
            "reinvestedWpol": "0",
            "retainedWpol": "0",
            "reason": "An EVM revert on any cycle reverses all earlier transfers and state changes in the same ten-cycle transaction.",
        }

    counted = sum(Decimal(str(row["countedRevenueWpol"])) for row in rows)
    reinvested = counted * REINVESTMENT_SHARE
    retained = counted - reinvested
    return {
        "status": "ATOMIC_BATCH_PASS",
        "completedCycles": CYCLES,
        "cumulativeGrossRouteProfitWpol": str(sum(gross_profits)),
        "cumulativeFlashFeesWpol": str(FEE_WPOL * CYCLES),
        "countedRevenueWpol": str(counted),
        "reinvestedWpol": str(reinvested),
        "retainedWpol": str(retained),
        "rows": rows,
    }


def minimum_gross_profit(principal: Decimal) -> Decimal:
    return FEE_WPOL + principal * STRICT_NET_EDGE_BPS / BPS


def minimum_principal_for_gross_edge(gross_edge_bps: Decimal) -> Decimal | None:
    excess_edge = gross_edge_bps - STRICT_NET_EDGE_BPS
    if excess_edge <= 0:
        return None
    return FEE_WPOL / (excess_edge / BPS)


def main() -> None:
    principal = Decimal("1000")
    success = evaluate_atomic_batch(principal, [Decimal("6")] * CYCLES)
    tenth_cycle_failure = evaluate_atomic_batch(
        principal,
        [Decimal("6")] * 9 + [Decimal("5.2")],
    )
    fee_failure = evaluate_atomic_batch(principal, [Decimal("4.99")] * CYCLES)
    exact_boundary = evaluate_cycle(principal, minimum_gross_profit(principal))

    capital_frontier = []
    for gross_edge in map(Decimal, ("3", "4", "5", "7.5", "10", "20", "50", "100")):
        minimum_principal = minimum_principal_for_gross_edge(gross_edge)
        capital_frontier.append({
            "grossRouteEdgeBpsBeforeFixedFee": str(gross_edge),
            "minimumPrincipalWpolToRetainStrict2685148Bps": (
                str(minimum_principal) if minimum_principal is not None else None
            ),
        })

    result = {
        "model": "SYNERGY V15.4 atomic fixed 5 WPOL flash fee x10",
        "policy": {
            "fixedFlashFeeWpolPerCycle": str(FEE_WPOL),
            "cycles": CYCLES,
            "strictNetEdgeBpsAfterAllCosts": str(STRICT_NET_EDGE_BPS),
            "reinvestmentShare": str(REINVESTMENT_SHARE),
            "countOnlyRealizedNetProfit": True,
            "failedAtomicBatchCountsZeroRevenue": True,
        },
        "principal1000Wpol": {
            "minimumGrossRouteProfitWpolPerCycle": str(minimum_gross_profit(principal)),
            "feeOnlyBreakEvenGrossProfitWpol": str(FEE_WPOL),
            "strictNetProfitFloorWpol": str(principal * STRICT_NET_EDGE_BPS / BPS),
            "allTenCyclesEarn6WpolGross": success,
            "nineGoodTenthBelowEdge": tenth_cycle_failure,
            "feeNotCovered": fee_failure,
            "exactBoundary": exact_boundary,
        },
        "capitalFrontier": capital_frontier,
        "interpretation": [
            "Below 5 WPOL gross route profit the lender cannot receive principal plus fee, so the flash transaction reverts.",
            "Between 5 and 5.2685148 WPOL gross on a 1,000 WPOL principal, repayment is possible but the strict 2.685148 bps post-fee gate fails, so the transaction still reverts.",
            "At 6 WPOL gross, each cycle leaves 1 WPOL net, equal to 10 bps. Ten successful cycles produce 10 WPOL counted revenue, 8 WPOL reinvestment and 2 WPOL retained capital.",
            "A structural PASS proves rollback and accounting only. Live profit requires an external route that actually supplies the gross profit without protocol subsidy.",
        ],
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
