---
trackerStatus:
  type: agent
title: Guard — track-данные в git не должны молча протухать / молча пропускаться в CI
status: backlog
source: owner-requirement-2026-07-23 (защита от повтора, карта «данные трека в git»)
created: 2026-07-23
priority: high
domain: CI integrity / track auditability
---

## Зачем (owner-требование)

Два класса бага, оба про «проверь нас» и оба «тихие»:
1. **git-копия трека молча протухает** — дневной цикл пишет `paper_evidence.json` локально, но в git не
   уезжает (был замёрз 21.06 на 12 днях при 44 локально). Проверяемость трека из репо ломается незаметно.
2. **CI-проверка молча пропускается**, когда нужный файл не в git (backtest-gate: 20 проверок + сторож
   «≥16/20» просто sk-ились). Fail-OPEN: отсутствие данных читается как «проверять нечего», а не как «красный».

Тот же класс: memory `fail-open-monitor-class`, `silently-skipped-test-files`, `ci-red-recurring-patterns`,
`git-push-api-drift` (локальный git дрейфует от origin).

3. **Производитель без расписания** — модуль пишет артефакт, но не подключён ни к агенту, ни к циклу →
   вывод молча замерзает. Примеры (замер 2026-07-23): riskwire proof 29 дней; rate_surface с 25.06;
   refusal_cost 34 дня; **`/api/rates-desk/capacity` — 36 дней (generated 2026-06-26)**, при этом
   отдаётся на публичную /fundability как «live capacity». Ловил только freshness-флаг (вечный WARNING).
   Правило: любой ПУБЛИЧНЫЙ/коммитимый артефакт обязан иметь известного производителя + расписание;
   отсутствие обновления сверх порога → КРАСНЫЙ; страница, показывающая число, должна показывать и ЕГО ВОЗРАСТ.

## Что сделать (детерминированно)

1. **Freshness-guard на закоммиченный evidence:** тест краснит, если git-копия `paper_evidence.json`
   старше N (последняя дата отстаёт от anchor/ожидаемого дня цикла). Протухание = красный, не тихий дрейф.
2. **Presence-guard вместо skip:** файлы, от которых зависят CI-проверки (backtest-gate и т.п.), должны
   ПРИСУТСТВОВАТЬ — отсутствие = КРАСНЫЙ, а не «skipped». Если файл легитимно опционален — явный
   `UNCHECKED`, никогда «OK/skipped» (memory `fail-open-monitor-class`).
3. **Дневной цикл коммитит+пушит** `paper_evidence.json` (+ канонический gate-артефакт), чтобы git-копия
   не отставала (после фикса выдуманных записей — иначе уедет непомеченный fabricated).
4. Не ослаблять пороги проверок молча (инвариант #16) — изменение только с обоснованием + journal.

## ✅ Сделано (Wave 1, 2026-07-23)

- **Единый реестр свежести артефактов** — `spa_core/monitoring/artifact_freshness.py` (10 артефактов,
  каждый с ПРОИЗВОДИТЕЛЕМ + max-age). fail-CLOSED: missing required → MISSING(RED), битый ts → UNCHECKED,
  age>max → STALE; только свежий+парсибельный = FRESH. Read-only advisory, LLM-forbidden, `now` инъектится.
  Пишет `data/artifact_freshness.json`. **10 герметичных тестов green.** Сразу поймал 4 стейл
  (riskwire 796ч, rate_surface 904ч, refusal_cost 811ч, capacity 890ч).
- **Остаётся (owner-gated deploy):** запустить его по расписанию (иначе сам станет producer-without-schedule)
  + завести Telegram-алерт на `any_stale` + вписать в system_health как advisory-домен.

## Как понять, что готово

Тест: устаревшая git-копия evidence → красный; отсутствующий требуемый CI-файл → красный (не skip);
после включения синхронизации git-копия догоняет локальную; прогон Actions подтверждает, что 20 проверок
РЕАЛЬНО выполняются (не пропущены).

## Связано

`owner-decision-dannye-treka-v-git-...`, `agent-ci-data-dependent-red-tests`,
`owner-decision-v-zhurnalah-dohodnosti...` (выдуманные записи — фикс ДО синхронизации).
