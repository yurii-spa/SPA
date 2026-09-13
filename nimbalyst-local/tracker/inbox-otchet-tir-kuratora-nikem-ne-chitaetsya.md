---
trackerStatus:
  type: inbox
title: Отчёт тир-куратора никем не читается — дать ему читателей (брифинг + карточка на held-DEMOTE)
status: in-progress
source: nimbalyst
created: 2026-09-11
status_trail:
  - "2026-09-13T07:28:12.001302+00:00 new -> in-progress · queue.set_status"
---

## Что найдено

`spa_core/analytics/tier_curator.py` (Y4, ADR-055) ежедневно выносит вердикты
`DEMOTE_SIGNAL / PROMOTE_CANDIDATE / KEEP / UNCHECKED` и пишет
`data/tier_curator_report.json`. `grep tier_curator_report` по репозиторию вне тестов
даёт **два** попадания: писателя (`cycle_runner.py:3162`) и докстроку самого модуля.

Читателя нет ни одного:

- в `scripts/update_system_briefing.py` **13** секций `build_*_section()`, секции куратора нет;
- карточка владельцу на `DEMOTE_SIGNAL` не создаётся;
- телеграм-алерта нет;
- сторожа свежести артефакта в `spa_core/monitoring/` нет (`grep tier_curator` по каталогу — пусто).

`DEMOTE_SIGNAL` по **удерживаемой** позиции печатает строку `HELD-DEMOTE⚠` в stdout
дневного цикла и умирает там.

Это тот же класс, который ADR-142 (решение владельца 25.08) закрыл для
`source_discovery` — «инструмент рабочий, покрыт 30 тестами, а `data/source_discovery.json`
не читал НИКТО». Воспроизвёлся на соседнем модуле того же слоя.

## Что сделать

1. `build_tier_curator_section()` в `scripts/update_system_briefing.py` — по образцу
   `build_source_discovery_section()` (ADR-142): вердикты по счёту, поимённо —
   `held_flagged`, состояние по свежести артефакта (`fresh / stale / отсутствует`,
   «не измерено» с причиной, а не молчание).
2. На `DEMOTE_SIGNAL` по протоколу с НЕнулевой позицией — автокарточка `needs-owner`
   через `scripts/orchestrator_queue.py create` (формат §2.4, четыре секции по-русски)
   и телеграм-нотификация. Дедупликация по протоколу, иначе цикл заведёт карточку
   каждые сутки.
3. Тест: фикстура `tier_curator_report.json` с held-DEMOTE обязана родить карточку;
   обратная сторона — отчёт без held-DEMOTE карточку НЕ родит. Положительный контроль
   к секции брифинга: отсутствующий артефакт даёт «не измерено» с названной причиной,
   а не «чисто».

**Не делать здесь:** автоматическую смену тира. Тир задаёт потолок концентрации,
это денежный путь — отдельная карточка владельцу
(`owner-decision-avtodemoushen-tira-signal-est-ispolnitelya-net`).

## Как понять, что готово

Читателей отчёта 0 → 2 (секция брифинга + карточка), тест на held-DEMOTE зелёный
в обе стороны.

## Контекст

Полный аудит четырёх контуров тир-жизненного цикла (поиск → присвоение → эскалатор
T3→T2 → пере-проверка) — `docs/TIER_LIFECYCLE_AUDIT_2026-09-11.md`, правка № 1 из шести.

---

## Ход работы (2026-09-13, ветка `claude/tier-promotion-loop`)

Оба читателя сделаны: (1) `findings_bridge` — четвёртый источник, `PROMOTE_CANDIDATE` ⇒
inbox-карточка агенту после 2 замеров подряд, `DEMOTE_SIGNAL` по удерживаемому ⇒ карточка о
видимости; авто-закрытие мостом; (2) секция брифинга `build_tier_curator_section()` с тремя
исходами. Проба по исходу — `spa_core/tests/test_tier_promotion_loop.py` (краснеет, если
читатель порван или T1-кандидат уходит владельцу как CRITICAL — проверено мутациями 2/2).
Проводка при рождении: `cycle_runner.PRODUCES`, манифест (produces/consumes/artifacts).
Закрывается после мержа PR.
