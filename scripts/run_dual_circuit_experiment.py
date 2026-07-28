#!/usr/bin/env python3
"""Print the deliberately unsafe Dual Circuit simulation with attribution."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulation.dual_circuit_solvency import experiment


if __name__ == "__main__":
    scale = 10**18
    print(json.dumps({key: value / scale for key, value in experiment().items()}, indent=2))
