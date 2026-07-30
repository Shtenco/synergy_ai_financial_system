# SYNERGY Contract Catalog

> Назначение: карта Solidity-контрактов исследовательской ветки `audit/synergy-qe-polygon-fork`.
>
> Это не deployment manifest. В репозитории одновременно находятся несколько поколений архитектуры — V2, V3, V4, V5, V6 и V7. Production release обязан явно выбрать только необходимый набор контрактов, версии и параметры.

---

## 1. Как читать каталог

Для каждого модуля указаны:

- **роль** — какую задачу решает контракт;
- **граница доверия** — какие данные, роли или внешние системы он принимает;
- **главный инвариант** — условие, которое модуль обязан сохранять;
- **статус** — core prototype, experimental harness, test-only либо legacy/research.

Общие правила всего каталога:

1. внутренние переводы не создают внешний PnL;
2. mint не создаёт резерв;
3. flash principal не является активом протокола;
4. market cap не входит в conservative NAV;
5. bridge переносит стоимость, но не создаёт её;
6. QE notional не является revenue;
7. QT internal inventory не уменьшает external liability;
8. дивиденды ограничены доказанным external PnL и платёжеспособностью;
9. off-chain optimizer предлагает действие, но on-chain gate обязан его ограничивать;
10. legacy и fork harness нельзя без отдельного review включать в production deployment.

---

# 2. Базовые V5-модули

## `contracts/SynergyV5Modules.sol`

Файл объединяет несколько контрактов V5.

### `ParticipantTaxRegistry`

**Роль:** on-chain eligibility/attestation registry для участников, keeper и операторов.

**Хранит:** registration flag, expiry attestation и hash внешней tax identity.

**Граница доверия:** attester. Контракт не вычисляет налоговое резидентство, KYC/AML или юридический статус самостоятельно.

**Инвариант:** eligible только зарегистрированный участник с неистёкшим attestation.

**Статус:** core prototype; требует внешней compliance-процедуры и governance attester.

### `AutoReinvestDividendControllerV5`

**Роль:** принимает только реальную внешнюю прибыль, формирует 10% dividend pool, удерживает налог и автоматически реинвестирует net portions owner/keeper.

**Граница доверия:** operator, boundary registry, risk gate, reinvestment engine и корректный reserve balance delta.

**Инварианты:**

- external payer не является system address;
- sourceId одноразовый;
- risk invariant пройден;
- фактический reserve delta равен declared gross profit;
- cash dividend отсутствует: net amounts возвращаются в productive capital.

**Статус:** V5 research/core prototype.

### `SynergyPermissionedPair`

**Роль:** constant-product AMM pair с eligibility gate.

**Свойства:** 30 bps fee, minimum liquidity, deadline, slippage checks, restricted LP behavior, стандартные Mint/Burn/Swap/Sync events.

**Граница доверия:** factory/router и `ParticipantTaxRegistry`.

**Инвариант:** constant-product reserve invariant после fee и запрет неразрешённого доступа.

**Статус:** V5 internal DEX primitive.

### `SynergyDexFactoryV5`

**Роль:** создаёт и индексирует permissioned pairs, управляет разрешёнными router.

**Инвариант:** одна pair на unordered token pair, только валидные адреса, контролируемый router set.

**Статус:** V5 internal DEX core.

### `SynergyDexRouterV5`

**Роль:** permissioned add/remove liquidity и swaps.

**Граница доверия:** registry, factory, pair implementation и caller-provided minima/deadline.

**Инвариант:** операция должна пройти eligibility, deadline, non-zero minima и pair-level invariant.

**Статус:** V5 internal DEX core.

### Прочие V5-компоненты файла

Файл также содержит интерфейсы и вспомогательные контуры, используемые V5 growth/dividend tests. Перед release следует разбить monolithic source на отдельные файлы либо зафиксировать точный deployment manifest.

---

# 3. Accounting

## `contracts/accounting/ConsolidatedLedger.sol`

**Роль:** консолидированный append-only ledger.

**Классифицирует:** internal transfer, external revenue/expense, liability issuance/redemption, inventory, dividend и loss.

