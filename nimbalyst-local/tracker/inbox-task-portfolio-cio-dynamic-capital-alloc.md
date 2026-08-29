---
trackerStatus:
  type: inbox
title: "TASK — Portfolio CIO: Dynamic Capital Allocation & Rebalancing"
status: in-progress
source: telegram
created: 2026-08-13
priority: critical
status_trail:
  - "2026-08-26T22:31:36.748790+00:00 new -> in-progress · queue.set_status · cycle-96657"
---

## УКАЗАНИЕ ВЛАДЕЛЬЦА 2026-08-22 (cloud-сессия): ЗАПУСТИТЬ СЛЕДУЮЩИМ ЦИКЛОМ

Владелец спросил «как запустить CIO?» — трактовать как прямой приказ начать
исполнение немедленно, вне общей очереди. Порядок готов и перепроверен:
`docs/research/RS-portfolio-cio-diagnosis.md` — начинать с **G1 (живые фиды вне
Ethereum + расхождение pendle-фидов; только с хоста)**, затем вопрос владельцу
про констрейнты тюнера (кандидат-ADR из диагностики), затем SHADOW-замер и
вопрос про ARM ADR-060. G2/G3/G4 уже закрыты (см. замеры в
`inbox-cio-etap1-diagnostika-gotova-ispolnyat-g1-g4`) — не переделывать.

## Задание (из Telegram)

TASK — Portfolio CIO: Dynamic Capital Allocation & Rebalancing
1. Цель задачи
Необходимо спроектировать, реализовать и протестировать portfolio-level управляющий слой для SPA, который будет отвечать за оптимальное распределение капитала между разрешенными DeFi-позициями.
Рабочее название компонента:
Portfolio CIO / Dynamic Capital Allocation & Rebalancing
Его задача — не искать максимальный APY и не перекладывать средства при каждом изменении ставок.
Его задача:
Максимизировать устойчивую ожидаемую чистую доходность всего портфеля в рамках действующей risk policy, учитывая стоимость ребалансировки, устойчивость APY, риски, концентрацию, ликвидность, влияние нашего размера позиции и стоимость последующего выхода.
Система должна постоянно отвечать на два разных вопроса:
Как в текущих условиях должен выглядеть оптимальный portfolio allocation?
Экономически оправдано ли переходить из текущего allocation в оптимальный allocation прямо сейчас?
Решение DO NOTHING / KEEP является полноценным инвестиционным решением и не должно считаться отсутствием работы.


⸻


2. Реальная проблема
Текущий SPA Daily Report:
SPA Daily Report — Day 65 (2026-08-13)

Portfolio: $100,867
Paper APY: 6.89% (7-day avg: 5.41%)

Positions:
Aave V3: $40,000 (39.7%) — 2.7% APY
Pendle Finance: $20,000 (19.8%) — 8.0% APY
Maple Finance: $20,000 (19.8%) — 4.8% APY
Morpho Steakhouse USDC: $10,000 (9.9%) — 4.4% APY
Cash: $10,867 (10.8%)

Cycle: last status blocked_by_policy
Risk gate: 9 block event(s) today

Base monitoring:
Aave V3 Base [T2]: 3.7%
Morpho Blue Base [T2]: 4.4%
Moonwell Base [T3]: SUSPENDED
Extra Finance XLend [T3]: 1.5%
aerodrome_usdc_lp [T2]: 8.5%
Очевидный симптом:
почти 40% капитала продолжает находиться в Aave V3 под 2.7%, одновременно существуют позиции и наблюдаемые opportunities с существенно большей доходностью.
10.8% портфеля также находится в Cash.
При этом система сообщает:
blocked_by_policy
9 risk policy blocks
Поэтому нельзя заранее предполагать, что проблема заключается только в отсутствии allocator.
Возможны как минимум следующие причины:
allocation сейчас статичен;
allocation рассчитан один раз и дальше не пересматривается;
существует allocator, но он работает неправильно;
allocator принимает решение, но Risk Gate его блокирует;
position sizing определяется некорректно;
policy слишком жесткая;
APY используется только для reporting, но не для allocation;
opportunity agents не связаны с portfolio allocation;
portfolio allocation и execution существуют как разрозненные циклы;
существует другое архитектурное ограничение.
Это необходимо сначала установить фактически.


⸻


3. Критическое правило
Не начинать задачу с создания нового агента.
Сначала выполнить полную диагностику существующей системы.
Не дублировать уже существующие механизмы.
Не создавать параллельные Tier, Risk, Allocation или Execution модели, если такие механизмы уже существуют.
Сначала найти канонический текущий flow.


⸻


