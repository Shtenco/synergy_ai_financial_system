#!/usr/bin/env python3
"""Deterministic SYNA/USDT bullish-CB microcycle with strict accounting."""
from __future__ import annotations

import argparse
import csv
import json
import math
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class Config:
    initial_supply: float = 1_000_000.0
    initial_pool_tokens: float = 500_000.0
    initial_pool_usdt: float = 1.0
    owner_working_usdt: float = 1.0
    gas_budget_usdt: float = 1.0
    fee: float = 0.003
    trigger: float = 0.01
    burn_multiplier: float = 2.0
    mint_multiplier: float = 1.0
    max_burn: float = 0.08
    max_mint: float = 0.04
    sma_window: int = 20
    cooldown: int = 8
    cycles: int = 15
    blocks_per_cycle: int = 10
    gas_usdt_per_cycle: float = 0.0


class Pool:
    def __init__(self, token: float, usdt: float, fee: float):
        self.token = token
        self.usdt = usdt
        self.fee = fee
        self.fees_usdt = 0.0

    @property
    def price(self) -> float:
        if self.token <= 0:
            raise RuntimeError("ZERO_TOKEN_RESERVE")
        price = self.usdt / self.token
        if not math.isfinite(price) or price <= 0:
            raise RuntimeError("ZERO_OR_INVALID_PRICE")
        return price

    @property
    def k(self) -> float:
        return self.token * self.usdt

    def buy(self, usdt_in: float) -> tuple[float, float]:
        fee = usdt_in * self.fee
        net = usdt_in - fee
        old_k = self.k
        new_usdt = self.usdt + net
        token_out = self.token - old_k / new_usdt
        if token_out <= 0 or token_out >= self.token:
            raise RuntimeError("INVALID_BUY_OUTPUT")
        self.usdt = new_usdt
        self.token -= token_out
        self.fees_usdt += fee
        return token_out, fee

    def sell_spot_notional(self, target_usdt: float, available: float) -> tuple[float, float, float]:
        token_in = min(available, target_usdt / self.price)
        if token_in <= 0:
            return 0.0, 0.0, 0.0
        old_k = self.k
        gross = self.usdt - old_k / (self.token + token_in)
        fee = gross * self.fee
        net = gross - fee
        if net <= 0 or gross >= self.usdt:
            raise RuntimeError("INVALID_SELL_OUTPUT")
        self.token += token_in
        self.usdt -= gross
        self.fees_usdt += fee
        return net, fee, token_in


class Economy:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.pool = Pool(cfg.initial_pool_tokens, cfg.initial_pool_usdt, cfg.fee)
        self.supply = cfg.initial_supply
        self.circulating = cfg.initial_supply - cfg.initial_pool_tokens
        self.owner_usdt = cfg.owner_working_usdt
        self.owner_token = 0.0
        self.treasury_usdt = 0.0
        self.gas_usdt = cfg.gas_budget_usdt
        self.gas_spent = 0.0
        self.burned = 0.0
        self.minted = 0.0
        self.burn_events = 0
        self.mint_events = 0
        self.blocked_mints = 0
        self.lp_usdt_contribution = 0.0

    @property
    def hard_nav(self) -> float:
        return self.pool.usdt + self.owner_usdt + self.treasury_usdt + self.gas_usdt

    @property
    def spot_nav(self) -> float:
        return self.hard_nav + (self.pool.token + self.owner_token) * self.pool.price

    @property
    def gross_tvl(self) -> float:
        return self.pool.usdt + self.pool.token * self.pool.price

    def burn_global(self, fraction: float) -> float:
        fraction = min(max(fraction, 0.0), self.cfg.max_burn)
        factor = 1.0 - fraction
        before = self.supply
        self.supply *= factor
        self.circulating *= factor
        self.pool.token *= factor
        self.owner_token *= factor
        amount = before - self.supply
        self.burned += amount
        self.burn_events += 1
        return amount

    def mint_add_lp(self, fraction: float) -> dict[str, float]:
        fraction = min(max(fraction, 0.0), self.cfg.max_mint)
        requested_token = self.supply * fraction
        requested_usdt = requested_token * self.pool.price
        paired_usdt = min(self.treasury_usdt, requested_usdt)
        if paired_usdt <= 1e-18:
            self.blocked_mints += 1
            return {"minted": 0.0, "paired_usdt": 0.0, "requested_usdt": requested_usdt}
        minted = paired_usdt / self.pool.price
        self.supply += minted
        self.minted += minted
        self.pool.token += minted
        self.pool.usdt += paired_usdt
        self.treasury_usdt -= paired_usdt
        self.lp_usdt_contribution += paired_usdt
        self.mint_events += 1
        return {"minted": minted, "paired_usdt": paired_usdt, "requested_usdt": requested_usdt}


class CentralBank:
    def __init__(self, economy: Economy):
        self.e = economy
        self.prices = deque([economy.pool.price] * economy.cfg.sma_window, maxlen=economy.cfg.sma_window)
        self.cooldown = 0

    def step(self) -> dict[str, float | str]:
        cfg = self.e.cfg
        reference = sum(self.prices) / len(self.prices)
        deviation = self.e.pool.price / reference - 1.0
        action = "NONE"
        data: dict[str, float | str] = {"reference": reference, "deviation": deviation}
        if self.cooldown > 0:
            self.cooldown -= 1
        elif deviation <= -cfg.trigger:
            fraction = min(cfg.max_burn, -deviation * cfg.burn_multiplier)
            data.update({"fraction": fraction, "amount": self.e.burn_global(fraction)})
            action = "GLOBAL_REBASE_DOWN"
            self.cooldown = cfg.cooldown
        elif deviation >= cfg.trigger:
            fraction = min(cfg.max_mint, deviation * cfg.mint_multiplier)
            data.update({"fraction": fraction, **self.e.mint_add_lp(fraction)})
            action = "MINT_ADD_LP" if data["minted"] else "MINT_BLOCKED"
            self.cooldown = cfg.cooldown
        data["action"] = action
        self.prices.append(self.e.pool.price)
        return data


