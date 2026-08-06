---
trackerStatus:
  type: inbox
title: "Tier-B: 19 модулей числятся работающими, но различают протоколы побочными полями — предметных данных у них нет"
status: new
source: nimbalyst
created: 2026-08-06
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
