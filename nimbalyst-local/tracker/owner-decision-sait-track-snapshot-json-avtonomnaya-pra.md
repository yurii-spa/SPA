---
trackerStatus:
  type: owner-decision
title: "Сайт: track_snapshot.json — автономная правка задела owner-gated область, нужно решение"
status: needs-owner
source: orchestrator
created: 2026-10-06
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
  - [B] landing/src/data/track_snapshot.json · snapshot.number · real_track_days: 101 → 105
  - [B] landing/src/data/track_snapshot.json · snapshot.number · end_equity: 101492.73 → 101538.01
  - [B] landing/src/data/track_snapshot.json · snapshot.number · nav_usd: 101492.73 → 101538.01
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_apy_pct: 4.9282 → 4.8986
  - [B] landing/src/data/track_snapshot.json · snapshot.number · total_return_pct: 1.4927 → 1.538
  - [B] landing/src/data/track_snapshot.json · snapshot.number · packages.conservative.apy_pct: 3.7 → 5.4
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.conservative.apy_pct: 4.93 → 4.9
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.conservative.nav_usd: 101492.73 → 101538.01
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.balanced.dd_pct: 0.0 → -0.11
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.balanced.post_fix.apy_pct: None → -4.88
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.aggressive.dd_pct: 0.0 → -0.01
  - [B] landing/src/data/track_snapshot.json · snapshot.number · paper_tracks.aggressive.post_fix.apy_pct: None → 8.95

## Как понять, что готово
Ты нажал кнопку в Телеграме (или написал в карточке «одобряю» / «отклоняю»); при одобрении оркестратор запушит с трейлером `Owner-Approved: <id-карточки>`.

## Что будет после
Одобришь → изменение уезжает в live /dashboard и на сайт. Отклонишь → оркестратор не трогает эту область.

<!-- owner-gate-fingerprint: 50be760cf879 -->
