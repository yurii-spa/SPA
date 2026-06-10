# SPA — REBUILD PLAN v1.0 (Teardown-аудит → стандарт Tier-1 фонда)

> Дата аудита: **2026-06-10**. Метод: полный послойный разбор кода, данных,
> инфраструктуры и документации (5 параллельных аудитов + ручная верификация
> данных). Этот документ — операционный план пересборки. Источник задач —
> `KANBAN.json` (задачи RB-xxx). Стратегический контекст — `ROADMAP_v2.md`,
> `GRAND_VISION_v1.md`, `ARCHITECTURE_v2.md`.

---

## 0. Главный вывод (безжалостно честно)

**Система — это работающий однодневный прототип внутри четырёхмесячной горы
обвязки.** Что реально есть:

- ✅ Живой data-фид (DeFiLlama, 5 адаптеров), качественный аллокатор с cap'ами,
  детерминированная Risk Policy, замкнутый paper-цикл (закрыт **2026-06-10**,
  первая настоящая сделка T001).
- ❌ Реальный track record = **1 день**. Всё, что показывалось до 2026-06-10 —
  демо-сид.
- ❌ Из ~41 analytics-модуля в автоматическом цикле живут **2**. Остальные 39 —
  мёртвый код или ручной запуск по устаревшим данным.
- ❌ Алерты в `dry_run` — реально **ничего не отправляется**.
- ❌ Дашборд мешает архивные демо-цифры (2026-05-22) со свежими данными —
  для инвестора это хуже, чем отсутствие дашборда.
- 🔴 **Утёкший GitHub PAT лежит в plaintext в 76 файлах** + был в KANBAN.json
  (вычищен этим аудитом) + в CLAUDE.md. Не ротирован с цикла v3.68.

Оценка инвесторской готовности: **2/10**. Оценка инженерного фундамента: **6/10**.
Вывод: не строить дальше — сначала вычистить, потом 30 дней доказывать, что
фундамент работает, и только потом масштабировать.

---

## 1. Инвентарь

