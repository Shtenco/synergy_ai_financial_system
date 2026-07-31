# SYNERGY Testing and Evidence Guide

> Назначение: объяснить, что именно проверяет каждый тестовый контур, какие доказательства создаются и какие выводы из них допустимы.
>
> Baseline evidence commit: `90273f12d356411af70bae0ba64265b7a83455cc`.
>
> Важно: успешный тест доказывает выполнение конкретных assertions в конкретной среде. Он не является гарантией будущей прибыли, полной безопасности или юридического соответствия.

---

## 1. Пирамида доказательств

SYNERGY использует несколько уровней проверки.

### Уровень 1 — compile

Проверяет синтаксис, типы, interfaces и совместимость Solidity toolchain.

Не проверяет экономическую корректность.

### Уровень 2 — unit tests

Проверяет отдельные контракты, роли, reverts, бухгалтерские классификации и детерминированные fixtures.

Не доказывает корректность реального внешнего DEX/bridge/oracle.

### Уровень 3 — batch/integration tests

Проверяет несколько модулей в одном цикле и повторяет операции десятки или тысячи раз.

Не воспроизводит полностью публичный mempool и экономику независимых пользователей.

### Уровень 4 — Polygon fork tests

Исполняет код против состояния Polygon на фиксированном блоке. Проверяет реальные deployed addresses, bytecode, token behavior и внешние pools.

Fork может использовать локально развёрнутые токены, impersonation и искусственное финансирование fixture. Это доказательство интеграции, а не live deployment.

### Уровень 5 — deterministic economic simulation

Проверяет бухгалтерские identities и динамику модели на большом числе блоков при фиксированном seed.

Результат воспроизводим, но зависит от параметров модели.

### Уровень 6 — Monte Carlo

Проверяет множество траекторий volatility/dislocation/costs и ищет нарушение инвариантов.

Нулевая наблюдаемая вероятность insolvency означает только отсутствие failure в исследованной выборке.

### Уровень 7 — stress matrix

Запускает явно неблагоприятные сценарии: redemption pressure, gas shock, stale oracle, bridge outage, loss и отсутствие external opportunity.

Покрывает только перечисленные сценарии.

### Уровень 8 — mandatory validator

Собирает JSON reports и выдаёт единый PASS/FAIL. Наличие одного failed invariant завершает workflow с ошибкой.

Validator является acceptance gate для данной версии, но не заменяет независимый аудит.

---

# 2. GitHub Actions workflows

На baseline commit завершились успешно семь workflows.

| Workflow | Run ID | Основная цель |
|---|---:|---|
| `SYNERGY V7 Graph Arbitrage` | `30571716391` | exact topology, hybrid graph, external-only profit, V7 fork, Monte Carlo |
| `SYNERGY V5 Compounding and Permissioned DEX` | `30571716406` | permissioned DEX, eligibility, representative liquidity, external-profit compounding |
| `Synergy QE Polygon Fork` | `30571716380` | QE/QT fork integration и Polygon asset behavior |
| `SYNERGY V6 Dividend Self-Support` | `30571716829` | no-new-capital self-support, keeper reimbursement, reinvestment identity |
| `Real Liquidity Multiplier V4` | `30571716418` | 3–5× stress-equivalent liquidity invariant |
| `Full QE QT Relay Integration` | `30571716475` | recovery, dividend и relay integration |
| `Consolidated Solvency V3` | `30571716430` | ledger, liabilities, solvency, dividends, stress, integrated fork |

Статус `success` означает, что все steps соответствующего workflow завершились успешно на конкретном commit.

---

# 3. V7 Graph Arbitrage workflow

Файл: `.github/workflows/synergy-graph-arbitrage-v7.yml`.

Среда:

```text
Ubuntu GitHub runner
Node setup: 20 requested
Python: 3.12
Foundry/Anvil: stable
Polygon chain id: 137
Fork block: 90,790,000
Local fork: http://127.0.0.1:8545
```

Последовательность:

1. checkout;
2. install npm dependencies;
3. install NumPy;
4. temporary Solidity identifier patch;
5. compile;
6. deterministic V7 model;
7. 1,000 × 20,000 Monte Carlo;
8. launch Anvil pinned fork;
9. strict topology fork-test;
10. mandatory validator;
11. upload `reports/*` artifact.

