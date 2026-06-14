# ADR-031: Analytics Integration Architecture

Date: 2026-06-14
Status: Proposed
Author: SPA Architect

## Context

`spa_core/analytics/` содержит **578 модулей** (`__init__.py` исключён). Из них в
реальном контуре принятия решений (`cycle_runner.run_cycle()` →
`StrategyAllocator.allocate()` → `RiskPolicy` gate) сегодня участвуют только ~5:

- `spa_core/analysis/market_regime.py` (MP-534) — пишет `market_regime.json`, влияет косвенно.
- `spa_core/risk/emergency_breakers.py` (ADR-030) — Step 2b, HALT/PAUSE.
- `spa_core/risk/daily_limits.py` (MP-375) — Step 2a, DL-01..05.
- `spa_core/risk/policy.py` (MP-005) — детерминированный gate ПОСЛЕ аллокатора.
- `spa_core/governance/kill_switch.py` (MP-108) — Step 1b.

Остальные 573 модуля **advisory-only**: каждый пишет собственный ring-buffer
JSON-лог в `data/*_log.json`, но НИ ОДИН не влияет на веса аллокации.
`analytics_pipeline.py` (MP-663) и `analytics_runner.py` (MP-104) запускаются
**после** цикла и тоже ничего не возвращают в аллокацию — это чистая
пост-фактум отчётность. Жёстко зашитыми остаются ~8 модулей в pipeline.

### Ключевые факты о существующем контуре (важны для дизайна)

1. **Точка влияния на аллокацию уже есть.** `scoring_engine.py` считает 15
   детерминированных subscore-ов → numeric_score → grade (A/B/C/D) и пишет
   `data/risk_scores.json`. Аллокатор (`allocation_models.risk_adjusted_breakdown`)
   читает grade и применяет `GRADE_MULTIPLIERS_DEFAULT` (A=1.0, B=0.85, C=0.5,
   D=0.0 → исключение) к весам `apy_pct × multiplier`. **Это и есть готовый
   Tier-B канал**: аналитика должна вливаться в subscore-ы / grade, а не строить
   параллельный контур.
2. **Контур цикла — это лестница fail-safe гейтов** (regime → kill-switch →
   daily-limits → emergency-breakers → RiskPolicy). Все обёрнуты в `try/except`
   с fail-open/WARNING. Новый Tier-A гейт обязан следовать ровно этому паттерну.
3. **Контракт модулей единообразен.** Каждый модуль — pure-stdlib, read-only,
   atomic write, ring-buffer лог. 449 файлов имеют класс (`*Scorer`/`*Analyzer`/
   `*Predictor`/`*Monitor` с методом `.score()/.analyze()/.detect()/.check()`),
   188 — top-level функцию. Большинство риск-модулей возвращают `dict` с числовым
   score 0-100 и `risk_label` (NEGLIGIBLE…CRITICAL). Это позволяет
   унифицированный адаптер-обёртку.
4. **`risk_scores.json` регенерируется КАЖДЫЙ цикл** в Step 0b
   (`_refresh_risk_scores`) ПЕРЕД аллокатором — идеальное место подмешать аналитику.

## Категоризация модулей (с количеством)

Группировка по доминирующему ключевому слову имени файла (модуль может попадать
в несколько тем; ниже — основная):

| Тема (keyword) | Модулей | Назначение | Tier |
|----------------|---------|------------|------|
| yield / apy / forecast | 115+16+11 | доходность, прогноз APY | B (scoring) + C |
| risk (generic) | 78 | риск-скоринг протоколов | A/B |
| liquidity / liquidation | 32+6 | глубина, кризис, каскад ликвидаций | **A** + B |
| fee / gas | 27+12 | издержки, drag | B (apy-adjust) + C |
| position / portfolio | 17+16 | sizing, концентрация | B + C |
| staking / reward | 13+13 | стейкинг, эмиссия наград | B + C |
| cross_chain / bridge | 13+9 | мост-риск, арбитраж | **A** (bridge) + C |
| collateral | 13 | здоровье залога | A/B |
| stablecoin / depeg / peg | 12+4+3 | депег-риск | **A** |
| oracle | 8 | манипуляция оракулом | **A** |
| concentration / correlation | 12+5 | диверсификация | B |
| governance | 11 | управленческий риск | B + C |
| tvl | 10 | momentum, состав | B + C |
| insurance / audit | 8+2 | покрытие, аудиты | C |
| exit / withdrawal | 8+3 | exit-ликвидность, очередь вывода | **A** |
| stress / attack / contagion | 7+7+5 | стресс-тесты, атаки, заражение | **A** + C |
| unlock / sentiment | 5+3 | разлоки токенов, настроения | C |
| sharpe / sortino / drawdown / calmar | 2+1+4 | метрики перформанса | C (отчётность) |
| rebalance / momentum | 6+6 | ребаланс, моментум | B + C |
| report / summary / digest | ~12 | отчёты | C |

