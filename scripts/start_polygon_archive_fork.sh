#!/usr/bin/env bash
set -euo pipefail

HARD_FORK="${1:-cancun}"
LOG_FILE="${2:-reports/polygon_archive_anvil.log}"
PORT="${3:-8545}"
BLOCK_NUMBER="${FORK_BLOCK_NUMBER:?FORK_BLOCK_NUMBER is required}"
LOCAL_URL="http://127.0.0.1:${PORT}"

USDC="0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
WPOL="0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270"
QS_FACTORY="0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32"
UNI_FACTORY="0x1F98431c8aD98523631AE4a59f267346ea31F984"
UNI_QUOTER="0xb27308f9F90D607463bb33eA1BeBb41C27CE5AB6"

RPC_CANDIDATES=(
  "https://tenderly.rpc.polygon.community/"
  "https://polygon.drpc.org"
  "https://polygon-public.nodies.app/"
  "https://polygon.api.onfinality.io/public"
  "https://1rpc.io/matic"
  "https://polygon-mainnet.gateway.tatum.io/"
)

mkdir -p "$(dirname "$LOG_FILE")"
rm -f "$LOG_FILE"

stop_pid() {
  local pid="$1"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid" 2>/dev/null || true
    for _ in $(seq 1 10); do
      if ! kill -0 "$pid" 2>/dev/null; then
        break
      fi
      sleep 0.2
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
  wait "$pid" 2>/dev/null || true
}

cast_probe() {
  timeout 40s cast call "$@" --rpc-url "$LOCAL_URL" >/dev/null 2>&1
}

for rpc_url in "${RPC_CANDIDATES[@]}"; do
  echo "ARCHIVE_FORK_CANDIDATE ${rpc_url}" | tee -a "$LOG_FILE"
  candidate_log="${LOG_FILE%.log}.$(echo "$rpc_url" | tr -c '[:alnum:]' '_').log"
  rm -f "$candidate_log"

  anvil \
    --fork-url "$rpc_url" \
    --fork-block-number "$BLOCK_NUMBER" \
    --timeout 180000 \
    --chain-id 137 \
    --hardfork "$HARD_FORK" \
    --host 127.0.0.1 \
    --port "$PORT" \
    > "$candidate_log" 2>&1 &
  anvil_pid=$!

  ready=0
  for _ in $(seq 1 45); do
    if ! kill -0 "$anvil_pid" 2>/dev/null; then
      break
    fi
    response="$(curl --max-time 2 -s "$LOCAL_URL" \
      -H 'content-type: application/json' \
      --data '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}' || true)"
    if echo "$response" | grep -q '0x89'; then
      ready=1
      break
    fi
    sleep 1
  done

  probe_ok=0
  if [[ "$ready" == "1" ]]; then
    # Gate only on state V15 actually requires. Router helper methods are not
    # used as provider eligibility tests because their ABI differs by deployment.
    if \
      cast_probe "$QS_FACTORY" "getPair(address,address)(address)" "$USDC" "$WPOL" && \
      cast_probe "$UNI_FACTORY" "getPool(address,address,uint24)(address)" "$USDC" "$WPOL" 100 && \
      cast_probe "$UNI_QUOTER" \
        "quoteExactInputSingle(address,address,uint24,uint256,uint160)(uint256)" \
        "$USDC" "$WPOL" 100 10000000 0; then
      qs_pair="$(timeout 40s cast call "$QS_FACTORY" \
        "getPair(address,address)(address)" "$USDC" "$WPOL" \
        --rpc-url "$LOCAL_URL" 2>/dev/null | tail -n 1 | tr -d '[:space:]')"
      uni_pool="$(timeout 40s cast call "$UNI_FACTORY" \
        "getPool(address,address,uint24)(address)" "$USDC" "$WPOL" 100 \
        --rpc-url "$LOCAL_URL" 2>/dev/null | tail -n 1 | tr -d '[:space:]')"
      if [[ "$qs_pair" =~ ^0x[0-9a-fA-F]{40}$ ]] \
        && [[ "$uni_pool" =~ ^0x[0-9a-fA-F]{40}$ ]] \
        && [[ "$qs_pair" != "0x0000000000000000000000000000000000000000" ]] \
        && [[ "$uni_pool" != "0x0000000000000000000000000000000000000000" ]] \
        && cast_probe "$qs_pair" "getReserves()(uint112,uint112,uint32)" \
        && cast_probe "$USDC" "balanceOf(address)(uint256)" "$qs_pair" \
        && cast_probe "$WPOL" "balanceOf(address)(uint256)" "$qs_pair" \
        && cast_probe "$USDC" "balanceOf(address)(uint256)" "$uni_pool" \
        && cast_probe "$WPOL" "balanceOf(address)(uint256)" "$uni_pool"; then
        probe_ok=1
      fi
    fi
  fi

  if [[ "$probe_ok" == "1" ]]; then
    cat "$candidate_log" >> "$LOG_FILE"
    echo "ARCHIVE_FORK_SELECTED ${rpc_url} pid=${anvil_pid}" | tee -a "$LOG_FILE"
    if [[ -n "${GITHUB_ENV:-}" ]]; then
      echo "SELECTED_POLYGON_RPC=${rpc_url}" >> "$GITHUB_ENV"
      echo "ANVIL_PID=${anvil_pid}" >> "$GITHUB_ENV"
    fi
    exit 0
  fi

  stop_pid "$anvil_pid"
  cat "$candidate_log" >> "$LOG_FILE" || true
  echo "ARCHIVE_FORK_REJECTED ${rpc_url}" | tee -a "$LOG_FILE"
done

echo "No archive-capable Polygon RPC candidate passed the V15 pool and quoter prewarm" | tee -a "$LOG_FILE"
exit 1