| Категория | Количество | Комментарий |
|---|---|---|
| Python-файлы | 323 (~150 не-тестовых) | из них реально в продуктовом цикле ~25 |
| Тесты | ~160 файлов | покрытие хорошее, но тестируют и мёртвый код |
| .md документы | 115+ | из них актуальных ~8 |
| data/*.json | 72 | живых (пишутся циклом) ~12, демо/stale ~25 |
| Мусор: push_*.html | **98 файлов** (76 с PAT) | артефакты автономных пушей |
| Мусор: .fuse_hidden | **627 файлов (~20MB)** | spa_core/database/ |
| Мусор: DISPATCH_REPORT и пр. | ~28 .md | одноразовые отчёты в корне |
| launchd-агенты | 4 (2 работают, 2 падают) | daily_cycle ✅, cloudflared ✅, httpserver ❌, autopush ❌ |

---

## 2. Послойный аудит

### Слой 1 — Data feeds ⚠️ Частично
- ✅ `spa_core/adapters/` — 5 живых адаптеров (Aave, Morpho, Yearn, Euler, Maple),
  реальный HTTP к `yields.llama.fi`, честный отказ при ошибке (никаких mock-фолбэков).
- ⚠️ **Compound V3 зарегистрирован, но отсутствует в runtime-статусе** —
  второй T1-якорь не работает (RB-013).
- ⚠️ Pendle PT и Sky/sUSDS — есть только в execution-домене, аллокатор их **не видит**.
  Потолок APY ~4.7% против цели 7.3% — **структурно недостижимо** без них.
- 🗑️ `data_pipeline/` (defillama_fetcher, pendle_fetcher, sky_monitor, price_feeds) —
  orphan-код, не в цикле.
- Покрытие vs конкуренты: 5 протоколов / 1 сеть. Llama-агрегаторы и
  институциональные конкуренты — 20-50+ протоколов, 5-8 сетей.

### Слой 2 — Allocation engine ✅ Работает (с одной дырой)
- ✅ Цепочка замкнута: `cycle_runner → orchestrator → StrategyAllocator →
  risk_adjusted веса → caps (T1≤40%, T2≤20%) → remainder-fill → trades.json`.
- ✅ StrategySelector подключён (активируется с 15-го дня трека shadow-стратегий).
- 🔴 **Дыра:** `RiskPolicy.check()` не вызывается на каждую сделку в cycle_runner —
  caps зашиты в аллокаторе, но политика как блокирующий гейт стоит только в
  legacy-engine и execution-пути. Текущие позиции: **$0 cash при
  `min_cash_pct = 0.05`** — реальная аллокация нарушает действующую политику v1.0
  без ADR (remainder-fill убрал cash-drag в обход min_cash). RB-007.
- ⚠️ `risk_scores.json` устарел (2026-05-27) — аллокатор работает на stale-оценках. RB-014.
- 🗑️ `optimization/` (kelly, markowitz, recommender) — мёртвый код вне цикла.

### Слой 3 — Paper trading ✅ Работает, трек = 1 день
- ✅ `trades.json`: первая реальная запись **T001, 2026-06-10 06:49 UTC**, `is_demo:false`.
- ✅ `equity_curve_daily.json`: реальная, 1 день ($100,000 → $100,010.09, APY 3.68%).
  Демо-кривая корректно заархивирована в `.demo_backup`.
- ✅ `cycle_runner` на launchd ежедневно 08:00, идемпотентный, атомарная запись.
- 🗑️ `paper_trading/engine.py` (1382 строки) — параллельный legacy-путь, питает
  только мёртвый `data/status.json` (заморожен 2026-05-22).
- ❌ «Day 22/30» в статусах — фикция: считается от 2026-05-20, а честный трек
  начался 2026-06-10. **Реальный отсчёт: 30 дней истекают ~2026-07-10.**

### Слой 4 — Analytics ❌ 39/41 мёртвые
- В автоматическом цикле живут: `equity_curve` (cycle_runner) и `agent_stability`
  (export_data). `honest_metrics` используется backtester'ом.
- 19 модулей имеют standalone `main()` и недавно запускались чем-то вручную/почасово,
  но считают **n=0…7 сэмплов** — на 1 дне реального трека всё это шум.
- `risk_metrics.json` пуст (sharpe/win_rate/max_dd = null), а go-live критерии
  C002-C004 читают именно его.
- Вердикт: оставить ~8 модулей в post-cycle хуке, остальные — удалить/архив (RB-104).

### Слой 5 — Strategies / Shadow ⚠️ Частично
- ✅ 6 shadow-стратегий (S0-S5) в реестре, раннер работает, selector в аллокаторе.
- ⚠️ Сравнение посчитано на **синтетике** (30-step backtest), не на реальном треке.
  Sharpe 48.5 на n=1 день — бессмысленные числа с low_sample_warning.
- 🗑️ Мёртвые: `s1_conservative_lending`, `s2_lp_stable`, `s3_yield_loop`,
  `bull_cycle_detector` — старый дизайн, не в реестре.
- Реально торгуется **1 модель** (risk_adjusted), стратегии — тени.

### Слой 6 — Monitoring / Alerts ❌ Dry-run
- ✅ Правила алертов детерминированные, alert_log пишется (сегодняшние записи).
- ❌ Всё с `sent_via: "dry_run"` — **ни одно письмо/сообщение не отправлено**.
  SMTP env-переменные не заданы локально.
- ❌ Текущие алерты — мусор на демо-данных: «Sharpe -5.38» из старого
  synthetic-бэктеста, «C001 20/30 дней» от фиктивной даты старта.
- ⚠️ `red_flags.json` (13 дней), `incidents.json` (14 дней) — stale;
  governance_watcher/red_flag_monitor не в расписании.
- 🗑️ `spa_core/monitor/` — дубликат spa_core/alerts/.

### Слой 7 — Dashboard ❌ Опасен для инвестора
- ✅ Технически работает: 6 вкладок, динамический fetch data/*.json.
- ❌ Читает мёртвые `status.json`/`protocols.json` (2026-05-22, `is_demo:true`) —
  показывает 3-недельную «историю», которой не существует.
- ❌ Day-счётчики — календарная арифметика от hardcoded дат, не от реального трека.
- 🗑️ `spa_dashboard.html`, `SPA_Kanban.html`, `spa_frontend/` (несобранный React) — мусор.
- Вердикт для инвестора: **не показывать до RB-010**.

### Слой 8 — Documentation ⚠️ 8 живых из 115
- ✅ Актуальны (2026-06-10): `ROADMAP_v2.md`, `ARCHITECTURE_v2.md`,
  `ANALYST_REPORT_v1.md`, `GRAND_VISION_v1.md`, этот файл, `SYSTEM_HEALTH.md`.
- ❌ `CLAUDE.md` — заморожен на 2026-05-22 («День 2/56», v1.6, 4h-cron) и
  **содержит plaintext PAT**. Лжёт почти в каждом утверждении статуса. RB-012.
- ⚠️ `DEV_STRATEGY_v1.0.md`, `README.md`, `MEMORY_FACTS.md` — stale.
- 🗑️ В архив: 23× DISPATCH_REPORT, ESCALATION, orchestrator_run_*_HALT,
  peer_chat_review, REVIEW_SUMMARY, STATUS_*, SPA/ (v0.3 docs), CHANGELOG_v0.3/0.4.
- ✅ docs/ADR_001-018 — сохранить как контракты.

### Слой 9 — Infrastructure ⚠️ Наполовину
- ✅ `com.spa.daily_cycle` (08:00, miniconda python) — работает, это сердце системы.
- ✅ `com.spa.cloudflared` — туннель жив.
- ❌ `com.spa.httpserver` (exit 78) и `com.spa.autopush` (exit 2) — падают:
  системный `/usr/bin/python3` не имеет прав на Documents (`Operation not permitted`).
  Лечится путём к miniconda-python (как в daily_cycle) или Full Disk Access. RB-008.
- ⚠️ GitHub Actions (spa-run 4h, spa_alerts 6h) — зависят от push'а репо;
  secrets не заполнены (user action).
- ✅ SQLite работает; Postgres — Phase 1 готов, не развёрнут.
- 🔴 Безопасность: утёкший PAT в 76 html + KANBAN (вычищен) + CLAUDE.md.

---

## 3. Tier-1 Fund Ready Checklist

| Критерий | Статус | Комментарий |
|---|---|---|
| **Track Record** | | |
| 30+ дней реального paper track | ❌ НЕТ | 1 день (старт 2026-06-10) |
| Верифицируемая equity curve без gaps | ⚠️ ЧАСТИЧНО | механизм есть (атомарный, идемпотентный), истории нет |
| Sharpe ≥0.5, Sortino ≥0.7, maxDD <5% | ❌ НЕТ | n=1, ничего не вычислимо |
| On-chain Proof-of-Track | ❌ НЕТ | план в Phase 3 (Merkle root) |
| **Risk Framework** | | |
| RiskPolicy на critical path | ⚠️ ЧАСТИЧНО | caps в аллокаторе да; policy.check как блокирующий гейт в cycle_runner — нет; min_cash нарушен |
| Protocol risk scores актуальные | ❌ НЕТ | stale 2026-05-27 |
| Real-time TVL floor | ⚠️ ЧАСТИЧНО | проверка есть, на stale-данных |
| Kill-switch протестирован | ❌ НЕТ | ни одного drill на реальных данных |
| **Capital Efficiency** | | |
| 0% cash drag | ⚠️ ДА, но в обход политики | конфликт с min_cash 5% — нужен ADR |
| Cross-protocol rebalancing | ✅ ЕСТЬ | порог 1%, T001 это доказал |
| Gas optimization | — Н/П | paper mode |
| **Infrastructure** | | |
| 99.9% uptime | ❌ НЕТ | один Mac, 2 из 4 сервисов падают |
| Incident response playbook | ⚠️ ЧАСТИЧНО | emergency.md v0.3, устарел |
| Disaster recovery | ❌ НЕТ | бэкапов трека нет |
| **Reporting** | | |
| Daily P&L с attribution | ⚠️ ЧАСТИЧНО | investor_report.json есть, доставки нет (dry_run) |
| Monthly investor PDF | ⚠️ ЧАСТИЧНО | pdf_generator есть, не в расписании |
| Real-time dashboard | ❌ НЕТ | демо-смесь |
| **Security** | | |
| Smart contract audit | — Н/П | контрактов ещё нет |
| Key management policy | ❌ НЕТ | **PAT утёк, не ротирован** |
| Access control documented | ❌ НЕТ | — |

**Итог: 1 ✅ / 7 ⚠️ / 10 ❌ из 18 применимых.**

---

## 4. Что выбросить (конкретный список)

### Удалить немедленно (после ротации PAT — RB-001):
```
push_*.html (98 шт), check_pat.html, list_repos.html        # 76 с PAT
push_batch_1..4.json, push_v22_files.json
KANBAN.json.corrupt.bak, spa_core/database/spa.db.bak
spa_core/tests/test_alerts_daily_report.py.bak
spa_core/database/.fuse_hidden* (627 файлов, ~20MB)
"=0.10.0" (артефакт pip), minipytest_tmp.py
_v407_kanban.py, push_kanban_v17.py, cleanup_fuse.py
spa_dashboard.html, SPA_Kanban.html
spa_frontend/ (несобранный React-черновик)
```

### В архив (docs/archive/):
```
DISPATCH_REPORT_*.md (23), ESCALATION_v375.md,
orchestrator_run_*_HALT.md (2), peer_chat_review_v0.4.5.md,
REVIEW_SUMMARY.md, STATUS_2026-06-01.md, CHANGELOG_v0.3.md,
CHANGELOG_v0.4_v0.4.5.md, deep_research_defi_protocols_may2026.md,
SPA/ (вся папка v0.3-доков), ANALYST_REPORT_v1.md (после Phase 0)
```

### Удалить/переписать код (после перевода читателей):
```
spa_core/paper_trading/engine.py        # legacy-путь → выпилить после миграции export_data
spa_core/monitor/                       # дубликат alerts/
spa_core/strategies/{s1_conservative_lending,s2_lp_stable,s3_yield_loop,bull_cycle_detector}.py
spa_core/optimization/                  # или интегрировать (Kelly) — решение в RB-105
~30 analytics-модулей вне выбранного ядра (RB-104)
data/status.json, data/protocols.json, data/strategy_state.json,
data/strategy_v2.json, data/pnl_history.json (demo-часть),
data/backtest_results.json, data/alerts.json, data/bus_stats.json   # demo/orphan
```

---

## 5. Rebuild Roadmap

### Phase 0 — Cleanup (1 неделя, до 2026-06-17) — задачи RB-001…RB-014
Цель: **ничего фальшивого в системе, ноль секретов в файлах, политика на пути капитала.**
1. 🔴 RB-001 Ротация PAT (user action) → только Keychain.
2. RB-002/004/006 Удаление мусора и секретов (списки выше), чистка git-истории.
3. RB-005 Архивация одноразовых отчётов и v0.3-доков.
4. RB-007 **RiskPolicy.check() как блокирующий гейт в cycle_runner** + ADR по min_cash.
5. RB-009 Go-live критерии читают ТОЛЬКО реальные файлы + anti-demo гейт
   (is_demo:true → автоматический FAIL).
6. RB-010/011 Дашборд только на живых данных; затем удалить демо-файлы.
7. RB-008 Починить launchd httpserver/autopush.
8. RB-012 CLAUDE.md переписать по факту.
9. RB-013/014 Compound V3 в runtime + risk_scores в ежедневный цикл.

**Definition of Done Phase 0:** `grep -r "ghp_" → 0`; все читатели go-live/дашборда
на реальных файлах; RiskPolicy блокирует сделку при нарушении; 4/4 launchd живы.

### Phase 1 — Prove It Works (30 дней, до ~2026-07-12) — RB-101…RB-110
Цель: **30 дней непрерывного честного трека + автоматическая отчётность.**
- RB-101 Gap-monitor: пропущенный день цикла = CRITICAL алерт.
- RB-102/103 Алерты из dry_run в бой; ежедневный отчёт (Telegram/email) после цикла.
- RB-104 Ядро аналитики (~8 модулей) в post-cycle хук; остальное удалить.
- RB-105 Выпилить legacy engine.py / monitor/ / мёртвые стратегии.
- RB-106 Shadow S0-S5 на реальном треке; selector активен с 15-го дня.
- RB-107 red_flag/incidents/governance в расписание.
- RB-108 Kill-switch drill (документированный прогон).
- RB-109 SQLite-персистенция трека + ежедневный бэкап (DR-минимум).
- RB-110 Investor view: один честный экран.

**DoD Phase 1:** 30/30 дней без gap; Sharpe/Sortino/maxDD считаются на n≥30;
отчёт приходит сам; дашборд можно показать инвестору без оговорок.

### Phase 2 — Scale Data (2 месяца, до ~2026-09-15) — RB-201…RB-208
Цель: **закрыть APY-gap и снять зависимость от 5 lending-пулов.**
- RB-201/202 Pendle PT + Sky read-only фиды в оркестратор (V409/V410).
- RB-203 Multi-chain: Arbitrum + Base.
- RB-204/205 20+ адаптеров; candidate-tier автодискавери (V417).
- RB-206 Тюнер аллокации с backtest-валидацией (поглощает SPA-V391) → цель APY ≥5.5%.
- RB-207 Postgres-миграция (ADR_005).
- RB-208 Uptime: выделенный сервер 24/7, incident playbook v1, DR-процедура.

**DoD Phase 2:** APY paper ≥5.5% устойчиво; ≥15 живых адаптеров; 60+ дней трека.

### Phase 3 — Institutional Product (3-4 месяца, 2026-Q4…2027-Q1) — RB-301…RB-307
По ROADMAP_v2 Phase 3: live-пилот собственным капиталом через E2E fork-harness
(SPA-V384) → Gnosis Safe → ERC-4626 vault + аудит tier-1 фирмы → on-chain
Proof-of-Track (Merkle root decision-лога) → white-label API → investor portal →
юр. структура. **Гейт входа:** paper go-live пройден по усиленным критериям,
APY ≥5.5%, 60+ дней трека.

### Phase 4 — Distribution (ongoing, 2027+)
Outreach (DAO-казначейства → family offices → fund-of-funds), публичный
tear-sheet ежемесячно, AUM flywheel. Kill-criteria — см. ROADMAP_v2 / GRAND_VISION §5.

---

## 6. Риски графика

1. **Go-live 2026-07-15 формально достижим, но без запаса:** 30 честных дней
   истекают ~2026-07-10. Любой gap в треке = перенос. ADR о правиле переноса —
   принять сейчас, не 14 июля.
2. **APY 3.68% vs цель 7.3%** — на текущем whitelist недостижимо. Либо Phase 2
   фиды (Pendle/Sky), либо официально снизить цель ADR'ом.
3. **Bus factor = 1, инфраструктура = 1 Mac.** До внешних денег — RB-208.

---

*Обновлять этот файл по завершении каждой фазы. Текущее состояние системы —
`SYSTEM_HEALTH.md`. Задачи — `KANBAN.json` (RB-xxx).*
