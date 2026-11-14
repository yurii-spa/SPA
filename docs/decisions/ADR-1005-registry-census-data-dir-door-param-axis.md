# ADR-1005 — §49 «Portfolio CIO»: прибор «реестр → бегун» судит дверь по ПАРАМЕТРУ, а не по ключу — третий исход `FOREIGN_PARAM`; из 53 читателей ключа 36 читают у связанного имени, 12 у `config`, 5 без входа; предмет 240 → 251

- **Дата:** 2026-11-13 (цикл #1125, `cycle-1125`, объявления `cycle-70846`)
- **Статус:** принято
- **Предмет:** заказ G994 п. 1 (а) карточки приказа владельца «Portfolio CIO» = ADR-1004 § 6 (а) «ось „у какого параметра дверь“ у прибора
  ADR-1002 — расширить `_reads_context_data_dir` третьим исходом `FOREIGN_PARAM`; население среди 53 читателей НЕ ИЗМЕРЕНО»; плюс
  G994 п. 25 — прочитать CI `main` на вершине #1124.
- **Соседи:** ADR-1004 (дверь «контекст → config» у двух модулей — ТОТ случай, который статика по ключу назвала читателем ложно),
  ADR-1003 (дверь `data_dir` у бегуна), ADR-1002 (прибор `registry_runner_write_census.py`, ось по КЛЮЧУ), ADR-1000/999 (слепые точки
  входа), ADR-031 (контекстная ветка Tier-B), ADR-333 (проба не подстрокой), ADR-726 (мутационный прибор), инв. #16, #17.

## 1. Вопрос заказа

Прибор ADR-1002 отвечал «модуль читает каталог бегуна», если ГДЕ-НИБУДЬ в файле стоит `X["data_dir"]` или `X.get("data_dir")` — кто такой
`X`, не спрашивалось. Бегун `_invoke` биндит контекст РОВНО в один параметр (`context=` по имени либо первый позиционный после `self`), и
чтение ключа у ЛЮБОГО другого имени каталога бегуна не видит. ADR-1004 § 1 нашёл это на одном модуле: `analyze(self, protocols, config=None)`
читал `config.get("data_dir", self.data_dir)`, бегун отдавал контекст в `protocols`, статика числила модуль читателем, и дверь бегуна
(ADR-1003) «закрывала» его умолчание на бумаге — а запись шла в `data/` дерева. ADR-1004 § 4 назвал класс таких читателей среди
остальных 51 НЕ ИЗМЕРЕННЫМ.

## 2. Решение — ось «у какого параметра дверь», четыре исхода, строгое распространение

1. **`DOOR_OUTCOMES = (CONTEXT_PARAM, FOREIGN_PARAM, NONE, UNRESOLVED)`**, у каждого модуля `data_dir_door` + чтения поимённо
   (`data_dir_reads`: функция · строка · у кого читается · достигает ли связанного имени) + причина у `UNRESOLVED`.
2. **Связанное имя** — тем же правилом, что `_accepts_context` / `_invoke` (`_bound_context_name`): форма 1 — параметр `context`, если
   он назван; форма 2 — первый позиционный после `self`. Контекст, уходящий только в `*args` или `**kwargs`, имени не имеет ⇒
   `UNRESOLVED` с причиной. Модуль без входа у бегуна, читающий ключ, — `UNRESOLVED` «входа у бегуна нет — связывать нечего».
3. **Распространение по графу вызовов модуля** (`_data_dir_door`), до неподвижной точки: само имя · псевдоним (`ctx = context or {}`,
   `a if c else b`, `dict(ctx)`, `ctx.copy()`) · параметр помощника, которому имя передано позиционно или по ключу (по имени метода — с
   избытком, как и достижимость записи) · атрибут `self`, в который имя положено, — виден методам того же класса.
   **Контейнер (`[ctx]`, `{"k": ctx}`) и результат чужого вызова (`f(ctx)`) связью НЕ являются**: ошибка идёт в сторону `FOREIGN_PARAM`,
   то есть находки, а не её отсутствия (тот же выбор, что у сторожа претензии `injected-clock`, `.claude/rules/deployment.md`).
4. **Предмет считается по оси, не по ключу:** `default_reached_under_sandbox` исключает писателя только при
   `runner.passes_data_dir and data_dir_door == "CONTEXT_PARAM"`; три счётчика оси (`door_context_param` · `door_foreign_param` ·
   `door_unresolved`) печатаются рядом с прежним `module_reads_context_data_dir` (ось ADR-1002 сохранена, не переписана).
   Читатели не у связанного имени печатаются поимённо с базой чтения.
5. Бегун, модули реестра, RiskPolicy, стоп-кран — не тронуты: правка только у прибора и его батарей.

## 3. Замер (дерево `origin/main` a62c9f4f + байты доставки; контроль — отдельный detached worktree e35585473 = `origin/main` ДО ADR-1004)

### 3.1. Население 53 читателей ключа — ИЗМЕРЕНО, впервые

| ось | a62c9f4f (после ADR-1004) | e35585473 (до ADR-1004) |
|---|---|---|
| `module_reads_context_data_dir` (по ключу, ADR-1002) | 53 | 53 |
| **`CONTEXT_PARAM`** | **36** | 35 |
| **`FOREIGN_PARAM`** | **12** — все 12 читают у `config` | 13 |
| **`UNRESOLVED`** | **5** — все `NO_ENTRY` («входа у бегуна нет») | 5 |
| `default_reached_under_sandbox` | **251** (было 240 по ключу) | 252 |
| сменили исход между деревьями | **ровно один:** `protocol_defi_yield_duration_mismatch_analyzer` `FOREIGN_PARAM` → `CONTEXT_PARAM` | |

То есть статика по ключу завышала закрытых дверью на **11 писателей** (12 `FOREIGN_PARAM`, из них 11 `WRITE_REACHABLE` и один
`DELEGATES_OUT`): они пишут в умолчание модуля под песочницей, как и нечитатели, а прибор ADR-1002 числил их за дверью. Положительный
контроль — ADR-1004: модуль, который тот ADR починил, на дереве ДО него прибор называет `FOREIGN_PARAM` (чтение `analyze:220` у `config`),
ПОСЛЕ — `CONTEXT_PARAM` (чтение `_config_from_context:30` у `context`, достигнуто через вызов `_config_from_context(protocols)`); второй
модуль ADR-1004 (`yield_volatility_surface_analyzer`) на обоих деревьях `CONTEXT_PARAM` — он и до починки читал ряд у `yield_series`,
починка была про ЗАПИСЬ, что прибор и показывает тремя чтениями (две у связанного имени, одна у `config or {}`).

### 3.2. Двенадцать `FOREIGN_PARAM` поимённо — одна форма, ADR-1004 § 1 ДО починки

`defi_gas_cost_yield_drag_analyzer` · `defi_impermanent_loss_breakeven_analyzer` · `defi_lending_market_utilization_analyzer` ·
`defi_lockup_opportunity_cost_analyzer` · `defi_protocol_sandwich_attack_vulnerability_scorer` · `defi_protocol_sequencer_downtime_risk_analyzer` ·
`defi_protocol_systemic_risk_contagion_modeler` (`DELEGATES_OUT`) · `defi_reward_token_sell_pressure_analyzer` ·
`defi_stablecoin_reserve_quality_scorer` · `protocol_defi_vault_fee_structure_breakeven_analyzer` · `protocol_token_distribution_analyzer` ·
`protocol_yield_curve_arbitrage_detector`. Выборочно прочитаны два (`defi_gas_cost_yield_drag_analyzer:52–79`,
`defi_stablecoin_reserve_quality_scorer:65–92`): `analyze(self, <домен>, config=None)` → контекстная ветка зовёт `self.analyze([_ctx_profile])`
БЕЗ `config` → `self._write_log(output, config.get("data_dir", "data"))` — дословно форма ADR-1004 § 1, строка в строку. Починка та же
(дверь «контекст → config»), и это **12 модулей одной работы**, не двенадцать работ (урок #1002/#1029: группировать по причине).

Пять `UNRESOLVED` (`defi_protocol_liquidity_fragmentation_analyzer` · `defi_protocol_volume_to_tvl_efficiency_analyzer` ·
`protocol_defi_token_buyback_impact_analyzer` · `protocol_defi_whale_concentration_monitor` · `protocol_defi_yield_curve_position_analyzer`) —
все `NO_ENTRY`: бегун в них с контекстом не входит, читают они у `config`; вопрос «у какого параметра дверь» к ним не относится, и прибор
говорит это причиной, а не нулём и не «читает».

### 3.3. CI `main` на вершине #1124 (G994 п. 25)

ci-control **43479360457** на `a62c9f4f` (ADR-1004) — `completed failure`, прочитан `ci_control_verdict.py`: `RED · failed 69 · error 5 ·
shards 12/12 · not_obtained 0 · population 142 091 · passed 141 355 · skipped 667`; стенные часы **8**, окружение раннера 18, **дефектов
34…42 — без сдвига**. Ожидание было «67 → ≤ 67», вышло **69**; имена сняты дверью `report_of_run` из `report.json` обоих прогонов: 67 общих,
ушедших 0, **пришедших два, и оба не дефекты кода**: `test_acceptance_probe_writer::…test_at_least_one_open_card_declares_a_registered_probe`
— под обмороком ИНСТРУМЕНТА шарда 3 (`TypeError: NoneType - int` внутри сессии pytest), на Маке в c1125 **27 passed** за 94 с;
`test_child_env_census::test_every_outcome_the_doors_return_is_declared` — род `pytest-timeout` (7 → 8; состав рода ротирует при
постоянном числе, G994 п. 26в). Худшие файлы прежние: `test_mutation_window_owner_probe` ×6 · `test_python_git_ref_provenance` ×4 ·
`test_subscript_silencer` ×4.

## 4. Что это НЕ делает

Не чинит 12 `FOREIGN_PARAM` — называет их и форму починки (§ 6а). Не меряет 26 `dormant` под песочницей с данными (ADR-1003 § 6в). Не
решает судьбу 240 записей без вопроса к контексту (ADR-1002 § 6д) — число теперь 251, и это точнее, а не хуже. Статика по-прежнему не
видит связи через контейнер и через чужой вызов — НАМЕРЕННО (§ 2.3), и модуль, передающий контекст помощнику внутри списка, прибор назовёт
`FOREIGN_PARAM`: это ложная НАХОДКА, а не ложное «чисто», и выборочное чтение (§ 3.2) её не встретило. Делегирование чужому модулю
аналитики с контекстом (`DELEGATES_OUT`) прибор не следит и там — как и раньше.

## 5. Приёмка (байты финальные; деревья отдельные; md5 доставки — `registry_runner_write_census.py` `8d9553f8f1ecceb3bc68ba4f0ef9e2b0` · `test_registry_census_data_dir_door_param.py` `eddafbea5adfda418b2c027e8dac6bd7` · `test_registry_runner_write_census.py` `09dcdae5152a30b094c4cae56f0cc326`)

- **Батарея** `spa_core/tests/test_registry_census_data_dir_door_param.py` — **22 passed**, по исходу прибора на сценах, не подстрокой
  (ADR-333): чтение у связанного имени пятью формами (само имя · псевдоним с хвостом `or {}` · помощник по ключу · форма `context=` ·
  `self._ctx`) ⇒ `CONTEXT_PARAM` · **форма ADR-1004 ДО починки** (`analyze(self, protocols, config=None)`, рекурсия без `config`) ⇒
  `FOREIGN_PARAM`, писатель остаётся в предмете под бегуном С дверью (`default_reached_under_sandbox` 1, код 1) · **та же форма ПОСЛЕ
  починки** ⇒ `CONTEXT_PARAM`, предмет пуст (код 0) — положительный и отрицательный контроль на одной форме · контейнер и чужой вызов —
  не связь · строка-литерал — не чтение (`NONE`) · без входа / `*args` / `**kwargs` ⇒ `UNRESOLVED` с названной причиной · текст и JSON несут
  ось · живое дерево: оба модуля ADR-1004 `CONTEXT_PARAM` через `_config_from_context`, каждый читатель ключа несёт ровно один исход,
  сумма трёх исходов = 53, у каждого `UNRESOLVED` причина названа.
- **Соседи** — `test_registry_runner_write_census` (тождество живого дерева переведено с ключа на ось: это УСИЛЕНИЕ — прежнее тождество
  по ключу на этом дереве ЛОЖНО, и тест теперь утверждает это явно `assertLess`; инв. #16: правка названа здесь и в журнале W46 #1125) ·
  `test_sandbox_data_dir_census` (потребитель прибора по файлу): **89 passed** втроём (27,7 с).
- **`pre_cutover_gate`** (одноразовый sandbox, `--no-save`): `all_defenses_fired True · would_cutover False`.
- **Мутации** — спецификация `docs/mutations/ADR-1005-spec-2026-11-13.json` (8: ось схлопнута в ключ · предмет по ключу · связанное имя —
  последний позиционный · имя не идёт в помощников · псевдонимы и `self.attr` не идут · без входа — `NONE` вместо `UNRESOLVED` ·
  контейнер/чужой вызов считаются связью · `*args` получает имя), прибор ADR-726 в rsync-копии `/private/tmp/spa_mut_1125` на ФИНАЛЬНЫХ
  байтах: **применено 8 · убито 8 · выжило 0 · сломало сборку 0**, базовых красных 0 («контур зелен»), окно снято после побайтовой сверки (`--window-check`: окна нет); каждую мутацию убила СВОЯ сцена (M01 — контейнер/чужой вызов + форма до починки; M02 — форма до починки + тождество живого дерева; M03 — обе формы ADR-1004; M04 — помощник по ключу + форма после починки + живые модули ADR-1004; M05 — псевдоним + `self._ctx`; M06 — без входа + сумма по живому дереву; M07 — контейнер + чужой вызов; M08 — `*args`). Запись — `docs/mutations/ADR-1005-2026-11-13.json`.
- **1г** (тест-файл добавлен): `import_time_anchor_bombs --repo-root /private/tmp/spa_anchor_1125` (rsync финальных байтов): код 0 — «Бомб нет: при задержке 95 мин ни один вердикт не изменился».
- Контрольный замер § 3.1 — detached worktree `/private/tmp/spa_pre1004_1125` на e35585473, снят после замера; прод-`data/` не писался.

## 6. Исполнители (работа следующих циклов — заказ G995 карточки приказа)

(а) **12 `FOREIGN_PARAM` — одна форма, одна работа:** дверь «контекст → config» (ADR-1004 § 2.1) у каждого, батарея по образцу
`test_registry_writers_follow_the_runner_door.py`, дифференциальное наблюдение бегуном (ADR-1004 § 3.2): ожидание — корзина бегуна 1 → 12,
дерево 47 → 36. (б) 26 `dormant` под песочницей С ДАННЫМИ (ADR-1003 § 6в). (в) 240 → 251 записей без вопроса к контексту (ADR-1002 § 6д) —
решение. (г) Тихий `except Exception: pass` у `yield_volatility_surface_analyzer._log_result` (ADR-1004 § 6г). (д) Транш 2 ADR-1000.
(е) ADR-1002 § 6 (в), (г), (е). (ж) 34…42 дефекта CI поимённо; (з) пакет владельцу; (и) G994 п. 1и — два члена рода «окружение раннера»
красны на Маке, дифференциально; (к) 6 красных только-Мак — решение об объявлении рода.

## 7. Инварианты

#1 RiskPolicy не тронут · #2 fail-CLOSED: связанное имя не названо ⇒ `UNRESOLVED` с причиной, не угадано · #3 LLM нет · #4 stdlib (`ast`) ·
#5 прибор только читает · #6 `execution/` не импортируется · #16 ни один тест не снят и не ослаблен; изменённое тождество — усиление, названо ·
#17 три исхода «читает у связанного · читает у чужого · связывать нечего» различимы и закреплены сценами; ноль по оси не печатается, пока
исход недостижим (`DOOR_OUTCOMES` замкнут и проверен).

## 8. Карточка владельцу

Не нужна: предмет — статика прибора о советательных журналах под песочницей (ADR-285: не деньги, не публичные числа, не необратимое).