**Граница доверия:** recorder role, `SystemBoundaryRegistry`, balanceOf reserve asset и одноразовый sourceId.

**Главные инварианты:**

- internal transfer не меняет external PnL/NAV;
- external revenue требует внешнего payer и фактического balance delta;
- capital inflow с liability не является прибылью;
- inventory burn не уменьшает external liabilities;
- sourceId нельзя использовать повторно;
- каждая запись включается в append-only `ledgerRoot`.

**Статус:** консолидированный V3 core prototype; центральный источник бухгалтерской правды.

---

# 4. Policy и risk

## `contracts/policy/SystemBoundaryRegistry.sol`

**Роль:** определяет консолидированную границу системы.

**Главный инвариант:** перевод между двумя system addresses является внутренним и не может признаваться external revenue.

**Граница доверия:** admin, который обязан регистрировать не только формально принадлежащие адреса, но и фактически контролируемые/связанные контуры.

**Статус:** core prototype; требует multisig/timelock в production.

## `contracts/policy/SolvencyController.sol`

**Роль:** вычисляет conservative haircut assets, stress liabilities, NAV, solvency, liquidity, gas и reserve-policy coverage; переключает operational mode.

**Основные пороги:**

- normal solvency 120%;
- defensive solvency 105%;
- liquidity coverage 120%;
- gas coverage 120%;
- reserve-policy ratio 70%.

**Режимы:** BOOTSTRAP, RECOVERY, NORMAL, DEFENSIVE, PAUSED, DIVIDEND, EMERGENCY.

**Главные инварианты:**

- market cap исключён из NAV;
- операция разрешена только при positive expected external margin;
- stale oracle, unavailable bridge или отсутствие opportunity блокируют execution;
- dividend ограничен realized external PnL и положительным NAV после buffers.

**Статус:** core risk prototype.

## `contracts/policy/RealLiquidityMultiplierInvariant.sol`

**Роль:** единый скалярный gate для политики 3–5× recognised real liquidity.

**Цели:**

- sigma ≤ 2.5% → 5×;
- sigma ≤ 7% → 4×;
- sigma ≤ 12% → 3×;
- выше 12% → unsupported/fail.

**Главные инварианты:**

- recognised liquidity не может превышать 5× net external capital;
- internal transfer revenue обязан быть нулём;
- solvency, liquidity, gas и emission coverage не ниже 120%;
- anchor pool depth выше floor;
- snapshot одноразовый.

**Статус:** V4 risk gate prototype. «Multiplier» означает stress-equivalent executable depth, а не withdrawable POL, market cap или nominal TVL.

## `contracts/policy/SynergyV6SelfSupport.sol`

### `AutoReinvestDividendControllerV6`

**Роль:** сначала покрывает bounded keeper reimbursement, затем распределяет только net external profit между retained reinvestment, owner/keeper reinvestment и tax escrow.

**Инварианты:**

- bootstrap original capital неизменен;
- internal transfer revenue равен нулю;
- keeper reimbursement ограничен percentage cap и меньше gross revenue;
- risk invariant пройден;
- payer действительно внешний;
- sourceId одноразовый.

### `DividendSelfSupportInvariantV6`

**Роль:** сводит доказательство no-new-capital self-support к одному scalar invariant.

**Hard gates:**

- current original capital равен bootstrap capital;
- cash dividend равен нулю;
- internal transfer revenue равен нулю;
- recognised multiplier ≥ 3×;
- risk invariant ≥ 1.0;
- reimbursement покрывает фактический keeper gas;
- capital и reinvestment identities совпадают.

**Статус:** V6 research/core prototype.

---

# 5. QE

## `contracts/qe/BackedReserveQE.sol`

**Роль:** перераспределяет часть реального excess reserve по системным buckets.

**Buckets:** LIQUIDITY, BRIDGE, INSURANCE, PRODUCTIVE_YIELD.

**Граница доверия:** operator, solvency controller, ledger, boundary registry и reserve token.

**Главные инварианты:**

