#!/usr/bin/env python3
"""Run the connected SYNA/SYNR graph with transfer burning disabled."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulation.graph_arbitrage import run_no_burn_experiment


if __name__ == "__main__":
    print(json.dumps(run_no_burn_experiment(), indent=2))
