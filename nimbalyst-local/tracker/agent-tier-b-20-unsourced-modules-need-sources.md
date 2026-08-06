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
