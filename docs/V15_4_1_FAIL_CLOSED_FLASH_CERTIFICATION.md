# SYNERGY V15.4.1 — fail-closed certification для 5 WPOL × 10

## Причина усиления

Первая версия V15.4 правильно моделировала fixed fee `5 WPOL`, десять flashloan в одной EVM transaction, строгий post-cost floor `2.685148 bps` и реинвестирование `80%`.

Но исходный validator допускал отсутствие Solidity structural report:

```text
not structural OR evidenceClass == STRUCTURAL_ONLY_NOT_MARKET_EDGE
```

Из-за этого deterministic economics мог теоретически дать PASS даже если Hardhat test не был выполнен. Для строгого evidence это недопустимо.

## Новое правило dual evidence

V15.4.1 выдаёт PASS только если одновременно существуют и взаимно согласованы:

1. deterministic economics report;
2. Solidity/Hardhat structural report;
3. SHA-256 текущего контракта;
4. SHA-256 текущего теста;
5. все обязательные rollback и boundary assertions.

Отсутствие любого компонента означает:

```text
verdict = FAIL
economicStatus = V15_4_EVIDENCE_REJECTED
```

## Добавленные строгие проверки

Hardhat test теперь доказывает:

- полный rollback, когда десятый цикл даёт только `5.2 WPOL gross`;
- успешные десять циклов при `6 WPOL gross` каждый;
- PASS ровно на границе `5.2685148 WPOL gross`;
- REVERT на один wei ниже границы;
- запрет pre-funded receiver subsidy;
- нулевой settlement residue;
- точные cumulative values `60 / 50 / 10 / 8 / 2 WPOL`.

Structural report создаётся после всей test suite и содержит:

```text
allAssertionsPassed
contractSha256
testSha256
atomicRollbackOnTenthFailure
profitableTenCycleBatch
exactBoundaryPass
boundaryMinusOneWeiRevert
receiverSubsidyRejected
```

## Self-hosted certification

Добавлен workflow:

```text
.github/workflows/atomic-flashloan-5pol-v15-4-self-hosted.yml
```

Runner labels:

```text
self-hosted
linux
x64
synergy-v15
```

Workflow выполняет:

```text
npm ci
hardhat compile
hardhat structural tests
Python deterministic economics
fail-closed dual-evidence validator
artifact upload
```

Финальный artifact:

```text
synergy-v15-4-runner-certified-atomic-fixed-5-wpol-flash-10x
```

## Экономический статус

При principal `1,000 WPOL`:

```text
minimum gross per cycle = 5.2685148 WPOL
```

Если каждый цикл даёт `6 WPOL gross`:

```text
10 cycles gross route profit = 60 WPOL
flash fees                   = 50 WPOL
counted net protocol profit  = 10 WPOL
reinvested 80%               = 8 WPOL
retained 20%                 = 2 WPOL
```

Если хотя бы один цикл не проходит strict floor, весь batch откатывается:

```text
completed cycles = 0
paid fees = 0
counted revenue = 0
reinvestment = 0
```

Это остаётся structural-only evidence. Live Polygon profitability не заявляется без реального внешнего маршрута и fork replay.
