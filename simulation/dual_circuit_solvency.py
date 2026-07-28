"""Solvency-first accounting for a Polygon ↔ controlled-L1 bridge circuit.

Internal ledger prices are deliberately excluded from external LNAV. A bridge
withdrawal can pay POL only from escrowed/reserve POL or an external inflow.
"""

from dataclasses import dataclass, replace

BPS = 10_000


@dataclass(frozen=True)
class Circuit:
    wallet_pol: int
    bridge_reserve_pol: int = 0
    synthetic_pol: int = 0
    polygon_fees_pol: int = 0
    external_revenue_pol: int = 0
    privileged_extraction_pol: int = 0

    @property
    def external_lnav(self) -> int:
        return self.wallet_pol + self.bridge_reserve_pol

    @property
    def bridge_surplus(self) -> int:
        return self.bridge_reserve_pol - self.synthetic_pol

    def marked_lnav(self, synthetic_price_bps: int) -> int:
        """Unsafe dashboard valuation used to expose mark-to-model inflation."""
        return self.external_lnav + self.synthetic_pol * synthetic_price_bps // BPS

    def bridge_in(self, amount: int, gas: int = 0) -> "Circuit":
        if amount <= 0 or amount + gas > self.wallet_pol:
            raise ValueError("insufficient Polygon POL")
        return replace(
            self,
            wallet_pol=self.wallet_pol - amount - gas,
            bridge_reserve_pol=self.bridge_reserve_pol + amount,
            synthetic_pol=self.synthetic_pol + amount,
            polygon_fees_pol=self.polygon_fees_pol + gas,
        )

    def internal_reprice(self, multiplier_bps: int) -> "Circuit":
        """A controlled ledger quote changes no externally redeemable asset."""
        if multiplier_bps <= 0:
            raise ValueError("invalid price")
        return self

    def unbacked_qe(self, amount: int) -> "Circuit":
        if amount <= 0:
            raise ValueError("invalid QE")
        return replace(self, synthetic_pol=self.synthetic_pol + amount)

    def bridge_out(self, amount: int, gas: int = 0) -> "Circuit":
        if amount > self.synthetic_pol:
            raise ValueError("insufficient synthetic balance")
        if amount > self.bridge_reserve_pol:
            raise ValueError("insolvent bridge withdrawal")
        return replace(
            self,
            wallet_pol=self.wallet_pol + amount - gas,
            bridge_reserve_pol=self.bridge_reserve_pol - amount,
            synthetic_pol=self.synthetic_pol - amount,
            polygon_fees_pol=self.polygon_fees_pol + gas,
        )

    def quickswap_round_trip(self, amount: int, gas: int, fee_bps: int = 30) -> "Circuit":
        """Best-case zero-slippage round trip: only fees and gas remain."""
        if amount + gas > self.wallet_pol:
            raise ValueError("insufficient Polygon POL")
        after_buy = amount * (BPS - fee_bps) // BPS
        after_sell = after_buy * (BPS - fee_bps) // BPS
        loss = amount - after_sell + gas
        return replace(
            self,
            wallet_pol=self.wallet_pol - loss,
            polygon_fees_pol=self.polygon_fees_pol + loss,
        )

    def receive_external_revenue(self, amount: int) -> "Circuit":
        """Explicit counterparty/yield inflow—the only new external value here."""
        if amount <= 0:
            raise ValueError("invalid revenue")
        return replace(
            self,
            wallet_pol=self.wallet_pol + amount,
            external_revenue_pol=self.external_revenue_pol + amount,
        )

    def unsafe_privileged_extract(self, amount: int) -> "Circuit":
        """Simulate privileged reserve drainage without pretending it is profit."""
        if amount <= 0 or amount > self.bridge_reserve_pol:
            raise ValueError("insufficient bridge reserve")
        return replace(
            self,
            wallet_pol=self.wallet_pol + amount,
            bridge_reserve_pol=self.bridge_reserve_pol - amount,
            privileged_extraction_pol=self.privileged_extraction_pol + amount,
        )

    def external_buyer_inflow(self, amount: int) -> "Circuit":
        """Model public buyers: system LNAV rises by their real transferred POL."""
        return self.receive_external_revenue(amount)


def experiment() -> dict[str, int]:
    """Run the proposed unsafe mechanisms and attribute every apparent gain."""
    pol = 10**18
    initial = Circuit(wallet_pol=100 * pol)
    backed = initial.bridge_in(60 * pol)
    qe = backed.unbacked_qe(180 * pol)  # 4x synthetic supply versus backing
    marked = qe.marked_lnav(40_000)
    extracted = qe.unsafe_privileged_extract(60 * pol)
    pumped = extracted.quickswap_round_trip(20 * pol, gas=pol // 100)
    with_buyers = pumped.external_buyer_inflow(25 * pol)
    return {
        "initial_external_lnav": initial.external_lnav,
        "marked_lnav_after_4x_reprice": marked,
        "external_lnav_after_4x_reprice": qe.external_lnav,
        "external_lnav_after_privileged_extract": extracted.external_lnav,
        "bridge_surplus_after_privileged_extract": extracted.bridge_surplus,
        "external_lnav_after_quickswap_pump": pumped.external_lnav,
        "external_lnav_after_external_buyers": with_buyers.external_lnav,
        "external_buyer_inflow": with_buyers.external_revenue_pol,
        "polygon_fees_and_roundtrip_loss": pumped.polygon_fees_pol,
    }
