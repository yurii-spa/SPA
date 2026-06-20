# DECISIONS — Журнал решений сессий

Агент добавляет запись в КОНЦЕ каждой сессии. Читай последние 3-5 записей в начале сессии.

---

## 2026-06-21 (Session decisions — ADR-042…047)

Шесть решений сессии задокументированы как ADR. Исходно черновики были
пронумерованы 030–035, но эти номера заняты (ADR-030…041 уже существуют), поэтому
перенумерованы в **ADR-042…047** для непрерывной последовательности.

| ADR | Тема | Status | Ключевое |
|-----|------|--------|----------|
| [ADR-042](adr/ADR-042-backtest-harness-design.md) | Backtest Harness Design | Accepted | 35+ backtest-файлов наконец прогнаны; adapter-harness в `scripts/run_backtest.py` нормализует 3 несовместимых интерфейса в дневные equity curves. S7=11.08%, S2=8.98%, S0=5.72% (90д synthetic). **S7 bear = −14.28%** — risk-сигнал. |
| [ADR-043](adr/ADR-043-new-protocol-adapters-ethena-fluid-usual.md) | New Protocol Adapters (Ethena/Fluid/Usual) | Accepted | 3 новых T2-адаптера, layered fallback (direct API → DeFiLlama → cache). Live APY: Ethena 3.50%, Fluid 6.22%, Usual 2.27%. Registry → 22 активных tuple. |
| [ADR-044](adr/ADR-044-bear-market-hedge-strategy.md) | Bear-Market Hedge S31 + Market-Neutral S32 | **Proposed** | Мотивирован S7 −14.28%. Regime detection: Aave utilization + T2 APY trend. Target max DD <0.5% в bear. S31/S32 ещё не реализованы. |
| [ADR-045](adr/ADR-045-kelly-criterion-allocation.md) | Kelly Criterion Allocation | Accepted | Half-Kelly (50% blend), tier-based hack prob: T1 0.5%/y, T2 2.0%, T3 5.0%. Реализован `spa_core/allocator/kelly_sizer.py`. Supersedes ADR_012 sizing rationale. |
| [ADR-046](adr/ADR-046-multi-chain-expansion-strategy.md) | Multi-Chain Expansion | Accepted | Read-only адаптеры Arbitrum (Aave/Radiant/GMX) + Optimism (Aave/Velodrome). Bridge risk + gas monitoring. T2-until-proven per-chain. |
| [ADR-047](adr/ADR-047-site-privacy-hardening.md) | Site Privacy Hardening (earn-defi.com) | Accepted | Reframe → «personal research project, paper validation». `noindex` все страницы, удалён mechanism of entry, переработан emergency-withdrawal. `scripts/cf_install_token.command` НЕ пушится (secrets policy). |

**Что сделано:**
- Прочитан формат существующих ADR (ADR-041, ADR_TEMPLATE) и `docs/DECISIONS.md`
- Верифицированы артефакты сессии в репо: `scripts/run_backtest.py` ✓, адаптеры
  ethena/fluid/usual ✓ (T2, MP-1227), `kelly_sizer.py` ✓ (half-Kelly, T1/T2/T3 = 0.5/2.0/5.0%),
  arb/op адаптеры ✓. S31/S32 — **отсутствуют** → ADR-044 в статусе Proposed.
- Написаны 6 ADR (042–047), обновлён `docs/adr/ADR_INDEX.md`

**Заметки:**
- Перенумерация 030–035 → 042–047 (коллизия номеров)
- ADR-045 ссылается и supersede'ит sizing-обоснование `docs/ADR_012_dynamic_kelly_sizing.md`
- SECURITY: `scripts/cf_install_token.command` исключён из всех пушей

---

## 2026-06-12 (v4.64 Phase2 Roadmap)

