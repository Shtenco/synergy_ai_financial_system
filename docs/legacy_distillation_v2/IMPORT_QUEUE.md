# LEGACY DISTILLATION V2 — Import Queue

Canonical owner: `Shtenco/ai_financial_system`

Nothing in this queue is auto-promoted to production. Every mechanism must pass the listed gate in this repository authority boundary.

| Priority | ID | Family | Action | Occurrences | Test gate | Representative |
|---|---|---|---|---:|---|---|
| P0_PROMOTE_WITH_GATE | M115 | ORACLE_PRICE | PROMOTION_CANDIDATE | 140 | `oracle_staleness_manipulation` | getTWAP |
| P1_PROMOTE_WITH_GATE | M116 | ORACLE_PRICE | PROMOTION_CANDIDATE | 55 | `oracle_staleness_manipulation` | needsUpdate |
| P1_PROMOTE_WITH_GATE | M117 | ORACLE_PRICE | PROMOTION_CANDIDATE | 47 | `oracle_staleness_manipulation` | QEEngine |
| P1_R&D | M156 | SIMULATION_STRESS | R_AND_D_WITH_GATE | 81 | `falsification_reproducibility` | Order |
| P1_R&D | M157 | SIMULATION_STRESS | R_AND_D_WITH_GATE | 73 | `falsification_reproducibility` | __init__ |
| P1_PROMOTE_WITH_GATE | M118 | ORACLE_PRICE | PROMOTION_CANDIDATE | 26 | `oracle_staleness_manipulation` | constructor |
| P1_R&D | M158 | SIMULATION_STRESS | R_AND_D_WITH_GATE | 52 | `falsification_reproducibility` | main |
| P1_R&D | M159 | SIMULATION_STRESS | R_AND_D_WITH_GATE | 37 | `falsification_reproducibility` | recalc |
| P1_PROMOTE_WITH_GATE | M119 | ORACLE_PRICE | PROMOTION_CANDIDATE | 16 | `oracle_staleness_manipulation` | _renounceDeployerRoles |
| P1_PROMOTE_WITH_GATE | M120 | ORACLE_PRICE | PROMOTION_CANDIDATE | 15 | `oracle_staleness_manipulation` | allAddresses |
| P1_PROMOTE_WITH_GATE | M121 | ORACLE_PRICE | PROMOTION_CANDIDATE | 13 | `oracle_staleness_manipulation` | tick |
| P1_R&D | M160 | SIMULATION_STRESS | R_AND_D_WITH_GATE | 26 | `falsification_reproducibility` | mode_seed |
| P1_PROMOTE_WITH_GATE | M140 | RL_OPTIMIZER_POLICY | PROMOTION_CANDIDATE | 9 | `oos_constraints_and_authority` | _rl_optimize |
| P1_PROMOTE_WITH_GATE | M141 | RL_OPTIMIZER_POLICY | PROMOTION_CANDIDATE | 8 | `oos_constraints_and_authority` | decide |
| P1_R&D | M161 | SIMULATION_STRESS | R_AND_D_WITH_GATE | 13 | `falsification_reproducibility` | run_comparison |
