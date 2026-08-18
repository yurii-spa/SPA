---
trackerStatus:
  type: agent-task
title: "20 модулей Tier-B помечены `unsourced` — поднять их обратно можно только источником, не правкой разметки"
status: backlog
created: 2026-08-06
---

## Откуда это

Цикл #134 закрыл `inbox-tier-b-19-modulei-chislyatsya-rabotayusc`: 20 модулей
Tier-B, различавшие протоколы ПОБОЧНЫМИ полями, получили пометку
`unsourced` и перестали складываться в `composite_risk_0_100` и в `confidence`
(`spa_core/analytics/_protocol_key_coverage.py`, статус виден в
`_meta.module_status`). Числа не удалены — они больше не выдаются за измерение.

Это честная фиксация состояния, а не его улучшение. Живой прогон Tier-B после
пометки: `ok=102`, `unsourced=20`, `blind=167` из 479 — работающий слой стал
меньше, потому что стал правдивым.

## Что нужно сделать

По каждому модулю — **источник**, а не правка разметки. Разметка
СГЕНЕРИРОВАНА: как только профиль начнёт отдавать все ключи, которые движок
читает, модуль уходит из неё сам при следующем `--emit-markup`.

Три группы (по природе недостающих ключей):

**А. Дешёвые — один ключ, и он структурный** (кандидаты в `_protocol_facts`,
если можно НАЗВАТЬ источник; иначе остаются помеченными):

| модуль | покрытие | чего нет |
|---|---|---|
| `defi_gas_cost_yield_drag_analyzer` | 0.90 | `harvests_per_year` |
| `defi_oracle_risk_scorer` | 0.88 | `max_price_deviation_pct` |

**Б. Нужен живой фид** — величина по природе динамическая, константа тут была
бы новой ложью:

- `defi_token_governance_power_analyzer` (0.57) — `active_voters_30d`,
  `avg_voter_turnout_pct`;
- `protocol_governance_attack_resistance_scorer` (0.27) — `quorum_pct`,
  `total_unique_voters_30d`, `governance_token_market_cap_usd`;
- `defi_protocol_oracle_manipulation_risk_analyzer` (0.29) —
  `oracle_sources_count`, `manipulation_cost_usd_estimate`;
- `protocol_oracle_risk_analyzer` (0.40) — `deviation_threshold_pct`,
  `has_fallback_oracle`, `staleness_threshold_minutes`;
- `protocol_liquidation_history_analyzer` (0.50) — `liquidations_count_30d`,
  `total_liquidations_30d_usd`;
- `defi_protocol_borrower_concentration_risk_analyzer` (0.50) —
  `top_borrower_amounts_usd`, `protocol_reserve_usd`;
- `lending_pool_utilization_analyzer` (0.38) — кривая ставки
  (`base_rate`, `slope1`, `slope2`, `optimal_utilization`, `reserve_factor`);
- `protocol_ecosystem_health_scorecard` (0.14) — `github_commits_30d`,
  `daily_active_users`, `revenue_monthly_usd` и ещё 9.

**В. Качественные атрибуты — фид не поможет, нужен реестр фактов, который
кто-то ведёт РУКАМИ и датирует** (или честное списание):

- `defi_protocol_regulatory_risk_scorer` (0.36) / `protocol_regulatory_risk_assessor`
  (0.60) — `entity_incorporated`, `dao_governance`, `has_received_sec_subpoena`,
  `team_is_doxxed`;
- `protocol_audit_coverage_scorer` (0.20) / `protocol_security_audit_tracker`
  (0.40) — `audit_count`, `auditor_tier`, `days_since_last_audit`,
  `formal_verification`;
- `defi_protocol_composability_risk_analyzer` (0.18) — `dependency_depth`,
  `base_protocol`, `auto_unwind_available`;
- `defi_protocol_mev_protection_effectiveness_analyzer` (0.55) —
  `has_sandwich_guard`, `has_commit_reveal`, `order_flow_auction`;
- `yield_bearing_stablecoin_comparator` (0.20), `defi_yield_bearing_collateral_analyzer`
  (0.27), `protocol_defi_yield_duration_mismatch_analyzer` (0.45),
  `protocol_defi_vault_fee_structure_breakeven_analyzer` (0.56).

