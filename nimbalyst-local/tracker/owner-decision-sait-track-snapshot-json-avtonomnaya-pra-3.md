---
trackerStatus:
  type: owner-decision
title: "Сайт: track_snapshot.json — автономная правка задела owner-gated область, нужно решение"
status: needs-owner
source: orchestrator
created: 2026-10-29
approves: landing/src/data/track_snapshot.json
---

## Что случилось и почему это важно
Автономный оркестратор хотел изменить публичный сайт, но правка задевает owner-gated область (числа доходности / нейминг тиров / legal / solicitation). Такое не уезжает в live само — только с твоего одобрения (инвариант #8).

## Что от тебя нужно
Посмотри изменение и выбери:

1. **Одобрить** — правка уезжает в live как есть.
2. **Отклонить (рекомендую)** — оркестратор не трогает эту область; owner-gated поверхность остаётся неизменной, пока ты не решишь иначе.
3. **Отложить** — оставить карточку открытой и вернуться к ней позже.

Что именно меняется:
- Файлы: landing/src/data/track_snapshot.json
- Коммит-сообщение оркестратора: chore(site-custodian): auto-deploy fresh track_snapshot after daily cycle
- Что зафлагано owner-gate линтером:
  - [B] landing/src/data/track_snapshot.json · snapshot.number · real_track_days: 127 → 128
  - [B] landing/src/data/track_snapshot.json · snapshot.number · end_equity: 101835.21 → 101848.49
  - [B] landing/src/data/track_snapshot.json · snapshot.number · nav_usd: 101835.21 → 101848.49
  - [B] landing/src/data/track_snapshot.json · snapshot.number · total_return_pct: 1.8352 → 1.8485
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_return_pct: 1.682 → 1.6953
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_period.period_return_pct: 1.682016 → 1.695276
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_period.twr_pct: 1.682016 → 1.695276
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_period.mwr_pct: 1.682016 → 1.695276
  - [B] landing/src/data/track_snapshot.json · snapshot.number · track_period.annualised_equivalent_pct: 4.871418 → 4.871443
  - [B] landing/src/data/track_snapshot.json · snapshot.number · packages.conservative.apy_pct: 3.709 → 4.044
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.conservative.nav_usd: 101835.21 → 101848.49
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.balanced.post_fix.apy_pct: 3.04 → 3.05
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.aggressive.post_fix.apy_pct: 6.3 → 6.55

## Как понять, что готово
Ты нажал кнопку в Телеграме (или написал в карточке «одобряю» / «отклоняю»); при одобрении оркестратор запушит с трейлером `Owner-Approved: <id-карточки>`.

## Что будет после
Одобришь → изменение уезжает в live /dashboard и на сайт. Отклонишь → оркестратор не трогает эту область.

<!-- owner-gate-fingerprint: 7e1d479ad2c7 -->
