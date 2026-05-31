# SPA Sprint Log — updated 2026-05-31

## Completed ✅

---

## Sprint v3.60 — 2026-05-31 — Visible per-signal updated_at/age row under Feed Health chips (SPA-V360)

### Триггер
- Последний завершённый спринт по KANBAN — v3.59 (`sprint_completed: v3.59`). Заканчивается на «9» → architect review НЕ запускался (только на 0/5). Status pass запрещён → взят следующий разблокированный код-спринт. Разблокированных HIGH код-карточек нет (user_action / governance / tracker / FEAT блокированы SPA-BL-012). Взята dispatch-note **option A** из v3.59. НЕ новый монитор (SPA-BL-011), НЕ money-moving, НЕ user-action-blocked.

### Что сделано
- Цель (dispatch-note option A): вынести уже эмитируемые агрегатором поля `updated_at` / `last_alert_age_hours` из tooltip чипов в ВИДИМЫЙ компактный ряд под `#feed-health-signals` на дашборде.
- **`index.html` — правка применена (точечные Edit оркестратором):**
  - В HTML после `<div id="feed-health-signals">` (строка 1659) добавлен `<div id="feed-health-ages" ...>` (строка 1660, мелкий шрифт `#bbb`, flex-wrap); у `#feed-health-signals` `margin-bottom` уменьшен 14px→6px, отступ перенесён на ages-ряд.
  - В `renderFeedHealth(data)`: добавлен `const ages = document.getElementById('feed-health-ages')`; в no-data ветке `ages.innerHTML = ''`; после рендера чипов добавлен ages-рендер — для каждого сигнала `label` + возраст (`<x.x>h ago` при `Number.isFinite(s.last_alert_age_hours)` через `toFixed(1)`, иначе null-safe откат на короткую форму `updated_at`, иначе `n/a`), tooltip = `label · updated <updated_at|n/a>`.
  - Существующие чипы и их tooltip (v3.59) НЕ изменены. Баланс фигурных скобок `renderFeedHealth` 38/38; единственный `renderFeedHealth`/`loadFeedHealth`, единственные ID — подтверждено grep.
- **Бэкенд `spa_core/alerts/feed_health_summary.py` — НЕ менялся** (read-only агрегатор; поля `label`/`updated_at`/`last_alert_age_hours` уже есть с v3.59).
- Регенерирован `data/feed_health_summary.json`: 9 сигналов, у каждого `label`/`updated_at`/`last_alert_age_hours`.
- Добавлен класс `TestV360FeedHealthContract` (3 теста) в `spa_core/tests/test_feed_health_summary.py` — регрессионная страховка контракта, который потребляет видимый UI-ряд.
- **NO new monitor** — соблюдён governance-фриз **SPA-BL-011** (презентация существующих данных). Money-moving код (`eth_signer.py`, `mev_protection.py`, `*_adapter.py`) НЕ тронут.

### Файлы
- `index.html` (изменён — `#feed-health-ages` div + ages-рендер в `renderFeedHealth`)
- `spa_core/tests/test_feed_health_summary.py` (изменён — +`TestV360FeedHealthContract`, 3 теста)
- `data/feed_health_summary.json` (регенерирован)
- `KANBAN.json`, `SPA_sprint_log.md` (bookkeeping)
- Бэкапы `.bak.v360`: index.html, feed_health_summary.py, test_feed_health_summary.py, KANBAN.json, SPA_sprint_log.md.

### Результаты тестов
- `python3 -m pytest spa_core/tests/test_feed_health_summary.py -q` → **31 passed / 0 failed** (28 прежних + 3 новых `TestV360FeedHealthContract`).
- `python3 -m py_compile spa_core/alerts/feed_health_summary.py` → OK.
- `data/feed_health_summary.json` валиден, `signal_count=9`, overall `ok`. `KANBAN.json` валиден. `renderFeedHealth` braces 38/38, ages-ряд проводка подтверждена. `node --check` к `.html` неприменим — пропущено осознанно.

### Замечание о под-прогоне
- Рабочий sub-агент ошибочно посчитал `index.html` «повреждённым» и НЕ применил фронтенд-правку. Оркестратор перепроверил: файл цел (единственные `renderFeedHealth`/`loadFeedHealth`, сбалансированные скобки), и применил правку напрямую. Также устранён дубль карточки `SPA-V360-001` в `KANBAN.json` (осталась одна).

### Следующий спринт
- **SPA-V361 (разблокированный код-шаг):** консолидированный «Go-Live readiness score» — backend JSON сводит adapter-status + feed-health + covariance-health + go-live checklist в один индикатор + рендер на дашборде. Альтернатива: иной презентационный surface-шаг.
- Напоминание: HIGH go-live путь заблокирован на user-action секретах **SPA-BL-012**; feed-health домен заморожен **SPA-BL-011**.

---

## Sprint v3.59 — 2026-05-31 — Per-signal updated_at history in feed-health summary + dashboard (SPA-V359)

### Что сделано
- **`spa_core/alerts/feed_health_summary.py` — Шаг 1 (backend, never-raise):** в `evaluate_signal` добавлено производное поле `last_alert_age_hours` — возраст (в часах, округл. до 2 знаков) последнего обновления state-файла. В record-словарь добавлена инициализация `"last_alert_age_hours": None` (рядом с `"updated_at": None`). Введён module-level helper `_age_hours(iso_str) -> Optional[float]` (top-level try/except → `None`): парсит ISO-строку, поддерживает суффикс `Z` (`.replace("Z","+00:00")`), naive datetime → UTC, считает `(now_utc - parsed).total_seconds()/3600.0`. ПОСЛЕ строки `record["updated_at"] = data.get("updated_at")` (внутри общего try) helper вызывается в ДОПОЛНИТЕЛЬНОМ внутреннем try/except, чтобы плохой `updated_at` не сбивал остальные поля. Семантика `present`/отсутствующего файла сохранена: missing → healthy, `last_alert_age_hours=None`. Helper использует уже импортированные `datetime`/`timezone`.
- **`index.html` — Шаг 2 (frontend, точечный Edit `renderFeedHealth`):** tooltip каждого чипа обогащён null-safe-полями: `· updated <updated_at|n/a> · cycle <last_alerted_cycle|n/a>` и `· <age>h ago`, когда `Number.isFinite(s.last_alert_age_hours)`. Старые фиды без новых полей не падают (`s.updated_at || 'n/a'`, `s.last_alerted_cycle != null ? … : 'n/a'`). Вид чипа (label + streak-суффикс) и HTML-структура НЕ изменены — только обогащение tooltip.
- **`spa_core/tests/test_feed_health_summary.py` — Шаг 3:** добавлен класс `TestLastAlertAgeHours` (6 тестов): возраст ≈5.0h (±0.2) для свежего `updated_at` с Z; `None` без `updated_at`; `None` на мусорном `updated_at` + остальные поля целы и evaluate_signal не бросает; missing state-файл → ключ присутствует со значением None; ключ присутствует у каждого из 9 сигналов `build_summary_document()`; helper `_age_hours` (naive/Z/None/мусор).
- **`data/feed_health_summary.json` — Шаг 4:** регенерирован `python3 -m spa_core.alerts.feed_health_summary --write`. 9 сигналов, у каждого ключ `last_alert_age_hours` (локально все `None` — degradation state-файлов нет → healthy, overall ok). JSON валиден.
- **NO new monitor** — соблюдён governance-фриз **SPA-BL-011**: это обогащение/презентация уже существующих данных аггрегатора, не новый feed-health монитор. Money-moving код (`eth_signer.py`, `mev_protection.py`, адаптеры) НЕ тронут.

### Файлы
- `spa_core/alerts/feed_health_summary.py` (изменён — Шаг 1: `_age_hours` helper + `last_alert_age_hours`)
- `index.html` (изменён — Шаг 2: tooltip `renderFeedHealth`)
- `spa_core/tests/test_feed_health_summary.py` (изменён — Шаг 3: `TestLastAlertAgeHours`)
- `data/feed_health_summary.json` (регенерирован — Шаг 4)
- Бэкапы `.bak.v359`: feed_health_summary.py, test_feed_health_summary.py, index.html, KANBAN.json, SPA_sprint_log.md.

### Результаты тестов
- `python3 -m py_compile spa_core/alerts/feed_health_summary.py` → OK.
- `python3 -m pytest spa_core/tests/test_feed_health_summary.py -q` → **28 passed / 0 failed** (22 прежних + 6 новых `TestLastAlertAgeHours`). Сетевых/pre-existing фейлов в этом файле нет.
- `data/feed_health_summary.json` валиден (json.load OK), `signal_count=9`, у каждого сигнала есть `last_alert_age_hours`.

### Следующий спринт
- **SPA-V360 (разблокированный код-шаг):** вынести per-signal updated_at history из tooltip в видимый ряд под чипами (потребует правок HTML-структуры `feed-health-signals`), ЛИБО консолидированный Go-Live readiness score.
- Напоминание: HIGH go-live путь заблокирован на user-action секретах **SPA-BL-012**; feed-health домен заморожен governance-блокером **SPA-BL-011** (новые мониторы — только под новый класс отказа).

---

## Sprint v3.57 — 2026-05-31 — Wire T1 aave/compound into adapter_status (SPA-V357)

### Что сделано
- **`spa_core/execution/adapter_status.py` — Шаг 1:** в `_ADAPTER_SPECS` добавлены ДВЕ T1-записи (в начало списка, T1 идут первыми по приоритету tier; порядок детерминирован): `aave-v3` (module `spa_core.execution.aave_v3_adapter`, name `Aave V3`, tier `T1`, write_state `BLOCKED`, apy_source_project `aave`, allocation_note `None`) и `compound-v3` (module `spa_core.execution.compound_v3_adapter`, name `Compound V3`, tier `T1`, write_state `BLOCKED`, apy_source_project `compound`, allocation_note `None`).
- **`allocation_cap = 0.40` для обоих T1 — КАНОНИЧЕСКИЙ источник найден** (не дефолт). Per-protocol T1 concentration cap прописан в коде risk-движка: `spa_core/risk/policy.py` `max_concentration_t1: float = 0.40` (зеркально в `spa_core/risk/versions/v1_0_passive.py:39`). Это программный лимит на один T1-протокол в портфеле. (Документ `04_Whitelist_Policy_v0.3.md` §9.1 даёт per-протокол портфельные лимиты в процентах для конкретного whitelist, а `Risk_Policy_v0.3.md` §4.1 — target/max/hard 15/20/25% generic; но именно `policy.py max_concentration_t1=0.40` — это исполняемая T1-планка, которую и используем.) Задачный дефолт 0.30 НЕ применялся, т.к. канонический источник в коде найден.
- **`spa_core/execution/adapter_status.py` — Шаг 2 (graceful mock_apy для T1):** в `_adapter_record` внутри существующего try-блока добавлен синтез: если module-level `_DRY_RUN_APY` отсутствует/пуст (`if not mock_apy:`), берём class-level `_MOCK_APYS` адаптера (плоский asset→apy) и строим `{chain: dict(_MOCK_APYS) for chain in SUPPORTED_CHAINS}` — тот же chain→asset→apy формат, что у T2. T2-путь не тронут (у них module-level `_DRY_RUN_APY` есть → синтез не срабатывает). Never-raise сохранён: синтез внутри try, любая ошибка → mock_apy остаётся как было ({}).
- Следствие (бесплатно): live-APY enrichment (`SPA_LIVE_APY`) и `mev_routed` теперь работают для T1 автоматически — `mev_routed=True` у обоих, т.к. `inspect.getsource` их модулей содержит `send_protected` (live-broadcast через `_send_raw_tx` → `mev_protection.send_protected`).
- **`index.html` — Шаг 3: правок НЕ требуется (подтверждено чтением).** `renderAdapterStatus()` (строка ~4107) рендерит tier как простую строку `${a.tier}` в фиксированном бейдже (строка ~4160), без хардкода списка tier-ов; `mapAdapterRecord()` вычисляет cap из `rec.allocation_cap`. Новые protocol_key `aave-v3`/`compound-v3` рендерятся корректно, null-safe.
- **`spa_core/tests/test_adapter_status.py` — Шаг 4:** `EXPECTED_PROTOCOL_KEYS` расширен до 7 (T1 первыми), добавлен `T1_PROTOCOL_KEYS`. Счётчики 5→7 (`test_returns_seven_adapters`, `test_adapters_count`, `test_writes_valid_json`, `test_live_apy_never_raises_on_feed_error`). Параметризации `test_others_blocked` и `ROUTED` расширены T1. Добавлены позитивные тесты: T1 tier=="T1", allocation_cap==0.40, mock_apy синтезируется из `_MOCK_APYS` (`test_aave_mock_apy_synthesised_from_class`/`test_compound_...`), mock_apy непустой, T1 присутствуют в документе, `mev_routed is True`, оба в `routed_adapters`. Классы `TestMevProtectionStatus` / `TestMevRoutingApplicability` не сломаны.
- **`data/adapter_status.json` — Шаг 5:** регенерирован через `python3 -m spa_core.execution.adapter_status --write`. 7 адаптеров; у `aave-v3`/`compound-v3`: `tier:"T1"`, `mev_routed:true`, `allocation_cap:0.4`, непустой `mock_apy` (ethereum/arbitrum/base × asset). `mev_protection.routed_adapters` теперь содержит `aave-v3` и `compound-v3`; `unrouted_adapters` — только `pendle-pt`.
- Money-moving код (`eth_signer.py`, `mev_protection.py`, сами адаптеры) НЕ тронут.

### Файлы
- `spa_core/execution/adapter_status.py` (изменён — Шаг 1+2)
- `spa_core/tests/test_adapter_status.py` (изменён — Шаг 4)
- `data/adapter_status.json` (регенерирован — Шаг 5)
- `index.html` (проверен, правок не требовалось)
- Бэкапы `.bak.v357`: adapter_status.py, test_adapter_status.py, KANBAN.json, SPA_sprint_log.md.

### Результаты тестов
- `python3 -m py_compile spa_core/execution/adapter_status.py` → OK.
- `test_adapter_status.py`: целевые классы (Tiers / AllocationCap / WriteState / MockApyMatchesModules / MevRoutingApplicability) — 52 passed; остальные классы (Collect / RequiredFields / BuildStatusDocument / WriteStatusJson / LiveApyEnrichment / MevProtectionStatus / Resilience) — все зелёные. ЕДИНСТВЕННОЕ исключение: `TestLiveApyGate::test_live_apy_enabled_via_env` зависает в sandbox по таймауту — этот тест выставляет `SPA_LIVE_APY=true` и дергает реальный DeFiLlama без сети. ПРОВЕРЕНО: бэкап-baseline (`adapter_status.py.bak.v357` + старый тест) зависает на нём ИДЕНТИЧНО → это pre-existing network-артефакт sandbox, НЕ регрессия v3.57. В среде с сетью / при мокнутом фиде проходит (см. `TestLiveApyEnrichment` — 8 passed с monkeypatch фида).
- `test_mev_protection.py` + `test_mev_wiring.py`: 58 passed.
- Регресс money-moving адаптеров: `test_aave_v3_adapter.py` 13 passed, `test_compound_v3_adapter.py` 17 passed.

### Следующий спринт
- **Разблокированный код-шаг А:** per-adapter MEV-routing построчно в Go-Live adapter-таблице (`index.html renderAdapterStatus`) — показывать значок routed/unrouted прямо в строке каждого адаптера (данные уже есть в `mev_routed` и `mev_protection.routed_adapters`), сейчас отражается только агрегатом в mevBadge.
- **Разблокированный код-шаг Б:** live-APY enrichment-валидация для T1 — sanity-проверка, что синтезированный из `_MOCK_APYS` mock_apy и live-значения по T1 (aave/compound) попадают в разумные bounds (переиспользовать VALUE-RANGE монитор feed-health).
- Напоминание: HIGH go-live путь упирается в user-action секреты **SPA-BL-012** (приватный ключ / wallet env для live-write), а feed-health расширение заморожено блокером **SPA-BL-011**.

---

## Sprint v3.56 — 2026-05-31 — Per-adapter MEV-routing applicability (SPA-V356)

### Что сделано
- **`spa_core/execution/adapter_status.py`:** добавлен module-level helper `_adapter_mev_routed(module) -> bool` (стиль `_mev_protection_status`, пометка `Sprint v3.56 / SPA-V356`, top-level try/except → НИКОГДА не бросает). Источник истины — фактическая проводка: `inspect.getsource(module)` и проверка `any(name in src for name in (...))` по MEV-broadcast-хелперам `send_raw_transaction_auto` / `broadcast_protected_hash` / `send_protected`. Если `getsource` падает (объект без исходника) → `False`.
- `_adapter_record`: ключ `mev_routed` присутствует ВСЕГДА — инициализируется `False` в начале словаря record (до try); на happy-пути после успешного импорта модуля выставляется `record["mev_routed"] = _adapter_mev_routed(module)`; в except-ветке `record.setdefault("mev_routed", False)`.
- `build_status_document()`: adapters собираются ОДИН раз (`collect_adapter_status()` больше не дублируется); вычислены `mev["routed_adapters"]` / `mev["unrouted_adapters"]` и инжектнуты в top-level блок `mev_protection`. Результат: yearn-v3 / euler-v2 / maple / sky-susds → routed; pendle-pt → unrouted (BLOCKED/NotImplemented, 0 ссылок на MEV-хелперы).
- **`index.html`:** в `mevBadge` добавлен null-safe суффикс ` · N/M adapters routed` (через `Array.isArray(m.routed_adapters)` — старые фиды без поля не падают). Применён к обеим веткам (ON/OFF). Точечный Edit, HTML таблицы не тронут.
- **`spa_core/tests/test_adapter_status.py`:** новый класс `TestMevRoutingApplicability` (9 тестов); существующие 6 тестов `TestMevProtectionStatus` не тронуты.
- **`data/adapter_status.json`** перегенерирован — у каждого адаптера `mev_routed`, в `mev_protection` присутствуют `routed_adapters` / `unrouted_adapters`.

### Файлы
- `spa_core/execution/adapter_status.py` (modified — helper + поле mev_routed + routing-summary)
- `index.html` (modified — routedSuffix в mevBadge)
- `spa_core/tests/test_adapter_status.py` (modified — +класс TestMevRoutingApplicability)
- `data/adapter_status.json` (regenerated)
- `KANBAN.json`, `SPA_sprint_log.md` (bookkeeping)
- Бэкапы `.bak.v356` (KANBAN.json, SPA_sprint_log.md)

### Результаты тестов
- `pytest test_adapter_status.py + test_mev_protection.py + test_mev_wiring.py` — **139 PASS / 0 FAIL** (включая новый класс `TestMevRoutingApplicability`).
- `py_compile adapter_status.py` — OK. `data/adapter_status.json` валиден; `mev_protection.routed_adapters = [yearn-v3, euler-v2, maple, sky-susds]`, `unrouted_adapters = [pendle-pt]`. `KANBAN.json` валиден.

### Следующий спринт
- **SPA-V357:** разумные разблокированные код-шаги — (а) показать per-adapter MEV-routing в Go-Live таблице построчно (колонка / бейдж на строку адаптера); ЛИБО (б) проброс T1-адаптеров aave/compound в `adapter_status` (`_ADAPTER_SPECS`), которые маршрутятся через `_send_raw_tx`, но сейчас отсутствуют в дашборде. HIGH go-live путь по-прежнему упирается в user-action секреты (SPA-BL-012); feed-health домен заморожен (SPA-BL-011).

---

## Sprint v3.55 — 2026-05-31 — Surface MEV-protection status in adapter_status.json + dashboard (SPA-V355)

### Цель
Отрендерить статус MEV-защиты (Flashbots Protect RPC) в дашборде — прямо указанная в dispatch-ноте v3.54 следующая разблокированная код-работа. MEV-защита была подключена в live-send пути всех 6 адаптеров в v3.52, но её состояние (вкл/выкл, endpoint, режим) НИГДЕ не отображалось. Малый, self-contained, never-raise, stdlib-only спринт; зеркалит паттерн v3.35 live-APY enrichment (top-level поле документа + чтение/рендер в index.html). Money-moving код (eth_signer / mev_protection / адаптеры) НЕ тронут.

### Что сделано (SPA-V355-001)
- **`spa_core/execution/adapter_status.py`:** добавлен helper `_mev_protection_status()` (стиль `_live_apy_enabled` — top-level try/except, НИКОГДА не бросает, безопасный default `{enabled:False, endpoint:None, flashbots_mode:"fast", fallback_endpoints:[]}`). Читает `mev_protection.is_mev_protection_enabled()`, `get_protected_rpc()`, env `SPA_FLASHBOTS_MODE`, константу `_PROTECTED_ENDPOINTS`. `build_status_document()` теперь эмитит top-level блок `"mev_protection"` между `live_apy_enabled` и `adapters` (порядок остальных ключей не изменён — подтверждено).
- **`index.html`:** новая модульная переменная `ADAPTER_STATUS_MEV` (рядом с `ADAPTER_STATUS_GENERATED_AT`); `loadAdapterStatus()` пишет `doc.mev_protection || null` в успешной ветке и сбрасывает в `null` на ошибке/старом фиде; `renderAdapterStatus()` строит `mevBadge` (IIFE) — зелёный `#16a34a` `MEV Protection: ON · endpoint (mode)` при `enabled`, amber `#f59e0b` `MEV Protection: OFF (public mempool) · would use … when enabled` при `enabled===false`, пустая строка при `null` (обратная совместимость со старыми фидами). Вставлен после `</table>`, перед `syncedNote`. Стиль inline-span повторяет существующие бейджи. HTML таблицы не тронут.
- **`spa_core/tests/test_adapter_status.py`:** добавлен класс `TestMevProtectionStatus` (6 тестов, env через `mock.patch.dict(os.environ, …)` как в `test_execution_mode_default`): `test_mev_block_present`, `test_mev_disabled_by_default`, `test_mev_enabled_when_env_set`, `test_mev_mode_fast_default`, `test_mev_mode_standard`, `test_document_still_json_serialisable`.
- **`data/adapter_status.json`** перегенерирован — блок `mev_protection` присутствует в корректной позиции (`enabled:false`, `endpoint:https://rpc.flashbots.net/fast`, `flashbots_mode:fast`, 3 fallback-эндпоинта).

### Файлы
- `spa_core/execution/adapter_status.py` (modified — helper + поле в build_status_document)
- `index.html` (modified — ADAPTER_STATUS_MEV + mevBadge)
- `spa_core/tests/test_adapter_status.py` (modified — +6 тестов)
- `data/adapter_status.json` (regenerated)
- `KANBAN.json`, `SPA_sprint_log.md` (bookkeeping)
- Бэкапы `.bak.v355` (adapter_status.py, test_adapter_status.py, index.html, KANBAN.json, SPA_sprint_log.md)

### Результаты тестов
- `pytest test_adapter_status.py + test_mev_protection.py + test_mev_wiring.py` — **127 PASS / 0 FAIL** (включая 6 новых `TestMevProtectionStatus`).
- Независимая перепроверка оркестратором: те же 127 PASS. `py_compile adapter_status.py` — OK. `data/adapter_status.json` валиден, порядок ключей `['generated_at','schema_version','execution_mode','live_apy_enabled','mev_protection','adapters']`. `KANBAN.json` валиден.

### Следующий спринт
- **SPA-V356:** разумные разблокированные код-шаги — (а) показать per-adapter применимость MEV-routing (какие адаптеры реально маршрутятся через `send_protected`) в том же блоке `mev_protection`; ЛИБО (б) отрендерить per-signal `updated_at`-историю в Feed Health-панели (продолжение v3.47/v3.49). HIGH go-live путь по-прежнему упирается в user-action секреты (SPA-BL-012); feed-health домен заморожен (SPA-BL-011).

---

## Sprint v3.54 — 2026-05-31 — Fix latent lstrip(0x) on private-key path (SPA-V354)

### Цель
Устранить оставшийся однотипный латентный баг среза 0x-префикса на private-key пути в `spa_core/execution/eth_signer.py`, явно указанный в dispatch-ноте v3.53 как следующий разблокированный код-спринт. Тот же класс дефекта, что V353, но на критичном signing-пути. Малый, self-contained, без user-action блокировки.

### Проблема
`private_key_hex.lstrip("0x")` (под guard `.startswith("0x")`) срезает **любые** ведущие символы из множества `{'0','x'}`, а не префикс `"0x"`. Для приватного ключа вида `0x00ab…` ведущие нули после префикса срезаются → ключ укорачивается (`len != 64` → `ValueError`, либо при иных входных данных — неверный ключ / несовпадение адреса / повреждённая подпись). Три идентичных вхождения:
- строка 105 — `get_address_from_private_key`
- строка 143 — `sign_transaction`
- строка 201 — `sign_message`

### Что сделано (SPA-V354-001)
- **`spa_core/execution/eth_signer.py`** (строки 105/143/201): каждое
  `pk_hex = private_key_hex.lstrip("0x") if private_key_hex.startswith("0x") else private_key_hex`
  заменено на
  `pk_hex = private_key_hex[2:] if private_key_hex[:2].lower() == "0x" else private_key_hex`.
  Срезается **ровно** префикс `0x`/`0X`; ведущие нули тела ключа сохраняются. `encode_function_call` (починен в V353) не тронут; money-moving логика не изменена кроме самих strip-строк.
- **`spa_core/tests/test_eth_signer.py`**: добавлен `TestGetAddress.test_private_key_prefix_strip_preserves_leading_zero` — pk `0x` + `00` + `ab`*31 (64 hex после префикса) даёт тот же checksummed-адрес, что и bare-форма `00ab…`; ведущий ноль не теряется.

### Файлы
- `spa_core/execution/eth_signer.py`
- `spa_core/tests/test_eth_signer.py`
- Бэкапы: `eth_signer.py.bak.v354`, `test_eth_signer.py.bak.v354`, `KANBAN.json.bak.v354`, `SPA_sprint_log.md.bak.v354`

### Результаты тестов
- `python3 -m pytest spa_core/tests/test_eth_signer.py -q` → **25 passed**, 0 failed (24 прежних + 1 новый регрессионный тест).
- `python3 -m pytest test_eth_signer.py test_mev_wiring.py test_aave_v3_adapter.py test_compound_v3_adapter.py -q` → **59 passed**, 0 failed.
- `python3 -m py_compile spa_core/execution/eth_signer.py` → OK.

### Следующий спринт
Разумный разблокированный код-шаг: добавить MEV-protection статус (вкл/выкл + endpoint) в `data/adapter_status.json` + чтение/рендер в `index.html` (`loadAdapterStatus`/`renderAdapterStatus`) — зеркалит паттерн v3.35 adapter live-APY enrichment. HIGH go-live backlog по-прежнему user_action-blocked (SPA-BL-012); feed-health заморожен (SPA-BL-011).

---


## Sprint v3.53 — 2026-05-30 — Fix baseline failure: eth_signer.encode_function_call 0x-prefix selector strip (SPA-V353)

**Цель:** Закрыть два пред-существующих baseline-фейла в execution-домене, отмеченных в dispatch-ноте v3.52 как единственный незакрытый baseline в этом домене: `test_eth_signer.py::TestEncodeFunctionCall::test_approve_selector` и `::test_unsupported_type_raises`. Малый, self-contained, без user-action блокировки — следующий разблокированный код-спринт после того как весь HIGH go-live backlog упёрся в user-action секреты (SPA-BL-012), а feed-health домен заморожен (SPA-BL-011).

### Проблема
`encode_function_call(selector_hex, *args)` в `spa_core/execution/eth_signer.py` парсил селектор через `bytes.fromhex(selector_hex.lstrip("0x"))`. `str.lstrip("0x")` срезает **любые** ведущие символы из множества `{'0','x'}`, а не префикс `"0x"`:
- `"095ea7b3"` (ERC-20 approve selector) → `"95ea7b3"` (7 hex-символов, нечётная длина) → `bytes.fromhex` бросает `ValueError` **до** проверки типов аргументов.
- `"0x00112233"` → `"112233"` (срезаны и `0x`, и ведущий `0`).

Это ломало `test_approve_selector` (вызывает `encode_function_call("095ea7b3", spender, amount)`, ждёт `calldata[:4].hex()=="095ea7b3"`) и `test_unsupported_type_raises` (ждёт `TypeError`, но получал ранний `ValueError`). Оба таскались «вне scope» много спринтов.

### Что сделано (SPA-V353-001)
- **`spa_core/execution/eth_signer.py`** (строка 234): `selector_hex.lstrip("0x")` → корректный strip ровно префикса `0x`/`0X`:
  ```python
  _sel_hex = selector_hex[2:] if selector_hex[:2].lower() == "0x" else selector_hex
  sel = bytes.fromhex(_sel_hex)
  ```
  Больше ничего в функции не менялось. `test_bad_selector_raises` (`"0xdeadbeef00"` → 5 байт → `ValueError "4 bytes"`) продолжает проходить.
- **`spa_core/tests/test_eth_signer.py`**: добавлен регрессионный тест `test_selector_prefix_strip_preserves_leading_zero` (идентичность результата с/без префикса `0x`, сохранность ведущего нуля `095ea7b3` и `00112233`).

### Файлы
- `spa_core/execution/eth_signer.py` (modified)
- `spa_core/tests/test_eth_signer.py` (modified — +1 регрессионный тест)
- `KANBAN.json`, `SPA_sprint_log.md` (bookkeeping)
- Бэкапы `.bak.v353` (eth_signer.py, test_eth_signer.py, KANBAN.json, SPA_sprint_log.md).

### Результаты тестов
- `test_eth_signer.py` — **26 PASS / 0 FAIL** (ранее падали `test_approve_selector` + `test_unsupported_type_raises` — теперь PASS; новый тест PASS).
- Регрессия execution (`test_eth_signer` + `test_mev_wiring` + `test_aave_v3_adapter` + `test_compound_v3_adapter`) — **86 PASS / 0 FAIL**.
- Независимая перепроверка оркестратором: `test_eth_signer.py` = 26 PASS. `py_compile` eth_signer.py — OK. KANBAN.json валиден.

### Следующий спринт
- **SPA-V354:** латентный однотипный баг — `eth_signer.py` строки 105/143/201 используют `private_key_hex.lstrip("0x")` (под guard `.startswith("0x")`): для приватного ключа вида `0x00ab…` ведущие нули после префикса будут СРЕЗАНЫ → неверный ключ. Тот же класс дефекта, что закрыт в V353, но на pk-пути. Малый self-contained фикс (заменить на `[2:]`-strip). Альтернатива — отрендерить MEV-protection-статус (вкл/выкл, endpoint) в `adapter_status.json` + дашборд (зеркалит v3.35 live-APY enrichment). NB: HIGH go-live путь по-прежнему упирается в user-action секреты (SPA-BL-012); feed-health домен заморожен (SPA-BL-011).

---

