import json
from pathlib import Path
p=Path('reports/synergy_atomic_qe_qt_v11_polygon_fork.json')
d=json.loads(p.read_text(encoding='utf-8'))
a=d.get('assertions',{});s=d.get('success',{})
checks={
 'fork_pass':d.get('pass') is True,
 'no_external_flow_no_cycle':a.get('noExternalFlowNoCycle') is True,
 'replay_rejected':a.get('replayRejected') is True,
 'mev_atomic_rollback':a.get('mevAdverseMoveAtomicRollback') is True,
 'unauthorized_rejected':a.get('unauthorizedRejected') is True,
 'temporary_supply_closed':s.get('temporaryOutstandingZero') is True and s.get('totalSupplyClosed') is True,
 'positive_after_gas':s.get('consolidatedTokenProfitUsdt',0)>s.get('gasUsdt',10**99),
 'lp_liquid_nonnegative':s.get('lpLiquidGainUsdt',-1)>=0,
 'k_non_decreasing':s.get('kGrowth',0)>=1.0,
 'dust_bounded':s.get('syntheticDustRaw',999)<=2,
}
verdict={'verdict':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'fork':d}
Path('reports/synergy_atomic_qe_qt_v11_verdict.json').write_text(json.dumps(verdict,indent=2),encoding='utf-8')
print(json.dumps(verdict,indent=2))
if verdict['verdict']!='PASS': raise SystemExit(1)
