# SPA — Live Sprint Status

> **Живой трекер спринтов.** Обновляется КАЖДЫЙ firing автономного лупа. Источник задач:
> `docs/ROADMAP_2MONTH_EISENHOWER_v2.md` (4 двухнедельных спринта) + вплетаемые Month-1/2 задачи
> из `docs/TOURNAMENT_VERDICT_AND_6MO_BACKLOG.md` (3-тир продукт). Легенда: ✅ done · 🔄 in progress · ⬜ next.

**Обновлено:** 2026-07-11 (firing #14) · **Текущий спринт:** Sprint 1–2 (W1–W4) активно · **Track:** 19/30 evidenced (go-live ~07-21)

---

## 🎯 Текущий фокус (в работе / следующее)

| Статус | Задача | Спринт |
|---|---|---|
| 🔄 | 3-тир продукт: вывод realized+tail на все поверхности | 6mo M3–M5 (вплетено) |
| ⬜ | #13→#14 турнир на реальные фиды → tail-penalized ранжирование | Sprint 2 (M2) |
| ⬜ | Q2-10 offline DD snapshot (`verify_spa --offline`, замороженный checksummed датасет) | Sprint 2 |
| ⬜ | Q2-11 / Q2-12 checkup: Uniswap V3 LP + Morpho/Fluid leverage detection | Sprint 3 |
| ⬜ | Q2-10 offline DD snapshot дальше по фокусу | Sprint 2 |

---

## Sprint 1 · W1–W2 — «Green the gate, guard the track, stop the bleeding»
**Цель:** войти в go-live-окно с доверенной readiness-поверхностью, живой DR-цепочкой, восстановленной честностью чисел.

| # | Задача | Статус | Коммит |
|---|---|---|---|
| Q1-2 | reconcile golive_preflight (sprint_log_md → PASS при KANBAN) | ✅ | `a423d85e` |
| Q1-7 | conversion instrumentation (data-track) на всех proof-страницах | ✅ | `3cc80d97` |
| Q1-8 | self-clearing gap-recovery state | ✅ | `b73600b4` |
| Q1-10 | resilience → agent_health WARNING | ✅ (было готово) | — |
| Q1-11 | golive/pre_cutover freshness agent | ✅ (built, bootstrap owner) | — |

## Sprint 2 · W3–W4 — «Prove scale & replayability; wake the funnel & the blog»
**Цель:** превратить «edge — артефакт $100k» в измеренную кривую масштаба; сделать отказы воспроизводимыми; включить discoverability.

| # | Задача | Статус | Коммит |
|---|---|---|---|
| Q2-1 | N-book capacity aggregator (кривая above-floor $/yr) | ✅ | `c7ee9c6c` |
| Q2-5b | avoided-loss refusal P&L ledger (~$49k/100k) | ✅ | `5888c0e7` |
| Q2-9 | self-verifying data-room bundle (hostile reviewer) | ✅ | `f5bf9819` |
| Q2-15 | RSS/Atom feed + BlogPosting JSON-LD | ✅ | `e4f27123` |
| Q2-16 | per-protocol SEO-страницы (is ezETH safe? …) | ✅ | `889544ba` |
| Q2-17 | days-to-verdict countdown | ✅ | `e29bcdf4` |
| #16 | tournament data-trust monitor + agent_health WARNING | ✅ | `a059b631` |
| #17 | promotion-framework parity (2 фреймворка + parity-тест) | ✅ | `b684c583` |
| Q2-18 | dated evidenced-track ledger 19→30 (per-day dd/return, /api/readiness) | ✅ | `pending` |
| Q2-2 | `--replay` verifier | ⬜ (branch-blocked: verify_spa на verifier-v1.1) | — |

## Q3 batch — housekeeping / alert-fatigue
| # | Задача | Статус | Коммит |
|---|---|---|---|
| Q3-1 | retire redundant weekly_backup | ✅ | `80037cee` |
| Q3-2 | fleet-parity self-check | ✅ | `ad957143` |
| Q3-4 | consecutive-ready-days на /readiness | ✅ | `0374945b` |
| Q3-5 | kill-switch drill EVIDENCE артефакт (latency + дата) | ✅ | `59cd31b4` |
| Q3-6 | kill-switch drill в resilience_cycle | ✅ | `59cd31b4` |
| Q3-3 | checkup KNOWN_SPENDERS per-chain routers | ⛔ SKIP (нужны верифиц. адреса — риск фабрикации) | — |

---

## 🏗️ Параллельный трек: 3-ТИР ПРОДУКТ (owner #1 приоритет · 6mo Month-1/2 вплетено)
**Цель:** продаваемые 3 тира с честными числами, показанным хвостом, enforced-правилами. Полный стек прошит.

| # | Задача | Статус | Коммит |
|---|---|---|---|
| M1 #1 | `tier_policy.py` — enforced правила per-tier (вне RiskPolicy) | ✅ | `214b9a32` |
| M1 #2 | enforce tier_policy в roster (parking eth_directional) | ✅ | `7b485f6b` |
| M1 #5 | annualization guard (убран артефакт 517%) | ✅ | `1c801341` |
| M1 #7 | единый источник APY-бэндов (фикс 6–8% vs 2–6%) | ✅ | `14866997` |
| M1 #11 | tier-band consistency guard (WARN-only) | ✅ | `d299b8e8` |
| M2 #22 | strategy-census guard | ✅ | `8a319e7b` |
| — | scorecard tier wire-through (→ /api) | ✅ | `c1a4ad75` |
| M3 #33 | 3-строчный tier-card контракт (band+evidence+tail) на /packages | ✅ | `3f8200ef` |
| M5 #46 | хвост в точке выбора на главной (никаких «—») | ✅ | `4c90e8fc` |
| M5 #47 | data-track на выбор тира | ✅ | `f2729148` |
| M5 #50 | proof-strip на /packages | ✅ | `20148f15` |
| M3 #32 | realized+tail из регенерированного scorecard.json | ⬜ | — |
| M2 #14 | tail-penalized (Calmar) ранжирование турнира | ⬜ (gated на #13 real feeds) | — |
| #6/#8 | канон. имена тиров + публичное APY-число | 🔒 OWNER | — |

---

## 🔁 Стоячие треки (постоянные, вне спринтов)
| Трек | Механизм | Статус |
|---|---|---|
| Novel-edge R&D (поиск заработка) | **облачная routine** `trig_016xZei1jPzEeek3LcUvJkHV`, ежедневно 08:13 UTC | ✅ live (permanent) |
| Roadmap ship loop | cron `fe025b9e` каждые 10 мин | ✅ live |
| Автопуш / GitHub | push_to_github_batch.py → origin/main | ✅ |

---

## 🔒 Owner-gated (механизм построен, жду решения)
- **#6/#8** — канонические имена тиров (Conservative/Balanced/Aggressive vs Preserve/Core/Max) + публичное APY-число.
- **Q1-5** Etherscan-ключ на prod (checkup approvals).
- **Q2-3** WALLET_REF_SALT + RESEND (checkup retention).
- **Q2-4** funnel terminal copy (legal).
- **Bootstrap** агентов golive_freshness / resilience на Mac (через `check_agent_before_deploy`).
- Legal / custody / audit / 30-дневный трек — критический путь go-live.
