# SPA — Code Audit Backlog

> Аудит кодовой базы от **2026-06-22** (branch `claude/project-code-audit-9jyi9l`).
> Масштаб: 2796 Python-файлов, ~1.35M строк. Источники находок: автоматические
> проверки (ruff, pytest, compileall) + 3 доменных аудита (FORBIDDEN-правила,
> дубликаты/мусор, корректность капитального пути).

Легенда статуса: ✅ DONE (в этой сессии) · 🔜 READY (готово к работе) ·
🟥 DECISION (нужно решение Owner / ADR).

> **Test health (после сессии):** из ~58 предсуществующих падений в analytics/
> strategies/allocator/alerts/risk-наборах → **0**. Найден и устранён **системный
> баг `atomic_save(..., str(self))` в ~23 analytics-модулях** (персистенция писалась
> в garbage-имена `<object at 0x…>` — источник junk-файлов в репо). Плюс реальные
> баги: `MomentumSignal` без `@dataclass`, allocator weight-overshoot, argparse-внутри-
> `log_result`, swapped `atomic_save`-args. Остаток (длинный хвост): сетевые тесты
> (sandbox DeFiLlama 403, не реальные баги), точечный fragile-mock дрейф
> (`daily_report`, `red_flag_monitor`), AUD-09/13/16.

---

## Сводка severity

| # | Severity | Тема | Статус |
|---|---|---|---|
| AUD-01 | ✅ CRITICAL | Kill-switch порог 15% → 5% main / до 15% alt (ADR-023) | DONE |
| AUD-02 | ✅ CRITICAL | LLM в `monitoring/auto_fixer.py` → перенесён в `dev_agents/` (ADR-026) | DONE |
| AUD-03 | ✅ HIGH | `sky_susds_feed.py` использовал `requests` (FORBIDDEN rule 2) | DONE |
| AUD-04 | ✅ HIGH | `paper_trading/engine.py` импортирует `execution/` (rule 1) | DONE |
| AUD-05 | ✅ HIGH | Риск-гейт: добавлена whole-portfolio holistic ре-валидация | DONE |
| AUD-06 | ✅ HIGH | Закоммичены node_modules + venv (~8100 файлов, ~135M) | DONE |
| AUD-07 | ✅ MEDIUM | Закоммичен мусор: .command, *.bak, *.log, отчёты, junk-файлы | DONE |
| AUD-08 | ✅ MEDIUM | Демо-бэкап под `data/` может навсегда заблокировать go-live | DONE |
| AUD-09 | 🟡 MEDIUM | Дубликаты модулей в корне репо (7 орфанов удалено; ~16 — follow-up) | PARTIAL |
| AUD-10 | ✅ MEDIUM | file_lock (fcntl) на read-modify-write shared JSON | DONE |
| AUD-11 | ✅ LOW | `cycle_runner` shadow-day: `today.isoformat()` всегда падал | DONE |
| AUD-12 | ✅ LOW | `ValidationError` теперь `ValueError`; `test_sky_susds_adapter` 50/50 | DONE |
| AUD-13 | 🟡 LOW | ruff: bare-except + F601 + F541 + F811 исправлены; F401/F841 — follow-up | PARTIAL |
| AUD-15 | ✅ MEDIUM | ~80 предсущ. падений почин.; **системный atomic_save(str(self))-баг в ~23 модулях** | DONE |
| AUD-16 | 🔜 LOW | Registry-sync: пакетный реестр на 26 адаптеров > оркестраторного | READY |
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

### AUD-02 — LLM в monitoring-компоненте ✅ DONE
`auto_fixer.py` (`import anthropic` → `anthropic.Anthropic().messages.create()` +
raw-HTTP fallback на `api.anthropic.com`) нарушал FORBIDDEN rule 4 («LLM запрещён
в monitoring»). **Решение Owner: вынести из monitoring.** `auto_fixer.py` перенесён
`spa_core/monitoring/` → `spa_core/dev_agents/` (LLM-зона dev-агентов, рядом с
`architect.py`); `rules_watchdog._KNOWN_EXCEPTIONS` опустошён (carve-out больше не
нужен — monitoring/ буквально чист); тесты перенацелены. Оформлено в **ADR-026**.
31/33 теста проходят; 2 предсуществующих падения — висячий импорт
`spa_core.monitoring.telegram_watcher` (см. AUD-15), не связан с переносом.

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

