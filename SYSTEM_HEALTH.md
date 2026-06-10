# SPA — SYSTEM HEALTH

> Живой документ состояния системы. Обновляется при каждом существенном
> изменении. Последнее обновление: **2026-06-10** (teardown-аудит).
> План пересборки: `REBUILD_PLAN_v1.md`. Задачи: `KANBAN.json`.

---

## Сводка за 2 минуты

**SPA — система автоматического управления stablecoin-доходностью в DeFi.
Сейчас: paper trading (виртуальные $100K), реальные рыночные данные,
ни одной транзакции с реальным капиталом.**

| Метрика | Значение | Дата |
|---|---|---|
| Реальный track record | **1 день** (старт 2026-06-10) | 2026-06-10 |
| Equity | $100,010.09 (+0.0101%) | 2026-06-10 |
| APY текущий | **3.68%** | 2026-06-10 |
| APY цель | 7.3% (gap −3.6 пп, структурный) | — |
| Живых адаптеров | 5 (Aave, Morpho, Yearn, Euler, Maple) | 2026-06-10 |
| Сделок (реальных paper) | 1 (T001 — initial rebalance) | 2026-06-10 |
| Max drawdown | 0.0% (n=1 — не показателен) | — |
| Sharpe / Sortino | не вычислимы (нужно ≥30 дней) | — |
| Go-live решение | 2026-07-15 (30 честных дней ≈ 2026-07-10 — впритык) | — |
| Реальный капитал | **$0** (исполнение заблокировано by design) | — |

---

## Светофор по слоям

| Слой | Статус | Одной строкой |
|---|---|---|
| 1. Data feeds | 🟡 | 5/8 адаптеров живые (DeFiLlama live); Compound V3 не поднялся; Pendle/Sky не подключены → потолок APY ~4.7% |
| 2. Allocation | 🟡 | Цикл замкнут, caps работают; но RiskPolicy.check() не блокирует сделки напрямую, cash 0% против min_cash 5% (нужен ADR) |
| 3. Paper trading | 🟢 | cycle_runner ежедневно 08:00 (launchd), атомарная запись, is_demo:false; истории всего 1 день |
| 4. Analytics | 🔴 | 39/41 модулей — мёртвый код или считают шум на n=1; risk_metrics.json пуст |
| 5. Strategies | 🟡 | 6 shadow-стратегий работают, но на синтетике; selector активируется на 15-й день реального трека |
| 6. Monitoring | 🔴 | Все алерты в dry_run — реально ничего не отправляется; red_flags/incidents stale 13-14 дней |
| 7. Dashboard | 🔴 | Мешает демо (2026-05-22) с реальными данными — инвестору не показывать до RB-010 |
| 8. Docs | 🟡 | ROADMAP_v2 / ARCHITECTURE_v2 / GRAND_VISION актуальны; CLAUDE.md лжёт (заморожен 2026-05-22) |
| 9. Infra | 🟡 | daily_cycle ✅, cloudflared ✅; httpserver ❌ (exit 78), autopush ❌ (exit 2); один Mac, DR нет |
| Security | 🔴 | **Утёкший GitHub PAT в 76 файлах, не ротирован** — действие №1 |

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

1. 🔴 **Ротировать GitHub PAT** — отозвать утёкший токен в GitHub Settings,
   новый положить только в Keychain (`GITHUB_PAT_SPA`). Блокирует чистку мусора.
2. Заполнить GitHub Secrets: RPC-ключи (Alchemy/Infura), `TELEGRAM_BOT_TOKEN`,
   `TELEGRAM_CHAT_ID`, SMTP-креды — без них алерты остаются dry_run.
3. Включить GitHub Pages (Settings → Pages → main / root).
4. Принять ADR: min_cash 5% vs 0% cash-drag (текущая аллокация нарушает политику v1.0).
5. Принять ADR: правило переноса go-live даты (30 честных дней ≈ 2026-07-10).

---

## Ключевые риски сейчас

1. **Трек хрупкий:** один пропущенный день цикла до 2026-07-10 → перенос go-live.
   Gap-monitor пока не настроен (RB-101).
2. **APY-gap структурный:** 3.68% против 7.3% — закрывается только подключением
   Pendle PT / Sky (Phase 2) или официальным снижением цели.
3. **Алерты молчат:** при инциденте (drawdown, отказ фида) никто не узнает —
   доставка не настроена.

---

*Формат: обновляй таблицы, не добавляй разделы. История изменений — git.*
