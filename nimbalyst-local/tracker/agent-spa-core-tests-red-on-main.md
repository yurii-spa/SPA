---
trackerStatus:
  type: agent-task
title: 19 тестов spa_core/tests красны на main (предсуществующие, никем не отслеживались)
status: backlog
source: session-2026-07-29-cycle33
created: 2026-07-29
---

**Что найдено (цикл #33).** Полный прогон `spa_core/tests/ tests/` на чистом `origin/main`:
**102 634 passed, 20 failed, 642 skipped**. Карточка цикла #31/#32 разбирала только каталог
`tests/` — эти падения живут в `spa_core/tests/` и до сих пор не были описаны ни одной карточкой.
Все 20 воспроизведены на чистом чекауте без чужих правок (не регрессия).

Из 20 один уже адресован владельцу (`test_evidence_seeded::test_real_days_present` →
`owner-decision-dannye-treka-v-git-fail-dokazatelstv-zam.md`). Остальные 19:

| Файл | Тесты | Первая гипотеза (проверять!) |
|---|---|---|
| `test_eth_signer.py` | 8 | нет опциональной зависимости `eth_account` — вероятно, гейт по зависимости |
| `test_rates_desk_calibration.py` | 3 | детерминизм/robust-центр свипа |
| `test_deploy_gate_exit78.py` | 2 | fail-closed проверки деплой-гейта |
| `test_portfolio_capacity.py` | 1 | identity «каждое семейство выше пола» |
| `test_rates_desk_carry_validation.py` | 1 | детерминизм прогона |
| `test_rates_desk_surface_expansion.py` | 1 | refusal 100% на toxic после расширения |
| `test_tier1_backtest.py` | 1 | gate-eligible ⊆ validated |
| `test_tier1_e2e.py` | 1 | предсуществующая data-зависимость (известна с цикла #32) |
| `test_tier1_regime.py` | 1 | атомарность/форма отчёта |

**Почему это важно.** Красный тест — сигнал, а не помеха (инвариант #16). Часть этих имён
(`rates_desk` refusal, `tier1_backtest` gate-eligible, `deploy_gate` fail-closed) звучит как
проверки честности/отказа — то есть ровно тот класс, где молчаливое падение опаснее всего.
Тяжёлый `ci.yml` гоняет `tests/`, поэтому в CI эти падения не видны вовсе.

**Acceptance criteria:**
1. По каждому из 19 определён класс: (а) отсутствие опциональной зависимости → явный
   `skipUnless(<условие>, "<почему>")`, (б) устаревший ассерт после чужого рефактора →
   правка по существу с обоснованием в теле + журнал, (в) **настоящий баг** → фикс прод-кода
   с тестом, красным до фикса.
2. Ничего не ослаблено молча (инвариант #16); каждое намеренное изменение теста — с
   обоснованием в теле и записью в `docs/journal/<неделя>.md`.
3. Всё, что упирается в risk-логику / kill-switch / живой трек / данные в git — НЕ чинить,
   а завести карточку `needs-owner`.
4. Брать порциями (по файлу-два за заход), не big-bang.
