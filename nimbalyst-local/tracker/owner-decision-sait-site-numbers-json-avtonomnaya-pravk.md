---
trackerStatus:
  type: owner-decision
title: "Сайт: site_numbers.json — автономная правка задела owner-gated область, нужно решение"
status: needs-owner
source: orchestrator
created: 2026-10-28
approves: landing/src/data/site_numbers.json
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
  - [P] landing/src/data/site_numbers.json · publication.gate · missing owner approval for: shelf.packages.conservative.apy: backtest value changed 5.365 → 3.709; shelf.packages.conser

Ворота публикации (ADR-630) не пропустили витрину чисел сайта:
- missing owner approval for: shelf.packages.conservative.apy: backtest value changed 5.365 → 3.709; shelf.packages.conservative.drawdown: backtest value changed 0.04 → 0.047

Одобрение относится ровно к этой витрине (строка ниже — её отпечаток; другую витрину оно не пропустит):

publication-approves: landing/src/data/site_numbers.json 2026-10-29 sha256:e540b5e6542bcd5c53e9e239c6201833fa23220d0249e51f5dce728cfe489ec9

## Как понять, что готово
Ты нажал кнопку в Телеграме (или написал в карточке «одобряю» / «отклоняю»); при одобрении оркестратор запушит с трейлером `Owner-Approved: <id-карточки>`.

## Что будет после
Одобришь → изменение уезжает в live /dashboard и на сайт. Отклонишь → оркестратор не трогает эту область.

<!-- owner-gate-fingerprint: 135e6150119d -->
