# SYNERGY V15.5 — compiler artifact и Polygon archive-fork закрыты

## Финальный статус

```text
Solidity compiler artifact:    PASS
Polygon archive-fork artifact: PASS
Mainnet broadcast:             НЕ ВЫПОЛНЯЛСЯ
Потрачено реальных POL:        0
Counted live revenue:          0
```

## Привязка точного исходника

Компилировался точный файл из ветки `audit/stateful-supercycle-v8`:

```text
contracts/v15_5/MainnetAtomicAddLpExperimentV155.sol
Git blob SHA: ad85d886f2797b030a89d2aa0b15f4a5c1446939
SHA-256:      db91b560ad3cce8851f9c7f044f365cfd878ffc48c2522b3332515da3cdad825
```

Интеграционный тест также побайтово совпал с PR №8:

```text
test/v15_5_mainnet_addlp_polygon_fork.js
Git blob SHA: f575fcb646af1c39ace6a0190f2e3886aaa37fa6
SHA-256:      81bd447707e8d47faefbf0127dd11fdd49b6a202ae73d320b13759f586be421f
```

## Solidity compiler artifact

Фактически выполнено:

```text
solc:          0.8.26+commit.8a97fa7a.Emscripten.clang
Hardhat:       2.22.19
optimizer:     enabled, 500 runs
viaIR:         true
EVM target:    cancun
compiled files: 11
```

Основной контракт:

```text
artifact SHA-256:          c502538a50010eaed37faee344ba552eff46f4bcc1552379c83a91282f813fde
ABI SHA-256:               2508450eec4555345782dfb95fcb69848f77def7183660ce18e9cec83ba23798
creation bytecode bytes:   19 581
creation bytecode SHA-256: 525b062d2fbc441210ed7d091e10152f1f7b0961ce53c185b48bd63e9cd655cc
deployed bytecode bytes:   13 817
deployed bytecode SHA-256: e50f3ccd64581ca91cb5adb597be4a44e9c43c23f1ad62c8f43047d5114676ef
build-info SHA-256:        c76d4641da21f00ebb98a57090817ab1d411e1d8d6edb0fa1fd40947496d5d45
```

## Polygon archive-fork artifact

Fork зафиксирован на:

```text
chain ID:    137
block:       90 000 000
block hash:  0xb179e0aca3a467061947d4d7e699926aa3109da807e6bc2e2546113d55f66f1f
RPC host:    polygon.drpc.org
```

Archive-capability доказана отдельными historical calls:

- старый блок возвращён с ожидаемым номером и хэшем;
- исторический код WPOL доступен;
- исторический код Aave V3 Pool доступен;
- historical state call возвращает значение;
- chain ID равен 137.

## Реальный integration path

На fork использованы реальные состояния:

```text
Aave V3 Pool:
0x794a61358D6845594F94dc1DB02A252b5b4814aD

WPOL:
0x0d500B1d8E8eF31E21C99d1Db9A6444d3ADf1270

QuickSwap V2 Router:
0xa5E0829CaCEd8fFDD4De3c43696c57F7D7A678ff

QuickSwap V2 Factory:
0x5757371414417b8C6CAad45bAeF941aBc7d3Ab32
```

Выполнен сценарий:

```text
seed two isolated QuickSwap pools: 0.2 POL total
Aave flash principal:              100 WPOL
ADDLP pool A
ADDLP pool B
reversible gradient A
reversible gradient B
REMOVE-LP A
REMOVE-LP B
restore state
attempt repay principal + premium
```

Фактический результат:

```text
actual outcome:                    ATOMIC_REVERT
pools restored exactly:            true
Aave liquidity restored exactly:   true
experiment-token supply restored:  true
completed cycles:                  0
counted revenue:                   0 WPOL
reinvestment:                      0 WPOL
```

Это подтверждает нулевую гипотезу: закрытый внутренний цикл из ADDLP, обратимых swap, mint и burn не создаёт внешний WPOL surplus, необходимый для выплаты Aave premium и прохождения строгого net-edge gate.

## Evidence provenance

```text
GitHub Actions run: 30722463478
job:                91428359512
conclusion:         success
artifact ID:        8825296639
artifact digest:    sha256:76eb1da31fad92a7852ef77f5d248c067b7aef1746e7597cd491f25041f666c3
public evidence commit:
2ed3a659ed3337a98d6d9417af601f60d563825b
```

Полная привязка находится в:

```text
reports/v15_5_compiler_and_archive_fork_binding.json
```

Полные Hardhat artifacts, build-info, JSON, PNG и logs закоммичены в изолированной evidence-ветке `Shtenco/shtencoauantai.github.io:ci/v15-5-artifacts`. Ветка не предназначена для merge в сайт.