- нет mint;
- нет buyback, dividend или operations path;
- allocation только из фактического balance и `excessReserve()`;
- fraction cap ≤ 20% excess reserve;
- rolling monthly cap;
- destination является system address;
- работа только в NORMAL mode;
- операция записывается как internal transfer.

**Статус:** consolidated QE core prototype.

---

# 6. QT

## `contracts/qt/ExternalLiabilityQT.sol`

**Роль:** отделяет погашение внешнего обязательства от сжигания внутреннего inventory.

### `externalTenderAndBurn`

External holder продаёт токен системе; система выплачивает reserve, сжигает токен и уменьшает external liability. Разница между stress value и payment может стать discount profit после external costs и solvency gate.

### `retireInternalInventory`

Сжигает protocol inventory без revenue, PnL или уменьшения external liabilities.

**Главный инвариант:** только токен независимого внешнего holder может уменьшить external liability.

**Статус:** consolidated QT core prototype.

---

# 7. Market making

## `contracts/mm/ExternalRevenueMarketMaker.sol`

**Роль:** protocol-owned market maker, который принимает revenue только от внешнего контрагента.

**Потоки:**

- external sale: payment делится на backing liability и realised spread;
- external strategy revenue: reserve tokens фактически поступают от внешнего payer;
- internal reserve transfer: записывается как internal transfer.

**Инварианты:**

- system buyer/payer запрещён для revenue;
- payment должен превышать liability issued;
- external costs меньше spread;
- solvency разрешает trade;
- inventory и pool depth не нарушены;
- reserve balance delta доказан ledger.

**Статус:** consolidated MM prototype.

---

# 8. Dividend

## `contracts/dividend/ExternalProfitDividendVault.sol`

**Роль:** выплачивает cash dividend только из ledger-proven realised external profit.

**Ограничения:** local reserve, payout rate, dividendable capital, 120% solvency/liquidity/gas, 70% reserve-policy ratio и внешний recipient.

**Главный инвариант:** cumulative dividends не превышают realised external PnL и не повреждают buffers.

**Статус:** consolidated dividend prototype. В V5/V6 параллельно исследуется auto-reinvestment вместо cash payout.

---

# 9. Liquidity engines

## `contracts/liquidity/TriangularLiquidityEngineV4.sol`

**Роль:** V4-контур распределения реального капитала и оценки multiplier/liquidity policy.

**Статус:** исследовательское поколение V4. Используется совместно с `RealLiquidityMultiplierInvariant` и V4 workflow; не смешивать автоматически с V5/V7 topology.

## `contracts/liquidity/TriangularLiquidityEngineV5.sol`

**Роль:** размещает original external capital и reinvested realised profit, создаёт representative SYNA/SYNR positions и хранит отдельные accounting buckets.

**Бюджетные константы baseline V5:**

- LP 54%;
- liquid reserve 30%;
- insurance 10%;
- gas 5%;
- operations 1%.

**Инварианты:**

- original capital отделён от reinvested/retained profit;
- internal emission не является external revenue;
- min position amounts ненулевые;
- finite deadline;
- representative wallet-to-wallet routing ограничен trusted endpoint.

**Статус:** V5 liquidity prototype; V7 использует отдельный topology contract.

---

# 10. Graph V7

## `contracts/graph/SynergyGraphArbitrageV7.sol`

Файл содержит пять главных контрактов.

### `SynergyRepresentativeTokenV7`

**Роль:** публичный representative SYNA.

**Инвариант:** transfer должен касаться public pool через protected gateway, internal pair или trusted infrastructure; произвольный wallet-to-wallet transfer запрещён.

### `SynergyInternalReserveTokenV7`

**Роль:** внутренний SYNR.

**Инвариант:** transfer разрешён только через internal endpoint/engine.

### `SynergyTopologyV7`

**Роль:** фиксирует exact six-pool internal complete graph и создаёт единственный официальный public WPOL/SYNA pool.

**Инварианты:**

- internal factory содержит ровно 6 pairs;
- addresses ненулевые, уникальные и имеют code;
- public pool создаётся только после internal topology и protected gateway;
- при создании отсутствуют public WPOL/SYNR, SYNA/SYNR, USDT/SYNA, USDT/SYNR;
- liquidity position имеет ненулевые amounts и minima.

