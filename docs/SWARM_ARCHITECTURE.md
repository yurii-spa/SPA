# SPA Swarm — рефлекторный харвестер carry (charter / ADR-YL-012)

> **Owner-директива (2026-07-11):** продумать архитектуру агентов (10–50+, сколько нужно), которые
> непрерывно следят за рынком и нашими «вкладами» и выводят агрессивный тир на реальные ~20–25% —
> с рисками, но минимизированными системно. Этот документ — canonical charter архитектуры.
> Статус: **paper-only, advisory** — капитал не двигает, go-live трек не трогает, RiskPolicy v1.0 не меняет.

---

## Тезис (одна строка)

**Мы не покупаем более высокий yield — мы покупаем более высокий uptime на условно-высоком carry
и режем хвост скоростью реакции + отказом + сайзингом к ликвидности выхода.**

```
Доход = Σ( carry_i × uptime_i ) − Σ( tail_i )
```

Рынок платит 15–30% за риск, который большинство держит слепо. Кто видит риск в реальном времени —
держит carry, пока он зелёный, и де-рискует за часы до того, как он становится красным. Разница
между «слепым» и «зрячим» держателем — наш edge. Он **уже подтверждён числами** (см. «Доказанная база»).

## Честные пределы (без них это маркетинг, не инженерия)

1. **Скорость лечит только МЕДЛЕННЫЙ риск** (funding-flip, TVL-bleed, эрозия пега, vol-режим —
   разворачиваются часами). Против **GAP-риска** (эксплойт, мгновенный депег, осушенный выход)
   не успеет ни один агент — работают только сайзинг + диверсификация + refusal. Остаточный хвост
   существует всегда и всегда показан клиенту.
2. **20–25% — режимно-условны.** В зелёном funding-режиме система даёт 18–25%+, во враждебном —
   честно отказывается и даёт 5–8% (floor + fixed-carry). Средняя через цикл ~13–18%.
   Система, обещающая 20–25% «всегда», — ложь по построению.
3. **Больше агентов ≠ больше edge.** Edge даёт петля sense→react→size; агенты дают ей скорость и
   полноту зрения. ~40–70 логических агентов достаточно; 1000 — шум.
4. **Ёмкость.** Exotic-sleeve'ы (levered PT) тонкие (~$1M cliff); дальше компрессия к core.
   Capacity governor обязан это отслеживать и показывать.
5. **«Безопасное плечо» недоказуемо вперёд** — только стресс-тест против прошлых кризисов +
   форвардный paper сквозь реальное событие (вердикт UPD4 реестра идей).

## Доказанная база (реестр `docs/DYNAMIC_LEVERAGE_GUARDIAN.md`, все числа — backtest/OOS)

| # | Идея | Вердикт | Ключевое число |
|---|---|---|---|
| 1 | Pre-emptive vol-guardian (де-риск на всплеск собственной vol ДО убытка) | ✅ OOS-валидирован | susde_dn: доход 4.2→7.3%, DD 8.5→4.5%, Calmar ×3; OOS держится на всех 5 книгах |
| 2 | Наивная диверсификация скоррелированных книг | ❌ | corr 0.87 → портфель хуже лучшей одиночной |
| 3 | **Cross-desk бленд** (sUSDe-carry + rates-carry + RWA-floor, corr ≈ 0) | ✅ дефолт тира | 25/50/25: тот же доход, DD 8.5→2.1% (−75%), Calmar ×4; режет хвост ~4× в КАЖДОМ из 3 кризисов |
| 4 | Vol-targeted сайзинг (непрерывный) | ⚠️ | доход↑ держится OOS, risk-adjusted edge на калме — нет; дефолт остаётся фикс-бленд #3 |
| 5 | Refusal-veto как портфельный фильтр | ✅ selection-edge | отказ от C/D-книг доминирует по ОБЕИМ осям при кризисах ≥0.81× исторических |

**Синтез для роя:** #1 (guardian) = страж каждой позиции; #3 (cross-desk) = скелет портфеля;
#5 (refusal) = входной фильтр; #4 — не включать (недоказан). Всё выше — backtest;
**миссия роя — превратить это в живой форвардный paper-трек** (только форвард делает числа продаваемыми).

---

## Архитектура: 5 слоёв

