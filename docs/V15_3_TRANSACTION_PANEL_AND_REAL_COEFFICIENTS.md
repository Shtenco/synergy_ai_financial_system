# SYNERGY V15.3 — transaction-level panel и реальные коэффициенты

## Цель

V15.3 переводит проект от сценарных параметров V15.2 к эмпирической политике исполнения.

Жёсткая задача:

```text
исполнять только когда:

realized aggregate net edge after all costs >= 2.685148 bps

и одновременно:

predicted one-sided 95% lower bound >= 2.685148 bps
solver net after gas > 0
route closes atomically
fixture principal, bonds and internal mint/burn are not revenue
```

После строгого исполнения:

```text
reinvested external capital = 80% × realized net protocol revenue
```

Прогноз, block-end mark, внутренний transfer, refundable bond и fixture principal не реинвестируются.

---

## 1. Немедленный реальный empirical prior из V14

До сбора transaction-level panel повторно обработан строгий evidence-пакет V14:

- GitHub Actions run: `30709889373`;
- artifact: `synergy-v14-strict-stateful-closed-loop-evidence`;
- digest: `sha256:b7f6876dcb0ac0f5491d01c45acfda5fcbb4be3b7eadeda79cfca9e5aa50f935`;
- Polygon blocks: `91,266,209–91,266,308`;
- exact candidates: `396`;
- strict accepted cycles: `0`;
- best reverse-funding near-miss observations: `66`.

Машинный prior находится в:

`economics/v15_3_v14_empirical_prior.json`

### Самая сильная route family

```text
forward:     DAI -> USDT [V3]
restoration: USDT -> USDC [V3] -> DAI [V3]
observations: 33
```

Реальные block-state характеристики:

- среднее улучшение до +$0.01 strict profit: `2.931062 bps`;
- медиана: `2.908384 bps`;
- лучший исторический минимум: `2.685150946 bps`;
- медианный pre-gas deficit: `1.191641 bps`;
- медианный gas burden: `1.496541 bps`.

Это даёт важную экономическую декомпозицию:

```text
strict hurdle ≈ market/reverse-route deficit + execution gas + profit floor

2.908384 bps ≈ 1.191641 bps + 1.496541 bps + 0.220202 bps
```

Следовательно, задача V15.3 не состоит в поиске десятков процентов доходности. Нужен внешний order-flow displacement, RFQ improvement или solver surplus примерно на несколько дополнительных базисных пунктов.

### Реальный route-family effect

По сравнению с худшей наблюдавшейся V14 family использование V3/V3 restoration уменьшило средний требуемый hurdle примерно на:

```text
-20.813300 bps
```

Это описательный fixed effect, а не live execution coefficient. Но он уже показывает, что выбор venue family важнее косметической настройки mint/burn.

---

## 2. Почему нужен transaction-level panel

V14 — block-state strict shadow. Он доказал бухгалтерию, но не измерил непосредственную причинную связь:

```text
конкретная victim transaction
-> изменение pool state
-> появление cross-venue spread
-> фактически исполненный backrun
-> net profit после всего gas
```

V15.3 строит эту связь на уровне отдельных транзакций.

Первая эмпирическая market cell намеренно узкая:

```text
victim venue: QuickSwap V2 USDC -> WPOL
source venue: Uniswap V3 USDC -> WPOL
backrun:      Uniswap V3 USDC -> WPOL -> QuickSwap V2 WPOL -> USDC
settlement:   USDC
chain:        Polygon PoS, chain id 137
```

Узкая первая cell нужна для идентифицируемости. После накопления достаточной выборки тот же schema расширяется на USDT/WPOL, WETH/stable и дополнительные DEX/RFQ families.

---

## 3. Raw transaction panel

Collector:

`scripts/collect_polygon_transaction_panel_v15_3.js`

Он сканирует реальные успешные QuickSwap V2 router transactions и сохраняет JSONL:

`reports/v15_3_transaction_panel_raw.jsonl`

Для каждой строки фиксируются:

- transaction hash, block, timestamp и transaction index;
- реальный amount in USDC и amount out WPOL;
- pre-block и post-block reserves QuickSwap V2;
- victim amount / target TVL;
- фактический price impact;
- pre-victim Uniswap V3 -> QuickSwap V2 roundtrip quote;
- block-end изменение quote как diagnostic-only variable;
- rolling realized volatility;
- actual victim gas;
- base fee и priority fee;
- предварительная стоимость V15.1 route gas;
- calldata hash и адреса venue.

Raw panel имеет класс:

`ACTUAL_POLYGON_TRANSACTION_BLOCK_BOUNDARY_FEATURES`

Его counted revenue всегда равно нулю.

Block-end fields не допускаются в live execution model, потому что они содержат информацию из будущего относительно момента bundle submission.

---

## 4. Strict fork replay

Orchestrator:

`scripts/replay_transaction_panel_v15_3.py`

Для равномерно распределённой по времени подвыборки он:

1. запускает чистый Anvil fork на блоке `N-1`;
2. передаёт реальный transaction hash в существующий V15.1 historical harness;
3. повторяет оригинального sender, target, calldata и value;
4. ставит victim и V15.1 backrun в один mined block;
5. выполняет реальный Uniswap V3 -> QuickSwap V2 route;
6. учитывает фактический operational gas;
7. исключает fixture principal, solver bonds и внутреннюю эмиссию;
8. проверяет нулевой settlement residue;
9. пересчитывает V15.3 net edge независимо от V15.1 status.

Главная формула строки:

```text
aggregate_net_profit =
    gross_route_profit
  - operational_gas
  - flash_premium
  - bridge_cost
  - mev_loss
  - protocol_lp_damage
  - liability_increase

aggregate_net_edge_bps =
    aggregate_net_profit / principal × 10,000
```

