---
trackerStatus:
  type: owner-decision
title: "Сайт: страница Aggressive в четырёх местах всё ещё пишет про плечо, которого в книге нет"
status: ingested
source: orchestrator
created: 2026-10-01
approves: landing/src/pages/strategies/aggressive.astro
adr: ADR-531
priority: high
status_trail:
  - "2026-10-01T15:59:47.470986+00:00 needs-owner -> owner-done · queue.set_status/closed_by:owner (explicit decision in session 2026-10-01: «OWNER DECISION — CLOSE REMAINING P0-4 PUBLIC CORRECTNESS GAPS», both packages approved)/evidence:owner approval 2026-10-01 of docs/owner_packages/2026-10-01-aggressive-residual-leverage.md; patch applied as is; live check after push"
  - "2026-10-02T16:23:43.235733+00:00 owner-done -> ingested · queue.set_status · cycle-93700"
---

## Что случилось и почему это важно
P0-4 опубликован целиком, но на странице Aggressive остались четыре блока вне пакета, которые
по-прежнему пишут «да, у этого тира плечевые петли и риск ликвидации». На той же странице выше
теперь написано «без плеча, без петель, без LP». Посетитель видит противоречие.

## Что от тебя нужно
Открой `docs/owner_packages/2026-10-01-aggressive-residual-leverage.md` — четыре места, старый и новый текст.
Метки «refused for live» остаются; хвост «~50% на обвале ETH» не убирается, а приписывается книге
лаборатории, которой он принадлежит.
- **A (рекомендую):** одобрить все четыре.
- **B:** выборочно — номера.
- **C:** оставить.

## Как понять, что готово
На живой `/strategies/aggressive/` нет «levered loops», «plus leverage» и «Real (cascade)».

## Что будет после
Применю готовый патч, опубликую через `safe_site_push.py` с трейлером `Owner-Approved:` и проверю страницу.

---

## Инжест ответа владельца — цикл #753 (2026-10-02)

Статус переведён `owner-done → ingested` (инв. #14: `owner-done` ставит только владелец, `ingested` — агент после инжеста). Решение владельца записано в `status_trail` и в ADR-531.

**Что измерено перед закрытием.** Проверено ЖИВЫМ сайтом: на `/strategies/aggressive/` все упоминания плеча — в исправленной форме («кредитная часть без плеча; петля — бумажная симуляция без реальных займов», «симулированное плечо», «плечевые конструкции… только в отдельной Aggressive Lab»). Утверждения о настоящем плече в книге не осталось ни одного; метки «refused for live» на месте.

**Названо, а не умолчано:** машинного следа ответа (`owner_choice`, `owner_answered_at`) у карточки нет ни в одной копии — владелец ответил текстом в сессии 01.10, а не кнопкой, и очередь об этом предупредила при переводе статуса. Закрытие стоит на `closed_by:owner` + `evidence` в `status_trail` и на замере живого сайта выше, а не на прозе сессии.
