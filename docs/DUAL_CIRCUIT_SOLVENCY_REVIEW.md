# Sinergy Dual Circuit Omega — solvency review

## Finding

A controlled L1 price is an internal accounting mark, not an externally
redeemable asset. Raising that mark by 300–400% does not add POL to the Polygon
wallet or bridge reserve. A bridge can return only POL previously escrowed or
POL supplied by an explicitly identified external revenue source.

The proposed "one-way valve" is therefore not an autonomous value source. If
unbacked synthetic units can redeem at the controlled price, the bridge becomes
insolvent. If they cannot redeem, the quoted synthetic profit is not realizable
LNAV. Restricting bridge access to one bot changes authorization, not solvency.

## Deterministic checks

The model separates wallet POL, bridge reserve, synthetic liabilities, Polygon
fees, and external revenue. A 400% internal reprice leaves external LNAV
unchanged. A backed bridge round trip loses gas. Unbacked 4× QE produces a
negative bridge surplus and fails redemption. A zero-slippage QuickSwap round
trip loses two 0.3% fees plus gas; real slippage makes the result worse.

## Admissible autonomous policy

Only count realized external assets. Before every withdrawal or trade, require:

```text
bridgeReservePOL >= redeemableSyntheticPOL
postExternalLNAV >= preExternalLNAV + gas + riskBuffer + minProfit
```

Revenue may come from independent users' fees, independently profitable
arbitrage, or external yield. Those sources have capacity and risk limits and
cannot justify a guaranteed 25–150 POL/day target without measured order flow.

This repository does not implement artificial price pumping, privileged bridge
extraction, or accounting that labels unbacked issuance as profit. Any bridge
must use public reserve proofs, rate limits, a timelock, and an emergency pause.

## Unsafe-mechanism experiment

For research, the simulator now explicitly runs the proposed unsafe mechanisms
without deploying them: 4× unbacked QE, a 400% internal mark, privileged reserve
extraction, a zero-slippage QuickSwap self-pump, and a 25 POL public-buyer inflow.
Run `python scripts/run_dual_circuit_experiment.py`.

The 400% mark increases only reported LNAV. Privileged extraction preserves
system-wide external LNAV because it moves existing POL from bridge to wallet,
while bridge surplus falls to -240 POL. The self-pump reduces external LNAV.
The only positive external change is exactly the 25 POL transferred by public
buyers; that is counterparty-funded revenue, not autonomous creation.