Строка считается strict PASS только если:

```text
aggregate_net_edge_bps >= 2.685148
solver_net_after_gas > 0
victim_before_backrun == true
same_block == true
engine_settlement_residue == 0
fixture_principal_counted == false
bond_counted == false
internal_mint_burn_counted == false
```

---

## 5. Эконометрическая модель

Estimator:

`econometrics/estimate_transaction_panel_v15_3.py`

Target:

```text
aggregate_net_edge_bps_after_all_costs
```

Live-eligible features:

1. `log_victim_notional_usdc`;
2. `log_target_tvl_usdc`;
3. `victim_amount_to_tvl_bps`;
4. `victim_price_impact_bps`;
5. `pre_roundtrip_gross_edge_bps`;
6. `realized_volatility_bps`;
7. `estimated_route_gas_bps`;
8. `base_fee_gwei`;
9. `priority_fee_gwei`.

Запрещены как predictors:

- block-end displacement;
- post-minus-pre block-end edge;
- transaction index fraction;
- realized route output;
- realized gas;
- treasury revenue;
- сам target.

### Метод оценки

- time-ordered train/holdout split;
- standardized ridge regression;
- coefficient conversion обратно в original units;
- circular contiguous block bootstrap;
- 500 bootstrap replications;
- one-sided 95% lower prediction bound;
- out-of-sample confusion matrix относительно hurdle `2.685148 bps`.

Исполнение разрешается не по point forecast:

```text
predicted edge >= hurdle
```

а по более строгому правилу:

```text
bootstrap P05(predicted net edge) >= 2.685148 bps
```

Так модель должна пережить model uncertainty, а не только показать красивый средний прогноз.

---

## 6. Капитализация 80%

Для каждой out-of-sample строки:

```text
model_execute = predicted_P05 >= 2.685148 bps
actual_pass   = realized_net_edge >= 2.685148 bps
```

Деньги учитываются только при одновременном выполнении:

```text
model_execute && actual_pass
```

Тогда:

```text
counted_protocol_revenue = realized treasury net after shared costs
reinvested                = 0.80 × counted_protocol_revenue
retained_not_reinvested   = 0.20 × counted_protocol_revenue
```

False positive расходует gas, но не создаёт revenue.

False negative не создаёт убыток principal, но означает упущенную возможность и учитывается через recall.

---

## 7. Minimum evidence gate

Реальные коэффициенты не публикуются при малой выборке.

Минимум:

- `30` valid strict replay rows;
- не менее `20` training rows;
- не менее `8` holdout rows.

При меньшей выборке status обязан быть:

`INSUFFICIENT_REPLAY_ROWS`

В этом режиме:

- coefficients = `null`;
- counted revenue = `0`;
- reinvestment = `0`;
- no economic PASS.

---

## 8. Fail-closed validator

Validator:

`scripts/validate_transaction_panel_v15_3.py`

Он независимо пересчитывает:

- `2.685148 bps` threshold;
- `80%` reinvestment;
- gross profit минус все cost buckets;
- net edge;
- V15.3 strict PASS каждой replay row;
- zero revenue для FAIL/ERROR;
- отсутствие post-state leakage в predictors;
- time split;
- lower-bound execution decisions;
- holdout counted revenue;
- holdout reinvestment.

Validator PASS означает корректность evidence pipeline. Только status
`TRANSACTION_LEVEL_COEFFICIENTS_ESTIMATED` означает, что минимальная реальная выборка собрана и коэффициенты действительно оценены.

---

## 9. Команды

```bash
npm run panel:v15.3:collect
npm run panel:v15.3:replay
npm run panel:v15.3:estimate
npm run panel:v15.3:validate
npm run test:v15.3:econometrics
```

Полный historical run требует `POLYGON_RPC_URL`, Foundry/Anvil, Node.js и Python.

Пример:

```bash
export POLYGON_RPC_URL="https://your-archive-polygon-rpc"
export V153_START_BLOCK=91250000
export V153_END_BLOCK=91266308
export V153_MAX_RAW_ROWS=250
export V153_REPLAY_LIMIT=40

npm run panel:v15.3:collect
npm run panel:v15.3:replay
npm run panel:v15.3:estimate
npm run panel:v15.3:validate
```

---

## 10. Текущий честный статус

Готовы и проверены локально:

- panel specification;
- actual-chain collector source;
- strict replay orchestrator;
- time-split ridge estimator;
- block-bootstrap lower-bound gate;
- 80% reinvestment policy;
- fail-closed validator;
- deterministic unit tests;
- real V14 66-row empirical prior.

Пока не заявляется:

- transaction-level coefficient estimate на минимуме 30 strict replays;
- положительный out-of-sample execution precision;
- live Polygon revenue;
- production readiness.

Причина не экономическая, а execution-status: текущие GitHub-hosted jobs этого репозитория завершаются до первого шага с `steps: null`. Поэтому V15.3 workflow добавлен, но runner-certified panel и coefficients должны считаться несуществующими до появления artifact с фактическими строками.

---

## Экономический вывод

Строгий рубеж стал намного конкретнее.

V14 показала, что лучший public closed-loop находился практически ровно у границы `2.685148 bps`, а медиана сильнейшей route family требовала около `2.91 bps` улучшения.

Следовательно, экономическая гипотеза V15.3 фальсифицируема:

> Реальные крупные USDC -> WPOL transactions должны создавать такой displacement, при котором V15.1 atomic backrun после всех расходов систематически превышает 2.685148 bps, а pre-trade features позволяют выделять эти события с положительной out-of-sample precision.

Если transaction panel этого не покажет, система не должна исполнять сделки и реинвестировать средства. Если покажет — появляется первая эмпирически оценённая revenue function проекта.
