# SPA — Code Audit Backlog

> Аудит кодовой базы от **2026-06-22** (branch `claude/project-code-audit-9jyi9l`).
> Масштаб: 2796 Python-файлов, ~1.35M строк. Источники находок: автоматические
> проверки (ruff, pytest, compileall) + 3 доменных аудита (FORBIDDEN-правила,
> дубликаты/мусор, корректность капитального пути).

Легенда статуса: ✅ DONE (в этой сессии) · 🔜 READY (готово к работе) ·
🟥 DECISION (нужно решение Owner / ADR).

---

## Сводка severity

| # | Severity | Тема | Статус |
|---|---|---|---|
| AUD-01 | ✅ CRITICAL | Kill-switch порог 15% → 5% main / до 15% alt (ADR-023) | DONE |
| AUD-02 | 🟥 CRITICAL | LLM-вызов в `monitoring/auto_fixer.py` (FORBIDDEN rule 4) | DECISION |
| AUD-03 | ✅ HIGH | `sky_susds_feed.py` использовал `requests` (FORBIDDEN rule 2) | DONE |
| AUD-04 | ✅ HIGH | `paper_trading/engine.py` импортирует `execution/` (rule 1) | DONE |
| AUD-05 | 🔜 HIGH | Риск-гейт валидирует позиции по одной, а не портфель целиком | READY |
| AUD-06 | ✅ HIGH | Закоммичены node_modules + venv (~8100 файлов, ~135M) | DONE |
| AUD-07 | ✅ MEDIUM | Закоммичен мусор: .command, *.bak, *.log, отчёты, junk-файлы | DONE |
| AUD-08 | ✅ MEDIUM | Демо-бэкап под `data/` может навсегда заблокировать go-live | DONE |
| AUD-09 | 🟡 MEDIUM | Дубликаты модулей в корне репо (7 орфанов удалено; ~16 — follow-up) | PARTIAL |
| AUD-10 | 🔜 MEDIUM | Гонки read-modify-write на shared ring-buffer JSON | READY |
| AUD-11 | ✅ LOW | `cycle_runner` shadow-day: `today.isoformat()` всегда падал | DONE |
| AUD-12 | 🔜 LOW | Предсуществующие падения `test_sky_susds_adapter.py` | READY |
| AUD-13 | 🟡 LOW | ruff: bare-except + F601 + F541 исправлены; F401/F841 — follow-up | PARTIAL |
| AUD-15 | 🔜 MEDIUM | 58 предсуществующих падений тестов (test-hygiene drift) | READY |
| AUD-14 | 🔜 LOW | Near-duplicate подпакеты (backtest/backtesting, monitor/monitoring, …) | READY |

---

## CRITICAL

### AUD-01 — Kill-switch порог 15% ≠ документированным 5% 🟥 DECISION
`spa_core/governance/kill_switch.py:34` — `DRAWDOWN_THRESHOLD_PCT = 15.0`,
применяется на строке 152 (`if drawdown_pct > DRAWDOWN_THRESHOLD_PCT`). При этом
`RiskConfig.max_drawdown_stop = 0.05` (policy.py:75), CLAUDE.md и GoLiveChecker
(golive_checker.py:663, блок при `drawdown >= 5%`) определяют стоп как **5%**.
Активный в цикле автономный kill-switch (`run_kill_switch_check`,
cycle_runner.py:1255) срабатывает только на 15%. `RiskPolicy.check_portfolio_health`
(5%) **не вызывается** в основном цикле, а проверка новой позиции строит свежий
пустой `PortfolioState` (cycle_runner.py:601) → её drawdown всегда 0.
**Итог:** документированный 5%-стоп фактически не действует; единственный
активный — 15%, со strict `>` (ровно 15.00% не триггерит) и окном лишь 30 баров.

**Почему DECISION:** изменение риск-порога — капитальное решение Owner и требует
ADR (CLAUDE.md: «изменение RiskPolicy → новый ADR»). Нужно явно решить: 5% или 15%,
затем синхронизировать все три точки (kill_switch, policy, golive) на единый
источник `RiskConfig.max_drawdown_stop` и заменить `>` на `>=`.

### AUD-02 — LLM в monitoring-компоненте 🟥 DECISION
`spa_core/monitoring/auto_fixer.py:309-336` — `import anthropic` →
`anthropic.Anthropic(api_key)` → `client.messages.create(...)` + raw-HTTP fallback
на `api.anthropic.com`. Нарушает FORBIDDEN rule 4 («LLM запрещён в monitoring»).
Собственный watchdog (`rules_watchdog.py:382`) **уже whitelist-ит** этот файл —
т.е. это осознанный carve-out. **Решение Owner:** либо вынести `auto_fixer.py` из
`spa_core/monitoring/` (это dev/repair-инструмент, не капитальный мониторинг),
либо оформить исключение через ADR, уточняющий область действия rule 4.

