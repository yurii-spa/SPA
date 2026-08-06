---
trackerStatus:
  type: inbox
title: "Tier-C: пять настоящих отказов агрегатора — два чинятся, три требуют фактов, которых нет"
status: new
source: nimbalyst
created: 2026-08-06
---

## Находка

Цикл #136 разобрал группу «64 failed» Tier-C. 59 из них оказались не отказами
модулей, а неспособностью агрегатора построить их доменный вход (переклассифицированы
в `unchecked` с названной причиной). **Осталось пять НАСТОЯЩИХ отказов** — эти
модули контекст принять МОГУТ и всё равно падают каждый прогон:

| модуль | исключение |
|---|---|
| `protocol_defi_interest_rate_kink_proximity_analyzer` | `TypeError: analyze() got an unexpected keyword argument 'context'` |
| `protocol_defi_validator_slashing_exposure_analyzer` | `TypeError: analyze() got an unexpected keyword argument 'context'` |
| `protocol_adoption_scorer` | `KeyError: 'unique_users_30d'` |
| `defi_protocol_flash_loan_attack_surface_analyzer` | `ValueError: Missing required keys: ['protocol_name', 'tvl_usd', 'single_block_borrowable_usd', …]` |
| `protocol_defi_protocol_maturity_score_analyzer` | `ValueError: Missing required fields: ['audit_count', 'bug_bounty_usd', 'chain_count', 'github_commits_90d', …]` |

## Два разных диагноза, не смешивать

**(а) Двое первых — дефект обвязки, чинится.** Диагноз снят с живого объекта:

```
signature: analyze(token: 'dict | None' = None, **kwargs: 'Any') -> 'dict'
source:    return analyze(token, config=self._config, **kwargs)
```

Классовая обёртка принимает контекст в `**kwargs` (поэтому `bind` проходит) и
пробрасывает его в модульную функцию `analyze`, которая аргумента `context` не
знает. Контекст при этом НЕ доезжает до `token`, ради которого всё писалось.
То есть обвязку начали и не довели: параметр есть, маршрут не проложен.
Починка — направить контекст в `token`, как у остальных обвязанных модулей.

**(б) Трое остальных — нехватка ФАКТОВ, и чинить их «дописав ключи» ЗАПРЕЩЕНО.**
`unique_users_30d`, `audit_count`, `bug_bounty_usd`, `single_block_borrowable_usd`
— это ровно тот класс входов, которые циклы #133/#134 измерили и отклонили:
их нет в `_protocol_facts`, и дописать их значит СОЧИНИТЬ вход. Правильный
исход для этой тройки — честная разметка (как `unsourced` в Tier-B), а не
выдуманные числа. См. `spa_core/analytics/_protocol_key_coverage.py`.

## Acceptance

- для (а): контекст доезжает до `token`, модуль перестаёт падать ИЛИ получает
  честный не-ok статус по доменной причине; тест-репродукция краснеет на
  сегодняшнем коде;
- для (б): решение записано (разметка/списание), ни одного нового ключа в
  `_protocol_facts` без источника факта;
- радиус измерен до правки, контроль в обе стороны, инв. #16.

## Радиус

Tier-C advisory, в hard-гейт RiskPolicy не попадает. Но `signal_aggregator`
общий для Tier-A/B/C — правка обвязки конкретных модулей радиус не расширяет,
правка адаптера расширяет (урок #136: аннотация не гарантия, Tier-A ловится
`test_tier_a_protocol_context.py`).

*Родительская карточка: `inbox-tier-c-171-iz-180-modulei-ne-otvechayut`. Цикл #136.*