```
L0 СЕНСОРЫ (15–20)          глаза: multi-source quorum, keyless, fail-closed
   есть:  peg, tvl, oracle, liquidity        (RTMR, spa_core/monitoring/sensors/)
   есть:  funding ×5 бирж                    (strategy_lab/data/funding_feed.py)
   есть:  PT implied-rate surface            (rates_desk/feeds.py)
   есть:  depth_at_size / exit-NAV           (rates_desk/depth_at_size.py)
   добавить: governance/red-flag поток, bridge health, CEX basis,
             points-реализация, stable-flows
L1 СИГНАЛ (8–10)            мозжечок: сырьё → смысл
   есть:  fair-value / mispricing            (rates_desk/fair_value.py)
   есть:  tail estimator                     (aggressive_lab/tail_overlay.py)
   есть:  vol-режим per-book                 (aggressive_lab/guardian.py — OOS-валидирован)
   добавить: funding-regime classifier (зелёный/жёлтый/красный carry-режим),
             anomaly, cross-book correlation monitor
L2 СТРАЖИ ПОЗИЦИЙ (1 на книгу, 10–40)   ← сердце роя
   каждая paper-книга получает персонального стража: thesis входа, kill-линии,
   exit-depth-бюджет, vol-guardian состояние (exposure 0/1), причина де-риска.
   Полномочия ТОЛЬКО de-risk. Физически — ОДИН supervisor-процесс
   с per-book state-машинами (логически N агентов, дёшево).
   → spa_core/strategy_lab/swarm/guardian_forward.py (блок 1, построен)
L3 МОЗГ (3–5)               детерминированный, LLM FORBIDDEN
   Dynamic Leverage Guardian: плечо = f(live exit-depth, carry, vol-режим, форма хвоста)
   allocator по бленду #3 (25/50/25 как дефолт), rebalancer,
   capacity governor ($1M cliff)
L4 ИММУНИТЕТ (5–8)          агенты, следящие за агентами
   есть:  agent_health, system_health, resilience_status, proof-chain
   добавить: swarm-health (стражи живы? сигналы свежи?), data-quorum аудитор,
             backtest-vs-forward drift, chaos-drill роя
```

### Правила роя (инварианты, наследуют FORBIDDEN-список CLAUDE.md)

- **Детерминизм, stdlib-only, LLM FORBIDDEN** во всех слоях risk/reaction (это risk-путь).
- **Fail-CLOSED:** нет данных / не сошёлся кворум / нельзя измерить выход → exposure 0, не «понадеемся».
- **De-risk-only:** ни один страж не может УВЕЛИЧИТЬ риск; увеличение — только детерминированный
  allocator L3 в дневном цикле по зелёному режиму.
- **Advisory / paper:** весь рой живёт вне RiskPolicy v1.0 (aggressive-домен, owner-selectable),
  капитал не двигает; глобальный two-tier kill (SOFT 5% / HARD 10%) — нетронут и главнее.
- **Хвост всегда показан:** каждая публичная цифра APY несёт evidence-level, worst-DD и
  остаточный gap-риск. Никогда не продавать риск как безопасность.
- **Proof-chain:** каждое решение стража (де-риск/ре-entry/отказ) — в hash-chain, публично проверяемо.

## Как рой достигает 15–25% (механика, не обещание)

| Sleeve | Платит (режимно) | Кто держит риск в узде |
|---|---|---|
| sUSDe/funding carry | 8–25% | L1 funding-regime + L2 vol-guardian: держим ТОЛЬКО в зелёном, выход при инверсии за часы |
| Levered PT fixed-carry (валидированные книги) | база × плечо | L3 Dynamic Leverage Guardian: плечо ≤ exitable-before-tail по живой глубине |
| Concentrated LP | 15–30% fees | L2 IL-страж (выход при развороте диапазона) |
| RWA-floor + rates-carry | ~3.4% + ~4.6% | декоррелятор бленда #3 — поглощает депег/unwind |
| Points/LRT | 20–40% «бумажных» | **маркируем в 0** до реализации; опцион, не доход |

## Дорожная карта (блоки; каждый — паперный, проверяемый, публикуемый)

| Блок | Что | Статус |
|---|---|---|
| 0 | Backtest-валидация guardian/cross-desk/refusal (идеи #1–#5) | ✅ сделано (реестр) |
| 1 | **L2 стражи форвард**: vol-guardian overlay на живом paper-треке всех aggressive-книг, per-book state + status JSON + hash-proof | ✅ построен (`swarm/guardian_forward.py`, агент `com.spa.swarm_guardian`) |
| 2 | Форвардный 3-desk бленд #3 (25/50/25) как paper-портфель роя + risk-parity веса | план |
| 3 | L1 funding-regime classifier (зелёный/жёлтый/красный) на 5-venue funding + подключение стражам как экзогенный сигнал (раньше собственной vol) | план |
| 4 | L3 Dynamic Leverage Guardian форвард: плечо = f(depth_at_size, carry, режим, tail) на levered-книгах | план (после блока 3) |
| 5 | L4 swarm-health + drift-монитор + chaos-drill | план |
| 6 | Публичная поверхность: /aggressive live-трек с uptime-статистикой, guarded-vs-raw, хвостом и refusal-логом | план |
| 7 | Через ≥30 форвардных дней и ≥1 реальное vol-событие: owner + Red Team ревью → решение о статусе тира | gate |

**Критерий успеха роя (falsifiable):** на живом форвардном треке guarded-книги показывают
maxDD ≤ ~50% от raw при удержании ≥80% дохода зелёных периодов; бленд #3 форвард держит
Calmar ≥ 2× лучшей одиночной книги. Не показал — честно пишем и перепроектируем.

---

*Создан 2026-07-11. Связан: `docs/DYNAMIC_LEVERAGE_GUARDIAN.md` (реестр идей + числа),
`docs/THREE_TIER_YIELD_PRODUCT.md` (продуктовый charter), `docs/RTMR_INTEGRATION_MAP.md` (L0),
`docs/RATES_DESK.md` (fair-value/refusal), `docs/STRATEGY_LAB.md` (harness).*
