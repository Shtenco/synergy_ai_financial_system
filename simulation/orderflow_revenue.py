"""Voluntary MEV solver-auction revenue with protocol reserve-floor accounting."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Epoch:
    bids_pol: tuple[float, ...]
    external_route_profit_usdt: float
    protocol_pool_loss_usdt: float = 0.0

    def settle(self) -> dict[str, float]:
        winning_bid = max(self.bids_pol, default=0.0)
        net_lnav = self.external_route_profit_usdt - self.protocol_pool_loss_usdt
        if net_lnav <= 0:
            return {"auction_revenue_pol": winning_bid, "route_profit_usdt": 0.0, "pool_loss_usdt": 0.0}
        return {"auction_revenue_pol": winning_bid, "route_profit_usdt": net_lnav,
                "pool_loss_usdt": self.protocol_pool_loss_usdt}


def run_epochs(epochs: tuple[Epoch, ...]) -> dict[str, float]:
    revenue = profit = losses = 0.0
    for epoch in epochs:
        result = epoch.settle()
        revenue += result["auction_revenue_pol"]
        profit += result["route_profit_usdt"]
        losses += result["pool_loss_usdt"]
    return {"auction_revenue_pol": revenue, "route_profit_usdt": profit, "pool_loss_usdt": losses}
