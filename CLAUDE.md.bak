# SPA — Smart Passive Aggregator

> ⚠️ **ЧИТАЙ ПЕРВЫМ:** [`CURRENT_STATE.md`](CURRENT_STATE.md) — там актуальный статус инфраструктуры (launchd, push-метод, активные блокеры).

## Что это

SPA — автономный DeFi yield optimizer. Paper trading с виртуальным капиталом
**$100,000 USDC**: ежедневный цикл забирает живые APY/TVL из whitelisted-протоколов,
прогоняет через детерминированный RiskPolicy и ребалансирует виртуальный портфель.

**Цель (GRAND_VISION_v1.md):** $1M/год дохода; оценка $100M через управление внешним
AUM (third-party capital) после подтверждённого track record. Финмодель — MASTER_PLAN_v1.md §1.

**Источник истины плана:** `MASTER_PLAN_v1.md` (задачи MP-xxx) → `KANBAN.json`.
Аудит: `REBUILD_PLAN_v1.md`. Состояние системы: `SYSTEM_HEALTH.md`.

---

## Текущее состояние (2026-06-10)

| Поле | Значение |
|---|---|
| Реальный трек | начат **2026-06-10** (всё до этой даты — демо/недействительно после teardown) |
| Капитал | $100,000 USDC (виртуальный) |
| Go-live решение | план 2026-07-15 → **перенос на ~2026-08-01** (ADR-002 go-live transfer rule) |
| 30 честных дней трека | истекают ~2026-07-10 |
| GoLiveChecker | **NOT READY** — `trades_real: false` (реальных трейдов is_demo:false ещё нет) |
| Тесты | `spa_core/tests/` — 121 файл; `tests/` — 11 файлов |

⚠️ Старый CLAUDE.md (заморожен на «Sprint v1.6, День 2/56», 4h GitHub Actions cron)
был неактуален. Реальный runtime — локальный, через launchd (см. ниже).

---

## Архитектура (реальный runtime)

```
launchd com.spa.daily_cycle (ежедневно 08:00)
    └─► python3 -m spa_core.paper_trading.cycle_runner --verbose
          1. adapter orchestrator (read-only) → живой снимок APY/TVL
          2. StrategyAllocator → целевая аллокация (USD по пулам)
          2b. RiskPolicy gate (детерминированный) — нарушение блокирует
              ребаланс → data/risk_policy_blocks.json (ring-buffer 100)
          3. дельта > порога → виртуальный rebalance-трейд → data/trades.json
          4. начисление дневного yield на позиции
          5. data/equity_curve_daily.json (ring-buffer 365 дней)
          6. data/current_positions.json, data/paper_trading_status.json (is_demo: false)
          7. GoLiveChecker → data/golive_status.json

launchd com.spa.autopush — ❌ НЕ УСТАНОВЛЕН (PYTHON_PATH-заглушка)
    └─► Фикс: bash mp009_fix_launchd.command (см. CURRENT_STATE.md)
```

Также установлены: `com.spa.httpserver` (локальный HTTP для дашборда),
`com.spa.cloudflared` (туннель). Логи цикла: `/tmp/spa_cycle.log`, `/tmp/spa_cycle_err.log`.

**Стек:** Python 3, **только stdlib** (никаких внешних зависимостей в runtime-коде).
Все записи на диск — атомарные: `tmp-файл + os.replace`.

---

## Адаптеры (spa_core/adapters/ — read-only домен)

Реестр — `ADAPTER_REGISTRY` в `spa_core/adapters/__init__.py`:

| Протокол | Tier | Адаптер |
|---|---|---|
| Aave V3 | **T1** | `aave_v3.py` |
| Compound V3 (Comet USDC) | **T1** | `compound_v3.py` |
| Morpho Blue | T2 | `morpho_blue.py` |
| Yearn V3 | T2 | `yearn_v3.py` (ERC-4626) |
| Euler V2 | T2 | `euler_v2.py` (ERC-4626) |
| Maple | T2 | `maple.py` |
| Sky/sUSDS | watch list, **0%** | адаптера нет; `spa_core/data_pipeline/sky_monitor.py` ждёт GSM Pause Delay ≥ 48h |

APY/TVL feed: `spa_core/adapters/defillama_feed.py` (DeFiLlama yields API,
кэш TTL 300 c, конфиг через env в `spa_core/adapters/config.py`).