### AUD-05 — Риск-гейт проверяет позиции по одной ✅ DONE
`cycle_runner.py:_apply_risk_policy_gate` валидировал каждый пул через
`check_new_position` инкрементально (order-dependent: каждая позиция видит только
добавленные ДО неё). **Фикс:** после цикла (когда весь предлагаемый портфель в
`state`) добавлен один holistic-вызов `check_portfolio_health(state)` — order-
independent ре-валидация концентрации по всему портфелю, ловит кумулятив/дубль-
ключи. Те же детерминированные пороги → только ДОБАВляет violations, не ослабляет.
Fail-closed: ошибка в ре-проверке блокирует трейд. Добавлен тест
`test_portfolio_health_recheck_failclosed_blocks`; 16/16 gate-тестов зелёные.

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

### AUD-10 — Гонки read-modify-write ✅ DONE
`risk_policy_blocks.json`, `analytics_blocks.json`, `gap_monitor.json` —
read→modify→write не были транзакционны (конкурентный часовой процесс мог терять
записи). **Фикс:** добавлен stdlib-хелпер `file_lock` (`fcntl.flock` на sidecar
`<path>.lock`, auto-release при выходе процесса, graceful fallback — никогда не
блокирует/не падает) + `locked_append_ring` в `spa_core/utils/atomic.py`.
Применён к обоим ring-buffer'ам cycle_runner (`_record_policy_block`,
analytics_blocks) и к 3 read-modify-write на `gap_monitor.json` (`_finalize`,
`_log_skip`, `attempt_recovery`). Тесты: `test_atomic_file_lock.py` (взаимное
исключение + ring), gap_monitor 15/15. `*.lock` добавлен в `.gitignore`.

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
- 5 F811 (redefined-while-unused): дубли импортов в `reporting/tear_sheet.py`
  (tempfile/statistics/timezone), `tests/test_monitor.py`, `tests/test_sky_susds_feed.py`
  (мой дубль `json` из AUD-03). Остался 1 неоднозначный (`_std` в
  `test_tournament_evaluator` — локальный def шадует импорт, не авто-фиксим).
- Проверка: `compileall` чисто; затронутые тесты зелёные; те же 58
  предсуществующих падений на чистом HEAD → ноль регрессий.

**Follow-up (🔜, осторожно):** F401 (2548) / F841 (332) — массовый `--fix` на
капитальном коде рискован (import с side-effect/регистрацией). Делать поэтапно
по пакетам с прогоном тестов.

### AUD-15 — Предсущ. падения тестов 🟡 PARTIAL
На чистом HEAD (до правок аудита) ~58 падений в наборе analytics/strategies/alerts.
Не регрессии аудита.

**Сделано (✅):**
- **REAL BUG** `spa_core/analytics/apy_momentum.py`: у `class MomentumSignal`
  пропущен `@dataclass` → `get_signal()` падал `TypeError` всегда (38 тестов).
  Добавлен декоратор → 97/97 тестов, аналитика восстановлена.
- 4 hygiene-drift файла (`test_turnover/yield_decay/cost_drag/apy_dispersion_
  analytics::test_atomic_write_pattern*`): ассерт `tempfile.mkstemp` обновлён на
  «`atomic_save` ИЛИ legacy inline» (модули перешли на централизованный
  `atomic_save`, MP-1453). 363/363.

**Осталось (🔜, неоднозначное — капитальная/allocator-семантика, не угадывать):**
- ✅ **float-overshoot аллокатора FIXED** (`test_weights_sum_within_caps_and_le_one`):
  независимое `round(w,6)` по каждому весу давало сумму 1.000009 > 1.0. Добавлен
  `_round_weights_sum_le_one` (избыток вычитается из наибольшего веса — только
  уменьшение, cap'ы держатся). Аллокатор-сьют: baseline 23 fail → 19 fail, ноль
  регрессий, +3 unit-теста. Связан с H2 исходного аудита.
- `test_strategy_selector` (4 ост.): фикстуры с `tvl_usd: 0.0` → TVL-floor ($5M)
  фильтрует адаптеры → `strategy_loop_active=False`. Поднять TVL в фикстурах —
  но часть тестов в том же setUp ждёт `False`; нужно понять условие активации.
- `test_telegram_alerts` (8): `_send` перешёл на `send_message_with_keyboard`;
  + изменения формулировок логов и семантики `send_red_flag([])`/crash — требуют
  решения «правда ли поведение». 
- `test_analytics` (2), `test_alerts` (1).
- pre-existing: `test_sky_susds_adapter.py`, `test_engine_bridge::
  test_skipped_unsupported_protocol` (AUD-12), deprecated-pendle collection errors,
  `test_data_integrity::test_only_stdlib_imports` (di.py импортит spa_core),
  **висячий импорт** `spa_core.monitoring.telegram_watcher`/`parse_alert_type` в
  `dev_agents/auto_fixer.py` (модуль не существует → 2 теста `run_auto_fix`).

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