---

## HIGH

### AUD-03 — `sky_susds_feed.py` зависел от `requests` ✅ DONE
Runtime read-only адаптер `spa_core/adapters/sky_susds_feed.py` импортировал
сторонний `requests` (rule 2: только stdlib). В stdlib-only рантайме это latent
crash при первом сетевом вызове. **Фикс:** переписан на `urllib.request` +
ручная gzip-распаковка, зеркалируя канонический `defillama_feed.py`. Тесты
`test_sky_susds_feed.py` обновлены на мок `urlopen` (69/69 pass).

### AUD-04 — `engine.py` импортирует execution-домен 🔜 READY
`spa_core/paper_trading/engine.py:140` — `from execution.engine_bridge import
LiveExecutionBridge` (с fallback на `spa_core.execution...`). Lazy-импорт за
`self.live_execution`, но rule 1 безусловен. **Фикс:** инвертировать зависимость —
инжектить bridge из execution-домена, а не импортировать его внутри paper-кода.

### AUD-05 — Риск-гейт проверяет позиции по одной 🔜 READY
`cycle_runner.py:601-676` — `_apply_risk_policy_gate` валидирует каждый пул через
`check_new_position` и лишь затем добавляет в `state.positions`. Кумулятивные
cap'ы (cash buffer, T2-total, concentration) считаются на неполном портфеле.
Дублирующиеся ключи протокола могли бы пройти cap. Низкая вероятность, но
defense-in-depth слабее, чем кажется. **Фикс:** строить весь предлагаемый портфель,
затем одним вызовом `check_portfolio_health`.

### AUD-06 — Закоммичены node_modules + venv ✅ DONE
`cabinet/node_modules/` (6719 файлов, ~109M, с бинарниками), `.venv_test/`
(1209 файлов). Уже были в `.gitignore`, но закоммичены раньше правил.
**Фикс:** `git rm --cached` (файлы на диске сохранены), `.gitignore` уточнён
(`cabinet/node_modules/`, `.venv_test/`).

---

## MEDIUM

### AUD-07 — Мусорные артефакты в git ✅ DONE
Отвязаны от трекинга (оставлены на диске): 76 `*.command`, 30 `*.bak*`, 21 `*.log`
(вкл. `httpserver.log` ~6.9M), 47 `AUTOPUSH_REPORT_*.md`, scratch-JSON
(`cli_out*`, `m1830`, `m2830`, `out_*` …). Удалены junk-файлы: `[]`, `__probe__`,
`.ts_err`. `.gitignore` дополнен.

### AUD-08 — Демо-бэкап блокирует go-live 🔜 READY
`golive_checker.py:313` (`_check_no_demo_data`) рекурсивно ищет `is_demo:true` под
`data/`, исключая только `golive_status.json` и dotfiles. Цикл архивирует старую
демо-кривую как `data/equity_curve_daily.demo_backup.json` (cycle_runner.py:1193) —
этот файл попадёт в скан и **навсегда** заблокирует критерий `no_demo_data`.
**Фикс:** писать бэкап вне `data/` или добавить `*.demo_backup.json` в исключения.

### AUD-09 — Дубликаты модулей в корне репо 🔜 READY
Орфанные копии в корне (канон — в `spa_core/`), ничто не импортирует bare-модуль:
- byte-identical адаптеры: `euler_v2.py`, `maple.py`, `morpho_blue.py`, `yearn_v3.py`
- 3 разных орфана DeFiLlama: `defi_llama_feed.py`, `defillama_feed.py`, `defillama_fetcher.py`
- ~16 копий: `server.py`, `portfolio_monitor.py`, `kill_switch.py`, `uptime_monitor.py`,
  `signal_aggregator.py`, `atomic.py`, `errors.py`, `version.py` и т.д.

**Сделано (✅):** удалены 7 верифицированных орфанов — byte-identical адаптеры
`euler_v2.py`, `maple.py`, `morpho_blue.py`, `yearn_v3.py` и 3 DeFiLlama-орфана
`defi_llama_feed.py`, `defillama_feed.py`, `defillama_fetcher.py`. Подтверждено:
ни одного bare-импорта, ссылки только в комментариях; spa_core-канон цел, тесты
адаптеров/feed зелёные.

**Follow-up (🔜, осторожно):** ~16 корневых копий (`server.py`, `kill_switch.py`,
`portfolio_monitor.py`, `uptime_monitor.py`, `atomic.py`, `errors.py`, `base.py`
и т.д.) **завязаны** на tracked-plist'ы `scripts/com.spa.*.plist`, deploy-скрипты
и корневые `test_*.py`. Массовое удаление сломает демоны/тесты — требуется
поштучный анализ + репойнт тестов и обновление plist/скриптов. Отложено как
отдельная задача (не «безопасный» автономный шаг).