### Acceptance checks

Validator требует:

- exact six internal pools;
- complete four-asset internal graph;
- only one public representative pool;
- exactly two WPOL/USDT external exits;
- total graph size 9;
- deterministic growth > 1;
- minimum multiplier ≥ 3;
- minimum invariant ≥ 1;
- fake QE rejection;
- actual use of internal USDT routes;
- internal transfer revenue = 0;
- no new investor capital after bootstrap;
- Monte Carlo p05 growth ≥ 1;
- Monte Carlo insolvency probability = 0 in sample;
- six liquid internal pools on fork;
- outsider rejection;
- LP transfer restriction;
- absence of unauthorised public local-token pairs at test time;
- non-zero public quote;
- commit owner binding and replay rejection;
- zero quote rejection;
- deviation and sandwich bounds;
- two validated external exits;
- hybrid route containing internal and external edges;
- positive external net result;
- fake QE revenue rejection;
- USDT settlement.

### Baseline V7 metrics

```text
verdict                       SYNERGY V7 GRAPH ARBITRAGE: PASS
failed_invariants             []
model_growth_factor           1.0560657753300176
model_minimum_multiplier      3.184479120855431
model_external_profit         6.795851555153707
model_internal_usdt_cycles    591
monte_p05_growth_factor       1.030644180564504
monte_minimum_multiplier      3.22
fork_external_net_profit      0.07 USDT
public_quote_0.1_WPOL         0.09993350612262718 SYNA
internal_pool_count           6
total_pool_count              9
```

### Что действительно доказывает fork-test

- реальные Polygon WPOL/USDT QuickSwap V2/V3 pools обнаружены;
- public WPOL/SYNA pool можно создать в fork state;
- internal DEX создаёт шесть уникальных pairs;
- outsider не может выполнить internal USDT/SYNA route;
- LP нельзя передать outsider;
- declared hybrid proof после costs даёт 0.07 USDT;
- QE proof без internal value loss отклоняется;
- public order guard отклоняет zero router quote и replay.

### Чего fork-test не доказывает

- что 0.07 USDT получены фактическим live swap;
- что route adjacency доказана внутри текущего `CycleProof`;
- что caller-supplied oracleOut независим и честен;
- что public pool нельзя создать третьей стороной позднее;
- что depth thresholds достаточны для production trade;
- что прибыльный route существует в каждом блоке;
- что MEV отсутствует.

---

# 4. Consolidated Solvency V3 workflow

Файл: `.github/workflows/consolidated-solvency-v3.yml`.

Проверяет:

- 1,000 внутренних циклов с нулевым PnL;
- 1,000 внешних issue/QT cycles;
- safe pause при zero revenue;
- dividend только из external profit;
- redemption stress;
- gas/oracle/bridge gates;
- integrated Polygon WPOL fork;
- 20,000-block deterministic model;
- stress matrix;
- 1,000 × 20,000 Monte Carlo;
- единый solvency validator.

Mandatory checks включают:

```text
solvency ratio >= 1.20
liquidity coverage >= 1.20
gas coverage >= 1.20
reserve policy ratio >= 0.70
dividend invariant = true
Monte Carlo insolvency probability = 0 in sample
no negative reserve on all sampled paths
internal transfer revenue = 0
all enumerated stress scenarios safe
fork integration pass
fork final external liabilities = 0
dividend <= realised external PnL
```

Ограничения validator явно указывает:

- fork использует реальный Polygon WPOL, но локально развёрнутый SYN;
- consolidated V3 fork не вызывает полный реальный QuickSwap/Aave/production bridge contour;
- Monte Carlo не доказывает будущий спрос или revenue.

---

# 5. Real Liquidity Multiplier V4 workflow

Файл: `.github/workflows/real-liquidity-multiplier-v4.yml`.

Проверяет:

- deterministic V4 model;
- 1,000 × 20,000 Monte Carlo;
- V4 stress matrix;
- real QuickSwap V3 Polygon fork fixture;
- scalar invariant validator.

Главная идея: recognised multiplier должен быть обеспечен stress-equivalent executable liquidity, а не nominal token TVL.