Итого: ~30 модулей кандидаты в **Tier-A**, ~180 в **Tier-B**, остальные ~370 —
**Tier-C** (отчётность/обогащение, не влияют на решение).

## Решение: 3-tier Signal Aggregator

Вводим единый агрегатор сигналов `signal_aggregator.py`, который встаёт в Step 0b
(перед аллокатором, после регенерации `risk_scores.json`). Он НЕ заменяет
существующие гейты — он добавляет два новых артефакта, которые потребляют
(a) новый Tier-A blocklist-гейт в `cycle_runner` и (b) `scoring_engine` (Tier-B).

### Tier A — Blocking signals (влияют на аллокацию напрямую)

**Назначение:** обнаружить условия, при которых протокол должен быть полностью
исключён из аллокации НЕМЕДЛЕННО (а не просто понижен в весе). Это
catastrophic-risk модули, способные обосновать `BLOCK`.

**Модули (топ-приоритет, ~12):**

1. `defi_stablecoin_depeg_risk_monitor` / `stablecoin_depeg_monitor` — депег стейблкоина (фундамент всего портфеля)
2. `defi_liquidation_cascade_risk_analyzer` / `protocol_defi_liquidation_cascade_risk_analyzer` — каскад ликвидаций
3. `defi_liquidity_crisis_predictor` / `liquidity_crisis_detector` — кризис ликвидности
4. `defi_oracle_manipulation_risk_scorer` / `defi_protocol_oracle_manipulation_risk_analyzer` — манипуляция оракулом
5. `defi_lending_protocol_bad_debt_monitor` — bad debt в кредитном протоколе
6. `defi_protocol_systemic_risk_contagion_modeler` — системное заражение
7. `defi_protocol_depeg_contagion_risk_analyzer` / `protocol_defi_depeg_contagion_modeler` — заражение от депега
8. `defi_protocol_exit_liquidity_analyzer` / `protocol_defi_exit_liquidity_depth_analyzer` — нет exit-ликвидности
9. `defi_protocol_withdrawal_queue_risk_analyzer` / `withdrawal_queue_risk_analyzer` — заблокированная очередь вывода
10. `defi_protocol_admin_key_control_risk_analyzer` — централизованный admin-key (rug risk)
11. `defi_protocol_token_bridge_security_risk_analyzer` — компрометация моста
12. `defi_protocol_sequencer_downtime_risk_analyzer` — даунтайм секвенсора L2

**Выход:** `data/analytics_signals_blocking.json`
```json
{
  "generated_at": "2026-06-14T08:00:00Z",
  "signals": {
    "<protocol>": {
      "signal": "BLOCK|WARN|OK",
      "reason": "depeg_risk_score=88 (CRITICAL): stablecoin off-peg 1.2%",
      "score": 88.0,
      "triggered_by": ["defi_stablecoin_depeg_risk_monitor"]
    }
  }
}
```
**Интеграция:** новый Step 2c-pre («Analytics Blocking Gate») в `cycle_runner`,
ПОСЛЕ аллокатора и ПЕРЕД RiskPolicy gate. Для каждого протокола с `signal=="BLOCK"`
его `target_usd` обнуляется, освободившийся капитал перераспределяется
пропорционально на разрешённые протоколы (как делает `_fill_remainder`), а если
блокируется слишком много — остаток уходит в cash. Любое срабатывание пишется в
`data/analytics_blocks.json` (ring-buffer 100) с correlation_id (MP-310).
Fail-open: исключение в гейте → WARNING + note, цикл продолжается без блокировки.

### Tier B — Advisory signals (влияют на risk-grade в scoring_engine)

**Назначение:** не блокировать, а **понизить вес** протокола. Вместо параллельного
множителя вливаемся в существующий канал: добавляем в `scoring_engine` новый
агрегированный subscore `analytics_composite` (вес 1.5x как у oracle_risk/
hack_history), который тянет числовое значение из агрегатора. Это автоматически
сдвигает grade и, через `GRADE_MULTIPLIERS`, веса аллокатора — без изменения
формата `risk_scores.json` и без новой логики в аллокаторе.

**Модули (~180):** все `*_risk_*`, `*_scorer`, `*_health_*`, `concentration`,
`correlation`, `fee_drag`, `gas_*`, `tvl_momentum`, `governance_*`,
`reward_dilution_*`, `collateral_health_*` и т.п. — то есть всё, что выдаёт
непрерывный risk-сигнал 0-100, но не катастрофический.