4. Read-before-work gate
Перед внесением любых изменений необходимо прочитать актуальные canonical project documents и последний handoff проекта.
Обязательно найти и изучить:
текущую архитектуру SPA;
portfolio/allocation logic;
Risk Policy;
определения Tier 1 / Tier 2 / Tier 3 / Candidate;
execution architecture;
agents responsible за APY/risk monitoring;
portfolio position sizing;
ADR, относящиеся к portfolio allocation;
ADR-025 и связанные с ним решения, если они относятся к текущему flow;
последние handoff/state documents;
существующий owner UX;
существующие tests для portfolio/risk/execution loop.
До начала реализации зафиксировать:
READ-BEFORE-WORK
docs read:
ADR read:
handoff read:
current branch/commit:
current canonical architecture source:
Работа не должна строиться на памяти AI-сессии.


⸻


5. Этап 1 — As-Is Investigation
До изменения кода проследить полный жизненный цикл allocation decision.
Необходимо определить:
market/APY data
↓
research / monitoring agents
↓
opportunity evaluation
↓
portfolio allocation
↓
position sizing
↓
risk policy
↓
rebalance decision
↓
execution planning
↓
execution
↓
post-trade verification
↓
reporting

---
_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении закрой карточку со ссылкой на порождённую работу (§6.4)._

---

## Приоритет high + осколки склеены (цикл #310, задание владельца 19.08)

Владелец 19.08: «Подними приоритет `inbox-task-portfolio-cio-dynamic-capital-alloc` на high.
Шесть карточек-осколков от 13.08 склей в якорную и закрой как дубли. Начни с этапа диагностики
по моему ТЗ: почему 40 % в Aave под 2.7 %, что блокирует risk gate (9 blocks/день), где рвётся
цепочка allocator→gate→execution.»

Исполнено:

1. `priority: high` — проставлен.
2. Шесть осколков закрыты как дубли этой карточки (все — куски ЭТОГО ТЗ, разрезанные интейком
   по границам Telegram-сообщений): `inbox-why-it-exists`, `inbox-dlya-kazhdogo-etapa-pokazat`,
   `inbox-actual-costs`, `inbox-apy-persistence-confidence`,
   `inbox-esli-tot-zhe-target-mozhno-priblizit-pro`, `inbox-100-zapuskov-na-odnom-snapshot`.
3. **Этап диагностики уже исполнен — заново не делаю** (шаг 1a протокола, «не делали ли мы это
   уже»): документ **`docs/research/RS-portfolio-cio-diagnosis.md`**, доставлен 19.08
   (коммиты `891ad092e`, `9b432abf3`), карточка-приёмник
   `inbox-cio-etap1-diagnostika-gotova-ispolnyat-g1-g4`.

**Ответы на три твоих вопроса — коротко (доказательства в документе):**

| твой вопрос | ответ диагностики |
|---|---|
| почему 40 % в Aave под 2.7 % | аллокатор **не статичен**, оптимум считается каждый цикл; книга стояла, потому что входы не менялись ⇒ `diff < $200` ⇒ no trade. Инерция не в правиле, а в НАБЛЮДАЕМОСТИ |
| что блокирует risk gate («9 blocks/день») | гейты (ADR-061/053/MP-011) блокировали **правильно**: это ≈ по паре строк на каждый пул без доказанного живого числа, а не 9 инцидентов |
| где рвётся цепочка allocator→gate→execution | не в цепочке — в **входах**: из $80k только $20k (pendle) ранжировались по живому числу, у 12 адаптеров схемный fail-OPEN (ADR-060 §1.2) |

Дальше по документу §4 — гэпы **G1 (наблюдаемость)** → G2 → G3 → G4; замером 19.08 уточнено,
что **G4 не воспроизводится, а G2 в main пуст**. ~70 % ТЗ уже принято решениями ADR-055 + ADR-060
(SHADOW до честных чисел) — **заново не строить**.

---

## Цикл #389 (2026-08-27) — приказ владельца 26.08 исполнен: сделана половина G1 (D6)

Карточка ОСТАЁТСЯ открытой: доделана одна позиция списка, не весь список.

**Перемерено, а не принято на веру.** Дефект D6 ADR-060 («расхождение pendle-фидов»,
описан 02.08) жив 25 дней спустя ДОСЛОВНО. Замер 26.08 20:47Z, два артефакта,
написанные одним дневным циклом с разрывом 0,6 с:

| | доходность | тир | TVL |
|---|---|---|---|
| `data/adapter_status.json` | 8,0 % (`live_apy: null` ⇒ литерал) | 2 | $500 000 000 (`static`) |
| `data/adapter_orchestrator_status.json` | 13,9673 % (`live_data: true`) | **T3** | $6 151 592 (`live`) |

Сверх карточки D6 (там названо только расхождение доходности) измерены ещё две вещи:

1. **Тир расходится тоже** — T2 против T3. Тир это ПОТОЛОК концентрации, а не подпись:
   два ответа = два разных потолка на один капитал.