Failure должен произойти при:

- internal transfer revenue;
- multiplier overclaim > 5×;
- volatility выше supported boundary;
- недостаточном solvency/liquidity/gas/emission coverage;
- недостаточной глубине anchor pool.

---

# 6. V5 Compounding and Permissioned DEX workflow

Файл: `.github/workflows/synergy-growth-dividend-dex-v5.yml`.

Проверяет:

- ParticipantTaxRegistry eligibility;
- permissioned factory/router/pairs;
- external payer requirement;
- representative token endpoint restrictions;
- capital allocation;
- auto-reinvestment of net dividend;
- withholding transfer;
- internal emission not treated as external revenue;
- Polygon fork liquidity interaction;
- deterministic growth model;
- validator acceptance.

Ключевой смысл V5: original external capital и reinvested realised profit учитываются отдельно, а internal notional не превращается в income.

---

# 7. V6 Dividend Self-Support workflow

Файл: `.github/workflows/dividend-self-support-v6.yml`.

Проверяет:

- 20,000-block deterministic model;
- 1,000 × 20,000 Monte Carlo;
- Polygon fork no-new-capital contour;
- self-support invariant.

Hard gates:

```text
bootstrap original capital unchanged
cash dividend = 0
internal transfer revenue = 0
recognised multiplier >= 3
risk invariant >= 1
keeper reimbursement >= actual keeper gas
keeper reimbursement < gross revenue
actual reinvestment = expected net profit after tax
```

Это режим compounding, а не обещание perpetual revenue.

---

# 8. QE Polygon Fork workflow

Файл: `.github/workflows/synergy-qe-polygon-fork.yml`.

Объединяет QE/QT fork harnesses, Aave/QuickSwap probes, renewable cycles и отчёты.

Проверяет конкретные deployed Polygon dependencies и локальные controllers. Fork funding/impersonation используется только для fixture setup.

Этот workflow нельзя трактовать как подтверждение того, что QE создаёт прибыль. Его смысл — проверить execution mechanics, repayment, reserve behavior и ограничения.

---

# 9. Full QE QT Relay Integration workflow

Файл: `.github/workflows/full-qe-qt-relay-test.yml`.

Проверяет:

- complete solvency/dividend/relay fork scenario;
- V2 tender refill на 1,000 cycles;
- Across-compatible relay adapter через test environment;
- отчёт artifact.

Ограничение: mock/fork relay не доказывает production delivery, relayer competition или refund behavior при реальном incident.

---

# 10. Hardhat test catalog

## Accounting and boundary

### `test/consolidated_internal_cycle_zero_pnl.js`

Доказывает, что большой внутренний оборот не создаёт external PnL/NAV.

### `test/external_mm_revenue_cycle.js`

Проверяет внешний market-maker revenue, liability accounting и repeated cycles.

### `test/dividend_external_profit_only.js`

Проверяет, что dividend bounded realised external profit и отклоняется без него.

### `test/zero_revenue_safe_pause.js`

Проверяет безопасную остановку при отсутствии external opportunity/revenue.

### `test/helpers/consolidatedFixture.js`

Создаёт единый fixture boundary/ledger/solvency/QE/QT/MM/dividend для integration tests.

## Stress

### `test/stress_redemptions.js`

Проверяет redemption pressure, liability retirement, reserve floors и mode response.

### `test/stress_gas_oracle_bridge.js`

Проверяет gas reserve, stale oracle и bridge availability gates.

## QE/QT

### `test/synergy_qe_polygon_fork.js`

Основной QE Polygon fork fixture.

### `test/qe_qt_integrated_solvency_polygon_fork.js`

Проверяет объединённый ledger/solvency/QE/QT contour с реальным WPOL.

### `test/qe_qt_v2_polygon_fork_renewable_cycle.js`

Проверяет повторяемый V2 tender/refill cycle.

### `test/synergy_qt_autonomy_20_cycles.js`

Проверяет bounded autonomous QT sequence и terminal conditions.

### `test/synergy_qt_buyback_fork.js`

Проверяет fork buyback/QT harness.

### `test/absolute_solvency_dividend_qt_fork.js`

