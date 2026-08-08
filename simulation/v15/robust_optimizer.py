#!/usr/bin/env python3
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from math import inf
from typing import Iterable, Optional, Tuple

class Mode(str, Enum):
    GREEN="GREEN"; YELLOW="YELLOW"; ORANGE="ORANGE"; RED="RED"
class ActionClass(str, Enum):
    EXPAND="EXPAND"; NEUTRAL="NEUTRAL"; REDUCE="REDUCE"; RESTORE="RESTORE"

@dataclass(frozen=True)
class RegimeLimits:
    min_hard_nav: float=0.0
    min_risk_assets: float=0.0
    green_coverage: float=1.30
    yellow_coverage: float=1.15
    orange_coverage: float=1.05
    green_sts: float=1.30
    yellow_sts: float=1.15
    orange_sts: float=1.05
    max_asset_concentration: float=0.80
    min_robust_gain: float=0.0
    max_defensive_loss: float=0.02
    def __post_init__(self):
        if not (self.green_coverage>self.yellow_coverage>self.orange_coverage>1): raise ValueError("bad coverage")
        if not (self.green_sts>self.yellow_sts>self.orange_sts>1): raise ValueError("bad sts")
        if not (0<self.max_asset_concentration<=1): raise ValueError("bad concentration")

@dataclass(frozen=True)
class ScenarioOutcome:
    name: str
    delta_hard_nav: float
    post_coverage: float
    post_sts: float
    post_risk_assets: float
    post_max_concentration: float

@dataclass(frozen=True)
class Candidate:
    name: str
    action_class: ActionClass
    nominal_delta_hard_nav: float
    no_gradient_delta_hard_nav: float
    oracle_uncertainty: float
    model_uncertainty: float
    system_cost: float
    hard_turnover: float
    pre_coverage: float
    pre_sts: float
    pre_risk_assets: float
    pre_max_concentration: float
    outcomes: Tuple[ScenarioOutcome,...]
    supply_ok: bool=True
    accounting_ok: bool=True
    atomic_qe_ok: bool=True
    solver_reward_ok: bool=True
    @property
    def uncertainty_cost(self): return self.oracle_uncertainty+self.model_uncertainty+self.system_cost
    @property
    def worst_case_raw_gain(self): return min(o.delta_hard_nav for o in self.outcomes)
    @property
    def robust_gain(self): return self.worst_case_raw_gain-self.uncertainty_cost
    @property
    def initiated_alpha(self): return self.nominal_delta_hard_nav-max(0.0,self.no_gradient_delta_hard_nav)
    @property
    def hard_capital_efficiency(self):
        if self.hard_turnover==0: return inf if self.robust_gain>0 else 0.0
        return self.robust_gain/self.hard_turnover
    @property
    def post_min_coverage(self): return min(o.post_coverage for o in self.outcomes)
    @property
    def post_min_sts(self): return min(o.post_sts for o in self.outcomes)
    @property
    def post_min_risk_assets(self): return min(o.post_risk_assets for o in self.outcomes)
    @property
    def post_max_concentration(self): return max(o.post_max_concentration for o in self.outcomes)

@dataclass(frozen=True)
class Decision:
    accepted: bool
    reason: str
    candidate: Optional[Candidate]=None

class RobustGovernor:
    def __init__(self, limits: RegimeLimits): self.limits=limits
    def floors(self, mode):
        l=self.limits
        if mode==Mode.GREEN:return l.green_coverage,l.green_sts
        if mode==Mode.YELLOW:return l.yellow_coverage,l.yellow_sts
        if mode==Mode.ORANGE:return l.orange_coverage,l.orange_sts
        return inf,inf
    def evaluate(self,c,mode):
        l=self.limits
        if not (c.supply_ok and c.accounting_ok and c.atomic_qe_ok and c.solver_reward_ok): return Decision(False,"invariant-failure",c)
        if mode==Mode.RED and c.action_class not in (ActionClass.REDUCE,ActionClass.RESTORE): return Decision(False,"red-only-defensive",c)
        if mode==Mode.ORANGE and c.action_class==ActionClass.EXPAND:return Decision(False,"orange-no-expansion",c)
        if c.post_min_risk_assets<l.min_risk_assets:return Decision(False,"absolute-risk-capital-floor",c)
        if c.post_max_concentration>l.max_asset_concentration:return Decision(False,"concentration-limit",c)
        if c.action_class==ActionClass.EXPAND:
            cov,sts=self.floors(mode)
            if c.post_min_coverage<cov:return Decision(False,"coverage-floor",c)
            if c.post_min_sts<sts:return Decision(False,"sts-floor",c)
            if c.robust_gain<l.min_robust_gain:return Decision(False,"robust-gain-floor",c)
            return Decision(True,"safe-expansion",c)
        if c.action_class==ActionClass.NEUTRAL:
            if c.robust_gain<0:return Decision(False,"neutral-action-loss",c)
            if c.post_min_coverage+1e-12<c.pre_coverage or c.post_min_sts+1e-12<c.pre_sts:return Decision(False,"neutral-worsens-solvency",c)
            return Decision(True,"safe-neutral",c)
        if c.robust_gain<-l.max_defensive_loss:return Decision(False,"defensive-loss-budget",c)
        nonworse=c.post_min_coverage+1e-12>=c.pre_coverage and c.post_min_sts+1e-12>=c.pre_sts
        improved=c.post_min_coverage>c.pre_coverage+1e-12 or c.post_min_sts>c.pre_sts+1e-12
        if c.action_class==ActionClass.REDUCE and not(nonworse and improved):return Decision(False,"reduce-must-improve-solvency",c)
        if c.action_class==ActionClass.RESTORE and not nonworse:return Decision(False,"restore-must-not-worsen",c)
        return Decision(True,"safe-defensive",c)
    def _buffer(self,c,mode):
        cov,sts=self.floors(mode)
        if cov==inf:return -inf
        return min(c.post_min_coverage/cov-1,c.post_min_sts/sts-1,self.limits.max_asset_concentration/max(c.post_max_concentration,1e-18)-1)
    def rank_key(self,c,mode): return (c.robust_gain,self._buffer(c,mode),c.hard_capital_efficiency,c.initiated_alpha,-c.hard_turnover)
    def choose(self,candidates:Iterable[Candidate],mode):
        safe=[c for c in candidates if self.evaluate(c,mode).accepted]
        if not safe:return Decision(False,"HOLD")
        b=max(safe,key=lambda c:self.rank_key(c,mode));return Decision(True,"EXECUTE",b)

def capture_efficiency(protocol_tax,gross): return 0.0 if gross<=0 else protocol_tax/gross
def edge_activation_ratio(with_gradient,no_gradient):
    if with_gradient<=0:return 0.0
    return (with_gradient-max(0.0,no_gradient))/with_gradient