### AUD-10 — Гонки read-modify-write 🔜 READY
`risk_policy_blocks.json` (cycle_runner.py:709), `analytics_blocks.json` (1490),
`gap_monitor.json` finalize (gap_monitor.py:195) — read→append→write не транзакционны;
конкурентный часовой процесс может терять записи ring-buffer. Отдельные записи
атомарны, но последовательность — нет. **Фикс:** lock вокруг read-modify-write
shared ring-buffer (как `gap_recovery.lock`) либо задокументировать lossy-семантику.

---

## LOW

### AUD-11 — Shadow-day `today.isoformat()` ✅ DONE
`cycle_runner.py:2234` — `today` это `str` (стр. 956), `today.isoformat()` бросал
`AttributeError` каждый цикл, проглатывался fail-safe except → MP-1357 shadow
никогда не исполнялся. **Фикс:** `date_str=today`.

### AUD-12 — Предсуществующие падения `test_sky_susds_adapter.py` 🔜 READY
`TestInit`/`TestValidation` ожидают сообщения `"unsupported chain"`/`"supply ..."`,
но `execution/adapters/sky_susds_adapter.py` бросает `ValidationError` с другим
текстом (`"must be one of ..."`). Не связано с AUD-03. **Фикс:** синхронизировать
ожидаемые сообщения или сами `ValidationError`. Тот же класс дрейфа:
`test_engine_bridge.py::test_skipped_unsupported_protocol` ожидает reason
`unsupported_protocol`, а bridge возвращает `adapter_init_failed` (chain
arbitrum не поддержан) — предсуществующее падение, не регрессия аудита.

### AUD-13 — ruff: 4063 замечания 🟡 PARTIAL
Из 4063: 2548 unused-import (F401), 332 unused-var (F841), 131 f-string-no-placeholder,
2 bare-except (E722), 1 repeated-dict-key (F601).

**Сделано (✅, безопасный приоритет):**
- 2 bare-except (E722) → `except Exception:` (`analytics/apy_tracker.py`,
  `paper_trading/gap_monitor.py`) — больше не глотают KeyboardInterrupt/SystemExit.
- 1 F601: дубль ключа `"risk_score"` в `strategies/s7_pendle_yt_aggressive.py`
  (идентичное значение, лишний ключ удалён).
- 87 F541 (f-string без плейсхолдеров) в `spa_core/` авто-фикс — 100% безопасно.
- Проверка: `compileall` чисто; те же 58 предсуществующих падений на чистом HEAD
  → ноль регрессий от F541.

**Follow-up (🔜, осторожно):** F401 (2548) / F841 (332) — массовый `--fix` на
капитальном коде рискован (import с side-effect/регистрацией). Делать поэтапно
по пакетам с прогоном тестов.

### AUD-15 — 58 предсуществующих падений тестов 🔜 READY
На чистом HEAD (до правок аудита) в наборе analytics/strategies/backtesting/alerts
**58 падений** (из ~5000). Не регрессии аудита. Категории:
- `TestImportHygiene::test_atomic_write_pattern_present` (turnover, yield_decay …)
  ассертят литерал `tempfile.mkstemp`, но модули перешли на `atomic_save`
  (MP-1453) — тесты устарели.
- `test_telegram_alerts` (формат/диспетчеризация), и др.
**Фикс:** обновить устаревшие тест-ассерты под текущий код (или наоборот). Также
сюда же: pre-existing `test_sky_susds_adapter.py`, `test_engine_bridge.py::
test_skipped_unsupported_protocol` (см. AUD-12) и deprecated-pendle collection errors.

### AUD-14 — Near-duplicate подпакеты 🔜 READY
`spa_core/backtest` vs `backtesting`, `analytics` vs `analysis`, `monitor` vs
`monitoring`, `reports` vs `reporting`, `adapters` vs `adapter_sdk`.
`cycle_health_monitor.py` существует в 3 местах. Требует per-pair анализа графа
импортов перед консолидацией — не bulk-delete.

---

## Прочее (наблюдения, не блокеры)

- **Внешние зависимости вне капитального цикла (MEDIUM/контекстно):** `pydantic`
  в `api/server.py` и `family_fund/api/*`; `scipy` в `bee/*`; `yaml` в
  `adapter_sdk/manifest.py`; `anthropic` в `dev_agents/`, `agents/`. Не в рантайм-
  цикле, но `tests/` тянут `fastapi` (не установлен) — часть тест-сьюта не
  собирается (`test_family_fund_api`, `test_tournament_api`).
- **Атомарность записей (rule 3):** проверено — чисто. Все state-write используют
  `tmp + os.replace`.
- **Секреты (rule 5):** проверено — чисто. Хардкоженных PAT/ключей нет.
- **RiskPolicy version (rule 6):** `"v1.0"` — соблюдено.

---

*Аудит выполнен автоматически; правки DONE — на ветке `claude/project-code-audit-9jyi9l`.*