Проверяет formal recovery до strict solvency при fixture assumptions.

### `test/absolute_solvency_dividend_relay_full_fork.js`

Проверяет recovery, dividend и relay в одном fork contour.

## V4/V5/V6/V7

### `test/real_liquidity_multiplier_v4_polygon_fork.js`

Связывает V4 multiplier model с реальной QuickSwap V3 fork environment.

### `test/synergy_growth_dividend_v5_unit.js`

Unit assertions V5 capital, profit, dividend/reinvestment и registry.

### `test/synergy_growth_dividend_v5_polygon_fork.js`

V5 Polygon fork representative liquidity and compounding fixture.

### `test/dividend_self_support_v6_polygon_fork.js`

V6 no-new-capital and keeper-cost fork fixture.

### `test/synergy_graph_arbitrage_v7_polygon_fork.js`

V7 exact topology, protected public edge, exits и profit gate.

---

# 11. Python simulation catalog

## `simulation/consolidated_solvency_v3.py`

Детерминированный consolidated balance-sheet model: reserves, liabilities, external PnL, expenses, dividends и coverage.

## `simulation/monte_carlo_v3.py`

Много траекторий V3; ищет insolvency, negative reserve, dividend violation и coverage breach.

## `simulation/stress_matrix_v3.py`

Перебирает явно заданные stress scenarios.

## `simulation/real_liquidity_multiplier_v4.py`

Детерминированная модель recognised liquidity multiplier.

## `simulation/monte_carlo_real_liquidity_multiplier_v4.py`

Monte Carlo multiplier/coverage model.

## `simulation/stress_real_liquidity_multiplier_v4.py`

Volatility, depth, gas, liability и emission stress для V4.

## `simulation/synergy_growth_dividend_v5.py`

Модель external profit compounding и permissioned liquidity V5.

## `simulation/dividend_self_support_v6.py`

No-new-capital, keeper reimbursement и reinvestment V6.

## `simulation/synergy_graph_arbitrage_v7.py`

Nine-pool graph, external dislocations, internal QE depth, graph cycles, cost deductions и fake-QE counterfactual.

## `simulation/run_synergy_graph_v7.py`

Entry point, создающий V7 deterministic и Monte Carlo reports.

---

# 12. Validator catalog

## `scripts/validate_consolidated_solvency.py`

Создаёт `SOLVENT SYSTEM: PASS/FAIL`, JSON verdict и русский consolidated report.

## `scripts/validate_real_liquidity_multiplier_v4.py`

Проверяет единый V4 invariant across deterministic, Monte Carlo, stress и fork results.

## `scripts/validate_synergy_growth_v5.py`

Проверяет V5 external-only profit, compounding, permissioned access и capital identities.

## `scripts/validate_dividend_self_support_v6.py`

Проверяет V6 no-new-capital and reinvestment identities.

## `scripts/validate_synergy_graph_v7.py`

Проверяет exact topology, graph size, external-only profit, fake QE rejection, fork access и public protections.

Validator должен:

- завершаться non-zero exit code при любом failed invariant;
- сохранять список `failed_invariants`;
- не скрывать negative result;
- включать limitations;
- записывать machine-readable JSON.

---

# 13. Evidence artifacts

V7 baseline artifact:

```text
name: synergy-v7-graph-arbitrage-evidence
artifact id: 8771099117
size: 13,698 bytes
digest: sha256:6f369bc68f6dedfa269507ff3683c4c11c745a5a50fda1505a35ac389c492646
head sha: 90273f12d356411af70bae0ba64265b7a83455cc
```

Evidence artifact обычно содержит:

- model logs;
- deterministic JSON;
- Monte Carlo JSON;
- Anvil log;
- fork-test log;
- fork result JSON;
- validator log;
- final verdict JSON.

Artifact digest следует сохранять в release record. Истёкший GitHub artifact не должен быть единственной копией production evidence.

---

# 14. Локальный запуск V7

