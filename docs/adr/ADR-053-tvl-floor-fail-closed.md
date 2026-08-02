# ADR-053: TVL-floor становится fail-CLOSED (провенанс TVL + отмена $20M-фабрикации)

**Дата:** 2026-08-02
**Статус:** Accepted
**Связано:** MP-005 (RiskPolicy gate), MP-1180 (registry fallback), MP-011 (allocator TVL-filter),
`.claude/rules/risk-engine.md` («Fail-CLOSED», «Stale-фид ⇒ протокол не берётся в свежую аллокацию»)

---

## Контекст (аудит 2026-08-02)

TVL-floor ($5M, `RiskConfig.min_tvl_usd`) фактически был **декоративным**:

1. **Фабрикация $20M в гейте.** `spa_core/paper_trading/risk_gate.py` (MP-1180): при
   отсутствии живого TVL подставлялся литерал `20_000_000.0`, выбранный так, чтобы
   floor-проверка **всегда проходила**. Сетевой сбой молча превращал hard-check в no-op —
   любой пул из registry получал свежий капитал без какой-либо верификации ликвидности.
2. **Статические константы в адаптерах.** ~22 адаптера возвращают `tvl_usd` из
   захардкоженной константы класса `TVL_USD` (напр. `aave_v3_base_adapter.py` = $400M
   образца 2026-06, `silo_arbitrum_usdc_adapter.py` = $12K — навсегда ниже floor).
   Гейт не отличал живой TVL от committed-литерала — константа проходила floor «как живая».
3. `adapter_registry.json` не содержит **ни одного** `tvl_usd` → каждый registry-fallback
   пул получал ровно $20M.

Это нарушало оба инварианта risk-engine.md: «Fail-CLOSED: при нехватке данных — отказ, никогда
не угадывать в пользу входа» и «никаких fake-fallback'ов».

## Решение

### 1. Провенанс TVL: `tvl_source` (контракт «live | static | None»)

- `YieldInfo` (`spa_core/adapters/base_adapter.py`) получает поле
  `tvl_source: Optional[str] = None`. `"live"` — TVL получен из живого фида **в этом вызове**;
  `"static"` — committed-константа; `None` — не задекларировано.
- **Fail-closed по умолчанию:** любое значение, кроме `"live"`, трактуется потребителями как
  static/unverified. Адаптер, не доказавший живость TVL, не проходит floor. Это покрывает все
  ~22 статических адаптера **одной точкой enforcement'а** (оркестратор+гейт), без правки 22 файлов —
  и автоматически любой будущий адаптер.
- `"live"` проставили адаптеры, реально берущие TVL из фида: `aave_v3`, `morpho_blue`,
  `yearn_v3`, `euler_v2`, `maple` (DeFiLlama `get_tvl`, None при сбое), `pendle_adapter`
  (Pendle API). `compound_v3_adapter` явно помечен `"static"` (константа $1.5B).
- Оркестратор (`adapter_orchestrator._run_one_adapter`) нормализует: число без декларации
  live → `"static"`; нет TVL → `None`.

### 2. Гейт (`risk_gate._apply_risk_policy_gate`): floor проверяется только живым TVL

- **$20M-фабрикация удалена полностью.** Registry больше не источник TVL (его `tvl_usd`,
  если появится — литерал, не верификация). APY-fallback MP-1180 сохранён без изменений.
- Пул проходит floor-проверку **только** при `tvl_source == "live"` и конечном TVL > 0.
  Живой TVL ниже $5M — по-прежнему blocking violation (floor реален).
- Пул с неверифицируемым TVL (missing / zero / static / без меты) — **fail-closed per-pool**:
  - target капится на текущую удерживаемую позицию: `min(target, held)` — hold и reduce
    разрешены (de-risk не блокируем), **свежий капитал — нет**;
  - если позиции нет — пул исключается из target'а («не берётся в свежую аллокацию»,
    как для stale-фидов);
  - замороженные пулы репортятся в `warnings` + новом поле `tvl_unverified` и в notes цикла
    (`risk_policy: TVL unverified (fail-closed, no fresh allocation): …`) — аудируемо;
  - замороженный удерживаемый пул **продолжает учитываться** в кумулятивных лимитах
    (T2-total, концентрация) через `state.positions`.
- Гейт получает `current_positions` от `cycle_runner` (новый опциональный параметр).
- PRESENT non-finite TVL (NaN/Inf) — по-прежнему corrupt-feed → blocking violation (P5-1).

### 3. Семантика «per-pool fail-closed» vs старое «block-all»

До ADR-053 пул без registry-записи с TVL=0 давал violation, блокировавший **весь** ребаланс
(историческая причина появления $20M-фабрикации). Теперь недоказуемый пул замораживается
индивидуально, а верифицированная часть книги продолжает работать: сетевой blip не
останавливает ребаланс и не распродаёт книгу, но и не получает выдуманного TVL.
Forced-sell замороженных позиций НЕ делается — контроль удерживаемого риска остаётся за
kill-switch/DL-гейтами/position-monitor (их данные — drawdown, не TVL).

