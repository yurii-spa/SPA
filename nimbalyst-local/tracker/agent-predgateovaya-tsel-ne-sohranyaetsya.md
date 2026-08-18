---
trackerStatus:
  type: agent-task
title: "Цель аллокатора ДО гейта нигде не сохраняется — ни один вопрос «а что он просил?» не проверяем задним числом"
status: done
source: session-2026-08-08-owner-answers
created: 2026-08-08
priority: medium
tags: [observability, audit, allocator, adr-072, adr-073]
---

## Что нашлось

При проверке ADR-073 потребовалось воспроизвести цикл **2026-08-08 09:50 UTC**: что аллокатор
просил ДО гейта, что осталось ПОСЛЕ, и сколько бюджета освободилось. Оказалось — **невозможно**.

`_pre_gate_target` живёт только в памяти `run_cycle`. В артефакты попадает лишь производное:
`policy_refusals` (сколько снято с конкретного пула) и текстовая строка в `cash_attribution`.
Самой цели нет ни в `allocation_rationale.json`, ни в `current_positions.json`, ни в
`audit_trail.jsonl` (событие `risk_verdict` несёт вердикт и нарушения, но не цель).

**Цена уже уплачена.** Приёмка ADR-073 из-за этого модульная, на воспроизведённой аварии, а не
сквозная — и это записано в самом ADR как ограничение, а не спрятано. Прогон в песочнице
воспроизвести срез не смог: другая вселенная фидов (7 живых против 18).

## Что сделать

Писать в артефакт цикла (или отдельным событием `audit_trail`) пару
`pre_gate_target` / `post_gate_target` вместе с `freed_usd` и итогом перераздачи.
Это чистая наблюдаемость: ни одного решения не меняет, капитал не двигает.

## Почему это важнее, чем кажется

Без этих двух словарей ЛЮБОЙ вопрос вида «почему деньги остались в кэше в такой-то день»
отвечается только моделированием. Именно на моделировании и родился неверный диагноз в карточке
владельца («перезаполнения не существует»), тогда как оно существовало и было отвергнуто гейтом.

## Сделано (2026-08-18)

**Замер до правки.** Цель рождается в `spa_core/paper_trading/cycle_runner.py:1440`
(`alloc.target_usd`), копируется предгейтово в `:1703` (`_pre_gate_target`) и **умирает там же,
в кадре `run_cycle`** — наружу не выходило ничего, кроме производного
`quantify_policy_refusals` (`spa_core/paper_trading/cycle_gates.py:33`, только по
TVL-замороженным пулам) и строки в `cash_attribution`. Событие `risk_verdict`
(`cycle_runner.py:~1716`) несёт вердикт/нарушения, но не цель. Второго писателя нет: по
всему репо `pre_gate` встречается только в `cycle_runner` / `risk_gate` / `cycle_gates` —
`allocation_rationale`, `decision_shadow`, `feed_coverage`, `capital_efficiency`
предгейтовую цель НЕ хранят.

**Что добавлено (только наблюдаемость, money-path не тронут).**

- `spa_core/paper_trading/cycle_gates.py` — `build_gate_ledger()` рядом с
  `quantify_policy_refusals` (тот же домен сравнения pre/post, второго источника правды не
  заводим). Сравнивает три словаря, ничего не мутирует.
- `cycle_runner.py` — снимок сырой цели аллокатора (`_allocator_target`), исход перераздачи
  ADR-072 (`_redistribution_summary`) и сборка ledger'а **сразу после гейта и ДО**
  kill-switch / soft-derisk / base-gas / ALLOC-002 / RTMR, чтобы разница отвечала на вопрос
  «что зарубил ГЕЙТ», а не на смесь шести стадий. Fail-open.
- `allocation_rationale.py` — секция `gate_ledger` в `data/allocation_rationale.json`
  (запись через существующий `atomic_save`).

**Fail-CLOSED в атрибуции.** Правило приписывается снятию, только если гейт его назвал
(`tvl_unverified` → ADR-053; `trimmed` → min-cash буфер; ADR-072 — на добавления). Всё
остальное — `rule=None` / `attributed=False` / `status="not_measured"` и попадает в
`summary.unnamed_removed_usd`; `attribution_complete` — утверждение, а не умолчание.
Отсутствие ledger'а читается как `status: "not_measured"`, а не как «гейт ничего не зарубил».

**Положительный контроль в обе стороны** — `spa_core/tests/test_gate_ledger.py` (12 тестов,
зелёные). Мутации краснят: (A) ledger перестал писать снятия → 5 красных; (B) чистый проход
породил ложные «зарубленные» → 2 красных; (C) неназванному снятию подставлено правдоподобное
правило → 1 красный; (D) `gate_ledger=` убран из вызова в `cycle_runner` → 1 красный.

### Независимая сверка 2026-08-18 — статус `done` подтверждён прогоном

Перепроверено не по отчёту, а прогоном и чтением кода:

- `build_gate_ledger` существует — `spa_core/paper_trading/cycle_gates.py:76`;
- **проведён в цикл** — `spa_core/paper_trading/cycle_runner.py:126` (импорт) и `:1845`
  (вызов), ровно после гейта и ДО kill-switch/soft-derisk (см. комментарий `Step 2b-ledger`),
  обёрнут `try/except` (fail-open, наблюдаемость не валит цикл);
- запись в артефакт — `allocation_rationale.py:301` (параметр) / `:454` (секция `gate_ledger`,
  при отсутствии — `not_measured`, а не «гейт ничего не зарубил»);
- тесты — `pytest spa_core/tests/test_gate_ledger.py -q` → **12 passed in 0.54s**;
  строка `test_gate_ledger.py:219` держит сам факт вызова из `cycle_runner`.

**Где замер неполон** (честно, не закрыто этой карточкой): стадии ДО RiskPolicy
(analytics-blocking gate) мутируют `target_usd` на месте и наружу причину по протоколам не
сообщают — их разница показана отдельной секцией `pre_riskpolicy_stage_changes` и целиком
помечена `not_measured`. Стадии ПОСЛЕ гейта (kill-switch, soft-derisk, base-gas, ALLOC-002,
RTMR) в ledger не попадают по построению — это отдельный вопрос и отдельная карточка.
