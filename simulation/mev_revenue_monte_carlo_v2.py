"""
AI Financial System - MEV Revenue Monte Carlo V2
Tests whether external solver fees create autonomous LNAV growth.
"""
import random
import statistics


def run(seed, months=60, lnav=1_000_000, mev_yield=0.12):
    random.seed(seed)
    fees = 0
    losses = 0
    for _ in range(months):
        external_mev = lnav * mev_yield / 12
        competition_noise = random.uniform(0.4, 1.2)
        fees += external_mev * competition_noise

        if random.random() < 0.03:
            losses += lnav * random.uniform(0.01, 0.08)

        if random.random() < 0.02:
            losses += lnav * random.uniform(0.02, 0.15)

        lnav += external_mev * competition_noise
        lnav -= losses
        losses = 0

    return lnav


if __name__ == '__main__':
    scenarios = [0.00,0.05,0.10,0.12,0.15]
    for y in scenarios:
        values=[run(i,mev_yield=y) for i in range(100000)]
        print({
            'mev_yield': y,
            'median': round(statistics.median(values),2),
            'survival': round(sum(v>1000000 for v in values)/len(values),4)
        })