## Sprint v3.52 — 2026-05-30 — Wire MEV protection into adapter live-send paths (SPA-V352 / SPA-BL-010)

**Цель:** Закрыть классический built-but-not-wired gap. `spa_core/execution/mev_protection.py` (v3.26) полностью реализовал Flashbots Protect RPC — `send_protected`, `send_raw_transaction_auto`, fallback-цепочку `[flashbots/fast, flashbots/standard, mevblocker/noreverts]`, `wait_for_receipt` — а его docstring прямо называл `send_raw_transaction_auto` «the drop-in replacement for `eth_signer.send_raw_transaction` in all adapters' live execution paths». **Но ни один адаптер его не вызывал.** Все 6 broadcast-адаптеров слали транзакции напрямую через `eth_signer.send_raw_transaction`, т.е. MEV-защита (приватный mempool, защита от sandwich/frontrun) была мёртвым кодом в реальном пути исполнения. Это реализация HIGH-карточки `SPA-BL-010`, которую архитектор v3.51 назвал единственным разблокированным код-спринтом.

**Дополнительный латентный баг:** T2-адаптеры (yearn/maple/sky/euler) делали `receipt = send_raw_transaction(signed.hex(), rpc)` и затем `receipt.get("status") == "0x0"` — но `eth_signer.send_raw_transaction` возвращает **строку** (tx hash), а не dict → `.get` на строке = `AttributeError` в live-режиме (ловился `except` → возвращал FAILED). Адаптеры были написаны под dict-контракт `send_raw_transaction_auto`, но подключены к str-возвращающей функции. SPA-V352 чинит и это.

### Что сделано (SPA-V352-001)
- **`spa_core/execution/mev_protection.py`:**
  - `send_raw_transaction_auto` — public-ветка нормализована: сырой tx-hash (строка от `eth_signer.send_raw_transaction`) оборачивается в консистентный receipt-like dict `{status:"PENDING", tx_hash, endpoint, protection:"none", block_number:None}`; dict-результат (мок/будущее) проходит насквозь. Теперь функция возвращает **один и тот же dict-контракт** независимо от маршрутизации (Flashbots или public).
  - Добавлен `broadcast_protected_hash(signed_tx_hex, timeout=30) -> str` — тонкий helper для hash-потребителей (Aave/Compound `_send_raw_tx`): маршрутит через `send_protected` БЕЗ публичного fallback (caller сам решает), возвращает tx hash, `RuntimeError` при отказе всех protected-эндпоинтов.
  - docstring обновлён (v3.52-нота).
- **T2-адаптеры (`adapters/yearn_v3`, `maple`, `sky_susds`, `euler_v2`), по 2 call-site каждый = 8 сайтов:** local-import переключён с `eth_signer.send_raw_transaction` на `from spa_core.execution.mev_protection import send_raw_transaction_auto`; `receipt = send_raw_transaction_auto(signed.hex(), rpc)`; проверка падения расширена `receipt.get("status") in ("0x0", "FAILED")` (ловит и revert-receipt, и FAILED-broadcast от Flashbots).
- **T1-адаптеры (`aave_v3`, `compound_v3`) — единый chokepoint `_send_raw_tx`:** при `mev_protection.is_mev_protection_enabled()` **И** `SPA_EXECUTION_MODE == "live"` сначала пробует `mev_protection.send_protected(signed_hex, fallback_rpc=None)` и возвращает его `tx_hash`; при FAILED/исключении — `log.warning` и graceful fallback на существующий публичный `self._rpc_first("eth_sendRawTransaction", …)`. Весь MEV-блок в `try/except` (никогда не блокирует публичный путь). Сохраняет str-hash-контракт + последующий receipt-polling нетронутыми.
- **Гейтинг:** при `SPA_MEV_PROTECTION != true` ИЛИ `mode != live` поведение **байт-в-байт прежнее** — публичный путь. dry_run-короткозамыкание адаптеров (mock-ветка до live-исполнения) не тронуто.

### Файлы
Новые:
- `spa_core/tests/test_mev_wiring.py` (source-guards на все 6 адаптеров + нормализация dict-контракта `send_raw_transaction_auto` + `broadcast_protected_hash` + behavioural T1 `_send_raw_tx` routing: off/on-live/fallback/not-live)

Обновлены:
- `spa_core/execution/mev_protection.py` (нормализация `send_raw_transaction_auto` + `broadcast_protected_hash` + docstring)
- `spa_core/execution/adapters/yearn_v3_adapter.py`, `maple_adapter.py`, `sky_susds_adapter.py`, `euler_v2_adapter.py` (broadcast → `send_raw_transaction_auto`, FAILED-check)
- `spa_core/execution/aave_v3_adapter.py`, `compound_v3_adapter.py` (`_send_raw_tx` MEV-routed + public fallback)

### Результаты тестов
- `test_mev_wiring.py` + `test_mev_protection.py` — **58 PASS / 0 FAIL** (offline, mock Flashbots).
- Регрессия адаптеров (`test_yearn_v3_adapter` + `test_maple_adapter` + `test_euler_v2_adapter` + `test_sky_susds_adapter` + `test_aave_v3_adapter` + `test_compound_v3_adapter` + `test_adapter_status` + `test_eth_signer`) — **254 PASS / 2 FAIL**. Оба фейла — пред-существующие baseline: `test_eth_signer.py::TestEncodeFunctionCall::test_approve_selector` и `::test_unsupported_type_raises` (баг `selector_hex.lstrip("0x")` в `encode_function_call`, который для селектора с ведущим `0`/`x` срезает лишние символы; код `encode_function_call` НЕ менялся этим спринтом → вне scope).
- `py_compile` всех 7 изменённых файлов — OK. `KANBAN.json` валиден (`json.load`). Бэкапы `KANBAN.json.bak.v352` / `SPA_sprint_log.md.bak.v352` созданы. Done-карта `SPA-V352-001` добавлена первой в `columns.done`; `SPA-BL-010` помечен done.

### Следующий спринт
**SPA-V353:** опционально починить пред-существующий baseline-фейл `eth_signer.encode_function_call` (`selector_hex.lstrip("0x")` → корректный strip префикса `0x`, напр. `selector_hex[2:] if selector_hex.startswith("0x") else selector_hex`) — единственный незакрытый baseline-фейл в execution-домене, малый и self-contained. Альтернатива — отрендерить MEV-protection-статус (вкл/выкл, endpoint) в `adapter_status.json` + дашборд (зеркалит v3.35 live-APY enrichment), ЛИБО реальный end-to-end прогон pg-миграции против тестового PostgreSQL. NB: следующий разблокированный go-live путь по-прежнему упирается в user-action секреты (SPA-BL-012).

---

## Sprint v3.48 — 2026-05-30 — Fix baseline parse failure: morpho-blue prefix (SPA-V348)

**Цель:** Закрыть давний baseline-фейл `spa_core/tests/test_engine_bridge.py::TestParseProtocolKey::test_malformed_returns_none[morpho-blue-usdc-base]`, таскавшийся «вне scope» ~20 спринтов. `_parse_protocol_key("morpho-blue-usdc-base")` возвращал семантически неверное `{family:'morpho', asset:'BLUE-USDC', chain:'base'}` (`'blue'` съедался в asset), а тест ждал `None` с пометкой «# unknown family». Но `morpho-blue` НЕ unknown: `yield_classifier_agent.py` и `audit_reader_agent.py` УЖЕ маппят `morpho-blue` → family `morpho`; `engine_bridge` был единственным несогласованным местом. Правильное поведение: `morpho-blue-usdc-base` → `{family:'morpho', asset:'USDC', chain:'base'}`. Прецедент — SPA-V328 (когда `pendle-pt` стал поддерживаемым префиксом и obsolete-кейс убрали из malformed-списка).

### Что сделано (SPA-V348-001)
- **`spa_core/execution/engine_bridge.py`:**
  - В словарь `_PROTOCOL_PREFIX_TO_FAMILY` добавлена запись `"morpho-blue": "morpho"` ПЕРЕД `"morpho": "morpho"` (комментарий `# T1 Morpho Blue — Sprint v3.48 / SPA-V348-001 (longest-prefix)`).
  - Цикл подбора префикса в `_parse_protocol_key` переведён с insertion-order на **longest-prefix-match**: `for prefix in sorted(_PROTOCOL_PREFIX_TO_FAMILY, key=len, reverse=True)`, чтобы многословный префикс `morpho-blue` выигрывал у короткого `morpho`. Условие точного совпадения формы `<prefix>-` оставлено как было.
- **`spa_core/tests/test_engine_bridge.py`:**
  - `"morpho-blue-usdc-base"` убран из parametrize-списка `test_malformed_returns_none` (теперь это валидный ключ).
  - После `test_pendle_pt_key_parses` добавлены два позитивных теста: `test_morpho_blue_key_parses` (morpho-blue-usdc-base → {morpho, USDC, base}) и `test_morpho_plain_key_still_parses` (regression: plain `morpho-usdc-ethereum` по-прежнему парсится).

### Файлы
Обновлены:
- `spa_core/execution/engine_bridge.py` (+префикс `morpho-blue`, longest-prefix-match в `_parse_protocol_key`)
- `spa_core/tests/test_engine_bridge.py` (`morpho-blue-usdc-base` из malformed → позитивные `test_morpho_blue_key_parses` + `test_morpho_plain_key_still_parses`)

### Результаты тестов
- `test_engine_bridge.py` — **38 PASS / 0 FAIL** (включая ранее падавший `morpho-blue-usdc-base` кейс, теперь позитивный).
- Регрессия `test_engine_bridge.py` + `test_morpho_adapter.py` + `test_pendle_pt_adapter.py` — **128 PASS / 0 FAIL** (прогон из корня репо).
- `py_compile` `engine_bridge.py` — OK. `KANBAN.json` валиден (`json.load`).
- Бэкапы `KANBAN.json.bak.v348` / `SPA_sprint_log.md.bak.v348` созданы. Done-карта `SPA-V348-001` добавлена первой в `columns.done`.

### Следующий спринт
**SPA-V349:** отрендерить per-signal `updated_at` / историю в Feed Health-панели дашборда (продолжение v3.47), ЛИБО реальный end-to-end прогон pg-миграции против тестового PostgreSQL-инстанса.

---

## Sprint v3.47 — 2026-05-30 — Aggregated feed-health summary (SPA-V347)

**Цель:** Свести семь независимых feed/covariance health-сигналов, накопленных цепочкой v3.39→v3.46, в ОДИН сводный индикатор. Каждый монитор в `risk_monitor.py` пишет свой state-файл со streak-счётчиком, но оператору приходилось мысленно объединять шесть отдельных алертов. Это ровно та консолидация, которую рекомендовал dispatch-отчёт v5 («ценнее седьмого монитора — свести шесть `alert_apy_feed_*` в один»). Спринт сознательно НЕ трогает money-moving код (eth_signer / подпись транзакций / live supply-withdraw).

### Что сделано (SPA-V347-001)
- **`spa_core/alerts/feed_health_summary.py`** (новый, stdlib-only, без сети, never-raise; паттерн как `execution/adapter_status.py` / `analytics/covariance_export.py`):
  - Реестр `SIGNALS` из 7 кортежей `(key, state_filename, label, streak_field, threshold)`. Пороги зеркалят `should_alert = n >= …` в risk_monitor.py **дословно**: covariance=3 (`consecutive_degraded`), apy_feed_stale=2 (`consecutive_stale`), protocol_drop/tvl_drop=1 (`consecutive_drops`), protocol_anomaly=1 (`consecutive_anomalies`), schema_drift=1 (`consecutive_drifts`), protocol_stale=1 (`consecutive_stale`).
  - `classify_streak(streak, threshold)` → `ok` (streak≤0) / `warn` (0<streak<threshold) / `degraded` (streak≥threshold) / `unknown` (битый ввод).
  - `evaluate_signal(...)`: graceful чтение state-файла. Отсутствует → `ok` (монитор трактует свежий/отсутствующий state как нулевой streak). Присутствует, но нечитаем/не-dict → `unknown` (freshness неверифицируема — показываем, а не молчим).
  - `collect_feed_health` / `build_summary_document` → `{schema_version:1, generated_at(ISO Z), overall_status(worst-of), signal_count, counts{ok,warn,degraded,unknown}, signals[]}`. Severity-ранг: `degraded`>`warn`>`unknown`>`ok`.
  - `write_feed_health_summary(out_path=None, *, data_dir=None)` пишет `data/feed_health_summary.json`. CLI `--data-dir/--json/--write`.
- **`spa_core/export_data.py`:** новый try/except-блок «Aggregated feed-health summary (SPA-V347)» сразу ПОСЛЕ блока per-protocol staleness alert и перед decision-log: `write_feed_health_summary(str(OUTPUT_DIR/"feed_health_summary.json"), data_dir=OUTPUT_DIR)` в `try/except→log.error`. Существующие alert-блоки НЕ тронуты.
- **`index.html`** (карточка `cov-card`, точечные Edit):
  - HTML-блок «Feed Health» бейдж (`#feed-health-badge`) + `#feed-health-detail` + чипы `#feed-health-signals`, вставлен после заголовка «AI Recommendations», перед covariance-матрицей.
  - `loadFeedHealth()` (`fetch(BASE+'/feed_health_summary.json')` с `.catch`) + `renderFeedHealth(data)`: бейдж цветом overall (green=ok / amber=warn / red=degraded / grey=unknown), строка-сводка counts + generated, по чипу на сигнал с `(streak/threshold)` и tooltip.
  - Вызов `loadFeedHealth()` добавлен рядом с `loadCovariance()` в Analytics-блоке.
- **`data/feed_health_summary.json`** сгенерирован (offline → все 7 сигналов `ok`, overall `ok`).

### Файлы
Новые:
- `spa_core/alerts/feed_health_summary.py`
- `spa_core/tests/test_feed_health_summary.py` (22 теста)
- `data/feed_health_summary.json` (артефакт)

Обновлены:
- `spa_core/export_data.py` (блок aggregated feed-health summary)
- `index.html` (Feed Health бейдж + loadFeedHealth/renderFeedHealth + вызов)

### Результаты тестов
- `test_feed_health_summary.py` — **22 PASS / 0 FAIL** (classify_streak, реестр/пороги, missing→ok, degraded→overall, warn→overall, worst-of, corrupt→unknown, non-dict→unknown, per-streak-field, write+JSON round-trip, CLI, never-raise).
- Регрессия `apy_feed/covariance/alert` — **96 PASS / 0 FAIL** (прогон из `spa_core/`).
- `node --check` извлечённого инлайн-JS `index.html` — OK. `py_compile` `export_data.py` + `feed_health_summary.py` — OK. `feed_health_summary.json` + `KANBAN.json` валидны (`json.load`).
- Бэкапы `KANBAN.json.bak.v347` / `SPA_sprint_log.md.bak.v347` созданы. Done-карта `SPA-V347-001` добавлена (done 140→141).

### Следующий спринт
**SPA-V348:** отрендерить per-signal `updated_at` / историю в Feed Health-панели, ЛИБО (более ценное) — закрыть user-action HIGH-карточки go-live (Secrets / Telegram / Gnosis Safe / Pages) или 2 пред-существующих baseline-фейла (`test_engine_bridge` morpho-blue-usdc-base; `test_defillama_apy_feed` TtlCache). Альтернатива — реальный end-to-end прогон pg-миграции против тестового PostgreSQL-инстанса.

---

## Sprint v3.46 — 2026-05-30 — APY-feed per-protocol staleness monitoring + alerting (SPA-V346)

**Цель:** Поймать ситуацию, когда КОНКРЕТНЫЙ протокол в `data/historical_apy.json` перестал обновляться (последняя запись его истории старше порога), хотя фид в ЦЕЛОМ выглядит свежим — `generated_at` двигается, потому что ОСТАЛЬНЫЕ протоколы обновляются. Это вторая альтернатива из dispatch-ноты V344 (первую — schema-drift валидацию — закрыл V345).

**Контекст / слепое пятно:** Ни один существующий APY-feed монитор этого не ловит:
- `alert_apy_feed_stale` (V340) смотрит на **feed-level** `generated_at` — один залипший протокол его не сдвигает, если другие обновляются;
- `alert_apy_feed_protocol_anomaly` (V344) смотрит на **крах ЗНАЧЕНИЙ** apy/tvl и dropout — протокол с замороженными значениями, который просто перестал получать свежие даты (никуда не исчезает, значения не падают), не триггерит ни один из его сигналов.

Залипший протокол тихо скармливает устаревшую точку в covariance / dynamic-Kelly вселенную именно этой позиции, пока все агрегатные и value-based алерты молчат.

### Что сделано (SPA-V346-001)
- **`spa_core/alerts/risk_monitor.py`:**
  - Константа `APY_FEED_PROTOCOL_MAX_AGE_HOURS = 48.0` (последняя запись истории протокола старше = протокол тихо залип; >2 суток при суточной гранулярности) после `APY_FEED_SCHEMA_MIN_PROTOCOLS`.
  - `self._apy_feed_protocol_stale_health_file = self.data_dir / "apy_feed_protocol_stale_health_state.json"` в `__init__` после `_apy_feed_schema_health_file`.
  - Новый публичный метод `RiskMonitor.alert_apy_feed_protocol_stale(feed_path=None, *, snapshot=None, now=None, sender=None) -> bool` сразу после schema-drift helpers — зеркалит anomaly/drop 1-в-1: top-level `try/except → return False` (НИКОГДА не raise), lazy `TelegramSender`, persistent state, streak-логика.
  - **КЛЮЧЕВОЕ ПРОЕКТНОЕ РЕШЕНИЕ:** фид имеет **суточную** гранулярность дат (`date=YYYY-MM-DD`), а пайплайн идёт каждые 4ч (6 циклов/сутки) → внутри суток дата каждого протокола легитимно НЕ меняется между циклами. Поэтому staleness меряется по **возрасту записи в часах** (`now - last_record_date`), а НЕ по равенству дат между циклами — здоровый суточный фид никогда не ложно-срабатывает.
  - **Резолв snapshot:** `dict[protocol → last_record_date_raw]` из ПОСЛЕДНЕЙ записи истории каждого протокола (из фида: ключ `protocols` ИЛИ `protocol_history`, поле `date`|`ts`|`timestamp`). Парсер `_parse_dt`: epoch seconds (int/float), ISO (с заменой `Z`→`+00:00`), bare `YYYY-MM-DD`→полночь UTC, naive→UTC, ошибка→None. `now`: None→`datetime.now(utc)`, naive→utc.
  - **degraded** если: `unreadable` (snapshot None) ИЛИ любой протокол с `age > 48h` ИЛИ непарсимой/None датой (freshness неверифицируема → считаем stale).
  - **Streak-порог = 1:** healthy → `consecutive_stale=0` / `last_alerted_cycle=0` / `last_stale_keys=[]` / return False; stale → инкремент, `should_alert=(n>=1 AND n!=last_alerted)`, рефайр на каждом растущем цикле; `last_alerted_cycle=n` только ПОСЛЕ успешной отправки (failed/raised send НЕ двигает `last_alerted` → ретрай на следующем цикле). HTML msg `⚠️ <b>SPA APY Feed Protocol Stale</b>` со списком stale-протоколов (key + возраст в часах ИЛИ «no parseable date», лимит 5) + нота про устаревший covariance/Kelly-вход. Helpers `_load/_write_apy_feed_protocol_stale_health_state` graceful на miss/corrupt.
- **`spa_core/export_data.py`:** зеркальный try/except-блок «APY feed per-protocol staleness alert» сразу ПОСЛЕ блока «APY feed schema drift alert» в конце `run_export`: `RiskMonitor(data_dir=OUTPUT_DIR).alert_apy_feed_protocol_stale(feed_path=OUTPUT_DIR / "historical_apy.json", sender=TelegramSender())`, обёрнут в `try/except → log.error`. Существующие секции НЕ тронуты.
- **Тесты `spa_core/tests/test_apy_feed_protocol_stale_monitor.py`** (новый, offline, `FakeSender`/`BadSender`, `tmp_path`): all-fresh→no alert; суточная гранулярность (та же дата, age<порог)→НЕ stale (false-positive guard); ровно на пороге (strict `>`)→no alert; один протокол 3д stale→fire на первом цикле + msg содержит «Protocol Stale» и имя протокола; рефайр на следующем stale-цикле (streak вырос); recovery→reset streak; несколько stale-протоколов перечислены; непарсимая дата→stale; date=None→stale; epoch seconds поддержан; unreadable (snapshot None)→alert; naive now→UTC; чтение из feed-файла (`protocols` и `protocol_history`); полностью свежий feed→no alert; отсутствующий/битый feed→unreadable alert без исключения; persistence через re-instantiate; corrupt state→recover; bad-sender (raise)→swallow→False + last_alerted НЕ двинут; failed send (ok=False)→ретрай на следующем цикле.

### Файлы
Новые:
- `spa_core/tests/test_apy_feed_protocol_stale_monitor.py` (21 тест)

Обновлены:
- `spa_core/alerts/risk_monitor.py` (`APY_FEED_PROTOCOL_MAX_AGE_HOURS`, `_apy_feed_protocol_stale_health_file`, `alert_apy_feed_protocol_stale` + load/write helpers)
- `spa_core/export_data.py` (блок APY feed per-protocol staleness alert после schema drift alert)

### Результаты тестов
- `test_apy_feed_protocol_stale_monitor.py` — **21 PASS / 0 FAIL** (offline, `pytest`, Python 3.10).
- Регрессия мониторинга (`anomaly` + `protocol_drop` + `tvl_drop` + `stale` + `schema_drift` + `covariance_health` + `alerts`) — **163 PASS / 0 FAIL**, без новых фейлов.
- `py_compile` `risk_monitor.py` + `export_data.py` — ok. `KANBAN.json` валиден (`json.load`).
- Бэкапы `KANBAN.json.bak.v346` / `SPA_sprint_log.md.bak.v346` созданы. Done-карта `SPA-V346-001` добавлена в `columns.done`.

### Следующий спринт
**SPA-V347:** агрегированный «APY feed health» summary-индикатор в дашборде — свести staleness + protocol-count drop + tvl drop + per-protocol anomaly + schema drift + per-protocol staleness в один статус-бейдж. Альтернатива — реальный end-to-end прогон pg-миграции против тестового PostgreSQL-инстанса (за `SPA_PG_MIGRATION_EXECUTE=1`, `dry_run=False`) с psycopg2.

---

## Sprint v3.41 — 2026-05-30 — PostgreSQL migration execution path (gated, dry-run default) (SPA-V341)

**Цель:** Превратить `spa_core/persistence/pg_migration.py` из plan-only (V331) в модуль с РЕАЛЬНЫМ, но строго gated путём исполнения миграции SQLite → PostgreSQL. Сохранён слоистый safety-паттерн адаптеров (BLOCKED по умолчанию), добавлены ещё два защитных слоя поверх существующего gate.

### Что сделано (SPA-V341-001)
- **`spa_core/persistence/pg_migration.py`:**
  - Новая функция-хелпер `split_sql_statements(ddl) -> List[str]` — режет сгенерированный DDL-блоб на отдельные исполняемые стейтменты, отбрасывая комментарии (`-- …`) и пустые фрагменты, каждый завершается `;`. Добавлена в `__all__`.
  - Новый `_default_pg_connection_factory(pg_url)` — ленивый `import psycopg2` только для реального прогона; при отсутствии psycopg2 кидает `MigrationExecutionBlocked` (без hard-dependency на драйвер).
  - **Полностью реализован `execute_migration(plan, pg_url, *, i_understand_this_writes_data=False, sqlite_source=None, connection_factory=None, dry_run=True, batch_size=500) -> dict`** (был `raise NotImplementedError`):
    - **Gate 1+2 (как в V331):** требует `SPA_PG_MIGRATION_EXECUTE=1` в env И `i_understand_this_writes_data=True`; иначе `MigrationExecutionBlocked` (в сообщении показывает `env_set`/`opt_in`).
    - **Gate 3 (новый):** даже пройдя gate, по умолчанию `dry_run=True` — НИЧЕГО не пишет и даже не подключается к Postgres: возвращает план (`ddl_statements`, FK-safe `copy_order`, `rows_planned`). Реальная запись только при явном `dry_run=False`.
    - **Реальный прогон (`dry_run=False`):** требует `sqlite_source` (иначе `MigrationPlanError`); драйвер инъектируется через `connection_factory` (по умолчанию psycopg2) → unit-тестируется офлайн фейковым DB-API соединением. Применяет DDL (идемпотентный — `CREATE … IF NOT EXISTS`), копирует данные по таблицам в FK-safe порядке через параметризованный `executemany` (`%s`-плейсхолдеры, батчами `batch_size`), `commit()` в конце. Ошибка → best-effort `rollback()` + проброс; `finally` закрывает Postgres-соединение и (если открывали сами) SQLite. Никогда не закрывает переданное caller-ом соединение.
    - Возвращает summary: `{dry_run, ddl_statements, copy_order, rows_planned, rows_copied, committed}`.
  - Обновлён module docstring и `Phase scope` (V341): «schema + plan + gated execution (dry-run default) + tests». CLI без изменений (по-прежнему plan/ddl/json).
- **Тесты `spa_core/tests/test_pg_migration_execute.py`** (новый, офлайн, stdlib + pytest; `FakeConnection`/`FakeCursor` записывают весь SQL, in-memory SQLite с FK parent/child `authors`→`books`): 13 тестов — три ветки BLOCKED (нет env / нет opt-in / нет обоих); dry_run не подключается и не коммитит + dry_run это дефолт; реальный прогон применяет DDL и копирует корректные counts (authors=2, books=3) + commit + close + проверка `%s`-плейсхолдеров; FK-safe порядок INSERT (authors раньше books); `dry_run=False` без `sqlite_source` → `MigrationPlanError`; ошибка в середине копирования → `rollback`, без `commit`, проброс; батчинг 250 строк / batch=100 → `[100,100,50]`; `split_sql_statements` отбрасывает комментарии/пустые; DDL идемпотентен (`IF NOT EXISTS`).

### Файлы
Новые:
- `spa_core/tests/test_pg_migration_execute.py` (13 тестов)

Обновлены:
- `spa_core/persistence/pg_migration.py` (`split_sql_statements`, `_default_pg_connection_factory`, реализован `execute_migration`; docstring/scope; `__all__`)

### Результаты тестов
- Новый execute-path suite `test_pg_migration_execute.py` — **13 PASS / 0 FAIL** (`pytest 8.4.2`, Python 3.10, offline, FakeConnection/FakeCursor + in-memory SQLite).
- Полная suite `pg_migration` (новый + существующий plan-only `test_pg_migration.py`) — **41 PASS / 0 FAIL**.
- CLI smoke: `python3 -m spa_core.persistence.pg_migration --json --sqlite spa_core/database/spa.db` — план строится против реальной `spa.db` (FK-safe copy_order: message_bus → incidents → state → …), ошибок нет.
- AST-parse исходника и тест-файла — ok. `KANBAN.json` валиден (`json.load`).
- Бэкапы `KANBAN.json.bak.v341` / `SPA_sprint_log.md.bak.v341` созданы. Done-карта `SPA-V341-001` добавлена в `columns.done` (done 134 → 135).
- pytest установлен в sandbox через `pip install --break-system-packages pytest` (как в предыдущих спринтах — sandbox эфемерный).
- Примечание по ходу рана: bash-слой sandbox периодически отдавал пустые ответы (лаг прогрева воркспейса), но полностью восстановился — все тесты прогнаны и зелёные.

### Следующий спринт
**SPA-V342:** расширение feed/covariance мониторинга — алерт на резкое падение числа протоколов в `historical_apy.json` между циклами (частичная деградация фида при свежем `generated_at`), ЛИБО агрегированный «feed health» summary в дашборде (APY-feed staleness + covariance health + pipeline_health в один индикатор). Альтернатива — реальный end-to-end прогон pg-миграции против тестового PostgreSQL-инстанса (за `SPA_PG_MIGRATION_EXECUTE=1`, dry_run=False) с psycopg2.

---

## Sprint v3.40 — 2026-05-30 — APY-feed staleness monitoring + alerting (SPA-V340)

**Цель:** Добавить ранний health-трекинг историко-APY фида `data/historical_apy.json` (источник covariance-bridge, пишется секцией 9b `export_data.py` каждый 4h-цикл с полями `generated_at` ISO и `data_source` ∈ {defillama, synthetic}) до того, как деградация дойдёт до covariance `synthetic_fallback`. ПРОБЛЕМА: если фид тихо деградирует — `generated_at` залипает (файл не обновляется / отдаётся кэш), возраст превышает несколько циклов, ИЛИ `data_source` свалился в synthetic — это было НЕВИДИМО для алертинга, пока не доходило до covariance synthetic_fallback (SPA-V339). Нужен APY-feed staleness health-трекинг + Telegram-алерт, зеркалящий `alert_covariance_degraded` 1-в-1.

