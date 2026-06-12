# SPA — SYSTEM HEALTH

> Живой документ состояния системы. Обновляется при каждом существенном
> изменении. Последнее обновление: **2026-06-12** (SYS-audit: 13 системных задач добавлены в backlog).
> План пересборки: `REBUILD_PLAN_v1.md`. Задачи: `KANBAN.json`.

---

## Сводка за 2 минуты

**SPA — система автоматического управления stablecoin-доходностью в DeFi.
Сейчас: paper trading (виртуальные $100K), реальные рыночные данные,
ни одной транзакции с реальным капиталом.**

| Метрика | Значение | Дата |
|---|---|---|
| Реальный track record | **3 дня** (старт 2026-06-10) | 2026-06-12 |
| Equity | $100,026.06 (+0.026%) | 2026-06-12 |
| APY текущий | **3.20%** | 2026-06-12 |
| APY цель | 7.3% (gap −4.1 пп, структурный) | — |
| Живых адаптеров | 5 (Aave, Morpho, Yearn, Euler, Maple) | 2026-06-12 |
| Сделок (реальных paper) | 3 (T001/T002/T003) | 2026-06-12 |
| Max drawdown | 0.0% (день 3 — пока не показателен) | — |
| Sharpe / Sortino | INSUFFICIENT (<7d) — модуль honest_metrics ✅ | — |
| Go-live решение | 2026-07-15 (осталось 33 дня) | — |
| Реальный капитал | **$0** (исполнение заблокировано by design) | — |

---

## Светофор по слоям

| Слой | Статус | Одной строкой |
|---|---|---|
| 1. Data feeds | 🟡 | 5/8 адаптеров живые (DeFiLlama live); Compound V3 не поднялся; Pendle/Sky не подключены → потолок APY ~4.7% |
| 2. Allocation | 🟡 | Цикл замкнут, caps работают; но RiskPolicy.check() не блокирует сделки напрямую, cash 0% против min_cash 5% (нужен ADR) |
| 3. Paper trading | 🟢 | cycle_runner ежедневно 08:00 (launchd), атомарная запись, is_demo:false; 3 дня трека ✅ |
| 4. Analytics | 🟡 | honest_metrics (MP-138) ✅, backtest_vs_paper (MP-140) ✅, structural_break (MP-139) ✅, progress_tracker (MP-141) ✅ — все INSUFFICIENT день 3 (норма) |
| 5. Strategies | 🟡 | 6 shadow-стратегий (S0–S5), S0 лидирует $100,039; selector активируется на 15-й день трека |
| 6. Monitoring | 🟡 | Telegram бот ✅ (daily_report, milestone_alert, cycle_gap_monitor); cycle_gap_monitor в разработке (MP-144) |
| 7. Dashboard | 🟡 | Dashboard v3.0 ✅ — Performance/Strategies/Risk/Ops tabs; Go-Live Timeline панель; читает реальные data/*.json |
| 8. Docs | 🟡 | ROADMAP_v2 / ARCHITECTURE_v2 / GRAND_VISION актуальны; CLAUDE.md лжёт (заморожен 2026-05-22) |
| 9. Infra | 🟡 | daily_cycle ✅, cloudflared ✅; httpserver ❌ (exit 78), autopush ❌ (exit 2); один Mac, DR нет |
| Security | 🟡 | PAT ротирован в Keychain; CI lint MP-309 в разработке; 0 секретов в файлах |
| 10. Системные долги | 🔴 | 13 SYS-задач в backlog из аудита 2026-06-12; autopush сломан, sprint log дырявый |

---

## Что работает автоматически

| Что | Расписание | Механизм | Статус |
|---|---|---|---|
| Paper-trading цикл (orchestrator → allocator → trades → equity) | ежедневно 08:00 | launchd `com.spa.daily_cycle` | ✅ |
| Cloudflare-туннель (localhost:8765) | постоянно | launchd `com.spa.cloudflared` | ✅ |
| Тесты + export + Pages deploy | каждые 4ч | GitHub Actions `spa-run.yml` | ⚠️ зависит от push и secrets |
| Alert rules | каждые 6ч | GitHub Actions `spa_alerts.yml` | ⚠️ dry_run, SMTP не настроен |
| HTTP-сервер дашборда | постоянно | launchd `com.spa.httpserver` | ❌ падает (права) |
| Автопуш в GitHub | каждые 90 мин | launchd `com.spa.autopush` | ❌ падает (права) |

---

## Что требует ручного действия (Owner)

1. ~~Ротировать GitHub PAT~~ — **✅ СДЕЛАНО** (PAT в Keychain)
2. **RPC-ключи Alchemy/Infura** (MP-017) — добавить в Keychain для Pendle PT feed (APY +2–3 пп)
3. Включить GitHub Pages (Settings → Pages → main / root) — UA-004
4. Workflow-scope token для GitHub Actions — UA-006
5. Принять ADR: min_cash 5% vs 0% cash-drag (текущая аллокация нарушает политику v1.0).
6. ~~Telegram бот настроить~~ — **✅ СДЕЛАНО** (TELEGRAM_BOT_TOKEN_SPA / TELEGRAM_CHAT_ID_SPA в Keychain)

---

## Ключевые риски сейчас

1. **Трек хрупкий:** один пропущенный день цикла до 2026-07-10 → перенос go-live.
   Cycle gap monitor (MP-144) в разработке — будет слать Telegram при пропуске.
2. **APY-gap структурный:** 3.20% против 7.3% — закрывается только подключением
   Pendle PT / Sky (Phase 2), требует RPC-ключи (MP-017, USER ACTION).
3. **httpserver + autopush:** launchd exit 78/exit 2 — нужен `mp009_fix_launchd.command`
   (одно ручное действие владельца). Без этого autopush не работает каждые 90 мин.
4. **Системный долг:** 9 пропущенных sprint log записей (v4.31-v4.47), CLAUDE.md vs RULES.md
   расходятся, sprint DoD не включает синхронизацию sprint_log. 13 SYS-задач в backlog (аудит 2026-06-12).

---

*Формат: обновляй таблицы, не добавляй разделы. История изменений — git.*