```bash
npm ci
python -m pip install numpy

# Temporary debt in current workflow; fix source and remove before release.
perl -0pi -e 's/\breference\b/referencePrice/g' contracts/fork/SynergyQEForkHarness.sol

npx hardhat compile
python simulation/run_synergy_graph_v7.py

export POLYGON_RPC_URL=https://approved-archive-provider.example
export FORK_BLOCK_NUMBER=90790000
export LOCAL_FORK_URL=http://127.0.0.1:8545

anvil \
  --fork-url "$POLYGON_RPC_URL" \
  --fork-block-number "$FORK_BLOCK_NUMBER" \
  --chain-id 137 \
  --hardfork shanghai \
  --host 127.0.0.1 \
  --port 8545

npx hardhat test test/synergy_graph_arbitrage_v7_polygon_fork.js --network polygonFork
python scripts/validate_synergy_graph_v7.py
```

Запуск требует архивного RPC, способного вернуть состояние pinned block.

---

# 15. Reproducibility requirements

Каждый release evidence record должен фиксировать:

- git commit SHA;
- merge commit SHA, если применимо;
- compiler version и longVersion;
- optimizer/viaIR/EVM settings;
- npm lockfile digest;
- Python version и dependency versions;
- Foundry/Anvil version;
- fork provider class;
- fork block;
- chain id;
- external contract addresses;
- random seeds;
- environment variables без secrets;
- workflow run IDs;
- artifact IDs/digests;
- complete PASS/FAIL output.

Не допускается менять source через CI patch без отражения patched source digest. Предпочтительно полностью удалить runtime source patch.

---

# 16. Обязательные будущие тесты

До production необходимы:

## Contract security

- fuzz всех public/external functions;
- reentrancy across callback tokens/router/bridge;
- ERC-777/hooks;
- fee-on-transfer;
- rebasing token;
- false-return/no-return ERC-20;
- decimals mismatch;
- approval race and allowance exhaustion;
- malicious pair/router/oracle;
- duplicate/colliding source IDs;
- admin/operator/attester revocation;
- timelock bypass;
- pause/unpause.

## V7 route proof

- explicit token path;
- token0/token1 verification per pool;
- hop continuity;
- settlement start/end equality;
- cyclic route without repeated pool;
- real pre/post balance deltas;
- declared-vs-measured cost mismatch;
- forged externalEdge;
- pool whose code changes via proxy/selfdestruct semantics;
- stale/invalid exit depth.

## Oracle/MEV

- independent TWAP;
- stale round;
- zero/negative/overflowed quote;
- cross-source deviation;
- builder censorship;
- reveal leakage;
- sandwich simulation with adversarial ordering;
- reorg and delayed inclusion;
- private relay fallback.

## Economics

- no external opportunity for extended period;
- negative revenue months;
- gas 10×–100×;
- liquidity evaporation;
- stablecoin depeg;
- WPOL crash;
- correlated pool loss;
- bridge outage and refund delay;
- mass redemption;
- keeper monopoly/collusion;
- oracle disagreement;
- repeated QE with zero revenue;
- QT demand exhaustion.

## Operations

- monitoring outage;
- RPC inconsistency;
- artifact expiration;
- partial deployment;
- wrong constructor args;
- role transfer failure;
- compromised operator;
- emergency runbook rehearsal.

---

# 17. Правильная интерпретация PASS

Допустимая формулировка:

> На commit X конкретный workflow выполнил compile, модели, fork-test и validator без нарушения перечисленных инвариантов.

Недопустимые формулировки:

- «система гарантированно прибыльна»;
- «невозможен взлом»;
- «MEV полностью устранён»;
- «Monte Carlo доказал нулевой риск»;
- «fork-test равен mainnet deployment»;
- «все будущие рынки дадут тот же growth factor»;
- «7/7 workflows означают юридическое одобрение».

---

# 18. Release evidence checklist

```text
[ ] commit SHA recorded
[ ] source compiles without patch
[ ] all workflows completed, not merely queued
[ ] all validator failed_invariants arrays empty
[ ] fork block and provider recorded
[ ] no secrets in logs/artifacts
[ ] external addresses independently verified
[ ] artifact digests archived
[ ] model seeds recorded
[ ] limitations published beside metrics
[ ] security audit version linked
[ ] deployment bytecode matches tested bytecode
[ ] production parameters equal reviewed parameters
[ ] monitoring verifies the same invariants live
```

Только после выполнения checklist evidence может сопровождать release candidate.