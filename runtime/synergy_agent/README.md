# SYNERGY agent secure runtime

This directory is a local runtime boundary, not a place for tracked secrets.

## Create a local environment file

```bash
python scripts/synergy_secure_vault.py init --network amoy
python scripts/synergy_secure_vault.py init --network polygon
```

The command creates one of these ignored files with POSIX mode `0600`:

- `runtime/synergy_agent/local/amoy.env`
- `runtime/synergy_agent/local/polygon.env`

Never use `git add -f` on `runtime/synergy_agent/local/`. Never paste a private
key into an issue, pull request, Actions log or chat.

## Validate without revealing the key

```bash
python scripts/synergy_secure_vault.py check \
  --env runtime/synergy_agent/local/amoy.env
```

The checker validates path, permissions, key format, derived signer address,
chain ID, block/loss limits and mainnet arming rules. It prints only the signer
address and a redacted configuration summary.

## Execution phases

1. Offline simulator and unit tests.
2. Amoy dry-run for 150 blocks.
3. Amoy execution after contract addresses are configured.
4. Polygon mainnet read-only shadow run.
5. Only then: manually armed 150-block mainnet run with a hard 20 POL loss cap.

Mainnet execution is rejected unless all of the following are true:

- `CHAIN_ID=137` is returned by the RPC;
- `EXPECTED_SIGNER_ADDRESS` equals the private-key signer;
- `BLOCK_LIMIT=150` and `MAX_LOSS_POL=20`;
- `TX_SUBMISSION_MODE=private`;
- a private transaction endpoint is configured;
- `MAINNET_ARM_PHRASE=I_ACCEPT_MAX_20_POL_LOSS_FOR_150_BLOCKS`;
- no `STOP` file exists;
- the owner starts with at least 10 POL.

The repository does not automate mainnet deployment or secret upload.
