---
trackerStatus:
  type: inbox
title: "Tier-B: 19 модулей числятся работающими, но различают протоколы побочными полями — предметных данных у них нет"
status: done
source: nimbalyst
created: 2026-08-06
claimed_by: pid33901
claimed_at: 2026-08-06T12:52:52Z
---

## Находка

Замер цикла #133 (2026-08-06, sandbox-worktree от `origin/main` a4b7f088f,
новый `scripts/audit_tier_c_wiring_feasibility.py`):

**19 модулей Tier-B, которые аудит слепоты считает `sensitive` («работает,
различает протоколы»), различаются НЕ тем, о чём они.** Их движок читает у
записи предметные ключи, которых `generic_profile_for` не содержит: ключ молча
становится дефолтом (0.0 / False), а всё различие между протоколами приходит из
побочных полей вроде `utilization_rate_pct` или `tvl_usd`.

Покрытие ключей профилем (сколько из читаемых ключей профиль реально отдаёт):

| модуль | покрытие | чего нет |
|---|---|---|
| `defi_protocol_composability_risk_analyzer` | 0.18 | `dependency_depth`, `base_protocol`, `auto_unwind_available` |
| `defi_protocol_oracle_manipulation_risk_analyzer` | 0.29 | `oracle_sources_count`, `manipulation_cost_usd_estimate` |
| `defi_protocol_regulatory_risk_scorer` | 0.36 | `entity_incorporated`, `dao_governance`, `defi_category` |
| `defi_token_governance_power_analyzer` | 0.57 | `avg_voter_turnout_pct`, `active_voters_30d` |
| `defi_oracle_risk_scorer` | 0.88 | `max_price_deviation_pct` |
| `defi_gas_cost_yield_drag_analyzer` | 0.90 | `harvests_per_year` |

(полный список из 19 — в отчёте инструмента, `--tier B`)

## Почему это важно, а не придирка

Одинаковая константа видна глазом и ловится существующим аудитом слепоты.
**Правдоподобно различающееся число — нет:** оно проходит критерий `sensitive`,
попадает в `composite_risk_0_100` и в счётчик «работающего слоя», и выглядит
как измерение риска оракула/регуляторики/композабилити, будучи функцией
утилизации пула.

Это тот же класс, что закрытая карточка
`agent-insurance-scorer-fabricates-missing-tvl` (модуль перестал отказывать без
`tvl_usd` и подставлял казну как 2 % от TVL), только не в одном модуле, а в
массовой проводке фазы 2.

## Замер честный, не артефакт инструмента

Контекст-ветка этих модулей в проде — буквально
`extract_protocol_score(analyze([generic_profile_for(protocol)]), …)`
(проверено чтением `defi_oracle_risk_scorer.py:185`,
`defi_protocol_composability_risk_analyzer.py:104`). Инструмент зовёт ровно то
же самое, поэтому покрытие меряется на прод-пути, а не на выдуманном.

## Что сделать (радиус — отдельный, поэтому карточка, а не молчаливая правка)

По каждому из 19 — одно из трёх, **записью**:

1. **дописать факт в `_protocol_facts`**, если поле структурное и его можно
   назвать источником (как `utilization_pct` / `exit`), — тогда число станет
   тем, чем называется;
2. **взять живой фид**, если поле по сути динамическое (число активных
   голосующих, инциденты оракула) — и до появления фида модуль обязан
   отказывать (`None` → dormant), а не считать по дефолту;
3. **честно списать** — модуль остаётся в реестре с записанной причиной.

Молчаливый дефолт отсутствующего ключа запрещён в любом из трёх исходов.

## Как понять, что готово

`audit_tier_c_wiring_feasibility.py --tier B` не отдаёт ни одного `UNCOVERED`
среди модулей, которые аудит слепоты считает `sensitive`.

## Радиус

Tier-B — advisory: в hard-гейт RiskPolicy не входит, капитал не двигает
(инвариант «Risk Scoring v2 — только advisory»). Но число публикуется в
`analytics_report.json` и участвует в метрике «% работающего слоя», а часть
калибровки закреплена тестами — поэтому правка не молчаливая.

---

