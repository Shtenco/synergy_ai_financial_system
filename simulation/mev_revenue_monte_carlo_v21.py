"""MEV Revenue Organism Test V2.1
External solver fee economy simulation.
"""
import random
import statistics


def run(seed, months=60, lnav=1_000_000, annual_fee=0.12):
    random.seed(seed)
    peak = lnav
    drawdown = 0
    for _ in range(months):
        fee = lnav * annual_fee / 12
        competition = random.uniform(0.4, 1.25)
        lnav += fee * competition

        # liquidity shocks
        if random.random() < 0.03:
            lnav *= 1-random.uniform(0.01, 0.08)
        if random.random() < 0.02:
            lnav *= 1-random.uniform(0.02, 0.15)

        peak = max(peak, lnav)
        drawdown = max(drawdown, 1-lnav/peak)

    return {"lnav": lnav, "drawdown": drawdown}


if __name__ == '__main__':
    for fee in [0, .05, .10, .12, .15]:
        r=[run(i, annual_fee=fee) for i in range(100000)]
        print({
            "annual_solver_fee":fee,
            "median_lnav":statistics.median(x['lnav'] for x in r),
            "survival":sum(x['lnav']>1000000 for x in r)/len(r),
            "max_drawdown":max(x['drawdown'] for x in r)
        })