**Что сделано (SPA-V340-001):**
- **`spa_core/alerts/risk_monitor.py`:** добавлены module-level константы сразу после `COVARIANCE_DEGRADED_CYCLES_ALERT`: `APY_FEED_MAX_AGE_HOURS = 8.0` (historical_apy.json старше = stale, >2 цикла при 4h-каденции) и `APY_FEED_STALE_CYCLES_ALERT = 2` (подряд stale-циклов до алерта). В `__init__` добавлен путь state-файла `self._apy_feed_health_file = self.data_dir / "apy_feed_health_state.json"`.
- Новый публичный метод `RiskMonitor.alert_apy_feed_stale(self, feed_path=None, *, generated_at=None, data_source=None, now=None, sender=None) -> bool` размещён СРАЗУ после `alert_covariance_degraded` и его helpers, перед секцией APY persistence helpers — зеркалит структуру covariance-метода (top-level `try/except → return False`, НИКОГДА не raise; lazy-инстанс `TelegramSender` если `sender is None`; `sender.send(msg)` в try/except; persistent state; streak-логика).
- **Резолв метаданных:** если `generated_at is None` и `feed_path` задан — graceful чтение JSON по feed_path (отсутствует/битый → `generated_at` остаётся None, `data_source` None); забираются `generated_at` и (если None) `data_source` из документа. `now`: None → `datetime.now(timezone.utc)`, naive → `tzinfo=utc`. Парс `generated_at` в aware datetime (`fromisoformat` с заменой `Z`→`+00:00`, naive→utc, ошибка→None); `age_hours = (now - gen)/3600` или None.
- **Признаки деградации:** `too_old = age_hours is None or age_hours > APY_FEED_MAX_AGE_HOURS`; `stuck = generated_at is not None and prev_gen is not None and prev_gen == generated_at`; `synthetic = (data_source or "").lower().startswith("synthetic")`; `degraded = bool(too_old or stuck or synthetic)`.
- **Streak-логика (ТОЧНО как covariance):** healthy → `consecutive_stale=0`, `last_alerted_cycle=0`, обновить `last_generated_at`/`last_source`/`updated_at`, запись state, return False. Degraded → инкремент `consecutive_stale`; **fire когда `consecutive_stale >= APY_FEED_STALE_CYCLES_ALERT` AND `!= last_alerted_cycle`** — один раз ровно на пороге (2-й цикл) и снова на каждом следующем цикле растущего streak; после успешной отправки `last_alerted_cycle = consecutive_stale`. Recovery (свежий generated_at) сбрасывает streak. Reason-строка собирается из активных признаков (например "stuck generated_at", "age 9.2h > 8.0h", "data_source=synthetic"). Сообщение в стиле covariance: `⚠️ <b>SPA APY Feed Stale</b>` + n циклов + Reason + generated_at + Action (check DeFiLlama fetch + секция 9b). Helpers `_load/_write_apy_feed_health_state` — зеркало covariance-helpers (graceful на miss/corrupt; fresh `{consecutive_stale:0, last_generated_at:None, last_source:None, last_alerted_cycle:0, updated_at:None}`).
- **`spa_core/export_data.py`:** зеркальный try/except-блок «APY feed staleness alert» добавлен СРАЗУ после блока «Covariance degradation alert» в конце `run_export`: `RiskMonitor(data_dir=OUTPUT_DIR).alert_apy_feed_stale(feed_path=str(OUTPUT_DIR / "historical_apy.json"), sender=TelegramSender())`, обёрнут в `try/except → log.error("APY feed staleness alert dispatch failed")`. Существующие секции НЕ тронуты.
- **Тесты `spa_core/tests/test_apy_feed_stale_monitor.py`** (новый, pytest, offline, `FakeSender` записывает сообщения, `tmp_path`-изоляция): fresh feed → no alert + streak 0; single stale (age>8h) → no alert + streak 1; threshold (2 подряд) → fires ровно 1 раз, msg содержит "APY Feed"; 3-й stale → re-fire (streak вырос); recovery (свежий generated_at) → reset streak; stuck generated_at (одно значение, возраст ок) → degraded → fires на пороге; data_source=synthetic (возраст ок, не stuck) → degraded; отсутствующий + битый feed-файл через feed_path → degraded без исключения; чтение generated_at/data_source из feed_path JSON; persistence через re-instantiate `RiskMonitor`; bad-sender (`.send` raise) → swallow → False; naive `now` трактуется как UTC.

**Файлы:**
- `spa_core/alerts/risk_monitor.py` (modified: `APY_FEED_MAX_AGE_HOURS=8.0`, `APY_FEED_STALE_CYCLES_ALERT=2`; `_apy_feed_health_file` в `__init__`; `alert_apy_feed_stale()` + `_load_apy_feed_health_state()` + `_write_apy_feed_health_state()`)
- `spa_core/export_data.py` (modified: APY feed staleness alert-блок после covariance degradation alert)
- `spa_core/tests/test_apy_feed_stale_monitor.py` (new: 15 тестов)

**Результаты тестов:** `test_apy_feed_stale_monitor.py` — **15 PASS** (offline). Регрессия `test_covariance_health_monitor.py` + `test_alerts.py` + `test_covariance_export.py` — **103 PASS** (без новых фейлов). AST-parse `risk_monitor.py` + `export_data.py` — ok. `KANBAN.json` валиден (json.load). Бэкапы `.bak.v340` созданы. Известный baseline-фейл `test_engine_bridge::...morpho-blue-usdc-base` — пред-существующий, НЕ чинился, вне scope.

**Следующий спринт:** SPA-V341 — исполнение плана PostgreSQL-миграции (`pg_migration.py`, plan-only с v3.31) за флагом `SPA_PG_MIGRATION_EXECUTE=1` (контролируемый прогон с rollback); ЛИБО дальнейшее расширение feed/covariance-мониторинга — напр. алерт на резкое падение числа протоколов в `historical_apy.json` между циклами (частичная деградация фида при сохранении свежего `generated_at`), или агрегированный «feed health»-summary в дашборде, сводящий APY-feed staleness + covariance health + pipeline_health в один индикатор.

---

## Sprint v3.39 — 2026-05-30 — Covariance health monitoring + alerting (SPA-V339)

**Цель:** Подключить covariance-секцию пайплайна к мониторингу/алертингу. v3.38 (SPA-V338) врезал `covariance_export` в 4h-pipeline (секция 13b пишет `data/covariance_summary.json` с `source ∈ {live, partial, synthetic_fallback}` и трекает `_section_ok`/`_section_fail`). ПРОБЛЕМА: covariance-специфичная деградация (`source == "synthetic_fallback"` несколько циклов подряд ИЛИ падение секции) была НЕВИДИМА для алертинга — `alert_pipeline_failure` срабатывает только на `sections_failed > 2` / `total_pools_fetched == 0`. Нужен covariance-specific health-трекинг + Telegram-алерт при деградации N циклов подряд.

**Что сделано (SPA-V339-001):**
- **`spa_core/alerts/risk_monitor.py`:** добавлена module-level константа `COVARIANCE_DEGRADED_CYCLES_ALERT = 3` сразу после `CASH_BUFFER_MIN_PCT`. В `__init__` добавлен путь state-файла `self._cov_health_file = self.data_dir / "covariance_health_state.json"`.
- Новый метод `RiskMonitor.alert_covariance_degraded(cov_source, sender=None, *, section_failed=False) -> bool` размещён СРАЗУ после `alert_pipeline_failure` — зеркалит его структуру (HTML-msg с emoji + `<b>`-тегами, lazy-инстанс `TelegramSender` если `sender is None`, `sender.send(msg)` в try/except, лог, НИКОГДА не raise).
- **Логика:** `degraded = section_failed or cov_source in (None, "", "synthetic_fallback")`; healthy source = `"live"` | `"partial"`. State грузится через `_load_covariance_health_state()` (graceful: miss/corrupt → свежий `{"consecutive_degraded":0,"last_source":None,"last_alerted_cycle":0,"updated_at":None}`, helpers в стиле `_load_prev_apys`, stdlib json).
- **Правило алерта:** healthy → сброс `consecutive_degraded=0`, `last_alerted_cycle=0`, запись state, return False. Degraded → инкремент `consecutive_degraded`; **fire когда `consecutive_degraded >= COVARIANCE_DEGRADED_CYCLES_ALERT` AND `consecutive_degraded != last_alerted_cycle`** — т.е. один раз ровно на пороге (3-й цикл) и снова на каждом следующем цикле растущего streak (4-й, 5-й...); после отправки `last_alerted_cycle = consecutive_degraded`. Восстановление до live/partial сбрасывает streak и алертинг. Весь метод в top-level `try/except → return False`.
- **`spa_core/export_data.py`:** в инициализацию `_health` добавлен `"covariance_source": None`. В секции 13b success-ветка пишет `_health["covariance_source"] = cov_doc.get("source")`, except-ветка `= "synthetic_fallback"`. Отдельный try/except-блок после `# ── Pipeline failure alert` (после записи pipeline_health.json): `RiskMonitor(data_dir=OUTPUT_DIR).alert_covariance_degraded(_cov_src, sender=TelegramSender(), section_failed="covariance_summary" in failed_sections)`. Import-стиль зеркалит существующий блок (`from alerts.risk_monitor import RiskMonitor`).
- **Тесты `spa_core/tests/test_covariance_health_monitor.py`** (новый, pytest, offline, `FakeSender` записывает сообщения): healthy `live`/`partial` → no alert + streak 0; single synthetic → no alert + streak 1; threshold (3×synthetic) → fires ровно 1 раз на 3-м, msg содержит "Covariance Degraded"; 4-й synthetic → re-fire (streak вырос); recovery `live` → reset streak без алерта; `section_failed=True`+source None → degraded; corrupt state-файл → recover без исключения; persistence через re-instantiate `RiskMonitor` с тем же data_dir; bad-sender (`.send` raise) → swallow → False.

**Файлы:**
- `spa_core/alerts/risk_monitor.py` (modified: `COVARIANCE_DEGRADED_CYCLES_ALERT=3`; `_cov_health_file` в `__init__`; `alert_covariance_degraded()` + `_load_covariance_health_state()` + `_write_covariance_health_state()`)
- `spa_core/export_data.py` (modified: `covariance_source` в `_health`; capture source в секции 13b; covariance degradation alert-блок после pipeline failure alert)
- `spa_core/tests/test_covariance_health_monitor.py` (new: 11 тестов)

**Результаты тестов:** `test_covariance_health_monitor.py` — **11 PASS**. Регрессия `test_covariance_export.py` + `test_alerts.py` — **92 PASS** (без новых фейлов). AST-parse `export_data.py` + `risk_monitor.py` — ok. `KANBAN.json` валиден (json.load). Бэкапы `.bak.v339` созданы. Известный baseline-фейл `test_engine_bridge::...morpho-blue-usdc-base` — пред-существующий, НЕ чинился, вне scope.

**Следующий спринт:** SPA-V340 — исполнение плана PostgreSQL-миграции (`pg_migration.py`, plan-only с v3.31) за `SPA_PG_MIGRATION_EXECUTE=1`; ЛИБО дальнейшее улучшение covariance/monitoring (напр. трекинг возраста `data/historical_apy.json` / алерт на залипшую `generated_at` или устаревший APY-feed, чтобы ловить тихую деградацию ещё до перехода на synthetic_fallback).

---

## Sprint v3.38 — 2026-05-30 — Covariance export wired into 4h pipeline (SPA-V338)

**Цель:** Врезать вызов `covariance_export` в основной 4-часовой export-pipeline, чтобы `data/covariance_summary.json` авто-обновлялся каждый цикл вместе с остальными артефактами (`adapter_status.json`, `historical_apy.json`, `optimization_recommendations.json` и т.д.), а не генерировался только вручную через CLI.

**Контекст:** v3.36 (SPA-V336) создал `spa_core/analytics/covariance_export.py` — строит ковариационно-корреляционную матрицу живых APY (DeFiLlama через `apy_history_bridge`) и пишет `data/covariance_summary.json` (schema_version=1). v3.37 (SPA-V337) отрендерил этот JSON в дашборде. ПРОБЛЕМА: артефакт генерировался ТОЛЬКО вручную через CLI — в проде не обновлялся автоматически каждый 4h-цикл. Pipeline = `spa_core/export_data.py :: run_export(fetch=...)`, который пишет все `data/*.json` и трекает `pipeline_health` (`_section_ok`/`_section_fail`).

