---
trackerStatus:
  type: inbox
title: "L2-мониторы газа молча предъявляют fallback-константу как живое чтение"
status: backlog
priority: medium
created: 2026-08-30
---

## Что найдено (ADR-182, замер 30.08)

`arbitrum_gas_monitor --check` печатает 0.1 Gwei, `optimism_gas_monitor --check` — 0.05 Gwei.
Это ровно их `FALLBACK_GWEI`: Blocknative отвечает пустым телом (без ключа), Infura требует
project id. Вывод монитора не содержит признака, какая ветка сработала, — константа
неотличима от измерения. Класс «мерить, какая ветка сработала» (журнал W35) +
fail-OPEN-провенанс (константа со штампом чтения — тот же класс, что ADR-126).

## Что сделать

1. В выводе и в state-файле мониторов — явное поле `source: live|fallback` (и в `--check`).
2. Fallback НЕ писать в историю как чтение дня; писать `unchecked` (третий исход, не ноль).
3. Рабочий источник без ключа: `eth_gasPrice` публичных RPC (проверено 30.08:
   `arbitrum.drpc.org`, `mainnet.optimism.io`, `base.drpc.org` отвечают; Blocknative/Infura — нет).
4. Положительный контроль: тест, в котором все источники падают, обязан дать `fallback`/`unchecked`
   в выводе, а не голое число.

Связано: `docs/cost_model_provenance.md` §2-бис, ADR-182; живой газ Ethereum — отдельная
линия (упомянута в карточке владельца о пилоте).