**Выход:** `data/analytics_signals_advisory.json`
```json
{
  "generated_at": "...",
  "signals": {
    "<protocol>": {
      "composite_risk_0_100": 42.0,
      "risk_multiplier": 0.93,
      "confidence": 0.81,
      "top_contributors": [
        {"module": "defi_protocol_reward_dilution_velocity_tracker", "score": 61, "weight": 0.04}
      ]
    }
  }
}
```
`risk_multiplier` нормирован в диапазон **0.5–1.5** и применяется как
дополнительный коэффициент к subscore-у `analytics_composite` в scoring_engine
(не напрямую к APY — чтобы не дублировать grade-механику).
**Интеграция:** `scoring_engine` читает этот файл в Step 0b при регенерации
`risk_scores.json`. `confidence` < порога (напр. 0.3) → сигнал игнорируется
(neutral 0.5), защищая от шумных/незаполненных модулей.

### Tier C — Background signals (ежедневная аналитика)

**Назначение:** обогащение контекста и отчётность. НЕ влияют на аллокацию.
Дашборд, тиршиты, отчёты, sentiment, unlock-календари, perf-метрики (Sharpe/
Sortino/Calmar/drawdown), insurance/audit-скоринг, прогнозы APY на горизонт.

**Модули (~370):** всё, что не вошло в A/B, плюс существующие
`analytics_pipeline`/`analytics_runner` сценарии.

**Расписание:** отдельный launchd `com.spa.analytics_tier_c.plist`, раз в день
в 05:00 UTC (за час до Tier-A/B прогрева в 06:00, за 3 часа до цикла в 08:00).
Пишет `data/analytics_report_full.json` (агрегат) для дашборда.

## Агрегация сигналов

**578 → composite — как:**
1. Каждый модуль обёрнут унифицированным адаптером `_ModuleAdapter`, который
   нормализует разный выход (число / dict со `score`/`risk_label` / grade)
   в кортеж `(protocol, score_0_100, confidence)`. Реестр обёрток —
   `analytics/_module_registry.py` (генерируется + ручная разметка tier/weights).
2. Per-protocol Tier-B: **взвешенное среднее** числовых score с весами по
   важности темы (oracle/depeg/liquidation выше, fee/gas ниже). Веса сумма=1.0.
3. **Противоречия:** Tier-A имеет абсолютный приоритет — если хоть один Tier-A
   модуль даёт BLOCK, протокол блокируется независимо от мягких Tier-B сигналов
   («худший выигрывает» для критических, «среднее» для advisory). Это убирает
   ситуацию «один модуль хвалит, другой блокирует».
4. **confidence** = доля модулей категории, реально вернувших валидный сигнал
   (не упавших / не получивших данные). Низкая confidence → сигнал смягчается к
   нейтральному, что предотвращает ложные блокировки из-за неполноты данных.

**Изоляция медленных/падающих модулей:**
- Каждый вызов модуля в отдельном `try/except` + per-module timeout (signal.alarm
  или ThreadPool future с `.result(timeout=)`). Упавший/таймаутнувший модуль
  логируется в `data/analytics_health.json`, его сигнал отбрасывается, цикл
  продолжается (`modules_failed` счётчик — как уже сделано в `analytics_pipeline`).
- **Circuit-breaker на уровне модуля:** модуль, упавший N раз подряд, временно
  отключается (cooldown), чтобы не тратить бюджет цикла.

## Производительность

578 модулей нельзя гонять синхронно каждые 30 мин. План:

1. **Tier-split по частоте:** только Tier-A (~12) + Tier-B критические (~40)
   гоняются каждый цикл. Полный Tier-B (~180) — раз в час (кеш). Tier-C — раз в день.
2. **Параллелизм:** `concurrent.futures.ThreadPoolExecutor` (модули I/O-light,
   pure-stdlib, GIL не критичен для смеси). Партиционирование по протоколам.
3. **Кеширование:** результат каждого модуля кешируется с TTL по tier-у
   (A=цикл, B=1ч, C=1д). `signal_aggregator` при отсутствии свежих входных
   данных переиспользует последний валидный сигнал (с пометкой `stale`).
4. **Partial execution:** агрегатор имеет дедлайн (напр. 10 сек на Tier-A+B-crit);
   модули, не успевшие к дедлайну, дают `stale`/neutral, цикл не ждёт.
5. **Бюджет цикла:** целевое добавление к 30-мин циклу — **< 10 сек** (Tier-A+B-crit
   параллельно). Полный прогон Tier-B/C — вне горячего пути.

