#!/usr/bin/env bash
set -euo pipefail

HARD_FORK="${1:-cancun}"
LOG_FILE="${2:-reports/polygon_archive_anvil.log}"
PORT="${3:-8545}"
BLOCK_NUMBER="${FORK_BLOCK_NUMBER:?FORK_BLOCK_NUMBER is required}"
LOCAL_URL="http://127.0.0.1:${PORT}"

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

  if [[ "$ready" == "1" ]]; then
    # Force several historical state reads before accepting the provider.
    probes=(
      '{"jsonrpc":"2.0","method":"eth_getCode","params":["0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff","latest"],"id":2}'
      '{"jsonrpc":"2.0","method":"eth_getCode","params":["0xE592427A0AEce92De3Edee1F18E0157C05861564","latest"],"id":3}'
      '{"jsonrpc":"2.0","method":"eth_getCode","params":["0x1F98431c8aD98523631AE4a59f267346ea31F984","latest"],"id":4}'
      '{"jsonrpc":"2.0","method":"eth_getCode","params":["0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32","latest"],"id":5}'
      '{"jsonrpc":"2.0","method":"eth_getBalance","params":["0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266","latest"],"id":6}'
    )
    probe_ok=1
    for payload in "${probes[@]}"; do
      response="$(curl --max-time 20 -s "$LOCAL_URL" \
        -H 'content-type: application/json' \
        --data "$payload" || true)"
      if [[ -z "$response" ]] || echo "$response" | grep -q '"error"'; then
        probe_ok=0
        break
      fi
    done
    if [[ "$probe_ok" == "1" ]]; then
      cat "$candidate_log" >> "$LOG_FILE"
      echo "ARCHIVE_FORK_SELECTED ${rpc_url} pid=${anvil_pid}" | tee -a "$LOG_FILE"
      if [[ -n "${GITHUB_ENV:-}" ]]; then
        echo "SELECTED_POLYGON_RPC=${rpc_url}" >> "$GITHUB_ENV"
        echo "ANVIL_PID=${anvil_pid}" >> "$GITHUB_ENV"
      fi
      exit 0
    fi
  fi

  stop_pid "$anvil_pid"
  cat "$candidate_log" >> "$LOG_FILE" || true
  echo "ARCHIVE_FORK_REJECTED ${rpc_url}" | tee -a "$LOG_FILE"
done

echo "No archive-capable Polygon RPC candidate could start and prewarm Anvil" | tee -a "$LOG_FILE"
exit 1