**Ограничение:** permissionless public factory позволяет третьей стороне создать пару позднее; нужна transfer restriction и monitoring.

### `ExternalExitPoolRegistryV7`

**Роль:** allowlist внешних WPOL/USDT exit pools QuickSwap V2/V3.

**Инвариант:** только правильная token pair, известный kind и minimum token balances.

**Ограничение:** fork thresholds `1` base unit — test-only.

### `SynergyGraphProfitGateV7`

**Роль:** owner-bound commit/reveal acceptance gate для hybrid internal/external route.

**Вычитает:** gas, pool fees, slippage, flash premium и internal value loss.

**Инварианты:**

- eligible keeper;
- unique commit и replay prevention;
- one-block minimum delay;
- WPOL/USDT settlement;
- минимум один internal и один external pool;
- QE notional не считается revenue;
- QE требует internal value loss;
- QT burn ≤ external net profit.

**Критическое ограничение baseline:** proof содержит pool membership, но не token path и не доказывает adjacency каждого hop. Gate также принимает declared amountOut/costs вместо атомарного измерения фактических balances. До production нужен atomic executor и token-route proof.

### `PublicRepresentativeProtectionV7`

**Роль:** commit/reveal и quote bounds для public WPOL/SYNA edge.

**Baseline hard caps:**

- max oracle deviation 3%;
- max sandwich loss 1%;
- max deadline window 15 минут;
- minimum delay задаётся immutable constructor parameter.

**Критическое ограничение:** `oracleOut`, `routerOut` и `postTradeQuote` передаются caller; контракт не читает независимый oracle и не выполняет swap. Требуется atomic trusted-oracle adapter.

**Статус файла:** главный V7 prototype, прошедший fork/Monte Carlo acceptance, но не production-ready.

---

# 11. Bridge

## `contracts/bridge/AcrossMainnetDividendRelay.sol`

**Роль:** ownerless narrow adapter, отправляющий весь pending WPOL через Across V3 одному immutable Ethereum recipient.

**Инварианты:**

- destination chain permanently Ethereum mainnet;
- immutable recipient/token/spoke pool;
- output amount ограничен maximum relay fee;
- quote age ≤ 10 минут;
- fill window 5 минут–2 часа;
- no arbitrary calls, withdrawals, owner или upgrade hook;
- reentrancy guard.

**Статус:** bridge prototype с узкой поверхностью; требует реального Across integration review и failure/refund monitoring.

## `contracts/bridge/MockAcrossSpokePoolV3.sol`

**Роль:** test double интерфейса Across SpokePool.

**Статус:** test-only. Никогда не использовать как production bridge.

---

# 12. Fork, flash и recovery harnesses

## `contracts/fork/AaveFlashProbe.sol`

**Роль:** минимально проверяет поддержку `flashLoanSimple` выбранным Aave Polygon reserve независимо от QE logic.

**Инвариант:** callback только от configured pool, initiator = self, asset совпадает, principal+premium approved.

**Статус:** diagnostic/fork-test only.

## `contracts/fork/AaveFlashQESolverV2.sol`

**Роль:** Aave V3-compatible flash receiver для closed/open QE/QT fork scenarios.

**Функции:** commit auction, execute closed/open route, enforce min profit, claim settled profit оператором.

**Граница доверия:** immutable operator, Aave pool, demand/auction contracts и выбранная external pair.

**Статус:** V2 fork audit harness; не production solver без отдельного audit.

## `contracts/fork/ForkFlashLender.sol`

**Роль:** локальный flash lender для fork/integration fixtures, когда нужен детерминированный источник временной ликвидности.

**Статус:** test/fork only, не реальный lender.

## `contracts/fork/SynergyQEForkHarness.sol`

**Роль:** собирает QE/fork fixture и Polygon integration paths.

**Особый технический долг:** CI сейчас заменяет reserved identifier `reference` через `perl` перед compile. Source должен быть исправлен так, чтобы собираться без runtime patch.

**Статус:** fork harness, не production contract.

