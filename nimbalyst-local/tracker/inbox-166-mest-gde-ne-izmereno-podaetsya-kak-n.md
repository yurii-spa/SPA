---
trackerStatus:
  type: inbox
title: "166 мест, где «не измерено» подаётся как «ноль»: инвариант #17 пропал из CLAUDE.md на 16 суток"
status: backlog
source: nimbalyst
created: 2026-09-11
---

## Что случилось и почему это важно

Инвариант #17 («там, где наблюдения нет, система обязана сказать „не знаю“, а не „всё
хорошо“» — решение владельца 23.08, ADR-129) **пропал из `CLAUDE.md` 27 августа**: доставка
`e1044b907` принесла свою правку поверх устаревшей копии файла и унесла пункт целиком.
Шестнадцать суток инвариант, который сторожит храповик, не существовал в файле, который
сессии читают первым.

За тот же срок класс вырос **со 192 мест до 325**: 177 новых подстановок вида
`doc.get("apy_pct") or 0.0` / `or {}` у писателей артефактов, 44 старых места ушли.
Из 177 проверены на «различает ли функция отсутствие»: **166 не различают** (11 различают
и будут переписаны формой, а не смыслом). Каждое такое место — это «не измерено», поданное
как «измерено и равно нулю».

Инвариант восстановлен из истории дословно, дверь доставки закрыта (сторож пропажи раздела
теперь видит и `CLAUDE.md`, положительный контроль — та самая авария побайтово), и добавлено
честное чтение `spa_core/utils/observation.py` — оно КОРОЧЕ подстановки, иначе класс будет
расти дальше сам собой (ADR-344).

Осталось разобрать сами места. Это НЕ косметика: пока они есть, CI шаг 2 красный, а шаги 3–4
не исполняются вовсе.

## Что делать

По каждому файлу (список ниже — замер 11.09, порядок по числу мест): прочитать каждое место и
решить ПО СУЩЕСТВУ, а не заменить форму:

1. отсутствие поля обязано давать названный третий исход (`unmeasured` / `None` / строка
   причины в отчёте), а не ноль и не пустоту;
2. пустой словарь/список и ноль остаются ЗНАЧЕНИЯМИ — их смысл не менять;
3. у каждого исправленного писателя — тест, который краснеет на возврате подстановки;
4. **в базу `spa_core/tests/absent_observation_baseline.json` дописывать запрещено** —
   она может только уменьшаться.

Проверять прогресс: `python3 -c "from spa_core.tests import _absent_observation as a; print(len(a.build_baseline()['signals']['or_falsy']['places']))"`.

### or_falsy: 177 новых мест
- `spa_core/monitoring/decision_record_verdict_sensitivity.py` — 16
- `spa_core/monitoring/ranking_tie_persistence.py` — 14
- `spa_core/telegram/bot.py` — 11
- `spa_core/monitoring/capital_evidence_coverage.py` — 10
- `spa_core/monitoring/cio_shadow_replay.py` — 10
- `spa_core/monitoring/ranking_tie_census.py` — 10
- `spa_core/monitoring/decision_journal_coverage.py` — 10
- `spa_core/tuner/allocation_tuner.py` — 8
- `spa_core/telegram/reports/daily.py` — 5
- `spa_core/monitoring/unevidenced_leg_causes.py` — 5
- `spa_core/monitoring/cio_failure_modes.py` — 4
- `spa_core/monitoring/shadow_blockade_attribution.py` — 4
- `spa_core/monitoring/arming_wall_order.py` — 4
- `spa_core/monitoring/hit_rate_selection_bias.py` — 4
- `spa_core/monitoring/findings_bridge.py` — 3
- `spa_core/monitoring/rebalance_cost_evidence.py` — 3
- `spa_core/tuner/portfolio_rebalancer.py` — 3
- `scripts/find_defillama_sources.py` — 3
- `spa_core/monitoring/cio_target_producers.py` — 3
- `spa_core/monitoring/journal_population_backfill.py` — 2
- `spa_core/monitoring/cio_explainability.py` — 2
- `spa_core/monitoring/house_view_gap.py` — 2
- `spa_core/paper_trading/concentration_analytics.py` — 2
- `spa_core/alerts/governance_watcher.py` — 2
- `spa_core/monitoring/agent_health_monitor.py` — 2
- `spa_core/monitoring/g1_verdict_recoverability.py` — 2
- `spa_core/monitoring/snapshot_minute_sensitivity.py` — 2
- `spa_core/monitoring/target_stability.py` — 2
- `spa_core/monitoring/audit_trail_rate_input_coverage.py` — 2
- `spa_core/monitoring/decision_audit_trail.py` — 2
- `spa_core/adapters/apy_aggregator.py` — 2
- `spa_core/strategy_lab/rates_desk/paper_rates.py` — 2
- `spa_core/monitoring/architecture_conformance.py` — 2
- `spa_core/monitoring/intraday_equity.py` — 1
- `spa_core/monitoring/decision_record_run_identity.py` — 1
- `spa_core/monitoring/apy_forecast_accuracy.py` — 1
- `spa_core/strategy_lab/swarm/guardian_forward.py` — 1
- `spa_core/monitoring/owner_decision_pending.py` — 1
- `spa_core/monitoring/system_health_monitor.py` — 1
- `spa_core/monitoring/run_axis_time_stitch.py` — 1
- `spa_core/monitoring/journal_backfill_material.py` — 1
- `spa_core/monitoring/cio_auto_execution_limits.py` — 1
- `spa_core/monitoring/cio_kill_switch_controls.py` — 1
- `spa_core/monitoring/rate_observation_census.py` — 1
- `spa_core/monitoring/intraday_rate_input_movement.py` — 1
- `spa_core/monitoring/marginal_apy_at_size.py` — 1
- `scripts/check_owner_order_starvation.py` — 1
- `spa_core/monitoring/cio_post_trade_verification.py` — 1
- `spa_core/strategy_lab/swarm/blend_forward.py` — 1
- `spa_core/paper_trading/allocation_rationale.py` — 1
- `spa_core/monitoring/day_replacement_verdict_loss.py` — 1
- `spa_core/paper_trading/shadow_trigger_eval.py` — 1
### except_success: 8 новых мест
- `spa_core/telegram/bot.py` — 3
- `spa_core/paper_trading/concentration_analytics.py` — 1
- `spa_core/paper_trading/cycle_gap_monitor.py` — 1
- `spa_core/telegram/owner_decisions.py` — 1
- `spa_core/monitoring/telegram_health.py` — 1
- `spa_core/monitoring/competitive_watch.py` — 1

## Как понять, что готово

`SPA_ENV=ci python3 -m pytest spa_core/tests/test_absent_observation_ratchet.py -q` зелёный:
число мест в дереве не больше базы, и член-в-член она совпадает с деревом.

## Что будет после

Шаг 2 CI перестанет краснеть на этой причине; станут видны шаги 3–4, которые не исполнялись
ни разу. И главное — писатели артефактов перестанут выдавать «не знаю» за «всё хорошо».
