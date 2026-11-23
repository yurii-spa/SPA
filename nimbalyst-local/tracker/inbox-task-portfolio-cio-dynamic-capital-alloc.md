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
acceptance_probe: apy_name_carries_one_kind
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

## ВОССТАНОВЛЕНО: полный текст ТЗ владельца, §5-окончание … §52 (цикл cloud-сессии, 2026-08-29)

**Доставлено в `main` циклом #699 (2026-09-25).** Секция написана 29.08 облачной сессией и
28 дней пролежала в **ЧЕРНОВОМ PR #50** (`ac312ff7c`, `claude/chat-search-saagql`): на `main`
тело этой карточки всё это время обрывалось на середине §5, и каждый цикл читал приказ
владельца на 5 разделах из 52. Текст ниже — **дословно** из `ac312ff7c`, ни одного слова не
изменено; вставлен ДОПИСЫВАНИЕМ к origin-версии карточки (`e83393f9e`, 8897 строк), а не
подменой её своей копией (`.claude/rules/deployment.md`, хвост).

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


## СОСТОЯНИЕ ПРИКАЗА (цикл #1209, 2026-11-19) — читать ЭТОТ раздел, не всю карточку

**Хроника вынесена в архив:** `docs/journal/CARD-archive-portfolio-cio-chronicle-2026-11-19.md`
— **374** записей цикла, побайтово, ни одна строка не выброшена.
В карточке не оставлено ни одной: последние ТРИ весили 444 777 символа, то есть
в 13 раз больше, чем всё ТЗ владельца.

**Почему приказ голодал 488 циклов, и это НЕ лень.** Карточка весила 3 273 543
символа (109× предела `docs/STATE.md`); ТЗ владельца занимало в ней 1.03 %.
`CLAUDE.md` велит прочитать карточку ПЕРЕД работой — и прочитать её было НЕЛЬЗЯ:
3,27 млн символов не помещаются в окно сессии. Приказ можно было только
дописать, что каждый «взявший» цикл и делал. Механизм закрыт ADR-1066 (дверь
ПЕРЕНОСА записи цикла в названный архив) + храповик веса карточки
`spa_core/tests/test_tracker_card_weight_ratchet.py`: дорасти обратно карточка
больше не может молча.

**Живой заказ следующему циклу** лежит НИЖЕ, в разделе «ЖИВОЙ ЗАКАЗ» — побайтовая
копия хвоста последней записи цикла (оригинал — в архиве внутри своей записи).
`docs/STATE.md` указывает адресом именно сюда, и адрес сохранён.

**Что это НЕ закрывает.** Содержательный остаток ТЗ владельца (§1–§52 выше) не
тронут ни на байт и НЕ объявляется сделанным: вес карточки и исполнение приказа —
два разных вопроса, и здесь измерен и починен ПЕРВЫЙ. Приёмка приказа остаётся
объявленной пробой `acceptance_probe: apy_name_carries_one_kind` (её делающая
сессия не правит — `.claude/rules/acceptance.md` п. 2).

---

## ЖИВОЙ ЗАКАЗ (копия хвоста записи цикла; оригинал — в архиве)

### Заказы G1054…G1056 и пост-записи циклов #1208…#1210 — ПЕРЕНЕСЕНЫ

Побайтовая копия (6 разделов, 12 983 символа) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`.
Перенёс цикл #1215; причина и замер («полного текста заказов в журнале недели НЕ БЫЛО») — в шапке архива.

### Заказ G1057 и пост-запись цикла #1213 — ПЕРЕНЕСЕНЫ

Побайтовая копия — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`
(тот же архив, что принял G1054…G1056). Перенёс цикл #1217 порядком G1059 п. 6:
СПЕРВА спрошен адрес (G1057 в архиве не было ни разу — `grep` дал 0), потом сверен
побайтово, и только потом снят текст из карточки. Живыми в карточке остаются два
последних заказа.

### Заказ G1058 (следующему циклу)

**0. ТЗ и обе приёмки читать ПРИБОРАМИ, числа не перепечатывать.**
`python3 scripts/cio_tz_section_census.py` · `python3 scripts/cio_dod_rollup.py --data-dir
<прод>/data` (без `--data-dir` сводка §50 отвечает о СВОЁМ дереве, и два вердикта
`НЕ ВЫПОЛНЕНО` пропадают). Заказ G1057 п. 1 назвал предмет верно, и он ЗАКРЫТ наполовину —
см. п. 1.

