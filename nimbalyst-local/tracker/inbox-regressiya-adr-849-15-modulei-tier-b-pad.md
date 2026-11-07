---
trackerStatus:
  type: inbox
title: "Регрессия ADR-849: 15 модулей Tier-B падают с 02.11 — default_file(None) роняет «не писать лог»"
status: done
source: nimbalyst
created: 2026-11-06
priority: high
twin_key: "sha256:f27f0acc2c1599f45e83305948d20c328e3f220ab51dbf8b4d80a8e70f206bbf"
intake_kind: task
acceptance_probe: tier_b_protocol_path_survives_a_disabled_log
status_trail:
  - "2026-11-07T22:17:01.713052+00:00 new -> in-progress · queue.set_status · cycle-26318"
  - "2026-11-07T22:31:12.470027+00:00 in-progress -> done · queue.set_status/closed_by:cycle-26318/evidence:проба tier_b_protocol_path_survives_a_disabled_log: not_satisfied (15 из 19 названы) -> satisfied (19 вызвано, падений нет); ADR-948 на origin 5a226e92d; контроль в обе стороны test_tier_b_disabled_lo · cycle-26318"
---

## Что случилось

С **2026-11-02 17:58Z** (первый часовой прогон Tier-B после `df6a24a07`, цикл #1013, ADR-900) **15 модулей Tier-B
перешли в `failed`** (`data/analytics_signals_advisory.json` → `_meta.module_status.counts.failed = 15`; 31.10 было 0).
`ok` упал 101 → 87, `modules_ok` у каждого протокола −15 (aave_v3 85, pendle 64).

## Причина (воспроизведено в одноразовом дереве на `origin/main` 912f828ff)

Все 15 модулей зовут себя протокольным путём `analyze(_legacy, config={"log_path": None})` — `None` значит
«лог не писать». Переписка ADR-849 §2 обернула путь в
`_default_file(cfg.get("log_path", _LOG_PATH), _LOG_PATH_AT_IMPORT)`, а `spa_core/utils/data_dir.py::default_file`
начинается с `os.fspath(path)` ⇒ `TypeError: expected str, bytes or os.PathLike object, not NoneType`.
`default_file(None, '/x/y.json')` падает отдельно, без модуля. У всех 15 в теле ровно одно `"log_path": None`.

Модули: defi_protocol_borrow_rate_volatility_forecaster, defi_protocol_gas_cost_breakeven_analyzer,
defi_protocol_gauge_emission_decay_forecaster, defi_protocol_rebase_token_yield_normalizer,
defi_protocol_reward_claim_timing_optimizer, defi_protocol_reward_dilution_velocity_tracker,
defi_protocol_risk_adjusted_yield_hurdle_analyzer, defi_protocol_stablecoin_peg_arbitrage_analyzer,
defi_protocol_stablecoin_yield_basis_spread_analyzer, defi_protocol_tvl_yield_elasticity_analyzer,
defi_protocol_yield_after_tax_drag_analyzer, defi_protocol_yield_term_structure_analyzer,
protocol_defi_collateral_health_factor_simulator, protocol_defi_mercenary_capital_risk_analyzer,
protocol_defi_reward_token_lockup_discount_analyzer.

## Что сделать

Вариант, который кажется верным (решает делающая сессия): `default_file` возвращает `path` как есть, когда
`path is None` (явное «не писать» — это «вызывающий сказал своё», тот же принцип, что у несовпадения). Плюс тест
с положительным контролем: `default_file(None, …)` и протокольный вызов каждого из 15 модулей при выставленном
`SPA_DATA_DIR`. Проверить остальные места переписки ADR-849 на ту же форму (`log_path: None` / `path=None`).

## Как понять, что готово

Tier-B `failed` в `analytics_signals_advisory.json` снова 0 (или названная другая причина), `ok` ≥ 101.
Пробу приёмки ставит сессия, берущая карточку (`.claude/rules/acceptance.md`).

Найдено ежедневным аудитом 90 % 2026-11-06 (`agent-audit-2026-08-02-fix-tracks.md`).

---

## Исполнено циклом #1066 (2026-11-07, `cycle-26318`) — [ADR-948](../../docs/decisions/ADR-948-an-explicit-none-log-path-is-the-caller-speaking-not-a-missing-default.md)

**Причина перемерена независимо, другим прибором.** Живой артефакт флота говорил `failed = 15`;
прямой вызов `analyze({"protocol": "aave_v3"})` у всех **19** модулей, несущих `"log_path": None`
(одноразовое дерево на чистых байтах `origin/main`, `SPA_DATA_DIR` в песочницу) дал
**падают 15 · проходят 4**. Два независимых способа — одно число.

**Сделано ровно то, что карточка называла верным:** `spa_core/utils/data_dir.py::default_file`
возвращает `path` как есть, когда `path is None` (явное «лога не писать» — это «вызывающий
сказал своё», тот же принцип, что у несовпадения путей).

**`default is None` НЕ тронуто, и это замер, а не пропуск:** население формы равно **нулю** —
ни один модуль дерева не объявляет умолчание лога `None`. Выдумывать поведение там, где у него
нет вызывающего, значило бы завести необъявленный исход.

**Проба приёмки** `tier_b_protocol_path_survives_a_disabled_log` (`card_acceptance.PROBES`)
объявлена ДО первой правки и дала:

| момент | вердикт |
|---|---|
| до правки | **`not_satisfied`** — «падают на отключённом логе 15 из 19», все 15 названы поимённо |
| после правки | **`satisfied`** — «вызвано 19 модулей Tier-B с отключённым логом, падений НЕТ» |

Контроль в обе стороны — `spa_core/tests/test_tier_b_disabled_log_probe.py`: зелёная на целом
контуре и красная на КАЖДОМ порванном звене с названным звеном (дверь возвращена к телу до
правки — у каждого предмета, потому что модули связывают её при ИМПОРТЕ · каталог нечитаем ·
предмета нет ни одного · предмет до двери не доехал). Подстрокой проба не проходит.
Батарея на байтах доставки: **82 passed**.

**Чего проба НЕ говорит — и это названо, а не умолчано.** Вернулся ли `failed` к нулю у
ФЛОТА, этот цикл не измерял и измерить не мог: артефакт `data/analytics_signals_advisory.json`
производит часовой прогон в ПРОД-дереве, а прод-дерево цикл не трогает (правило доставки п. 6 —
только с разрешения владельца). Вопрос закрывает первый часовой прогон после прихода кода на
`main`; до него утверждение «`failed` = 0» было бы НЕ ИЗМЕРЕНО, а не выполнено.
