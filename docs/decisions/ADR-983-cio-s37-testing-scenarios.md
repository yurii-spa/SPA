# ADR-983 — §37 ТЗ «Portfolio CIO»: из пятнадцати сцен владельца живые двери исполняют тринадцать; «очевидно плохую» аллокацию колонка paper не перекладывает никогда, пойманный всплеск — сразу

- **Статус:** принято (замер, прибор только ЧИТАЕТ)
- **Дата:** 2026-11-11
- **Цикл:** #1100 (`cycle-19320`), заказ G970 п. 1 (главное)
- **Предмет:** §37 приказа владельца `inbox-task-portfolio-cio-dynamic-capital-alloc` («Testing scenarios»)
- **Продолжает:** ADR-982 (§36) · ADR-967 (§24: словарь владельца не реализован ни на одной двери — токены
  дверей печатаются дословно, перевод запрещён) · ADR-974 (§30 Shadow: пары «система ↔ CIO») · ADR-977
  (§31 горизонты) · ADR-978 (§32 классы ошибок) · ADR-969 (§26 Determinism; тот же ADR закрыл слепоту
  сторожа архитектуры, которую два теста §45 закрепляли как норму — § 7) · ADR-060 §3 (колонка порогов
  paper) · ADR-053 (TVL только живым числом) · ADR-025 (газовый стоп-кран Base) · ADR-031 (гейт Tier-A)
- **Прибор:** `spa_core/analytics/testing_scenario_census.py` (артефакт `data/testing_scenario_census.json`;
  живой `data/` НЕ читается: все сцены из литералов, часы/журнал ходов инъектируются, газовый монитор и
  гейт Tier-A — в одноразовом каталоге, сигнал Tier-A подменён только на время сцены 14)
- **Батарея:** `spa_core/tests/test_testing_scenario_census.py` (**76 passed**) — это и есть scenario tests
  владельца: 15 сцен × (сцена владельца · порванная сцена), имена функций объявлены в реестре прибора
- **Проба приёмки:** `owner_scenes_pass_and_discriminate` (реестр `card_acceptance.PROBES`, вход `repo_root`;
  на живом дереве — `not_satisfied`, сцены 1 и 2 названы)
- **Мутации:** `docs/mutations/TSC-983-2026-11-11.json` (M01–M23), `/private/tmp/spa_mut_1100` — итог в § 8
- **Попутно (та же доставка):** два теста `test_cio_architecture_constraints.py`, красные на `main` с #1090,
  закрепляли дефект, снятый ADR-969; перевёрнуты с обоснованием (§ 7). Третий красный того же файла —
  настоящая находка, НЕ тронут (§ 7)
- **Касается ли money-path:** нет. Ни один порог, дверь, гейт, RiskPolicy, стоп-кран, трек не правлены ни
  байтом; колонка paper передаётся сценам ЯВНО (`TriggerParams()`), чтобы вердикт не зависел от
  `SPA_CAPITAL_MODE` хоста.
- **Карточка владельцу:** НЕ заведена (§ 9).

## Дословное требование владельца

> §37 «Testing scenarios». Необходимо реализовать automated tests и scenario tests.
> Test 1 — очевидно плохая текущая аллокация (Aave 40 % / 3 %, Morpho 10 % / 6 %, оба допустимы, low
> switching cost, stable destination APY) — Expected: REBALANCE, но не обязательно перемещение всех 40 %.
> Test 2 — transient spike (3 % → 12 % на несколько минут, затем обратно) — KEEP / DEFER. Test 3 — expensive
> transaction (+2 %, break-even 20 дн., persistence 5 дн.) — KEEP. Test 4 — Candidate 20 % — не обходить
> Tier/Risk Policy. Test 5 — marginal yield collapse (8 % → 3,5 % после депозита) — уменьшить размер или
> отказаться. Test 6 — correlation — concentration/correlation constraints. Test 7 — stale data (APY свежий,
> liquidity stale) — NO EXECUTION. Test 8 — high gas — DEFER. Test 9 — gas falls — DEFER → REBALANCE.
> Test 10 — new capital (+$10k) — к Target без лишнего Aave withdrawal. Test 11 — APY disappears before
> execution — pre-trade validation отменяет. Test 12 — oscillating APYs (5,0/5,3 ↔ 5,4/5,1) — никакого churn.
> Test 13 — concentration limit (оптимум 70 %, потолок 25 %) — 25 % max. Test 14 — emergency (critical
> security alert) — risk action выше yield. Test 15 — same snapshot determinism (100 запусков) — идентичный
> output.

Сцен **ПЯТНАДЦАТЬ**; прибор держит названия и ожидания константами и сверяет с карточкой (`parity`) —
совпало на первом прогоне (строки 1036…1209 карточки с `origin`, вторая граница — «38. Historical replay»).
Заказ G970 п. 1 чисел не называл (привёл одну сцену примером) — сдвиг не применим, и это печатается отдельно.

