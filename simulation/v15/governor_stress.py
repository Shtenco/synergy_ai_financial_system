#!/usr/bin/env python3
from __future__ import annotations
import random
from dataclasses import dataclass
from collections import Counter
from robust_optimizer import ActionClass, Candidate, Mode, RegimeLimits, RobustGovernor, ScenarioOutcome

@dataclass(frozen=True)
class StressSummary:
    generated:int; accepted:int; violations:int; reasons:dict

def run_stress(n:int=10000,seed:int=42)->StressSummary:
    rng=random.Random(seed)
    gov=RobustGovernor(RegimeLimits(min_risk_assets=50,max_asset_concentration=.80,min_robust_gain=.01))
    reasons=Counter(); accepted=[]
    for i in range(n):
        nominal=rng.uniform(-.1,.5); cov=rng.uniform(1.0,1.8); sts=rng.uniform(1.0,1.8); risk=rng.uniform(20,150); conc=rng.uniform(.35,.95)
        outcomes=[]
        for name,gd,cd,sd,rd,qd in [('base',0,0,0,1,0),('liq',rng.uniform(0,.25),rng.uniform(0,.15),rng.uniform(0,.2),rng.uniform(.8,1),rng.uniform(0,.05)),('depeg',rng.uniform(0,.35),rng.uniform(0,.2),rng.uniform(0,.25),rng.uniform(.7,1),rng.uniform(0,.08))]:
            outcomes.append(ScenarioOutcome(name,nominal-gd,max(0,cov-cd),max(0,sts-sd),risk*rd,min(1,conc+qd)))
        c=Candidate(str(i),ActionClass.EXPAND,nominal,rng.uniform(-.1,.2),rng.uniform(0,.03),rng.uniform(0,.03),rng.uniform(0,.02),rng.uniform(1,200),1.4,1.4,100,.5,tuple(outcomes))
        d=gov.evaluate(c,Mode.GREEN)
        if d.accepted: accepted.append(c)
        else: reasons[d.reason]+=1
    violations=sum(1 for c in accepted if c.robust_gain<.01 or c.post_min_coverage<1.3 or c.post_min_sts<1.3 or c.post_min_risk_assets<50 or c.post_max_concentration>.8)
    return StressSummary(n,len(accepted),violations,dict(reasons))

def main():
    s=run_stress();print('generated',s.generated,'accepted',s.accepted,'violations',s.violations);print('reasons',sorted(s.reasons.items(),key=lambda x:-x[1]))
if __name__=='__main__':main()
