# SPA Swarm — разбор сессии 2026-07-11/12 (по просьбе владельца 2026-07-16)

> **Источник:** `SPA_exports/2026-07-11_swarm_session_chat_export.md` (4744 строки, диалог сессии
> `c607edcd`). Полный разбор архитектором: каждая мысль извлечена и сверена с **origin/main**
> (локальное дерево отстаёт — API-push дрейф; вся работа роя в origin присутствует).
> **Всё построенное — paper / advisory / OUTSIDE RiskPolicy.** Go-live трек и RiskPolicy v1.0 НЕ тронуты.

## Итог одной строкой

**31 мысль. ~23 УЖЕ СДЕЛАНО** (весь рой построен и живёт), **~5 частично**, **~6 owner-gates**
(в основном время-гейты — ждут накопления данных, решение владельца по мере созревания). Коммиты
`bf3def4d…a638e86c` — в origin. **Чтобы не заваливать канбан 23 карточками «сделано», полный реестр —
здесь; отдельной карточкой вынесено только то, что реально нужно от тебя сейчас (пилот ~22 июля).**

## Реестр (31 пункт)

| # | Мысль | Тип | Сделано? | Нужно? |
|---|---|---|---|---|
| 1 | «Max Yield» карточка показывала «—» | wish | ✅ DONE (index.astro: Aggressive «up to 20%» + refused-for-live + хвост) | нет |
| 2 | Честная декомпозиция 15-20% (нет low-tail 15-20%) | decision | ✅ DONE (ADR-YL-012 + site-copy: хвост всегда виден) | нет |
| 3 | Директива «рой уровня бог → 20-25% при мин. риске» | wish | ✅ DONE (SPA Swarm, 6 органов) | нет (кроме блока 7) |
| 4 | Charter — 5-слойная архитектура | built | ✅ DONE (SWARM_ARCHITECTURE.md + ADR-YL-012) | нет |
| 5 | Блок 1 — L2 стражи позиций (форвард) | built | ✅ DONE (guardian_forward.py, com.spa.swarm_guardian) | нет |
| 6 | Блок 6 — /aggressive-lab + /api/swarm/* | built | 🟡 PARTIAL: API есть; swarm-бейджи на странице ушли при редизайне | **MAYBE — owner** |
| 7 | Блок 2 — 3-desk бленд 25/50/25 | built | ✅ DONE (blend_forward.py, com.spa.swarm_blend) | нет |
| 8 | Блок 3 — классификатор funding-режима | built | ✅ DONE (funding_regime.py, com.spa.swarm_regime) | нет |
| 9 | Блок 4 — Dynamic Leverage Guardian (мозг) | built | ✅ DONE (leverage_brain.py, com.spa.swarm_brain) | нет |
| 10 | Блок 5 — иммунитет (swarm_health) | built | ✅ DONE (swarm_health.py, com.spa.swarm_health) | нет |
| 11 | Блок 5b — chaos-drill (еженедельно) | built | ✅ DONE (chaos_drill.py, 6/6) | нет |
| 12 | S1 — shadow-стражи на все домены + фикс zero-vol | built | ✅ DONE (commit 6f560a19) | нет |
| 13 | S2 — леджер опережения (leadtime) | built | ✅ DONE (leadtime_evidence.py) | **гейт — копит данные** |
| 14 | Автономный R&D-цикл edge-идей (1-2×/нед) | decision | ✅ DONE (scheduled novel-edge-rnd, вт+пт; дал #7) | нет |
| 15 | Вопрос: рой на все тиры? | Q→ans | 🟡 S1 done, S2 идёт, S3/S4 гейты | **owner (ADR после S2)** |
| 16 | CLAUDE.md секция про рой | built | 🟡 PARTIAL: сжато до ADR-ссылки при конденсации | MAYBE (опц.) |
| 17 | Round-2 А — Swarm Book (портфель, которым рой рулит) | built | ✅ DONE (swarm_book.py, /api/swarm/book) | нет |
| 18 | Round-2 Б — RTMR-сигналы прямо в стражей | built | ✅ DONE (guardian OR-gate rtmr_exogenous) | нет |
| 19 | Round-2 В — системный корреляционный часовой | built | ✅ DONE (в swarm_book веса) | нет |
| 20 | Round-2 Г — рой зовёт на помощь (d6→Telegram) | built | ✅ DONE (гейт d6.swarm) | нет |
| 21 | Owner-wish: уникальный Tier-1 (алгоритм, не публикация) | wish | ✅ DONE (переориентировано → EYC) | owner (направление задано) |
| 22 | Proof-панель Tier-1 (verify_spa I + /api/tier1/proof + scorecard) | built | ✅ DONE (verify_spa.py, track-record scorecard) | нет |
| 23 | Идея #6 — EYC, бэктест (5.76% vs 5.24% при 10× меньше churn) | built | ✅ DONE (equilibrium_yield_backtest.py) | нет |
| 24 | EYC v2 — shadow-аллокатор («APY после нас») | built | ✅ DONE (eyc_allocator.py, /api/swarm/eyc) | **гейт — копит divergence** |
| 25 | Вопрос: EYC/рой на базовый тир? | Q→ans | 🟡 shadow на базовом готов; боевое = гейт | **owner-decision (ADR)** |
| 26 | Ежедневный аппендер historical_apy (расширить вселенную EYC) | idea | 🟡 PARTIAL: fetch_historical_apy есть; EYC читает historical_apy | MAYBE (R&D) |
| 27 | Фикс: launchd wrapper cd перед `-m` (ModuleNotFound) | built | ✅ DONE (commit a638e86c) | нет |
| 28 | Живые числа пакетов 1/2/3 «на сегодня» | Q→ans | ✅ DONE (справочный ответ) | нет |
| 29 | **$1k живой пилот на пакет (~22 июля) + live-vs-paper сверщик** | wish/idea | 🟡 PARTIAL: общие сверщики есть, целевого нет | **🔴 NEEDED + owner (дата близко)** |
| 30 | Блок 7 — вердикт по агрессивному тиру (≥30 дней + шторм) | гейт | ⏳ NOT-DONE (by design, копится) | **owner (время, ~сер. авг)** |
| 31 | R&D уже дал находки (#7 PERS positive, #8) | built | ✅ DONE (commit 8cac68a77) | нет |

## Что реально нужно от тебя (actionable)

- **🔴 #29 — $1k живой пилот пакета 1 (~22 июля) + live-vs-paper сверщик.** Единственный близкий по
  времени пункт: дата приближается, целевого сверщика (сравнить живой $1k с бумажным треком) ещё нет,
  и запуск non-custodial пилота — твоё решение. **Вынесен отдельной карточкой `own-*`.**
- 🟡 #6 — вернуть ли swarm-бейджи (страж/carry-погода) на публичную `/aggressive-lab` (API готов) — твоя
  вкусовая правка. #16 — нужна ли отдельная swarm-секция в CLAUDE.md (контекст сохранён в ADR).

## Время-гейты (НЕ действие сейчас — Claude принесёт данные по мере созревания)

- **#13/#30 S2-леджер + блок-7** (~середина августа): ≥30 форв. дней Swarm Book + 1 реальный шторм → твой ADR.
- **#24/#25 промоушен EYC в живой базовый тир**: копит divergence-досье → ADR (первый кандидат на промоушен).
- **#15 S3/S4** (vol-режим как 5-й RTMR-сенсор; Balanced-продуктизация): твои ADR после данных S2.

_Разбор read-only (архитектор ничего не менял). Этот документ — полный «карточный» реестр всех мыслей
сессии; отдельные tracker-карточки заведены только под actionable-пункты, чтобы не засорять канбан
23 карточками «уже сделано»._
