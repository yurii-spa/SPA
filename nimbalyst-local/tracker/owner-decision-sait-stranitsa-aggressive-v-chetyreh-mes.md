---
trackerStatus:
  type: owner-decision
title: "Сайт: страница Aggressive в четырёх местах всё ещё пишет про плечо, которого в книге нет"
status: needs-owner
source: orchestrator
created: 2026-10-01
approves: landing/src/pages/strategies/aggressive.astro
adr: ADR-531
priority: high
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