2. **Живое число выдаётся в обход собственного порога адаптера.** Живой запрос 27.08:
   у Pendle три eligible-рынка, и `_classify_tier` возвращает `None` («не годится»)
   для ВСЕХ ТРЁХ ($6,1 / $10,2 / $5,5 млн при пороге T3 $20 млн). `get_markets()`
   отказ соблюдает и отдаёт **0 рынков**; `get_yield_info()` — то есть ровно тот метод,
   чьё число уезжает в снимок оркестратора, — делает `_classify_tier(tvl) or "T3"` и
   отдаёт «14,39 %, tier T3, tvl_source=live». Один класс, одни данные, одна секунда:
   «подходящих нет» и «годится, 14,39 %». Это потерянная коэрция отказа — тот же класс,
   что `inbox-slepota-mozhet-byt-poteryannoi-koerciei`.

**Доставлено (автономно, не money-path):** `spa_core/monitoring/adapter_feed_divergence.py` —
сторож, отвечающий на вопрос, которого не задавал ни один существующий: «говорят ли два
артефакта об ОДНОМ протоколе одно и то же». Рода расхождений разделены намеренно
(`live_vs_live` = противоречие наблюдений, инвариант 2, CRITICAL · `literal_vs_live` =
одна сторона не наблюдала, WARN · `both_literal` · `tier_mismatch`); провенанс TVL —
INFO, чтобы 6 из 8 протоколов не кричали ежедневно о решённом (ADR-053). Считается в
`com.spa.decision_loop` (без нового агента ⇒ без деплоя), читается ОБЯЗАТЕЛЬНЫМ шагом
0-офис каждого цикла. 21 тест, каждый — положительный контроль на замер 26.08; приёмка
шестью мутациями, включая две мутации ПРОВОДКИ.

**Отдано владельцу (money-path, автономно запрещено):**
`owner-decision-pyataya-chast-deneg-stoit-na-chisle-o-ko` — какое число и какой тир
считать правдой для 20 % книги, и чинить ли коэрцию отказа в адаптере.

**Дальше по списку:** вторая половина G1 (схема `adapter_status.json` — статус починки
12 адаптеров перемерить живым замером, §6 диагностики), затем SHADOW-замер ADR-060 и
отдельный вопрос про ARM.

---

## ВОССТАНОВЛЕНО: полный текст ТЗ владельца, §5-окончание … §52 (цикл cloud-сессии, 2026-08-29)

