#!/usr/bin/env python3
"""Demonstrate voluntary external solver bids plus reserve-safe route profit."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simulation.orderflow_revenue import Epoch, run_epochs


if __name__ == "__main__":
    scenario = (
        Epoch((0.10, 0.30, 0.20), 50.0),
        Epoch((0.05, 0.08), 20.0),
        Epoch((1.00,), 50.0, protocol_pool_loss_usdt=60.0),
    )
    print(json.dumps(run_epochs(scenario), indent=2))
