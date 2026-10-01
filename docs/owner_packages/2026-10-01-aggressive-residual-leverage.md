# Owner package · страница Aggressive всё ещё приписывает книге плечо (предмет №2)

> Дата: 2026-10-01 · связано: ADR-531 (P0-4, пункт 4) · патч: `2026-10-01-aggressive-residual-leverage.patch`.

## Что не так

P0-4 опубликован целиком (45/45 проверок на живом сайте). Подзаголовок, вступление, механика,
FAQ про стопы и блок рисков стратегии теперь говорят «без плеча, без петель, без LP». Но пакет P0-4
называл конкретные строки, и на той же странице `/strategies/aggressive` остались **четыре блока
вне его**, которые описывают ЭТУ книгу как плечевую:

| # | Строка | Сейчас на сайте |
|---|---|---|
| 1 | `aggressive.astro:203` | «the aggressive mechanic itself carries real liquidation-cascade and depeg risk» |
| 2 | `:241-243`, таблица гейта | «Liquidation risk · Real (cascade) · Levered loops + directional restaking carry cascade & depeg» |
| 3 | `:277-279`, раздел рисков | «Aggressive carries all risks of Balanced plus leverage and directional risks… an unhedged book saw ~50% through the ETH crash» |
| 4 | `:384-386`, FAQ «Is there liquidation risk?» | «Yes — this tier carries real liquidation-cascade risk (levered loops) and depeg risk (directional restaking)» |

Читатель видит на одной странице «No leverage, no loops, no LP» и «Yes — levered loops». Факт
(ADR-530, замер книги): две позиции кредитования стейблкоинов, без займа и без плеча.

## Предлагаемый текст (EN; RU — в патче, по смыслу дословно)

1. «…the book itself uses no leverage — its risk is concentration in fewer protocols.»
2. «Liquidation risk · None in this book · The book does not borrow or use leverage; levered
   constructions are researched only in the Aggressive Lab. The gate refuses live: advisory research
   outside RiskPolicy v1.0.»
3. «Aggressive carries stablecoin lending risks concentrated in fewer protocols, with a wider stop than
   Balanced. It uses no leverage. The ~50% drawdown through the ETH crash belongs to the unhedged
   Aggressive Lab research book, not to this one. Refused for live capital.»
4. «Not in this book: it does not borrow or use leverage. Liquidation-cascade and depeg risk belong to
   the levered constructions researched only in the separate Aggressive Lab, which never fund this
   book. The desk REFUSES this tier for live capital; it exists as advisory paper research with the
   tail shown.»

## Что сохранено

- Все метки «refused for live» / «REFUSES… for live capital» стоят на месте.
- Хвост «~50% на обвале ETH» не убран: он перенесён к тому объекту, которому принадлежит
  (книга лаборатории). Убрать его значило бы спрятать хвост (инв. #8).
- Новых чисел, обещаний и юридических формулировок нет. Мета-описание и баннер вверху страницы
  (`:13`, `:24-25`) говорят о стратегиях **лаборатории**, а не об этой книге, и не трогаются.

## Варианты

- **A (рекомендую):** одобрить 1–4 — страница перестаёт противоречить себе.
- **B:** выборочно (номера).
- **C:** оставить.

## Как довести после ответа

Карточка в `owner-done` (поле `approves:` уже указывает файл) → `git apply` патча → `scripts/safe_site_push.py`
с трейлером `Owner-Approved: <id карточки>` → проверка `curl -L /strategies/aggressive/`: на отрисованной
странице нет ни «levered loops», ни «plus leverage», ни «Real (cascade)».