## 1. Предмет — не «есть ли тесты в репозитории»

Заказ назвал предмет точно: «у КАЖДОЙ названной владельцем сцены есть тест, который на ней проходит, и он
красен на ПОРВАННОЙ сцене». Поверхностная мера («в дереве 82 тест-файла со словом spike, 60 — churn, 168 —
gas») на вопрос не отвечает. Осей ЧЕТЫРЕ:

| ось | вопрос | роды |
|---|---|---|
| A — дверь | есть ли на ДЕНЕЖНОМ ПУТИ дверь, принимающая входы сцены | `present` · `partial` (вход владельца ОТСУТСТВУЕТ, назван) · `absent` · unmeasured |
| B — сцена владельца | что живая дверь делает на литералах владельца | `as_expected` · `contrary` · `unreachable` · unmeasured |
| C — порванная сцена | меняется ли ответ там, где ожидание обязано смениться | `discriminates` · `indiscriminate` · `not_built` · unmeasured |
| D — тест в репозитории | есть ли названный тест (реестр `SCENE_TESTS`, сверка AST) | `present` · `stale` · `absent` · unmeasured |

Токены дверей (`ACT`/`HOLD`, `ALLOW`/`BLOCK`, `approved`, `kill_switch_active`) печатаются ДОСЛОВНО;
ожидание владельца читается **предикатом о поведении** (`reading` печатается рядом) — перевод
`ACT ↔ REBALANCE` утверждением об эквивалентности не является (ADR-967). Контроль всего отчёта — здоровая
сцена проходит обе главные двери (дверь цены `ACT`, гейт `approved`); сломан ⇒ счёт не читается.

## 2. Живой замер: 15 сцен — дверей present 6 / partial 9 / absent 0; как ожидалось 13, вопреки 2; различают 15/15

| Test | дверь (ось A) | сцена владельца (B) | порванная (C) | что сказала дверь |
|---|---|---|---|---|
| 1 плохая аллокация | present | **contrary** | discriminates | весь ход: `HOLD` (`move_turnover_over_budget:40.0%>15%`); ход в потолке 15 %: `HOLD` (`gain_below_band:0.450pp<0.500pp`) |
| 2 transient spike | partial | **contrary** | discriminates | `ACT` на пойманном всплеске («gain 1.350pp ≥ 0.500pp … repays in 9.7d») |
| 3 expensive tx | partial | as_expected | discriminates | `HOLD`, но причина — `gain_below_band`, не «стойкость < окупаемости» |
| 4 Candidate 20 % | present | as_expected | discriminates | гейт: `approved=False` (потолок T3 15 %) при ставке внутри полосы APY |
| 5 marginal yield | partial | as_expected | discriminates | ёмкость режет $20 000 → $5 000 (1 % TVL) |
| 6 correlation | partial | as_expected | discriminates | два vault на Base сверх потолка L2 50 % — `approved=False` |
| 7 stale data | present | as_expected | discriminates | `tvl_source≠live` ⇒ пул выброшен из цели, `tvl_unverified=[morpho_blue]` |
| 8 high gas | partial | as_expected | discriminates | 3 чтения ≥ 10 gwei ⇒ `kill_switch_active`, нога Base → 0, нога Ethereum цела |
| 9 gas falls | partial | as_expected | discriminates | четвёртое чтение 1 gwei ⇒ `KILL_SWITCH_RESET`, нога Base возвращена |
| 10 new capital | partial | as_expected | discriminates | ноги `{morpho_blue: +10 000}`, `ACT`, ограничитель `ALLOW` |
| 11 APY disappears | partial | as_expected | discriminates | пересчёт на упавшей ставке — `HOLD` |
| 12 oscillating | present | as_expected | discriminates | оба шага `HOLD` (`reversal_of_recent_move`, `cooldown_active`), ограничитель `BLOCK/min_hold` |
| 13 concentration | present | as_expected | discriminates | `_apply_caps` 0,70 → 0,40; гейт на 70 %: «exceeds T1 limit 40.0%» |
| 14 emergency | partial | as_expected | discriminates | `BLOCK` ⇒ лучшая ставка обнулена, $50 000 перераспределено |
| 15 determinism | present | as_expected | discriminates | отпечатков за 100 прогонов — 1 у двери цены и 1 у гейта |

Ось D: с этой доставкой у каждой сцены — пара тестов батареи (сцена · порванная) плюс у восьми сцен
названы существующие тесты дерева (`test_rebalance_economics`, `test_churn_damper`, `test_tvl_floor_verdict`,
`test_risk_policy_gate`, `test_capacity_limits`, `test_allocator_properties`, `test_cycle_nav_determinism`,
`test_cycle_runner_characterization`) — все `present` по AST. До этой доставки реестр был пуст: ось D
отвечала бы `absent` на все пятнадцать.

