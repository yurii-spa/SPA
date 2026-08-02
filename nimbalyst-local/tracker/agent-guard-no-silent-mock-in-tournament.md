---
trackerStatus:
  type: agent
title: Guard — стратегия не должна молча падать на mock, если заявленный живой адаптер не грузится
status: backlog
source: owner-requirement-2026-07-23 (защита от повтора S23)
created: 2026-07-23
priority: high
domain: strategy/eval integrity
---

## Зачем (owner-требование)

Класс бага S23: стратегия заявляет «беру живой Pendle», импортирует адаптер внутри `except: pass`,
адаптер мёртв → ошибка глотается молча → стратегия НАВСЕГДА на mock-числе (7%) → mock попадает в
турнир как реальная оценка. Владелец (2026-07-23): предусмотреть, чтобы это НЕ повторилось.

Тот же класс, что: fail-OPEN мониторы (memory `fail-open-monitor-class`), abstract-analytics
silently-dead (`abstract-analytics-latent-bugs`), silently-skipped tests.

## Что сделать (guard, детерминированно, LLM запрещён)

1. **Тест-guard:** для каждой стратегии, заявляющей живой источник, проверить, что заявленный адаптер
   реально ИМПОРТИРУЕТСЯ (import-based, не `compile`) — падение = красный тест, а не тихий mock.
   (Тот же принцип, что фикс гейта готовности в карте 2.)
2. **Запрет `except: pass` вокруг импорта адаптера** в стратегиях (lint/AST-проверка): молчаливое
   глотание ImportError запрещено — логировать + помечать `*_live: false` явно.
3. **Турнир помечает/исключает mock-записи:** стратегия с `*_live: false` НЕ ранжируется как живая —
   либо отдельная пометка «MOCK», либо исключение из доверенного лидерборда (см. карту
   `agent-tournament-trustworthy-real-apy.md`).

## Защита самого honesty-gate (owner-вопрос 2026-07-23)

Турнир уже имеет HONESTY GATE (`mass_tournament.py:650`, `assess_tournament_trust`): fail-CLOSED
штампует `trustworthy:false` на вырожденных/mock данных. Риск рецидива в ДВУХ формах:
1. **Снова подсунуть mock** — gate ПОЙМАЁТ (пометит false), но не предотвратит; ловят п.1–3 выше.
2. **Молча ЗАГЛУШИТЬ сам gate** (поставить `trustworthy:true` / убрать проверку) = инвариант #16.
   → добавить **тест, что honesty-gate СРАБАТЫВАЕТ** на вырожденных/mock входах (near-const returns →
   `trustworthy:false`) — тогда gate нельзя тихо удалить/ослабить (тест покраснеет). Тест-guard на
   сам guard.

## Как понять, что готово

Тест: стратегия с заявленным-живым, но не грузящимся адаптером → guard краснит; mock-запись не
попадает в доверенный рейтинг незамеченной; S23 после фикса (MP-201) проходит guard как живая;
honesty-gate доказанно срабатывает на mock-входе (нельзя тихо заглушить).

## Связано

S23-решение (`owner-decision-strategiya-s23-...`), турнир (`agent-tournament-trustworthy-real-apy.md`),
директива «оценивать стратегии по реальной доходности» (`owner-directive-head-of-investment-layer`).
