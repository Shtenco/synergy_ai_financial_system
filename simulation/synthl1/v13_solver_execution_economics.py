#!/usr/bin/env python3
"""Gas-aware realized-profit tax economics for SynthL1 V13.1.

A 99% tax is a ceiling, not a target.  The economically executable tax is:

    tau <= 1 - required_solver_reward / gross_arb_profit

where required_solver_reward must cover gas, risk and competition.  The protocol
still applies the atomic post-trade HardNAV gate after the actual route.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionEconomics:
    gross_profit_usd: float
    external_lp_loss_usd: float
    gas_usd: float
    solver_floor_usd: float
    executable_tax_share: float
    protocol_tax_usd: float
    solver_reward_usd: float
    protocol_hardnav_gain_usd: float


def gas_cost_usd(gas_units: int, gas_price_gwei: float, native_usd: float) -> float:
    return gas_units * gas_price_gwei * 1e-9 * native_usd


def adaptive_execution(
    gross_profit_usd: float,
    external_lp_loss_usd: float,
    gas_units: int,
    gas_price_gwei: float,
    native_usd: float,
    tax_ceiling: float = 0.99,
    gas_safety_multiple: float = 1.25,
    risk_premium_usd: float = 0.001,
) -> ExecutionEconomics:
    if not (0.0 <= tax_ceiling < 1.0):
        raise ValueError("tax_ceiling must be in [0,1)")
    if gross_profit_usd <= 0.0 or external_lp_loss_usd <= 0.0:
        raise ValueError("positive realized economics required")

    gas = gas_cost_usd(gas_units, gas_price_gwei, native_usd)
    floor = gas * gas_safety_multiple + risk_premium_usd
    if floor >= gross_profit_usd:
        executable_tax = 0.0
        solver_reward = gross_profit_usd
        protocol_tax = 0.0
    else:
        executable_tax = min(tax_ceiling, 1.0 - floor / gross_profit_usd)
        protocol_tax = gross_profit_usd * executable_tax
        solver_reward = gross_profit_usd - protocol_tax

    # Conservation for the exact EVM geometry:
    # external LP loss = protocol HardNAV gain + solver retained reward.
    protocol_gain = external_lp_loss_usd - solver_reward
    return ExecutionEconomics(
        gross_profit_usd=gross_profit_usd,
        external_lp_loss_usd=external_lp_loss_usd,
        gas_usd=gas,
        solver_floor_usd=floor,
        executable_tax_share=executable_tax,
        protocol_tax_usd=protocol_tax,
        solver_reward_usd=solver_reward,
        protocol_hardnav_gain_usd=protocol_gain,
    )


def main() -> None:
    # Exact integer-mirror values from the A=B=$1, external 10000/10100,
    # gradient=40, principal=39.8 EVM fixture.
    gross = 0.109498
    external_loss = 0.119014
    native_usd = 0.15

    print("V13.1 gas-aware solver economics")
    print("gasUnits gasGwei gasUSD solverFloor maxTax protocolGain solverReward")
    for gas_units in (200_000, 500_000, 800_000):
        for gas_gwei in (30, 100, 300):
            x = adaptive_execution(
                gross,
                external_loss,
                gas_units,
                gas_gwei,
                native_usd,
            )
            print(
                f"{gas_units:7d} {gas_gwei:7.0f} {x.gas_usd:7.5f} "
                f"{x.solver_floor_usd:10.6f} {x.executable_tax_share:7.2%} "
                f"{x.protocol_hardnav_gain_usd:+11.6f} {x.solver_reward_usd:11.6f}"
            )


if __name__ == "__main__":
    main()