## 3. Test 1: колонка paper не перекладывает «очевидно плохую» аллокацию НИКОГДА — и это арифметика порогов, не случай

Владелец называет сцену очевидной: Aave 40 % под 3 %, Morpho 10 % под 6 %. Дверь цены отвечает `HOLD` на
обеих целях, и причины у них разные:

| цель | оборот | выигрыш (пп TOTAL капитала) | гейт, который отказал |
|---|---|---|---|
| весь ход (40 % → Morpho) | 40 % | 1,20 | `max_turnover_per_move` 15 % · `max_trade_usd` $15 000 · недельный и дневной бюджет |
| ход в потолке (15 %) | 15 % | **0,45** | `min_gain_pp` **0,50** |

Наибольший выигрыш ОДНОГО допустимого хода равен `max_turnover_per_move × (6 − 3) = 0,15 × 3 = 0,45 пп` и
меньше полосы `min_gain_pp = 0,50`. Второй ход после cooldown даёт те же 0,45 — то есть при этих двух
ручках колонки paper (ADR-060 §3) разница ставок в 3 пп **не преодолевает полосу ни одним ходом**, и книга
останется в сцене владельца навсегда. Порванная сцена (Morpho 9 %) даёт `ACT` на ходе в потолке — дверь
различает, вопрос не в двери, а в ПАРЕ порогов. Прибор это НЕ правит: оба числа — предмет ADR-060 §3
(ручки мандата) и денежного пути; он печатает `largest_gain_one_move_pp=0.45` рядом с `required_gain_pp=0.5`.

## 4. Test 2: пойманный всплеск перекладывается сразу — входа «стойкость» у двери нет

На снимке со ставкой 12 % дверь цены говорит `ACT` (выигрыш 1,35 пп, окупаемость 9,7 дн.). Входа
«сколько держалась ставка» у `evaluate` нет; окно свежести снимка (ADR-976, 36 ч) старит наблюдение, но не
спрашивает его длительности; полоса здравости живого APY (`_LIVE_APY_MAX_DECIMAL` = 200 %) всплеск 12 % не
ловит. Защищает систему от этой сцены только ТАКТ наблюдения (ADR-055: суточный снимок) — всплеск «на минуты»
либо не попадёт в снимок, либо попадёт и будет исполнен. Та же нехватка входа у Test 3: `HOLD` там верный,
но по причине полосы выигрыша, не по «стойкость 5 дн. < окупаемость 20 дн.»; окупаемость — не вход, а вывод
из констант газа/проскальзывания (`cost_model`).

## 5. Девять частичных дверей — входы владельца, которых нет ни у одной двери денежного пути

| вход владельца | сцены | где он живёт сегодня |
|---|---|---|
| стойкость/длительность ставки (persistence) | 2, 3 | нигде; §22 `minimum persistence` — ADR-963/§41 BINDING-замер |
| ставка ПОСЛЕ нашего депозита (marginal APY) | 5 | нигде; размер режется долей TVL (1 %), а в `check_new_position` ёмкость warn-only (ADR-009) |
| общие критические зависимости vault | 6 | только СЕТЬ (`max_single_chain_allocation`, L2 50 %); `investment_cio/correlation.py` — advisory-коэффициент |
| газ Ethereum как наблюдение | 8, 9 | у двери цены газ — литерал `GAS_USD_PER_POSITION_CHANGE`; наблюдается только Base, порог 3 суточных чтения |
| цель с учётом ТЕКУЩИХ позиций | 10 | `StrategyAllocator.allocate(self, model)` книги не принимает — «без лишнего вывода из Aave» судят двери НАД готовой целью |
| дверь ОТМЕНЫ рекомендации перед исполнением | 11 | ручки `input_freshness_tolerance_s=60` / `decision_ttl_s=600` описывают допуск, ворот принуждения нет (ADR-971 ось E, ADR-972); на бумаге решение и исполнение — один процесс (ADR-970 § 2) |
| детектор «critical security alert» в Tier A | 14 | `protocol_security_incident_tracker` — тир **C**, вес **0,0**; в Tier A по безопасности один модуль `defi_protocol_token_bridge_security_risk_analyzer` (категория bridge). Гейт BLOCK чтит; сигналу о взломе до BLOCK дойти нечем (G969 п. 12 — измерено СЦЕНОЙ) |

`partial` — WARN, не CRITICAL: это предмет исполнителей, а сцена на существующей части двери измерима.

## 6. Что прибор НЕ утверждает

- **Не судит, ВЕРНЫ ли пороги.** Test 1 измерен против колонки paper как она есть; менять `min_gain_pp` или
  `max_turnover_per_move` — ADR-060 §3, предмет №1 владельца.