## Правило, которое нельзя нарушить

**Молчаливый дефолт отсутствующего ключа запрещён в любом исходе.** Дописать
ключ в `_protocol_facts` можно ТОЛЬКО назвав источник; «поставим правдоподобное
значение, чтобы покрытие стало 1.0» — это ровно та авария, ради которой пометка
и заведена, только с обходом сторожа. Так же запрещено снимать пометку правкой
`_protocol_key_coverage.py` руками: файл производный, тест
`test_report_json_and_markup_agree` это стережёт.

## Как понять, что готово

Модуль ушёл из `UNSOURCED_DETAIL` после перегенерации
(`audit_tier_c_wiring_feasibility.py --tier B --emit-markup` в sandbox), и у
каждого добавленного факта в `_protocol_facts` назван источник и дата.
Частичный прогресс — норма: карточка закрывается по группам, а не целиком.

## Радиус

Advisory. RiskPolicy разметку не видит, Tier-A не потребляет, капитал не
двигается. Живой фид = новый источник данных ⇒ до его появления модуль обязан
ОТКАЗЫВАТЬ, а не считать по умолчанию.

*Заведена циклом #134 (сессия pid33901) как то, что он сознательно НЕ делал.*

---

## Разметка протухла на 7 записей (замер цикла #142, 2026-08-17)

Карточка говорит: «Разметка СГЕНЕРИРОВАНА: как только профиль начнёт отдавать все
ключи, модуль уходит из неё сам при следующем `--emit-markup`». Верно — но
`--emit-markup` с тех пор не запускался, а модули менялись. Замер на живом
реестре (sandbox-копия дерева):

| | число |
|---|---|
| записей в закоммиченном `_protocol_key_coverage.py` | **35** |
| `UNCOVERED` на свежем прогоне инструментом ДО правки #142 | **29** |
| `UNCOVERED` на свежем прогоне инструментом ПОСЛЕ правки #142 | **30** |

Заголовок карточки («20 модулей») тоже устарел: набор стал 35 ещё в цикле #138.

### Шесть записей — уже не `UNCOVERED`, а `NO_SCORE`

Все шесть — `data_dir`-семейство, покрытие 0.5, `missing_keys: ("data_dir",)`:

* `defi_protocol_vault_apr_lookback_window_selection_bias_analyzer`
* `defi_protocol_vault_apr_quote_staleness_analyzer`
* `defi_protocol_vault_headline_spot_snapshot_vs_twap_analyzer`
* `defi_protocol_vault_relative_yield_outlier_analyzer`
* `defi_protocol_vault_yield_realization_gap_analyzer`
* `defi_protocol_vault_yield_variance_drag_realization_analyzer`

Причина названа: `data_dir` они больше не спрашивают у записи, а берут из
`spa_core.utils.live_paths.sandboxed_state_path` (правка того же дня). Сегодня
они `NO_SCORE`, то есть выбывают из composite по ДРУГОЙ причине, и разметка
держит их за старую. Числа это пока не портит (в обоих случаях модуль в
composite не входит), но приговор в файле больше не соответствует улике.

### Одна запись — новая и настоящая

