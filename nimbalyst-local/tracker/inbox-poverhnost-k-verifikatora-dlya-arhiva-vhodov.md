---
trackerStatus:
  type: inbox
title: "Дать верификатору рецепт для архива входов начисления (поверхность K)"
status: backlog
source: agent
created: 2026-09-09
tags: [verifier, adr-280, adr-269, proof-chain]
---

## Что случилось и почему это важно

С ADR-269 цикл пишет `data/cycle_inputs.jsonl` — входы начисления, из которых кривая пересчитывается
заново. Это и есть ответ на вопрос «а не нарисованы ли числа»: пересчёт уже работает и сходится до
цента (замер 09.09). Но **публичный** верификатор `scripts/verify_spa.py` этого файла не умеет:
по ADR-282 он честно числит его нераспознанным и не проверяет. То есть проверить пересчёт может
только наш собственный код, а внешний читатель — нет.

## Что чинить (порядок и приёмка)

1. Поверхность **[K]**: проверка хеш-цепочки `cycle_inputs` (как у [J]) плюс пересчёт бара из
   полей строки — `Σ pos_usd × apy% / 100 / 365` — и сверка с `daily_yield_usd`/`close_equity`
   той же строки. Всё zero-dependency, как остальной верификатор (без импорта `spa_core`).
2. Строки с `accrual_source != "live"` и с пулами из `fallback_pools` помечать в выводе отдельно:
   пересчёт сойдётся, но входом была НЕнаблюдённая ставка — это разные утверждения.
3. Обновить `docs/PROOF_CHAIN_SPEC.md` (§6c), `VERIFIER_RELEASE.md` и пин на `/verify`.

**Приёмка:** `verify_spa.py data/cycle_inputs.jsonl` даёт `[K] cycle inputs: valid=True rows=N
replayed=N/N`; строка с подменённым `apy_map` краснеет; строка с `fallback` названа отдельно.

## Что НЕ трогать

Правило «верификатор не судит журнал, для которого нет рецепта» (ADR-282) — поверхность добавляется,
обобщающая ветка не возвращается.

## Ссылки

[ADR-282](../../docs/decisions/ADR-282-verifier-never-judges-a-foreign-chain.md) ·
[ADR-269](../../docs/decisions/ADR-269-track-verifiability-transfer-from-earn-defi.md) ·
`spa_core/audit/replay_equity.py`.
