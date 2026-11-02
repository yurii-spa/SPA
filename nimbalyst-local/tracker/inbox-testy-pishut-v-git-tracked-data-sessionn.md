---
trackerStatus:
  type: inbox
title: Тесты пишут в git-tracked data/ — сессионный сторож отказывает в КАЖДОМ прогоне CI (12 из 12 шардов), и зелёный контрольный прогон недостижим
status: new
source: nimbalyst
created: 2026-11-02
finding_adr: ADR-899
twin_key: "sha256:890437eb234220571bcb6c0c765977fc00d0874ed9d489f51c11f8d60f625b9c"
---

## Что измерено

Сессионный сторож `spa_core/tests/tracked_write_guard.py` отказывает в КАЖДОМ
контрольном прогоне CI, и его отказ не доходит до свода НИ ОДНОЙ строкой.

Замер 2026-11-02 по логам джоб (цикл #1012, ADR-899):

| прогон | sha | шардов с «НОВОЕ (вне базы)» | нарушений | назвал отчёт |
|---|---|---|---|---|
| 41435243848 | `8f34a8894` | **12 из 12** | 68 | **0** |
| 41410492012 | `539bccdd4` | ≥1 (шард 11) | 7 | 0 (как «незавершён») |

Семь модулей, пишущих в git-tracked `data/*.json` вне базы (шард 11,
прогон 41410492012): `test_concurrent_fetch` → `data/chains_status.json` ·
`test_defi_liquidation_cascade_risk_analyzer` → `data/liquidation_cascade_log.json` ·
`test_defi_points_to_token_conversion_analyzer` → `data/points_conversion_log.json` ·
`test_defi_protocol_stablecoin_peg_arbitrage_analyzer` →
`data/stablecoin_peg_arbitrage_log.json` ·
`test_protocol_defi_yield_source_sustainability_ranker` →
`data/yield_sustainability_rank_log.json` · `test_protocol_fee_structure_analyzer` →
`data/fee_structure_log.json` · `test_signal_aggregator_entrypoint_typing` → СЕМЬ
файлов `data/` сразу.

База `spa_core/tests/tracked_write_baseline.json` ПУСТА (`modules: {}`), то есть любой
такой модуль есть нарушение по построению. Дописывать в базу ЗАПРЕЩЕНО (инв. #16) —
чинить надо ТЕСТЫ: они обязаны писать в свою песочницу, а не в дерево.

## Почему это не косметика

Прогон CI не может быть зелёным, пока отказ жив: код выхода шарда всегда 1. ADR-899
сделал этот род ВИДИМЫМ для свода, но не починил его причину — пока модули пишут в
дерево, каждый шард кончается ненулевым кодом, и «зелёный контрольный прогон» в
проекте недостижим ПО ПОСТРОЕНИЮ.

## Две части работы (разные предметы, не смешивать)

1. **Починить семь модулей** — писать в `tmp_path`/песочницу. Мера — та же: прогон
   этих файлов не меняет `git status` дерева.
2. **ADR-899 оставил названную границу:** ветка свода стои́т под `shard_fails == 0`,
   поэтому отказ сторожа на шарде С ПРОВАЛАМИ по-прежнему невидим. Нужен ли отдельный
   канал от самого сторожа (чтобы свод называл ВИНОВНИКА, а не только род) — вопрос
   с ценой, и решать его надо замером населения, а не расширением наугад.

## Как понять, что готово

`SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest <семь файлов> -q` не оставляет ни одной
строки в `git status -- data/`, а шард, их несущий, кончается кодом 0.
