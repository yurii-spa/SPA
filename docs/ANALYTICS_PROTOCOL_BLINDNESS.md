# Analytics Tier-B — дифференциальный аудит протокол-слепоты (2026-08-02)

**TL;DR:** из 519 Tier-B модулей **ни один не выдаёт протокол-специфичный сигнал**.
150 «ok»-модулей — все `blind_constant`: возвращают один и тот же score для
aave_v3, maple, pendle **и для заведомо несуществующего контрольного протокола**
(132 из 150 — константа `0.0`). До фикса эти константы складывались в
`composite_risk_0_100 ≈ 8.6` → фиктивный `risk_multiplier ≈ 1.41` («−41% риска»)
для **любого** протокола одинаково, а `scoring_engine.analytics_composite`
получал завышенный safety-subscore ≈0.91 вместо честного 0.5. После фикса
Tier-B честно отвечает «не знаю»: composite 50.0, multiplier 1.0, confidence 0.

Слой advisory-only (`scoring_engine` / `analytics_composite`); money-path
(RiskPolicy, kill-switch) аналитику не читает и не тронут.

---

## Контекст

Audit 2026-08-02 (первая фаза): в `spa_core/analytics/signal_aggregator.py`
убран no-arg fallback в `_ModuleAdapter._invoke` — раньше модуль, не принявший
protocol-контекст, молча исполнялся без аргументов на встроенных demo-данных.
Статусы стали громкими (`ok/unchecked/failed/dormant/timeout` → health-лог +
`_meta.module_status`). Но 150 модулей, принимающих `context`, всё равно давали
байт-в-байт одинаковый composite для разных протоколов → слепота ушла с уровня
адаптера, но осталась **внутри модулей**.

## Метод (дифференциальный)

`scripts/audit_protocol_blindness.py` — каждый модуль прогоняется через тот же
`_ModuleAdapter`, что и в проде (timeout 3s), для пяти прогонов:

| Прогон | Зачем |
|---|---|
| `aave_v3`, `maple`, `pendle` | реальные протоколы: различаются ли score |
| `aave_v3` повторно | ловит недетерминизм (различие ≠ чувствительность) |
| `__nonexistent_control_protocol__` | модуль, отдавший тот же score для несуществующего протокола, гарантированно не читает `ctx["protocol"]` |

Классификация ok-модулей: `sensitive` (score различается между реальными
протоколами) / `nondeterministic` / `blind_constant` (одинаков везде, включая
контроль) / `blind_equal` (одинаков на реальных, но контроль повёл себя иначе —
код читает протокол, данных нет). Прогон — только в sandbox (модули пишут
собственные `data/*_log.json` относительно корня репо).

## Результаты Tier-B (519 модулей)

| Статус | N | Что это |
|---|---|---|
| `blind_constant` | **150** | принимают context, игнорируют протокол → константа (132× `0.0`, остальные 18 — от 10 до 100) |
| `sensitive` | **0** | — |
| `unchecked` | 203 | нет entrypoint'а, принимающего protocol-контекст |
| `failed` | 149 | исключение при вызове с контекстом (82× `AttributeError: 'str' object has no attribute 'get'` — entrypoint ждёт другую структуру данных, не protocol-контекст; 16× `TypeError: analyze`; хвост мелочи) |
| `dormant` | 17 | вызвались, результат не коэрсится в score |

Повтор aave_v3 стабилен у всех 150 → константы детерминированные (не шум).
Распределение констант: `{0.0: 132, 10: 2, 12.5: 1, 20: 1, 30: 1, 35: 1, 40: 1,
42: 1, 50: 1, 55: 1, 65: 1, 70: 2, 75: 1, 100: 4}`.

## Tier-A — ПОЧИНЕН (2026-08-02, вторая фаза)

Было (первая фаза, тем же методом): **9 failed + 3 unchecked, 0 сигналов** —
блокирующий слой фактически мёртв (fail-open → «OK» для всех протоколов).

Фикс: все 12 модулей проведены поимённо через новый структурный факт-слой
`spa_core/analytics/_protocol_facts.py` (35 протоколов whitelisted-universe:
chain/sequencer/bridge, пег-профили underlying-активов, oracle/admin-профили,
exit/withdrawal-механика, bad-debt/systemic-структура). Каждый модуль строит
из фактов СВОИ доменные входы и прогоняет их через СВОЙ движок (no-fork);
контекст-пути не пишут ring-buffer логов. После фикса: **10 sensitive +
2 blind_equal** (bridge/sequencer — все три аудит-протокола mainnet → честный
0; на L2-протоколах различаются).