**Домены разделены:** `spa_core/adapters/` — read-only; `spa_core/execution/` —
execution-домен (подписи, live-write адаптеры). `data/adapter_status.json`
принадлежит execution — **не перезаписывать** из read-only кода.

---

## RiskPolicy (spa_core/risk/policy.py — детерминированный, LLM FORBIDDEN)

Версия **v1.0** (2026-05-20). Любое изменение → новый ADR + snapshot в
`spa_core/risk/versions/`. Ключевые лимиты:

| Параметр | Значение |
|---|---|
| TVL floor | **≥ $5M** на пул |
| Per-protocol cap | **40%** T1 / **20%** T2 |
| T2 total cap | **≤ 35%** портфеля |
| APY-границы новой позиции | 1% … 30% |
| Min cash buffer | ≥ 5% |
| Kill switch | drawdown портфеля ≥ 5% → закрыть всё |

`StrategyAllocator` (`spa_core/allocator/allocator.py`) **сам** соблюдает
TVL floor и T2 total cap (MP-011) — гейт в cycle_runner должен approve'ить
циклы штатно. Структурный кэш ~25% при одном доминирующем T1 — норма политики.
Если «не торгует» — смотри `data/risk_policy_blocks.json`.

`approved=False` от RiskPolicy не может быть переопределён никаким агентом.

**LLM_FORBIDDEN_AGENTS = {risk, execution, monitoring}** — в этих компонентах
LLM-вызовы запрещены (prompt injection в капитал — критический вектор атаки).

---

## GoLiveChecker (spa_core/paper_trading/golive_checker.py)

**6 критериев**, все должны пройти; статус пишется в `data/golive_status.json`:

1. `equity_curve_real` — equity curve реальная (не демо)
2. `trades_real` — есть реальные трейды (`is_demo: false`)
3. `status_real` — paper_trading_status реальный
4. `no_demo_data` — нигде нет `is_demo: true`
5. `data_fresh_48h` — данные не старше 48 ч
6. `cycle_runner_exists` — cycle_runner на месте

Правило перехода в production: **ADR-002** (`docs/adr/ADR-002-golive-transfer-rule.md`) —
READY 7+ дней подряд + gap_monitor без пробелов 30 дней + manual review Owner.
`data/gap_monitor.json` следит за непрерывностью трека (`spa_core/paper_trading/gap_monitor.py`).

Активация live: только `spa_core/golive/activate.py` с ручным вводом
`"I CONFIRM LIVE TRADING"`.

---

## Структура репо

| Путь | Назначение |
|---|---|
| `spa_core/adapters/` | Read-only адаптеры протоколов + DeFiLlama feed + реестр |
| `spa_core/allocator/` | `StrategyAllocator` — целевые веса с cap'ами и TVL floor |
| `spa_core/paper_trading/` | `cycle_runner.py` (ядро), `engine.py`, `golive_checker.py`, `gap_monitor.py`, аналитика |
| `spa_core/risk/` | `policy.py` (RiskConfig/RiskPolicy v1.0), `versions/` (snapshots) |
| `spa_core/golive/` | `activate.py`, checklist, readiness reports |
| `spa_core/execution/` | Execution-домен — **НЕ импортировать** из read-only кода |
| `spa_core/tests/` | Unit-тесты (121 файл) |
| `tests/` | Интеграционные тесты (11 файлов) |
| `data/` | Все JSON-state файлы (trades, equity curve, golive_status, gap_monitor, …) |
| `docs/`, `docs/adr/` | ADR-документы, runbooks (в т.ч. `TOKEN_ROTATION_RUNBOOK.md`) |
| `KANBAN.json` | Kanban (источник: MASTER_PLAN_v1.md); `kanban.html` — UI |
| `push_to_github.py` | Пушер файлов в GitHub через API |
| `auto_push.py` | Автопуш данных (launchd, 90 мин) — ❌ демон не установлен; фикс: `bash mp009_fix_launchd.command` |
| `index.html` | Дашборд |

⚠️ **KANBAN.json пишет конкурентный автономный процесс** (часовой цикл).
Перед записью — перечитай файл с диска, пиши атомарно (tmp + os.replace).

---

## Ключевые data/*.json

