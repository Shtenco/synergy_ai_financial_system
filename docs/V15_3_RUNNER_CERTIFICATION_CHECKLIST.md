# SYNERGY V15.3 — как закрыть runner-certified ≥30 replay rows

## Почему сейчас статус не закрыт

Текущие GitHub-hosted jobs завершаются до первого шага:

```text
steps: null
logs: отсутствуют
artifacts: отсутствуют
```

Это означает, что ни checkout, ни компиляция, ни Polygon collector не запускались. Такой run не является отрицательным экономическим результатом, но и не создаёт evidence.

## Самый надёжный путь: отдельный self-hosted runner

В репозиторий добавлен workflow:

`.github/workflows/synergy-transaction-panel-v15-3-self-hosted.yml`

Он требует runner labels:

```text
self-hosted
linux
x64
synergy-v15
```

### Рекомендуемая машина

Минимально практичная конфигурация для 30–40 последовательных archival forks:

- Ubuntu 22.04/24.04 x64;
- 8 CPU;
- 16 GB RAM;
- 100 GB SSD;
- стабильный исходящий HTTPS;
- Node.js 22;
- Python 3.12;
- Foundry/Anvil/Cast;
- Git;
- доступ к архивному Polygon RPC.

Для публичного репозитория runner должен быть одноразовой изолированной VM без личных ключей и без доступа к домашней сети.

## Что настроить в GitHub

1. `Repository → Settings → Actions → Runners → New self-hosted runner`.
2. Выполнить показанные GitHub команды регистрации на Linux-машине.
3. Добавить custom label `synergy-v15`.
4. Запустить runner как service.
5. Добавить repository secret:

```text
POLYGON_ARCHIVE_RPC_URL=<платный или собственный Polygon archive endpoint>
```

Никаких private keys для V15.3 panel не требуется.

## Требования к RPC

Endpoint должен поддерживать:

- Polygon chain ID 137;
- исторические полные блоки с транзакциями;
- receipts;
- `eth_call` на старом block tag;
- historical token balances и pool state;
- стабильные 30–40 последовательных Anvil forks;
- достаточный rate limit без публичного throttling.

Перед запуском workflow проверяет начальный и конечный исторический блок через `cast block`.

## Запуск сертификации

Открыть:

```text
Actions → SYNERGY V15.3 Self-Hosted Certification → Run workflow
```

Рекомендуемые параметры первого полного прогона:

```text
start_block:          91250000
end_block:            91266308
minimum_victim_usdc:  100
maximum_raw_rows:     250
replay_limit:         40
```

## Что workflow обязан доказать

1. Минимум 30 valid fresh-fork replay rows.
2. Каждая строка начинается с fork `N-1`.
3. Воспроизводится фактическая историческая transaction.
4. Victim находится раньше backrun в одном fork block.
5. Все расходы вычтены.
6. FAIL/ERROR строки имеют нулевой counted revenue.
7. Train/holdout разделены по времени.
8. Коэффициенты не используют post-block leakage.
9. Live gate использует bootstrap `P05 >= 2.685148 bps`.
10. Реинвестируется ровно 80% только фактической counted protocol revenue.

## Артефакт, закрывающий статус

Workflow должен создать:

```text
synergy-v15-3-runner-certified-transaction-panel
```

Внутри обязательны:

- `v15_3_transaction_panel_raw.jsonl`;
- `v15_3_transaction_panel_replayed.jsonl`;
- `v15_3_transaction_panel_replay_summary.json`;
- `v15_3_transaction_coefficients.json`;
- `v15_3_holdout_predictions.jsonl`;
- `v15_3_strict_empirical_verdict.json`.

Статусы считаются закрытыми только при:

```text
validReplayRows >= 30
empiricalStatus = TRANSACTION_LEVEL_COEFFICIENTS_ESTIMATED
verdict = PASS
```

После этого:

- `Real transaction coefficients` берутся из coefficient artifact;
- `Counted revenue` берётся только из фактических holdout execution rows;
- `Reinvestment = 0.80 × counted revenue`;
- при отсутствии строгих PASS строк revenue и reinvestment могут честно остаться нулевыми даже после успешной сертификации.

## Альтернатива

Можно восстановить GitHub-hosted runners, проверив Actions policy, billing/quota и spending limits аккаунта. Но self-hosted workflow устраняет зависимость от текущей невозможности выделить hosted VM и одновременно даёт контролируемый доступ к архивному RPC.