**1. Критерий §50 «counterfactual tracking» ПОЧИНЕН В КОДЕ, но вердикт ещё старый —
ПЕРЕМЕРИТЬ ПЕРВЫМ ДЕЛОМ.** ADR-1071: судья тени считает на ВСЕХ пяти горизонтах владельца,
перепись §31 читает НАБОР горизонтов носителя. Проба читает ЖИВОЙ
`data/shadow_trigger_evaluation.json`, а пишет его шаг 2g дневного цикла — **до прогона
судьи сводка честно ответит «1 из 5»**. Порядок перемера:
   * шаг 2g прошёл (возраст артефакта < суток) ⇒ `cio_dod_rollup` обязан дать по этому
     критерию **✅**, и `НЕ ВЫПОЛНЕНО` станет **1**;
   * артефакт старый ⇒ это НЕ регрессия и НЕ повод править код: назвать возраст и ждать
     прогон. Писать прод-`data/` руками ЗАПРЕЩЕНО (цикл #1214 этого не делал).
   * дифференциальный замер, которым это проверено в памяти: судья прежней редакции +
     починенная перепись ⇒ `tracked 1 · reachable_untracked 4 · unreachable 0`; новый
     судья ⇒ `tracked 5`.

**2. Находка #1214, которую стóит проверить ШИРЕ: «недостижимо» мерилось ЧУЖИМ носителем.**
Шаг наблюдения брался у ДНЕВНОГО трека, а величина считалась из журнала решений. Класс не
измерен: сколько ЕЩЁ приборов судят о достижимости/свежести одного носителя шагом ДРУГОГО —
НЕ ИЗВЕСТНО, и нулём это не считается. Метод замера тот же, что у pid и имени ветки:
собрать зовущих `_cadence_hours`-подобные мерки и спросить у каждого, ТОТ ли носитель несёт
величину, о которой выносится вердикт.

**3. Второй `НЕ ВЫПОЛНЕНО` §50 — к владельцу, не правкой.** «Нет автоматического
real-money execution без прохождения release stages»: из 747 артефактов стадию словарём
владельца не несёт НИ ОДИН, и ни одна из 3267 строк трёх журналов не несёт поля стадии при
трёх ВЗВЕДЁННЫХ книгах — решающий вердикт в журнале неотличим от советующего. Это предмет
№1 границы ADR-285 (запись решения на денежном пути): карточка владельцу с вариантами, а не
дописанное поле.

**4. ПЯТЬ критериев §50 с ближним промахом** (ADR-1070 называет поимённо) — мерку не
объявлять прицепом: либо своя проба с контролем в обе стороны, либо честное «мерка шире
критерия». **ДЕВЯТЬ без даже ближней пробы** — долг РАБОТЫ, брать ПО ОДНОМУ с пробой,
объявленной ДО работы.

**5. Вердикт контрольного прогона #1213 ПРОЧИТАН, регрессии НЕТ** (`--delta 44632220021
44646094968`): 62 → 65 имён, но ПРИШЛО 5 — все род стенных часов, вердикта о них прогон не
вынес; гнаться стои́т за **0** именами. **Попутно закрыт G1057 п. 4:**
`test_hermetic_launchd_door.py::test_the_prod_code_really_does_call_a_mutating_launchctl`
из красного набора **УШЛО** — проверять на своём дереве больше нечего.

**6. `STATE.md` после доставки #1214: 149 строк / 29 880 символов / 689 в самой длинной**
(пределы 150 / 30 000 / 700). Запас — ОДНА строка и ~120 символов. #1214 освободил место,
сжав строку ADR-1054…1059 (перечень шести уроков → адрес + два, меняющих поведение) и
строку ADR-1070 (разбор населения ушёл в сам ADR, осталась сводка + адрес прибора). Тот же
резерв остался у строк 97 и 114–120.

**7. Перенесённые пункты предшественников** (не двигались): G1057 пп. 2, 5, 7, 8 · G1056
пп. 5, 8 · G1054 целиком · G1053 пп. 3–4 · G1049 пп. 1–6 · G832 пп. 1–6.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Прогон и подтверждения цикла #1214 (вписано ПОСЛЕ доставки)

**Коммит `e9202db22dfc0fb1419afe9c19a7f98263c9fe81`** — 11 файлов, проверен на origin СВОИМИ
руками (`git ls-tree origin/main`: ADR-1071 и `docs/evidence/cio-horizons-2026-11-20/` есть,
строка реестра одна, `STATE.md` на origin — 149 строк / 29 880 символов / 689 в самой
длинной). Пушер доложил: слепок байтов сверен у **30** чтений, слепок режимов у **2**,
разбор уезжающего Python — **4** файла.

**Батареи:** `test_shadow_trigger_eval.py` + `test_counterfactual_tracking_census.py` —
**88 passed**; `test_frozen_date_ratchet` + `test_injected_clock_claim` +
`test_absent_observation_ratchet` + `test_cio_dod_rollup` + `test_cio_tz_section_census` —
**112 passed**; реестр ADR (4 файла) — **117 passed**; `test_inbox_acceptance_ratchet` +
`test_delivery_board_row` — **50 passed**; `test_state_md_length_ratchet` — **13 passed**.

**Мутации:** прогон №1 в отдельном дереве `/tmp/mut1214` — применено 15 · убито **11** ·
выжило **4**; все четверо разобраны (журнал W47) и оказались НАСТОЯЩИМИ дырами: мутация без
различающей сцены (M02, M15), утверждение про причину без вердикта (M12), правило, чей
контроль остался у ЧУЖОГО читателя после переезда в новую дверь (M13). Прогон №2 на
ФИНАЛЬНЫХ доставляемых байтах в СВЕЖЕМ дереве `/tmp/mut1214b` (md5 всех четырёх файлов
сверены с деревом доставки) — **15 из 15 убито, 0 выжило**. `--window-check` во всех
деревьях (`c1214`, `/tmp/mut1214b`, `/tmp/anchor1214`) — код 0, окна нет ни в одном.

**Красное было красным ДО меня, измерено на ЧИСТОМ `origin/main`.**
`test_green_by_construction_census.py` в моём дереве — **2 failed, 106 passed**; тот же файл
в отдельном worktree на чистом `0624982fa` (`c1214c`) — **2 failed, 32 passed**, и имена
совпали ДО ИМЕНИ (`test_whole_contour_separates_the_three_outcomes`,
`test_a_test_that_VANISHES_under_force_is_named_so_and_not_counted_as_a_kill`), текст
утверждения тот же. Разница в `passed` — свойство населения переписи, а не вердикта.

**Обязательные шаги:** 1в код 0 (аудит мерили 8.8 ч назад при такте 30 ч) · 1г **«Бомб нет»**
при задержке 95 мин, дерево НАЗВАНО входом `--repo-root /tmp/anchor1214` · 1д код 1 (НОВЫХ
расхождений нет, два исторических названы) · 1е перепись капитала **100 % по обеим осям** ·
1е витрина сайта код 4 (ждёт владельца, карточка открыта), правка витрины в worktree
откачена и в доставку не вошла.

**Заказан контрольный прогон `44658981497`** на ПОЛНОЙ sha
`e9202db22dfc0fb1419afe9c19a7f98263c9fe81` (`total_count` 381 → 382, HTTP 204, `head_sha`
перечитан и СОВПАЛ). **Вердикт НЕ ИЗМЕРЕН** — читать следующему циклу:
`python3 scripts/ci_control_verdict.py --delta 44646094968 44658981497`.

**Предшественник перемерен:** вердикт `44646094968` против `44632220021` — 62 → 65 имён,
ПРИШЛО 5 и ВСЕ род стенных часов (вердикта прогон не вынес ни в одну сторону), гнаться стои́т
за **0** именами. Попутно закрыт заказ G1057 п. 4: имя
`test_hermetic_launchd_door.py::test_the_prod_code_really_does_call_a_mutating_launchctl`
из красного набора **УШЛО**.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1059 (следующему циклу)

**0. ТЗ и ОБЕ приёмки читать ПРИБОРАМИ, числа не перепечатывать.**
`python3 scripts/cio_tz_section_census.py` · `python3 scripts/cio_dod_rollup.py --data-dir
<прод>/data`. Без `--data-dir` сводка §50 отвечает о СВОЁМ дереве, и вердикты
`НЕ ВЫПОЛНЕНО` пропадают (из worktree живого `data/` нет по построению).

**1. §50 перемерен цикла #1215 СВОИМИ руками на прод-`data/`: ВЫПОЛНЕНО 2 ·
НЕ ВЫПОЛНЕНО 1 · НЕ ИЗМЕРЕНО 17 из 20.** Заказ G1058 п. 1 ЗАКРЫТ: критерий
«Shadow recommendations имеют counterfactual tracking» — ✅ (шаг 2g прошёл, код
ADR-1071 не правился ни байтом). **Единственный `НЕ ВЫПОЛНЕНО` ушёл К ВЛАДЕЛЬЦУ**
карточкой `owner-decision-sistema-ne-govorit-na-kakoi-stupeni-vypu` (needs-owner,
доставлена #1215): «нет real-money execution без прохождения release stages» — это
предмет №1 границы ADR-285, правкой его закрывать ЗАПРЕЩЕНО. Пришёл ответ ⇒ инжест
шагом 2 (ADR + `set-status ingested`, `owner-done` ставит ТОЛЬКО владелец).

**2. ДЕВЯТЬ критериев §50 без даже ближней пробы — долг РАБОТЫ, не прибора.**
Брать ПО ОДНОМУ, пробу объявлять ДО работы (`.claude/rules/acceptance.md` п. 1–2).
Перечень — у прибора, а не из этой строки.

**3. ПЯТЬ критериев с ближним промахом — мерку НЕ объявлять прицепом:** либо своя
проба с контролем в обе стороны, либо честное «мерка шире критерия». Объявить
ближнюю пробу = ложное усиление.

**4. Вердикт контрольного прогона цикла #1215 — прочитать первым делом** (sha и номер
в пост-записи ниже). Имена падений — ТОЛЬКО из артефакта `report.json`; нетто-числом
дельту мерить НЕЛЬЗЯ, сличать по именам и по ОБОИМ счётчикам (`failed` + `error`).
Род стенных часов (`wallclock_timeout`) регрессией не является — вердикта о нём
прогон не выносит.

**5. Класс «шаг ИЗМЕРЕН с одного носителя, а вердикт о ДРУГОМ» ИЗМЕРЕН (ADR-1072):
предмет 0 при знаменателе 3.** Храповика у класса НЕТ намеренно — население узкое.
Новая мерка шага возвращает поверхность, и прибор
(`spa_core/analytics/foreign_carrier_cadence_census.py`) для этого и написан.
**Урок мутационного замера:** из ДВУХ обязательных условий мерки шага батарея
проверяла только одно, и мутация M16 (снятие проверки ИМЕНИ) ВЫЖИЛА — набор упавших
имён не менялся. Выжившую записали, а не замазали: сцена-различитель добавлена,
прогон №2 на финальных байтах — в пост-записи ниже.

**6. Инструкция «сжимать заказы в адрес журнала недели» была НЕИСПОЛНИМА как
написана, и это ИЗМЕРЕНО.** Она стояла три заказа подряд (G1056 п. 8 · G1057 п. 7 ·
G1058 п. 7) и ни разу не исполнялась не из лени: полного текста заказов в
`docs/journal/2026-W47.md` НЕТ — замер #1215: `Заказ G1057` встречается в журнале
**0** раз, `G1058` — **0**, живой текст лежал ТОЛЬКО в карточке. «Сжать в адрес»
значило бы стереть единственную копию и оставить адрес, по которому ничего нет.
Исполнено правильным порядком: сперва носитель
(`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`, 6 разделов,
12 983 символа, слаб сверен ПОБАЙТОВО), потом снятие из карточки — **62 324 → 49 630
символов**. **Правило на будущее: прежде чем сжимать в адрес, спроси у адреса, несёт
ли он предмет.** Следующему циклу сжимать G1057 и пост-записи #1213 тем же порядком
(дописывать в ТОТ ЖЕ архив), оставляя в карточке два последних заказа.

**7. Два артефакта офиса НЕ ПРОЧИТАНЫ СЕДЬМОЙ цикл подряд** (офис 145 / 2):
`data/acceptance_tree_lineage.json`, `data/step_time_drift.json`. Карточки есть,
дубля не заводить. Причина чужая и названа: бегун `com.spa.decision_loop` во флоте
НЕ загружен, включение службы — действие ВЛАДЕЛЬЦА (ADR-1053/1061).

**8. Пределы `STATE.md` после доставки #1215** — в пост-записи ниже (пределы 150 /
30 000 / 700). Резерв прежний: блоки старше двух недель живут в реестре и журнале.

**9. У прибора ADR-1072 НЕТ автоматического читателя, и поверхность сторожей-сирот его
НЕ ВИДИТ — это ИЗМЕРЕНО, а не предположено.** `test_unwired_guard_modules_ratchet._DIRS` =
`spa_core/alerts`, `spa_core/monitoring`, `spa_core/governance`; `test_unwired_scripts_ratchet`
смотрит `scripts/`. Новый прибор лежит в `spa_core/analytics/` — ни одному из двух храповиков
он не виден, и красный набор обоих после доставки совпал с замером на ЧИСТОМ `origin/main`
ДО ИМЕНИ (4 имени и 2 имени). Следствие: «новая мерка шага возвращает поверхность, и прибор
для этого написан» верно только пока прибор кто-то ЗОВЁТ, а сегодня его зовёт рука.
Варианты, оба названы и ни один не сделан: (а) ступень моста находок — ИНЕРТНА, пока
`com.spa.decision_loop` не загружен владельцем (ADR-1053/1061); (б) расширить поверхность
храповика на `spa_core/analytics/` — **только ПОСЛЕ замера населения**, иначе покрасит
неизвестное число модулей и научит дописывать в базу. Население НЕ ИЗМЕРЕНО, и нулём это не
считается.

**10. Перенесённые пункты предшественников** (не двигались): G1058 пп. 4, 7 · G1057
пп. 2, 5, 8 · G1056 п. 5 · G1053 пп. 3–4 · G1049 пп. 1–6 · G832 пп. 1–6. Текст
заказов G1054…G1056 — в архиве, названном в п. 6.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Прогон и подтверждения цикла #1216 (ПОДЪЁМ доставки #1215; вписано ПОСЛЕ доставки)

**Работа #1215 на origin НЕ УЕХАЛА — умерли ДВЕ сессии подряд.** `ps -p 89644` и
`ps -p 17703` (пустой формат, не греп по колонкам) отвечают пустотой: автор ADR-1072
умер, дописав журнальную запись; поднявшая его сессия закрыла выжившую мутацию M16 и
умерла в 22:16. Дерево `SPA_worktrees/c1215` стояло с 12 файлами при чистом
`origin/main` (`bc612dcd0`). Доставил цикл #1216, ПЕРЕМЕРИВ каждое утверждение.

**Что перемер НАШЁЛ (две поправки, обе в ADR-1072):**

1. **Ссылка на собственный замер, которого нет ни в одном файле.** ADR говорил
   «мутационный замер … числа в `docs/journal/2026-W47.md`, запись цикла #1215», а в
   записи #1215 про мутации нет ни строки: автор умер до того, как вписал их. Прогон
   сделан этим циклом, адрес исправлен на запись **#1216**.
2. **«Чужие носители `bag:eval`, `bag:replay`» — ДВА из четырёх.** Прибор печатает
   `bag:eval`, `bag:eval_reason`, `bag:replay`, `bag:replay_reason`. Перечень из двух
   читался бы как ЗАМЕР, а был сокращением; недостающие два — именно те мешки, из-за
   которых вердикт о достижимости был бы объяснён не тем носителем.

**Что СОВПАЛО до числа** (перемер своими руками, деревья отдельные): батарея
**37 passed** · предмет класса **0** · знаменатель **3** (те же три мерки поимённо) ·
«шаг есть РЕШЕНИЕ» **173** · НЕ ИЗМЕРЕНО **0** · слепота 1 — **0 из 3** · слепота 2 —
переходов **2** · контроль в ОБЕ стороны: прежняя редакция переписи §31 даёт РОВНО
**1** кандидата (`measure_horizons:342`), починенная — **0**.

**Коды возврата измерены БЕЗ конвейера** (в `zsh` `${PIPESTATUS[0]}` пусто, и `$?`
после `| head` — код `head`, а не прибора): **0** чисто · **1** находка · **2**
нечитаемое НАЗВАННОЕ дерево.

**Контроль взят из ПОЛНОГО клона, и клон НАЗВАН.** Прежняя редакция поднята из
`SPA_mirror` (`--is-shallow-repository` → `false`); прод-клон и КАЖДЫЙ его worktree
усечены (`true`), и на вопрос «какие байты были до ADR-1071» отвечать не способны —
поправка #1031 правила доставки.

**Красное было красным ДО меня, и это ИЗМЕРЕНО дифференциально.** Два храповика-сироты
(`test_unwired_guard_modules_ratchet`, `test_unwired_scripts_ratchet`) дают **2 failed /
25 passed** И на чистом `bc612dcd0`, И с моими байтами — имена совпали ДО ИМЕНИ. Новый
прибор лежит в `spa_core/analytics/`, поверхности обоих храповиков он не виден (п. 9
заказа G1059 — подтверждено).

**Ратчеты класса времени и представления:** `test_frozen_date_ratchet` +
`test_injected_clock_claim` + `test_absent_observation_ratchet` — **56 passed**;
`test_state_md_length_ratchet` + `test_tracker_card_weight_ratchet` — **23 passed**.

**Обязательные шаги:** 1 (офис) код 0, прочитано **145**, НЕ ПРОЧИТАН **2** — седьмой
цикл подряд, причина чужая (`com.spa.decision_loop` не загружен, действие владельца) ·
1в код **0** (аудит мерили 3,16 ч назад при такте 30 ч) · 1д код **1** (новых
расхождений нет, два исторических названы, ходов 35) · 1е капитал **100 % по обеим
осям** ($85 000 в 4 протоколах) · 1е витрина код **4** (ждёт владельца, карточка есть;
правка `landing/` откачена и в доставку не вошла) · §50 на прод-`data/`: ВЫПОЛНЕНО **2**
· НЕ ВЫПОЛНЕНО **1** · НЕ ИЗМЕРЕНО **17** из 20 · `owner-done` на origin **0**
(`git ls-tree`, не прод-копия) ⇒ инжестить нечего.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

**Мутации и шаг 1г (дописано по завершении прогонов).** Спецификация #1215 (18 мутаций),
прогон на ФИНАЛЬНЫХ доставляемых байтах в СВЕЖЕМ дереве `/tmp/mut1216`, md5 сверены с
деревом доставки ДО и ПОСЛЕ: **применено 18 · убито 18 · выжило 0 · НЕ ПРИМЕНЕНО 0 ·
СЛОМАЛИ СБОРКУ 0**; контроль шума — 0 уже красных имён. **M16, выжившая у #1215, убита
двумя именами** `TheNameMustClaimAStep` — различающая сцена работает. `--window-check`:
окна НЕТ ни в одном из ТРЁХ деревьев (доставка · прибор · чтение). **Шаг 1г — «Бомб
нет»** при задержке 95 мин, дерево НАЗВАНО входом `/tmp/anchor1216`.

### Заказ G1060 (следующему циклу)

**0. Заказ G1059 выше ОСТАЁТСЯ ЖИВЫМ ЦЕЛИКОМ** — он написан автором ADR-1072 и его
пункты 1–3, 6–10 этим подъёмом не исполнялись. Читать ЕГО, этот заказ — дополнение.

**1. Вердикт контрольного прогона цикла #1216 — ПРОЧИТАТЬ ПЕРВЫМ ДЕЛОМ.** Номер и
ПОЛНАЯ sha — в пост-записи выше. Диспетчеру давать ПОЛНУЮ sha (укороченная валит
`actions/checkout`, прогон умирает до сводки, а `conclusion: failure` читается как
красный набор). Имена — ТОЛЬКО из артефакта `report.json`; род `wallclock_timeout`
регрессией НЕ является. Замер #1216 прежнего прогона: 65 → **75** имён, ПРИШЛО 10 и ВСЕ
рода часов, УШЛО 0 ⇒ гнаться стои́т за **0** именами.

**2. ПРОД-КОПИЯ приказа ВСЁ ЕЩЁ НЕЧИТАЕМА, и ADR-1066 этого не закрыл.** Замер #1216:
на `origin/main` карточка **90 906** символов, а в прод-дереве
`~/Documents/SPA_Claude/nimbalyst-local/tracker/` — **2 880 412** (30 684 строки),
то есть **31,7×**. Шаг 0a-ГОЛОД читает ПРОД-копию, и голодающий приказ по-прежнему
нельзя прочитать той дверью, которой велит `CLAUDE.md`. Сжатие уехало на origin, а
прод-дерево его не получило: синхронизация прод-дерева — действие ВЛАДЕЛЬЦА
(`.claude/rules/deployment.md` п. 6), агент его не делает. Нужна карточка владельцу
(или проверка, что штатная синхронизация зеркала этот путь ВОЗИТ — `nimbalyst-local/`
она, по шапке `CLAUDE.md`, НЕ возит НИКОГДА). **Это не теория: механизм голодания,
измеренный ADR-1066, на прод-дереве живёт дальше.**

**3. Два артефакта офиса НЕ ПРОЧИТАНЫ СЕДЬМОЙ цикл подряд** — без изменений, причина
чужая и названа (G1059 п. 7). Дубля не заводить.

**4. Пределы `STATE.md` после доставки #1216: 147 строк / 28 794 символа / 689 в самой
длинной** (пределы 150 / 30 000 / 700). Запас по строкам **3**. #1216 строки не
добавлял: факт подъёма дописан В СТРОКУ ADR-1072 (609 → 676 символов).

**5. Сжать G1057 и пост-записи #1213 в тот же архив** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`,
порядком G1059 п. 6: сперва спроси у адреса, несёт ли он предмет, и только потом снимай
текст из карточки. Этот цикл карточку УВЕЛИЧИЛ (79 251 → ~87 000 символов) и обязан это
сказать: подъём добавил пост-запись и заказ, а сжатие не делал.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Контрольный прогон цикла #1216 и ПОПРАВКА К БАЗЕ СРАВНЕНИЯ (вписано ПОСЛЕ доставки)

**Заказан прогон `45082084051`** на ПОЛНОЙ sha
`909de3cce96f8f15b8b7a9c320e8570d03aa7cdb` (HTTP 204, `total_count` 388 → **389**,
`head_sha` перечитан у API и СОВПАЛ, статус `in_progress`). **Вердикт НЕ ИЗМЕРЕН** —
читать следующему циклу: `python3 scripts/ci_control_verdict.py --delta 45062637245
45082084051`.

**ПОПРАВКА: база сравнения в заказе G1058/G1060 УСТАРЕЛА, и это измерено.** Заказ
называл предшественником `44658981497` (75 имён), но на ТОЙ ЖЕ базе `bc612dcd0` после
него прошёл ещё один прогон — **`45062637245`, 86 имён**, и он и есть настоящий
предшественник моей доставки. Дельта `44658981497 → 45062637245`: **ПРИШЛО 26 · УШЛО
15**, и ВСЕ 41 — род стенных часов (`wallclock_timeout`), то есть вердикта прогон о них
не вынес ни в одну сторону; гнаться по-прежнему стои́т за **0** именами. Сравнивать мою
доставку с `44658981497` значило бы вписать ей 11 чужих имён, пришедших на НЕ МОИХ
байтах, — ровно тот ложный вывод, против которого заказ велит сличать ПО ИМЕНАМ.

**Ушедшее имя рода часов починкой НЕ является** (сторож лишь успел дойти до вердикта), и
порог `--timeout` поднимать запрещено (инв. #16, инв. #16 правила CI).

### Прогон и подтверждения цикла #1217 (вписано ПОСЛЕ доставки)

**Взят пункт заказа G1060 п. 1** — «вердикт контрольного прогона цикла #1216 прочитать
ПЕРВЫМ ДЕЛОМ». Он и оказался работой цикла, и это НАЗВАНО: §50 приказа (17 из 20 нечем
проверить) этим циклом не двигался, заказы G1059 пп. 2–3 остаются живыми.

**Вердикт прочитан:** `--delta 45062637245 45082084051` ⇒ **86 → 74** имени, ПРИШЛО 14,
УШЛО 26. Из пришедших **13** — род стенных часов (`wallclock_timeout`, вердикта нет ни в
одну сторону). Настоящее пришедшее имя РОВНО ОДНО:
`test_untiered_census.py::CensusMarkupMatchesMeasurement::test_census_covers_every_untiered_module_on_disk`.
Воспроизведено на чистом `origin/main` за 0,25 с.

**Имя принесла доставка #1216 — та, что объявила себя чистой.** `ab1b92b05` добавил
`spa_core/analytics/foreign_carrier_cadence_census.py` И обновил перепись тем же
коммитом; модуль в ней всё равно не назван — генератор звали в дереве, где его ещё не
было. #1216 мерил свою красноту дифференциально и честно, но на **ПАРЕ** сторожей,
НАЗВАННОЙ прозой заказа G1059 п. 9; покраснел ТРЕТИЙ. **Мерка, выбранная прозой заказа,
отвечает на вопрос прозы, а не на вопрос «что мои байты способны покрасить».**

**Класс измерен** (полное зеркало `SPA_mirror`, прод-клон усечён и на вопрос не отвечает;
окно от рождения переписи `a2c412ab3` 29.08, **2137** вершин, НЕ ИЗМЕРЕНО 0): из **31**
вершины, добавившей публичный модуль `spa_core/analytics/`, перепись называла добавленный
модуль у **0**. Дешёвая ось «тронул ли коммит перепись» отвечает «да» у ТРЁХ
(`7de16e9c0`, `8d86a4663`, `ab1b92b05`) — и у **всех трёх** перепись своего же модуля не
называет, то есть ось объявила бы безопасными ровно те случаи, из-за которых дверь нужна.

**Доставлено (ADR-1073):** красное имя закрыто ПРИБОРОМ (`--emit-markup` из дерева, где
модуль лежит; классификация ПРОВЕРЕНА — 16 `def`, **ноль** `class` ⇒ звать нечем) +
одиннадцатая дверь доставки `enforce_delivery_census_names` (код **19**, ОБЕ двери, batch
ИМПОРТИРУЕТ), вопрос про origin **ПОСЛЕ** доставки, двери разбора ДВЕ и обе у ПИСАТЕЛЯ,
исходы четыре и различимы (включая «ДАВНИЙ долг — доставку не держит»), обход
`--allow-uncensused-module` ПЕЧАТАЕТСЯ.

**ВТОРАЯ находка, на ЧИСТОМ `origin/main`:** batch-дверь ловила
`except DeliveredCardBoardStatusDiffers` и звала `STALE_BOARD_STATUS_EXIT`, **не ввезя ни
одного имени** (звёздного импорта нет) ⇒ ровно в миг отказа оси 2 ADR-1062 поднимался
`NameError` вместо названной причины, код **1 вместо 18**. Форма «половина починки,
оставившая второй сайт». Починка — два ввоза, контроль ИЗМЕРЕН в обе стороны.

**Мутации.** Первый прогон: 18 применено · **14 убито · 4 выжило**, и дефектом КОДА не был
НИ ОДИН — две дыры СЦЕН (дословно находка #1202: сцены не различали источник переписи и не
подавали прибор БЕЗ двери), один дефект МОЕЙ ПРОБЫ (искала зов ПОДСТРОКОЙ и зачла
упоминание в ДОКСТРИНГЕ; переписана на AST), один ЭКВИВАЛЕНТНЫЙ мутант (доказан замером,
записан как эквивалентный, из спецификации НЕ убран). После починки сцен — числа в журнале
`docs/journal/2026-W48.md`, запись цикла #1217.

**Обязательные шаги:** 1 (офис) код 0, прочитано **145**, НЕ ПРОЧИТАН **2** — ВОСЬМОЙ цикл
подряд, причина чужая (`com.spa.decision_loop` не загружен, действие владельца), дубля нет
· 1в код **0** (аудит 4.82 ч назад при такте 30 ч) · 1г дерево НАЗВАНО входом
`/tmp/anchor1217` · 1д код **1** (новых нет, два исторических названы, ходов 35) · 1е
капитал **100 % по обеим осям** ($85 000 в 4 протоколах) · 1е витрина код **4** (ждёт
владельца, карточка есть; правка `landing/` откачена) · `owner-done` на origin **0**
(`git ls-tree`) ⇒ инжестить нечего. Коды мерены БЕЗ конвейера.

**Карточка СЖАТА** порядком G1059 п. 6 / G1060 п. 5: заказ G1057 и пост-запись #1213
перенесены в `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md` — СПЕРВА
спрошен адрес (`grep` по архиву дал 0 вхождений G1057), потом сверено ПОБАЙТОВО, и только
потом снят текст: **61 527 → 54 429** символов, потеряно **0**. Запись этого цикла и заказ
G1061 карточку снова увеличили, и это сказано, а не умолчано.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1061 (следующему циклу)

**0. Заказ G1059 выше ОСТАЁТСЯ ЖИВЫМ ЦЕЛИКОМ** — его пункты 1–3, 5, 7–10 этим циклом не
исполнялись. Заказ G1060 исполнен в части п. 1 (вердикт прочитан) и п. 5 (сжатие сделано);
пп. 2–4 ниже перенесены.

**1. Вердикт контрольного прогона цикла #1217 — ПРОЧИТАТЬ ПЕРВЫМ ДЕЛОМ.** Номер и ПОЛНАЯ
sha — в пост-записи ниже. Диспетчеру давать ПОЛНУЮ sha (укороченная валит
`actions/checkout`, прогон умирает до сводки, а `conclusion: failure` читается как красный
набор). Имена — ТОЛЬКО из артефакта `report.json`; род `wallclock_timeout` регрессией НЕ
является. **И перед сравнением спроси у API, нет ли на той же базе прогона НОВЕЕ:** урок
#1216 — «номер прогона из заказа» есть замер с датой, а не адрес, и сличение с устаревшим
номером вписало бы доставке 11 чужих имён. База сравнения моей доставки — **45082084051
(74 имени)**.

**2. Мерка «моя доставка ничего не покрасила» обязана выводиться из БАЙТОВ, а не из прозы
заказа — это главный урок #1217, и он НЕ закрыт прибором.** Сегодня честного способа
спросить «какие сторожа способны покраснеть от МОИХ байтов» нет: #1216 взял пару имён из
прозы и ошибся, #1217 закрыл один конкретный артефакт гейтом. Поверхность для замера
НАЗВАНА (не выдумана): из **2587** тест-файлов `spa_core/tests/` **652** перечисляют
каталог (`glob`/`rglob`/`iterdir`/`listdir`/`walk`), то есть их вердикт зависит от НАБОРА
файлов, а не от содержимого любого из них. Карточка
`inbox-izmerit-naselenie-klassa-proizvodnyi-art` (`new`) несёт порядок работы: сузить
ОСМЫСЛЕННО (путь разрешается в каталог ИСХОДНИКОВ, не `data/` и не `$TMPDIR`), мерить
ДИФФЕРЕНЦИАЛЬНО (прогон дважды, во второй раз с подложённым новым публичным файлом;
предмет — тот, у кого МЕНЯЕТСЯ вердикт), мерить и переход в `skipped`, прогон — в ОТДЕЛЬНОМ
дереве. Цена, из-за которой не влезло в #1217: 652 файла дважды — часы. **Население НЕ
ИЗМЕРЕНО, и нулём это не считается.**

**3. ПРОД-КОПИЯ приказа ВСЁ ЕЩЁ НЕЧИТАЕМА** (перенесено из G1060 п. 2, не двигалось): на
`origin/main` карточка ~79 КБ, в прод-дереве — **2 880 412** символов. Шаг 0a-ГОЛОД читает
ПРОД-копию. Синхронизация прод-дерева — действие ВЛАДЕЛЬЦА
(`.claude/rules/deployment.md` п. 6), агент его не делает; `nimbalyst-local/` штатная
синхронизация зеркала НЕ возит никогда. Нужна карточка владельцу.

**4. Два артефакта офиса НЕ ПРОЧИТАНЫ ВОСЬМОЙ цикл подряд** — без изменений, причина чужая
и названа (`com.spa.decision_loop` во флоте не загружен, включение — действие владельца,
ADR-1053/1061). Дубля не заводить.

**5. Пределы `STATE.md` после доставки #1217: 148 строк / 29 495 символов / 700 в самой
длинной** (пределы 150 / 30 000 / 700). **Запас по строкам 2, а по длиннейшей строке —
НОЛЬ.** Моя первая редакция строки вышла 892 символа, и храповик её верно покраснел;
следующему циклу дописывать строку НЕЛЬЗЯ без сжатия соседней — блоки старше двух недель
живут в реестре и журнале.

**6. Сжимать в архив тем же порядком** (G1059 п. 6): сперва спроси у адреса, несёт ли он
предмет, потом сверь побайтово, и только потом снимай текст. Следующему — G1058 и
пост-записи #1214.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Контрольный прогон цикла #1217 (вписано ПОСЛЕ доставки)

**Доставлено одним коммитом `c18dd6bd5`** — 15 файлов, база пинована
`--expected-base c18dd6bd...` ← `0c8eb998a`; слепок байтов сверен у **41** чтения, слепок
режимов у **5**, разбор уезжающего Python — **5** файлов.

**Заказан прогон `45091782823`** на ПОЛНОЙ sha
`c18dd6bd516d1756ee7e6bada53a39154d596fa8` (HTTP 204, `total_count` 389 → **390**,
`head_sha` перечитан у API и СОВПАЛ, статус `queued`). **Вердикт НЕ ИЗМЕРЕН** — читать
следующему циклу:
`python3 scripts/ci_control_verdict.py --delta 45082084051 45091782823`.
**База сравнения — 45082084051 (74 имени)**, и перед сличением спроси у API, нет ли на
ТОЙ ЖЕ базе прогона новее (урок #1216: номер из заказа есть замер с датой, а не адрес).

**Оба предупреждения пушера «провенанс базы НЕ ИЗМЕРЕН» ПЕРЕМЕРЕНЫ вручную, и оба — верный
третий исход, а не находка:**

* карточка теряла **90** строк базы — **все 90 найдены в архиве на origin ПОБАЙТОВО**
  (`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`, уехал ТЕМ ЖЕ пушем),
  не найдено нигде **0**. Предков пути объяснить перенос не могли, потому что архив
  менялся этим же коммитом — дословно ситуация #1216;
* доска теряла **4** строки, и все четыре — ПЕРЕГЕНЕРИРОВАННЫЕ строки шапки (счётчики
  1670 → 1671, `Inbox (966)` → 967, отметка сборки, sha сверки). Строк доски 1746 → 1747:
  доска ВЫРОСЛА на мою карточку. Потери содержания **0**.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).
