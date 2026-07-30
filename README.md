# SYNERGY / SHTENCO AI Financial System

SYNERGY is an experimental DeFi architecture for consolidated accounting, solvency-controlled QE/QT, permissioned liquidity, external-profit compounding, graph arbitrage and protected interaction with public Polygon markets.

The project does **not** treat token issuance, internal transfers, controlled prices or protocol-owned wash volume as profit. External revenue must be backed by a real external balance increase after fees, gas, slippage, flash premium, liabilities and protocol-owned liquidity loss.

> Status: architecture, simulation and Polygon fork testing. Not production-ready. No guaranteed yield, guaranteed arbitrage or absolute MEV protection is claimed.

---

## Documentation

Start here:

- [Complete system documentation](docs/SYNERGY_SYSTEM_DOCUMENTATION.md) — vision, economic constitution, architecture, V2–V7 history, modules, topology, metrics, risks, roadmap and limitations.
- [Contract catalog](docs/CONTRACT_CATALOG.md) — contract-by-contract roles, trust boundaries, invariants and deployment status.
- [Testing and evidence guide](docs/TESTING_AND_EVIDENCE.md) — workflows, unit/fork tests, simulations, validators, baseline metrics and evidence semantics.
- [Production readiness runbook](docs/PRODUCTION_RUNBOOK.md) — safe setup, fork reproduction, release manifest, shadow/canary procedure, monitoring and incident response.

Focused research documents:

- [Self-sustaining graph design and limits](docs/SELF_SUSTAINING_GRAPH_DESIGN.md)
- [Graph arbitrage and QE results](docs/GRAPH_ARBITRAGE_QE_RESULTS.md)
- [Anti-MEV execution boundary](docs/ANTI_MEV_DESIGN.md)
- [Repository security review](docs/SECURITY_AUDIT.md)
- [External order-flow revenue](docs/ORDERFLOW_REVENUE.md)
- [Dual-circuit solvency review](docs/DUAL_CIRCUIT_SOLVENCY_REVIEW.md)
- [Absolute solvency specification](docs/ABSOLUTE_SOLVENCY_SPEC.md)

---

## Current V7 topology

The tested V7 graph has exactly nine pools.

### Internal permissioned SINERGY DEX

The complete graph over WPOL, USDT, SYNA and SYNR:

```text
WPOL / SYNA
WPOL / SYNR
SYNA / SYNR
WPOL / USDT
USDT / SYNA
USDT / SYNR
```

### Public representative

```text
QuickSwap V3 WPOL / SYNA
```

### Independent external exits

```text
QuickSwap V2 WPOL / USDT
QuickSwap V3 WPOL / USDT
```

The public representative is protected with owner-bound commit/reveal, deadline, non-zero quote/minOut checks, replay prevention and quote-loss bounds. These controls mitigate risk but do not make a transparent public mempool immune to MEV.

---

## Economic constitution

The system is built around the following rules:

```text
internal transfer != external revenue
minted token != reserve asset
market cap != consolidated NAV
flash principal != protocol capital
QE notional != profit
internal inventory burn != external liability retirement
bridge transfer != new value
external profit = external amount out - all external and internal economic costs
```

The consolidated boundary is defined by `SystemBoundaryRegistry`. `ConsolidatedLedger` records external revenue, expenses, liabilities, inventory, losses and dividends in an append-only hash chain. `SolvencyController` applies haircut assets, stress liabilities and coverage gates before execution or distribution.

---

## Architecture

The repository combines:

- Flash Loan Arbitrage;
- AI/off-chain route and policy optimization;
- AI Central Bank research;
- AI Market Maker;
- Value Flow Treasury;
- consolidated ledger and system boundary;
- solvency and real-liquidity risk gates;
- backed reserve QE;
- external-liability QT;
- permissioned SINERGY DEX;
- public representative liquidity;
- external order-flow revenue;
- dividend/reinvestment controls;
- Across-compatible dividend relay;
- deterministic, Monte Carlo and stress simulation;
- Polygon fork acceptance tests.

The off-chain optimizer may discover and propose actions. Deterministic on-chain rules must remain the final execution authority.

---

## Repository structure

```text
contracts/              Solidity smart contracts
  accounting/           Consolidated ledger
  bridge/               Across-compatible relay and mocks
  dividend/             External-profit dividend vault
  fork/                 Polygon fork and recovery harnesses
  graph/                SYNERGY V7 topology and graph gates
  liquidity/            V4/V5 liquidity engines
  mm/                   External-revenue market maker
  policy/               Boundary, solvency, multiplier and self-support
  qe/                   Backed reserve QE
  qt/                   External-liability QT
  test/                 Solidity test harnesses

simulation/             Python deterministic and Monte Carlo models
scripts/                Validators, preflight and reporting tools
test/                   Hardhat unit and Polygon fork tests
docs/                   Architecture, audit and operations documentation
.github/workflows/       Mandatory CI acceptance gates
solver/                  External solver discovery/auction examples
TOP_AI/                  Separate experimental TOP AI contour
```

Several generations coexist in the repository. Do not deploy every contract. A release-specific deployment manifest must explicitly select contracts and exclude `contracts/test/**`, `contracts/fork/**` and legacy modules not included in the release.

---

## Toolchain

Baseline configuration:

```text
Solidity       0.8.26
Optimizer      enabled, 500 runs
viaIR          true
EVM version    paris
Hardhat        2.22.19
ethers         6.17.0
OpenZeppelin   5.6.1
Python CI      3.12
Polygon        chain id 137
Fork block     90,790,000
```

GitHub Actions currently requests Node 20, which is deprecated in the current runner environment. Migration to Node 24 is tracked as technical debt.

---

## Install and compile

```bash
npm ci
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install numpy matplotlib
npx hardhat compile
```

Current CI temporarily patches a reserved identifier in `contracts/fork/SynergyQEForkHarness.sol` before compile. A production release must fix the source and compile from a clean checkout without runtime source mutation.

---

## V7 model and validator

```bash
python simulation/run_synergy_graph_v7.py
python scripts/validate_synergy_graph_v7.py
```

The model runs a deterministic 20,000-block path and a 1,000 × 20,000 Monte Carlo experiment.

Baseline evidence at commit `90273f12d356411af70bae0ba64265b7a83455cc` reported:

```text
model growth factor          1.0560657753300176
minimum model multiplier     3.184479120855431
model external profit        6.795851555153707
internal USDT cycles         591
Monte Carlo p05 growth       1.030644180564504
Monte Carlo min multiplier   3.22
fork external net profit     0.07 USDT
internal pools               6
total graph pools            9
failed invariants            []
```

These are test-model and fork-fixture results, not a forecast or promise of future performance.

---

## Polygon fork

Configure an approved archival Polygon RPC and launch Anvil:

```bash
export POLYGON_RPC_URL=https://approved-provider.example/API_KEY
export FORK_BLOCK_NUMBER=90790000
export LOCAL_FORK_URL=http://127.0.0.1:8545

anvil \
  --fork-url "$POLYGON_RPC_URL" \
  --fork-block-number "$FORK_BLOCK_NUMBER" \
  --chain-id 137 \
  --hardfork shanghai \
  --host 127.0.0.1 \
  --port 8545
```

Run V7 fork acceptance:

```bash
npx hardhat test test/synergy_graph_arbitrage_v7_polygon_fork.js --network polygonFork
python scripts/validate_synergy_graph_v7.py
```

Fork tests may impersonate accounts and fund local fixtures. This is test-only behavior and is not a production funding mechanism.

---

## Baseline CI evidence

Seven workflows completed successfully on the baseline code commit:

```text
SYNERGY V7 Graph Arbitrage
SYNERGY V5 Compounding and Permissioned DEX
Synergy QE Polygon Fork
SYNERGY V6 Dividend Self-Support
Real Liquidity Multiplier V4
Full QE QT Relay Integration
Consolidated Solvency V3
```

V7 artifact:

```text
name: synergy-v7-graph-arbitrage-evidence
artifact id: 8771099117
digest: sha256:6f369bc68f6dedfa269507ff3683c4c11c745a5a50fda1505a35ac389c492646
```

A successful workflow proves only the assertions and models executed at that commit.

---

## Known production blockers

The current branch must not be treated as a production release. Important blockers include:

- clean compile without CI source patch;
- explicit token path and per-hop adjacency in V7 proof;
- atomic route execution with measured pre/post balances;
- independent on-chain oracle/TWAP/M-of-N source;
- economically meaningful exit-depth thresholds;
- private transaction relay;
- multisig, timelock and pause-only guardian;
- fuzz, hostile-token and adversarial-MEV tests;
- bridge failure/refund testing;
- release-specific deployment manifest;
- independent audits and bug bounty;
- legal review;
- shadow mode and limited canary deployment.

See [Production readiness runbook](docs/PRODUCTION_RUNBOOK.md).

---

## Security

No private keys, seed phrases, RPC secrets or `.env` files belong in this repository.

Before any mainnet action:

1. use a fresh hardware-backed deployment setup;
2. verify exact external addresses and bytecode;
3. reproduce pinned fork tests;
4. verify tested bytecode equals deployed bytecode;
5. transfer control to multisig/timelock;
6. configure guardian and limits;
7. enable monitoring before execution;
8. start with shadow mode and minimal canary capital.

Do not use any private key posted in chat or committed elsewhere. Treat it as permanently compromised.

---

## Read-only Polygon balance check

The repository includes a dependency-free read-only diagnostic. It never accepts or uses a private key:

```bash
POLYGON_RPC_URL=https://your-provider.example \
  python scripts/check_polygon_balances.py
```

If an approved HTTPS inspection gateway requires a CA certificate:

```bash
POLYGON_RPC_URL=https://your-provider.example \
POLYGON_CA_CERT=/secure/path/gateway-ca.pem \
  python scripts/check_polygon_balances.py
```

Do not disable TLS verification. A local CA certificate can establish TLS trust but cannot bypass an outbound proxy policy that rejects HTTP `CONNECT`.

---

## External solver research

The repository includes a voluntary solver-auction model. After a separately audited deployment, searchers may discover announcements with:

```bash
npm run solver:watch
npm run solver:bid
```

Publishing a contract does not guarantee solver participation or revenue. See [External order-flow revenue](docs/ORDERFLOW_REVENUE.md).

---

## Final statement

SYNERGY is being designed as a digital economy that can prove where value came from, what liabilities were created, what costs were paid and whether the whole consolidated system became stronger.

The current engine runs on the test stand. The next task is not to declare victory, but to make the tested architecture atomic, independently priced, governed, audited and safe enough for a carefully limited real-world canary.