## `contracts/fork/SynergyQTBuybackHarness.sol`

**Роль:** тестовый QT/buyback contour на fork.

**Статус:** fork harness. Его balance and profit semantics не должны заменять consolidated ledger.

## `contracts/fork/BackedQETenderQTControllerV2.sol`

**Роль:** V2 bounded QE/tender/QT recovery controller с auction/commit-reveal и refill logic.

**Статус:** research recovery generation; assumptions должны проверяться отдельно.

## `contracts/fork/AutonomousQTController.sol`

**Роль:** автоматизирует последовательность QT cycles и terminal conditions.

**Статус:** research/fork prototype. Автономность не отменяет solvency, demand и reserve assumptions.

## `contracts/fork/AbsoluteSolvencyDividendQTController.sol`

**Роль:** реализует сценарий восстановления under-collateralized balance sheet до ≥100% coverage с bounded cycles и terminal halt.

**Статус:** formal recovery experiment, основанный на конкретных fixture assumptions; не универсальная гарантия восстановления.

---

# 13. Test contracts

## `contracts/test/ConsolidatedCycleBatchHarness.sol`

**Роль:** batch execution для большого числа deterministic accounting cycles.

**Статус:** test-only.

## `contracts/test/MockReserveAsset.sol`

**Роль:** управляемый reserve token fixture.

**Статус:** test-only; не production reserve.

## `contracts/test/SynergyTopologyV7Harness.sol`

**Роль:** расширяет/оборачивает V7 topology функциями, необходимыми для fork fixture — например, mint internal inventory или infrastructure configuration.

**Статус:** test-only. Production topology не должен автоматически включать harness-only полномочия.

---

# 14. Deployment selection rules

Production release нельзя строить командой «deploy all contracts».

Нужен manifest вида:

```yaml
release: synergy-v7-rc1
chain_id: 137
contracts:
  boundary:
    source: contracts/policy/SystemBoundaryRegistry.sol
    contract: SystemBoundaryRegistry
  ledger:
    source: contracts/accounting/ConsolidatedLedger.sol
    contract: ConsolidatedLedger
  solvency:
    source: contracts/policy/SolvencyController.sol
    contract: SolvencyController
  internal_dex_factory:
    source: contracts/SynergyV5Modules.sol
    contract: SynergyDexFactoryV5
  internal_dex_router:
    source: contracts/SynergyV5Modules.sol
    contract: SynergyDexRouterV5
  topology:
    source: contracts/graph/SynergyGraphArbitrageV7.sol
    contract: SynergyTopologyV7
excluded:
  - contracts/test/**
  - contracts/fork/**
  - MockAcrossSpokePoolV3
```

Для каждого deployed contract manifest должен фиксировать:

- compiler and optimizer settings;
- constructor arguments;
- bytecode hash;
- deployed address;
- owner/admin/operator/reporter/attester;
- proxy/implementation relationship либо explicit non-upgradeability;
- token decimals;
- external dependencies and chain addresses;
- limits and thresholds;
- source verification URL;
- audit report version.

---

# 15. Production blockers, выявленные каталогом

1. Исправить source compile без `perl` patch.
2. Добавить token path и hop adjacency в V7 proof.
3. Объединить proof acceptance с atomic execution и real balance deltas.
4. Подключить independent oracle/TWAP/M-of-N вместо caller-supplied oracleOut.
5. Установить economic exit depth thresholds.
6. Перевести admin/operator на multisig/timelock/guardian model.
7. Отделить test harness bytecode от release artifact.
8. Создать release-specific manifest и удалить ambiguity V2–V7.
9. Провести hostile-token, reentrancy, bridge-failure и adversarial-MEV testing.
10. Получить независимые аудиты до funding.

---

# 16. Источник правды

При конфликте документов приоритет следующий:

1. verified deployed bytecode и immutable configuration;
2. release manifest;
3. production contract source at exact commit;
4. automated acceptance validator and evidence artifact;
5. эта документация;
6. старые research notes и маркетинговые материалы.

Ни один текст не может превратить экспериментальный harness в production-ready contract или модельный результат в гарантированную доходность.