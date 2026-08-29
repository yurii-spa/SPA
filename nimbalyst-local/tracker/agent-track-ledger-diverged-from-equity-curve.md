---
trackerStatus:
  type: agent
title: track_ledger.json (источник /changelog) отстал от equity_curve_daily.json на 7 недель — 19 против 67 evidenced-дней
status: backlog
source: session-2026-08-29 (найдено при попытке опубликовать CMO-дайджест на /changelog)
created: 2026-08-29
priority: medium
domain: track-integrity
---

## Что случилось

Пытался опубликовать на `/changelog` (публичный автоматический дайджест трека) свежую запись
через уже существующий, уже подключённый генератор `scripts/generate_research_changelog.py`.
Генератор берёт числа evidenced-дней/доходности/просадки из `data/track_ledger.json`.

**`data/track_ledger.json` не обновлялся с 2026-07-10** (`n_evidenced_days: 19`,
`last_evidenced_date: 2026-07-10`). При этом источник отказов того же генератора
(`data/rates_desk/decision_log.jsonl`) обновляется КАЖДЫЙ день, последняя запись — сегодня.

Параллельно у **дневного цикла** (`spa_core/paper_trading/cycle_runner.py`) есть **свой,
другой** источник — `data/equity_curve_daily.json`, поле `summary.evidenced_days` — там сегодня
**67**, не 19. Файл обновляется ежедневно, подтверждено сегодняшним `generated_at`.

## Почему это важно

Если запустить генератор `/changelog` не разбираясь — он выдаст **гибридную запись**: свежий
счётчик отказов + семинедельной давности число evidenced-дней, поверх ещё и разошедшееся с тем
числом, что показывает `/admin/portfolio-summary` (Фаза B CIO, сегодняшняя доставка) из
`equity_curve_daily.json`. Два публичных/полу-публичных места сайта показали бы **разные** числа
одного и того же трека одновременно.

`evidenced days` — не косметика: это метрика go-live трека (CLAUDE.md: «трек 13/30 evidenced»).

## Что нужно

1. Понять, ПОЧЕМУ `track_ledger.json` не обновляется — кто должен его писать (найти
   производителя: grep по `track_ledger.json` на предмет writer'а, не только читателей) и
   когда он в последний раз реально запускался.
2. Решить, какой источник канонический для `/changelog`: `track_ledger.json` (если чинить его
   писателя) или переключить генератор на `equity_curve_daily.json` (если `track_ledger.json` —
   заброшенный дубль).
3. НЕ запускать `generate_research_changelog.py` до решения п.2 — иначе на публичный сайт
   уедет честно посчитанное, но вводящее в заблуждение число.

## Как понять, что готово

`/changelog` и `/admin/portfolio-summary` показывают согласованное число evidenced-дней (или,
если это в принципе разные метрики — явно названо, почему они расходятся, а не просто оставлено
как есть).
