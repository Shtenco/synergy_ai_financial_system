"""Autonomous Financial Organism V2.2 Monte Carlo.

Compares external MEV revenue against reserve LNAV, without counting internal
marks as realized wealth.
"""
import argparse
import random
import statistics
from dataclasses import dataclass

@dataclass
class Result:
    reserve: float
    equity: float


def run(seed: int, months: int, mev_yield: float, attack: float):
    rng = random.Random(seed)
    initial = 1_000_000.0
    reserve = initial
    minted = 0.0
    for _ in range(months):
        fee = reserve * mev_yield / 12 * rng.uniform(.4, 1.2)
        reserve += fee
        minted += fee * .25
        if rng.random() < attack:
            reserve *= rng.uniform(.85, .99)
    return Result(reserve, reserve - minted)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--worlds', type=int, default=100000)
    p.add_argument('--months', type=int, default=60)
    args = p.parse_args()
    for y in [0, .05, .10, .12, .15]:
        vals=[run(i,args.months,y,.03) for i in range(args.worlds)]
        print({
            'mev_yield': y,
            'median_reserve': round(statistics.median(x.reserve for x in vals),2),
            'p_reserve_growth': round(sum(x.reserve>1000000 for x in vals)/len(vals),6),
            'p_equity_growth': round(sum(x.equity>1000000 for x in vals)/len(vals),6),
        })

if __name__ == '__main__':
    main()
