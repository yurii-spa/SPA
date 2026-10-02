---
trackerStatus:
  type: owner-decision
title: "Сайт: на трёх страницах всё ещё старая ставка «~3.3%» вместо живой 4.9% — заменить на общий источник"
status: ingested
source: orchestrator
created: 2026-10-01
approves: landing/src/pages/packages.astro, landing/src/pages/system.astro, landing/src/pages/learn/why-20-apy-means-tail-risk.astro
adr: ADR-531
priority: high
status_trail:
  - "2026-10-01T15:59:47.477071+00:00 needs-owner -> owner-done · queue.set_status/closed_by:owner (explicit decision in session 2026-10-01: «OWNER DECISION — CLOSE REMAINING P0-4 PUBLIC CORRECTNESS GAPS», both packages approved)/evidence:owner approval 2026-10-01 of docs/owner_packages/2026-10-01-stale-realized-3-3-pct.md; literals replaced by realizedApyLabel()/measuredNote()/realizedPhrase(); dist has 0 × '3.3%'"
  - "2026-10-02T16:23:42.497141+00:00 owner-done -> ingested · queue.set_status · cycle-93700"
---

## Что случилось и почему это важно
На трёх страницах (`/packages`, `/system`, урок «why 20% APY means tail risk») ставка Conservative
вписана руками: «~3.3%». Это июльский замер; трек сейчас даёт 4.9%, и рядом на тех же страницах
стоит именно 4.9%. 16.09 ты эту правку уже одобрял, но карточка не получила `owner-done`, и
пуш так и не случился. Плюс одной ссылки («15% vs the real ~3.3%») в той карточке не было вовсе.

## Что от тебя нужно
Открой `docs/owner_packages/2026-10-01-stale-realized-3-3-pct.md` — там все шесть мест и чем их заменить.
Замена — не «4.9» вместо «3.3», а та же функция, что на остальном сайте (`realized_rate.js`): число
обновляется само и печатается с датой замера. Остальной текст строк не меняется.
- **A (рекомендую):** одобрить все шесть.
- **B:** выборочно — напиши номера.
- **C:** не менять.

## Как понять, что готово
На живых `/packages`, `/system` и уроке нет «3.3», ставка совпадает с главной.

## Что будет после
Применю правку, опубликую через `safe_site_push.py` с трейлером `Owner-Approved:` и проверю три страницы `curl`-ом.

---

## Инжест ответа владельца — цикл #753 (2026-10-02)

Статус переведён `owner-done → ingested` (инв. #14: `owner-done` ставит только владелец, `ingested` — агент после инжеста). Решение владельца записано в `status_trail` и в ADR-531.

**Что измерено перед закрытием.** Проверено ЖИВЫМ сайтом, а не словами карточки: `curl` по `/packages/`, `/system/`, `/strategies/aggressive/`, `/learn/why-20-apy-means-tail-risk/` — вхождений «3.3%» **ноль** на всех четырёх.

**Названо, а не умолчано:** машинного следа ответа (`owner_choice`, `owner_answered_at`) у карточки нет ни в одной копии — владелец ответил текстом в сессии 01.10, а не кнопкой, и очередь об этом предупредила при переводе статуса. Закрытие стоит на `closed_by:owner` + `evidence` в `status_trail` и на замере живого сайта выше, а не на прозе сессии.