**Что сделано:**
- Прочитан полный контекст: CURRENT_STATE, KANBAN, RULES, ADR-002, golive_status, equity_curve, gap_monitor
- Оценка готовности к Phase 2: **42/100** (главный блокер — 3/30 дней трека)
- GoLiveChecker: технически READY (все 6 критериев), но ADR-002 требует READY 7+ дней подряд — ETA 2026-06-17
- Создан `docs/PHASE2_ROADMAP.md` — критический путь, sprint plan v4.64–v4.70, риски
- KANBAN обновлён: sprint_current → v4.64; добавлены MP-350 (Telegram activation), MP-351 (preflight script), MP-352 (chain concentration)

**Ключевые выводы:**
- Autopush работал раньше как автономный агент v4.64 — KANBAN уже на v4.64 при нашей работе
- Минимальный путь к live-пилоту: MP-402 ✅ → 30d track → ADR-002 review → activate.py (ERC-4626 не нужен для личного пилота)
- Все Phase 2 features (MP-403-507) в правильном dependency order, разблокированы последовательно

**Топ-5 блокеров (не изменились):**
1. Трек record: 3/30 дней (27 дней ждать)
2. MP-313: bash mp009_fix_launchd.command (USER ACTION P0)
3. UA-004: GitHub Pages (USER ACTION P1)
4. MP-017: RPC keys для Pendle (USER ACTION P1)
5. ADR-011 manual review (Owner action к 2026-07-15)

**Следующий автономный sprint (v4.64):**
- MP-350: Активировать Telegram daily report (снять dry_run) — код готов, token в Keychain
- MP-351: ADR-011 pre-flight скрипт — автоматизировать всё что можно из 39-point checklist
- MP-352: ethereum chain concentration → разобраться и понизить до INFO если структурно

---

## 2026-06-12 (SYS-sprint)

**Что сделано:**
- Аудит истории проекта (SPA_audit_report.md, 561 строка)
- Выявлено 7 категорий системных ошибок
- Создано 13 SYS-задач в KANBAN backlog (SYS-001..010, MP-312..314)
- MP-310 Decision Audit Trail (72 теста)
- MP-146 Ulcer Index (81 тест)
- MP-147 Bias Ratio (58 тестов)
- CURRENT_STATE.md создан (SYS-001)
- CLAUDE.md согласован с реальностью (SYS-002)
- DECISIONS.md создан (SYS-006)

**Что НЕ сделано и почему:**
- Autopush не работает (USER ACTION: `bash mp009_fix_launchd.command` — пользователь не запустил)
- Telegram daily report не активирован (ждёт Telegram token от пользователя, задача MP-314)
- GitHub Pages не включены (USER ACTION: Settings → Pages → main/root)
- Sprint log v4.31-v4.47 пропущен (9 записей, задача SYS-009 в backlog)

**Блокеры для следующей сессии:**
- USER ACTION: `bash mp009_fix_launchd.command` (P0, ~2 мин)
- USER ACTION: Telegram token → daily report (MP-314)

**Следующий приоритет (автономно):**
- SYS-003/004/005/007/008: Обновить RULES.md (sprint DoD, infra-first, anti-HALT, startup, delivery_status)
- SYS-009: Восстановить sprint log v4.31-v4.47
- MP-312: Kill-switch drill

---

## 2026-06-12 (MP-412 ADR-023 Strategy Promotion Policy)

| ADR | Date | Topic | Status | Notes |
|-----|------|-------|--------|-------|
| ADR-023 | 2026-06-12 | Strategy Promotion Policy Paper→Live | Accepted | T3 requires 30d, T1/T2 14d |

**Что сделано:**
- Создан `docs/ADR-023-strategy-promotion-policy.md` — детерминированные критерии продвижения стратегий
- Promotion Gate: MIN_DAYS_PAPER ≥14d, SHARPE ≥0.80, MAX_DD ≥-5%, APY ≥7.0%, CALMAR ≥1.0
- T3/T3-SPEC (S7, S8, S10): MIN_DAYS ≥30d, SHARPE ≥1.0, MAX_ALLOC 30%, требует USER_APPROVAL
- S7 (Pendle YT+PT, 10.115% APY) — первая стратегия выше 10% барьера, Est. promotion 2026-07-12
- KANBAN: MP-412 → done