`protocol_tvl_filter` (+1 от правки #142): читает `tvl_trend_7d_pct` у
`generic_profile_for`, а тот его не отдаёт (ключ есть только в `facts_for`) ⇒
молчаливое «изменение TVL за 7 дней = 0 %» на каждом протоколе. Проверено на
исходнике модуля, не только вердиктом.

### Одна запись разметки СЛЕПОТЫ протухла в другую сторону (соседний файл)

`protocol_insurance_scorer` числится в `PROTOCOL_BLIND_MODULES`, а после починки
17.08 различает протоколы (замер: 67.71 против других значений). То есть
`run_tier_b` СЕГОДНЯ не исполняет модуль, который снова работает.

### Почему перегенерации НЕТ в этой итерации

`--emit-markup` — полный прогон 479 модулей, и он переразметил бы всё сразу,
смешав минимум три независимых дифа (правка #142 · `data_dir`-семейство ·
починка страхового скорера). Диф моей правки строго аддитивен (+1, −0), а вот
остальные 6 — вычитание из прод-разметки, то есть модули ВОЗВРАЩАЮТСЯ в
composite, и это заслуживает своей приёмки в обе стороны, а не хвоста к правке
инструмента. Названо здесь как отдельная итерация; правка `_protocol_key_coverage.py`
руками ЗАПРЕЩЕНА (файл производный, стережёт `test_report_json_and_markup_agree`).

**Группы А/Б/В карточки этим замером не закрыты**: источников не появилось ни у
одного модуля, и появиться от правки инструмента они не могли.

*Цикл #142.*

---

## Цикл #143 (2026-08-17): источников НЕ появилось ни у одного модуля — и вот каких именно данных нет

Отдельно называю это прямо, потому что предыдущие две итерации закрывали соседние
карточки и на этой оставляли строчку «группы А/Б/В не закрыты»: **ни один модуль из
разметки источника не получил.** Источники правкой инструмента не появляются, и появиться
не могли — инструмент отвечает на вопрос «чего не хватает», а не «где это взять».

Актуальное число — **36** записей в `_protocol_key_coverage.py`
(`AUDIT_GENERATED_AT` 2026-08-17T18:31:09Z, перегенерация предыдущего цикла). Заголовок
карточки («20 модулей») устарел дважды: 20 → 35 (#138) → 36.

### Чего именно не хватает — четыре разных класса, и лечатся они по-разному

**1. Временной ряд TVL — его у нас нет вообще.** `protocol_tvl_filter` (покрытие 0.6667)
ждёт `tvl_trend_7d_pct`. Ключ есть в структурной базе (`facts_for`), и «прокинуть его в
`generic_profile_for`» выглядит как правка на пять минут. **Это ловушка, проверено:**
`tvl_trend_7d_pct` равен `0.0` у ВСЕХ 35 протоколов базы — это не факт, а заглушка, и
`data/tvl_trend_report.json` пуст (`[]`). Проводка не дала бы источника, она дала бы
покрытие 1.0 и вывела бы модуль из разметки — то есть отмыла бы заглушку в измерение,
ровно та авария, ради поимки которой разметка и заведена. Нужен настоящий источник:
история TVL по протоколам (хотя бы 7 суточных точек), которую сегодня никто не пишет.

**2. `data_dir` — это вообще не факт про протокол** (6 модулей, все vault-семейства:
`..._vault_apr_lookback_window_selection_bias_...`, `..._vault_apr_quote_staleness_...`,
`..._vault_headline_spot_snapshot_vs_twap_...`, `..._vault_relative_yield_outlier_...`,
`..._vault_yield_realization_gap_...`, `..._vault_yield_variance_drag_realization_...`).
Замер #142 уже показал, что они спрашивают его не у записи, а берут из
`sandboxed_state_path`, и сегодня они `NO_SCORE`. Источник тут не нужен — нужна
перегенерация разметки, и она сама по себе не хвост к чужой правке (см. предыдущий раздел
этой карточки).

**3. Живой фид — величина по природе динамическая, константа была бы новой ложью.**
Поимённо, чего нет: участие в управлении (`active_voters_30d`, `avg_voter_turnout_pct`,
`quorum_pct`, `total_unique_voters_30d`, `governance_token_market_cap_usd`), конфигурация
оракула (`oracle_sources_count`, `deviation_threshold_pct`, `staleness_threshold_minutes`,
`has_fallback_oracle`, `manipulation_cost_usd_estimate`, `twap_window_seconds`), история
ликвидаций (`liquidations_count_30d`, `total_liquidations_30d_usd`, `peak_single_day_usd`),
концентрация заёмщиков (`top_borrower_amounts_usd`, `protocol_reserve_usd`), кривая ставки
(`base_rate`, `slope1`, `slope2`, `optimal_utilization`, `reserve_factor`) и активность
экосистемы (`github_commits_30d`, `daily_active_users`, `revenue_monthly_usd`,
`developer_count`, `integrations_count`). Ни одного из этих фидов у нас не подключено.

**4. Реестр качественных фактов, который кто-то ведёт РУКАМИ и датирует** — фид тут не
поможет в принципе: аудиты (`audit_count`, `auditor_tier`, `days_since_last_audit`,
`formal_verification`), регуляторика (`entity_incorporated`, `dao_governance`,
`has_received_sec_subpoena`, `team_is_doxxed`, `has_legal_wrapper`), защита от MEV
(`has_sandwich_guard`, `has_commit_reveal`, `order_flow_auction`), композиция
(`dependency_depth`, `base_protocol`, `auto_unwind_available`). Такого реестра у нас нет,
и завести его — решение про процесс (кто ведёт, как часто датирует), а не про код.

**5. Отдельно: часть модулей спрашивает не про протокол, а про ПОЗИЦИЮ** (`token`,
`vault`, `vault_apr_pct`, `nav_per_share_usd`, `health_factor`, `entry_value_usd`,
`days_held`). Профиль протокола им не подходит по существу — никакой фид этого не
починит, у них другой субъект. Для них честный исход — не источник, а списание либо
переезд на вход из книги позиций.

### Что не сделано и почему

Ни одного ключа в `_protocol_facts` не дописано (правило карточки соблюдено), разметка
руками не тронута (файл производный). Перегенерации не делал: диф Tier-C был предметом
этой итерации, а смешивать его с вычитанием шести `data_dir`-записей из прод-разметки —
значит лишить оба дифа приёмки.

*Цикл #143. Группы А/Б/В карточки остаются открытыми: источников нет.*

---

## Цикл 2026-08-18: разбор всех 36 записей по источникам — группа «а» ровно ОДНА, и её нельзя закрыть фактом

Задача была не «поднять 20 модулей», а разобрать каждый: есть ли у него настоящий источник.
Замер сделан в sandbox-копии дерева, живой `data/` не тронут.

### Что измерено

**160 различных недостающих ключей** на 36 модулях. Из них в структурной базе
`_protocol_facts` существуют **два**:

| ключ | что с ним | вердикт |
|---|---|---|
| `tvl_trend_7d_pct` | есть в `facts_for`, но **0.0 у всех 35 протоколов**, `data/tvl_trend_report.json` пуст | заглушка, не источник |
| `twap_window_seconds` | есть, **различается** (1800 у amm_twap, 0 у остальных) | источник есть, но у модуля-владельца ещё 4 ключа без источника |

Остальные 158 не отдаёт ни один адаптер (`spa_core/adapters/`: 0 совпадений по
`quorum_pct`, `audit_count`, `liquidations_count_30d`, `optimal_utilization`,
`github_commits_30d`, `deviation_threshold_pct`, …), ни фид DeFiLlama
(`spa_core/adapters/defillama_feed.py:206` отдаёт ровно `{"apy","tvl","pool_id"}`),
ни `data/`. Найденные при поиске совпадения в `data/*.json` — это ВЫХОДЫ самих
модулей (`data/composability_risk_log.json`, `data/yield_after_tax_drag_log.json`),
источником быть не могут.

Два кандидата в источники всё же есть, но оба частичные и датированы плохо:
`spa_core/risk/scoring_engine.py:225 BOOTSTRAP_PROTOCOLS` (`audit_count`,
`tvl_change_30d_pct`; шапка прямо называет это fallback'ом «когда DefiLlama
недоступен», `as_of` нет) и `data/incidents.json` (577 инцидентов, `by_protocol_summary`
на 16 slug'ов; `updated_at` 2026-06-21, `total_amount_lost_usd` = 5.6e13 — суммы
явно битые). Ни один модуль ими не закрывается целиком.

### Разбивка 36 записей

* **(а) источник ЕСТЬ и его хватает целиком — 1 модуль:**
  `protocol_defi_stable_yield_consistency_scorer` (все 5 ключей: `apy_history` ←
  `_apy_series`/`data/historical_apy`, остальные ← `_protocol_facts`).
* **(в) источник частичный — 16 модулей.** Проводить нельзя: закрыв 1–4 ключа из 8–12,
  получим более убедительное с виду число при тех же молча занулённых остальных.
* **(б) источника нет и взять неоткуда — 19 модулей** (живой фид управления/оракулов/
  ликвидаций/кривой ставки; реестр качественных фактов, который никто не ведёт;
  плюс модули, у которых субъект — ПОЗИЦИЯ, а не протокол). Пометка `unsourced` — верна.

**Ни одного факта в `_protocol_facts` не дописано** — дописывать нечего.

### Почему единственный модуль группы «а» всё равно нельзя «провести»

Он УЖЕ проведён в коде и работает честно; его пометка — артефакт замера. Инструмент
`audit_tier_c_wiring_feasibility.py:416` передаёт движку ТОЛСТУЮ запись
`generic_profile_for(proto)`, а прод-агрегатор (`signal_aggregator.py:450`) передаёт
голый контекст `{"cycle_ts", "protocol"}`. Толстая запись содержит `withdrawal_delay_days`
— один общий ключ с `_CTX_DOMAIN_KEYS` модуля, — поэтому `is_context_only` даёт False,
ветка контекста не берётся, и модуль судят по легаси-пути, которого в проде нет:

```
is_context_only(толстая запись) = False   collision keys: ['withdrawal_delay_days']
is_context_only(голый контекст) = True
probe_module(...) → verdict=UNCOVERED  basis=passed_record  eff_cov=0.2857
прод-путь _ModuleAdapter.run: aave_v3=68.51 morpho=45.50 spark=29.19 compound_v3=64.79
                              maple=dormant pendle=dormant __ctrl__=dormant
```

То есть значения РАЗЛИЧАЮТСЯ (реальный ряд APY) и модуль fail-CLOSED'ится там, где ряда нет.
Так же устроены ещё 9 модулей набора с веткой контекста (шесть `data_dir`-семейства +
`emergency_withdrawal_pause`, `vault_redemption_cooldown`, `vault_round_trip_cost`): все 10
судятся по `basis=passed_record`. **Осторожно:** у трёх из них ветка контекста сама молча
занулила ключи (у `defi_protocol_emergency_withdrawal_pause_risk_analyzer:483` не переданы
`annual_pause_probability_pct` и `historical_max_pause_days` ⇒ «вероятность паузы = 0»),
так что для них пометка верна по ДРУГОЙ причине, чем написано.

Починка — в инструменте (пробовать модуль тем же входом, каким его зовёт агрегатор), и это
отдельная итерация с перегенерацией разметки: правка `_protocol_key_coverage.py` руками
запрещена, а перегенерация смешала бы минимум четыре независимых дифа (см. разделы #142/#143).

### Найдено попутно: пять модулей отвечают числом за НЕСУЩЕСТВУЮЩИЙ протокол

`defi_protocol_cdp_stability_fee_analyzer` 100.0 · `defi_protocol_lending_market_health_scorer`
42.0 · `defi_protocol_vault_instant_exit_nav_discount_analyzer` 0.0 ·
`protocol_defi_position_health_monitor` 0.0 · `protocol_defi_yield_bearing_stablecoin_risk_analyzer`
70.0 — одинаково для `aave_v3` и для `__no_such_protocol__`. Фактов протокола они не читают
вовсе (ни `generic_profile_for`, ни `facts_for` в исходнике). Из composite они исключены уже
сегодня (и `blind`, и `unsourced`), вреда живым числам нет, но ярлык «различается побочными
полями» к ним не относится.

### Положительный контроль (новый файл, в обе стороны)

`spa_core/tests/test_unsourced_markup_positive_control.py` — 11 тестов, офлайн, ряды
синтетические в `tmp_path`, `data/` не читается и не пишется. Проверено мутациями:

| мутация | что краснеет |
|---|---|
| ветка контекста подставляет плоский `apy_pct` вместо ряда | `test_sourced_module_differentiates_on_real_series` |
| fallback вместо отказа при отсутствии ряда | `test_sourced_module_refuses_without_series` (2 из 3 параметров) |
| `tvl_trend_7d_pct` проведён в `generic_profile_for` | `test_unsourced_key_never_enters_profile_as_constant` + `test_tvl_trend_stub_is_not_promoted_into_profile` |
| модуль-константа убран из всех разметок | `test_constant_for_nonexistent_protocol_stays_out_of_composite` |

Тесты сформулированы двусторонне: появится настоящий источник истории TVL — значения начнут
различаться, и тест разрешит проводку сам; починится модуль-константа — ассерта про разметку
не будет вовсе.

*Группы «б» и «в» карточки остаются открытыми: источников по-прежнему нет. Группа «а» —
один модуль, и он ждёт не факта, а починки инструмента.*
