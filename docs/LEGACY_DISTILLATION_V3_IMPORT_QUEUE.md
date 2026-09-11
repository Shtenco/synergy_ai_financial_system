# LEGACY DISTILLATION V3 — ai_financial_system

Assigned primitives:

- P038 ORACLE_PRICE — PROMOTE — oracle/manipulation/TWAP.
- P039 ORACLE_PRICE — PROMOTE — secondary oracle lineage.
- P044 RL_OPTIMIZER_POLICY — PROMOTE — policy proposal only, never self-granted execution authority.
- P049 SIMULATION_STRESS — KEEP-AS-TEST.
- P050 SIMULATION_STRESS — KEEP-AS-TEST.

Required gates: stale/manipulated price rejection, decimal normalization, OOS policy validation, deterministic seed/config hashes, and strict separation between scenario evidence and observed accounting truth.
