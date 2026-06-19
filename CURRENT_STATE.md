# SPA System Current State
> Последнее обновление: **2026-06-19** | Версия: **v10.28** | Done: **1133** задач
> **ЧИТАЙ ЭТОТ ФАЙЛ ПЕРВЫМ** перед любой работой с проектом.
> ⚠️ Источник истины по done_count и sprint — всегда **KANBAN.json**, не этот файл.
> Governance-документы: `docs/governance/` (DEVELOPMENT_RULES, AI_ASSISTANT_RULES, GIT_WORKFLOW, ANTI_PATTERNS)

---

## SPA v10.28 — 2026-06-19

### Version: 10.0.0

| Поле | Значение |
|---|---|
| version | **10.0.0** (`spa_core/version.py`) |
| done_count | **1133** (KANBAN.json — source of truth) |
| sprint_completed | **v10.28** |
| Gate Status | Backtest ✅ Pre-Paper ✅ Paper ⏳ (0/30 pts) Live 🔒 |
| GoLive | **BLOCKED** — 35/100 pts, ETA ~2026-07-18 |
| Go-live target | **2026-08-01** |

---

## Architecture Health (Module Health Report)

| Issue | Status | Fix |
|-------|--------|-----|
| CRIT-001 | ✅ FIXED | KANBAN lock via `fcntl.LOCK_EX` |
| CRIT-002 | ✅ FIXED | 160 production tests added |
| CRIT-003 | ✅ FIXED | `LiveTradingGate` + `@live_trading_forbidden` |
| AUDIT-001 | ✅ FIXED | `atomic.py` centralized |
| AUDIT-002 | ⚠️ IN PROGRESS | 597 analytics files need BaseAnalytics migration |
| AUDIT-003 | ✅ FIXED | `defillama.py` centralized |
| AUDIT-004 | ✅ FIXED | Adapter registry — 20 adapters |

---

## Active Modules

- `spa_core/utils/`: `atomic.py`, `keychain.py`, `kanban.py`, `defillama.py`, `errors.py`
- `spa_core/safety/`: `live_trading_gate.py`, `safeguard.py`
- `spa_core/base.py`: `BaseAnalytics`, `BaseAdapter`, `BaseReport`
- `spa_core/adapters/registry.py`: 20 adapters (T1×7, T2×10, T3×3)
- `spa_core/family_fund/`: `investor_registration.py`, `withdrawal_engine.py`
- `spa_core/analytics/evidence_auto_calculator.py` (NEW)
- `scripts/`: `kanban_health.py`, `dead_code_scanner.py`, `analytics_conformance.py`, `migrate_atomic_writes.py`, `module_health_report.py`

---

## Infrastructure

| Компонент | Статус |
|-----------|--------|
| Push scripts wave 1 | ✅ (user pushed) |
| Push scripts wave 2 | ⏳ (user action pending) |
| Push scripts wave 3 | ⏳ (user action pending) |
| Push scripts wave 4 | ⏳ (user action pending — **NEW**) |
| Pre-commit hook | `scripts/pre_commit_check.sh` + `install_git_hooks.sh` |
| KANBAN health | `scripts/kanban_health.py` (--watch mode) |
| launchd `com.spa.daily_cycle` | ✅ (ежедневно 08:00) |
| launchd `com.spa.httpserver` | ✅ (port 8765) |
| launchd `com.spa.cloudflared` | ✅ (туннель) |
| launchd `com.spa.autopush` | ❌ НЕ УСТАНОВЛЕН — фикс: `bash mp009_fix_launchd.command` |

---

## Paper Trading

- Day 0 started
- Evidence: **0/30 pts**
- Evidence auto-calculator: NEW (`spa_core/analytics/evidence_auto_calculator.py`)
- ETA for 30 pts: ~30–68 дней от старта трека
- Цикл логи: `/tmp/spa_cycle.log`, `/tmp/spa_cycle_err.log`

---

## Push Pending (user action)

```bash
bash ~/Documents/SPA_Claude/scripts/run_cpa_wave2_pushes.sh   # v9.41-v9.70
bash ~/Documents/SPA_Claude/scripts/run_cpa_wave3_pushes.sh   # v9.71-v10.6
bash ~/Documents/SPA_Claude/scripts/run_cpa_wave4_pushes.sh   # v10.7-v10.28  ← NEW
```

Или двойной клик (Finder → double-click):
- `_push_wave4.command` — запускает wave4, лог в `/tmp/wave4_push.log`

---

## Wave 4 Sprint Summary (v10.7–v10.28)

| Sprint | MP | Описание |
|--------|----|----------|
| v10.7 | MP-1391 | Wave 3 master push script |
| v10.8–v10.18 | MP-1392–1402 | Infrastructure sprints |
| v10.19 | MP-1403 | AnalyticsConformanceChecker |
| v10.20 | MP-1404 | DeadCodeScanner v2 |
| v10.21–v10.26 | — | (scripts missing — будут SKIP в wave4) |
| **v10.27** | **MP-1411** | **Wave 4 consolidated push script (v10.7-v10.28)** |
| **v10.28** | **MP-1412** | **CURRENT_STATE v10.20 updated** |

---

## Open Issues

- 597 analytics files need BaseAnalytics migration (Phase 2-3)
- Paper trading evidence needs manual recording until launchd cron active
- Family Fund KYC: manual process, awaiting Yurii review
- GMX v2 DeFiLlama pool IDs: not found yet
- `com.spa.autopush` launchd не установлен — фикс: `bash mp009_fix_launchd.command`

---

## launchd — Активные сервисы

```
com.spa.daily_cycle   ✅  python3 -m spa_core.paper_trading.cycle_runner --verbose
com.spa.httpserver    ✅  http_server.py (port 8765)
com.spa.cloudflared   ✅  tunnel
com.spa.autopush      ❌  НЕ УСТАНОВЛЕН (PYTHON_PATH-заглушка; фикс: bash mp009_fix_launchd.command)
```

---

## RiskPolicy (актуальная)

| Параметр | Значение |
|----------|----------|
| Версия | v1.0 (заморожена на весь paper-период) |
| TVL floor | ≥ $5M на пул |
| Per-protocol cap | 40% T1 / 20% T2 |
| T2 total cap | ≤ 50% портфеля (ADR-019) |
| APY границы | 1% … 30% |
| Min cash buffer | ≥ 5% |
| Kill switch | drawdown ≥ 5% → закрыть всё |

`approved=False` от RiskPolicy не может быть переопределён никаким агентом.

---

*Обновлено: 2026-06-19 (MP-1412 v10.28 — CURRENT_STATE v10.20 updated, Wave 4 push script добавлен)*