*Инструмент замера: `scripts/audit_tier_c_wiring_feasibility.py` (цикл #133),
критерий — variance И покрытие ключей, оба плеча fail-CLOSED.
Родственная находка по Tier-C: `inbox-tier-c-171-iz-180-modulei-ne-otvechayut`.*

---

## Разбор цикла #134 (2026-08-06): критерий выполнен — числа помечены, не удалены

**Что сделано.** Ни одно число не удалено и ни одно не подделано. Появился
второй сторож рядом с существующим сторожем слепоты, устроенный точно так же:

1. `scripts/audit_tier_c_wiring_feasibility.py --tier B --emit-markup` пишет
   вердикт `UNCOVERED` в `spa_core/analytics/_protocol_key_coverage.py`
   (`UNSOURCED_DETAIL`: покрытие + поимённый список отсутствующих ключей) —
   так же, как `audit_protocol_blindness.py --emit-markup` пишет слепоту.
2. `signal_aggregator.run_tier_b` обходится с помеченными модулями ровно как
   со слепыми: НЕ исполняет, ставит громкий статус `"unsourced"`, исключает из
   `composite_risk_0_100` И из числителя `confidence`. Модуль в обеих
   разметках получает `"blind"` — вердикт старше и строже.

**Почему разметка, а не проводка.** Ни один из недостающих ключей не является
фактом, который у нас есть: `oracle_sources_count`, `active_voters_30d`,
`has_received_sec_subpoena`, `audit_count`, `harvests_per_year` — это либо
живые фиды, которых нет, либо качественные атрибуты. Дописать их в
`_protocol_facts` = сочинить вход; ровно это цикл #133 измерил и отклонил для
Tier-C (`wirable=0`). Поэтому исполнен пункт **3 карточки** («честно списать —
модуль остаётся в реестре с записанной причиной»), причина записана поимённо,
и снимается она перегенерацией разметки, а не правкой файла.

**Помечено 20, а не 19.** Двадцатый — `protocol_defi_vault_fee_structure_breakeven_analyzer`,
который разметка слепоты числит `wide_ok` («честный coarse»). Списков-исключений
в генераторе нет намеренно: два аудита отвечают на РАЗНЫЕ вопросы
(«различается ли score» и «о том ли он»), и модуль, чьё различие пришло из
побочного поля, не измеряет свой предмет независимо от того, грубо он это
делает или тонко. Решение названо здесь, а не спрятано в коде.

| модуль | покрытие | нет ключей |
|---|---|---|
| `protocol_ecosystem_health_scorecard` | 0.14 | 12/14 |
| `defi_protocol_composability_risk_analyzer` | 0.18 | 9/11 |
| `protocol_audit_coverage_scorer` | 0.20 | 8/10 |
| `yield_bearing_stablecoin_comparator` | 0.20 | 8/10 |
| `defi_yield_bearing_collateral_analyzer` | 0.27 | 8/11 |
| `protocol_governance_attack_resistance_scorer` | 0.27 | 8/11 |
| `defi_protocol_oracle_manipulation_risk_analyzer` | 0.29 | 5/7 |
| `defi_protocol_regulatory_risk_scorer` | 0.36 | 9/14 |
| `lending_pool_utilization_analyzer` | 0.38 | 5/8 |
| `protocol_oracle_risk_analyzer` | 0.40 | 6/10 |
| `protocol_security_audit_tracker` | 0.40 | 3/5 |
| `protocol_defi_yield_duration_mismatch_analyzer` | 0.45 | 6/11 |
| `protocol_liquidation_history_analyzer` | 0.50 | 4/8 |
| `defi_protocol_borrower_concentration_risk_analyzer` | 0.50 | 3/6 |
| `defi_protocol_mev_protection_effectiveness_analyzer` | 0.55 | 5/11 |
| `protocol_defi_vault_fee_structure_breakeven_analyzer` | 0.56 | 4/9 (wide_ok) |
| `defi_token_governance_power_analyzer` | 0.57 | 3/7 |
| `protocol_regulatory_risk_assessor` | 0.60 | 4/10 |
| `defi_oracle_risk_scorer` | 0.88 | 1/8 |
| `defi_gas_cost_yield_drag_analyzer` | 0.90 | 1/10 |

**Критерий приёмки проверен машинно, а не глазом:** `UNCOVERED` в отчёте
инструмента = 20, в разметке = 20, множество «UNCOVERED без пометки» ПУСТО.
Закреплено тестом `test_no_sensitive_module_stays_silently_uncovered`.

**Эффект ИЗМЕРЕН живым прогоном** (sandbox-worktree и пристинный контроль
`89a0d366a`, живое `data/` не тронуто), Tier-B на `aave_v3` / `morpho`:

```
ДО:    ok=122  blind=167                composite 32.54 / 33.01  conf 0.2547
ПОСЛЕ: ok=102  blind=167  unsourced=20  composite 33.59 / 34.18  conf 0.2129
```

*(Поправка цикла #135: сессия #134 умерла до пуша, её отчёт перемерен. Всё
воспроизвелось, кроме стороны ПОСЛЕ — у #134 записано `33.82 / 34.42` при
стабильно измеряемых `33.59 / 34.18` (три прогона подряд). Внесено измеренное;
вывод не меняется.)*

`ok` упал ровно на 20 — то есть все двадцать ДЕЙСТВИТЕЛЬНО складывались в
composite как измерения. Сдвиг мал и направлен в консервативную сторону: обе
стороны и до, и после лежат ниже `MIN_CONFIDENCE = 0.30`, где сигнал и так
смягчается к нейтральному. «% работающего слоя» честно уменьшился.

**Приёмка.** +17 тестов, **15 из них красные на пристинном `origin/main`
89a0d366a** (два зелёных — регрессионные пины уже существовавшего критерия
инструмента, помечены как таковые). Четыре мутации красят ровно свою цель:
снятое исключение (3 теста), перепутанный приоритет blind/unsourced (2),
генератор пишет не только `UNCOVERED` (1), потерянная запятая в
одноэлементном кортеже (1). Обратные контроли на месте: без разметки
сочинённое число ОБЯЗАНО попадать в composite, и полное покрытие ОБЯЗАНО
давать `WIRABLE`. Откат после каждой мутации сверен sha256 байт-в-байт. Ни
один существующий тест не изменён (инв. #16).

**Радиус.** Advisory-слой: RiskPolicy разметку не видит, Tier-A не потребляет,
капитал не двигается. `data/`, живой трек, launchd, `landing/` не тронуты;
аудит гонялся только в sandbox.

**Что НЕ сделано и почему это отдельная карточка.** Поднять сами 20 модулей
(дописать факт / подключить живой фид) — работа с другим радиусом: часть
требует НОВЫХ источников данных. Список с поимённой причиной по каждому —
`agent-tier-b-20-unsourced-modules-need-sources`.

*Цикл #134, сессия pid33901.*
