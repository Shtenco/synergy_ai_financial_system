# SHTENCO ai_financial_system

## DeFi TOP AI v3

Unified architecture:

- Flash Loan Arbitrage
- AI Central Bank
- AI Market Maker
- Value Flow Treasury
- QE and Bridge QE modules
- Economic State Oracle
- DeFi Contour Registry
- Monte Carlo internal market simulation

## Repository structure

```
contracts/          Solidity smart contracts
contracts/synthl1/  SynthL1 supply-neutral reserve-gradient / MEV engine
ai_centrobank/      AI policy and optimization engine
simulation/         Python economic simulations
solver/             External solver and market-graph configuration
docs/               Architecture and audit documents
scripts/            Deployment and testing scripts
```

## SynthL1 V13.1 — self-created reserve-gradient / HardNAV-gated MEV engine

The integrated module lives under [`contracts/synthl1/`](contracts/synthl1/README.md).
It restores the V12/V13 edge-initiation core and combines it with realized-profit MEV capture, multi-asset accounting and an atomic post-trade HardNAV gate.

Exact runtime cycle:

`source synthetic burn -> equal destination synthetic mint -> self-created graph gradient -> external searcher route -> realized-profit tax -> post-trade HardNAV check -> exact synthetic restore -> captured-quote reinvestment -> close/rotate -> repeat`.

The protocol does **not** wait for a pre-existing profitable external arbitrage before initiating the gradient. The corrected V13.1 model separates oracle marks from venue prices and shows the useful regime precisely: a supply-neutral gradient can make a small, cycle-consistent cross-venue basis executable even when the same basis is below the no-gradient multi-leg fee hurdle.

A perfectly aligned mark==venue market is a negative control. Raw solver profit created only by the protocol gradient is rejected when protocol HardNAV would fall.

Corrected deterministic reference with a sub-threshold venue vector:

- no profitable no-gradient route;
- 4 HardNAV-positive rotated gradient cycles;
- protocol HardNAV: **+0.204687 USD**;
- external LP delta: **-0.221851 USD**;
- solver reward: **+0.017164 USD**;
- conservation error approximately zero.

The earlier V13 `+1.28 USD` result based on mismatched valuation vectors has been rejected and removed from the current audit.

Managed gradient pools are 100% protocol LP-owned, reject third-party LP additions, and gate **both swap directions** through `GraphArbExecutor`. Searchers fund their own route principal. The executor taxes only realized profit and can atomically require `SystemAccounting.consolidatedHardNAV1e18()` to increase before the transaction is allowed to complete.

The existing root-level `GraphPolicy`, `GraphTreasury`, `OrderflowAuction`, `SecureFlashExecutor`, and `TimelockedMultisig` remain the outer policy/security/solver layer rather than being duplicated inside SynthL1.

Run the reference models and focused tests with:

```bash
npm run sim:synthl1:gradient
npm run sim:synthl1:v13
npm run test:synthl1
npm run test:synthl1:evm
```

The corrected audit is in [`docs/SYNTHL1_V6_RESERVE_GRADIENT_AUDIT.md`](docs/SYNTHL1_V6_RESERVE_GRADIENT_AUDIT.md).
The example external graph configuration remains in [`solver/synthl1/market-graph.example.json`](solver/synthl1/market-graph.example.json).

## Security

No private keys, seed phrases, RPC secrets or `.env` files belong in this repository.

Before any mainnet deployment:

1. Run compiler and EVM tests.
2. Run archival/fork tests.
3. Verify contracts.
4. Use a fresh deployment wallet.
5. Configure timelock, oracle/reporters, guardian and risk limits.

Status: architecture, corrected deterministic stateful simulation and integration-test stage. Fresh Solidity compiler/EVM/fork execution is still a required deployment gate.

The four-contract growth-cycle prototype and its economic limitations are
documented in [`docs/SELF_SUSTAINING_GRAPH_DESIGN.md`](docs/SELF_SUSTAINING_GRAPH_DESIGN.md).

Run the deterministic integer AMM model with:

```bash
python -m unittest tests.test_amm_growth_cycle -v
```

The connected multi-token arbitrage/QE model and results are documented in
[`docs/GRAPH_ARBITRAGE_QE_RESULTS.md`](docs/GRAPH_ARBITRAGE_QE_RESULTS.md). It
models USDT-settled routes, flash fees, AMM fees, and SYNA/SYNR transfer burns.

Run the counterfactual graph with SYNA/SYNR transfer burn disabled using
`python scripts/run_no_burn_graph_experiment.py`.

The bonded commit/reveal, vesting, fixed burn-sink, and sealed-route MEV model is
documented in [`docs/ANTI_MEV_DESIGN.md`](docs/ANTI_MEV_DESIGN.md).
The current deployment blockers and completed hardening work are tracked in
[`docs/SECURITY_AUDIT.md`](docs/SECURITY_AUDIT.md).

The voluntary external-solver auction and reserve-safe revenue attribution are
documented in [`docs/ORDERFLOW_REVENUE.md`](docs/ORDERFLOW_REVENUE.md).

After deployment, Polygon solvers can discover announcements with
`npm run solver:watch` and submit voluntary bids with `npm run solver:bid`; see
`solver/auction-manifest.example.json` for the public discovery manifest.

The two-chain bridge/QE solvency model is documented in
[`docs/DUAL_CIRCUIT_SOLVENCY_REVIEW.md`](docs/DUAL_CIRCUIT_SOLVENCY_REVIEW.md).
It treats controlled L1 prices as internal marks and accepts only realized
Polygon assets as LNAV.

Run the explicit unsafe-mechanism experiment (simulation only) with
`python scripts/run_dual_circuit_experiment.py`.

For the mandatory archival Polygon fork gate, configure `POLYGON_RPC_URL` and
`FORK_BLOCK_NUMBER=60000000`, install the pinned npm dependencies, and run
`npm run compile && npm run fork:preflight`. Mainnet deployment is intentionally not automated.

## Read-only Polygon balance check

The repository includes a dependency-free, read-only diagnostic for the current
SYNA and SYNR contracts. It never accepts or uses a private key:

```bash
POLYGON_RPC_URL=https://your-provider.example \
  python scripts/check_polygon_balances.py
```

If an HTTPS inspection gateway requires its own CA certificate, save the PEM
outside the repository and pass it explicitly:

```bash
POLYGON_RPC_URL=https://your-provider.example \
POLYGON_CA_CERT=/secure/path/gateway-ca.pem \
  python scripts/check_polygon_balances.py
```

The certificate only establishes TLS trust. It cannot override a proxy policy
that rejects the HTTP `CONNECT` request before the TLS handshake.

### `CONNECT` returned HTTP 403

Do **not** disable TLS verification. Options such as `curl -k` take effect only
after the proxy has accepted `CONNECT`; consequently, they cannot resolve this
error and would make successful connections vulnerable to interception.

The safe remedies are operational rather than changes to this script:

1. Ask the network administrator to allowlist the exact Polygon RPC hostname
   and TCP port 443 in the outbound proxy policy.
2. Use an organization-approved Polygon RPC provider already permitted by the
   proxy and configure its complete HTTPS URL in `POLYGON_RPC_URL`.
3. Run the read-only diagnostic from an authorized environment whose egress
   policy permits that RPC endpoint.

The checker intentionally provides no `--insecure` option. Never place an RPC
API key in source code, command history, logs, or a pull request.

Do not use any private key posted in chat or committed elsewhere. Treat a shared
key as compromised, move assets to a freshly generated wallet, and rotate the
provider credentials before performing deployment or administration.
