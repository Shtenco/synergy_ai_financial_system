# SYNERGY V15.6 — восстановление графового QE/QT-стека

## Что было сломано

Ошибка состояла не в том, что V15.5 повредил Solidity-контракты V11. Главная проблема была веточной и архитектурной.

PR №8 был создан от коммита `927a5e4d0046e377c78fed7f1a033ea0e3abc9c6`. После этой точки в ветке `audit/synergy-qe-polygon-fork` появились ещё 15 коммитов с прямым V11 atomic QE/QT executor и V12 managed-gradient probe. Они не попали в head PR №8.

В результате:

- V8 integration-test ссылался на `TemporaryQETokenV11` и `SynergyAtomicQeQtCycleV11`;
- сам `contracts/fork/SynergyAtomicQeQtCycleV11.sol` в PR №8 отсутствовал;
- V11/V12 tests, validators и workflows также отсутствовали;
- `.github/workflows/stateful-supercycle-v8.yml` был перезаписан содержимым V15.1 historical workflow.

Кроме того, узкий V15.5 negative-control тест был ошибочно представлен как завершение главной задачи. V15.5 доказывает только следующее: внутренние ADDLP, обратимые swaps, mint и burn без независимого внешнего плательщика не создают внешний WPOL surplus.

## Что восстановлено

Через recovery PR №10 в `audit/stateful-supercycle-v8` возвращены 15 потерянных коммитов V11/V12.

Recovery merge commit:

```text
7511bda78da38cd59c9ae828db5644e6bbb99f6f
```

Восстановлены:

- `contracts/fork/SynergyAtomicQeQtCycleV11.sol`;
- `contracts/fork/SelfCreatedGradientProbeV12.sol`;
- V11/V12 fork tests;
- V11/V12 validators;
- direct-source workflows;
- V8 package commands.

Workflow-инфраструктура разделена снова:

- `.github/workflows/stateful-supercycle-v8.yml` — V8 stateful 10+10 graph fork;
- `.github/workflows/synergy-v15-1-strict-historical.yml` — V15.1 historical external revenue.

## Восстановленный положительный fork

Из-за невозможности запуска hosted runner в приватном репозитории exact-source bundle был выполнен в изолированной публичной CI-ветке. Главные контракты были привязаны к точным Git blob SHA приватного PR №8.

### Точные исходники

```text
SynergyAtomicQeQtCycleV11.sol
Git blob SHA:
6c8303eae6bfae608532fbdfb50df72c044a1581

StatefulSupercycleV8.sol
Git blob SHA:
390eb5f99f2b6665708b460df9ecdf379227f615
```

Компилятор:

```text
solc:        0.8.26+commit.8a97fa7a.Emscripten.clang
Hardhat:     2.22.19
optimizer:   500 runs
viaIR:       true
EVM target:  Cancun
```

## Реальная структура эксперимента

На Polygon fork создано и проверено:

```text
Внутренних permissioned пулов: 10
Реальных внешних Polygon пулов: 10
Исполненных внутренних рёбер: 1
Исполненных внешних рёбер: 2
Успешных последовательных циклов: 3
```

Основной путь:

```text
temporary QE mint
→ внутренний SYN/USDT pool
→ QuickSwap Algebra V3: USDT → WPOL
→ QuickSwap V2: WPOL → USDT
→ точный расчёт внутреннего buyback
→ обратный swap USDT → SYN
→ QT burn временной эмиссии
→ treasury profit
→ проверка supply, LP reserves и k
```

Внешний ценовой градиент создавался независимой транзакцией, не самим executor-контрактом.

## Фактический результат

Fork зафиксирован на:

```text
Polygon block: 90 790 000
Block hash:
0xb0a1c2e01753d64bf33c0a0f97f6d22cb236b657f66d4376f4e0eac4d4b4488f
```

Итоги трёх циклов:

```text
Независимый внешний поток:       9 326.629578 USDT
Treasury profit до учёта газа:      75.491852 USDT
Газ при 274 gwei:                    0.061587 USDT
Treasury profit после газа:         75.430265 USDT
Рост консолидированного USDT NAV:   76.667613 USDT
```

### Цикл 1

```text
QE mint:             65.286407 SYN
External return:     90.914892 USDT
Exact buyback:       65.417635 USDT
Treasury profit:     25.497257 USDT
Gas:                  0.026453 USDT
Net after gas:       25.470804 USDT
kBefore: 4262314944975998446116
kAfter:  4262340531894075100344
```

### Цикл 2

```text
QE mint:             65.286407 SYN
External return:     90.581367 USDT
Exact buyback:       65.418027 USDT
Treasury profit:     25.163340 USDT
Gas:                  0.017594 USDT
Net after gas:       25.145746 USDT
```

### Цикл 3

```text
QE mint:             65.286407 SYN
External return:     90.249675 USDT
Exact buyback:       65.418420 USDT
Treasury profit:     24.831255 USDT
Gas:                  0.017540 USDT
Net after gas:       24.813715 USDT
```

Для каждого цикла доказано:

- внешний USDT покрывает точный buyback;
- treasury profit больше measured gas cost;
- временная эмиссия полностью закрыта;
- общий supply возвращён к исходному значению;
- внутренний liquid reserve не уменьшается;
- `kAfter >= kBefore`;
- WPOL, USDC и WETH внутри protocol boundary сохранены.

## Evidence provenance

```text
GitHub Actions run: 30723654292
Job:               91431413001
Conclusion:        success
Artifact ID:       8825633463
Artifact size:     58 281 bytes
Artifact digest:
sha256:59b470a2f604c69cff21d32c573cac6d3cdc79ddc357bda20992e7bccc6e4b78

Fork report SHA-256:
7340a303eb8912467fbd57e5a512c26ef3e702b43f70cb77668f87c59cb4a5cf
```

Архив содержит 40 файлов. Все 39 записей внутреннего checksum manifest проверены без расхождений.

## Что ещё не закрыто

Восстановленный положительный fork не равен полной целевой архитектуре.

Пока не доказано:

1. исполнение произвольного маршрута, выбранного из всех 50 внешних пулов;
2. использование реального Aave V3 flash principal в этих трёх циклах;
3. единая транзакция:

```text
Aave flash
→ 50-pool graph optimizer
→ selected external cycle
→ internal QE/QT closure
→ repayment + premium
→ V14 consolidated accounting
```

Строгий V14 поиск по 50 внешним пулам ранее дал `0` принятых циклов. Поэтому утверждать, что 50-пуловый Aave-flash контур уже доказан в прибыли, нельзя.

Старый `AaveFlashQESolverV2` исполнялся с детерминированным Aave-compatible lender; настоящий Aave Pool в том тесте использовался только для read-only проверки. Это отдельный слой, который ещё требуется соединить с восстановленным V8/V11 executor.

## Правильная роль версий

```text
V8/V11 — восстановленный положительный QE/QT graph fork
V14     — строгая 50-пуловая бухгалтерия и fail-closed gate
V15.1–V15.3 — внешние исторические revenue surfaces и panel
V15.4   — структурная fixed-fee flash accounting модель
V15.5   — отрицательный контроль без внешнего edge
V15.6   — восстановление стеков и подготовка единого Aave/50-pool/QE-QT контура
```

Полная машинная привязка результата находится в:

```text
reports/v15_6_recovered_v8_v11_positive_fork_binding.json
```
