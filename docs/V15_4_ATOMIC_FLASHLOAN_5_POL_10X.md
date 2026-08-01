# SYNERGY V15.4 — atomic flashloan с комиссией 5 POL × 10

## Задача

Проверить не обычный процентный Aave premium, а более жёсткое условие:

```text
фиксированная комиссия каждого flashloan = 5 WPOL
число flashloan в одной транзакции = 10
strict net edge after fee >= 2.685148 bps
reinvestment = 80% фактической net protocol profit
```

На Polygon on-chain расчёты выполняются в WPOL. Экономически 5 WPOL соответствуют 5 POL.

## Атомарное правило

Для principal `P` и gross route profit `G`:

```text
net protocol profit = G - 5 WPOL
net edge bps = (G - 5) / P × 10 000
```

Цикл принимается только если:

```text
G >= 5 WPOL
(G - 5) / P × 10 000 >= 2.685148 bps
```

Следовательно:

```text
minimum gross route profit = 5 + P × 2.685148 / 10 000
```

Для principal `1 000 WPOL`:

```text
minimum gross route profit = 5.2685148 WPOL
```

## Три исхода

### 1. Gross route profit ниже 5 WPOL

Lender не получает principal + fixed fee. Callback или repayment invariant откатывает всю транзакцию.

```text
completed cycles = 0
paid flash fees = 0
counted revenue = 0
reinvestment = 0
```

### 2. Gross profit от 5 до 5.2685148 WPOL

Principal и комиссия формально покрываются, но post-fee edge ниже 2.685148 bps. Строгий policy gate откатывает транзакцию.

### 3. Gross profit выше 5.2685148 WPOL

Цикл может закрыться, если выполнены остальные инварианты. Пример при gross profit `6 WPOL`:

```text
principal:               1 000 WPOL
route gross profit:          6 WPOL
flash fee:                   5 WPOL
net protocol profit:         1 WPOL
net edge:                   10 bps
reinvestment:              0.8 WPOL
retained:                  0.2 WPOL
```

За 10 циклов:

```text
gross route profit:        60 WPOL
flash fees:                50 WPOL
net protocol profit:       10 WPOL
reinvestment 80%:           8 WPOL
retained capital:           2 WPOL
```

## Ключевой тест полного rollback

V15.4 моделирует:

- циклы 1–9 дают `6 WPOL gross`;
- цикл 10 даёт `5.2 WPOL gross`;
- net десятого цикла равен `0.2 WPOL = 2 bps` на principal 1 000 WPOL;
- strict threshold не пройден.

Поскольку все 10 flashloan находятся в одной EVM transaction, откатываются:

- первые девять успешных callback;
- 45 WPOL предполагаемых lender fees;
- 9 WPOL предполагаемой system profit;
- reinvestment transfers;
- route counters;
- lender counters;
- все token balances.

Финальный результат равен нулю, а не прибыли первых девяти циклов.

## Реализованные файлы

```text
contracts/v15_4/AtomicFixedFeeFlashV154.sol
test/atomic_flashloan_5pol_10x_v15_4.js
simulation/atomic_flashloan_5pol_10x_v15_4.py
scripts/validate_atomic_flashloan_v15_4.py
.github/workflows/atomic-flashloan-5pol-v15-4.yml
```

## Что именно доказывает structural PASS

- точную fixed fee 5 WPOL;
- возврат principal;
- полный rollback десятициклового batch;
- strict 2.685148 bps после комиссии;
- отсутствие pre-funded receiver subsidy;
- отсутствие settlement residue;
- точное распределение 80/20.

Structural route финансируется тестовым внешним inventory. Поэтому результат `10 WPOL net` является проверкой механики, а не доказательством наличия такого live edge на Polygon.

## Требование к реальному рынку

При фиксированной комиссии 5 WPOL малая сделка экономически бессмысленна. Чем меньше gross edge, тем больше требуется principal.

Примеры без дополнительного газа:

| Gross route edge до fixed fee | Минимальный principal для сохранения 2.685148 bps net |
|---:|---:|
| 3 bps | ~158 805 WPOL |
| 4 bps | ~38 027 WPOL |
| 5 bps | ~21 600 WPOL |
| 7.5 bps | ~10 385 WPOL |
| 10 bps | ~6 835 WPOL |
| 20 bps | ~2 888 WPOL |
| 50 bps | ~1 057 WPOL |
| 100 bps | ~514 WPOL |

Газ, slippage, MEV loss и Aave premium увеличат необходимый principal или необходимый gross edge.

## Экономический вывод

Flashloan не создаёт прибыль. Он масштабирует найденный внешний edge.

При `G < 5.2685148 WPOL` на principal 1 000 WPOL V15.4 откатывается.

При `G = 6 WPOL` каждый цикл приносит системе `1 WPOL net`; десять циклов дают `10 WPOL`, из которых `8 WPOL` реинвестируются.

Реальный ответ для Polygon можно получить только после включения V15.4 в transaction-level fork panel и замены structural route фактическими DEX/RFQ котировками.
