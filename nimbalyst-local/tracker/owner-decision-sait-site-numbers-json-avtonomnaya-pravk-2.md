---
trackerStatus:
  type: owner-decision
title: "Сайт: site_numbers.json — автономная правка задела owner-gated область, нужно решение"
status: needs-owner
source: orchestrator
created: 2026-11-03
approves: landing/src/data/site_numbers.json
twin_key: "sha256:c9df7012d1472e325ac320d3158d7f86a73b05ae8405345b1e2ca53bf7cb67af"
---

## Что случилось и почему это важно
Автономный оркестратор хотел изменить публичный сайт, но правка задевает owner-gated область (числа доходности / нейминг тиров / legal / solicitation). Такое не уезжает в live само — только с твоего одобрения (инвариант #8).

## Что от тебя нужно
Посмотри изменение и выбери:

1. **Одобрить** — правка уезжает в live как есть.
2. **Отклонить (рекомендую)** — оркестратор не трогает эту область; owner-gated поверхность остаётся неизменной, пока ты не решишь иначе.
3. **Отложить** — оставить карточку открытой и вернуться к ней позже.

Что именно меняется:
- Файлы: landing/src/data/site_numbers.json
- Коммит-сообщение оркестратора: chore(site numbers): weekly shelf (ADR-630)
- Что зафлагано owner-gate линтером:
  - [P] landing/src/data/site_numbers.json · publication.gate · missing owner approval for: shelf.packages.conservative.apy: backtest value changed 5.365 → 4.044; shelf.packages.conser

Ворота публикации (ADR-630) не пропустили витрину чисел сайта:
- missing owner approval for: shelf.packages.conservative.apy: backtest value changed 5.365 → 4.044; shelf.packages.conservative.drawdown: backtest value changed 0.04 → 0.047; shelf.books.balanced.apy: null → 3.43 (a value appears for the first time); shelf.books.aggressive.apy: null → 5.64 (a value appears for the first time)

Одобрение относится ровно к этой витрине (строка ниже — её отпечаток; другую витрину оно не пропустит):

publication-approves: landing/src/data/site_numbers.json 2026-11-03 sha256:79935933cc20b8c20f03e12f2fa3b47652b1b6c38f871e9a0904485b21751cdb

## Как понять, что готово
Ты нажал кнопку в Телеграме (или написал в карточке «одобряю» / «отклоняю»); при одобрении оркестратор запушит с трейлером `Owner-Approved: <id-карточки>`.

## Что будет после
Одобришь → изменение уезжает в live /dashboard и на сайт. Отклонишь → оркестратор не трогает эту область.

<!-- owner-gate-fingerprint: 135e6150119d -->
