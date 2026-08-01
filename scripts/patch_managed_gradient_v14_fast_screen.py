#!/usr/bin/env python3
"""Replace expensive per-candidate screening binary search with a safe marginal upper bound.

The strict bracketed exact-input search remains mandatory for every final exact
candidate. This patch changes only ranking/screening and cannot make a cycle pass.
"""
from pathlib import Path

path = Path("scripts/scan_managed_gradient_v14_stateful.js")
text = path.read_text(encoding="utf-8")
old = '''              const restoreInputScreenRaw = screeningInputForTarget(
                routePair.restore,
                internal.extractedRaw,
                stateMap,
                TOKENS[destination].decimals
              );
              if (restoreInputScreenRaw === null) continue;
'''
new = '''              // Initial fee-adjusted marginal rate is an optimistic upper bound
              // on reverse-route output. Therefore target / marginalRate is a
              // lower bound on restoration input and produces an optimistic
              // profit upper bound suitable only for screening. Acceptance still
              // requires exactInputForTarget() below.
              const extractedScreenHuman = rawToNumber(
                internal.extractedRaw,
                TOKENS[source].decimals
              );
              const restoreInputScreenHuman =
                extractedScreenHuman / routePair.restore.approxMultiplier;
              const restoreInputScreenRaw = humanToRaw(
                restoreInputScreenHuman,
                TOKENS[destination].decimals
              );
              if (restoreInputScreenRaw <= 0n) continue;
'''
if old not in text:
    raise SystemExit("V14 screening restoration block not found")
text = text.replace(old, new, 1)
path.write_text(text, encoding="utf-8")
