# SYNERGY RL agent — secure testnet and bounded mainnet execution

## Security boundary

The RL policy never receives a private key and never signs transactions. It only
proposes bounded actions. A separate deterministic runtime guard checks chain ID,
signer, block budget, loss budget, gas, action notional, emergency stop and
submission mode before an adapter may sign anything.

A populated `.env` is local runtime data. It is excluded by both the repository
root `.gitignore` and `runtime/synergy_agent/.gitignore`. CI scans tracked files
for likely 32-byte wallet secrets and fails closed.

GitHub recommends never committing private keys and using runtime secret managers
or environment secrets. This repository intentionally does not upload or print a
private key.

## Network sequence

### Phase 1 — simulator

Run the previously prepared offline RL simulator locally without a wallet. The
security PR deliberately does not duplicate the large model source; its scope is
the vault, deterministic risk guard and chain preflight. The model will be wired
into the guarded policy interface only after this security gate is green.

### Phase 2 — Amoy read-only shadow

Polygon Amoy uses chain ID `80002`.

```bash
python scripts/synergy_secure_vault.py init --network amoy
# Populate runtime/synergy_agent/local/amoy.env locally.
python scripts/synergy_secure_vault.py check --env runtime/synergy_agent/local/amoy.env
python scripts/synergy_agent_preflight.py --env runtime/synergy_agent/local/amoy.env
python scripts/run_synergy_agent_guarded.py --env runtime/synergy_agent/local/amoy.env
```

The current guarded runner is shadow-only and proposes `HOLD`. This is deliberate:
the three-token contracts, valuation adapter, commit/reveal transaction adapter,
private submission adapter and gas-refill swap must first be deployed and audited
on Amoy.

### Phase 3 — Amoy execution

Execution may be enabled only after the adapter proves:

- router output is non-zero;
- oracle/TWAP deviation is inside the configured limit;
- nonce and deadline are valid;
- min-out and price-impact limits hold;
- LP accounting, mint/burn accounting and USDS solvency remain valid;
- gas-refill sells no more token value than needed to receive 2 POL;
- every failed invariant atomically reverts.

### Phase 4 — Polygon shadow run

Use `NETWORK=polygon`, `CHAIN_ID=137`, but keep `EXECUTION_MODE=dry-run`. Observe
exactly 150 blocks and compare proposed actions with executable quotes. No
transaction should be signed.

### Phase 5 — manually armed mainnet run

Mainnet execution is accepted only when all hard requirements are present:

```text
BLOCK_LIMIT=150
ACTION_INTERVAL=10
MAX_LOSS_POL=20
MIN_OWNER_POL>=10
REFILL_POL=2
TX_SUBMISSION_MODE=private
MAINNET_ARM_PHRASE=I_ACCEPT_MAX_20_POL_LOSS_FOR_150_BLOCKS
```

The run stops at the first of:

- 150 observed blocks;
- consolidated mark-to-market loss of 20 POL;
- emergency `runtime/synergy_agent/STOP` file;
- RPC chain mismatch;
- signer mismatch;
- single-transaction gas above 0.25 POL;
- action notional above its configured cap;
- unavailable private submission endpoint;
- invalid NAV or balance observation.

## Important limitation

The current branch creates the protected vault and deterministic safety shell.
It does not yet contain a reviewed live transaction adapter, so it cannot
accidentally broadcast the RL agent to mainnet. This must remain fail-closed until
the Amoy contracts and their ABIs/addresses are available.
