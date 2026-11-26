---
trackerStatus:
  type: owner-decision
title: "Сайт: track_snapshot.json — автономная правка задела owner-gated область, нужно решение"
status: ingested
source: orchestrator
created: 2026-11-26
approves: landing/src/data/track_snapshot.json
twin_key: "sha256:4402321d33df0fc543df371c9330e0a2b5fd2c0f0745464819247582b665635c"
owner_choice: 1
owner_answered_at: 2026-11-26T16:43:26.015764+00:00
owner_answer_via: telegram
owner_answered_by: 258651137
owner_answer_kind: option
status_trail:
  - "2026-11-26T16:43:26.016032+00:00 needs-owner -> owner-done · owner_answer.record_owner_answer"
  - "2026-11-26T21:08:32.974988+00:00 owner-done -> ingested · queue.set_status · cycle-94089"
---

## Что случилось и почему это важно
Автономный оркестратор хотел изменить публичный сайт, но правка задевает owner-gated область (числа доходности / нейминг тиров / legal / solicitation). Такое не уезжает в live само — только с твоего одобрения (инвариант #8).

## Что от тебя нужно
Посмотри изменение и выбери:

1. **Одобрить** — правка уезжает в live как есть.
2. **Отклонить (рекомендую)** — оркестратор не трогает эту область; почему это безопасное умолчание, сказано ниже отдельной строкой.
3. **Отложить** — оставить карточку открытой и вернуться к ней позже.

Что именно меняется:
- Файлы: landing/src/data/track_snapshot.json
- Коммит-сообщение оркестратора: chore(site-custodian): auto-deploy fresh track_snapshot after daily cycle
- Что зафлагано owner-gate линтером:
  - [B] landing/src/data/track_snapshot.json · snapshot.number · real_track_days: 154 → 156
  - [B] landing/src/data/track_snapshot.json · snapshot.number · end_equity: 102159.71 → 102177.97
  - [B] landing/src/data/track_snapshot.json · snapshot.number · nav_usd: 102159.71 → 102177.97
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_apy_pct: 4.7882 → 4.7693
  - [B] landing/src/data/track_snapshot.json · snapshot.number · total_return_pct: 2.1597 → 2.178
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_return_pct: 2.006 → 2.0243
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_period.period_return_pct: 2.006028 → 2.02426
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_period.twr_pct: 2.006028 → 2.02426
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_period.mwr_pct: 2.006028 → 2.02426
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_period.annualised_equivalent_pct: 4.788217 → 4.769325
  - [B] landing/src/data/track_snapshot.json · snapshot.number · packages.conservative.apy_pct: 4.044 → 3.532
  - [B] landing/src/data/track_snapshot.json · snapshot.number · packages.conservative.dd_pct: 0.047 → 0.026
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.conservative.apy_pct: 4.7882 → 4.7693
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.conservative.nav_usd: 102159.71 → 102177.97
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.balanced.apy_pct: 4.32 → 4.39
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.balanced.post_fix.apy_pct: 4.32 → 4.39
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.aggressive.apy_pct: 6.62 → 6.91
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.aggressive.post_fix.apy_pct: 6.62 → 6.91

- Цена отказа: **НЕ ИЗМЕРЕНО** — витрины чисел (`landing/src/data/site_numbers.json`) в этой правке нет, а накапливающуюся цену отказа эта дверь меряет только у неё.
- Рекомендация: **Отклонить** — не от замера, а по инварианту #8: owner-gated поверхность не уезжает в live одним тапом. Разовая правка страницы ничего не замораживает, поэтому отказ здесь и есть безопасное умолчание.

## Как понять, что готово
Ты нажал кнопку в Телеграме (или написал в карточке «одобряю» / «отклоняю»); при одобрении оркестратор запушит с трейлером `Owner-Approved: <id-карточки>`.

## Что будет после
Одобришь → изменение уезжает в live /dashboard и на сайт. Отклонишь → оркестратор не трогает эту область. Чего это стои́т посетителю — НЕ ИЗМЕРЕНО, причина названа выше.

<!-- owner-gate-fingerprint: 4ffb0a2534a5 -->

---

## Решение владельца

**Вариант 1** — Одобрить

_Ответ владельца получен 2026-11-26T16:43:26.015764+00:00 (telegram). Карточка закрыта самим владельцем, не агентом (инвариант #14)._
