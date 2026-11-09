---
trackerStatus:
  type: owner-decision
title: "Сайт: track_snapshot.json — автономная правка задела owner-gated область, нужно решение"
status: needs-owner
source: orchestrator
created: 2026-11-08
approves: landing/src/data/track_snapshot.json
twin_key: "sha256:ba2bfd1e739f1c17228b2245b60230a548a1fe9e9100c78a6619007a31a3f3f3"
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
  - [B] landing/src/data/track_snapshot.json · snapshot.number · real_track_days: 137 → 138
  - [B] landing/src/data/track_snapshot.json · snapshot.number · end_equity: 101973.32 → 101985.1
  - [B] landing/src/data/track_snapshot.json · snapshot.number · nav_usd: 101973.32 → 101985.1
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_apy_pct: 4.8859 → 4.8817
  - [B] landing/src/data/track_snapshot.json · snapshot.number · total_return_pct: 1.9733 → 1.9851
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_return_pct: 1.8199 → 1.8317
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_period.period_return_pct: 1.819918 → 1.83168
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_period.twr_pct: 1.819918 → 1.83168
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_period.mwr_pct: 1.819918 → 1.83168
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_period.annualised_equivalent_pct: 4.885883 → 4.881703
  - [B] landing/src/data/track_snapshot.json · snapshot.number · packages.conservative.apy_pct: 3.603 → 4.044
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.conservative.apy_pct: 4.8859 → 4.8817
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.conservative.nav_usd: 101973.32 → 101985.1
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.balanced.apy_pct: 3.85 → 3.72
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.balanced.post_fix.apy_pct: 3.85 → 3.72
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.aggressive.apy_pct: 5.3 → 5.13
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.aggressive.post_fix.apy_pct: 5.3 → 5.13

- Цена отказа: **НЕ ИЗМЕРЕНО** — витрины чисел (`landing/src/data/site_numbers.json`) в этой правке нет, а накапливающуюся цену отказа эта дверь меряет только у неё.
- Рекомендация: **Отклонить** — не от замера, а по инварианту #8: owner-gated поверхность не уезжает в live одним тапом. Разовая правка страницы ничего не замораживает, поэтому отказ здесь и есть безопасное умолчание.

## Как понять, что готово
Ты нажал кнопку в Телеграме (или написал в карточке «одобряю» / «отклоняю»); при одобрении оркестратор запушит с трейлером `Owner-Approved: <id-карточки>`.

## Что будет после
Одобришь → изменение уезжает в live /dashboard и на сайт. Отклонишь → оркестратор не трогает эту область. Чего это стои́т посетителю — НЕ ИЗМЕРЕНО, причина названа выше.

<!-- owner-gate-fingerprint: d233db4b325b -->