Честная рамка: это КУРИРОВАННЫЕ СТРУКТУРНЫЕ КОНСТАНТЫ (as_of в файле), не
live-телеметрия; live-пег/live-TVL сознательно не в 3s-timeout blocking-слое.
Калибровка: структурные скоры whitelisted-протоколов ≤ WARN (<70) — BLOCK
зарезервирован за живыми событийными сигналами; исключение — advisory
BTC-адаптеры (`cbbtc_lending` admin-key 89.7 BLOCK: custodial-кастоди, честно;
IS_ADVISORY → никогда не аллоцируется). Инвариант запинен гард-тестом
`spa_core/tests/test_tier_a_protocol_context.py` (sensitivity, детерминизм,
unknown→dormant, no-BLOCK-for-allocatable). Живая книга (morpho_steakhouse /
spark_susds / susde / pendle / extra_finance_base): максимум WARN — деплой
фикса аллокации НЕ меняет. Money-path по-прежнему не зависит от Tier-A.

## Фикс (advisory-слой)

1. **Разметка:** `spa_core/analytics/_protocol_blindness.py` — сгенерированный
   аудитом `PROTOCOL_BLIND_DETAIL` (150 модулей → подтип). Перегенерация:
   `python3 scripts/audit_protocol_blindness.py --emit-markup` (в sandbox).
2. **Потребление:** `run_tier_b` модули из разметки **не исполняет**
   (детерминированно и дешевле — экономия 150 прогонов/протокол/час), пишет
   громкий статус `blind` (health-лог + `_meta.module_status.counts.blind`) и
   исключает их из composite **и из числителя confidence** — confidence теперь
   отражает только реально протокол-специфичные сигналы.
3. **Итоговое поведение сегодня** (0 живых protocol-специфичных модулей):
   composite 50.0 / multiplier 1.0 / confidence 0.0 → `analytics_composite`
   в scoring_engine = нейтральные 0.5 (фиктивный бонус ≈0.91 снят).
4. Tier-A разметку сознательно **не потребляет** (worst-wins, не weighted;
   и его 12 модулей всё равно не дают сигналов — см. выше).

Гард-тест `test_real_markup_matches_registry` ловит дрейф разметки при
переименовании модулей в реестре; поведенческие тесты —
`spa_core/tests/test_signal_aggregator.py` (blind не исполняется, не в
composite, не в confidence; при 100% слепом реестре Tier-B нейтрален).

## Ограничения и follow-ups

- Дифференциальный тест — необходимое, не достаточное условие: модуль, читающий
  протокол, но возвращающий случайно равные score, попал бы в `blind_equal` —
  таких не оказалось (все 150 — `blind_constant` по контролю).
- Разметка эмпирическая и снимается перегенерацией: починенный модуль (начал
  реально читать `ctx["protocol"]`) надо убрать из разметки тем же скриптом.
- ✅ Follow-up (1) СДЕЛАН (2026-08-02, вторая фаза): 12 Tier-A модулей
  починены поимённо → 10 sensitive + 2 blind_equal (см. секцию Tier-A выше).
- ✅ Follow-up (2) СДЕЛАН частично (та же фаза): 81 модуль с общим
  `AttributeError: 'str'...` проведён массово (AST-вставка единой
  контекст-ветки: `_protocol_facts.generic_profile_for` → собственный движок
  модуля → `extract_protocol_score` из вложенного агрегата). Итог Tier-B:
  **sensitive 0 → 12**, failed 149 → 68 (остались другие классы сигнатур:
  16× `TypeError: analyze` + хвост), dormant 17 → 48 (движок отработал, но
  score не извлекается — громко), blind_equivalent 150 → 188 (38 новых
  blind_equal — на одиночном профиле их метрика дегенеративна, напр.
  portfolio-корреляция → размечены и скипаются). Разметка перегенерирована
  тем же скриптом. Известное ограничение слоя коэрции (не новое): у
  quality-скоров (higher=better) знак не различается — наследие
  `*_score`-fallback (MP-1305).
- Оставшиеся follow-ups: (a) 68 failed других классов сигнатур; (b) 48
  dormant — научить extract_protocol_score их выходным форматам; (c) судьба
  203 unchecked (нет context-entrypoint'а вовсе) — чинить или вычищать из
  реестра; (d) live-overlay поверх структурных фактов (live-пег/TVL) —
  снимет WARN-потолок и откроет BLOCK-пространство Tier-A.

*Полный JSON-отчёт со всеми прогонами воспроизводится скриптом; классификация
150 слепых модулей закоммичена в `_protocol_blindness.py`.*