### 4. Pre-cutover gate: новый дриль `TVL_UNVERIFIED_FREEZE`

`pre_cutover_gate.py` теперь ASSERT'ит все три формы: (a) потерянный фид на held-пуле →
cap-at-held; (b) static-константа → no fresh capital; (c) неизвестный пул → drop. Плюс
дриль `RISKPOLICY_BLOCK` переведён на live-помеченную фикстуру.

## Последствия

- **compound_v3 (T1-якорь) перестаёт получать свежий капитал**, пока не начнёт репортить
  живой TVL (константа $1.5B честно помечена static). Держать/сокращать можно. Follow-up:
  дать compound_v3 живой TVL (DeFiLlama Comet USDC), после чего он снова eligible.
- Пулы вне оркестраторного снимка (morpho_steakhouse, spark_susds, aave_arbitrum и т.д.)
  не получают свежих аллокаций, пока их TVL не станет живым/верифицируемым. Существующие
  позиции удерживаются. Это честная цена fail-closed: floor больше не декоративен.
- Аллокаторная фабрикация `_REGISTRY_FALLBACK_TVL_USD` ($50M) в `allocator.py` остаётся
  ranking-предположением ВНЕ hard-гейта (гейт её больше не пропустит) — кандидат на
  следующую итерацию той же честности (пометить static + учесть в feed_coverage).
- `RiskConfig` / RiskPolicy v1.0 **не тронуты** — пороги те же, изменился только источник
  данных для проверки (никакой выдуманный TVL больше не проходит floor).

## Верификация

- `spa_core/tests/test_cycle_runner_policy_gate.py` переписан на новый контракт
  (MP-1180 APY-fallback сохранён; TVL fail-closed запинен: cap-at-held, drop, static,
  registry-не-источник, live-below-floor блокирует, frozen-held в кумулятивных капах).
- Дриль `TVL_UNVERIFIED_FREEZE` в pre_cutover_gate.
- Полный `spa_core/tests/` прогнан (см. коммит).

---

## Addendum (2026-08-02, follow-up выполнен): live TVL для compound_v3 + парк адаптеров

Follow-up из «Последствий» закрыт тем же днём:

- **compound_v3 снова может проходить floor**: `compound_v3_adapter.py` получил живой
  DeFiLlama-фид TVL (`project=compound-v3, symbol=USDC, chain=Ethereum`, инжектируемый
  `feed=` как в `aave_v3.py`). `get_yield_info()` репортит живой `tvlUsd` c
  `tvl_source="live"`; при сбое фида — прежняя константа TVL_USD, честно помеченная
  `"static"` (гейт её floor'ом не пропустит). `health_check()`/`to_dict()` репортят
  `tvl_source`. Legacy-модуль `compound_v3.py` (собственный live-fetch) штампует
  `"live"`/`None` по факту наличия живого значения.
- **11 адаптеров парка перестали выбрасывать живой tvlUsd**: `aave_v3_base`,
  `silo_arbitrum_usdc`, `aerodrome_usdc`, `dolomite_arbitrum_usdc`,
  `moonwell_base`, `morpho_blue_base`, `velodrome_optimism`,
  `extra_finance_base`, `pendle_pt_usdc`, `pendle_pt_susde`, `btc_lending` — каждый уже
  выбирал лучший живой пул (`_find_best_*_pool` / `_find_pool` / `get_tvl`), но репортил
  committed-константу. Теперь `get_yield_info()` отдаёт живой `tvlUsd` выбранного пула с
  `tvl_source="live"`, константа осталась только как помеченный `"static"`-фолбэк
  (never stamp "live" on a constant). У `pendle_pt_*` молчаливый фолбэк
  `fetch_tvl()` разделён на `_fetch_live_tvl()` (live | None) + прежний фолбэк.
- Чисто статические адаптеры (sdai, sfrax, spark_susds и т.п. — без живого фида) НЕ
  тронуты: их покрывает оркестраторная нормализация (numeric без live-декларации →
  `"static"`), как и задумано одной точкой enforcement'а.
- Тесты: провенанс-кейсы live/static добавлены в `spa_core/tests/test_tvl_provenance.py`
  (compound_v3 с FakeFeed) и в адаптерные тесты (`tests/test_aave_v3_base_adapter.py`,
  `tests/test_silo_dolomite_arb.py`, `tests/test_pendle_pt_adapters.py`,
  `tests/test_extra_finance_base_adapter.py` — прежний тест пиновал константу при живом
  фиде и переписан на новый контракт). Все тесты офлайн (fake feeds / mocked urlopen).