- **Не судит построение цели.** Аллокатор в сценах зовётся только методом потолков (`_apply_caps`); живой
  `allocate()` читает файлы снимка и здесь не прогоняется — его детерминизм измерен §26 (ADR-969).
- **Не утверждает, что Tier-A увидит взлом.** Сцена 14 подменяет сигнал: измерено, что гейт его чтит;
  детектор — ось «недостающий вход».
- **Не заменяет остальные тесты дерева.** Ось D сверяет НАЛИЧИЕ названных функций разбором AST; что они
  зелены — вопрос прогона, и батарея этого цикла прогнана (§ 8).

## 7. Попутно: два теста §45 закрепляли дефект, снятый ADR-969; третий красный — настоящая находка

`test_cio_architecture_constraints.py` красен на `main` с #1090 (пред-существующее красное во всех прогонах
#1090…#1099). Разобрано:

| тест | что утверждал | вердикт | что сделано |
|---|---|---|---|
| `TestGuardBlindness.test_sdk_seen_and_subprocess_not` | сцена запуска бинаря `claude` НЕ видна сторожу, `blind_to_subprocess is True` | закреплял ДЕФЕКТ: прибор спрашивал одну дверь из двух (ADR-969 § «замер спрашивал одну дверь») | утверждение перевёрнуто: каждая сцена видна СВОЕЙ дверью (`seen_by`), `blind_to_subprocess is False`, контроль цел; докстринг называет историю |
| `TestLiveVerdict.test_guard_blindness_is_reported_as_critical` | на живом дереве есть находка `guard_blind_to_real_door` | закреплял ложный CRITICAL, печатавшийся 12 циклов (G947 п. 2 … G957 п. 14) | `assertIn` → `assertNotIn`; возврат находки = регресс сторожа |
| `TestLiveVerdict.test_money_path_layers_do_not_reach_the_llm` | слой `2-optimizer` не достигает LLM | **НАСТОЯЩАЯ НАХОДКА**: `spa_core.tuner.portfolio_rebalancer → telegram.push_policy → … → telegram.ask_router` (1 модуль, через канал объяснения) | НЕ ТРОНУТ. Исполнитель — агент: разорвать импорт `push_policy` из слоя оптимизатора (инв. #3), а не расширять исключение канала объяснения на денежный слой |

Инвариант #16: оба перевёрнутых теста изменены с обоснованием в теле (докстринги) и записью в журнале W46;
имена сохранены, потому что их читают сводки прошлых прогонов. Это не ослабление: утверждение стало
положительным контролем ADR-969 в обе стороны.

## 8. Приёмка

- батарея `test_testing_scenario_census.py` — **76 passed**; `test_cio_architecture_constraints.py` после
  правки — 40 passed, **1 failed** (`test_money_path_layers_do_not_reach_the_llm`, настоящая находка § 7);
- ратчеты на дереве: `test_absent_observation_ratchet` зелёный после снятия двух `or []` в читателе гейта
  (первая редакция внесла два члена класса инв. #17 — исправлено чтением индексом); `test_frozen_date_ratchet`,
  `test_injected_clock_claim`, `test_prescribed_run_matches_ci`, `test_acceptance_probe_writer`,
  `test_cio_acceptance_guards_are_wired` — зелёные; `test_inbox_acceptance_ratchet` — красен на чистом
  `origin/main` (десять карточек `done` без пробы, пред-существующее #1090…#1099), дельта цикла его не меняет;
- мутации TSC-983 (M01–M23, `/private/tmp/spa_mut_1100`): **применено 23 · убито 23 · выжило 0 · не применено 0 · сломали
  сборку 0**; `--window-check` — окна нет, байты модуля и `card_acceptance.py` сверены md5 с деревом доставки;
- шаг 1г (`import_time_anchor_bombs --repo-root /private/tmp/spa_anchor_1100`): **код 0** — «бомб нет: при задержке 95 мин ни один
  вердикт не изменился», дерево названо входом;
- живой вердикт: прибор `CRITICAL` (critical=2 — сцены 1 и 2; warn=9 — частичные двери), проба
  `not_satisfied` («не исполнены 2: Test 1, Test 2»).

## 9. Карточка владельцу — НЕ заведена

Ни одна находка не из трёх предметов ADR-285: пороги колонки paper (Test 1) — у владельца УЖЕ лежит механизм
(ADR-060 §3 меняется ADR-ом, и вопрос «как перекладывать деньги» ему уже задан карточкой
`agent-sovetnik-po-perekladke-deneg-ne-smozhet`, `backlog`); недостающие входы дверей — работа агента по
ТЗ владельца; красный тест слоя оптимизатора — работа агента (инв. #3). Заводить карточку значило бы
переспросить то, что владелец уже написал в §37.