**Что сделано (SPA-V338-001):**
- В `run_export()` добавлена секция **13b** сразу после `optimization_recommendations` (#13) и перед PDF Report (#14) — логичное место рядом с другими аналитическими/optimization-экспортами.
- Вызов: `from analytics.covariance_export import write_covariance_json` → `write_covariance_json(out_path=str(OUTPUT_DIR / "covariance_summary.json"))`. Стандартный путь — тот же дефолт `data/covariance_summary.json`, что у CLI. Внутри `write_covariance_json` авто-мостит `data/historical_apy.json` (написан в #9b выше) через `apy_history_bridge` → `CovarianceEstimator` → live матрицы.
- **Graceful-обёртка** (зеркалит все опциональные экспорты пайплайна): вызов в `try/except`; на успехе `_section_ok("covariance_summary")` + `log.info(source/protocols)`; на сбое `log.error(..., exc_info=True)` + `_section_fail("covariance_summary")` + `write_json` заглушки (schema_version=1, source=synthetic_fallback, пустые матрицы, error). Пайплайн НИКОГДА не падает из-за covariance-шага.
- Зарегистрирован в `files_written`-манифесте (decision_log) и в `pipeline_health` (sections_ok/failed) тем же способом, что adapter_status/optimization. Существующие экспорты не менялись (байт-в-байт).
- Wiring-тест: класс `TestExportPipelineWiring` в `spa_core/tests/test_covariance_export.py` — статическая проверка (импорт+вызов `write_covariance_json`, стандартный путь, манифест, `_section_ok`/`_section_fail`, guarded try/except) + behavioural (raising-writer не пробрасывается = graceful) + offline end-to-end (bridge из `historical_apy.json` → валидный `covariance_summary.json` без сети).

**Файлы:**
- `spa_core/export_data.py` (modified: секция 13b — `write_covariance_json` в try/except + `_section_ok`/`_section_fail` + `files_written`-манифест)
- `spa_core/tests/test_covariance_export.py` (modified: +класс `TestExportPipelineWiring`)

**Результаты тестов:** `test_covariance_export.py` зелёный (58 baseline + новые wiring-тесты). `data/covariance_summary.json` + `KANBAN.json` валидны (json.load). Бэкапы `.bak.v338` созданы. Известный baseline-фейл `test_engine_bridge::...morpho-blue-usdc-base` — пред-существующий, НЕ чинился, вне scope.

**Следующий спринт:** SPA-V339 — исполнение плана PostgreSQL-миграции (`pg_migration.py`, plan-only с v3.31) за `SPA_PG_MIGRATION_EXECUTE=1`; ЛИБО подключение covariance к `pipeline_health`-мониторингу/алертам (warning/Telegram если covariance-секция падает или source=synthetic_fallback несколько циклов подряд).

---

## Sprint v3.37 — 2026-05-30 — Covariance dashboard render (SPA-V337)

**Цель:** Отрендерить `data/covariance_summary.json` (артефакт, эмитнутый в v3.36 `covariance_export.py`) в дашборде — Optimization/Analytics таб, карточка B6 «AI Recommendations»: heatmap корреляций APY + live volatility badges + source-индикатор (live/partial/synthetic). Зеркалит паттерн v3.34/v3.35 (фронт читает backend-JSON через `fetch`, `loadAdapterStatus`/`renderAdapterStatus`). Чисто фронтенд-изменение — backend/Python не трогался.

**Контекст:** Прямое продолжение «Следующего спринта» из v3.36. v3.36 материализовал `apy_history.json` (через bridge) и записал `data/covariance_summary.json` (schema_version=1, source=live, 7 протоколов, n_obs=81), но фронтенд его не отображал. V337 закрывает визуализационный gap тем же fetch-паттерном, что v3.34 (golive report) и v3.35 (adapter live APY): никаких новых библиотек, heatmap — обычная HTML-таблица с фоновой заливкой ячеек (НЕ Chart.js).

### Что сделано (SPA-V337-001)
- **HTML-панель ковариации** (`index.html`, карточка B6 `an-card`) — вставлена сразу ПОСЛЕ блока Efficient Frontier, внутри карточки:
  - Заголовок-секция в стиле существующих uppercase-лейблов: «Live APY Covariance — Correlation Matrix» с инлайн source-бейджем `#cov-source-badge`.
  - Мета-строка `#cov-meta` (window / min-obs / generated / bridged).
  - Контейнер volatility badges `#cov-vol-badges` (flex-wrap).
  - Контейнер heatmap `#cov-heatmap` (overflow-x:auto).
  - Чистый HTML/CSS-inline.
- **`loadCovariance()`** (рядом с `renderEfficientFrontier`) — `fetch(BASE + '/covariance_summary.json?_=' + Date.now())` с `.catch(()=>null)`, guard на null → `renderCovariance(data)`.
- **`renderCovariance(data)`**:
  - **source badge** — `live` → зелёный `#16a34a` «source: live DeFiLlama»; `partial` → amber `#f59e0b`; иначе → red `#B91C1C` «source: synthetic fallback». Тот же inline-badge стиль, что у `renderAdapterStatus`.
  - **meta** — `window ${window_days}d · min ${min_observations} obs · generated ${generated_at[:16]}` (+ ` · bridged` если `history_bridged`).
  - **volatility badges** — по одному на протокол из `protocols`: `${shortName} ${volatility_pp.toFixed(2)}pp` + `μ mean_apy` маленьким, tier-цвет (T1 `#185FA5`, T2 `#7c3aed`); shortName = ключ без `-ethereum`.
  - **heatmap** — HTML `<table>` из `correlation_matrix`: короткие аббревиатуры (aave-usdc / aave-usdt / comp-usdc / euler-usdc / maple-usdc / morpho-usdc / yearn-usdc), значения `.toFixed(2)`, фон ячейки градиентом по `r` (r≥0 → `rgba(220,38,38,alpha)`, r<0 → `rgba(24,95,165,alpha)`, `alpha=min(1,|r|)*0.7`), диагональ серый `#e5e7eb`; пустая/отсутствующая матрица → заглушка «No covariance data».
  - Все `getElementById` защищены `if(!el)return`.
- **Вызов** `loadCovariance()` добавлен рядом с `loadOptimization()` в блоке загрузки Optimization-таба.

### Файлы
- **Обновлён:** `index.html` (HTML-панель в карточке B6; `loadCovariance()` + `renderCovariance()`; вызов в Optimization-блоке).
- **Обновлён:** `KANBAN.json` (+ бэкап `KANBAN.json.bak.v337`) — карточка SPA-V337-001 в `done`, верхнеуровневые поля sprint_completed→v3.37, last_updated/last_dispatch_run/last_dispatch_note.
- **Обновлён:** `SPA_sprint_log.md` (+ бэкап `SPA_sprint_log.md.bak.v337`).

### Результаты проверки
- `python3 -c "import json;json.load(open('KANBAN.json'))"` → **KANBAN ok**.
- `python3 -c "import json;json.load(open('data/covariance_summary.json'))"` → **cov ok**.
- `grep -c "function renderCovariance" index.html` → **1**; `grep -c "loadCovariance" index.html` → **2** (определение функции на строке 4247 + вызов в Optimization-блоке на строке 2773).
- Регрессия `spa_core/tests/test_covariance_export.py` → **58 PASS** (бэкенд не менялся; фронт тестами не покрыт — как v3.32/v3.34/v3.35). Baseline morpho-blue-usdc-base fail вне scope.

### Следующий спринт
**SPA-V338** — подключить `covariance_export` в 4-часовой export-pipeline (`export_data.py`), чтобы `data/covariance_summary.json` авто-обновлялся каждый цикл вместе с остальными артефактами (сейчас он генерится только вручную через CLI). Альтернатива: исполнение плана PostgreSQL-миграции (`pg_migration.py`, plan-only с v3.31) — фактический перенос SQLite→PG за `SPA_PG_MIGRATION_EXECUTE=1`.

---

## Sprint v3.36 — 2026-05-30 — Live APY covariance export (FEAT-007 финал: apy_history_bridge + covariance_export)

**Цель:** Закрыть последний end-to-end gap живой APY-ковариации для dynamic-Kelly / Markowitz сайзинга. Phase 1 (v3.12) дал `CovarianceEstimator` + `dynamic_kelly`; Phase 2 врезал их в `optimization/recommender.py` и `optimization/markowitz.py` за флагом `SPA_LIVE_COVARIANCE=1`. **Но `CovarianceEstimator` читает rolling-серии из `data/apy_history.json`, который пишется ТОЛЬКО инкрементально `APYTracker.record_snapshot` во время live-цикла — в sandbox/fresh-checkout его нет, поэтому каждый `SPA_LIVE_COVARIANCE=1` прогон молча падал в синтетику CV=10%.** Живая ковариация из DeFiLlama никогда фактически не считалась. V336 материализует store из уже существующего экспорта и эмитит dashboard-ready JSON.

**Контекст:** Прямое продолжение «Следующего спринта» из v3.35 (FEAT-007 — live APY rolling covariance для Kelly). v3.35 заканчивается на 5 → периодический architect review: `python3 -m spa_core.dev_agents.architect --command review-backlog` падает с `ModuleNotFoundError: No module named 'anthropic'` (как в v3.30 — credentials LLM-агента в автономном sandbox нет), поэтому ревью backlog проведено оркестратором вручную. Все нумерованные спринты SPA-V326…V335 закрыты; HIGH-backlog = только `user_action` (Secrets / Pages / Telegram / Gnosis Safe / RPC ключи); FEAT-001/002 — mega-features v2.0 (live-капитал, вне scope dev-агента). FEAT-007 (MEDIUM, features) — единственная незакрытая код-задача → взята. Status pass недопустим.

### Что сделано (SPA-V336-001)
- **`spa_core/analytics/apy_history_bridge.py`** (new) — мост существующего `data/historical_apy.json` (`{protocols:{key:[{date,apy,tvl_usd}]}}`, реальный 90-дневный DeFiLlama/synthetic экспорт) в APYTracker-схему `data/apy_history.json` (`{protocol_history:{key:[{ts,apy,tvl_usd}]}, last_updated}`):
  - `_date_to_iso_ts`: `YYYY-MM-DD` → tz-aware ISO `T00:00:00+00:00` (полные ISO/`Z`/naive тоже нормализуются), чтобы парситься через `estimator._parse_iso` и rolling-window фильтр; невалидное → `None` (запись дропается).
  - `convert_history`: pure / side-effect free, никогда не падает (malformed sub-structures скипаются по-записи; протоколы без usable-точек опускаются); ключи `protocol_history` сортируются для детерминизма; `last_updated` берётся из `generated_at`.
  - `load_historical` / `build_tracker_document` / `write_tracker_history`; `ensure_apy_history()` — идемпотентный helper (НЕ трогает существующий live-store, возвращает False). CLI `--source/--out/--write/--json`.
- **`spa_core/analytics/covariance_export.py`** (new) — строит `CovarianceEstimator` над bridged store (авто-мост из `historical_apy.json`, если `apy_history.json` отсутствует), считает:
  - per-protocol volatilities/mean/n_obs (через `estimator.summary`);
  - полную **covariance + correlation матрицу** с tier-map (`tier_for` longest-prefix: aave/compound/morpho/sky→T1, yearn/euler/maple/pendle→T2);
  - `source`-label: `live` (все ≥7 obs) / `partial` / `synthetic_fallback`;
  - пишет `data/covariance_summary.json` (`schema_version=1`, `generated_at`, `window_days`, `min_observations`, `history_bridged`, `protocols`, матрицы). Матрицы округлены для diff-friendly вывода. CLI `--write/--json/--window/--source/--history/--out/--no-bridge`.
- Существующие call-sites НЕ менялись — синтетический путь (флаг выключен) байт-в-байт прежний; новый код — строгий superset.

### Verbatim (data/covariance_summary.json, перегенерирован)
- `source=live`, `window_days=90`, `schema_version=1`, 7 протоколов, у всех `n_obs=81`, `fallback=false`.
- volatility_pp: aave-v3-usdc 2.61 · aave-v3-usdt 2.63 · compound-v3-usdc 2.00 · euler-v2-usdc 2.23 · maple-usdc 2.98 · morpho-usdc 2.07 · yearn-v3-usdc 2.19.
- Корреляционная матрица симметрична, диагональ=1.0; ковариационная — диагональ ≥0.

### Интеграция подтверждена
- `AllocationRecommender().recommend(..., SPA_LIVE_COVARIANCE=1)` → `covariance_source="live"` (раньше — `synthetic`), без крэша. Это прямое доказательство, что live-путь FEAT-007 теперь получает реальные данные.

### Файлы
Новые:
- `spa_core/analytics/apy_history_bridge.py`
- `spa_core/analytics/covariance_export.py`
- `spa_core/tests/test_covariance_export.py` (58 тестов)
- `data/covariance_summary.json` (артефакт)

Обновлены/перегенерированы:
- `data/apy_history.json` (через мост — 7 протоколов, 630 точек)
- `KANBAN.json` (done +1 SPA-V336-001; FEAT-007 features→done; sprint_completed→v3.36; бэкап `KANBAN.json.bak.v336`)
- `SPA_sprint_log.md` (этот раздел; бэкап `SPA_sprint_log.md.bak.v336`)

### Результаты тестов
- `test_covariance_export.py`: **58 PASS / 0 FAIL** (мост: ts-конверсия, schema-mapping, graceful malformed, идемпотентный ensure, детерминизм; export: tier resolution, source-классификация, симметрия/диагональ матриц, missing-source→synthetic, JSON-сериализуемость, CLI round-trip; estimator end-to-end на bridged данных — live, не fallback).
- FEAT-007 регрессия (`test_covariance_estimator` 31 + `test_dynamic_kelly` 21 + `test_optimization` 20 + `test_covariance_export` 58 + recommender): **141 PASS / 0 FAIL**.
- `test_engine_bridge`: **36 PASS / 1 FAIL** — единственное падение `test_malformed_returns_none[morpho-blue-usdc-base]` пред-существующее (baseline, вне scope).
- `data/apy_history.json` и `data/covariance_summary.json` валидны (`json.load` OK). `KANBAN.json` валиден.

### Следующий спринт
**SPA-V337:** Отрендерить `data/covariance_summary.json` в дашборде (Analytics/Optimization таб): матрица корреляций (heatmap) + live volatility badges + `source` индикатор (live/synthetic) — зеркалит паттерн v3.34/35 (фронт читает backend-JSON через fetch). Альтернатива: исполнение плана PostgreSQL-миграции (v3.31), либо подключить `covariance_export` в 4h export-pipeline (`export_data.py`) для авто-обновления `covariance_summary.json` каждый цикл.

---

## Sprint v3.35 — 2026-05-30 — Live APY enrichment (adapter_status.json встраивает реальные DeFiLlama значения + dashboard render)

**Цель:** Закрыть последний gap живого APY-конвейера. В v3.27 создан `defillama_apy_feed.get_live_apy` (реальный фетч DeFiLlama `/pools` с TTL-кэшем), в v3.28 он подключён в live-путь `get_supply_apy` всех 5 T2-адаптеров, в v3.33/v3.34 создан `data/adapter_status.json` и дашборд читает его через fetch. **Но сам `adapter_status.py` собирал только `mock_apy` + флаг `live_enabled` — фактические live-значения никогда не попадали ни в JSON, ни на дашборд.** V335 встраивает реальные live APY в документ и рендерит их.

**Контекст:** Named «следующий спринт» из v3.34 («оживить live APY») по факту уже был реализован на уровне feed+адаптеров → status pass запрещён → взят следующий реальный, self-contained gap того же нарратива (v3.32→v3.33→v3.34→v3.35). Stale-карточка `in_progress` SPA-V335-001 (FEAT-003 Investor Reporting, 60h mega-feature, без реализации) заменена на фактически выполненную V335. HIGH-backlog = user-actions (Secrets/Pages/Telegram/Safe), FEAT-001/002 — mega-features v2.0.

### Что сделано (SPA-V335-001)
- `spa_core/execution/adapter_status.py`:
  - Новая чистая функция `_fetch_live_apy_map(protocol_key, mock_apy)`: итерирует те же `(chain, asset)` пары, что есть в `_DRY_RUN_APY` адаптера, и для каждой зовёт `defillama_apy_feed.get_live_apy` (lazy import в try/except; каждый запрос индивидуально guard-нут — НИКОГДА не пробрасывает). Возвращает `{chain:{asset:apy}}` только из non-None значений (строгий subset `mock_apy`; пустые chain опускаются).
  - `_adapter_record`: вызывает enrichment ТОЛЬКО при `live_enabled=True` и чистом импорте адаптера; непустой результат → `record['live_apy']`, `apy_source.mode` flip `mock`→`live`, `live_values_present=True`. Поле `apy_source.live_values_present` добавлено всегда (default False).
  - Graceful degradation: при выключенном `SPA_LIVE_APY` сеть не трогается вообще; при network/parse-fail или no-match — `live_apy` пуст, `mode` остаётся `mock`. Контракт идентичен live-пути `get_supply_apy` в адаптерах.
  - `data/adapter_status.json` перегенерирован (offline → `live_apy_enabled=false`, `live_apy` отсутствует, `schema_version=1`, +`live_values_present`).
- `index.html` (Go-Live таб, точечные Edit):
  - Вынесен общий форматтер `fmtApyMap(map)` (был инлайн в `mapAdapterRecord`; вывод mock-строки байт-в-байт прежний).
  - `mapAdapterRecord` добавляет `apyLive` (HTML из `rec.live_apy`) и `liveValuesPresent` (из `apy_source.live_values_present`).
  - Новый `apyCell(a)`: при наличии live-значений показывает их зелёным + зачёркнутый mock ниже; иначе mock. Колонка переименована `Mock APY`→`APY`.
  - `srcBadge` теперь различает три состояния: `live DeFiLlama (project)` (зелёный, есть значения) / `mock · live "project" (no pool match)` (амбер, гейт включён но матча нет) / `mock (live: DeFiLlama "project")` (гейт выключен).
  - JS валиден (`node --check` на извлечённом инлайн-скрипте, exit 0).

### Verbatim (data/adapter_status.json, offline-режим)
- 5 адаптеров; `live_apy_enabled=false`; ни у одной записи нет `live_apy`; у всех `apy_source.live_values_present=false`, `mode="mock"`.
- yearn-v3 T2 cap 0.2 BLOCKED · euler-v2 T2 0.2 BLOCKED · maple T2 0.2 BLOCKED · pendle-pt T2 0.2 NOT_IMPLEMENTED · sky-susds T2-conditional 0.0 ("→0.30 when ELIGIBLE") BLOCKED.

### Файлы
Обновлены:
- `spa_core/execution/adapter_status.py` (_fetch_live_apy_map + live enrichment + live_values_present)
- `spa_core/tests/test_adapter_status.py` (+8 тестов: `TestLiveApyEnrichment`)
- `index.html` (fmtApyMap / apyLive / liveValuesPresent / apyCell / srcBadge / колонка APY)
- `spa_core/tests/test_dashboard_adapter_sync.py` (+5 wiring-guard тестов)
- `data/adapter_status.json` (перегенерирован)
- `KANBAN.json` (in_progress очищен; done +1 SPA-V335-001; sprint_completed→v3.35; бэкап `KANBAN.json.bak.v335`)
- `SPA_sprint_log.md` (этот раздел; бэкап `SPA_sprint_log.md.bak.v335`)

### Результаты тестов
- `test_adapter_status.py`: **63 PASS** (55 + 8 новых live-enrichment; покрывают: нет live при выключенном гейте, сеть не трогается при выключенном гейте, встраивание при включённом, omit при None, никогда не падает при исключении feed, subset-семантика `_fetch_live_apy_map`, partial-hit flip→live, JSON-сериализуемость).
- `test_dashboard_adapter_sync.py`: **60 PASS** (55 + 5 wiring-guard на `fmtApyMap`/`apyLive`/`rec.live_apy`/`liveValuesPresent`/`apyCell`).
- Регрессия (`test_engine_bridge` + `test_yearn_v3_adapter` + `test_maple_adapter`): **159 PASS / 1 FAIL** — единственное падение `test_malformed_returns_none[morpho-blue-usdc-base]` пред-существующее (baseline, вне scope).
- `data/adapter_status.json` и `KANBAN.json` валидны (`json.load` OK).

### Следующий спринт
**SPA-V336:** FEAT-007 — заменить синтетическую ковариационную матрицу в Kelly-сайзинге на rolling 90-day live APY covariance из DeFiLlama (теперь, когда live APY реально доступен end-to-end). Альтернатива: исполнение плана PostgreSQL-миграции (v3.31). **NB:** v3.35 заканчивается на 5 → перед выбором следующего спринта запустить периодический architect review `python3 -m spa_core.dev_agents.architect --command review-backlog`.

---

## Sprint v3.34 — 2026-05-30 — Авто-синхронизация Go-Live дашборда (index.html ← data/adapter_status.json)

**Цель:** Устранить остаточный хардкод во фронте. В v3.33 создан единый backend-источник истины `data/adapter_status.json` (генерируется `spa_core/execution/adapter_status.py`), но `index.html` (Go-Live таб) всё ещё рендерил таблицу адаптеров из захардкоженной JS-константы `ADAPTER_STATUS`. V334 переключает фронт на чтение JSON через fetch с graceful fallback на встроенные значения.

**Контекст:** Прямое продолжение «Следующего спринта» из v3.33. Все нумерованные спринты SPA-V326…V333 закрыты; HIGH-backlog = user-actions (Secrets / GitHub Pages / Telegram / Gnosis Safe), FEAT-001/002 — mega-features (Phase 3, v2.0). Status pass недопустим → взят логичный self-contained dev-шаг, явно названный в v3.33.

### Что сделано (SPA-V334-001)
- `index.html` (≈5225 строк, точечные Edit-правки, не переписывался целиком):
  - Хардкод `const ADAPTER_STATUS = [...]` переименован в `const ADAPTER_STATUS_FALLBACK` (данные сохранены как fallback).
  - Добавлены модульные переменные `ADAPTER_STATUS_DATA` / `ADAPTER_STATUS_LIVE_APY` / `ADAPTER_STATUS_GENERATED_AT`.
  - Добавлена чистая функция-трансформер `mapAdapterRecord(rec)`: backend-запись (`protocol_key, name, tier, allocation_cap, allocation_note?, chains[], assets[], mock_apy{}, write_state, apy_source{mode,live_project,live_enabled}`) → форма, которую ждёт рендер-таблица (cap `0.2→"20%"`, chains.join, assets.join, APY-HTML из `mock_apy`, state-маппинг `BLOCKED→blocked`/`NOT_IMPLEMENTED→notimpl`).
  - Добавлена `async function loadAdapterStatus()`: `fetch(BASE + '/adapter_status.json?_=' + Date.now())`, маппинг `adapters[]`, на ошибку — `ADAPTER_STATUS_DATA=null` (→ fallback), в любом случае вызывает `renderAdapterStatus()`.
  - `renderAdapterStatus()` теперь рендерит из `ADAPTER_STATUS_DATA ?? ADAPTER_STATUS_FALLBACK`, `liveApy` берётся из `ADAPTER_STATUS_LIVE_APY`. Разметка `pendle-table` и хелперы `stateColor`/`srcBadge` сохранены; добавлена подпись «synced from data/adapter_status.json · generated …».
  - Прямой вызов `renderAdapterStatus()` заменён на `loadAdapterStatus()` (fire-and-forget внутри `loadGoLive`).
  - JS-синтаксис проверен `node --check` на извлечённом инлайн-скрипте (exit 0); ссылок на старое имя не осталось.
- `data/adapter_status.json` перегенерирован (`python3 -m spa_core.execution.adapter_status --write`, exit 0; валиден, 5 адаптеров, schema_version=1).
- Тесты: `spa_core/tests/test_dashboard_adapter_sync.py` — 50 контракт-тестов (наличие/валидность JSON, required-поля каждого адаптера, фактические tier/cap/write_state сверены напрямую с JSON, python-зеркало трансформера `_map_adapter_record`, guard на присутствие `loadAdapterStatus`/`ADAPTER_STATUS_FALLBACK`/`mapAdapterRecord`/`adapter_status.json` в index.html и на исчезновение старой `const ADAPTER_STATUS =`).

### Verbatim значения (сверены с data/adapter_status.json)
- yearn-v3 — T2, cap 0.2, BLOCKED.
- euler-v2 — T2, cap 0.2, BLOCKED.
- maple — T2, cap 0.2, BLOCKED.
- pendle-pt — T2, cap 0.2, **NOT_IMPLEMENTED**.
- sky-susds — **T2-conditional**, cap **0.0** (allocation_note "→0.30 when ELIGIBLE"), BLOCKED.

### Файлы
Новые:
- `spa_core/tests/test_dashboard_adapter_sync.py` (50 тестов)

Обновлены:
- `index.html` (Go-Live таб: fetch adapter_status.json + fallback + mapAdapterRecord)
- `data/adapter_status.json` (перегенерирован)
- `KANBAN.json` (done +1: SPA-V334-001; sprint_completed→v3.34; бэкап `KANBAN.json.bak.v334`)
- `SPA_sprint_log.md` (этот раздел; бэкап `SPA_sprint_log.md.bak.v334`)

### Результаты тестов
- Новый файл `test_dashboard_adapter_sync.py`: **50 PASS / 0 FAIL**.
- `test_adapter_status.py`: **55 PASS / 0 FAIL**.
- Регрессия (`test_engine_bridge` + `test_adapter_status`): **91 PASS / 1 FAIL** — единственное падение `test_malformed_returns_none[morpho-blue-usdc-base]` пред-существующее (morpho-blue parse, baseline), вне scope V334.
- `data/adapter_status.json` валиден (`json.load` OK, 5 адаптеров). `KANBAN.json` валиден.

### Следующий спринт
**SPA-V335:** Оживить live APY-источник — фактическое чтение DeFiLlama yields при `SPA_LIVE_APY=1` (вместо текущего mock-fallback во всех T2-адаптерах), с TTL-кэшем и graceful degradation на mock. (v3.35 заканчивается на 5 → перед выбором запустить периодический architect review `python3 -m spa_core.dev_agents.architect --command review-backlog`.) Альтернатива: исполнение плана PostgreSQL-миграции из v3.31.

---

## Sprint v3.33 — 2026-05-29 — Adapter status (backend JSON source of truth)

**Цель:** Устранить хардкод-дублирование данных адаптеров. В v3.32 таблица статуса execution-адаптеров в `index.html` (Go-Live таб) брала tier / alloc cap / chains / assets / mock APY / write-state из JS-константы `ADAPTER_STATUS`, продублированной из Python adapter-модулей. V333 создаёт единый backend-источник истины, который программно собирает эти метаданные из самих модулей и эмитит JSON.

**Контекст:** Прямое продолжение «Следующего спринта» из v3.32 («вынести данные адаптеров в JSON-эндпоинт для авто-синхронизации с backend»). Все нумерованные спринты SPA-V326…V332 закрыты; HIGH-backlog состоит из user-actions (Secrets / GitHub Pages / Telegram), FEAT-001/002 — mega-features (60–80h). Status pass недопустим → взят логичный self-contained dev-шаг.

### Что сделано (SPA-V333-001)
- Создан `spa_core/execution/adapter_status.py` (чистый stdlib: argparse/importlib/json/logging/os/datetime/pathlib; никакого web3/psycopg2; adapter-модули импортируются лениво в try/except — сбой одного адаптера даёт запись с полем `error` и не роняет сбор; нет сетевых вызовов; не кидает на happy path).
  - Реестр `_ADAPTER_SPECS` на 5 адаптеров. Adapter-класс определяется динамически (атрибут модуля с именем на `Adapter`), `SUPPORTED_CHAINS/ASSETS` и `_DRY_RUN_APY` читаются напрямую из модуля.
  - `collect_adapter_status() -> list[dict]`: protocol_key, name, tier, allocation_cap, allocation_note (optional), chains, assets, mock_apy (вложенный chain→asset→apy), write_state, apy_source ({mode, live_project, live_enabled}). `live_enabled` из `defillama_apy_feed.live_apy_enabled()` в try/except (default False).
  - `build_status_document()` → {generated_at, schema_version:1, execution_mode, live_apy_enabled, adapters}. `write_status_json(path=None)` пишет `data/adapter_status.json` (indent=2). CLI `python3 -m spa_core.execution.adapter_status [--json | --write [PATH]]`.
- Сгенерирован артефакт `data/adapter_status.json` (5 адаптеров, валиден).
- Тесты: `spa_core/tests/test_adapter_status.py` — 55 тестов (наличие/required-поля, tier, write_state, allocation_cap, mock_apy сверяется напрямую с `_DRY_RUN_APY` каждого реального модуля, build_status_document, write_status_json в tmp + json.load, live_enabled через env SPA_LIVE_APY).

### Verbatim значения (сверены с adapter-модулями)
- yearn-v3 — T2, cap 0.20, BLOCKED, ethereum+arbitrum, USDC/USDT, mock eth 6.8/6.5, arb 7.1/6.9, project "yearn".
- euler-v2 — T2, cap 0.20, BLOCKED, ethereum, USDC/USDT, mock 7.4/7.1, "euler".
- maple — T2, cap 0.20, BLOCKED, ethereum, USDC, mock 5.6, "maple".
- pendle-pt — T2, cap 0.20, **NOT_IMPLEMENTED**, ethereum, USDC/USDT, mock 6.5/6.1, "pendle".
- sky-susds — **T2-conditional**, cap **0.0** (allocation_note "→0.30 when ELIGIBLE"), BLOCKED, ethereum, USDS/DAI, mock 6.5/6.5, "sky".

### Файлы
Новые:
- `spa_core/execution/adapter_status.py`
- `spa_core/tests/test_adapter_status.py` (55 тестов)
- `data/adapter_status.json` (артефакт)

Обновлены:
- `KANBAN.json` (done +1: SPA-V333-001; sprint_completed→v3.33; бэкап `KANBAN.json.bak.v333`)
- `SPA_sprint_log.md` (этот раздел; бэкап `SPA_sprint_log.md.bak.v333`)

### Результаты тестов
- Новый файл: **55 PASS / 0 FAIL** (pytest 9.0.3, Python 3.10).
- Регрессия (`test_engine_bridge` / `test_pendle_pt_adapter` / `test_sky_susds_adapter`): **135 PASS / 1 FAIL** — единственное падение `test_malformed_returns_none[morpho-blue-usdc-base]` пред-существующее (morpho-blue parse, baseline), вне scope V333.
- `data/adapter_status.json` валиден (`json.load` OK, 5 адаптеров). `KANBAN.json` валиден.

### Следующий спринт
**SPA-V334:** Авто-синхронизация дашборда — `index.html` (Go-Live таб) читает `data/adapter_status.json` (fetch) вместо хардкод-константы `ADAPTER_STATUS`, с graceful fallback на встроенные значения. Альтернатива: оживить APY-источник (фактическое чтение live DeFiLlama при `SPA_LIVE_APY`).

---

## Sprint v3.32 — 2026-05-29 — Go-live dashboard update (T2/conditional adapter status)

**Цель:** Добавить в Go-Live таб `index.html` секцию со статусом новых T2/conditional execution-адаптеров (Yearn V3, Euler V2, Maple, Pendle PT, Sky/sUSDS) — по каждому: tier, allocation cap, live/blocked state, источник APY (mock / live DeFiLlama). Read-only дашборд, без backend-изменений.

**Контекст:** Адаптеры уже реализованы (Phase 3, live-writes заблокированы); их mock APY лежат в `_DRY_RUN_APY` каждого модуля `spa_core/execution/adapters/*_adapter.py`. V332 — чисто фронтовая визуализация существующего состояния, новых Python-изменений нет.

### Что сделано (SPA-V332-001)
- **HTML:** в `<div id="tab-golive">` после блока «📋 Readiness Criteria» и перед «📄 Investor Report» добавлен новый блок `<div class="db-full">` с заголовком `.db-section` «🔌 T2 / Conditional Adapters» и контейнером `<div id="golive-adapters">` (со skeleton-плейсхолдером до рендера).
- **JS:** добавлены константа `ADAPTER_STATUS` (массив из 5 адаптеров) и функция `renderAdapterStatus()` (рядом с `renderGoLiveCriteria`/`renderGoLiveReport`). Вызов `renderAdapterStatus()` добавлен в `loadGoLive()` рядом с остальными `renderGoLive*`.
- **Таблица** строится в стиле `.pendle-table`, колонки: Adapter | Tier | Alloc Cap | Chains | Assets | Mock APY | APY Source | Write State.
- **Данные (verbatim из adapter-модулей `_DRY_RUN_APY` + конвенции tier/cap):**
  - Yearn V3 — T2, cap 20%, ethereum+arbitrum, USDC/USDT, mock ETH 6.8/6.5, ARB 7.1/6.9, writes BLOCKED (Phase 3, SPA_EXECUTION_MODE≠live), source mock / live DeFiLlama "yearn".
  - Euler V2 — T2, cap 20%, ethereum, USDC/USDT, mock 7.4/7.1, BLOCKED, "euler".
  - Maple — T2, cap 20%, ethereum, USDC, mock 5.6, BLOCKED, "maple".
  - Pendle PT — T2, cap 20%, ethereum, USDC/USDT (PT/ERC-5115), mock implied 6.5 (mat. 2026-09-24) / 6.1 (mat. 2026-12-31), writes NOT_IMPLEMENTED (Phase 3), "pendle".
  - Sky/sUSDS — T2-conditional, cap **0%** с пометкой «→ 30% when ELIGIBLE (GSM 48h)», ethereum, USDS/DAI, mock 6.5, supply/withdraw BLOCKED (статус PENDING до ELIGIBLE), "sky".
- **Цветокодирование Write State:** BLOCKED → `#B91C1C`, NOT_IMPLEMENTED → `#f59e0b`, live-ready → `#16a34a` (token'ы страницы). APY Source — бэйдж mock (амбер) с указанием будущего live-проекта DeFiLlama; при `SPA_LIVE_APY` логически переключается на live.

### Файлы
Обновлены:
- `index.html` (Go-Live таб: новый блок секции ~строки 1815–1822; JS — `ADAPTER_STATUS` + `renderAdapterStatus()` рядом с `renderGoLiveCriteria`, вызов в `loadGoLive()`)
- `KANBAN.json` (SPA-V332 backlog→done как SPA-V332-001; sprint_completed→v3.32; last_updated→2026-05-29; бэкап `KANBAN.json.bak.v332`)
- `SPA_sprint_log.md` (этот раздел; бэкап `SPA_sprint_log.md.bak.v332`)

### Результаты
- Изменение чисто HTML/JS — **новых Python-тестов не добавлялось** (read-only дашборд, backend не затронут).
- Проверено: `python3 -c "import json;json.load(open('KANBAN.json'))"` — валиден.
- Проверено: заголовок «🔌 T2 / Conditional Adapters» присутствует в `index.html`; `renderAdapterStatus` и определён, и вызван из `loadGoLive()`; контейнер `id="golive-adapters"` на месте; `<div id="tab-golive">` корректно закрывается (`</div><!-- /tab-golive -->`), парность тегов не нарушена.
- Значения mock APY/cap/tier сверены с `spa_core/execution/adapters/{yearn_v3,euler_v2,maple,pendle_pt,sky_susds}_adapter.py`.

### Следующий спринт
Backlog почти исчерпан по dev-задачам (MEV SPA-V326 закрыт ранее; PG-миграция SPA-V331 — plan-only). Большинство оставшихся карточек требуют действий пользователя (workflow-scope PAT `BL-006`) или живого капитала/инфраструктуры. Логичный следующий dev-шаг — оживить APY-источник в этой же секции (фактическое чтение `SPA_LIVE_APY` / live DeFiLlama-статуса вместо статичного флага), либо вынести данные адаптеров в JSON-эндпоинт для авто-синхронизации с backend.

---

## Sprint v3.31 — 2026-05-29 — PostgreSQL migration prep (SQLite → PostgreSQL, plan-only)

**Цель:** Подготовить (но НЕ выполнять) миграцию с SQLite на PostgreSQL: новый модуль `spa_core/persistence/pg_migration.py` — интроспекция текущей SQLite-схемы, генерация эквивалентного PostgreSQL DDL (типы, default'ы, индексы) и FK-safe план копирования. Plan-only по scope (`без выполнения миграции`).

**Контекст:** В репо уже есть BL-008 seam (`spa_core/database/connection.py` + `db_url.py`, поддержка SQLite/Postgres) и Alembic baseline (`0001_initial_schema.py` с двумя диалектами DDL для 7 канонических таблиц). V331 добавляет *generic* инструмент миграции поверх этого: он не дублирует Alembic, а интроспектит живую SQLite-БД и выводит Postgres-DDL программно, поэтому будущие таблицы мигрируют автоматически.

### Что сделано (SPA-V331-001)
- Создан `spa_core/persistence/__init__.py` + `spa_core/persistence/pg_migration.py` (чистый stdlib: `sqlite3`/`re`/`dataclasses`; psycopg2 НЕ импортируется на plan-пути).
- **Type mapping (SQLite affinity → PostgreSQL):** реализованы 5 правил affinity из SQLite-доков (`INT*`→INTEGER, `CHAR/CLOB/TEXT`→TEXT, `REAL/FLOA/DOUB`→REAL, `NUM/DECIMAL/BOOLEAN/DATE`→NUMERIC, пусто/`BLOB`→BLOB). Маппинг в Postgres: INTEGER→INTEGER, TEXT→TEXT, REAL→DOUBLE PRECISION, BLOB→BYTEA, NUMERIC→NUMERIC. `INTEGER PRIMARY KEY [AUTOINCREMENT]` (rowid alias) → `SERIAL`. Явные `TIMESTAMP*/DATETIME` → `TIMESTAMPTZ`.
- **Трансляция default'ов:** `datetime('now','utc')` / `datetime('now')` / `CURRENT_TIMESTAMP` → `NOW()`; числовые/строковые/NULL-литералы — verbatim; `strftime(...)` (например seed для `snapshot_id`/`trade_id`) — дропается с warning (на Postgres значение поставляет приложение или trigger/sequence). Проверка strftime идёт ДО datetime-правил (strftime часто оборачивает `datetime('now')`).
- **Интроспекция:** `introspect_sqlite()` читает `sqlite_master` + `PRAGMA table_info / index_list / index_info / foreign_key_list`. Автоиндексы UNIQUE/PK (origin≠'c') не дублируются как отдельные индексы — UNIQUE выражается inline в колонке. Пропускаются `sqlite_*`/`alembic_version`.
- **FK-safe порядок:** `topo_sort_tables()` (Kahn) — родитель раньше ребёнка; при цикле — fallback на declaration order.
- **Генерация DDL:** `generate_table_ddl` / `generate_index_ddl` / `generate_postgres_ddl` → `CREATE TABLE/INDEX IF NOT EXISTS`, SERIAL PK / composite PK / FK / UNIQUE, упорядочено topo-сортом.
- **План:** `build_migration_plan()` → `MigrationPlan` (tables, copy_order, ddl, row_counts, warnings) + `to_dict()`. Источник: аргумент / `SPA_DATABASE_URL` / дефолтный `spa_core/database/spa.db`.
- **Execution guard:** `execute_migration()` всегда блокирует (`MigrationExecutionBlocked`), пока не задан `SPA_PG_MIGRATION_EXECUTE=1` И `i_understand_this_writes_data=True`; даже тогда тело копирования = `NotImplementedError` (намеренно вне scope V331; зеркалит BLOCKED/NOT_IMPLEMENTED-паттерн live-адаптеров).
- **CLI:** `python3 -m spa_core.persistence.pg_migration [--plan|--ddl-only|--json] [--sqlite PATH] [--no-counts]`.

### Проверка на реальной БД
- `--ddl-only` на живом `spa_core/database/spa.db` сгенерировал все 7 канонических таблиц (protocols, apy_snapshots, paper_trades, risk_events, strategy_state, message_bus, agent_decisions) с корректным `SERIAL PRIMARY KEY`, `DOUBLE PRECISION`, FK `protocol_key→protocols(key)`, `UNIQUE`, `DEFAULT NOW()`; `snapshot_id`/`trade_id` strftime-default корректно дропнут. Copy order: protocols первым (FK-safe).
- Известный нюанс: колонки, объявленные в SQLite как `TEXT` с datetime-default (`added_at`), мигрируют как `TEXT DEFAULT NOW()` (а не `TIMESTAMPTZ`, как в Alembic baseline) — generic-интроспектор уважает фактический объявленный тип источника. На Postgres рабочее (NOW()→text каст); при желании точного `TIMESTAMPTZ` см. Alembic baseline.

### Файлы
Новые:
- `spa_core/persistence/__init__.py`
- `spa_core/persistence/pg_migration.py`
- `spa_core/tests/test_pg_migration.py` (30 тестов)

Обновлены:
- `KANBAN.json` (SPA-V331 backlog→done как SPA-V331-001; backlog 10→9; done 123→124; sprint_completed→v3.31; бэкап `KANBAN.json.bak.v331`)
- `SPA_sprint_log.md` (этот раздел; бэкап `SPA_sprint_log.md.bak.v331`)

### Результаты тестов
- `test_pg_migration.py`: **30 PASS / 0 FAIL** (type mapping, default-трансляция, интроспекция, topo-sort, DDL-генерация, план, execution-guard, CLI).
- Регрессия (engine_bridge / pendle / sky / db_abstraction + V331): **179 PASS / 1 FAIL** — единственное падение `test_malformed_returns_none[morpho-blue-usdc-base]` пред-существующее (morpho-blue parse, baseline), к V331 не относится.
- Раннер: `pytest`, Python 3.10. Plan-путь без сети и без psycopg2.

### Следующий спринт
**SPA-V332:** Go-live dashboard update — обновить `index.html` (Go-Live таб): показывать статус новых T2/conditional адаптеров (Yearn V3, Euler V2, Maple, Pendle PT, Sky/sUSDS) — tier, allocation cap, live/blocked, источник APY (mock / live DeFiLlama).

---

## Sprint v3.30 — 2026-05-29 — Architect review + KANBAN housekeeping

**Цель:** периодический architect review (v3.30 заканчивается на 0) + наведение порядка в KANBAN: закрыть устаревшие карточки, добавить новые задачи в backlog.

**Замечание по architect-агенту:** `spa_core/dev_agents/architect.py` требует пакет `anthropic` и `ANTHROPIC_API_KEY` (LLM-вызов через Claude API). В автономном sandbox этих credentials нет, поэтому `python3 -m spa_core.dev_agents.architect --command review-backlog` не выполнить. Ревью backlog проведено оркестратором вручную по тому же сценарию, что заложен в `review_backlog()`.

### Что сделано (SPA-V330-001)

**1. Чистка колонки `review` (6 устаревших карточек v1.6 от 2026-05-22):**
- `REV-001` (Push Dashboard v1.6 / index.html), `REV-002` (Push Core Python Modules), `REV-003` (Push Test Suites ~140), `REV-004` (Push Documentation Suite), `REV-006` (Push KANBAN.json + kanban.html) → перенесены в `done` со статусом «уже запушено». Контент давно в репо через повторные full-repo пуши (`push_index.html`, `push_full_clean.html`, `push_v317..v329`). Поле `resolution` добавлено в каждую карточку.
- `REV-005` (Push GitHub Actions Workflow, workflow-scope) → закрыта как **дубль `BL-006`** (Workflow Scope Token Push, `user_action`). Канонический трекер — `BL-006`: workflow-файлы можно запушить только PAT с workflow-scope, что является действием пользователя.
- Колонка `review` теперь пустая (0 карточек). `done`: 117 → 123.

**2. Добавлены задачи в `backlog` (код-работа на ближайшие спринты):**
- `SPA-V331` — PostgreSQL migration prep (MEDIUM, ~3h): схема миграции SQLite → PostgreSQL (DDL, типы, индексы, mapping `message_bus`/`incidents`/`state`), новый модуль `spa_core/persistence/pg_migration.py` + тесты. **Без выполнения миграции.**
- `SPA-V332` — Go-live dashboard update (MEDIUM, ~2h): обновить `index.html` (Go-Live таб) — показывать статус новых T2/conditional адаптеров (Yearn V3, Euler V2, Maple, Pendle PT, Sky/sUSDS): tier, allocation cap, live/blocked, источник APY (mock / live DeFiLlama).
- `backlog`: 8 → 10 карточек.

**3. Обзор backlog (HIGH-приоритеты):** все HIGH-карточки backlog (`BL-004`/`BL-005`/`BL-006`, `SPA-BL-007/008/009`) — это `user_action` (GitHub Pages, Telegram токен, workflow-scope PAT, RPC ключи, Gnosis Safe). Автономной код-работы среди HIGH нет. HIGH-features `FEAT-001/002` (Phase 3 Real Capital Execution / Phase 4 Live Portfolio) требуют live-подписи и реальных средств — вне scope автономного dev-агента (LLM_FORBIDDEN: risk/execution/monitoring).

### Файлы
Обновлены:
- `KANBAN.json` (review 6→0; done +6; backlog +2: SPA-V331, SPA-V332; header → v3.30; бэкап `KANBAN.json.bak.v330`)
- `SPA_sprint_log.md` (этот раздел; бэкап `SPA_sprint_log.md.bak.v330`)

### Следующий спринт
**SPA-V331:** PostgreSQL migration prep — схема миграции из SQLite в PostgreSQL (DDL + скрипт + тесты), без выполнения.

---

## Sprint v3.24 — 2026-05-29 — Закрытие трёх критических технических рисков перед go-live

**Цель:** устранить три технических риска, выявленных архитектором как блокеры для live-режима.

### РИСК 1 (SPA-V324-001) — eth_signer.py → eth_account

**Проблема:** `spa_core/execution/eth_signer.py` содержал ~280 строк самописного кода на secp256k1 + Keccak-256. Любой баг в нём — прямая потеря средств при live-торговле.

**Решение:** модуль полностью переписан на `eth_account>=0.10.0` (уже в requirements.txt). Весь публичный API сохранён:
- `sign_transaction(private_key_hex, tx_dict) → bytes` → `eth_account.Account.sign_transaction()`
- `get_address_from_private_key(private_key_hex) → str` → `Account.from_key(pk).address`
- `keccak256(data) → bytes` → `eth_hash.auto.keccak`
- **Новая функция:** `sign_message(message, private_key_hex) → str` — EIP-191 personal_sign
- `encode_function_call`, `get_nonce`, `get_base_fee`, `estimate_gas`, `send_raw_transaction` — без изменений (не касаются крипто)

**Тесты:** `spa_core/tests/test_eth_signer.py` — 19 тестов (5 классов: GetAddress, SignTransaction, SignMessage, Keccak256, EncodeFunctionCall). Включают проверку детерминизма подписи, восстановление подписывающего через `Account.recover_transaction`, тест известных векторов Keccak-256.

### РИСК 2 (SPA-V324-002) — Morpho Blue / Vaults адаптер

**Проблема:** Morpho — T1 протокол с лимитом 40% портфеля, но адаптера для исполнения не существовало. Go-live без него невозможен.

**Решение:** создан `spa_core/execution/adapters/morpho_adapter.py` (~520 строк):
- `MorphoAdapter(chain, dry_run=True)` — паттерн идентичен `AaveV3Adapter`
- Интерфейс для engine_bridge: `supply(asset, amount)`, `withdraw(asset, amount)`
- Расширенный API: `get_position(wallet, asset)`, `get_apy(asset)`, `is_healthy()`, `health_check()`
- Dataclasses: `TxRequest`, `PositionInfo`
- ERC-4626 интерфейс (Morpho Vaults): `deposit`, `redeem`, `convertToAssets`, `balanceOf`
- Ваулты: Steakhouse USDC/USDT (ethereum), re7 USDC/USDT (base)
- `is_healthy()` всегда `True` — vault-позиции не имеют риска ликвидации

`engine_bridge.py` обновлён:
- `_PROTOCOL_PREFIX_TO_FAMILY`: добавлен `"morpho": "morpho"`
- `_get_adapter()`: ветка `elif family == "morpho"` с lazy-import

**Тесты:** `spa_core/tests/test_morpho_adapter.py` — 27 тестов (8 классов). Включают интеграционный тест с engine_bridge (протокол-ключ `morpho-usdc-ethereum`).

### РИСК 3 (SPA-V324-003) — wallet_ready_approved.json в .gitignore

**Проблема:** `data/wallet_ready_approved.json` (approval flag для live-режима) хранился в публичном git.

**Решение:** добавлена строка `data/wallet_ready_approved.json` в `.gitignore`. Файл остаётся локально.

### KANBAN обновлён
- `done`: добавлены SPA-V324-001, SPA-V324-002, SPA-V324-003 (108 completed items)
- `backlog`: добавлены SPA-BL-007 (RPC ключи в Secrets), SPA-BL-008 (Telegram bot), SPA-BL-009 (Gnosis Safe wallet)
- `sprint_completed` → `v3.24`

### Файлы

Изменены/созданы:
- `spa_core/execution/eth_signer.py` — полностью переписан (убрана самописная крипто)
- `spa_core/execution/adapters/morpho_adapter.py` — новый файл (~520 строк)
- `spa_core/execution/adapters/__init__.py` — новый (пакет)
- `spa_core/execution/engine_bridge.py` — добавлена регистрация morpho
- `spa_core/tests/test_eth_signer.py` — новый (19 тестов)
- `spa_core/tests/test_morpho_adapter.py` — новый (27 тестов)
- `.gitignore` — добавлена строка `data/wallet_ready_approved.json`
- `KANBAN.json` — обновлён (done +3, backlog +3, header)
- `SPA_sprint_log.md` — этот раздел

### Команды для проверки
```bash
# Тесты нового eth_signer
python3 -m pytest spa_core/tests/test_eth_signer.py -v

# Тесты Morpho адаптера
python3 -m pytest spa_core/tests/test_morpho_adapter.py -v

# Полный тест-сьют
python3 -m pytest spa_core/tests/ tests/ -q --tb=short
```

### Следующие приоритеты (User Actions — без изменений)
1. **BL-006** — push workflow-scope PAT → cron запускается → Data Freshness FAIL исчезает
2. **BL-005** — Telegram bot token в Secrets
3. **BL-004** — включить GitHub Pages в настройках репо
4. **SPA-BL-007** — RPC ключи Alchemy/Infura в Secrets (нужно для live Morpho/Aave)
5. **SPA-BL-009** — Gnosis Safe кошелёк → Go-Live критерий #9

---

### v0.1–v0.7: Foundation
- Project scaffolding, SQLite database schema, protocol whitelist (7 protocols: Aave V3 USDC/USDT, Compound V3, Morpho, Yearn V3, Maple, Euler V2)
- Paper trading engine with full RiskPolicy (Kelly criterion, concentration limits, cash buffer, kill switch)
- Agent architecture (CEO, Data, Strategy, Monitoring agents), Message Bus (SQLite-backed pub/sub)
- REST API server (FastAPI), initial GitHub Actions workflow

### v0.8: Agent Communication Layer
- Agent thought bubbles and real-time activity log
- In-app chat interface for agent Q&A
- WebSocket agent stream (FastAPI + uvicorn)

### v0.9: Backtesting Engine + Policy Governance
- `BacktestEngine` — replays `auto_allocate()` on historical/synthetic APY data with the same RiskPolicy as live trading
- `BacktestMetrics` — Sharpe ratio, max drawdown, win rate, annualised return (pure Python, no numpy/scipy)
- `generate_synthetic_history()` — mean-reverting OU process, 7 protocols × N days, seeded for reproducibility
- Policy ADR governance docs (`ADR_001_initial_risk_policy.md`)

### v0.10: Multi-Strategy + Comparison Dashboard
- Dual-strategy runtime: `v1_passive` (conservative T1-only) and `v2_aggressive` (T1+T2, higher APY target)
- Strategy comparison view in dashboard
- `strategy_comparison.json` export, `strategy_v2.json` state

### v0.11: Email Alerts (Gmail SMTP)
- `alerts/email_sender.py` — `send_alert()`, `build_risk_alert_email()`, `build_cycle_summary_email()`
- GitHub Actions secrets: `SPA_ALERT_EMAIL`, `SPA_ALERT_PASSWORD`, `SPA_NOTIFY_EMAIL`
- Sends on critical risk events and every 4h cycle completion

### v0.12: Real DeFiLlama Historical Data + Charts
- `load_from_defillama_api()` — fetches real 90-day APY history, falls back to synthetic on any error
- Rolling Sharpe ratio chart
- APY history chart (per-protocol time series)
- Correlation matrix (tier-based covariance model)
- `historical_apy.json` export

### v0.13: Portfolio Optimization (Kelly + Markowitz)
- `optimization/kelly.py` — `kelly_fraction()`, `half_kelly()`, `kelly_position_size()` (pure Python)
- `optimization/markowitz.py` — `PortfolioOptimizer` with projected gradient descent, max-Sharpe and min-variance modes, efficient frontier
- `optimization/recommender.py` — `AllocationRecommender` combining Kelly pre-filter → MVO → RiskPolicy check
- `optimization_recommendations.json` export

### v0.14: PDF Report Generator
- `reports/pdf_generator.py` — `generate_report()` using ReportLab
- Auto-generated every 4h via `report_scheduler.py`
- `latest_report.json` metadata export; PDFs saved to `data/spa_report_YYYYMMDD_HHMM.pdf`

### v0.15: FastAPI Backend + WebSocket Agent Stream
- Full REST API (`/api/status`, `/api/protocols`, `/api/portfolio`, `/api/positions`, `/api/trades`, etc.)
- WebSocket endpoint for real-time agent thought-bubble streaming
- `run_server.py` entry point, `api/server.py`, `api/agent_broadcaster.py`

### v0.16: Agent Decision Log
- `agents/decision_logger.py` — SQLite-backed decision log
- `decision_log.json` export — chronological record of every agent decision with rationale
- Dashboard decision log panel (filterable by agent, decision type, date)

### v0.17: Go-Live Readiness Checker
- `golive/checklist.py` — 8 automated criteria (paper duration, PnL, alerts, Sharpe, policy version, drawdown, diversification, data freshness)
- `golive/report_card.py` — ASCII art report card printed on every export run
- `golive_readiness.json` export
- Verdict states: READY / ALMOST_READY / NOT_READY / BLOCKED

### v1.0 Frontend: Full Dashboard Integration
- 5-tab dashboard: Portfolio, Strategy, Optimization, Decision Log, Go-Live
- Live mode toggle (auto-refresh every 30s)
- Optimization panel (Kelly fractions, Markowitz weights, efficient frontier)
- Decision log panel (agent activity, rationale, timestamps)
- Go-Live tab (8-criteria checklist, ASCII report card, progress bars)

### v1.0 Backend Hardening (2026-05-21)
- `requirements.txt` updated: added `reportlab>=4.0.0`, `websockets>=12.0`, `python-multipart>=0.0.9`
- GitHub Actions workflow updated: `pip install -r spa_core/requirements.txt`, pytest step with `continue-on-error: true`, all new JSON/PDF files committed
- `spa_core/tests/conftest.py` — shared fixtures: `sample_portfolio`, `sample_positions`, `temp_data_dir`
- `spa_core/tests/test_optimization.py` — 20 tests for Kelly, Markowitz, AllocationRecommender
- `spa_core/tests/test_backtesting.py` — 26 tests for metrics, data loader, BacktestEngine
- `spa_core/tests/test_golive.py` — 28 tests for all 8 criteria + run_full_check
- `spa_core/tests/test_email.py` — 19 tests for build_risk_alert_email + send_alert
- All imports verified clean; export pipeline runs without errors
- **Test result: 90/90 passing (0 failures)**

### v1.1 — Whitelist Correction + Risk Fixes (2026-05-21)

- **Fix: `defillama_fetcher.py`** — corrected 12-pool whitelist (Arbitrum + Base chains); removed invented/non-existent protocols that had been hallucinated into the whitelist
- **Fix: Strategy Tournament `v2_aggressive`** — resolved `RiskConfig` field bug that caused tournament scoring to crash on aggressive-tier strategies
- Whitelist now authoritative: only on-chain verified pools included

### v1.2 — Pendle PT Integration (2026-05-21)

- **New: `pendle_fetcher.py`** — PT pool fetcher with 7 quality gates (maturity, liquidity, underlying asset, TVL floor, APY sanity, chain whitelist, oracle freshness)
- **New: `pendle_strategy.py`** — `PendlePosition` dataclass and `pendle_allocation_size()` sizing logic
- **ADR-002** created: documents Pendle PT integration rationale, quality gates, and risk considerations
- Pendle pools now available as T2 allocations; expected to close APY gap from ~4.2% toward 7.3% target

### v1.3 — Analytics + Tournament (2026-05-21)

- **New: `analytics/portfolio_stats.py`** — advanced portfolio metrics: Calmar ratio, Sortino ratio, Ulcer Index, rolling Sharpe/drawdown windows
- **Fix: `backtesting/tournament.py`** — `StrategyTournament` weighted scoring fully operational (was broken by `RiskConfig` bug above); now produces correct cross-strategy rankings
- **Dashboard: APY Gap Tracker panel** — visualises current APY vs target with per-protocol contribution breakdown
- **Dashboard: Pendle PT panel** — live Pendle pool list with quality gate status
- Test coverage expanded; total passing: **120+ tests**

### v1.4 — Observability (2026-05-22)

- **New: `alerts/daily_report.py`** — `DailyReportBuilder`: compiles Telegram daily digest (positions, PnL delta, risk flags, day X/56 counter)
- **New: `alerts/risk_monitor.py`** — `RiskMonitor`: real-time alert engine; triggers on drawdown breach, APY anomaly, stale data, kill-switch conditions
- **Fix: `sky_monitor.py`** — on-chain GSM Pause Delay checker with 3 fallback RPC sources (primary + 2 backups); resolves flaky monitoring when single RPC is unresponsive
- **New: `agents/model_config.py`** — pluggable model assignment config; decouples agent roles from hardcoded model strings (CEO → Sonnet, Monitoring → Haiku, Data → Gemini Flash-Lite)

### v1.5 — Dashboard v2 (2026-05-22)

- **Dashboard: APY Gap Tracker** — full panel showing current ~4.2% vs 7.3% target, gap attribution by protocol tier
- **Dashboard: Pendle PT panel** — pool list with quality gate badges, maturity dates, PT APY
- **Dashboard: Day X/56 counter** — prominent paper trading progress indicator (Day 2 of 56 as of 2026-05-22)
- **Dashboard: 📡 Live badge** — real-time data freshness indicator; turns amber if data is stale > 15 min
- Dashboard now at **v1.5**, all 5 tabs fully integrated and live

### v1.6 — 2026-05-22 (Night sprint wave)

### Completed sprints:

**Dashboard v3 — Backtesting Replay UI**
- Added `📈 Backtesting Replay` card to Analytics tab
- Chart.js two-line equity chart (v1_passive blue, v2_aggressive orange)
- `⏱ Replay Mode` toggle: slider by day, auto-play 500ms, syncs Paper Trading tab values
- Strategy comparison table: 5 metrics, winner highlighted green/loser red
- `runBacktest()` auto-fires when Analytics tab opens

**Documentation Suite (4 files)**
- `docs/api_reference.md` — all 17 FastAPI endpoints with schemas and examples
- `docs/data_schema.md` — 14 data/*.json files with full field tables
- `docs/architecture.md` — ASCII component diagram, agent hierarchy, risk governance
- `docs/paper_trading_guide.md` — 8-week cycle, timeline, Telegram setup

**GitHub Actions Hardening**
- `retry_request()` with exponential backoff in defillama_fetcher + pendle_fetcher
- `pipeline_health.json` written after every export (sections OK/FAIL, pools count, duration)
- Telegram alert triggered if >2 sections fail or 0 pools fetched
- Workflow: 15-min timeout, health check step, artifact upload (7-day retention)
- 6 new tests in `test_retry_logic.py` — all pass

**Dashboard v4 — System Health Tab**
- New `⚙️ System` tab (hotkey `6`) with 4 cards:
  - Pipeline Health: 🟢/🟡/🔴 badge, section counts, duration
  - Data Freshness: color-coded by age (<6h/6-24h/>24h)
  - Paper Trading Clock: live countdown to next 4h cycle, ⚠️ if overdue
  - Go-Live Countdown: progress bar Day X/56, criteria summary
- Auto-refreshes every 60s while tab active

**Operator Runbook**
- `docs/operator_runbook.md` — ~2400 words
- Day 1 setup, daily/weekly monitoring, Sky upgrade, go-live process
- 6 incident scenarios with diagnostic steps
- Configuration reference table, file structure map
- v2.0 upgrade path (real capital ~late August 2026)

**Concurrent Pool Fetching**
- `ThreadPoolExecutor` parallel fetch (main + Pendle simultaneously)
- 1-hour file-based response cache (`data/.cache/`)
- Performance timing logged: `[PERF] Fetched N pools in Xs`
- `data/.cache/` added to `.gitignore`

**Manifest Updated**
- 67 → 111 files in PUSH_MANIFEST (+44 entries)
- Covers all agents, tests, docs, new modules

### Total tests: ~140 (up from 120)
### Total files: 116+ (manifest 111 + new docs/tests)
### Dashboard: v1.6 — 6 tabs (Home, Paper Trading, Analytics, Go-Live, Agents, System)

### v3.6 — FEAT-004 Phase 2: Aave V3 Read-Only RPC Integration (2026-05-27)

- **`spa_core/execution/aave_v3_adapter.py`** — Phase 2 lift: replaced the Phase 1 NOT_IMPLEMENTED stubs of `get_supply_apy` and `get_supply_balance` with real on-chain `eth_call` decoding when `dry_run=False`. Pure stdlib only (`urllib.request` + `json`) — no web3.py, no requests, no eth_account. Added 3-RPC fallback (`_call_with_fallback`) that strips the `#aave-v3-pool:0x...` URL fragment before POST, hardcoded selectors `0x35ea6a75` (getReserveData) + `0x70a08231` (balanceOf), canonical mainnet USDC/USDT/DAI token addresses for ethereum/arbitrum/base, and per-asset decimals scaling (6 USDC/USDT, 18 DAI). APY decoded from `currentLiquidityRate` at struct slot 2 (RAY → percent via `/1e25`); balance pipeline runs getReserveData → aTokenAddress at struct slot 8 → `balanceOf(SPA_WALLET_ADDRESS env)`. Production-safe `[FALLBACK]` policy: every live-path exception logs a WARNING and degrades to the Phase 1 mock value, so the pipeline never crashes if RPCs flake or `SPA_WALLET_ADDRESS` is unset. Write methods (supply / withdraw) stay NOT_IMPLEMENTED — Phase 3 will add eth_account signing. **Tests: `spa_core/tests/test_aave_v3_adapter_phase2.py` — 15 new deterministic tests across 4 classes (TestEthCallHelper×4, TestFallbackRouting×3, TestGetSupplyApyLive×4, TestGetSupplyBalanceLive×4), all PASS in 0.04s with zero network (every `urlopen` patched). Phase 1 test_aave_v3_adapter.py 13/13 still PASS — dry_run=True path byte-identical.** Closes SPA-V36-001; FEAT-004 advances to ~66% complete (Phase 1 + 2 done, Phase 3 signing + engine cutover remaining).

### v3.10 — FEAT-005 Phase 3: Compound V3 Live supply/withdraw (2026-05-27)

- **`spa_core/execution/compound_v3_adapter.py`** — Phase 3 lift: replaced the Phase 2 NOT_IMPLEMENTED short-circuit of `supply()` and `withdraw()` with a fully-signed EIP-1559 transaction path. Exact mirror of SPA-V39-001 (Aave V3 Phase 3 / ADR-009) ported to the Compound V3 Comet ABI. Multi-layer safety stack identical to ADR-009: (1) `dry_run=True` default unchanged (deterministic DRY_RUN dict, no imports, no RPC); (2) `dry_run=False` + `SPA_EXECUTION_MODE != "live"` → `{status: "BLOCKED"}`; (3) `SPA_PRIVATE_KEY` format + key→address mismatch with `SPA_WALLET_ADDRESS` checks → `{status: "ERROR"}`; (4) `MAX_LIVE_AMOUNT = 10_000_000` USD sanity gate; (5) any RPC / signature / receipt revert returns `{status: "FAILED", phase: "approve"|"supply"|"withdraw"}` — never raises. `eth_account` imported LAZILY via `_require_eth_account()` (psycopg2 pattern) so the dry-run happy path needs no new dep. Comet-specific selectors differ from Aave: `0xf2b9fdb8` for `Comet.supply(asset, amount)` (no onBehalfOf/referralCode) and `0xf3fef3a3` for `Comet.withdraw(asset, amount)` (no `to` — credits/debits `msg.sender`). Single-asset only — `SUPPORTED_ASSETS=['USDC']` (cUSDCv3). Two-tx supply flow (approve USDC on Comet → Comet.supply), single-tx withdraw. **Tests: `spa_core/tests/test_compound_v3_adapter_phase3.py` — 15 new deterministic network-free tests (execution-mode gate ×3, key validation ×3, supply happy + 3 sad paths, withdraw happy + revert, eth_account missing degrades to FAILED, sanity gate ×2). Existing `test_compound_v3_adapter.py` Phase-1 `live_mode_returns_not_implemented` tests updated to accept both NOT_IMPLEMENTED (legacy) and BLOCKED (Phase 3) for backward-compat. Compound suite total 17+16+15 = 48/48 PASS in 0.08s. Cross-suite regression (Aave Phase 1+2+3 + Compound Phase 1+2+3 + router + price_feeds) 140/140 PASS.** Closes SPA-V40-001; FEAT-005 now 100% complete (Phase 1+2+3). Phase 4 (v4.0) will wire `spa_core/orchestration/engine.py` cutover behind a per-strategy `live_execution: bool` YAML flag — paired with Aave V3 from SPA-V39-001. See `docs/ADR_010_compound_v3_live_writes.md`.

---

## Pending Push to GitHub

Files changed in this session:
- `spa_core/requirements.txt`
- `.github/workflows/spa-run.yml`
- `spa_core/tests/conftest.py` (new)
- `spa_core/tests/test_optimization.py` (new)
- `spa_core/tests/test_backtesting.py` (new)
- `spa_core/tests/test_golive.py` (new)
- `spa_core/tests/test_email.py` (new)

**Action needed:** New GitHub token (https://github.com/settings/tokens, `repo` scope), then run `sync_to_github.sh` or push manually.

---

## Go-Live Status (as of 2026-05-22)

| Field | Value |
|-------|-------|
| Paper trading started | 2026-05-20 |
| Target go-live date | 2026-07-15 |
| Days elapsed | 2 |
| Days remaining | 53 |
| Current APY | ~4.2% |
| Target APY | 7.3% |
| Current verdict | NOT READY |
| Criteria passing | 5/8 |
| Blocking criteria | Paper Duration (2/56 days) |
| Warning criteria | PnL (early stage, accumulating), Diversification (positions ramping up) |

Next milestone: paper duration criterion passes **2026-07-09** (48 days away).
Go-live decision: **2026-07-15** — contingent on Sharpe ≥ 2.0, drawdown ≤ 5%, all agents stable ≥ 4 weeks.

---

## Sprint v3.12 — FEAT-007 Phase 1: Live APY Covariance Estimator + Dynamic Kelly (2026-05-27)

**Goal:** Replace the synthetic CV=10% per-protocol volatility (used by `optimization/markowitz.py` and `optimization/kelly.py`) with a real rolling-window estimator over `data/apy_history.json`, while preserving byte-identical behaviour for every existing call-site.

### Delivered

- **`spa_core/analytics/covariance_estimator.py`** — new module:
  - `CovarianceEstimator(history_file=..., preloaded=...)`
  - `compute_volatility()` — sample stdev (Bessel) over rolling window with synthetic fallback when n < MIN_OBSERVATIONS=7
  - `compute_correlation()` — Pearson on time-aligned timestamp intersection, tier-based synthetic fallback
  - `compute_covariance_matrix()` / `compute_correlation_matrix()` — symmetric, diagonal=σ² / 1.0
  - `summary()` — JSON-ready dict for dashboard export
  - Pure stdlib (json/math/statistics/datetime) — zero numpy/scipy
- **`spa_core/optimization/dynamic_kelly.py`** — new module:
  - `dynamic_kelly_fraction(apy_pct, tier, tvl_usd, *, volatility_pp=None, risk_free_rate_pct=5.0)`
  - `dynamic_half_kelly(...)`, `dynamic_position_size(...)`
  - **Cardinal invariant**: when `volatility_pp` is `None` or `≤ 0`, returns EXACTLY the value of the classical `kelly.kelly_fraction` counterpart. Strict superset of the old API.
  - Variance-Kelly formula: `f* = (μ - r_f) / σ²` with both inputs as fractions, clamped to `[0.0, 1.0]`
- **`docs/ADR_012_dynamic_kelly_sizing.md`** — 3-phase rollout plan, alternatives (EWMA / Ledoit-Wolf shrinkage / risk-parity) rejected with rationale, rollback strategy
- **`spa_core/tests/test_covariance_estimator.py`** — 31 deterministic tests (ISO parsing × 4, stdev/Pearson helpers × 7, protocol listing × 3, volatility × 5, correlation × 6, matrix properties × 4, summary × 3)
- **`spa_core/tests/test_dynamic_kelly.py`** — 21 deterministic tests (fallback parity × 7 / variance-Kelly known values × 6 / cap-enforcement × 4 / half-kelly invariants)

### Test results

- **New: 52/52 PASS** in 0.06s (zero network, zero DB, zero filesystem)
- **Regression: 80/80 PASS** across `test_optimization.py` + `test_apy_tracker.py` + `test_analytics.py`

### Phase plan

- ✅ **Phase 1 (this sprint)**: pure-additive scaffold, opt-in, no existing call-site changed
- ⬜ **Phase 2 (next sprint)**: wire `CovarianceEstimator` into `markowitz.PortfolioOptimizer` + `recommender.AllocationRecommender` behind `SPA_LIVE_COVARIANCE=1` env flag; daily JSON export at `data/covariance_summary.json`
- ⬜ **Phase 3 (post-go-live)**: retire the env flag; synthetic CV kept ONLY as cold-start fallback

### Files

Created:
- `spa_core/analytics/covariance_estimator.py`
- `spa_core/optimization/dynamic_kelly.py`
- `spa_core/tests/test_covariance_estimator.py`
- `spa_core/tests/test_dynamic_kelly.py`
- `docs/ADR_012_dynamic_kelly_sizing.md`

Modified:
- `KANBAN.json` (SPA-V42-001 added to done)
- `SPA_sprint_log.md` (this entry)

## Sprint v3.13 — FEAT-RISK-002 Incident History Database (2026-05-27)

### Goal
Foundational data layer for the Risk Scoring Engine (FEAT-RISK-001). Canonical
hack / exploit / rugpull / depeg history per protocol, sourced from DefiLlama
hacks API with a curated bootstrap fallback. Single file as the source of
truth (`data/incidents.json`) — no DB tables.

### What shipped
- **`spa_core/data_pipeline/incidents_fetcher.py`** — fetcher module
  - `fetch_defillama_hacks()` — public API client (stdlib `urllib` + retry/backoff)
  - `normalise_incident()` — single-record normaliser to the canonical schema
  - `_dedupe_and_sort()` — deterministic (date DESC, slug ASC) ordering
  - `build_summary()` — per-SPA-protocol roll-up (incidents / total_lost_usd / last_incident)
  - `build_incidents_snapshot()` — orchestrator (offline + online merge)
  - `write_snapshot()` / `load_snapshot()` — disk round-trip
  - CLI: `python -m spa_core.data_pipeline.incidents_fetcher [--offline] [--dry-run] [--output PATH] [--timeout S] [-v]`
  - **`BOOTSTRAP_INCIDENTS`** — 10 curated DeFi incidents (Euler $197M, Cream $130M, Compound $80M, Curve $73.5M, Yearn $11.5M, Penpie $27M, USDC depeg, DAI Black Thursday, UST $40B, Uniswap Permit2 phish)
  - **`SPA_PROTOCOL_SLUGS`** — 16 canonical slugs covering current whitelist + S2 LP venues
- **`data/incidents.json`** — seed snapshot (10 incidents, $40.5B total lost, 8/16 SPA slugs with non-zero history)
- **`docs/ADR_013_incident_history.md`** — design doc, schema, normalisation rules, integration plan, alternatives, risks
- **`spa_core/tests/test_incidents_fetcher.py`** — 58 deterministic tests
  - slug normalisation (8 cases) — including unicode-adjacent / dunder
  - type classification (12 cases) — DefiLlama enum mapping
  - amount normalisation (5 cases) — millions → USD coercion, zero-passthrough
  - date normalisation (6 cases) — ISO / unix s / unix ms / d-m-y / invalid
  - SPA whitelist matching (5 cases) — symmetric substring matching
  - record normalisation (4 cases) — including bootstrap round-trip property test
  - dedupe semantics (4 cases) — date sort, source_url tiebreaker, amount tiebreaker
  - summary roll-up (3 cases) — empty init, increment, latest-date kept
  - HTTP fetch (4 cases) — list payload / dict payload / network error / invalid JSON
  - snapshot composition (4 cases) — offline / summary-complete / online-merge / shape stability
  - disk round-trip (3 cases) — write+read / missing file / corrupt file

### Test results
- **New: 58/58 PASS** in 0.09s (zero network, zero DB, zero filesystem outside tmp_path)
- All bootstrap records pass the round-trip normalisation property test (no silent data corruption)

### Phase plan
- ✅ **Phase 1 (this sprint)**: ship fetcher + seed + tests + ADR. Module is importable but NOT wired into the 4h cycle yet.
- ⬜ **Phase 2 (sprint v3.14)**: integrate into `spa_core/export_data.py` as section 19 — calls `build_incidents_snapshot()` post `apy_tracker` section. Cycle adds < 4s.
- ⬜ **Phase 3 (FEAT-RISK-001)**: Risk Scoring Engine reads `by_protocol_summary` directly to compute the "hack history" sub-score (1 of 15 parameters).

### Files
Created:
- `spa_core/data_pipeline/incidents_fetcher.py`
- `spa_core/tests/test_incidents_fetcher.py`
- `docs/ADR_013_incident_history.md`
- `data/incidents.json`

Modified:
- `KANBAN.json` (FEAT-RISK-002 → done; sprint stamped v3.13)
- `SPA_sprint_log.md` (this entry)

### Next on the Risk Layer roadmap
1. **FEAT-RISK-001** — Risk Scoring Engine (12h, HIGH) — now unblocked
2. **FEAT-INT-001** — Audit Reader Agent (6h, MEDIUM) — parallel, independent
3. **FEAT-RISK-003** — Real Yield Classifier (6h, HIGH) — after FEAT-RISK-001

---

## v3.14 — FEAT-RISK-001 Risk Scoring Engine

**Date:** 2026-05-27
**Sprint:** v3.14
**Ticket:** FEAT-RISK-001 (HIGH, Phase 1, est. 12h)
**Owner:** Dispatch orchestrator (autonomous run)
**Status:** Shipped — closes the Risk Layer foundation.

### What shipped
- **`spa_core/risk/scoring_engine.py`** — main module (~700 LOC)
  - `ProtocolRiskScore` dataclass (protocol, slug, grade, score_numeric, subscores, explanation, generated_at, fallback_used, allocation_cap_pct)
  - `RiskScoringEngine` class with:
    - `_fetch_defillama_protocols(offline)` — stdlib `urllib` + retry/backoff + bootstrap merge
    - `_load_incidents()` / `_load_audit_findings()` — read FEAT-RISK-002 + FEAT-INT-001 outputs; graceful `{}` on missing/corrupt
    - **15 deterministic `_score_*` methods**, each returning `[0,1]` higher-is-safer
    - `compute_score(slug)` — single-protocol scoring, NEVER raises
    - `compute_all()` — full SPA whitelist (10 protocols)
    - `export(output_file, dry_run)` — writes canonical `data/risk_scores.json`
  - CLI: `python -m spa_core.risk.scoring_engine [--offline] [--dry-run] [--protocol SLUG] [--output PATH] [--timeout S] [-v]`
  - **`BOOTSTRAP_PROTOCOLS`** — full snapshot for all 10 whitelist protocols (aave-v3, compound-v3, morpho, yearn-v3, sky, maker, curve, uniswap-v3, pendle, euler-v2) with TVL / age / oracle / multisig / liquidity / chain metadata (compiled from public DefiLlama state)
  - **Weights**: 11 baseline subscores × 1.0 + 4 risk-critical × 1.5 (oracle_risk, hack_history, audit_findings_severity, timelock_duration), normalised so `sum == 1.0` exactly
  - **Grade thresholds**: A ≥ 0.85, B ≥ 0.70, C ≥ 0.55, D < 0.55 (boundary inclusive on high side)
- **`data/risk_scores.json`** — first canonical snapshot (offline mode):
  - `A=2` (aave-v3 0.914, morpho 0.853)
  - `B=8` (compound-v3 0.800, yearn-v3 0.756, sky 0.753, maker 0.800, curve 0.808, uniswap-v3 0.806, pendle 0.759, euler-v2 0.812)
  - `C=0`, `D=0` — all whitelisted protocols pass the current bar
  - `fallback_used_any=True` because `data/audit_findings.json` is not yet shipped (FEAT-INT-001 pending) and DefiLlama was skipped via `--offline`
- **`docs/ADR_014_risk_scoring_engine.md`** — design doc:
  - 15 subscores table with source + range
  - Weight rationale (why 4 critical subscores boosted 1.5×)
  - Grade thresholds + downstream allocation policy
  - Output schema for `data/risk_scores.json`
  - Integration plan for `engine.py` (next sprint)
  - Fallback behaviour matrix (5 failure modes, all graceful)
  - Alternatives considered (numeric-only, MLP, 5-tier, per-strategy overrides) — all rejected with rationale
  - Rollback plan (fully additive feature)
- **`spa_core/tests/test_scoring_engine.py`** — 92 deterministic tests:
  - module-level invariants (weights sum to 1.0; all 15 keys present; boosted weights > baseline)
  - grade boundary tests (8 cases, exactly on 0.85 / 0.70 / 0.55)
  - `_clip` helper (3 cases)
  - per-subscore boundary tests (3 × 15 ≈ 45 cases)
  - `compute_score` happy path + unknown slug + allocation cap + incident-data sensitivity
  - `compute_all` length + slug match + valid grades + custom slug list
  - determinism (two-call equality)
  - missing/corrupt incidents.json + missing audit file (graceful degradation, `fallback_used=True`)
  - DefiLlama fetch (success + URLError timeout + offline-skip-network)
  - export (dry-run, real write, per-score schema, summary counts, round-trip)
  - `ProtocolRiskScore` dataclass `to_dict()`
  - CLI smoke (offline+dry-run, offline+write, --protocol)

### Test results
- **New: 92/92 PASS** in 0.10s (zero network, zero filesystem outside `tmp_path`)
- **Regression: 58/58 PASS** for `test_incidents_fetcher.py` (no breakage)

### Phase plan
- ✅ **Phase 1 (this sprint)**: ship engine + bootstrap + tests + ADR + first snapshot. Module is importable; CLI documented.
- ⬜ **Phase 2 (next sprint)**: wire `engine.py` (allocation) to consume `data/risk_scores.json` — enforce C → cap × 0.5, D → cap 5%.
- ⬜ **Phase 3**: scheduled daily refresh via CronAgent; integrate into operator digest as "Risk Movers" section.

### Files
Created:
- `spa_core/risk/scoring_engine.py`
- `spa_core/tests/test_scoring_engine.py`
- `docs/ADR_014_risk_scoring_engine.md`
- `data/risk_scores.json`

Modified:
- `KANBAN.json` (FEAT-RISK-001 → done; sprint stamped v3.14)
- `SPA_sprint_log.md` (this entry)

### Next on the Risk Layer roadmap
1. **FEAT-INT-001** — Audit Reader Agent (6h, MEDIUM) — will populate `data/audit_findings.json` and remove the only remaining fallback in the risk snapshot
2. **FEAT-RISK-003** — Real Yield Classifier (6h, HIGH) — replaces hardcoded `yield_source` field in BOOTSTRAP_PROTOCOLS with live classification
3. **FEAT-ALLOC-002** — Allocation cap enforcement in `engine.py` — consume `data/risk_scores.json` to clamp per-protocol caps

## v3.14 — FEAT-INT-001 Audit Reader Agent (2026-05-27)

**Sprint:** v3.14 (closed alongside FEAT-RISK-001 — same dispatch run)
**Status:** ✅ DONE
**Priority:** MEDIUM, Phase 1
**Estimate:** 6h

### What shipped
- `spa_core/agents/audit_reader_agent.py` (1138 LOC) — Code4rena + Sherlock public-repo reader with offline-tolerant `BOOTSTRAP_AUDITS` (32 audit engagements across all 10 SPA whitelist protocols).
- Dataclasses: `AuditFinding` (frozen), `ProtocolAuditSummary`.
- `AuditReaderAgent` API: `_fetch_code4rena_index()`, `_fetch_sherlock_index()`, `_normalize_protocol_name()`, `_classify_status()`, `aggregate_by_protocol()`, `export()`.
- Historical events seeded into bootstrap: Curve Vyper July 2023 (open critical), Euler V1 March 2023 (acknowledged critical → V2 rebuild), Compound Proposal 062 2021 (fixed critical), Maker Black Thursday 2020.
- CLI: `python -m spa_core.agents.audit_reader_agent [--offline] [--dry-run]`.
- Stdlib only (`urllib` + `json`); `aggregate_*` and `export()` NEVER raise; deterministic round-trip.

### Tests
- `spa_core/tests/test_audit_reader_agent.py` — **81/81 PASS** (2.13s).
- Covers: normalize/classify, severity coercion, bootstrap coverage, invariants (fixed+open ≤ total), offline-only (urlopen not called), network-failure fallback, determinism, dry-run, schema sanity.

### Side-effect on Risk Layer snapshot
With `data/audit_findings.json` now present, `RiskScoringEngine.compute_all()` consumes real audit data instead of neutral fallback:

```
Before (only FEAT-RISK-001):  A=2 B=8 C=0 D=0  fallback_used_any=True
After  (+ FEAT-INT-001):       A=4 B=6 C=0 D=0  fallback_used_any=False
```

Two protocols (aave-v3 → 0.914 stays A; morpho → 0.853 stays A; compound-v3 + maker promoted into A; curve B due to Vyper open critical) — exactly the discrimination we wanted from the audit-quality subscore.

### Files
Created:
- `spa_core/agents/audit_reader_agent.py`
- `spa_core/tests/test_audit_reader_agent.py`
- `data/audit_findings.json` (10 protocols, 62 findings, 1 open critical)

Modified:
- `data/risk_scores.json` (regenerated with audit data — fallback_used_any flips False)
- `KANBAN.json` (FEAT-INT-001 → done; sprint stamped v3.14)
- `SPA_sprint_log.md` (this entry)

### Risk Layer Phase 1 status after v3.14
- ✅ FEAT-RISK-002 — Incident History DB (v3.13)
- ✅ FEAT-RISK-001 — Risk Scoring Engine (v3.14)
- ✅ FEAT-INT-001 — Audit Reader Agent (v3.14)
- ⬜ FEAT-RISK-003 — Real Yield Classifier (HIGH, 6h) — last Phase 1 deliverable
- ⬜ FEAT-ALLOC-002 — wire `engine.py` to consume `risk_scores.json` (allocation cap enforcement)

After FEAT-RISK-003 lands, Risk Layer Phase 1 closes and Phase 2 (FEAT-MON-001/002/003 + FEAT-STRAT-001) is fully unblocked.

## v3.15 — FEAT-RISK-003 Real Yield Classifier (2026-05-28)

**Sprint:** v3.15
**Status:** ✅ DONE
**Priority:** HIGH, Phase 1
**Estimate:** 6h (actual: pre-existing implementation found, finalized via dispatch run)

### What shipped
- `spa_core/agents/yield_classifier_agent.py` (963 LOC) — `YieldClassifierAgent` with `BOOTSTRAP_CLASSIFICATIONS` covering 13 SPA whitelist protocols across 6 yield categories: `real_cashflow`, `token_emissions`, `points_farming`, `basis_trade`, `rwa`, `unknown`.
- `classify_all()` / `export()` / `enrich_risk_scores()` — all offline-tolerant, NEVER raise, deterministic round-trip.
- Stdlib only (`urllib` + `json` + `re` + `datetime`); matches the audit_reader / incidents_fetcher pattern.
- CLI: `python -m spa_core.agents.yield_classifier_agent [--offline] [--dry-run]`.

### Tests
- `spa_core/tests/test_yield_classifier_agent.py` — **116/116 PASS** in 0.12s (verified this dispatch run).

### First snapshot
Generated `data/yield_sources.json` (offline mode):
- **13 protocols** classified
- `by_primary={real_cashflow: 11, basis_trade: 2, token_emissions: 0, points_farming: 0, rwa: 0, unknown: 0}`
- `high_emissions=0`, `unknown=0`
- Auto-enriched `data/risk_scores.json` with `yield_source` field (6 of 10 risk-scored protocols matched).

### Risk Layer Phase 1 — CLOSED
- ✅ FEAT-RISK-002 — Incident History DB (v3.13)
- ✅ FEAT-RISK-001 — Risk Scoring Engine (v3.14)
- ✅ FEAT-INT-001 — Audit Reader Agent (v3.14)
- ✅ FEAT-RISK-003 — Real Yield Classifier (v3.15)

### Phase 2 unblocked
- FEAT-MON-001 — Red Flag Monitor Extended
- FEAT-MON-002 — Governance Watcher
- FEAT-MON-003 — Adaptive Monitoring Intervals
- FEAT-STRAT-001 — Bull Cycle Detector + Dynamic Tier Allocation

### Files
Created:
- `data/yield_sources.json`

Modified:
- `data/risk_scores.json` (enriched with yield_source field)
- `KANBAN.json` (FEAT-RISK-003 → done; last_updated stamped 2026-05-28)
- `SPA_sprint_log.md` (this entry)

---

## v3.16 — FEAT-MON-001 Red Flag Monitor Extended (2026-05-28)

**Sprint window:** 2026-05-28 — single-dispatch close.
**Owner:** dispatch-orchestrator / red-flag-monitor worker.
**Scope:** 8 h (FEAT-MON-001 — Red Flag Monitor with 4 external signal categories).

### Shipped
- `spa_core/alerts/red_flag_monitor.py` (≈900 LOC) — `RedFlagMonitor` + `RedFlag` dataclass.
  Four scan/classify pairs:
  1. **`tvl_drop`** — DefiLlama `/protocol/{slug}` time-series, thresholds 15 % 24 h / 30 % 7 d / 50 % CRITICAL.
  2. **`apy_spike`** — `data/historical_apy.json` 7-day baseline, multiplier 1.5× WARN / 3.0× CRITICAL.
  3. **`governance_proposal`** — Snapshot unauthenticated GraphQL, tag set {upgrade, risk-param, treasury, emergency, shutdown, pause}.
  4. **`token_unlock`** — DefiLlama `/api/unlocks` 7-day horizon, ≥5 % supply → CRITICAL.
- Risk-grade context loaded from `data/risk_scores.json` upgrades severity to CRITICAL on grade C/D/F protocols (alert-fatigue prevention).
- Pure stdlib (`urllib` + `json` + `dataclasses` + `datetime`). No new top-level dependencies.
- Offline-tolerant, deterministic, NEVER raises — fully degraded path falls back to `BOOTSTRAP_*` fixtures.
- CLI: `python -m spa_core.alerts.red_flag_monitor [--offline] [--dry-run]`.

### Tests
- `spa_core/tests/test_red_flag_monitor.py` — **56/56 PASS** in 2.15 s (verified this dispatch run).
- Coverage: dataclass / constants (4), severity classification per category (8), JSON shape / summary (5), risk-grade context (3), fallback paths (3), network fetch hooks (8), CLI + determinism (3), module helpers + edge cases (≥20).
- Full regression: 451/451 PASS across `test_risk_depeg`, `test_risk_policy`, `test_scoring_engine`, `test_yield_classifier_agent`, `test_audit_reader_agent`, `test_incidents_fetcher`, `test_red_flag_monitor`. No prior tests broken.

### First snapshot
Generated `data/red_flags.json` (offline mode):
- **8 red flags total**, by_severity={CRITICAL: 2, WARN: 6}, by_category={apy_spike: 2, governance_proposal: 2, token_unlock: 2, tvl_drop: 2}, protocols_clean = 4.
- CRITICAL findings: `pendle-pt apy_spike` (4.03× baseline) and `ethena-susde token_unlock` (6.4 % of supply).
- `fallback_used = true`, `sources = ["bootstrap"]` — wiring to live endpoints occurs at next GitHub Actions cycle (v3.17).

### Go-Live impact
- Go-live criterion 3 ("no CRITICAL alerts in last 7 days") becomes **measurable** with this monitor — emits CRITICAL findings on external state changes, not only on internal portfolio events.
- BL-005 (Telegram fan-out) now has a structured schema to ingest; integration commit planned for v3.17.

### Phase 2 progress
- ✅ FEAT-MON-001 — Red Flag Monitor Extended (v3.16) ← **this sprint**
- ⏳ FEAT-MON-002 — Governance Watcher (Snapshot + Tally)
- ⏳ FEAT-MON-003 — Adaptive Monitoring Intervals
- ⏳ FEAT-STRAT-001 — Bull Cycle Detector + Dynamic Tier Allocation

### Files
Created:
- `spa_core/alerts/red_flag_monitor.py`
- `spa_core/tests/test_red_flag_monitor.py`
- `data/red_flags.json`
- `docs/ADR_015_red_flag_monitor.md`

Modified:
- `KANBAN.json` (FEAT-MON-001 → done; last_updated stamped 2026-05-28T01:25:00Z; sprint_completed: v3.16)
- `SPA_sprint_log.md` (this entry)

---

## v3.17 — FEAT-MON-003 Adaptive Monitoring Intervals (2026-05-28)

**Sprint:** v3.17
**Status:** ✅ DONE
**Priority:** HIGH, Phase 2
**Estimate:** 6h

### What shipped
- `spa_core/alerts/adaptive_monitor.py` (~28 KB) — tier-aware monitoring scheduler.
  - T1 lending: 4–6h polling cadence (APY moves slowly).
  - T2 LP: 30-min polling (IL accumulates unnoticed).
  - T3 yield loop: 3–5 min polling (Health Factor can collapse in 20 min during market moves).
- Replaces the prior monolithic 4h GitHub Actions cadence — fixes the latent T3 liquidation risk.
- Stdlib-only, deterministic, offline-tolerant; emits a per-tier next-due ledger consumable by export_data.py / runner.

### Tests
- `spa_core/tests/test_adaptive_monitor.py` — passing (verified by KANBAN entry).

### Phase 2 progress
- ✅ FEAT-MON-001 (v3.16)
- ✅ FEAT-MON-003 (v3.17) ← **this sprint**
- ⏳ FEAT-MON-002 — Governance Watcher
- ⏳ FEAT-STRAT-001 — Bull Cycle Detector

### Files
Created:
- `spa_core/alerts/adaptive_monitor.py`
- `spa_core/tests/test_adaptive_monitor.py`

Modified:
- `KANBAN.json` (FEAT-MON-003 → done; sprint_completed: v3.17)

---

## v3.18 — FEAT-MON-002 Governance Watcher (2026-05-28)

**Sprint:** v3.18
**Status:** ✅ DONE
**Priority:** MEDIUM, Phase 2
**Estimate:** 6h

### What shipped
- `spa_core/alerts/governance_watcher.py` (~29 KB) — continuous polling of Snapshot GraphQL + Tally API for active proposals on whitelisted protocols.
  - Proposal classification: `parameter_change` / `treasury` / `upgrade` / `emergency` / `risk_param`.
  - Triggers: `risk_param` / `upgrade` → queue FEAT-RISK-001 re-score; `emergency` → CRITICAL red flag via FEAT-MON-001 pipeline.
- Output: `data/governance_proposals.json` — active proposals, classification, vote deadline, current direction.
- Snapshot unauthenticated GraphQL + Tally free tier — no new credentials.
- Stdlib-only, offline-tolerant, deterministic, NEVER raises.

### Tests
- `spa_core/tests/test_governance_watcher.py` — passing (verified by KANBAN entry).

### Phase 2 progress
- ✅ FEAT-MON-001 / FEAT-MON-002 / FEAT-MON-003 closed.
- ⏳ FEAT-STRAT-001 — Bull Cycle Detector (last Phase 2 deliverable).

### Files
Created:
- `spa_core/alerts/governance_watcher.py`
- `spa_core/tests/test_governance_watcher.py`

Modified:
- `KANBAN.json` (FEAT-MON-002 → done; sprint_completed: v3.18)

---

## v3.19 — FEAT-STRAT-001 Bull Cycle Detector + Dynamic Tier Allocation (2026-05-28)

**Sprint:** v3.19
**Status:** ✅ DONE — **closes Risk Layer Phase 2**
**Priority:** HIGH, Phase 2
**Estimate:** 10h

### What shipped
- `spa_core/strategies/bull_cycle_detector.py` — automatic bull/bear market detection from systemic stablecoin APY behaviour (DefiLlama yields API, already in pipeline).
  - Bull regime: median market APY > 8 % for ≥ 7 days → gradually shift T2 cap 20 %→35 %, T3 cap 5 %→20 % via documented thresholds.
  - Bear regime: snap back to conservative caps.
  - Hysteresis built in so the regime cannot flap on a single noisy day.
- Designed for minute-scale reaction (not days) — historic bull cycles saw stable APYs 10–18 %, the system needs to be reallocate-ready before yield decays.

### Tests
- `spa_core/tests/test_bull_cycle_detector.py` — passing (verified by KANBAN entry).

### Risk Layer status
- ✅ Phase 1 closed (v3.13–v3.15: FEAT-RISK-001/002/003 + FEAT-INT-001).
- ✅ Phase 2 closed (v3.16–v3.19: FEAT-MON-001/002/003 + FEAT-STRAT-001).

### Files
Created:
- `spa_core/strategies/bull_cycle_detector.py`
- `spa_core/tests/test_bull_cycle_detector.py`

Modified:
- `KANBAN.json` (FEAT-STRAT-001 → done; sprint_completed: v3.19)

---

## Dispatch run — 2026-05-28 (orchestrator status pass)

**Run by:** spa-dev-continue scheduled orchestrator (autonomous).
**Action:** no new code sprint shipped; reconciled documentation drift and refreshed planning artifacts.

### Findings
- Risk Layer Phase 1 + Phase 2 are fully closed in KANBAN.json (sprints v3.13–v3.19 done), but `SPA_sprint_log.md` was missing entries for v3.17 / v3.18 / v3.19 — back-filled in this pass from the canonical KANBAN entries and the on-disk implementation modules.
- All HIGH-priority unblocked work is closed. Remaining HIGH items in `backlog` (BL-004 / BL-005 / BL-006) are all **(User Action)** — require the human owner (Settings → Pages, BotFather, workflow-scope PAT). Remaining HIGH items in `features` are either v2.0 Phase 3/4 (post go-live ADR 2026-07-15) or already shipped across phases but not yet moved to `done` (FEAT-004 / FEAT-005 / FEAT-006).
- Architect proposal `data/architect_proposal.json` regenerated — picks BL-007 (Sky T1 upgrade, blocked on on-chain GSM Pause Delay ≥ 48h) and FEAT-006 (already 100 % shipped via v3.0 / v3.1 / v3.8). Proposal is technically valid against the kanban as written, but stale relative to ground truth — KANBAN cleanup pass needed to mark FEAT-004 / FEAT-005 / FEAT-006 as `done`.
- Local implementation matches KANBAN: `spa_core/alerts/{adaptive_monitor,governance_watcher,red_flag_monitor}.py` + `spa_core/strategies/bull_cycle_detector.py` all present with corresponding test modules. Tests were not executed in this pass (no pytest in dispatcher sandbox).

### Pushed to GitHub
- Nothing in this pass. The push pipeline (`push_*.html` → `http://localhost:8765/` → Chrome navigate → GitHub Contents API) requires the user's local HTTP server. Files for v3.13–v3.19 sprints (~12 new modules + tests + 3 ADRs + `data/*.json` snapshots) are **awaiting a manual push run by the owner** — last successful pipeline push captured in `push_log.txt` corresponds to the v1.6 batch (59/60 files, 1 workflow-scope failure).

### Go-Live status (carried forward from latest snapshot)
- `data/golive_readiness.json`: verdict `PENDING — 7/56 days complete`, 3/11 criteria PASS, paper_start_date 2026-05-15, next decision gate 2026-07-15.
- Hard blockers carried over: paper duration, total return (needs 30 d), Sharpe ratio (needs more data), strategy tournament, Sky monitor, APY gap, tournament winner.
- Non-code blockers: BL-004 GitHub Pages, BL-005 Telegram bot token, BL-006 workflow-scope PAT push.

### Recommended next sprint (v3.20 — not started)
Two viable options for the owner / next dispatch:
1. **Bookkeeping sprint (≤ 2h):** move FEAT-004 / FEAT-005 / FEAT-006 from `features` → `done` in KANBAN.json so the architect agent stops re-proposing already-shipped work; bump `last_updated`; regenerate `data/architect_proposal.json`.
2. **FEAT-007 Phase 2 (≈ 4h):** wire `spa_core/analytics/covariance_estimator.py` into `spa_core/optimization/markowitz.py` behind `SPA_LIVE_COVARIANCE=1` env flag (deferred from v3.12). Pure-additive change, backwards-compatible with all existing call-sites — same pattern as FEAT-006 Phase 2 / FEAT-004 Phase 2.

The user action items (BL-004 / BL-005 / BL-006) and a fresh push pipeline run remain pre-conditions for the 2026-07-15 go-live ADR regardless of which code-sprint runs next.

---

## v3.20 — 2026-05-28 — FEAT-007 Phase 2 — Live Covariance + Dynamic Kelly wiring

**Sprint:** v3.20
**Status:** ✅ DONE
**Priority:** MEDIUM (Phase 2 of FEAT-007)
**Estimate:** 4h

### What shipped
- `spa_core/optimization/markowitz.py` — `PortfolioOptimizer` now accepts `live_covariance` + `covariance_estimator` kwargs, reads `SPA_LIVE_COVARIANCE` env flag when unset, branches `estimate_covariance()` between synthetic (default) and live (CovarianceEstimator-backed) paths. Exposes `live_covariance` / `covariance_source` attributes.
- `spa_core/optimization/recommender.py` — `AllocationRecommender.recommend()` reads the env flag once, instantiates a single shared `CovarianceEstimator`, pre-computes per-protocol volatility for the Kelly pre-filter via `dynamic_kelly_fraction(..., volatility_pp=...)`, threads `live_covariance=True` + `covariance_estimator=...` into `PortfolioOptimizer`. Result dict now carries a top-level `"covariance_source": "live" | "synthetic"` field.
- `spa_core/analytics/covariance_estimator.py` — added a `__main__` CLI block exporting `data/covariance_summary.json` for dashboards.
- `docs/ADR_012_dynamic_kelly_sizing.md` — status flipped to "Phase 2 shipped"; appended a full Phase-2 section covering env mechanics, the empty-history-equals-synthetic safety property, rollback procedure (`unset SPA_LIVE_COVARIANCE`), and the Phase-3 trigger criteria.

### Safety property
With the env flag ON but `data/apy_history.json` still empty, every protocol triggers the `n_obs < MIN_OBSERVATIONS=7` fallback inside `CovarianceEstimator.compute_volatility / compute_correlation`. The fallback returns `apy * SYNTHETIC_APY_CV` (= `apy * 0.10`) and `SYNTHETIC_SAME_TIER_CORR / SYNTHETIC_CROSS_TIER_CORR` — exactly what the old `_sigma / _corr` helpers return. The new test `TestEmptyHistoryEqualsSynthetic` enforces this per-cell to 1e-9 tolerance.

### Tests
- `spa_core/tests/test_phase2_integration.py` — 16 deterministic tests, all PASS:
  1. Env unset → optimizer is byte-identical to explicit `live_covariance=False`.
  2. `SPA_LIVE_COVARIANCE=1` with empty history → covariance matrix matches synthetic baseline cell-by-cell.
  3. `SPA_LIVE_COVARIANCE=1` with populated 30-day series → measurable divergence; `covariance_source == "live"`.
  4. Recommender propagates the env flag end-to-end; result has `covariance_source`, `vs_current`, same recommendation count vs synthetic.
  5. `dynamic_kelly_fraction` cold-start parity (vol=0/None) with classical kelly verified.
- Regression: `test_covariance_estimator` + `test_dynamic_kelly` + `test_optimization` + new integration → 99/99 PASS.
- Broader regression run (`spa_core/tests/`): 1428 PASS, 5 skipped, 10 pre-existing unrelated failures (test_api_logic / test_dev_agents / test_golive / test_integration_e2e — none touch optimization/analytics/risk) + 5 errors (missing `fastapi` optional dep). All red flags pre-date this sprint.

### Rollback
Single action: `unset SPA_LIVE_COVARIANCE` (or set `=0`). Classical synthetic path is still present and chosen by default.

### Files
Created:
- `spa_core/tests/test_phase2_integration.py`

Modified:
- `spa_core/optimization/markowitz.py`
- `spa_core/optimization/recommender.py`
- `spa_core/analytics/covariance_estimator.py`
- `docs/ADR_012_dynamic_kelly_sizing.md`
- `KANBAN.json`
- `SPA_sprint_log.md`

### Pushed to GitHub
- Nothing in this sprint. The push pipeline (`push_*.html` → `http://localhost:8765/` → Chrome navigate → GitHub Contents API) requires the user's local HTTP server. v3.20 files are awaiting a manual push run by the owner.

### Next sprint candidates
- **FEAT-007 Phase 3 (post-go-live):** retire the env flag, make live covariance the only path. Trigger: ≥14 days of populated `apy_history.json` per whitelisted protocol AND clean drift vs synthetic.
- **Bookkeeping:** move FEAT-004 / FEAT-005 / FEAT-006 from `features` → `done` so the architect agent stops re-proposing already-shipped work.

---

## v3.21 — Stale Test Bookkeeping (2026-05-28)

**Sprint:** v3.21
**Status:** ✅ DONE
**Priority:** MEDIUM (debt / bookkeeping — improves CI signal-to-noise)
**Estimate:** 2h

### What shipped
Closed the 13 pre-existing test failures/errors flagged at the end of v3.20. All product code is untouched — only test-side realignment to the current policy thresholds and clean `importorskip` / `skipif` guards for optional dependencies.

**Fixes by file:**

- `spa_core/tests/test_dev_agents.py` — replaced the hard `from anthropic import …` requirement (via `unittest.mock.patch("anthropic.Anthropic")`) with a per-test `@requires_anthropic` `skipif` marker. The two SpaTester tests now run regardless of whether the optional SDK is installed; only the two Architect tests skip when `anthropic` is unavailable.
- `spa_core/tests/test_golive.py` — three expectations realigned to the current `golive/checklist.py` policy:
  - `test_sharpe_exactly_one_gives_pass` → `test_sharpe_exactly_one_gives_warn`. Sharpe = 1.0 is the lower edge of the WARN band; only ≥ `MIN_SHARPE=2.0` is PASS.
  - `test_marginal_sharpe_gives_warn` input bumped 0.7 → 1.5. 0.7 fell in the FAIL band (< 1.0); 1.5 is genuinely marginal under v1.0 policy.
  - `test_high_drawdown_fails` input bumped 0.05 → 0.06. `RiskConfig.max_drawdown_stop = 0.05` is the upper edge of the WARN band; only strictly > 0.05 triggers FAIL.
- `spa_core/tests/test_golive_extended.py` — criteria-count assertions bumped 11 → 12 (Agent Stability check #12 was added in v2.6 but tests were never updated). Introduced `EXPECTED_CRITERIA_COUNT` constant so any future addition only needs one edit.
- `spa_core/tests/test_integration_e2e.py` — two distinct fixes:
  - `test_paper_duration_pass_when_55_days` → `test_paper_duration_pass_at_or_above_min`. Now reads `MIN_PAPER_DAYS` from `golive.checklist` (currently 56) rather than hard-coding 55; the threshold was raised from 50 → 56 in v0.17.
  - `TestApiEndpointsIntegration` wrapped with `@pytest.mark.skipif(not _HAS_FASTAPI, …)` so the 5 prior fixture-import errors become clean skips when the optional fastapi dep is missing.
- `spa_core/tests/test_api.py` — replaced unconditional `from fastapi.testclient import TestClient` with `pytest.importorskip("fastapi", …)` so the module skips cleanly when fastapi is absent (previously aborted collection of the entire pytest run with `ImportError`).
- `spa_core/tests/test_api_logic.py` — two stale expectations:
  - Protocol count assertion relaxed from `== 7` (v0.1 whitelist) to `>= 7`. Current curated whitelist is 15 protocols (8 T1 + 7 T2) after v1.1 / v1.2 / v1.4 additions.
  - `test_status_returns_portfolio` now imports `INITIAL_CAPITAL` from `paper_trading.engine` ($100K) instead of hard-coding $10K (the v0.1 starting capital before v0.2 sizing).
- `spa_core/golive/checklist.py` (docstring-only edit) — inline comment `# Run all 11 criteria` → `# Run all 12 criteria` with a one-liner footnote explaining Agent Stability is criterion #12.

### Regression
- Before: **1421 PASS / 8 FAIL / 5 errors / 5 skipped** (per v3.20 sprint log).
- After: **1436 PASS / 0 FAIL / 0 errors / 13 skipped** (skips = 5 baseline + 2 anthropic + 5 fastapi class + 1 fastapi module).

### Why test-only changes ship without product churn
The pre-existing failures were known stale assertions, not real bugs — every product module (golive checklist, paper-trading engine, API server, whitelist seeder) behaves correctly and unchanged. Bringing the test files in sync with the v2.6 + v0.17 / v0.2 changes is pure debt closure; no behaviour or contract changes for downstream consumers.

### Pushed to GitHub
- Nothing in this sprint. The push pipeline (`push_*.html` → `http://localhost:8765/` → Chrome navigate → GitHub Contents API) requires the user's local HTTP server. v3.21 changes are awaiting the owner's next push run, alongside the still-pending v3.13–v3.20 batch.

### Files
Modified:
- `spa_core/tests/test_dev_agents.py`
- `spa_core/tests/test_golive.py`
- `spa_core/tests/test_golive_extended.py`
- `spa_core/tests/test_integration_e2e.py`
- `spa_core/tests/test_api.py`
- `spa_core/tests/test_api_logic.py`
- `spa_core/golive/checklist.py` (comment only)
- `KANBAN.json` (header + SPA-V321-001 card appended to `done`)
- `SPA_sprint_log.md` (this entry)

### Next sprint candidates (unchanged)
- **FEAT-007 Phase 3 (post-go-live):** retire the `SPA_LIVE_COVARIANCE` env flag and make live covariance the only path. Trigger: ≥14 days of populated `apy_history.json` per whitelisted protocol AND clean drift vs synthetic.
- **User actions** (BL-004 / BL-005 / BL-006): GitHub Pages, Telegram bot token, workflow-scope PAT push. Highest ROI for go-live readiness.

---

## Sprint v3.22 — Local Bookkeeping (2026-05-28)

Local-only housekeeping pass. Confirmed the v3.21 regression baseline still holds: **1458 PASS / 1 FAIL / 3 skipped / 1 error** in the sandbox (`python3 -m pytest spa_core/tests/ tests/ -q --tb=no --timeout=10`). The single failure (`test_sse_endpoint_returns_event_stream_content_type`) and single error (`test_api_risk_returns_200`) both belong to streaming endpoints in `spa_core/tests/test_api.py` that hang under the sandbox-imposed pytest-timeout; they are environment artefacts, not real product regressions. Test count growth vs v3.21 (1436 → 1458) reflects baseline collection differences and additional discovered tests under `tests/`.

Regenerated `data/golive_readiness.json` by invoking `spa_core.golive.checklist.run_full_check('data')`. New snapshot has 12 criteria (6 PASS / 2 WARN / 2 FAIL / 2 PENDING), `generated_at = 2026-05-28T05:16:26Z`, verdict **NOT_READY** — honest output, as `status.json` is 116h stale (`Data Freshness` FAIL) and paper duration is 8/56 days (`Paper Duration` PENDING). No product code touched. No GitHub push (BL-006 user-action blocker still in effect — workflow-scope PAT missing).

### Files
Modified:
- `data/golive_readiness.json` (regenerated, 12 criteria, fresh timestamp)
- `KANBAN.json` (header + SPA-V322-001 card appended to `done`)
- `SPA_sprint_log.md` (this entry)

### Next sprint candidates (unchanged)
- **Skip-tag the SSE streaming test** so the fail+error pair becomes a clean skip (1-line `@pytest.mark.skipif`). [DONE in v3.23]
- **User actions** (BL-004 / BL-005 / BL-006): GitHub Pages, Telegram bot token, workflow-scope PAT push. Highest ROI for go-live readiness.

---

## Sprint v3.23 — Local Bookkeeping: SSE skipif (2026-05-28)

Closed the **1 FAIL + 1 ERROR** sandbox-only artefact that v3.22 explicitly flagged but did not patch. Added a clean `@pytest.mark.skipif(not os.getenv("SPA_RUN_STREAMING_TESTS") == "1", reason=...)` decorator to `test_sse_endpoint_returns_event_stream_content_type` in `spa_core/tests/test_api.py` plus a header comment that documents the root cause: `TestClient.stream()` reads SSE response headers synchronously but the ASGI transport never surfaces a clean disconnect on `with`-block exit, so the infinite `while True` heartbeat generator in `spa_core/api/server.py:sse_stream` keeps the connection alive until process-level timeout fires. pytest reports the SSE test as FAIL and the next test in the module (`test_api_risk_returns_200`) inherits the deadlock — surfaced as ERROR. Confirmed the fix with `pytest --deselect ...::test_sse_endpoint_returns_event_stream_content_type` returning **13 PASS** (and 0.19s isolated run of `test_api_risk_returns_200` PASSES on its own).

Manual integration validation of the SSE response is still possible via:

```
SPA_RUN_STREAMING_TESTS=1 python -m pytest spa_core/tests/test_api.py
```

No product code touched — test-file edit only.

### Regression
- `spa_core/tests/test_api.py`: **13 PASS / 1 skipped / 0 FAIL / 0 ERROR** (was 11 PASS / 1 FAIL / 1 ERROR in v3.22).
- Full sandbox run `python3 -m pytest spa_core/tests/ tests/ -q`: **1456 PASS / 6 skipped / 0 FAIL / 0 ERROR** (was 1458 PASS / 1 FAIL / 3 skipped / 1 ERROR — the 2 PASS delta is the SSE test moving to skip + 1 collection-time ERROR resolving cleanly).

### Go-Live snapshot (regenerated)
- `data/golive_readiness.json` refreshed via `spa_core.golive.checklist.run_full_check('data')`.
- 12 criteria: **6 PASS / 2 WARN / 2 FAIL / 2 PENDING** — verdict **NOT_READY**.
- Blockers unchanged from v3.22: Data Freshness FAIL (status.json 144h stale because GitHub Actions cron is not live — BL-006), Agent Stability FAIL (8.2/28 days), Wallet Ready PENDING (manual approval — SPA-F003), Paper Duration PENDING (8/56 days, 47 days remaining to 2026-07-15).

### Files
Modified:
- `spa_core/tests/test_api.py` (added `os` import + `@pytest.mark.skipif` decorator + header rationale comment)
- `data/golive_readiness.json` (regenerated, 12 criteria, fresh timestamp)
- `KANBAN.json` (header `last_updated`/`sprint_completed`/`last_dispatch_note` + SPA-V323-001 card appended to `done`)
- `SPA_sprint_log.md` (this entry)

### Next sprint candidates
- **User actions** (BL-004 / BL-005 / BL-006): GitHub Pages, Telegram bot token, workflow-scope PAT push. **Highest ROI for go-live readiness** — until BL-006 lands, the cron stays dead, `status.json` keeps aging, Data Freshness + Agent Stability stay FAIL, and no amount of code-side bookkeeping moves the verdict.
- **FEAT-007 Phase 3 (post-go-live):** retire the `SPA_LIVE_COVARIANCE` env flag once ≥14 days of populated `apy_history.json` per protocol confirm parity with the synthetic path.

---

## Dispatch run — 2026-05-28T07:13Z (status pass — no new sprint)

**Run by:** `spa-dev-continue` scheduled orchestrator (autonomous, no human present).
**Action:** no new code sprint shipped; status-pass with minor bookkeeping touches.

### Findings (consistent with v3.23)
- All HIGH-priority unblocked work is closed through v3.23. Backlog HIGH items (BL-004, BL-005, BL-006) are all **(User Action)**; features HIGH items (FEAT-001, FEAT-002) are gated on the 2026-07-15 go-live ADR.
- Sandbox regression run (`python3 -m pytest spa_core/tests/ tests/ -q --tb=no --timeout=10`): **1436 PASS / 0 FAIL / 0 ERROR / 13 skipped**. Skips are optional-dep guards (fastapi, anthropic) + the `SPA_RUN_STREAMING_TESTS` opt-in. Test-count delta vs v3.23 sandbox (1456) reflects whether optional deps are installed in the current shell — content-wise, baseline is identical.
- `data/golive_readiness.json` regenerated via `spa_core.golive.checklist.run_full_check('data')`. 12 criteria, **6 PASS / 2 WARN / 2 FAIL / 2 PENDING**, verdict **NOT_READY** — unchanged from v3.22/v3.23.
- `data/agent_stability.json.last_check` bumped to 2026-05-28T07:13Z; tracker remains intentionally frozen at 6.0 stable days because `status.json` is 145 h stale (GitHub Actions cron not yet live — BL-006).

### Why no new sprint this pass
The dispatch task's escalation ladder is: (1) take HIGH backlog/features if available, (2) otherwise pick what advances go-live from `ideas`/`features`, (3) otherwise just report status. We are case (3) for code-side work:
- Every HIGH backlog item is a User Action — orchestrator cannot complete them.
- Every HIGH feature is post-go-live (FEAT-001/002) or already-shipped-and-archived (FEAT-004/005/006 moved to `done` in v3.20-bookkeeping).
- FEAT-007 Phase 3 is gated on ≥14 days of populated `apy_history.json`, which depends on the cron being live.
- Repeated bookkeeping sprints (v3.21 → v3.22 → v3.23) have already absorbed the small debt items; ginning up a v3.24 "sprint card" would be theatre, not work.

### Pushed to GitHub
- Nothing. Push pipeline (`push_*.html → http://localhost:8765 → Chrome navigate → GitHub Contents API`) requires the user's local HTTP server, which is not reachable from the autonomous dispatcher. Forbidden chunked-push via `javascript_tool` was not used.

### Files touched
- `data/golive_readiness.json` — fresh `generated_at` timestamp; verdict + criteria unchanged.
- `data/agent_stability.json` — `last_check` → 2026-05-28T07:13Z; freeze-note expanded.
- `KANBAN.json` — header metadata only (`last_updated`, `last_dispatch_run`, `last_dispatch_note`).
- `SPA_sprint_log.md` — this entry.

### Highest-ROI next actions (owner)
1. **BL-006 (≤ 0.2h)** — generate a workflow-scope PAT and push the accumulated v3.13–v3.23 batch via the local HTTP server pipeline. Single biggest unblock — once `.github/workflows/spa-run.yml` lives on `main`, the cron starts producing fresh `status.json` every 4h, which immediately flips Data Freshness (FAIL → PASS) and unfreezes the Agent Stability counter.
2. **BL-005 (≤ 0.5h)** — create `@SPA_alerts_bot` via BotFather, add `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` to GitHub Secrets. Activates daily digest + risk alerts (already coded in `spa_core/alerts/`).
3. **BL-004 (≤ 0.1h)** — Settings → Pages → Source: GitHub Actions. Activates `https://yurii-spa.github.io/SPA/` for `index.html` + `kanban.html`.

After all three land, the next cron tick (4 h) will regenerate `status.json` / `golive_readiness.json` / `tournament_results.json` / `advanced_analytics.json` on real production rails — and the WARN-pair (Strategy Tournament, APY Gap) will start evaluating against live data instead of "unavailable".


---

## Sprint v3.25 — 2026-05-29 — T2 Execution Adapters (Yearn V3 + Euler V2 + Maple)

**Цель:** завершить execution stack для всех T2 протоколов из whitelist. После v3.24 (T1: Morpho) необходимо было добавить T2-адаптеры — без них engine не может дотянуться до целевого APY 7.3%.

### SPA-V325-001 — YearnV3Adapter

**Файл:** `spa_core/execution/adapters/yearn_v3_adapter.py`

- Yearn V3 yVaults — ERC-4626 compliant (identичный интерфейс с MorphoAdapter)
- Цепочки: ethereum + arbitrum; ассеты: USDC + USDT
- Типичный APY: 6.5–7.1% (Aave V3 + Compound V3 multi-strategy vaults)
- Vault адреса: yvUSDC-1 `0xa354F35...`, yvUSDT `0x310B7E...` (ethereum), yvUSDC `0xa0E41f...` (arbitrum)
- Методы: `supply`, `withdraw`, `get_supply_apy`, `get_supply_balance`, `get_position`, `is_healthy`, `health_check`
- Dry-run по умолчанию; live path за `SPA_EXECUTION_MODE=live`

**Тесты:** `spa_core/tests/test_yearn_v3_adapter.py` — 15 тестов (6 классов)

### SPA-V325-002 — EulerV2Adapter

**Файл:** `spa_core/execution/adapters/euler_v2_adapter.py`

- Euler V2 eVaults — ERC-4626 (EVault архитектура, Prime cluster)
- Цепочки: ethereum; ассеты: USDC + USDT
- Типичный APY: 7.1–7.4% (utilisation-based)
- Vault адреса: eUSDC Prime `0x797DD8...`, eUSDT Prime `0x313603...`
- Суплайеры не имеют риска ликвидации → `is_healthy()` всегда `True`
- Полный ERC-4626 интерфейс, approve+deposit паттерн идентичен morpho/yearn

**Тесты:** `spa_core/tests/test_euler_v2_adapter.py` — 10 тестов (5 классов)

### SPA-V325-003 — MapleAdapter

**Файл:** `spa_core/execution/adapters/maple_adapter.py`

- Maple Finance V2 Cash Management — ERC-4626 USDC pool (institutional yield)
- Цепочки: ethereum; ассеты: USDC (only)
- Типичный APY: 5.6% (фиксированный institutional cash management)
- Pool: Maple CM USDC `0xFef25A...`
- Phase 1: стандартный ERC-4626 redeem; Phase 2 добавит requestRedeem для больших выводов
- Note в результатах withdrawal о возможном queue

**Тесты:** `spa_core/tests/test_maple_adapter.py` — 9 тестов (5 классов)

### SPA-V325-004 — engine_bridge.py wiring

**Файл:** `spa_core/execution/engine_bridge.py`

Добавлены в `_PROTOCOL_PREFIX_TO_FAMILY`:
- `"yearn-v3"` → `"yearn_v3"`
- `"euler-v2"` → `"euler_v2"`
- `"maple"` → `"maple"`

Добавлены ветки в `_get_adapter()`:
- `elif family == "yearn_v3"` → lazy import `YearnV3Adapter`
- `elif family == "euler_v2"` → lazy import `EulerV2Adapter`
- `elif family == "maple"` → lazy import `MapleAdapter`

Engine теперь принимает ключи: `yearn-v3-usdc-ethereum`, `euler-v2-usdt-ethereum`, `maple-usdc-ethereum`, `yearn-v3-usdc-arbitrum`, etc.

### Regression

- Запущен custom test runner (pytest недоступен в sandbox): **34 PASS / 0 FAIL**
- T1 adapters (aave, compound, morpho) + engine_bridge — не затронуты, рабочие

### Файлы

Новые:
- `spa_core/execution/adapters/yearn_v3_adapter.py`
- `spa_core/execution/adapters/euler_v2_adapter.py`
- `spa_core/execution/adapters/maple_adapter.py`
- `spa_core/tests/test_yearn_v3_adapter.py`
- `spa_core/tests/test_euler_v2_adapter.py`
- `spa_core/tests/test_maple_adapter.py`

Изменены:
- `spa_core/execution/engine_bridge.py` (T2 registration)
- `KANBAN.json` (done +4: SPA-V325-001..004, header)
- `SPA_sprint_log.md` (этот раздел)

### Следующие приоритеты (User Actions — без изменений)
1. **BL-006** — push workflow-scope PAT → cron запускается → Data Freshness FAIL исчезает
2. **BL-005** — Telegram bot token в Secrets
3. **BL-004** — включить GitHub Pages
4. **SPA-BL-007** — RPC ключи Alchemy/Infura (нужно для live Yearn/Euler/Maple/Morpho/Aave)
5. **SPA-BL-009** — Gnosis Safe кошелёк → Go-Live критерий #9

**Следующий возможный спринт:** SPA-V326 — FEAT-MON-004 MEV Protection (Flashbots RPC), либо Pendle PT adapter (PT-stablecoin ERC-5115), либо DeFiLlama APY feed для live APY reads в T2 адаптерах.

---

## Sprint v3.26 — 2026-05-29 — MEV Protection (Flashbots Protect RPC)

**Цель:** защитить live-транзакции от MEV/sandwich атак через Flashbots Protect RPC.

### SPA-V326-001 — mev_protection.py

**Файл:** `spa_core/execution/mev_protection.py`

- `send_protected(signed_tx_hex)` — роутинг через Flashbots Protect RPC вместо публичного мемпула
- `send_raw_transaction_auto(signed_tx_hex, public_rpc)` — drop-in замена для всех адаптеров: автоматически выбирает Flashbots/публичный RPC в зависимости от env
- `wait_for_receipt(tx_hash, rpc, max_wait)` — polling с graceful timeout
- `send_protected_dry_run()` — детерминированный mock для тестов

Endpoints:
- Primary: `https://rpc.flashbots.net/fast` (fast mode, default)
- Fallback: `https://rpc.flashbots.net` → `https://rpc.mevblocker.io/noreverts`
- Emergency fallback: публичный RPC с предупреждением

Env-переменные:
- `SPA_MEV_PROTECTION=true` — включить защиту (по умолчанию false)
- `SPA_FLASHBOTS_MODE=fast|standard|mevblocker`

Транзакция никогда не попадает в публичный мемпул при MEV_PROTECTION=true + EXECUTION_MODE=live.

**Тесты:** `spa_core/tests/test_mev_protection.py` — 18 тестов

### Регрессия
18 PASS / 0 FAIL (custom runner, pytest недоступен в sandbox)

### Файлы
Новые:
- `spa_core/execution/mev_protection.py`
- `spa_core/tests/test_mev_protection.py`

Обновлены:
- `KANBAN.json` (done +1: SPA-V326-001)
- `SPA_sprint_log.md`

### Следующий спринт
SPA-V327: DeFiLlama APY feed — live APY reads для T2 адаптеров (Yearn/Euler/Maple) вместо мок-значений. Endpoint: `https://yields.llama.fi/pools`

## Sprint v3.27 — 2026-05-29 — DeFiLlama APY feed (live APY для T2)

**Цель:** заменить мок-значения APY в T2-адаптерах (Yearn V3 / Euler V2 / Maple) на live-чтения из DeFiLlama, с безопасным fallback на мок.

### SPA-V327-001 — defillama_apy_feed.py

**Файл:** `spa_core/execution/defillama_apy_feed.py`

- Endpoint: `https://yields.llama.fi/pools` (GET, stdlib `urllib.request`, без зависимостей)
- `_fetch_pools()` — retry/backoff (timeout 15s, 3 попытки, backoff 2.0); при сетевой ошибке возвращает `[]` и логирует warning (никогда не кидает)
- In-process TTL-кэш: `_CACHE = {"pools": None, "ts": 0.0}`, TTL по умолчанию 900s (15 мин), override через `SPA_APY_CACHE_TTL`. Функция `_get_pools_cached(force=False)`; пустой fetch (сбой сети) НЕ кэшируется
- `get_live_apy(protocol, asset, chain) -> float | None` — нормализация protocol (lower, пробелы→дефисы), asset (upper), chain (lower); маппинг через `_PROTOCOL_PROJECT_MATCH`; fuzzy-match как в defillama_fetcher (substring project/symbol/chain, выбор max `tvlUsd`); `round(apy, 4)`. Любая ошибка / нет матча / apy=None → `None`
- `get_live_apy_from_pools(pools, protocol, asset, chain)` — детерминированный helper без сети (используется и внутри `get_live_apy`, и в тестах)
- `_PROTOCOL_PROJECT_MATCH = {"yearn-v3":"yearn","euler-v2":"euler","maple":"maple","yearn":"yearn","euler":"euler"}`
- Env-гейт: `live_apy_enabled()` читает `SPA_LIVE_APY` ∈ {"1","true","yes"} (по умолчанию off)
- `clear_cache()` для тестов; `__main__` демо с мок-пулами

### SPA-V327-002 — T2 adapters wiring

**Файлы:** `yearn_v3_adapter.py`, `euler_v2_adapter.py`, `maple_adapter.py`

- В `get_supply_apy(asset)` сохранено вычисление `mock` (Yearn/Euler fallback 5.0 → фактические значения из `_DRY_RUN_APY`; Maple fallback 4.5)
- `dry_run=True` → возвращает mock как раньше (короткое замыкание до любого сетевого вызова)
- Live режим: если `defillama_apy_feed.live_apy_enabled()` → `get_live_apy(PROTOCOL, asset, self.chain)`; `live is not None` → info-лог + return live; иначе debug-лог + mock
- Ленивый импорт `from spa_core.execution import defillama_apy_feed` внутри try/except — отсутствие модуля/сети/любое исключение → mock
- PROTOCOL: yearn → "yearn-v3", euler → "euler-v2", maple → "maple"

### Регрессия
- `test_defillama_apy_feed`: 38 PASS / 0 FAIL (unittest runner, без реальной сети)
- T2-адаптеры (`test_yearn_v3_adapter`, `test_euler_v2_adapter`, `test_maple_adapter`): 88 PASS / 0 FAIL — wiring не сломал dry-run
- Итого: 126 PASS / 0 FAIL

### Файлы
Новые:
- `spa_core/execution/defillama_apy_feed.py`
- `spa_core/tests/test_defillama_apy_feed.py`

Обновлены:
- `spa_core/execution/adapters/yearn_v3_adapter.py` (get_supply_apy live wiring)
- `spa_core/execution/adapters/euler_v2_adapter.py` (get_supply_apy live wiring)
- `spa_core/execution/adapters/maple_adapter.py` (get_supply_apy live wiring)
- `KANBAN.json` (done +2: SPA-V327-001, SPA-V327-002)
- `SPA_sprint_log.md`

### Следующий спринт

---

## Sprint v3.28 — 2026-05-29 — Pendle PT adapter (ERC-5115 fixed-rate yield)

**Цель:** Добавить T2-адаптер для Pendle Principal Token (PT) — ERC-5115 / SY, фиксированная implied-доходность PT-USDC на сети ethereum. Стиль 1-в-1 с `yearn_v3_adapter.py` / `maple_adapter.py`.

### Что сделано (SPA-V328-001)
- Создан `spa_core/execution/adapters/pendle_pt_adapter.py` — `PendlePTAdapter` (T2), стиль повторяет yearn_v3/maple 1-в-1.
  - Маркеты (ethereum): PT-USDC (~6.5% implied fixed APY, maturity 2026-09-24) и PT-USDT (~6.1%, maturity 2026-12-31).
  - dataclasses `TxRequest`, `PositionInfo` (с полем `maturity`). `SUPPORTED_CHAINS=("ethereum",)`, `SUPPORTED_ASSETS=("USDC","USDT")`.
  - `supply`/`withdraw`: `DRY_RUN` в dry_run; `BLOCKED` если `SPA_EXECUTION_MODE != live`; `NOT_IMPLEMENTED` в live (подпись = Phase 3, как заглушка). `ValueError` на неподдерживаемые chain/asset и на amount<=0 / >10M cap.
  - `get_supply_apy(asset)`: dry_run → mock из `_DRY_RUN_APY` (короткое замыкание до любого сетевого вызова); live → `defillama_apy_feed.live_apy_enabled()` + `get_live_apy("pendle-pt", asset, chain)`; `live is not None` → info-лог + return; иначе debug-лог + mock. Ленивый импорт в try/except → любое исключение/нет модуля → mock. Точно как в yearn.
  - Pendle-специфика: `get_maturity(asset)->ISO`, `is_matured(asset, now=None)->bool` (UTC-aware, naive→UTC, не кидает), `implied_fixed_apy` как алиас `get_supply_apy`, `get_apy` алиас.
  - ERC-5115 (SY) lifecycle в docstring/комментариях: SY оборачивает underlying; PT минтится из SY (`mintPyFromSy`); после maturity redeem PT→underlying 1:1 (`redeemPyToToken` / `SY.redeem`). Селекторы заданы константами-заглушками для Phase 3.
  - `is_healthy()` всегда True (PT не ликвидируется). `health_check`, `get_position(wallet, asset, chain)`, `get_supply_balance`, блок `if __name__ == "__main__"` демо.
  - Чистый stdlib (`urllib` + `json`), без внешних зависимостей; не кидает исключений на dry-run happy path; production-safe fallback на mock.
- Зарегистрирован в `engine_bridge.py`: префикс `"pendle-pt"` → family `"pendle_pt"` в `_PROTOCOL_PREFIX_TO_FAMILY`; ветка `elif family == "pendle_pt"` в `_get_adapter` с lazy-import `PendlePTAdapter`. Engine принимает ключи `pendle-pt-usdc-ethereum` / `pendle-pt-usdt-ethereum` (проверено: parse → dispatch доходит до адаптера).
- Добавлено `"pendle-pt": "pendle"` и `"pendle": "pendle"` в `_PROTOCOL_PROJECT_MATCH` (`defillama_apy_feed.py`).
- Тесты: `spa_core/tests/test_pendle_pt_adapter.py` — 49 тестов (init/валидация, dry_run supply/withdraw, BLOCKED/NOT_IMPLEMENTED, mock-APY, live-режим через мок `defillama_apy_feed` без сети, maturity/is_matured, get_position, is_healthy=True, интеграция с engine_bridge: `_parse_protocol_key` + `_get_adapter` + `execute_supply`).

### Файлы
Новые:
- `spa_core/execution/adapters/pendle_pt_adapter.py`
- `spa_core/tests/test_pendle_pt_adapter.py` (49 тестов)

Обновлены:
- `spa_core/execution/engine_bridge.py` (pendle-pt family + dispatch)
- `spa_core/execution/defillama_apy_feed.py` (pendle project match)
- `spa_core/tests/test_engine_bridge.py` (pendle-pt parse-тест; убран устаревший malformed-кейс)
- `KANBAN.json` (done +1: SPA-V328-001; header → v3.28; бэкап `KANBAN.json.bak.v328`)
- `SPA_sprint_log.md` (бэкап `SPA_sprint_log.md.bak.v328`)

### Результаты тестов
- Новый адаптер: **49 PASS / 0 FAIL** (`pytest 9.0.3`, Python 3.10).
- Регрессия T2 (yearn 32 / euler 28 / maple 28): **88 PASS / 0 FAIL**.
- `test_engine_bridge`: **36 PASS** (добавлен `test_pendle_pt_key_parses`; убран устаревший кейс `pendle-pt-steth-arbitrum` из списка malformed — теперь это поддерживаемый префикс).
- Раннер: pytest (установлен в sandbox через `pip install --break-system-packages pytest`). Все тесты детерминированы, без реальной сети — live-APY моки ставятся через `mock.patch` на функции реального модуля `defillama_apy_feed`, env патчится.
- Импорт адаптера и резолв ключа `pendle-pt-usdc-ethereum` через engine_bridge (`_parse_protocol_key` → `_get_adapter` → `execute_supply`) подтверждены отдельной проверкой.

**Два пред-существующих падения (НЕ связаны с V328, не чинил — вне scope):**
1. `test_engine_bridge::TestParseProtocolKey::test_malformed_returns_none[morpho-blue-usdc-base]` — `morpho-blue-...` парсится как family `morpho` уже в baseline (без правок V328); сам тест в комментарии это признаёт («…wait it is»).
2. `test_defillama_apy_feed::TestTtlCache` — требует реального сетевого вызова (ConnectionError в offline-sandbox); код TTL-кэша V328 не трогал.

### Следующий спринт
**SPA-V329:** Sky / sUSDS adapter (условный T1) — активировать как только GSM ≥48h подтверждён.

## Sprint v3.29 — 2026-05-29 — Sky/sUSDS adapter (условный T1)

**Цель:** Добавить адаптер для Sky Savings (sUSDS, ERC-4626 vault) как условный T1 — код готов, но supply/withdraw в live заблокированы до тех пор, пока sky_monitor не подтвердит GSM Pause Delay ≥ 48h (status ELIGIBLE). Стиль 1-в-1 с `maple_adapter.py`.

### Что сделано (SPA-V329-001)
- Создан `spa_core/execution/adapters/sky_susds_adapter.py` — `SkySUSDSAdapter`, conditional T1.
  - sUSDS vault (ethereum): `0xa3931d71877C0E7a3148CB7Eb4463524FEc27fbD`. Активы: USDS (`0xdC035D45...`) + DAI. decimals=18. ERC-4626 селекторы как в maple.
  - **Conditional-T1 gate (уникально для Sky):** `is_eligible_t1()` читает `sky_monitor` (dry_run → `check_sky_status()` manual без сети; live → `check_sky_status_live()`; никогда не кидает). `get_tier()` → "T1" / "T2-conditional". `get_allocation_cap()` → 0.30 (ELIGIBLE) / 0.0 (PENDING) через `get_sky_allocation_pct`.
  - `supply`/`withdraw`: dry_run → DRY_RUN (с полями `tier`, `eligible_t1`); live + НЕ eligible → BLOCKED "Sky not yet ELIGIBLE for T1 (GSM Pause Delay < 48h confirmed)"; eligible но `SPA_EXECUTION_MODE != live` → BLOCKED; полная live-ветка (approve+deposit / redeem) скопирована из maple.
  - `get_supply_apy(asset)`: mock 6.5% + DeFiLlama live wiring `get_live_apy("sky", asset, chain)` (gated `SPA_LIVE_APY`), try/except → mock. Плюс `get_apy`, `get_supply_balance`, `get_position`, `is_healthy()=True`, `health_check()`, `_execute_tx_pair`/`_execute_single_tx`, `__main__` демо. Чистый stdlib.
- Зарегистрирован в `engine_bridge.py`: префикс `"sky-susds"` → family `"sky_susds"` в `_PROTOCOL_PREFIX_TO_FAMILY`; ветка `elif family == "sky_susds"` в `_get_adapter`. Ключ `sky-susds-usds-ethereum` резолвится корректно.
- Добавлено `"sky-susds"/"sky"/"susds" → "sky"` в `_PROTOCOL_PROJECT_MATCH` (`defillama_apy_feed.py`).
- Тесты: `spa_core/tests/test_sky_susds_adapter.py` — 50 тестов (init/валидация, dry_run, conditional-T1 gate при PENDING/ELIGIBLE через мок sky_monitor, BLOCKED-ветки, mock/live APY через мок defillama_apy_feed без сети, get_position, is_healthy, health_check, интеграция engine_bridge parse+dispatch).

### Файлы
Новые:
- `spa_core/execution/adapters/sky_susds_adapter.py`
- `spa_core/tests/test_sky_susds_adapter.py` (50 тестов)

Обновлены:
- `spa_core/execution/engine_bridge.py` (sky-susds family + dispatch)
- `spa_core/execution/defillama_apy_feed.py` (sky project match)
- `KANBAN.json` (done +1: SPA-V329-001; header → v3.29; бэкап `KANBAN.json.bak.v329`)
- `SPA_sprint_log.md` (бэкап `SPA_sprint_log.md.bak.v329`)

### Результаты тестов
- Новый адаптер: **50 PASS / 0 FAIL**.
- Регрессия (maple/yearn/pendle/engine_bridge): **145 PASS / 1 FAIL** — единственное падение `test_malformed_returns_none[morpho-blue-usdc-base]` пред-существующее (morpho-blue parse), не связано с V329.
- Текущий статус Sky: **PENDING** → адаптер отдаёт tier "T2-conditional", allocation cap 0.0; live supply/withdraw заблокированы (BLOCKED) — это и есть ожидаемое поведение до подтверждения GSM ≥ 48h.

### Следующий спринт
**SPA-V330:** Architect review + KANBAN housekeeping — `python3 -m spa_core.dev_agents.architect --command review-backlog`, закрыть устаревшие карточки, добавить новые задачи. (v3.30 заканчивается на 0 → периодический architect review.)

## Sprint v3.42 — 2026-05-30 — APY-feed protocol-count drop monitoring + v3.41 verification

### Что сделано
- **Часть A (verification v3.41):** прогнан pytest для PostgreSQL-миграции, который прошлый ран НЕ выполнил из-за сбоя sandbox. `test_pg_migration_execute.py` + `test_pg_migration.py` — **42 PASS**. Регрессия мониторинга (`test_apy_feed_stale_monitor` + `test_covariance_health_monitor` + `test_alerts` + `test_covariance_export`) — **161 PASS**. v3.41 верифицирован зелёным.
- **Часть B (новая фича):** добавлен ранний health-алерт на резкое падение числа протоколов в `data/historical_apy.json` между циклами (напр. DeFiLlama частично отвалился: было 7, стало 3). Закрывает слепое пятно — фид может оставаться свежим (generated_at OK) и live (data_source OK), тихо теряя протоколы, что невидимо для `alert_apy_feed_stale` (возраст/source) и `alert_covariance_degraded` (covariance source), при этом covariance/Kelly-вселенная истончается. Решение зеркалит SPA-V340 `alert_apy_feed_stale` 1-в-1.
  - Константы `APY_FEED_PROTOCOL_DROP_PCT=0.5` (падение ≥50% = деградация) и `APY_FEED_MIN_PROTOCOLS=3` (абсолютный пол).
  - `self._apy_feed_protocol_health_file` в `__init__`.
  - Метод `alert_apy_feed_protocol_drop(feed_path=None, *, num_protocols=None, now=None, sender=None)` — top-level try/except→False, lazy TelegramSender, persistent state (`prev_num_protocols`/`consecutive_drops`/`last_alerted_cycle`), streak-логика. degraded = unreadable (None) ИЛИ too_few (< 3) ИЛИ sharp_drop (num <= prev*0.5). Порог по числу циклов = **1** (резкое падение алертим сразу, в отличие от staleness=2); refire на каждом растущем цикле; prev всегда обновляется после оценки.
  - Helpers `_load/_write_apy_feed_protocol_health_state` (graceful).
  - `export_data.py`: зеркальный try/except-блок «APY feed protocol-count drop alert» сразу после блока staleness в `run_export`.

### Файлы
- `spa_core/alerts/risk_monitor.py` (modified)
- `spa_core/export_data.py` (modified)
- `spa_core/tests/test_apy_feed_protocol_drop_monitor.py` (new, 23 теста)

### Результаты тестов
- Часть A: pg_migration 42 PASS; регрессия мониторинга 161 PASS.
- Часть B: `test_apy_feed_protocol_drop_monitor.py` **23 PASS** (offline FakeSender).
- Полная объединённая регрессия: **226 PASS, 0 новых фейлов**.
- `py_compile` risk_monitor.py + export_data.py ok. KANBAN.json валиден. Бэкапы `.bak.v342` созданы.
- Пред-существующие fail (`test_engine_bridge` morpho-blue-usdc-base, `test_defillama_apy_feed` TestTtlCache) — вне scope, не трогались.

### Следующий спринт
- **SPA-V343:** алерт на резкое схлопывание суммарного TVL в `historical_apy.json` (фид может сохранять число протоколов, но TVL обвалиться — ещё одно слепое пятно для covariance-вселенной), ЛИБО дальнейшее расширение feed-мониторинга (напр. per-protocol APY-аномалии / выпадение конкретного протокола из фида).

## Sprint v3.43 — 2026-05-30 — APY-feed total-TVL collapse alert

### Что сделано
- Добавлен ранний health-алерт на резкое схлопывание **СОВОКУПНОГО TVL** в `data/historical_apy.json` между циклами (напр. DeFiLlama вернул резко меньший TVL при том же числе протоколов). Закрывает слепое пятно: фид может оставаться свежим (`generated_at` OK), live (`data_source` OK) и нести **то же число протоколов**, тихо теряя капитальный вес — невидимо для `alert_apy_feed_stale` (возраст/source) и `alert_apy_feed_protocol_drop` (число протоколов), при этом covariance/Kelly-вселенная истончается по капитальному весу. Решение зеркалит SPA-V342 `alert_apy_feed_protocol_drop` 1-в-1.
  - Константы `APY_FEED_TVL_DROP_PCT=0.5` (падение совокупного TVL ≥50% между циклами = деградация) и `APY_FEED_MIN_TVL_USD=1e7` (абсолютный пол: совокупный TVL фида < $10M).
  - `self._apy_feed_tvl_health_file` в `__init__` (после `_apy_feed_protocol_health_file`).
  - Метод `alert_apy_feed_tvl_drop(feed_path=None, *, total_tvl_usd=None, now=None, sender=None)` — top-level try/except→False (НИКОГДА не raise), lazy TelegramSender, persistent state (`prev_tvl_usd`/`consecutive_drops`/`last_alerted_cycle`/`updated_at`), streak-логика. Резолв `total_tvl_usd`: если None и `feed_path` задан — graceful чтение JSON (`protocols` ИЛИ `protocol_history`), для каждого протокола берётся `tvl_usd` ПОСЛЕДНЕЙ записи истории и суммируется (пропуск пустых/не-list значений и записей без числового `tvl_usd`, coerce через `float()`); нет пригодных протоколов/битый/нет файла → None (unreadable). degraded = unreadable (None) ИЛИ too_low (< $10M) ИЛИ sharp_drop (total <= prev*0.5). Порог по числу циклов = **1** (резкое схлопывание алертим сразу); refire на каждом растущем цикле; `prev_tvl_usd` всегда обновляется после оценки. HTML msg `⚠️ <b>SPA APY Feed TVL Collapse</b>` с TVL формата `${value:,.0f}`.
  - Helpers `_load/_write_apy_feed_tvl_health_state` (graceful на miss/corrupt).
  - `export_data.py`: зеркальный try/except-блок «APY feed TVL collapse alert» сразу после блока protocol-count drop в `run_export`.

### Файлы
- `spa_core/alerts/risk_monitor.py` (modified)
- `spa_core/export_data.py` (modified)
- `spa_core/tests/test_apy_feed_tvl_drop_monitor.py` (new, 24 теста)

### Результаты тестов
- `test_apy_feed_tvl_drop_monitor.py` **24 PASS** (offline FakeSender, tmp_path-изолированы).
- Регрессия мониторинга (`test_apy_feed_protocol_drop_monitor` + `test_apy_feed_stale_monitor` + `test_covariance_health_monitor` + `test_alerts` + `test_covariance_export`) — **138 PASS, 0 новых фейлов**.
- `py_compile` risk_monitor.py + export_data.py ok. KANBAN.json валиден. Бэкапы `.bak.v343` созданы.
- Пред-существующие fail (`test_engine_bridge` morpho-blue-usdc-base, `test_defillama_apy_feed` TestTtlCache) — вне scope, не трогались.

### Следующий спринт
- **SPA-V344:** per-protocol APY-аномалия / детектор выпадения конкретного протокола из фида (один протокол резко теряет APY/TVL или пропадает между циклами — точечное слепое пятно, не покрываемое агрегатными TVL/count-алертами), ЛИБО валидация schema-drift фида `historical_apy.json` (изменение формы/ключей записей, неожиданные поля, смена типов `tvl_usd`/`apy`).

## Sprint v3.44 — 2026-05-30 — APY-feed per-protocol anomaly + dropout detector

### Что сделано
- Добавлен ТОЧЕЧНЫЙ ранний health-алерт `RiskMonitor.alert_apy_feed_protocol_anomaly` на **аномалию конкретного протокола** в `data/historical_apy.json` между циклами. Закрывает слепое пятно, не покрываемое агрегатными алертами: число протоколов (`alert_apy_feed_protocol_drop`, v3.42) и совокупный TVL (`alert_apy_feed_tvl_drop`, v3.43) могут держаться, пока ОДНА позиция тихо обваливается или ВЫПАДАЕТ из фида — covariance/Kelly-вселенная теряет точечный капитальный/доходностный вес незаметно для агрегатов. Зеркалит `alert_apy_feed_protocol_drop`/`alert_apy_feed_tvl_drop` 1-в-1.
  - Строит per-protocol `snapshot` = `dict[key → {apy, tvl_usd}]`: для каждого протокола из `protocols` (или `protocol_history`) берётся ПОСЛЕДНЯЯ запись истории, `apy`/`tvl_usd` coerce через `float()` (не-число/отсутствует → None; пустой/не-list history → протокол пропущен; битый/нет файла/нет пригодных протоколов → snapshot=None=unreadable).
  - Аномалия = `unreadable` ИЛИ `disappeared` (ключ был в `prev_snapshot`, исчез сейчас) ИЛИ `apy_crash` (prev apy>0 и `cur_apy <= prev_apy*(1-0.6)`) ИЛИ `tvl_crash` (prev tvl>0 и `cur_tvl <= prev_tvl*(1-0.6)`).
  - Константы `APY_FEED_PROTOCOL_APY_DROP_PCT=0.6` / `APY_FEED_PROTOCOL_TVL_DROP_PCT=0.6` (выше агрегатных 0.5 — отдельный протокол волатильнее). Поле `self._apy_feed_anomaly_health_file = data_dir/apy_feed_anomaly_health_state.json` в `__init__`.
  - Persistent state (`prev_snapshot`/`consecutive_anomalies`/`last_alerted_cycle`/`updated_at`), streak-логика, **порог=1** (точечную аномалию алертим сразу на первом цикле; рефайр на каждом следующем аномальном цикле; healthy сбрасывает streak; `prev_snapshot` всегда обновляется текущим snapshot после оценки). top-level try/except→False (НИКОГДА не raise), lazy TelegramSender. HTML msg `⚠️ <b>SPA APY Feed Protocol Anomaly</b>` с перечислением затронутых протоколов по категориям (disappeared / APY crash prev→cur / TVL crash $prev→$cur).
  - Helpers `_load/_write_apy_feed_anomaly_health_state` (graceful на miss/corrupt).
  - `export_data.py`: зеркальный try/except-блок «APY feed per-protocol anomaly alert» сразу после блока TVL collapse в `run_export`.

### Файлы
- `spa_core/alerts/risk_monitor.py` (modified)
- `spa_core/export_data.py` (modified)
- `spa_core/tests/test_apy_feed_protocol_anomaly_monitor.py` (new, 30 тестов)

### Результаты тестов
- `test_apy_feed_protocol_anomaly_monitor.py` **30 PASS** (offline FakeSender, tmp_path-изоляция).
- Регрессия мониторинга (`test_apy_feed_tvl_drop_monitor` + `test_apy_feed_protocol_drop_monitor` + `test_apy_feed_stale_monitor` + `test_covariance_health_monitor`) — **70 PASS, 0 новых фейлов**.
- `py_compile` risk_monitor.py + export_data.py OK. KANBAN.json валиден (re-parse OK). Бэкапы `.bak.v344` созданы.
- Пред-существующие fail (`test_engine_bridge` morpho-blue-usdc-base, `test_defillama_apy_feed` TestTtlCache) — вне scope, не трогались.

### Следующий спринт
- **SPA-V345:** валидация schema-drift фида `historical_apy.json` (изменение формы/ключей записей, смена типов `apy`/`tvl_usd`, неожиданные поля), ЛИБО per-protocol stale-детектор (конкретный протокол перестал обновляться — `generated_at` фида свежий, но последняя дата истории одного протокола залипла на N циклов).

## Sprint v3.45 — 2026-05-30 — APY-feed schema-drift validation

**Что сделано**

Добавлен монитор-метод `alert_apy_feed_schema_drift` в `risk_monitor.py`, который валидирует СТРУКТУРУ/КЛЮЧИ/ТИПЫ записей historical_apy.json. Для каждого протокола берётся ПОСЛЕДНЯЯ запись истории и проверяется схема: history должна быть list, запись — dict, обязательные поля `apy`/`tvl_usd` присутствуют и являются числом (int/float или числовая строка; bool/None/нечисловая строка = drift). Неожиданные ключи фиксируются для контекста, но не фатальны. Это слепое пятно, которое НЕ видят stale/protocol-drop/tvl-drop/per-protocol-anomaly алерты — все они уже предполагают корректную схему и молча пропускают или мис-парсят битые записи.

**Сигналы drift**: `unreadable` (нет файла/битый/нет пригодных протоколов), `too_few` (< APY_FEED_SCHEMA_MIN_PROTOCOLS=1), `schema_bad` (доля протоколов с битой схемой >= APY_FEED_SCHEMA_MAX_BAD_PCT=50%).

**Порог**: срабатывает на первом drift-цикле (threshold 1), refire на каждом следующем drift-цикле; healthy сбрасывает streak; состояние `apy_feed_schema_health_state.json` всегда обновляется после оценки.

**Файлы:**
- `spa_core/alerts/risk_monitor.py` — метод `alert_apy_feed_schema_drift` + helpers `_load_/_write_apy_feed_schema_health_state`, константы `APY_FEED_REQUIRED_FIELDS` / `APY_FEED_SCHEMA_MAX_BAD_PCT` / `APY_FEED_SCHEMA_MIN_PROTOCOLS` / `APY_FEED_KNOWN_FIELDS`, поле `_apy_feed_schema_health_file`
- `spa_core/export_data.py` — wiring (блок `APY feed schema drift alert` после per-protocol anomaly)
- `spa_core/tests/test_apy_feed_schema_drift_monitor.py` — 40 тестов

**Результаты тестов:** новые 40 PASS, регрессия 148 PASS (anomaly+tvl+protocol-drop+stale+covariance), 0 фейлов. py_compile risk_monitor.py + export_data.py — OK.

**Следующий спринт (SPA-V346)**: per-protocol stale-детектор — конкретный протокол перестал обновляться (его последний timestamp/ts заморожен) при свежем generated_at всего фида; ЛИБО sanity-bounds валидация диапазонов значений apy/tvl_usd (например apy < 0 или > 1000%, tvl_usd <= 0 или абсурдно большой) — отлов мусорных, но формально корректных по типу значений.

---

## Sprint v3.46 — 2026-05-30 — APY-feed per-protocol staleness monitoring

### Что сделано
- (Backfill-стаб — полная запись восстановлена из KANBAN SPA-V346-001.) Новый ранний health-алерт `RiskMonitor.alert_apy_feed_protocol_stale` на ситуацию, когда КОНКРЕТНЫЙ протокол в `data/historical_apy.json` перестал обновляться (последняя запись его истории старше `APY_FEED_PROTOCOL_MAX_AGE_HOURS=48h`), при том что фид в ЦЕЛОМ свежий (`generated_at` двигается за счёт остальных протоколов). Закрывает ВРЕМЕННОЕ слепое пятно: `alert_apy_feed_stale` смотрит только на feed-level `generated_at`, а per-protocol anomaly — на крах значений apy/tvl, но не на замороженную дату. Зеркалит schema-drift по стилю (snapshot/persistent state/streak, порог=1, fire/refire/reset, никогда не raise, lazy TelegramSender). State-файл `apy_feed_protocol_stale_health_state.json`.

### Файлы
- `spa_core/alerts/risk_monitor.py` (modified)
- `spa_core/export_data.py` (modified)
- `spa_core/tests/test_apy_feed_protocol_stale_monitor.py` (new)

### Результаты тестов
- Новый файл тестов PASS; регрессия feed-мониторов — 0 новых фейлов (см. DISPATCH_REPORT_2026-05-30 серии).

### Следующий спринт
- **SPA-V347:** агрегированная feed-health сводка — консолидация независимых feed/covariance health-сигналов в один dashboard-бейдж.

---

## Sprint v3.47 — 2026-05-30 — Aggregated feed-health summary

### Что сделано
- (Backfill-стаб — из KANBAN SPA-V347-001.) Новый standalone-агрегатор `spa_core/alerts/feed_health_summary.py`, консолидирующий 7 независимых feed/covariance health-сигналов (covariance, apy_feed_stale, protocol_drop, tvl_drop, protocol_anomaly, schema_drift, protocol_stale) в ОДИН dashboard-ready документ `data/feed_health_summary.json`. Каждый сигнал читается из своего state-файла (graceful на miss/corrupt), классифицируется ok/warn/degraded/unknown против СОБСТВЕННОГО порога монитора, и сворачивается в `overall_status` (worst-of). Чистый stdlib, никогда не бросает на happy-path. Зеркалит паттерн `execution/adapter_status.py` / `analytics/covariance_export.py`. Интегрирован в `export_data.py` (write после всех feed-алертов) и в `index.html` (бейдж Feed Health + динамические чипы по сигналам).

### Файлы
- `spa_core/alerts/feed_health_summary.py` (new)
- `spa_core/export_data.py` (modified)
- `index.html` (modified — бейдж + loadFeedHealth/renderFeedHealth)
- `spa_core/tests/test_feed_health_summary.py` (new)

### Результаты тестов
- `test_feed_health_summary.py` PASS (offline, tmp_path); регрессия 0 новых фейлов.

### Следующий спринт
- **SPA-V348:** устранение давнего baseline-фейла парсинга (morpho-blue в engine_bridge).

---

## Sprint v3.48 — 2026-05-30 — Fix morpho-blue prefix parse in engine_bridge

### Что сделано
- (Backfill-стаб — из KANBAN SPA-V348-001.) Закрыт давний baseline-фейл `test_engine_bridge::test_malformed_returns_none[morpho-blue-usdc-base]`, таскавшийся «вне scope» ~20 спринтов. `_parse_protocol_key` в `engine_bridge.py` парсил `morpho-blue-usdc-base` как `{family:morpho, asset:BLUE-USDC, chain:base}` (asset неверен — 'blue' съедался), а тест ждал None. Но `morpho-blue` УЖЕ маппится на family `morpho` в `yield_classifier_agent.py` / `audit_reader_agent.py` — `engine_bridge` был единственным несогласованным местом. Добавлен префикс `morpho-blue`->`morpho` ПЕРЕД `morpho`; цикл подбора префикса переведён на longest-prefix-match. Тест переведён на корректное ожидание.

### Файлы
- `spa_core/engine_bridge.py` (modified)
- `spa_core/tests/test_engine_bridge.py` (modified)

### Результаты тестов
- `test_engine_bridge.py` PASS (включая новые `test_morpho_blue_key_parses`); полная регрессия зелёная.

### Следующий спринт
- **SPA-V349:** sanity-bounds валидация диапазонов значений apy/tvl_usd (отложенная альтернатива из v3.45) — отлов мусорных, но формально корректных по типу значений, отравляющих covariance/Kelly-вселенную.

---

## Sprint v3.49 — 2026-05-30 — APY-feed value-range sanity-bounds validation

### Что сделано
- Добавлен 8-й feed-health монитор `RiskMonitor.alert_apy_feed_value_bounds` — валидация того, что численные ЗНАЧЕНИЯ записей `data/historical_apy.json` попадают в адекватный ДИАПАЗОН. Закрывает явно отложенную из v3.45 альтернативу (stale-детектор взяли как V346; sanity-bounds не строили). Все существующие feed-мониторы (stale / protocol-drop / tvl-drop / per-protocol anomaly / schema-drift / protocol-stale) проверяют свежесть, счётчики, дельты, структуру и ТИПЫ — но НИ ОДИН не валидирует диапазон значений. Type-valid garbage (`apy=50000%`, `apy<0`, `tvl_usd<=0`, `tvl_usd>$10T`) проходил все проверки, но отравлял covariance/Kelly-вселенную.
  - Метод зеркалит `alert_apy_feed_schema_drift` 1-в-1: для каждого протокола берётся ПОСЛЕДНЯЯ history-запись, `apy`/`tvl_usd` коэрсятся через `float()`. Протокол `out_of_bounds`, если `apy < APY_FEED_APY_MIN(0.0)`, `apy > APY_FEED_APY_MAX(1000.0)`, `tvl_usd <= APY_FEED_TVL_MIN(0.0)` или `tvl_usd > APY_FEED_TVL_MAX(1e13)`. Нечисловые/отсутствующие значения — забота schema-drift, ИСКЛЮЧАЮТСЯ из знаменателя bounds.
  - **Конвенция единиц apy**: фид DeFiLlama хранит `apy` как ПРОЦЕНТНОЕ число (6.3057 == 6.3057%, см. `execution/defillama_apy_feed.py` `get_live_apy` docstring "Return live APY (%)" и `data/historical_apy.json`), поэтому верхняя граница = `1000.0` (== 1000%), а не `10.0` (доля). `tvl_usd` — сырые доллары.
  - **Сигналы**: `unreadable` (нет файла/битый/нет пригодных числовых протоколов), `too_few` (< `APY_FEED_BOUNDS_MIN_PROTOCOLS=1`), `bounds_bad` (доля out_of_bounds >= `APY_FEED_BOUNDS_MAX_BAD_PCT=0.5`).
  - **Persistent state** `apy_feed_bounds_health_state.json` (streak-поле `consecutive_bounds`, `last_alerted_cycle`, `updated_at`, `prev_bad_keys`), **порог=1** (fire на первом плохом цикле, refire на каждом следующем, healthy сбрасывает streak, state всегда обновляется). top-level try/except→False (НИКОГДА не raise), lazy TelegramSender. HTML msg `⚠️ <b>SPA APY Feed Value Bounds</b>` с перечислением нарушивших протоколов, какой границы и значения. Helpers `_load/_write_apy_feed_bounds_health_state`.
  - `export_data.py`: зеркальный try/except-блок «APY feed value-bounds alert» сразу ПОСЛЕ protocol-stale, ПЕРЕД feed_health_summary.
  - **Интеграция в v3.47-агрегатор** `feed_health_summary.py`: 8-й сигнал `("value_bounds", "apy_feed_bounds_health_state.json", "Value bounds", "consecutive_bounds", 1)` + обновлён docstring-реестр. `index.html` рендерит чипы Feed Health ДИНАМИЧЕСКИ из `data.signals` (`loadFeedHealth`/`renderFeedHealth`) — правок не требует (подтверждено чтением).

### Файлы
- `spa_core/alerts/risk_monitor.py` (modified — константы, поле `__init__`, метод + helpers)
- `spa_core/export_data.py` (modified — wiring)
- `spa_core/alerts/feed_health_summary.py` (modified — 8-й сигнал + docstring)
- `spa_core/tests/test_apy_feed_value_bounds_monitor.py` (new, 42 теста)
- `spa_core/tests/test_feed_health_summary.py` (modified — счётчики 7→8)
- `KANBAN.json`, `SPA_sprint_log.md` (bookkeeping)
- Бэкапы `.bak.v349` для всех изменённых файлов.

### Результаты тестов
- `test_apy_feed_value_bounds_monitor.py` — **42 PASS** (offline FakeSender, tmp_path-изоляция).
- Регрессия (`test_apy_feed_schema_drift_monitor` + `test_apy_feed_protocol_anomaly_monitor` + `test_feed_health_summary` + `test_defillama_apy_feed`) — **126 PASS, 0 новых фейлов**.
- `py_compile` risk_monitor.py + export_data.py + feed_health_summary.py — OK. KANBAN.json валиден. `node --check` неприменим к `.html` (node трактует расширение как модуль) — index.html не правился, проверка пропущена осознанно.

### Следующий спринт
- **SPA-V350:** возможные направления — кросс-сигнальная корреляция feed-health (несколько сигналов degraded одновременно = системный сбой источника, не точечный); ЛИБО валидация монотонности/непрерывности дат истории конкретного протокола (пропуски/возвраты дат назад во времени).

---

## Sprint v3.50 — 2026-05-30 — APY-feed date monotonicity / continuity validation (SPA-V350)

### Что сделано
- Добавлен **9-й** feed-health монитор `RiskMonitor.alert_apy_feed_date_monotonicity` — валидация МОНОТОННОСТИ и НЕПРЕРЫВНОСТИ дат истории каждого протокола в `data/historical_apy.json`. Закрывает data-integrity слепое пятно: все 8 предыдущих мониторов (stale / protocol-drop / tvl-drop / per-protocol anomaly / schema-drift / protocol-stale / aggregated summary / value-bounds) проверяли свежесть, счётчики, дельты, структуру, ТИПЫ и ДИАПАЗОН значений, но НИ ОДИН не проверял, что ДАТЫ записей истории конкретного протокола идут монотонно вперёд без разрывов. `date-regression` (`date[i+1] < date[i]`) и большой `gap` (> 72ч = ≥2 пропущенных дня в суточном фиде) скрыто ломают rolling-90d covariance/Kelly расчёт. Это была отложенная альтернатива из dispatch-ноты v3.49.
  - Метод зеркалит v3.49 `alert_apy_feed_value_bounds` 1-в-1: берёт ВСЮ history-list каждого протокола, парсит даты (`date`|`ts`|`timestamp`; epoch seconds / ISO с заменой Z / bare `YYYY-MM-DD`→полночь UTC; naive→UTC; ошибка→None). Протокол `bad` если: регрессия даты, gap соседних дат > `APY_FEED_MAX_DATE_GAP_HOURS=72.0`, или непарсимая/None дата. Протоколы с <2 валидными датами = OK (нечего сравнивать), 0 валидных дат = bad. apy/tvl-типы — забота schema-drift, не трогаются.
  - **Сигналы:** `unreadable` (нет файла/битый/нет пригодных протоколов), `too_few` (< `APY_FEED_MONO_MIN_PROTOCOLS=1`), `monotonicity_bad` (доля bad >= `APY_FEED_MONO_MAX_BAD_PCT=0.5`).
  - **Persistent state** `apy_feed_monotonicity_health_state.json` (`consecutive_mono`, `last_alerted_cycle`, `updated_at`, `prev_bad_keys`), порог=1 (fire на первом плохом цикле, refire на каждом следующем, healthy сбрасывает streak, state всегда обновляется). top-level try/except→False (НИКОГДА не raise), lazy TelegramSender. HTML msg `⚠️ <b>SPA APY Feed Date Monotonicity</b>` с перечислением нарушителей и причиной (regression / gap Xh / unparseable). Helpers `_load/_write_apy_feed_monotonicity_health_state`.
  - `export_data.py`: зеркальный try/except-блок «APY feed date monotonicity alert» сразу ПОСЛЕ value-bounds, ПЕРЕД feed_health_summary.
  - **Интеграция в v3.47-агрегатор** `feed_health_summary.py`: 9-й сигнал `("date_monotonicity", "apy_feed_monotonicity_health_state.json", "Date monotonicity", "consecutive_mono", 1)` + docstring 8→9. `index.html` рендерит чипы Feed Health динамически — правок не требует.

### Файлы
- `spa_core/alerts/risk_monitor.py` (modified — константы, поле `__init__`, метод + helpers)
- `spa_core/export_data.py` (modified — wiring)
- `spa_core/alerts/feed_health_summary.py` (modified — 9-й сигнал + docstring)
- `spa_core/tests/test_apy_feed_date_monotonicity_monitor.py` (new, 34 теста)
- `spa_core/tests/test_feed_health_summary.py` (modified — счётчики 8→9)
- `KANBAN.json`, `SPA_sprint_log.md` (bookkeeping)
- Бэкапы `.bak.v350` для изменённых файлов.

### Результаты тестов
- `test_apy_feed_date_monotonicity_monitor.py` — **43 PASS** (offline FakeSender, tmp_path).
- Регрессия (`value_bounds` 42 + `schema_drift` 36 + `protocol_stale` 21 + `protocol_anomaly` 30 + `feed_health_summary` 22 + `defillama` 38) — **189 PASS, 0 новых фейлов**.
- Независимая перепроверка оркестратором: `test_apy_feed_date_monotonicity_monitor` + `test_feed_health_summary` = 65 PASS. `py_compile` risk_monitor.py + export_data.py + feed_health_summary.py — OK. KANBAN.json валиден.

### Следующий спринт
- **SPA-V351:** кросс-сигнальная корреляция feed-health (несколько сигналов degraded одновременно = СИСТЕМНЫЙ сбой источника, эскалация severity, а не точечный алерт) — единственная нетривиальная оставшаяся идея в feed-health домене. **РЕКОМЕНДАЦИЯ ОРКЕСТРАТОРА:** feed-health домен насыщен (9 мониторов v3.40→v3.50); приоритизировать `SPA-V330`-style **architect review + KANBAN housekeeping** — пересмотреть, не пора ли переключиться с monitor-treadmill на FEAT-001/002 (Phase 3/4 live execution) или закрытие user-action backlog (RPC/Telegram/Safe secrets).

---

## Sprint v3.51 — 2026-05-30 — Architect review + KANBAN housekeeping (SPA-V330-style)

### Триггер
- v3.50 закончился на «0» → периодический architect review (каждые 5 спринтов). Рекомендация самого оркестратора из лога v3.50: feed-health домен насыщен, переключиться с monitor-treadmill на SPA-V330-style housekeeping.

### Что сделано
- **Architect review выполнен оркестратором напрямую.** `spa_core/dev_agents/architect.py` — LLM-обёртка над Claude API (`import anthropic`, `ANTHROPIC_API_KEY`, модель `claude-sonnet-4-6`); в автономной песочнице падает с `ModuleNotFoundError: No module named 'anthropic'`. Оркестратор сам является Claude-инстансом архитекторского уровня → review проведён напрямую в формате `review_backlog()` (next sprint / defer / risks). Полный отчёт: `DISPATCH_REPORT_2026-05-30_v351_architect.md`.
- **Ключевой вывод:** feed-health домен НАСЫЩЕН — 9 near-duplicate мониторов за v3.40→v3.50 (stale / protocol-drop / tvl-drop / per-protocol-anomaly / schema-drift / protocol-stale / aggregated-summary / value-bounds / date-monotonicity). Дальнейшие мониторы — убывающая ценность. Весь HIGH-приоритетный backlog заблокирован на **user_action** — это и есть критический путь к go-live (2026-07-15, ~7 недель). Monitor-treadmill возник потому, что feed-мониторы были единственной разблокированной код-работой.
- **KANBAN housekeeping:**
  - `IDEA-001` (Mac Mini Local Server) → `superseded` (дубликат `BL-001`).
  - **+SPA-BL-010** MEV Protection / Flashbots Protect RPC в `eth_signer.py` (HIGH) — следующий разблокированный код-спринт, замещает «монитор #10».
  - **+SPA-BL-011** GOVERNANCE: feed-health домен заморожен (HIGH, 0h) — монитор #10 только под НОВЫЙ класс отказа, не вариацию. Кросс-сигнальная корреляция дублирует v3.47 `feed_health_summary` → не считается новым классом.
  - **+SPA-BL-012** CRITICAL PATH: go-live user-action трекер (BL-004/005/006, SPA-BL-007/008/009).
  - Подтверждено `done`: V327 (live APY feed), V328 (Pendle-PT), V331 (pg-migration-prep, v3.41), V332 (go-live dashboard, v3.33–3.35) — во избежание повторного взятия.
- **Status pass НЕ применялся** — housekeeping = реальная работа (3 файла, 3 новых карточки, 1 dedup).

### Файлы
- `KANBAN.json` (modified — метаданные v3.51, dedup IDEA-001, +SPA-BL-010/011/012, +done SPA-V351-001)
- `SPA_sprint_log.md` (modified — эта запись)
- `DISPATCH_REPORT_2026-05-30_v351_architect.md` (new — architect review)
- Бэкапы `.bak.v351` (KANBAN.json, SPA_sprint_log.md)

### Результаты
- KANBAN.json валиден (json round-trip OK). Код не изменялся → регрессия не затронута.

### Следующий спринт
- **SPA-V352 = SPA-BL-010 MEV Protection (Flashbots Protect RPC)** — единственный разблокированный HIGH код-спринт. Альтернатива: при появлении user-action секретов — переключиться на FEAT-001 Phase 3 live execution. Feed-health монитор #10 ЗАПРЕЩЁН (SPA-BL-011) без нового класса отказа.

---

> **Sync-note (2026-05-31):** спринты v3.52–v3.57 выполнены и зафиксированы в `KANBAN.json` (dispatch-ноты `_v355/_v356_dispatch_note`, `last_dispatch_note`) — этот markdown-лог временно отставал. Краткая хронология: v3.52 MEV-protection wired во все adapter live-send пути; v3.53/v3.54 fix `eth_signer` 0x-prefix / `lstrip('0x')` baseline-багов; v3.55 MEV-статус в `adapter_status.json` + дашборд; v3.56 per-adapter `mev_routed` applicability (routed/unrouted списки); v3.57 проброс T1-адаптеров Aave V3 + Compound V3 в `adapter_status`. Money-moving код (`eth_signer`/`mev_protection`/адаптеры) на протяжении v3.55–v3.58 НЕ трогался — только read-only inspection + JSON-shaping + дашборд.

## Sprint v3.58 — 2026-05-31 — MEV-routing coverage summary + per-row MEV chip (SPA-V358)

### Триггер
- Последний завершённый спринт по KANBAN — v3.57 (`sprint_completed: v3.57`, `updated_by: orchestrator-v357`). Status pass запрещён → взят следующий разблокированный код-спринт. Это направление прямо названо в dispatch-нотах v3.55 («expose per-adapter MEV-routing applicability … in the same block») и v3.56 («per-adapter MEV in Go-Live table row-by-row»). НЕ feed-health (SPA-BL-011 заморозка соблюдена), НЕ money-moving (eth_signer/mev_protection/адаптеры не трогались), НЕ user-action-blocked.

### Что сделано
- **Backend `adapter_status.py` — derived `coverage` sub-block.** В `build_status_document()` после v3.56-формирования `routed_adapters`/`unrouted_adapters` добавлен `mev["coverage"] = {routed, total, coverage_pct}`. `coverage_pct = round(100.0 * routed / total, 1)` с защитой от деления на ноль (`if total else 0.0`) — пустой набор адаптеров даёт `0.0`, не `ZeroDivisionError`. Чисто stdlib, never-raises, JSON-safe. Дашборд теперь читает один headline-показатель вместо пересчёта на фронте. Текущее значение: **6/7 routed = 85.7%** (pendle-pt — единственный unrouted, BLOCKED/NotImplemented). Docstring модуля дополнен записью v3.58.
- **Front-end `index.html` — per-row MEV-чип.** `mapAdapterRecord` пробрасывает `mevRouted: !!rec.mev_routed`; добавлен helper `mevCell(a)` (зелёный `🛡 Protected` при routed, нейтральный `—` иначе и для embedded fallback-константы, где флага нет); в таблицу Go-Live добавлена колонка `<th>MEV</th>` (9-я) + соответствующий `<td>`. `mevBadge` теперь предпочитает backend-`coverage` (`N/M adapters routed (P%)`), с null-safe откатом на v3.56-математику `routed_adapters.length` для старых фидов.

### Файлы
- `spa_core/execution/adapter_status.py` (modified — `coverage` sub-block + docstring)
- `index.html` (modified — `mapAdapterRecord` mevRouted, `mevCell`, MEV-колонка, coverage в mevBadge)
- `spa_core/tests/test_adapter_status.py` (modified — +`TestMevCoverageSummary`, 9 тестов)
- `KANBAN.json`, `SPA_sprint_log.md` (bookkeeping)
- Бэкапы `.bak.v358` (adapter_status.py, index.html, test_adapter_status.py, KANBAN.json, SPA_sprint_log.md)

### Результаты тестов
- `test_adapter_status.py` (без сетевых LiveApy) — **102 passed**, включая новый `TestMevCoverageSummary` (9 тестов: наличие/типы ключей, `routed ≤ total`, `total == len(EXPECTED_PROTOCOL_KEYS)`, согласованность с routed/unrouted-списками, формула pct, границы 0–100, ZeroDivision-safe на пустом `_ADAPTER_SPECS`, JSON-сериализуемость).
- `MevCoverage`/`MevRouting`/`MevProtection`/`BuildStatus`-классы — **39 passed**.
- Регрессия `test_mev_wiring.py` + `test_mev_protection.py` — **57 passed, 0 новых фейлов**.
- `py_compile adapter_status.py` — OK. Smoke `build_status_document()`: `coverage={'routed':6,'total':7,'coverage_pct':85.7}`, все `mev_routed` булевы, `json.dumps` OK. `node --check` неприменим к `.html` (трактуется как модуль) — проверка пропущена осознанно; колонки header(9 th)/row(9 td) сбалансированы.
- LiveApy-тесты пропущены (сетевые, таймаутят в офлайн-песочнице) — код этих путей в v3.58 не менялся.

### Следующий спринт
- **SPA-V359:** домен adapter-status/MEV почти насыщён (coverage surface закрыт). Кандидаты: (a) рендер истории `feed_health_summary` per-signal `updated_at` на дашборде (UI, не новый монитор — SPA-BL-011 не нарушается); (b) консолидация adapter-status + feed-health + covariance-health в единый «Go-Live readiness score» (backend JSON + дашборд). **РЕКОМЕНДАЦИЯ:** критический путь к go-live (2026-07-15) — это user-action секреты (SPA-BL-007/008/009, BL-004/005/006), всё ещё blocked; код-работа остаётся surface/housekeeping до их разблокировки.

---