class Experiment:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.e = Economy(cfg)
        self.cb = CentralBank(self.e)
        self.rows: list[dict[str, object]] = []
        self.trades = 0
        self.start_hard = self.e.hard_nav
        self.start_spot = self.e.spot_nav
        self.start_tvl = self.e.gross_tvl
        self.start_pool_usdt = self.e.pool.usdt

    def record(self, cycle: int, event: str, **extra: object) -> None:
        self.rows.append({
            "cycle": cycle,
            "block": cycle * self.cfg.blocks_per_cycle,
            "trade": self.trades,
            "event": event,
            "price": self.e.pool.price,
            "pool_token": self.e.pool.token,
            "pool_usdt": self.e.pool.usdt,
            "owner_token": self.e.owner_token,
            "owner_usdt": self.e.owner_usdt,
            "treasury_usdt": self.e.treasury_usdt,
            "gas_usdt": self.e.gas_usdt,
            "supply": self.e.supply,
            "hard_nav": self.e.hard_nav,
            "spot_nav": self.e.spot_nav,
            "gross_tvl": self.e.gross_tvl,
            **extra,
        })

    def run(self) -> dict[str, object]:
        self.record(0, "INITIAL")
        completed = 0
        for cycle in range(1, self.cfg.cycles + 1):
            if self.e.gas_usdt < self.cfg.gas_usdt_per_cycle:
                self.record(cycle, "STOP_GAS")
                break
            self.e.gas_usdt -= self.cfg.gas_usdt_per_cycle
            self.e.gas_spent += self.cfg.gas_usdt_per_cycle
            for leg in range(2):
                if self.e.owner_usdt < 0.1:
                    self.record(cycle, "BUY_BLOCKED")
                    break
                self.e.owner_usdt -= 0.1
                token_out, fee = self.e.pool.buy(0.1)
                self.e.owner_token += token_out
                self.e.treasury_usdt += fee
                self.trades += 1
                self.record(cycle, "BUY", leg=leg + 1, fee=fee, token_out=token_out, **self.cb.step())
            for leg in range(5):
                usdt_out, fee, token_in = self.e.pool.sell_spot_notional(0.04, self.e.owner_token)
                if token_in <= 0:
                    self.record(cycle, "SELL_BLOCKED")
                    break
                self.e.owner_token -= token_in
                self.e.owner_usdt += usdt_out
                self.e.treasury_usdt += fee
                self.trades += 1
                self.record(cycle, "SELL", leg=leg + 1, fee=fee, token_in=token_in, usdt_out=usdt_out, **self.cb.step())
            completed = cycle
            self.record(cycle, "CYCLE_END")

        hard_delta = self.e.hard_nav - self.start_hard
        pool_usdt_delta = self.e.pool.usdt - self.start_pool_usdt
        return {
            "scenario": "SYNERGY_BULLISH_CB_MICROCYCLE_V1",
            "config": asdict(self.cfg),
            "completed_cycles": completed,
            "covered_blocks": completed * self.cfg.blocks_per_cycle,
            "trades": self.trades,
            "price_multiple": self.e.pool.price / self.rows[0]["price"],
            "supply_change_pct": (self.e.supply / self.cfg.initial_supply - 1.0) * 100.0,
            "burned": self.e.burned,
            "minted": self.e.minted,
            "burn_events": self.e.burn_events,
            "mint_events": self.e.mint_events,
            "blocked_mints": self.e.blocked_mints,
            "gross_tvl_change_usdt": self.e.gross_tvl - self.start_tvl,
            "pool_usdt_change_usdt": pool_usdt_delta,
            "internal_owner_transfer_to_pool_usdt": pool_usdt_delta,
            "organic_external_tvl_change_usdt": 0.0,
            "internal_fee_turnover_usdt": self.e.pool.fees_usdt,
            "gas_spent_usdt": self.e.gas_spent,
            "hard_nav_change_usdt": hard_delta,
            "spot_nav_change_usdt": self.e.spot_nav - self.start_spot,
            "strict_verdict": "PASS_EXTERNAL_VALUE" if hard_delta > 0 else "FAIL_NO_EXTERNAL_VALUE",
            "interpretation": "Price and gross TVL can rise from rebasing and internal capital relocation; self-trading fees are circular and hard NAV changes only by external costs.",
        }


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cycles", type=int, default=15)
    parser.add_argument("--gas-usdt-per-cycle", type=float, default=0.0)
    parser.add_argument("--outdir", type=Path, default=Path("reports/bullish_cb_v1"))
    args = parser.parse_args()
    exp = Experiment(Config(cycles=args.cycles, gas_usdt_per_cycle=args.gas_usdt_per_cycle))
    result = exp.run()
    args.outdir.mkdir(parents=True, exist_ok=True)
    (args.outdir / "summary.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    write_csv(args.outdir / "history.csv", exp.rows)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