| Файл | Что |
|---|---|
| `golive_status.json` | 6 критериев GoLiveChecker + ready/blockers |
| `gap_monitor.json` | Непрерывность трека (пробелы = перенос go-live) |
| `trades.json` | Виртуальные трейды (ring-buffer 500), `is_demo: false` |
| `equity_curve_daily.json` | Дневная equity curve (ring-buffer 365) |
| `current_positions.json` | Текущие позиции |
| `paper_trading_status.json` | Сводный статус paper trading |
| `risk_policy_blocks.json` | Блокировки RiskPolicy gate (ring-buffer 100) |
| `adapter_status.json` | Принадлежит execution-домену — не трогать из read-only кода |

---

## Push в GitHub

```bash
python3 push_to_github.py --files <paths> --message "<msg>"
# один файл: --file <path>; проверка без пуша: --dry-run
```

- **Пути передавай АБСОЛЮТНЫМИ** — относительные схлопываются в basename.
- PAT читается в runtime из macOS Keychain: `security find-generic-password -s GITHUB_PAT_SPA -w`.
  Ротация: `bash setup_pat.sh`; runbook: `docs/TOKEN_ROTATION_RUNBOOK.md`.
- Пуш зависимостей: пушь весь dependency closure изменённого модуля.

**SECRETS POLICY (инцидент 2026-06-10 — PAT утёк в 90+ сгенерированных файлов):**
1. НИКОГДА не писать токены/ключи/пароли ни в один файл (включая CLAUDE.md, docs,
   .command, сгенерированные артефакты). Без исключений.
2. ЗАПРЕЩЕНО генерировать `push_*.html`-артефакты с встроенными кредами.
3. Секрет попал в файл → немедленно revoke на github.com/settings/tokens,
   зачистить файлы и историю.

---

## FORBIDDEN (никогда не нарушать)

1. **Не импортировать** `execution/`, `feed_health/`, risk-агентов из read-only / paper-кода.
2. **Только stdlib** Python — без внешних зависимостей в runtime-коде.
3. **Атомарные записи** — всегда `tmp + os.replace`, никогда прямой `open(..., "w")` на state-файлы.
4. **LLM запрещён** в risk / execution / monitoring компонентах.
5. **Не встраивать PAT** в файлы; не создавать `push_*.html`.
6. RiskPolicy `version` остаётся `"v1.0"` весь paper-период; изменение → ADR.
7. Sky/sUSDS — 0% аллокации до подтверждённого on-chain GSM Pause Delay ≥ 48h.

---

## Analytics Modules (Read-Only/Advisory)

Все модули в `spa_core/paper_trading/` с префиксом своего MP-номера.
**Строго read-only** — никогда не модифицируют allocator/risk/execution.
Выходные артефакты сохраняются в `data/`. Pure stdlib, offline, exit 0 всегда.

| Module | MP | Data File | Description |
|--------|----|-----------|-------------|
| `drawdown_analytics.py` | MP-115 | `data/drawdown_analytics.json` | Drawdown episodes (peak→trough→recovery), underwater time |
| `concentration_analytics.py` | MP-116 | `data/concentration_analytics.json` | HHI by protocol/tier, effective positions, DOJ/FTC thresholds |
| `yield_attribution.py` | MP-117 | `data/yield_attribution.json` | Per-protocol yield contribution, yield-HHI, cash drag |
| `risk_contribution.py` | MP-118 | `data/risk_contribution.json` | MCTR/CCTR/PRC decomposition, risk-HHI, diversification ratio |
| `correlation_analyzer.py` | MP-120 | `data/correlation_analytics.json` | Pearson N×N correlation matrix across protocol APY series, clustering (|r|>0.8), advisory verdict |

CLI pattern (одинаков для всех):
```bash
python3 -m spa_core.paper_trading.<module> --check     # вычислить + вывести, без записи (дефолт)
python3 -m spa_core.paper_trading.<module> --run       # + атомарная запись в data/
python3 -m spa_core.paper_trading.<module> --run --data-dir <dir>
```

---

## Команды

```bash
# Все тесты
python3 -m pytest spa_core/tests/ -v
# Плюс интеграционные
python3 -m pytest tests/ spa_core/tests/ -v

# Прогнать дневной цикл вручную
python3 -m spa_core.paper_trading.cycle_runner --verbose

# Go-live статус
python3 -m spa_core.paper_trading.golive_checker

# Sky/sUSDS GSM Pause Delay
python3 -m spa_core.data_pipeline.sky_monitor

# Push
python3 push_to_github.py --files /abs/path/a.py /abs/path/b.json --message "msg"
```

---

*Обновлено: 2026-06-12 (SYS-002 — исправлен статус autopush; добавлена ссылка на CURRENT_STATE.md; MP-120 Analytics Modules).*
