---
trackerStatus:
  type: inbox
title: "Прогон тестов переписывает СОРОК git-tracked файлов в data/ (карточка #225/#226 считает, что их три) — среди них журнал исполнения"
status: new
source: замер 2026-08-20 при полном прогоне на ветке claude/unreadable-description-ltyucb
created: 2026-08-20
priority: high
domain: tests · data/
---

## Что измерено

Полный прогон предписанного набора

```
SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest spa_core/tests/ tests/ scripts/tests/ \
  spa_core/analytics/gross_of/ research/cards/ -q
```

оставляет после себя **40 изменённых git-tracked файлов в `data/`** плюс
`spa_core/database/spa.db`. Проверено дважды: после первого завершённого прогона — 40,
на промежуточных срезах второго — 9 и 15 (набор растёт по ходу прогона, то есть это не
разовая фикстура, а поведение многих тестов).

Характер правок — не «мусор в конце файла», а перезапись боевых полей:

```
data/alert_log.json:   "updated_at": "2026-08-04T08:30:45" → "2026-08-20T22:55:18"
                       "count": 26 → 28          (в журнал дописаны тестовые тревоги)
data/gap_monitor.json: "checked_at":  "2026-08-04T08:54:55" → "2026-08-20T22:57:07"
```

Полный список (замер после завершённого прогона):

`adapter_status` · `admin_key_control_risk_log` · `airdrop_farming_log` · `alert_log` ·
`apy_milestone_log` · `borrow_cost_log` · `borrow_rate_volatility_log` ·
`borrowing_cost_log` · `borrowing_power_utilization_log` · `chains_status` ·
`cross_asset_correlation_log` · `fixed_rate_duration_log` ·
`fixed_vs_floating_yield_decision_log` · `funding_rate_arb_log` · `gap_monitor` ·
`gas_cost_breakeven_log` · `gauge_emission_decay_log` · `il_hedging_log` ·
`lending_rate_spread_log` · `leverage_loop_risk_log` · `liquidation_cascade_log` ·
**`live_execution_log`** · `net_interest_margin_log` · `perp_funding_rate_log` ·
`points_conversion_log` · `points_token_conversion_risk_log` ·
`rebase_token_yield_normalizer_log` · `rehypothecation_risk_log` ·
`reserve_factor_economics_log` · `reward_claim_timing_log` ·
`reward_dilution_velocity_log` · `risk_adjusted_yield_hurdle_log` · `risk_alerts` ·
`stablecoin_basket_composition_log` · `stablecoin_peg_arbitrage_log` ·
`stablecoin_yield_basis_spread_log` · `treasury_diversification_log` ·
`tvl_yield_elasticity_log` · `yield_after_tax_drag_log` · `yield_term_structure_log`
(+ `spa_core/database/spa.db`)

## Почему это важнее, чем выглядит

1. **Класс считается закрытым, а он вырос в тринадцать раз.** Карточка `#225/#226`
   («прогон тестов переписывал ТРИ git-tracked фикстуры сегодняшней датой») закрыта, и
   `STATE.md` перечисляет её среди «не переделывать». Замер говорит: сорок.
2. **Среди них `live_execution_log.json`** — журнал домена исполнения. Тест не имеет права
   его касаться даже отметкой времени (`.claude/rules/deployment.md`: «`data/` при
   синхронизации кода НЕ ТРОГАТЬ», инв. #6 — read-only код не ходит в execution).
3. **Самообновляющаяся фикстура протухнуть не может** — это дословно диагноз из
   `#225/#226`. Любой сторож свежести, читающий эти сорок файлов, после прогона видит
   «всё свежее», потому что свежесть сделал он сам, а не система.
4. **Цена уже уплачена в этой сессии трижды.** Хук «есть незакоммиченные изменения»
   срабатывал на этом следе три раза подряд; каждый раз приходилось доказывать, что
   правки — не мои, и откатывать `data/` вручную. Любой, кто прогонит тесты и не заметит,
   закоммитит подмену трека вместе со своей работой.

## Что сделать

1. Найти писателей: прогнать набор по частям и после каждой части мерить
   `git status --short -- data/` — это даёт отображение «файл → тест», а не догадку.
2. Каждому — фикстура через `tmp_path`/инъекцию каталога данных, а не запись в живой `data/`.
   Время — входом (`now=`), как предписывает `.claude/rules/deployment.md`.
3. Сторож: после прогона `git status --porcelain -- data/` обязан быть ПУСТ. Это
   положительный контроль, который сегодня воспроизводит настоящую аварию — значит он не
   украшение.
4. Отдельно и первым — `live_execution_log.json`: выяснить, какой тест пишет в
   execution-домен, и закрыть это независимо от остальных 39.

## Как понять, что готово

Полный прогон предписанной команды оставляет `git status --porcelain -- data/` пустым,
и новый сторож краснеет, если это перестаёт быть правдой.

## СВЕДЕНИЕ ИСТОЧНИКОВ (дописано 21.08 после переноса на свежий `main`)

`main` принёс собственный замер того же класса — коммит `4a98fd7`, получен побочно от
приёмки цикла #324: **83** git-tracked пути (78 `data/*_log.json`, два `spa_core/data/*`,
плюс `spa.db`), и он прямо называет мою карточку третьим несходящимся источником.

| Источник | Число | Условия |
|---|---|---|
| карточка `#225/#226` | **3** | закрыты три ПОИМЕНОВАННЫХ пути |
| эта карточка | **40** | полный набор, контейнер cloud-сессии, sha `d2e1e5c` |
| `main` `4a98fd7` | **83** | полный набор CI-командой, другой sha, отсев уборщика деревьев |

**Числа не сводятся, и замазывать это нельзя.** Ни одно из трёх не опровергает другие:
мерили в разных деревьях, на разных sha и разными инструментами (я — `git status`,
`main` — перечень отсеянных churn-путей уборщика). Общее у всех трёх ровно одно и оно же
главное: **писателя не мерил никто** — какой тест какой файл трогает, неизвестно, поэтому
и разброс. Пока это не измерено, любое из трёх чисел — свойство прогона, а не системы.

Приёмка от этого не меняется и остаётся выполнимой при любом из чисел: после полного
прогона `git status --porcelain -- data/` обязан быть ПУСТ.

Что усиливается замером `main`: в списке 78 журналов `data/*_log.json`, среди них
`alert_log.json` и `risk_alerts.json` — прогон трогает ЖИВОЕ состояние тревог, а не
только фикстуры.
