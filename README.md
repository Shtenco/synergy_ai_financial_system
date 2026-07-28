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
ai_centrobank/     AI policy and optimization engine
simulation/        Python economic simulations
docs/              Architecture and audit documents
scripts/           Deployment and testing scripts
```

## Security

No private keys, seed phrases, RPC secrets or `.env` files belong in this repository.

Before any mainnet deployment:

1. Run fork tests.
2. Verify contracts.
3. Use a fresh deployment wallet.
4. Configure timelock, guardian and risk limits.

Status: architecture and local testing stage.

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