## Новые файлы для создания

1. `spa_core/analytics/signal_aggregator.py` — реестр обёрток, параллельный запуск
   Tier-A + Tier-B-critical с timeout/cache/circuit-breaker; пишет
   `analytics_signals_blocking.json` и `analytics_signals_advisory.json`.
   CLI: `python3 -m spa_core.analytics.signal_aggregator --run [--tier A|B|all]`.
2. `spa_core/analytics/_module_registry.py` — декларативная карта
   `{module: {tier, theme, weight, adapter}}` для всех 578 модулей (генерится
   скриптом + ручная разметка ~50 критичных).
3. `scripts/com.spa.analytics_tier_c.plist` — ежедневный фоновый прогон Tier-C
   (05:00 UTC), пишет `analytics_report_full.json`.
4. `spa_core/tests/test_signal_aggregator.py` — тесты: BLOCK-приоритет,
   confidence-смягчение, fail-isolation, timeout, формат JSON.

## Изменения в существующих файлах

- `cycle_runner.py`:
  - Step 0b: вызвать `signal_aggregator.run(tier="A+Bcrit")` ПЕРЕД
    `_refresh_risk_scores` (чтобы scoring_engine увидел advisory-сигнал).
  - Новый **Step 2c-pre «Analytics Blocking Gate»** между аллокатором (Step 2) и
    RiskPolicy (Step 2c): читает `analytics_signals_blocking.json`, обнуляет
    `target_usd` для BLOCK-протоколов, перераспределяет, пишет `analytics_blocks.json`,
    добавляет correlation_id-событие. Fail-open.
- `spa_core/risk/scoring_engine.py`: добавить 16-й subscore `analytics_composite`
  (вес-boosted), источник — `analytics_signals_advisory.json`; при отсутствии файла
  → нейтральный 0.5 (как `fallback_used`). Формат `risk_scores.json` не меняется,
  только +1 ключ в `subscores`.
- `allocation_models.py`: **изменений не требуется** — grade-механика уже учитывает
  новый subscore автоматически через numeric_score.

## Риски

- **Over-blocking:** агрессивный Tier-A может загнать весь капитал в cash. Митигация:
  глобальный предохранитель — если Tier-A блокирует > X% капитала за цикл, гейт
  переходит в WARN-режим (только лог, без блокировки) и шлёт Telegram-алерт.
- **Качество входных данных:** многие модули рассчитаны на данные, которых нет в
  paper-feed. Митигация: confidence-смягчение + `_module_registry` помечает
  модули с реально доступными входами как `active`, остальные — `dormant` (логируют,
  но не влияют) до появления данных.
- **Двойной учёт риска:** часть тем уже в 15 subscore-ах scoring_engine. Митигация:
  Tier-B `analytics_composite` покрывает ТОЛЬКО темы, не пересекающиеся с
  существующими 15 subscore-ами (явный exclude-list в registry).
- **Бюджет производительности:** при росте числа active-модулей цикл может
  замедлиться. Митигация: дедлайн + partial execution + перенос в Tier-C.
- **Регрессия paper-track:** изменение grade-ов сдвинет историческую аллокацию.
  Митигация: ≥ 2 недели shadow-прогона (как требует RiskConfig) с
  `analytics_influence=False` флагом перед включением.

## Метрики успеха

- **% протоколов с аналитическим покрытием:** цель ≥ 90% активных адаптеров
  (16 в `ADAPTER_REGISTRY`) имеют ≥ 1 валидный Tier-A и ≥ 3 Tier-B сигнала.
- **% модулей, реально влияющих на решение:** с ~1% (5/578) до ≥ 35% (Tier-A+B active).
- **Добавленное к циклу время:** < 10 сек (Tier-A+B-crit, параллельно), измеряется в
  `cycle_health.json`.
- **Fail-isolation:** 0 падений цикла из-за аналитики (все ошибки → WARNING + note).
- **Точность блокировок:** доля BLOCK, подтверждённых пост-фактум (down-move
  протокола в течение N дней) — отслеживается в shadow-режиме.

## План внедрения (фазы)

1. **P1 (registry + aggregator, shadow):** создать registry + aggregator, гонять в
   shadow (пишет JSON, `analytics_influence=False`), сверять с реальностью 2 недели.
2. **P2 (Tier-B вкл.):** добавить `analytics_composite` subscore в scoring_engine,
   мониторить сдвиг grade-ов.
3. **P3 (Tier-A вкл.):** включить Blocking Gate в cycle_runner с глобальным
   предохранителем over-blocking.
4. **P4 (Tier-C launchd):** ежедневный фоновый прогон + дашборд-панель покрытия.