**Почему эта секция появилась.** Замер 29.08: тело этой карточки обрывалось на середине §5,
а разделы 6–52 физически существовали ТОЛЬКО в шести карточках-осколках со статусом `done`.
Каждая из них при закрытии (цикл #310, 19.08) утверждала дословно: «Ничего не потеряно: текст
этого осколка есть в якорном ТЗ» — **и это было неверно**. Склейка была объявлена, но не
исполнена: закрытие дублей произошло, перенос текста — нет. То есть 47 разделов требований
владельца (экономика перехода, marginal APY, anti-churn, 15 сценариев тестов, Definition of
Done, формат отчёта владельцу) полтора месяца были недоступны любому, кто читал якорь.

Ниже — **дословная** склейка, собранная скриптом из тел осколков (не пересказ). Швы сходятся
встык, нумерация владельца непрерывна 1…52. Источник каждого куска назван перед ним.

<!-- источник: inbox-dlya-kazhdogo-etapa-pokazat.md строки 12-201 (окончание §5 → начало §10) -->

Для каждого этапа показать:
какой компонент отвечает;
какие данные получает;
какие данные возвращает;
какие policy применяются;
каким образом передается решение следующему компоненту.
Особенно ответить на следующие вопросы.
Aave
Почему Aave сейчас занимает:
$40,000
39.7% portfolio
2.7% APY
Кто и когда принял решение о размере $40,000?
Является ли $40k:
hardcoded allocation;
Tier allocation;
initial allocation;
maximum allocation;
target allocation;
historical allocation, который никто не пересматривает;
результатом optimizer;
чем-то другим?
Почему при падении APY до 2.7% позиция не уменьшается?
Cash
Почему Cash составляет:
$10,867
10.8%
Является ли это:
liquidity reserve;
unallocated capital;
failed deployment;
policy reserve;
intentional cash buffer?
Какой target cash allocation установлен системой?
Risk blocks
Открыть и проанализировать:
risk_policy_blocks.json
для Day 65.
Разобрать все 9 блокировок.
Для каждой показать:
timestamp
proposed action
source
destination
amount
rule that blocked
reason
whether block was correct
economic consequence
Определить:
блокирует ли Risk Policy потенциально разумные portfolio reallocations.
Paper APY
Проверить расчет:
Paper APY: 6.89%
Он выглядит потенциально несовместимым с displayed allocation/APY.
Необходимо установить точную формулу Paper APY.
Разделить:
displayed APY
weighted position APY
gross portfolio APY
net portfolio APY
realized APY
paper/model APY
Не допускать использования одного названия APY для разных экономических показателей.


⸻


6. Deliverable после Investigation
До реализации подготовить документ:
PORTFOLIO_CIO_AS_IS.md
Он должен содержать:
Current architecture
Как система работает сейчас.
Root cause
Почему возможно состояние:
39.7% portfolio at 2.7% APY
при наличии более доходных opportunities.
Existing reusable components
Что уже существует и не должно переписываться.
Missing capability
Какой конкретно capability отсутствует.
Policy conflicts
Какие existing policies препятствуют нормальной работе системы.
Recommended architecture
Минимально необходимое архитектурное изменение.
Только после этого переходить к реализации.


⸻


7. Целевая модель
Если investigation подтверждает отсутствие portfolio-level allocator/CIO либо недостаточность существующего механизма, реализовать следующий capability.
Portfolio CIO должен видеть:
100% portfolio
а не принимать решения по отдельным протоколам независимо.
Главная модель:
CURRENT ALLOCATION
        ↓
AVAILABLE POLICY-COMPLIANT OPPORTUNITIES
        ↓
TARGET PORTFOLIO OPTIMIZATION
        ↓
TARGET ALLOCATION
        ↓
REBALANCING ECONOMICS
        ↓
KEEP / REBALANCE / DEFER / RISK ACTION
        ↓
RISK POLICY
        ↓
PRE-TRADE SIMULATION
        ↓
EXECUTION
        ↓
POST-TRADE MONITORING


⸻


8. Разделить Target Allocation и Rebalancing
Это два разных решения.
Target Allocation
Отвечает:
Если бы капитал распределялся заново сейчас, как должна выглядеть оптимальная policy-compliant структура портфеля?
Например:
Current

Aave       39.7%
Pendle     19.8%
Maple      19.8%
Morpho      9.9%
Cash       10.8%
Optimizer может рассчитать условный:
Target

Aave       20%
Pendle     25%
Maple      20%
Morpho     20%
Cash       15%
Это только пример, не policy.
Rebalancing Decision
После этого система должна решить:
Стоит ли сейчас платить за переход Current → Target?
Возможный ответ:
NO
даже если Target отличается от Current.


⸻


9. Не использовать raw APY как главный показатель
Текущий APY нельзя считать ожидаемой доходностью.
Необходимо различать:
current APY
base APY
reward/incentive APY
historical APY
expected APY
conservative expected APY
net expected APY
marginal APY after our capital
Высокий APY может оказаться:
краткосрочным utilization spike;
временным reward boost;
результатом падения TVL;
ошибкой источника;
incentive, который заканчивается;
доходностью reward token с плохой liquidity;
доходностью, которая исчезнет после нашего большого deposit.


⸻


10. APY persistence
Для каждого opportunity анализировать минимум:
current
1h
6h
24h
7d
а при наличии данных — более длинную историю.
Необходим показатель:

<!-- источник: inbox-apy-persistence-confidence.md строки 12-227 (§10 → §20) -->

APY Persistence / Confidence
Система должна определять, насколько вероятно, что преимущество сохранится.
Первая версия должна быть прозрачной и детерминированной.
Не использовать opaque ML как обязательный компонент v1.
Можно использовать:
rolling averages;
weighted averages;
volatility;
duration above threshold;
mean reversion;
incentive expiry;
utilization trend;
TVL trend.


⸻


11. Conservative Expected APY
Ввести понятие:
Conservative Expected APY
Возможная логика:
Expected Base APY
+
Expected Incentive APY × Persistence Factor
-
Uncertainty Haircut
Формула может быть уточнена после анализа существующей системы.
Главное требование:
Displayed APY != Expected APY.


⸻


12. Marginal APY
Обязательно учитывать влияние нашего капитала.
Если vault показывает:
8% APY
это не означает, что $40k можно разместить под 8%.
Нужно оценивать:
APY at +$5k
APY at +$10k
APY at +$20k
APY at +$40k
если протокол позволяет получить такую оценку.
Учитывать:
TVL dilution;
utilization;
reward dilution;
capacity;
deposit caps;
liquidity;
withdrawal depth.
Optimizer должен по возможности распределять капитал по marginal return curve.


⸻


13. Transaction economics
Для каждого rebalance:
source
destination
amount
рассчитать полную стоимость.
Включить:
withdraw gas
deposit gas
claim gas
swap fee
protocol fee
slippage
market impact
bridge cost
future exit cost
Рассчитать:
Gross Incremental Yield

Net Incremental Yield

Expected Incremental Profit

Break-even Time
Базовая логика:
Expected Incremental Profit
=
Capital Moved
×
(Expected Destination APY - Expected Source APY)
×
Expected Holding Period / 365
-
Total Switching Cost
И:
Break-even Days
=
Total Switching Cost
/
Daily Incremental Yield


⸻


14. Учитывать round trip
Ошибка:
A → B
не должна оцениваться только по стоимости входа в B.
Нужно оценивать:
A exit
+
B entry
+
eventual B exit
Если высока вероятность скорой новой ребалансировки, это должно снижать привлекательность операции.


⸻


15. Portfolio optimization objective
Optimizer должен приблизительно решать:
MAXIMIZE

Expected Net Portfolio Yield

MINUS

transaction cost
risk penalty
concentration penalty
uncertainty penalty
turnover penalty
liquidity penalty
при constraints действующей Risk Policy.
Необходим deterministic calculation layer.
LLM не должен быть источником финансовой математики.


⸻


16. Risk
Использовать существующую каноническую Risk Policy.
Не создавать альтернативную.
Portfolio CIO не имеет права обходить Risk Gate.
Risk должен учитывать как минимум уже существующие ограничения, а если некоторые отсутствуют — вынести предложение отдельно:
protocol concentration
vault concentration
Tier concentration
chain concentration
asset concentration
strategy concentration
liquidity
withdrawal availability
correlated dependencies


⸻


17. Correlated risk
Несколько vault не всегда означают диверсификацию.
По возможности учитывать общие зависимости:
protocol
chain
oracle
curator
collateral
stablecoin
bridge
smart-contract implementation
reward token
liquidity venue
Если три vault зависят от одного и того же systemic component, они не должны автоматически считаться тремя независимыми risk buckets.


⸻


18. Asset allocation boundary
Portfolio CIO не должен самостоятельно менять strategic underlying exposure.
Пример:
нельзя продавать BTC/ETH и переходить в USDC только потому, что USDC yield выше.
Нужно разделить:
Strategic Asset Allocation
и
Yield Optimization inside approved asset allocation
В рамках этой задачи работать внутри уже разрешенной asset exposure.


⸻


19. Candidate и Tier
Найти существующие canonical definitions.
Не придумывать новые.
По умолчанию Candidate должен:
MONITOR
SCORE
COMPARE
но не получать capital автоматически, если existing policy этого не разрешает.
Tier должен влиять на допустимый risk/size, а не жестко фиксировать allocation.


⸻


20. New capital
Новый incoming capital должен использоваться умнее, чем существующий капитал.
Если поступает новый депозит, сначала направлять его в underallocated opportunities согласно Target Allocation.
Не делать:
withdraw A
deposit B

<!-- источник: inbox-esli-tot-zhe-target-mozhno-priblizit-pro.md строки 12-286 (§20 → §31) -->

если тот же target можно приблизить простым:
new money → B
без лишнего turnover.


⸻


21. Частота работы
Не связывать monitoring frequency и trading frequency.
Monitoring
Работает часто.
Ориентир:
5–10 min
или event-driven, если такая архитектура уже существует.
Target allocation recalculation
Ориентир:
hourly
и event-driven при значимых изменениях.
События:
APY movement
TVL movement
utilization
risk score change
new capital
withdrawal
reward expiry
gas regime change
liquidity change
Tier change
security alert
Trading
Не происходит автоматически после каждого recalculation.


⸻


22. Anti-churn / hysteresis
Обязательно реализовать защиту от:
A → B → A → B
из-за небольших колебаний APY.
Использовать policy-configurable параметры:
minimum yield edge
minimum net gain
minimum allocation delta
minimum persistence
minimum confidence
cooldown
maximum daily turnover
rebalance cost budget
decision expiry
Все значения должны быть config/policy.
Не hardcode.


⸻


23. Starting policy for Shadow Mode
Для shadow testing можно использовать стартовые значения, но не считать их production policy.
Пример:
minimum 3 consecutive confirmations

expected persistence
>= 3 × break-even period

expected net economic benefit
>= 3 × switching cost

target allocation difference
>= 3–5 percentage points

cooldown
~6h

maximum daily turnover
20–25%
После simulation/backtest значения должны быть откалиброваны.


⸻


24. Decision types
Portfolio CIO должен выдавать строго типизированный результат:
KEEP
REBALANCE
DEFER
REDUCE_RISK
EMERGENCY_EXIT
REQUIRE_OWNER_APPROVAL
Не использовать свободный текст как единственный machine-readable результат.


⸻


25. Decision payload
Для каждого решения сохранять:
timestamp

current allocation

target allocation

recommended actionable allocation

source

destination

amount

portfolio percentage

source expected APY

destination displayed APY

destination conservative APY

destination marginal APY

expected portfolio APY before

expected portfolio APY after

gross incremental profit

transaction cost

expected net profit

break-even

expected holding period

risk change

concentration change

confidence

decision type

decision reason

rejected alternatives

policy checks

data freshness

decision expiry


⸻


26. Determinism
При одинаковых:
market snapshot
portfolio state
risk policy
configuration
Portfolio Optimizer должен выдавать одинаковый результат.
LLM может:
объяснять;
summarise;
формировать owner-facing recommendation.
LLM не должен определять:
арифметику;
allocation constraints;
финансовые расчеты;
policy pass/fail.


⸻


27. Pre-trade check
Между recommendation и execution обязательно выполнить повторную проверку.
Проверить:
fresh APY
fresh gas
fresh liquidity
fresh slippage
withdraw simulation
deposit simulation
position impact
policy
expected economics
Если opportunity исчезла:
CANCEL / DEFER
а не исполнять устаревшее решение.


⸻


28. Decision expiry
Каждое investment decision должно иметь TTL.
Например:
valid_until
Если execution не произошел до TTL:
решение нельзя выполнять без нового расчета.


⸻


29. Emergency mode
Обычная yield optimization и emergency risk management — разные процессы.
При:
exploit
depeg
oracle failure
withdrawal issue
protocol suspension
critical security alert
сохранность капитала имеет приоритет над:
gas
APY
break-even
cooldown
turnover
Использовать существующую emergency policy либо спроектировать extension отдельно.


⸻


30. Shadow Mode — обязательный этап
Не подключать реальный capital execution сразу.
После реализации Portfolio CIO сначала работает:
SHADOW MODE
Он видит реальные данные и портфель, но не выполняет транзакции.
Каждый cycle сохраняет:
what current system did

what Portfolio CIO recommended

why

estimated outcome

what happened afterwards


⸻


31. Counterfactual tracking
Для каждой неисполненной shadow recommendation отслеживать:
Что было бы, если бы мы ее выполнили?
Например:
T0:
Move $15k Aave → Morpho

Expected break-even:
1.8 days

Expected holding:
14 days
После:
1h
6h
24h
3d
7d
пересчитывать:
actual opportunity APY
actual theoretical gain

<!-- источник: inbox-actual-costs.md строки 12-339 (§31 → §37 Test 15) -->

actual costs
whether recommendation was good


⸻


32. Ошибки, которые необходимо измерять
Минимум:
False Rebalance

Missed Opportunity

Late Rebalance

Excessive Turnover

Risk Violation

APY Forecast Error

Break-even Forecast Error


⸻


33. Portfolio KPIs
Ввести измеримые метрики Portfolio CIO.
Минимум:
Gross Portfolio APY

Net Portfolio APY

Realized Portfolio Yield

Optimal Policy-Compliant APY

Yield Gap

Transaction Cost Drag

Portfolio Turnover

False Rebalance Rate

Missed Opportunity Cost

Forecast Accuracy

Average Break-even

Risk Policy Violations
Особенно важен:
Yield Gap
=
Optimal Policy-Compliant Expected APY
-
Current Expected APY
Это показывает, сколько доходности теряет текущая аллокация.


⸻


34. Daily Report
Обновить SPA Daily Report.
Сохранить существующие полезные части, но добавить CIO section.
Пример:
🧠 Portfolio CIO

Current expected net APY: 4.1%
Optimal policy-compliant APY: 5.3%
Yield gap: 1.2 pp

Target allocation:
Aave: 22%
Pendle: 24%
Maple: 20%
Morpho: 19%
Cash: 15%

Decision: REBALANCE

Recommended:
Move $12,000
Aave → Morpho

Expected incremental return:
7d: +$X
30d: +$X
90d: +$X

Switching cost: $X
Break-even: X days
Expected persistence: X days

Risk:
before X
after X

Confidence: HIGH
Если ничего делать не надо:
Decision: KEEP

Reason:
No available rebalance currently exceeds required net economic threshold.


⸻


35. Paper APY cleanup
Отдельно исправить или документировать текущий Paper APY.
Owner должен четко видеть различие:
Current displayed weighted APY

Expected Net APY

Realized APY

7-day realized/estimated APY

Optimal policy-compliant APY
Не использовать неочевидную метрику без понятного определения.


⸻


36. Owner UI
Следовать owner-first принципу.
Owner не должен видеть:
optimizer internals
JSON
policy hashes
technical IDs
implementation paths
internal states
на основном экране.
Основной вывод:
Текущая доходность

Потенциальная доходность

Есть ли проблема

Что система предлагает сделать

Сколько это даст

Сколько стоит

Когда окупится

Изменится ли риск

Нужна ли моя реакция
Technical details скрыть в:
Подробнее


⸻


37. Testing scenarios
Необходимо реализовать automated tests и scenario tests.
Test 1 — очевидно плохая текущая аллокация
Aave:
40%
3%

Morpho:
10%
6%
оба допустимы Risk Policy.
Low switching cost.
Stable destination APY.
Expected:
REBALANCE
но не обязательно перемещение всех 40%.


⸻


Test 2 — transient spike
Destination:
3% → 12%
на несколько минут, затем обратно.
Expected:
KEEP / DEFER


⸻


Test 3 — expensive transaction
APY difference:
+2%
Break-even:
20 days
Expected persistence:
5 days
Expected:
KEEP


⸻


Test 4 — Candidate 20%
Candidate показывает:
20% APY
Expected:
не обходить Tier/Risk Policy.


⸻


Test 5 — marginal yield collapse
Displayed:
8%
After our deposit:
3.5%
Expected:
уменьшить position size или отказаться.


⸻


Test 6 — correlation
Несколько vault используют одинаковые critical dependencies.
Expected:
применять concentration/correlation constraints.


⸻


Test 7 — stale data
APY свежий.
Liquidity stale.
Expected:
NO EXECUTION


⸻


Test 8 — high gas
Economically good opportunity.
Gas временно делает trade плохим.
Expected:
DEFER


⸻


Test 9 — gas falls
Та же opportunity сохраняется.
Gas падает.
Expected:
новый расчет может перейти:
DEFER → REBALANCE


⸻


Test 10 — new capital
+$10k new cash.
Portfolio underallocated в Morpho.
Expected:
использовать новый capital для приближения к Target, не делать лишний Aave withdrawal.


⸻


Test 11 — APY disappears before execution
Recommendation создан.
До execution APY падает.
Expected:
pre-trade validation отменяет execution.


⸻


Test 12 — oscillating APYs
A и B постоянно меняются:
5.0 / 5.3
5.4 / 5.1
5.0 / 5.3
Expected:
никакого churn.


⸻


Test 13 — concentration limit
Лучший vault показывает отличный yield.
Оптимальная математическая allocation:
70%
Risk policy max:
25%
Expected:
25% max


⸻


Test 14 — emergency
Current protocol получает critical security alert.
Expected:
Risk action имеет приоритет над normal yield optimization.


⸻


Test 15 — same snapshot determinism

<!-- источник: inbox-100-zapuskov-na-odnom-snapshot.md строки 12-286 (§37 Test 15 → §48 CURRENT RULE) -->

100 запусков на одном snapshot.
Expected:
идентичный calculation output.


⸻


38. Historical replay
Если доступна historical data SPA:
прогнать новый allocator на прошлом периоде без look-ahead bias.
Минимум сравнить:
Current Strategy

vs

Portfolio CIO Shadow Strategy
По:
Net APY

Realized Return

Gas

Fees

Turnover

Risk Events

Max Concentration

False Rebalances

Missed Opportunities
Главная цель:
не показать максимальный APY на бумаге.
Главная цель:
показать улучшение:
risk-adjusted realized net return


⸻


39. Observation period
Перед реальным capital execution Portfolio CIO должен пройти shadow observation.
Duration определить на основании доступности данных и existing release process.
Не использовать только количество дней как критерий.
Нужен минимальный набор рыночных событий:
APY spike;
stable opportunity;
high gas;
low gas;
opportunity disappearing;
incoming capital;
risk block;
no-action period.


⸻


40. Release stages
Использовать поэтапный запуск.
Stage 0
Diagnosis only
Никаких изменений allocation.


⸻


Stage 1
Shadow CIO
Recommendations only.


⸻


Stage 2
Owner-approved execution
CIO предлагает.
Owner подтверждает.


⸻


Stage 3
Limited auto-execution
Только внутри заранее утвержденных bands.


⸻


Stage 4
Policy-bounded autonomous rebalancing
Только после доказательства безопасности предыдущих стадий.


⸻


41. Auto-execution limits
Если будет разрешен auto-execution, предусмотреть:
max trade amount

max % portfolio per rebalance

max daily turnover

allowed protocols

allowed vaults

allowed tiers

allowed chains

allowed assets

minimum expected net gain

minimum confidence

minimum persistence

maximum acceptable risk delta
Все policy-configurable.


⸻


42. Kill switch
Обязательно:
PAUSE CIO
PAUSE AUTO EXECUTION
EMERGENCY STOP
Owner должен иметь возможность остановить execution без остановки monitoring/reporting.


⸻


43. Audit trail
Каждое решение должно быть воспроизводимо.
Сохранять:
market snapshot
portfolio snapshot
policy version
configuration version
optimizer version
decision
calculations
execution result
post-trade result
Через месяц должно быть возможно ответить:
Почему система 13 августа переместила $12,000 из Aave в Morpho?
Не через память AI.
Через данные.


⸻


44. Explainability
Для каждой recommendation owner explanation должна быть простой.
Плохой вариант:
utility score 0.7234
Хороший:
Aave currently earns 2.7%.

Morpho's conservative expected yield is 4.5%.

After moving $12k the projected Morpho yield remains 4.3%.

Estimated switching cost is $7.80.

Expected break-even is 2.6 days.

The yield advantage has persisted for 36 hours.

Risk remains inside existing limits.

Recommendation: move $12k.


⸻


45. Architecture constraints
Не создавать одного огромного AI-agent, который:
читает рынок;
считает APY;
считает gas;
принимает risk decision;
подписывает транзакцию.
Разделить:
Data
↓
Deterministic Portfolio Optimizer
↓
Risk Policy
↓
Execution Planner
↓
Execution
↓
Monitoring
AI/LLM может быть orchestration/explanation layer, но не единственным финансовым control layer.


⸻


46. Минимальный proposed component map
После исследования адаптировать к существующей архитектуре.
Не создавать новые компоненты, если эквиваленты уже существуют.
Концептуально:
Opportunity Data
        ↓
Portfolio State
        ↓
Portfolio Optimizer
        ↓
Target Allocation
        ↓
Rebalance Evaluator
        ↓
Risk Gate
        ↓
Execution Planner
        ↓
Execution Agent
        ↓
Post-Trade Monitor
        ↓
Reporting
Portfolio CIO является orchestration/business layer над этим flow.


⸻


47. Failure modes
Система должна fail-safe.
При:
missing APY
stale data
conflicting sources
missing liquidity
simulation failure
risk service unavailable
unknown Tier
unknown protocol
unknown asset
price uncertainty
не выполнять automatic rebalance.
Использовать:
DEFER
или соответствующее safe состояние.


⸻


48. Изменения Risk Policy
Если investigation покажет, что существующая Risk Policy блокирует разумную работу allocator:
не ослаблять policy молча.
Сформировать отдельный proposal:
CURRENT RULE

<!-- источник: inbox-why-it-exists.md строки 12-148 (§48 → §52 (конец ТЗ)) -->

WHY IT EXISTS

WHAT IT BLOCKS

ECONOMIC IMPACT

PROPOSED CHANGE

NEW RISK

MITIGATION

OWNER DECISION REQUIRED
Без owner approval не менять существенные risk boundaries.


⸻


49. Acceptance criteria
Работа считается выполненной только когда доказано следующее.
Architecture
Portfolio-level decision owner существует.
Economics
Решения используют net expected return, а не raw APY.
Persistence
Transient APY spikes не вызывают ненужные trades.
Costs
Gas/fees/slippage/exit cost учитываются.
Marginal return
Position size влияет на expected yield.
Risk
Risk Policy невозможно обойти.
Determinism
Calculations reproducible.
Anti-churn
Система не прыгает между одинаковыми opportunities.
Pre-trade safety
Каждый trade пересчитывается непосредственно перед execution.
Auditability
Каждое решение имеет snapshot и explanation.
Owner visibility
Owner видит current/optimal APY, Yield Gap и recommendation.
Shadow verification
Проведены shadow/replay tests.
No regression
Existing risk/security/architecture tests проходят.


⸻


50. Definition of Done
Не считать задачу завершенной после:
code implemented
tests green
agent exists
Definition of Done:
Выполнена диагностика текущей системы.
Объяснено текущее состояние Day 65 и причины Aave 39.7%.
Разобраны 9 risk_policy_blocks.
Проверена формула Paper APY.
Зафиксирован root cause.
Target architecture утверждена и записана.
Реализован deterministic portfolio optimization capability.
Реализован rebalance economics layer.
Реализованы persistence и anti-churn gates.
Реализованы pre-trade checks.
Сохранена совместимость с существующей Risk Policy.
Все scenario tests проходят.
Historical replay/shadow run выполнен.
Новый CIO показывает понятный Yield Gap.
Daily Report обновлен.
Shadow recommendations имеют counterfactual tracking.
Есть owner pause/kill switch.
Есть audit trail.
Нет автоматического real-money execution без прохождения release stages.
Реальная работа Portfolio CIO доказана на нескольких market conditions.


⸻


51. Required final report from Claude
После завершения работы не давать owner длинный список файлов.
Подготовить owner-level итог:
1. Что было неправильно

2. Почему Aave мог держать 39.7% под 2.7%

3. Что оказалось причиной blocked_by_policy

4. Что изменено

5. Как теперь принимается allocation decision

6. Как система защищается от краткосрочных APY spikes

7. Как учитываются gas и break-even

8. Как выглядит новый Daily Report

9. Результаты shadow/backtest

10. Было:
   Net APY
   Turnover
   Costs

11. Стало:
   Net APY
   Turnover
   Costs

12. Какие риски остаются

13. Что сейчас работает:
   diagnosis / shadow / owner approval / auto

14. Какой следующий рекомендуемый шаг
Все технические подробности оставить в canonical engineering artifacts и приложить только как references.


⸻


52. Финальный принцип
Portfolio CIO не является:
APY chaser.
Он является:
управляющим капиталом всего портфеля.
Правильное решение может быть:
Переместить капитал.
Но правильное решение также может быть:
APY в другом vault выше, но преимущество недостаточно устойчиво, потенциальный доход не покрывает стоимость и риск переключения. Оставляем капитал на месте и пересчитываем ситуацию позже.
Главный критерий качества системы:
Не насколько высокий APY она нашла, а насколько хорошо она управляет risk-adjusted realized net return всего портфеля после всех расходов.

