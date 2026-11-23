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

### Заказ G1058 и пост-запись цикла #1214 — В АРХИВЕ

Сжато циклом #1218 порядком G1061 п. 6: СПЕРВА спрошен адрес (заголовка `### Заказ G1058`
в архиве не было — `grep` дал 0 при трёх упоминаниях в шапке), потом сверено ПОБАЙТОВО
(md5 блока `42ac10b8ae52aab2e46906054b97948b`, 105 строк / 6687 символов), и только потом
снят текст. Адрес — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`.
Живыми в карточке остаются два последних заказа.

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

### Прогон и подтверждения цикла #1216 — В АРХИВЕ

Побайтовая копия — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`
(md5 `f3bb587555be1b5299452780f2286802`, 63 строк / 3984 символов). Снял цикл #1222 порядком
G1064 п. 9: СПЕРВА спрошен адрес (заголовка в архиве не было — `grep` дал 0 при одном
соседнем «Контрольный прогон цикла #1216»), потом сверено ПОБАЙТОВО, и только потом
снят текст. **Заказ G1059 НЕ ТРОНУТ — он ЖИВОЙ** (G1064 п. 0).

### Заказы G1060, G1061 и контрольные прогоны #1216–#1217 — В АРХИВЕ

Оба заказа ИСПОЛНЕНЫ; полный текст (и обе пост-записи о доставке) —
`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`, раздел
«Заказы G1060, G1061 и контрольные прогоны циклов #1216–#1217». Перенос
сверен побайтово; снято 310 строк, md5 блока `cc2dcf824dc38c6765437dad2b19ddc3`.

### Заказ G1062 и контрольный прогон цикла #1218 — В АРХИВЕ

Побайтовая копия (**91** строка / **5955** символов, md5 блока
`6518977991053abfce4a76a66d08f8fa`) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`.
Снял цикл #1223 порядком G1059 п. 6: СПЕРВА спрошен адрес (заголовка `### Заказ G1062` в архиве
не было — `grep` дал 0 при двух упоминаниях номера в прозе), потом сверено ПОБАЙТОВО, и только
потом снят текст. Последний живой пункт G1062 (п. 7 — мутационный прогон прибора ADR-1074)
ЗАКРЫТ тем же циклом #1223 (ADR-1078). Живыми в карточке остаются два последних заказа.

### Заказ G1063 и прогон цикла #1220 — В АРХИВЕ

Побайтовая копия (**149** строк / **10 299** символов, md5 блока
`0cdfa53856057a4bd308bdbd3c96a9c3`) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`.
Снял цикл #1226 порядком G1059 п. 6: СПЕРВА спрошен адрес (заголовка `### Заказ G1063`
в архиве не было — `grep` дал 0, упоминаний `#1220` тоже 0), потом сверено ПОБАЙТОВО, и
только потом снят текст. **Заказ G1059 НЕ ТРОНУТ — он ЖИВОЙ** (его пп. 1–3, 5, 7–10 не
исполнял никто из #1218…#1225).

### Заказ G1064 (следующему циклу)

**0. Заказ G1059 ОСТАЁТСЯ ЖИВЫМ ЦЕЛИКОМ** (его пп. 1–3, 5, 7–10 не исполнял никто из
#1218…#1220). **Заказ G1063 исполнен в пп. 1 (насколько он исполним), 3 — ЗАМЕРОМ, 4, 5, 6,
7**; его **п. 2 НЕ ИСПОЛНЕН** и перенесён ниже. G1060, G1061, G1062 исполнены.

**1. Вердикт контрольного прогона цикла #1220 — ПРОЧИТАТЬ ПЕРВЫМ ДЕЛОМ.** Номер и ПОЛНАЯ
sha — в пост-записи ниже. ПОЛНАЯ sha идёт во **ВХОД** `inputs.sha`, а в `ref` — ветка (в
`ref` полная sha даёт HTTP 422 и прогон не стартует ВОВСЕ). Имена — ТОЛЬКО из артефакта
`report.json`; род `wallclock_timeout` регрессией НЕ является. Перед сравнением спроси у API,
нет ли на той же базе прогона НОВЕЕ. **База сравнения — `45108124169` (67 имён)**, и из
них ТРИ были «пришедшими» у #1218: одно (`test_hermetic_launchd_door`) закрыто ЭТОЙ
доставкой, два (`test_tb_sanitizer_probe`) — нет, см. п. 3.

**2. ПЕРЕНЕСЁН из G1063 п. 2 (не трогался): у дельты красного набора есть НЕПРОВЕДЁННАЯ
ОСЬ — ШАРД.** Замер #1219 сделан РУКАМИ по артефактам `ctl-manifest`; в
`scripts/ci_control_verdict.py --delta` ось не проведена. Требования названы там же:
«переехал» обязан быть ТРЕТЬИМ исходом (`unmeasured`), а не «не регрессия» — иначе ось врёт
в сторону «чисто» (`test_script_path_launch_imports` переехал И починился содержанием);
артефакта нет или истёк ⇒ третий исход с названной причиной; контроль в обе стороны.

**3. Два имени `test_tb_sanitizer_probe.py` — НЕИЗМЕРЕННАЯ ось сузилась до ОДНОЙ, и это
ИЗМЕРЕНО #1220.** В карточке `inbox-proba-sanitara-trassy-na-ci-otvechaet-ko` (status `new`,
пробы нет — объяви ДО работы) дописан замер: на Маке ребёнок загружает плагин ИЗ ДЕРЕВА
СЦЕНЫ, `looked.json` = `{plain: false, method: false}`, проба отвечает `unmeasured` ⇒ догадка
«ребёнок взял не тот плагин» на Маке ОПРОВЕРГНУТА; родитель в форме CI (ключи шарда,
`--timeout=180 --timeout-method=signal`, `SPA_PYTEST_STREAM`/`SPA_PYTEST_MANIFEST`) даёт
5 passed ⇒ «виноваты флаги» тоже опровергнуто. **Осталась ОДНА ось: ОС и версия Python**
(CI `ubuntu-latest` / 3.11 против Мака 3.13). Следующий шаг назван в карточке: запись сцены
обязана НЕСТИ путь загруженного плагина и `sys.path` ребёнка, чтобы вердикт на CI НАЗЫВАЛ
файл, а не оставлял догадку. Пока этого нет, зарегистрированная проба
`tb_sanitizer_sees_the_report_excinfo` на CI слепа — это опаснее красного теста.

**4. Мерку «что МОИ байты способны покрасить» выводи из БАЙТОВ, И ОБЪЯВЛЯЙ ОХВАТ ВСЛУХ.**
Замер #1220: тот же прибор на том же дереве даёт **65** сторожей при 5 объявленных каталогах
и **77** при 11 — и во втором случае красных 4, а не 1. Все четыре красны на ЧИСТОМ
`0b4c3d35c` ДО ИМЕНИ. **Число в этой мерке есть ответ о НАЗВАННОМ ОХВАТЕ, а не о дереве**;
охват объявляй строкой, иначе «у меня 1 красный» и «у меня 4» — об одном и том же дереве.

**5. Четыре сторожа карточки `inbox-chetyre-storozha-krasny-na-chistom-origi` красны на
`main`, и теперь это подтверждено на ДВУХ базах** (`2fc564a0e` — #1218, `0b4c3d35c` — #1220,
имена совпали ДО ИМЕНИ) ⇒ доставки их не двигали. Чинить У ПИСАТЕЛЯ, по одному, с пробой до
работы; дописывать в базы ЗАПРЕЩЕНО (инв. #16).

**6. Класс «подмена, пережившая сцену» ШИРЕ двери launchd, и за её пределами НЕ ИЗМЕРЕН.**
Перепись `_hermetic_launchd.direct_door_assignments` спрашивает атрибуты ЭТОГО перечня и
видит ОДИН хоп. Соседний член класса НАЗВАН замером #1220 и НЕ чинился: при сборе обоих
корней прогон печатает `network guard was RE-INSTALLED mid-run · missing[urlopen]` — та же
форма (присваивание вместо обёртки), другая дверь; он уже починен ГРОМКО в
`spa_core/tests/conftest.py`. Население класса за пределами двух дверей — НЕ ИЗМЕРЕНО, и
нулём это не считается.

**7. Два артефакта офиса НЕ ПРОЧИТАНЫ ОДИННАДЦАТЫЙ цикл подряд** — без изменений, причина
чужая и названа (`com.spa.decision_loop` во флоте не загружен, включение — действие
владельца, ADR-1053/1061). Дубля не заводить.

**8. Пределы `STATE.md` после доставки #1220 — в пост-записи ниже.** #1220 строки не
добавлял: факт подъёма и две поправки вписаны В СТРОКУ ADR-1075, а сама строка СЖАТА
(858 → 601 символа), потому что по длиннейшей строке запас был НОЛЬ.

**9. Сжимать в архив тем же порядком** (G1059 п. 6): сперва спроси у адреса, несёт ли он
предмет, потом сверь ПОБАЙТОВО, и только потом снимай текст. Следующему — G1059 и
пост-запись #1216, но **G1059 ЖИВОЙ**, поэтому снимать его текст нельзя, пока его пункты не
исполнены: переносить в архив **только пост-запись #1216**.

**10. Прод-копия приказа всё ещё нечитаема** (не двигалось): на `origin/main` карточка ~60 КБ,
в прод-дереве — 30 684 строки. Шаг 0a-ГОЛОД читает ПРОД-копию. Карточка владельцу есть
(`owner-decision-rabochaya-kopiya-prikaza-portfolio-cio-n`), дубля не заводить;
синхронизация прод-дерева — действие ВЛАДЕЛЬЦА.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Контрольный прогон цикла #1220 (вписано ПОСЛЕ доставки)

**Доставлено одним коммитом `0e6db0e9b4cbffa674f94cd806fe35895f842f51`** — 16 файлов, база
пинована `--expected-base b4014e258b491fb3cda7c2e7003b72e32bb9829a`; слепок байтов сверен у
**44** чтений, слепок режимов у **5**, разбор уезжающего Python — **5** файлов.

**Заказан прогон `45131349632`** (`SPA CI control`, run_number 391 → **392**, `total_count`
391 → 392) на ПОЛНОЙ sha `0e6db0e9b4cbffa674f94cd806fe35895f842f51`, поданной во **ВХОД**
`inputs.sha` при `ref: main` — HTTP **204**, `head_sha` перечитан у API и СОВПАЛ, статус
`in_progress`. **Вердикт НЕ ИЗМЕРЕН** — читать следующему циклу:
`python3 scripts/ci_control_verdict.py --delta 45108124169 45131349632`.
**База сравнения — `45108124169` (67 имён)**, и перед сличением спроси у API, нет ли на ТОЙ
ЖЕ базе прогона новее.

⚠️ **ДВЕ ловушки доставки, измеренные этим циклом (обе стоили прогона пушера):**

1. **`zsh` не расщепляет переменную со списком файлов.** `--files $FILES` ушло в пушер ОДНИМ
   аргументом длиной 1,7 КБ, и он умер на `OSError: [Errno 63] File name too long` — внутри
   гейта инструмента доставки, то есть ДО любого пуша. Верно — `${=FILES}`. Урок уже был
   записан памятью (`zsh-variable-list-not-split-in-for-loops`) и всё равно повторён.
2. **ПОЛУФАБРИКАТ В ИНДЕКСЕ мёртвой сессии читается пушером как БАЗА.** У трёх файлов
   наследства `git status` показывал `MM` (правка и в индексе, и в рабочем дереве), и страж
   перезаписи называл их **`diverged`**: «база 6564ad46 → remote af20206f», хотя байты
   рабочего дерева от remote-версии происходили честно. `git restore --staged` этого НЕ
   вылечил (байты не дрогнули, `md5` сверен до и после — совпал), то есть база берётся НЕ из
   индекса, а из записи провенанса дерева. Лечение — **СВЕЖИЙ worktree на `origin/main` плюс
   копирование 16 файлов**: оттуда пуш прошёл с первого раза. Это тот же класс, что память
   `second-push-into-the-same-tree-is-always-diverged`, но пришедший с другой стороны: не от
   своего прошлого пуша, а от НЕДОПИСАННОГО индекса предшественника.

**ОБА предупреждения пушера «провенанс базы НЕ ИЗМЕРЕН» перемерены вручную, и оба — верный
третий исход, а не находка:**

* `spa_core/tests/test_hermetic_launchd_door.py` теряло **6** строк: три бывших имени
  `_WIRED` без каталога (`test_self_heal.py` и соседи), комментарий о перечне и
  `source = (_TESTS / name).read_text(…)`. Это РОВНО переход перечня на репо-относительные
  пути — та самая починка №3 решения, без которой четвёртый сайт был перечню недоступен;
* `tests/test_kill_switch_eval_path.py` теряло **5** строк: комментарий «Avoid the launchctl
  kickstart side-effect» и ЧЕТЫРЕ строки
  `self._tr._kickstart_cycle = lambda: None` — дословный ПРЕДМЕТ ADR-1075.

**Карточка приказа теряла 308 строк, и все 308 найдены** (архив `CARD-archive-portfolio-cio-orders-2026-11-22.md`
уехал ТЕМ ЖЕ пушем; сверка построчная, не найдено нигде **0**) — это перенос G1060/G1061 и
двух пост-записей, сделанный #1219. Доска теряла **4** строки перегенерированной шапки при
росте карточек 1673 → **1675** (две мои) и нуле потерь содержания. `STATE.md` теряла **2**
строки: сжатые #1219 строки ADR-1064/1065 (полный текст — в их файлах решений) и моя
переписанная строка ADR-1075 (858 → 601 символа, запас по длиннейшей строке был НОЛЬ).

**Пределы `STATE.md` после доставки #1220: 150 строк / 29 674 символа / 700 в самой длинной**
(пределы 150 / 30 000 / 700). Запас — **0 строк, 326 символов, 0 по длиннейшей строке.**

**Чего этот цикл НЕ сделал и это НАЗВАНО:** мутационный прогон прибора ADR-1074
(`derived_artifact_census.py`) — долг заказа G1062 п. 7 — так и НЕ ЗАПУСКАЛСЯ; мутации этого
цикла прогнаны на СВОЕЙ работе (ADR-1075), и это другой предмет. Ось «шард» в читателе дельты
НЕ ПРОВЕДЕНА (заказ G1064 п. 2). Карточка `inbox-proba-sanitara-trassy-na-ci-otvechaet-ko` в
работу НЕ бралась — у неё нет объявленной пробы.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

---

## Цикл #1221 (2026-11-23, ADR-1076) — §50: критерий «Есть owner pause/kill switch» получил мерку

**Шаг 0a-ГОЛОД отдал такт этой карточке** (`in-progress` 2240,5 ч, держателя нет, мимо 494 цикла).

**Находка.** Сводка §50 (ADR-1070) ДО работы: ВЫПОЛНЕНО 2 · НЕ ВЫПОЛНЕНО 1 · НЕ ИЗМЕРЕНО **17**
(мерки нет 14). Среди четырнадцати «мерки нет» стоял критерий, который **мерить было ЧЕМ уже
11 дней**: прибор §42 `spa_core/monitoring/cio_kill_switch_controls.py` спрашивает ровно его и
ровно словами владельца, а с 12.11 докладывает `CRITICAL`. То есть ответ существовал, а вторая
приёмка его не читала — и «не измерено» было ложным в сторону «ещё не дошли».

**Сделано.** Проба `owner_has_the_three_stop_organs` объявила себя мерой критерия (строка
ДОСЛОВНАЯ; паритет с этой карточкой проверяется дверью `cio_dod_rollup.parse_s50_criteria`,
расхождение на байт = сирота и находка). Своего разбора ни строки — дверь ОДНА, `write=False`.

| орган §42 | обещано | ИЗМЕРЕНО | исход |
|---|---|---|---|
| PAUSE CIO | `HOLD_ONLY` | `ALL_CASH` | **CONFLATED** — `/pause` носит имя паузы, а опустошает книгу |
| PAUSE AUTO EXECUTION | `HOLD_ONLY` | — | **ABSENT** |
| EMERGENCY STOP | `ALL_CASH` | `ALL_CASH` | PRESENT |

Разделимость **SEPARABLE** — остановка не гасит наблюдение и отчёт (вторая половина §42 цела).

**§50 после:** ВЫПОЛНЕНО 2 · **НЕ ВЫПОЛНЕНО 2** · НЕ ИЗМЕРЕНО 16 (мерки нет **13**).

**Приёмка:** батарея `test_cio_kill_switch_controls.py` **46 → 67** тестов, `67 passed`;
мутации **14 применено / 14 убито / 0 выжило** в ОТДЕЛЬНОМ дереве, окна после прогона нет,
байты сверены `md5`.

**Органа у владельца НЕ появилось.** Проба ИЗМЕРЯЕТ: дать ручку, меняющую движение денег, —
money-path и решение владельца. `CONFLATED` у `/pause` снимет настоящая пауза, а не подпись кнопки.

**Названный долг:** 13 критериев §50 без мерки · сводка §50 не передаёт пробам `repo_root`
(печатает честно) · долги #1220 (мутации прибора ADR-1074, ось шарда в читателе дельты) НЕ закрыты.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

**Пост-запись #1221:** доставлено `825c6eca2` (8 файлов, один коммит), контрольный прогон
`45146707951` заказан на полной sha во входе `inputs.sha` (HTTP 204, `total_count` 393 → 394,
`head_sha` совпал), **вердикт НЕ ИЗМЕРЕН**; база сравнения `45133715376`. Сторожа, которых
задевают байты доставки: **66** файлов — `1571 passed, 1 skipped, 500 subtests`, `EXIT=0`,
прогон в ОТДЕЛЬНОМ дереве. Предупреждение пушера о провенансе `STATE.md` (−1 строка)
перемерено: верный третий исход, сжатие строки ADR-1070 в сводную; потерян один факт
(«население 20, а не 21 и не 25»), он жив в ADR-1070.

---

## Цикл #1222 (2026-11-23, ADR-1077) — ось ПЕРЕЕЗДА в дельте красного набора проведена

**Шаг 0a-ГОЛОД отдал такт этой карточке** (`in-progress` 2242,5 ч, держателя нет, мимо прошло
495 циклов). Из живого заказа G1064 взят **п. 2** — дважды перенесённый (G1063 п. 2 → G1064
п. 2) и не тронутый циклами #1218…#1221.

**П. 1 заказа исполнен первым делом.** Вердикт контрольного прогона #1221 — `45146707951`
(на `825c6eca273a`); прогона НОВЕЕ на той же базе у API нет. Дельта против `45133715376`:
**92 → 58** имён, **ПРИШЛО 0**, ушло 34, и все 34 — род `wallclock_timeout`. **Доставка #1221
чиста, гнаться не за чем.**

**Находка.** Дельта отвечала «какие имена ПРИШЛИ» и выдавала ответ списком того, за чем
стои́т гнаться. Контрольный прогон идёт по 12 шардам, состав шарда пересчитывается КАЖДЫЙ
раз — имя могло «прийти» не оттого, что его сломали, а оттого, что файл уехал к другим
соседям. Замер прибором на той же паре, что мерил #1219 (`45091782823` → `45108124169`,
между ними #1218 добавил один тест-файл):

| ось | ответ |
|---|---|
| файлов в населении | 3011 → **3012** |
| **ПЕРЕЕХАЛО файлов** | **1570 из 3011** — больше половины от ОДНОГО добавленного файла |
| пришедших имён рода ДЕФЕКТА | 3, и **ПЕРЕЕХАЛИ 3 из 3** (8→11 · 11→6 · 11→6) |
| ушедших имён | 11, ПЕРЕЕХАЛО **10**, в т. ч. `test_script_path_launch_imports` 1→11 |

Номера совпали с таблицей замера #1219 ДО ЦИФРЫ — сверка с независимой записью правила, а не
с самим собой. Прежняя редакция печатала здесь «гнаться стои́т за 3 именами» и давала код 1.
**Контрольная пара того же дня** (`45133715376` → `45146707951`): **0 переездов** — ось
РАЗЛИЧАЕТ, обе стороны различия наблюдены в один день.

**Сделано.** Исходов у перехода **четыре** (перечень ЗАКРЫТ), измерен РОВНО один:
`shard_same` · `shard_moved` · `shard_absent` · `shard_unmeasured` с названной причиной.
«Гнаться» сузилось до измеренного (`Delta.chase`), третий исход назван отдельно
(`shard_blind_arrivals`); прежнее `defect_arrivals` оставлено КАК БЫЛО. **Код «переехал» —
2**, не 0 («чисто» — прямой запрет заказа) и не 1 (фантом). Немочь плана `ctl-manifest`
(срок **30 дней против 90** у отчёта) дельту по родам НЕ рушит. Разбор плана — ЕДИНСТВЕННАЯ
дверь `shard_map_of`; имя артефакта и срок сверяются С ВОРКФЛОУ.

**Приёмка:** `168 passed, 46 subtests` (батареи **28 → 51** и **99 → 117**); живой вход —
фикстура дистиллята ЖИВЫХ артефактов той пары; достижимость ВСЕХ четырёх исходов проверяется
кодом; мутации — `docs/mutations/SHARD-1077-2026-11-23.json`.

**Своя ошибка записана, а не замазана:** мерку «второй разбор плана у прибора» я дважды
написал так, что она краснела на ВЕРНОМ состоянии (сперва подстрокой `doc.get("shards")`,
потом по одному ключу `files`) — оба читаются в приборе законно. Дискриминатор — ФУНКЦИЯ,
читающая ОБА ключа записи шарда; мерится AST, обратный контроль прилагается.

**Такт продолжен ДРУГОЙ сессией, и работа поднята ОСИРОТЕВШЕЙ.** Записи выше писала сессия
`cycle-20957` (объявление 10:34Z); она умерла, не доставив ничего (последний след в дереве
`c1222` — 10:42Z, в `c1222mut` — 11:11Z). Поднял такт `cycle-61765` порядком шага 0a: **отчёт
умершей сессии на веру НЕ принят** — переезд на живой паре, контрольная пара, вердикт #1221,
батареи, архив 61 снятой строки, inbox-население `origin` и пределы `STATE.md` перемерены
своими руками (таблица — в журнале `docs/journal/2026-W48.md`); из её чисел исправлено одно
(inbox на origin **959**, а не 970 — разбивка по статусам сходится в 959), мутационный прогон
спецификации проведён заново. **Ловушка опознания держателя:** ярлык `cycle-20957` — это pid
ОДНОРАЗОВОЙ CLI-команды журнала, а не сессии, поэтому `kill -0` о её живости не говорит
НИЧЕГО; живость измерена таблицей процессов (`claude -p` в системе РОВНО ОДИН) и отсутствием
окна мутационного прибора у всех пяти деревьев `c1222*`.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1065 (следующему циклу)

**0. Заказ G1059 ОСТАЁТСЯ ЖИВЫМ ЦЕЛИКОМ** (его пп. 1–3, 5, 7–10 не исполнял никто из
#1218…#1222). **Заказ G1064 исполнен в пп. 1, 2, 9**; его **пп. 3, 5, 6, 7, 10 НЕ ИСПОЛНЕНЫ**
и перенесены ниже без правок смысла. G1060…G1063 исполнены.

**1. Вердикт контрольного прогона цикла #1222 — ПРОЧИТАТЬ ПЕРВЫМ ДЕЛОМ.** Номер и ПОЛНАЯ sha —
в пост-записи ниже. ПОЛНАЯ sha идёт во **ВХОД** `inputs.sha`, а в `ref` — ветка (полная sha в
`ref` даёт HTTP 422 и прогон не стартует ВОВСЕ). Имена — ТОЛЬКО из артефакта `report.json`.
Перед сличением спроси у API, нет ли на той же базе прогона НОВЕЕ (урок #1216: номер из заказа
есть замер с датой, а не адрес). **Читать дельту теперь ОДНОЙ командой, и ось шарда она
спрашивает САМА** (ADR-1077): `python3 scripts/ci_control_verdict.py --delta <база> <новый>`.
Код **2** при непустом «ПРИШЛО» означает «переехало / ось слепа», а НЕ «ничего не найдено» —
читай строки, а не только код.

**2. ПЕРЕНЕСЁН из G1064 п. 3: два имени `test_tb_sanitizer_probe.py` — осталась ОДНА
неизмеренная ось.** Карточка `inbox-proba-sanitara-trassy-na-ci-otvechaet-ko` (`new`, пробы
нет — объяви ДО работы). На Маке догадка «ребёнок взял не тот плагин» ОПРОВЕРГНУТА, «виноваты
флаги» тоже. Осталась ось **ОС и версия Python** (CI `ubuntu-latest`/3.11 против Мака 3.13).
Следующий шаг назван в карточке: запись сцены обязана НЕСТИ путь загруженного плагина и
`sys.path` ребёнка. Пока этого нет, зарегистрированная проба `tb_sanitizer_sees_the_report_excinfo`
на CI слепа — это опаснее красного теста.
⚠️ **Добавлено #1222:** ОБА этих имени в паре `45091782823`→`45108124169` ПЕРЕЕХАЛИ (11 → 6),
поэтому «пришли они от доставки #1216» той дельтой НЕ ИЗМЕРЕНО. Вопрос о содержании задавать
прогоном на СВОЁМ дереве, а не дельтой.

**3. ПЕРЕНЕСЁН из G1064 п. 4 (мерка «что МОИ байты способны покрасить») — ОБЪЯВЛЯЙ ОХВАТ
ВСЛУХ.** Тот же прибор на том же дереве даёт **65** сторожей при 5 объявленных каталогах и
**77** при 11, и во втором случае красных 4, а не 1. Число есть ответ о НАЗВАННОМ ОХВАТЕ, а не
о дереве.

**4. ПЕРЕНЕСЁН из G1064 п. 5: четыре сторожа карточки
`inbox-chetyre-storozha-krasny-na-chistom-origi` красны на `main`** и подтверждены на ДВУХ
базах (`2fc564a0e`, `0b4c3d35c`, имена совпали ДО ИМЕНИ) ⇒ доставки их не двигали. Чинить У
ПИСАТЕЛЯ, по одному, с пробой до работы; дописывать в базы ЗАПРЕЩЕНО (инв. #16).
⚠️ **Добавлено #1222: ТРЕТЬЯ база, `f317721b3`.** Из 72 сторожей, которых задевают байты моей
доставки (охват объявлен: 10 каталогов набора), красны РОВНО ДВА — и оба из этой четвёрки
(`test_edge_boundary_dataflow_census` · `test_tier_curator`), имена совпали с чистым деревом
`origin/main` ДО ИМЕНИ при `4515 passed`. Двух других имён четвёрки моя поверхность не
задевает — это граница ОХВАТА, а не замер их зелени.

**5. ПЕРЕНЕСЁН из G1064 п. 6: класс «подмена, пережившая сцену» ШИРЕ двери launchd и за её
пределами НЕ ИЗМЕРЕН.** Соседний член НАЗВАН замером #1220 и не чинился: при сборе обоих
корней прогон печатает `network guard was RE-INSTALLED mid-run · missing[urlopen]` — та же
форма, другая дверь.

**6. ПЕРЕНЕСЁН из G1064 п. 7: два артефакта офиса НЕ ПРОЧИТАНЫ ДВЕНАДЦАТЫЙ цикл подряд.**
Без изменений, причина чужая и названа (`com.spa.decision_loop` во флоте не загружен,
включение — действие владельца, ADR-1053/1061). Дубля не заводить.

**7. ПЕРЕНЕСЁН из G1064 п. 10: прод-копия приказа всё ещё нечитаема.** На `origin/main`
карточка ~69 КБ, в прод-дереве — 30 684 строки. Шаг 0a-ГОЛОД читает ПРОД-копию. Карточка
владельцу есть (`owner-decision-rabochaya-kopiya-prikaza-portfolio-cio-n`), дубля не заводить;
синхронизация прод-дерева — действие ВЛАДЕЛЬЦА.

**8. ДОЛГ #1222, названный вслух: мутационный прогон прибора ADR-1074
(`derived_artifact_census.py`) так и НЕ ЗАПУСКАЛСЯ** — долг заказа G1062 п. 7, перенесённый
#1220 и не закрытый ни #1221, ни #1222 (мутации обоих циклов прогнаны на СВОЕЙ работе, а это
другой предмет).

**9. ОТКРЫТО ЗАМЕРОМ #1222: ось «тот ли ШАРД» закрыта, ось «те ли СОСЕДИ» — НЕТ.** Файл мог
остаться на шарде 7, а полюттер — приехать к нему; мерить это нечем, кроме состава шарда
целиком. Население класса «мера, не спросившая о перетасовке» за пределами ЭТОЙ дельты
НЕ ИЗМЕРЕНО, и нулём это не считается.

**10. Сжимать в архив тем же порядком** (G1059 п. 6): сперва спроси у адреса, несёт ли он
предмет, потом сверь ПОБАЙТОВО, и только потом снимай текст. #1222 так перенёс пост-запись
#1216 (md5 в заглушке). Следующему — **заказ G1062 и пост-запись #1218**; G1059 снимать
НЕЛЬЗЯ, пока его пункты не исполнены.

**11. ТРЕТЬЯ сессия такта перемерила ОБЕ записи предшественниц и нашла ТРИ поправки — все про
мерку, не про код** (подробно — `docs/journal/2026-W48.md`, раздел «Такт продолжен ТРЕТЬЕЙ
сессией»): (а) число мутаций в решении было вписано через **96 секунд** после спецификации, то
есть РАНЬШЕ, чем любой прогон мог его дать — поймано часами файлов, а не чтением прозы; прогон
проведён заново на финальных байтах в отдельном дереве, строка решения приведена к ИЗМЕРЕННОМУ;
(б) «959 против 970» — не ошибка числа, а два РАЗНЫХ вопроса: файлов `inbox-*` на origin 959, а
раздел доски насчитывает 970, потому что **11** карточек `agent-*` ОБЪЯВЛЯЮТ `type: inbox`
(поимённо в журнале); (в) строка офиса «критерий выполнен, а карточка открыта» склеивает ДВА
дерева — статусы из ПРОД-копии, числа критериев из дерева прогона, и названная ею карточка
`inbox-arb-razobrat-trevogu-telegram-posle-pere` на origin уже **`done`**.

**12. НОВАЯ карточка этого цикла:** `inbox-shag-ofis-0-sudit-statusy-kartochek-po-p` (`new`,
пробы нет — объявит та сессия, что возьмёт в работу). Предмет — п. 11(в): свести оба чтения к
ОДНОМУ дереву либо печатать третий исход «статусы из <A>, числа из <B>», и замерить население
строк раздела, стоящих сегодня на расхождении деревьев. Дубля не заводить.

**13. МЕЛКИЙ ДОЛГ, названный доставляющей сессией:** у `ShardMap` поле зовётся `run`, а несёт
`sha` манифеста (`shard_map_of`: `run = str(doc.get("sha"))`). Поле информационное — ни один
вердикт на нём не стои́т, в `--json` оно не печатается, — но имя отвечает не на свой вопрос, и
это ровно тот класс, которым живёт весь прибор. Переименовывать СЕЙЧАС нельзя: байты уже
прогнаны мутациями, смена байтов обесценила бы замер. Следующему циклу — одна правка имени плюс
прогон той же спецификации.

**Пределы `STATE.md` после доставки #1222 — в пост-записи ниже.** Строк я не добавлял: строки
ADR-1073 и ADR-1074 СЛИТЫ в одну (обе от 23.11, детали в реестре и журнале), и освободившаяся
строка отдана ADR-1077.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Контрольный прогон цикла #1222 (вписано ПОСЛЕ доставки)

**Доставлено одним коммитом `7bfc814950d36ec64a9afdccd7c97947b2789fc3`** — 15 файлов, база
пинована `--expected-base f317721b3de8f3114995e4b4583dd45b66751937`; слепок байтов сверен у
**40** чтений, слепок режимов — у **4**, разбор уезжающего Python — **4** файла. Доставка шла из
СВЕЖЕГО дерева на `origin/main` (наследство двух мёртвых сессий в индексе читается стражем
перезаписи как `diverged` — урок #1220).

**Заказан прогон `45188707864`** (`SPA CI control`, run_number 394 → **395**, `total_count`
394 → 395) на ПОЛНОЙ sha `7bfc814950d36ec64a9afdccd7c97947b2789fc3`, поданной во **ВХОД**
`inputs.sha` при `ref: main` — HTTP **204**, `head_sha` перечитан у API и СОВПАЛ, статус
`queued`. **Вердикт НЕ ИЗМЕРЕН** — читать следующему циклу:
`python3 scripts/ci_control_verdict.py --delta 45146707951 45188707864`.
**База сравнения — `45146707951`** (её красный набор измерен мной: **58** имён; против
`45133715376` она дала 92 → 58 при **ПРИШЛО 0**, все 34 ушедших — род часов ⇒ доставка #1221
чиста). Перед сличением спроси у API, нет ли на той же базе прогона новее. **Ось шарда теперь
спрашивается САМА**, и код **2** при непустом «ПРИШЛО» значит «переехало либо ось слепа», а не
«ничего не найдено».

**ОБА предупреждения пушера о провенансе перемерены РУКАМИ, и оба — верный третий исход:**

* карточка приказа теряет **50** строк базы (ни один из 67 предков пути не объясняет) — это
  перенос пост-записи #1216 в архив, уехавший ТЕМ ЖЕ пушем; сверка построчно против
  `origin/main` ПОСЛЕ доставки: **не найдено нигде 0** из 50, строк в карточке 2266 → 2372;
* доска теряет **4** строки перегенерированной шапки (дата сборки, база сверки, итог карточек
  1675 → **1676**, счёт раздела Inbox 970 → 971) при нуле потерь содержания.

**Пределы `STATE.md` после доставки #1222: 150 строк / 29 930 символов / 695 в самой длинной**
(пределы 150 / 30 000 / 700). Запас — **0 строк, 70 символов, 5 по длиннейшей строке.** Строк я
не добавлял: строки ADR-1073 и ADR-1074 слиты в одну сводную, и все факты обеих снятых строк
найдены по адресам (`74 → 70` · `86 → 74` · `652` · `547` · `458` · `29.9 %` · `115 … 244` ·
`160→165` · `код 19` · `NameError` · `18 применено · убито 17`) — не найдено нигде 0.

**Чего этот цикл НЕ сделал и это НАЗВАНО:** мутационный прогон прибора ADR-1074
(`derived_artifact_census.py`) — долг G1062 п. 7 — так и не запускался (мутации этого цикла
прогнаны на СВОЕЙ работе, это другой предмет); карточка
`inbox-proba-sanitara-trassy-na-ci-otvechaet-ko` в работу не бралась (у неё нет объявленной
пробы); поле `ShardMap.run`, несущее `sha`, не переименовано намеренно (п. 13 заказа); 13
критериев §50 без мерки не двигались.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1066 (следующему циклу)

**0. Заказ G1059 ОСТАЁТСЯ ЖИВЫМ ЦЕЛИКОМ** (его пп. 1–3, 5, 7–10 не исполнял никто из
#1218…#1223). **Заказ G1065 исполнен в пп. 1, 8, 10, 13**; его **пп. 2, 3, 4, 5, 6, 7, 9, 11, 12
НЕ ИСПОЛНЕНЫ** и перенесены ниже без правок смысла. G1060…G1064 исполнены (последний живой пункт
G1062 — п. 7, мутационный прогон прибора ADR-1074, — закрыт #1223).

**1. Вердикт контрольного прогона цикла #1223 — ПРОЧИТАТЬ ПЕРВЫМ ДЕЛОМ.** Номер и ПОЛНАЯ sha —
в пост-записи ниже. ПОЛНАЯ sha идёт во **ВХОД** `inputs.sha`, а в `ref` — ветка (полная sha в
`ref` даёт HTTP 422 и прогон не стартует вовсе). Имена — ТОЛЬКО из артефакта `report.json`.
Перед сличением спроси у API, нет ли на той же базе прогона НОВЕЕ. Команда одна, и ось шарда
она спрашивает САМА: `python3 scripts/ci_control_verdict.py --delta <база> <новый>`. Код **2**
при непустом «ПРИШЛО» означает «переехало / ось слепа», а НЕ «ничего не найдено».
⚠️ **Урок #1223:** ось ADR-1077 отработала в первом же применении — из 8 пришедших имён
ПЕРЕЕХАЛИ 5, и гнаться осталось за ОДНИМ. Но «гнаться за одним» ≠ «это регрессия доставки»:
единственный кандидат #1223 оказался бомбой с шагом в СЕКУНДУ, зелёной на Маке и красной на
загруженном раннере. **Спрашивай прогоном на СВОЁМ дереве, а не только дельтой.**

**2. ОТКРЫТО ЗАМЕРОМ #1223: ось «отрицательный возраст» закрыта у ОДНОЙ двери, население НЕ
ИЗМЕРЕНО.** Карточка `inbox-vozrast-nablyudeniya-byvaet-otritsatelny` (`new`, пробы нет — объяви
ДО работы). У `_meta` зовов десятки, и порядок назван в карточке: СПЕРВА население (собрать
модель на прод-`data/`, перечислить секции с `age_min < 0` поимённо), ПОТОМ правка. Правка
`_meta` задевает ВСЕ секции панели владельца — покрасить дашборд, не зная цены, это та же
ошибка в другую сторону.

**3. ОТКРЫТО ЗАМЕРОМ #1223: притязание `injected-clock` подтверждается, когда дверь к часам
достигается ВНУТРИ процесса через ПРОДУКЦИОННЫЙ код.** Карточка
`inbox-prityazanie-injected-clock-podtverzhdaet` (`new`, пробы нет). Это НЕ девятая дверь
(ADR-897 — подпроцесс). Население: **51** файл несёт притязание, и все 51 подтверждены меркой,
этой формы не видящей. Учить сторожа ТОЛЬКО после замера населения (порядок ADR-897 п. 3), иначе
покрасишь неизвестное число файлов и научишь дописывать в базу.

**4. ПЕРЕНЕСЁН из G1065 п. 2: два имени `test_tb_sanitizer_probe.py` — осталась ОДНА
неизмеренная ось.** Карточка `inbox-proba-sanitara-trassy-na-ci-otvechaet-ko` (`new`, пробы нет).
На Маке догадка «ребёнок взял не тот плагин» ОПРОВЕРГНУТА, «виноваты флаги» тоже. Осталась ось
**ОС и версия Python** (CI `ubuntu-latest`/3.11 против Мака 3.13). Запись сцены обязана НЕСТИ
путь загруженного плагина и `sys.path` ребёнка. Пока этого нет, зарегистрированная проба
`tb_sanitizer_sees_the_report_excinfo` на CI слепа — это опаснее красного теста.

**5. ПЕРЕНЕСЁН из G1065 п. 3 (мерка «что МОИ байты способны покрасить») — ОБЪЯВЛЯЙ ОХВАТ ВСЛУХ,
и СВЕРЯЙ ПОЛЕ.** Тот же прибор на том же дереве даёт **65** сторожей при 5 объявленных каталогах
и **77** при 11. ⚠️ **Урок #1223:** моё первое чтение дало **0**, потому что я спросил поле
`calls[].dir` вместо `entries[].source_dirs` — дешёвая ось соврала в сторону «чисто», и ноль
выглядел как ответ. Верный замер при 9 каталогах — **78**. Форма записи прибора:
`{"path", "calls":[{"lineno","attr","kind","rel_dir","reason"}], "kind", "source_dirs"}`.

**6. ПЕРЕНЕСЁН из G1065 п. 4: четыре сторожа карточки
`inbox-chetyre-storozha-krasny-na-chistom-origi` красны на `main`**, подтверждены на ТРЁХ базах
(`2fc564a0e`, `0b4c3d35c`, `f317721b3`) ⇒ доставки их не двигали. Чинить У ПИСАТЕЛЯ, по одному,
с пробой до работы; дописывать в базы ЗАПРЕЩЕНО (инв. #16).

**7. ПЕРЕНЕСЁН из G1065 п. 5: класс «подмена, пережившая сцену» ШИРЕ двери launchd и за её
пределами НЕ ИЗМЕРЕН.** Соседний член НАЗВАН замером #1220 и не чинился: при сборе обоих корней
прогон печатает `network guard was RE-INSTALLED mid-run · missing[urlopen]` — та же форма, другая
дверь.

**8. ПЕРЕНЕСЁН из G1065 п. 6: два артефакта офиса НЕ ПРОЧИТАНЫ ТРИНАДЦАТЫЙ цикл подряд.** Без
изменений, причина чужая и названа (`com.spa.decision_loop` во флоте не загружен, включение —
действие владельца, ADR-1053/1061). Дубля не заводить.

**9. ПЕРЕНЕСЁН из G1065 п. 7: прод-копия приказа всё ещё нечитаема.** На `origin/main` карточка
**115 136 Б** (после переноса #1223), в прод-дереве — **2 880 412 Б**, то есть **25,0×**. Шаг
0a-ГОЛОД читает ПРОД-копию. Карточка владельцу есть
(`owner-decision-rabochaya-kopiya-prikaza-portfolio-cio-n`), дубля не заводить; синхронизация
прод-дерева — действие ВЛАДЕЛЬЦА.

**10. ПЕРЕНЕСЁН из G1065 п. 9: ось «тот ли ШАРД» закрыта, ось «те ли СОСЕДИ» — НЕТ.** Файл мог
остаться на шарде 7, а полюттер — приехать к нему; мерить это нечем, кроме состава шарда целиком.
Население класса «мера, не спросившая о перетасовке» за пределами ЭТОЙ дельты НЕ ИЗМЕРЕНО.

**11. ПЕРЕНЕСЁН из G1065 п. 12: карточка `inbox-shag-ofis-0-sudit-statusy-kartochek-po-p`** (`new`,
пробы нет). Предмет — строка офиса «критерий выполнен, а карточка открыта» склеивает ДВА дерева:
статусы из прод-копии, числа из дерева прогона. Свести оба чтения к ОДНОМУ дереву либо печатать
третий исход «статусы из <A>, числа из <B>», и замерить население строк на расхождении деревьев.

**12. УРОК #1223 О САМОМ МУТАЦИОННОМ ЗАМЕРЕ — читать до того, как гнать спеку.** Три дефекта
были у МЕРКИ, не у кода, и каждый выглядел находкой:
(а) мутация `KNOWN_MEMBERS = {} or {…}` выжила ДВА прогона, а дыры покрытия нет: **`or`
возвращает непустой операнд**, мутант был ТОЖДЕСТВЕН коду. Опустошает `{} if True else {…}`;
(б) **спека мерила ЧУЖИЕ байты.** Перед прогоном DERIVED я откатил в дереве мутаций три файла
(`git checkout --`), и следующий прогон SHARD пошёл по origin-байтам с origin-тестами — поймано
по исходу `НЕ ПРИМЕНЕНА` у мутации, чей якорь я сам чинил под свои байты. **Перед каждым
прогоном сверяй `git status` дерева мутаций со своим набором**, а не полагайся на то, что файлы
там «с прошлого раза»;
(в) якоря спеки СЛЕДУЮТ ЗА БАЙТАМИ: правка кода ломает чужие якоря (3 из 20 у SHARD-1077), и
«НЕ ПРИМЕНЕНА» это третий исход, а не «мутация не нужна».

**13. Сжимать в архив тем же порядком** (G1059 п. 6): сперва спроси у адреса, несёт ли он
предмет, потом сверь ПОБАЙТОВО, и только потом снимай текст. #1223 так перенёс заказ G1062 и
контрольный прогон #1218 (md5 блока `6518977991053abfce4a76a66d08f8fa`, 91 строка / 5955
символов; снятых строк, не найденных в архиве, — **0**). Следующему — **заказ G1063 и прогон
#1220**; G1059 снимать НЕЛЬЗЯ, пока его пункты не исполнены.

**Пределы `STATE.md` после доставки #1223 — в пост-записи ниже.** Строк я не добавлял, а
ОСВОБОДИЛ одну: слиты пары ADR-1060+ADR-1062 (один предмет — индекс очереди против очереди, две
оси одного гейта) и ADR-1064+ADR-1065 (один предмет — юнит-тест двигал живой флот). Все факты
снятых строк найдены по адресам, не найдено нигде **0**.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1067 (следующему циклу)

**0. Заказ G1059 ОСТАЁТСЯ ЖИВЫМ ЦЕЛИКОМ** (его пп. 1–3, 5, 7–10 не исполнял никто из
#1218…#1225). **Заказ G1066 исполнен в пп. 1 и 13**; его **пп. 2–12 НЕ ИСПОЛНЕНЫ** и
перенесены ниже без правок смысла. G1060…G1065 исполнены и перенесены в архив.

**1. Вердикт контрольного прогона цикла #1226 — ПРОЧИТАТЬ ПЕРВЫМ ДЕЛОМ.** Номер и ПОЛНАЯ
sha — в пост-записи ниже. ПОЛНАЯ sha идёт во **ВХОД** `inputs.sha`, в `ref` — ветка
(полная sha в `ref` даёт HTTP 422 и прогон не стартует вовсе). Команда одна, и ось шарда
она спрашивает САМА: `python3 scripts/ci_control_verdict.py --delta <база> <новый>`. Код
**2** при непустом «ПРИШЛО» означает «переехало / ось слепа», а НЕ «ничего не найдено».
Перед сличением спроси у API, нет ли на той же базе прогона НОВЕЕ.

**2. ДВЕ ДОСТАВКИ ПОДРЯД УЕХАЛИ БЕЗ КОНТРОЛЬНОГО ПРОГОНА, и это ИЗМЕРЕНО.** На вершинах
#1225 (`40c815599`, `0e8941222`) прогона `SPA CI control` НЕТ НИ ОДНОГО — спрошено у API
23.11. Поэтому базой для дельты #1226 служит `45217734687` (вершина `b08347fc6`, цикл
#1223), и между базой и моими байтами лежат ЧУЖИЕ коммиты двух циклов: имя, пришедшее в
дельте, может принадлежать не мне. **Это НЕ повод не заказывать прогон, а повод назвать
базу вслух** — и повод заказывать его КАЖДОЙ доставкой, иначе дельта растёт на чужие
коммиты и перестаёт отвечать о своих.

**3. ОТКРЫТО ЗАМЕРОМ #1226: остаток населения класса «читатель отвечает о ДРУГОМ
носителе молча» — `scripts/build_tracker_board.py`.** У `drift.Report` четыре читателя;
измеренный трекер называют теперь **3 из 4** (ADR-1080). Доска его не называет; риск у
неё ниже ПО ПОСТРОЕНИЮ (её `TRACKER` выводится из `__file__`, и чужое дерево возникает
только под явным `--tracker-dir`), но это оговорка, а не доказательство пустоты. Карточки
на остаток НЕ заводил — он назван здесь и в ADR-1080 § «Чего это НЕ закрывает».
**Население класса за пределами этих четырёх читателей НЕ ИЗМЕРЕНО** и нулём не считается.

**4. ПЕРЕНЕСЁН из G1066 п. 2: ось «отрицательный возраст» закрыта у ОДНОЙ двери,
население НЕ ИЗМЕРЕНО.** Карточка `inbox-vozrast-nablyudeniya-byvaet-otritsatelny` (`new`,
пробы нет — объяви ДО работы). Порядок назван в карточке: СПЕРВА население (собрать модель
на прод-`data/`, перечислить секции с `age_min < 0` поимённо), ПОТОМ правка. Правка
`_meta` задевает ВСЕ секции панели владельца.

**5. ПЕРЕНЕСЁН из G1066 п. 3: притязание `injected-clock` подтверждается, когда дверь к
часам достигается ВНУТРИ процесса через ПРОДУКЦИОННЫЙ код.** Карточка
`inbox-prityazanie-injected-clock-podtverzhdaet` (`new`, пробы нет). Это НЕ девятая дверь
(ADR-897 — подпроцесс). Население: **51** файл несёт притязание, и все 51 подтверждены
меркой, этой формы не видящей. Учить сторожа ТОЛЬКО после замера населения.

**6. ПЕРЕНЕСЁН из G1066 п. 4: два имени `test_tb_sanitizer_probe.py` — осталась ОДНА
неизмеренная ось.** Карточка `inbox-proba-sanitara-trassy-na-ci-otvechaet-ko` (`new`,
пробы нет). Догадки «ребёнок взял не тот плагин» и «виноваты флаги» ОПРОВЕРГНУТЫ на Маке.
Осталась ось **ОС и версия Python** (CI `ubuntu-latest`/3.11 против Мака 3.13). Запись
сцены обязана НЕСТИ путь загруженного плагина и `sys.path` ребёнка.

**7. ПЕРЕНЕСЁН из G1066 п. 5: мерку «что МОИ байты способны покрасить» выводи из БАЙТОВ,
и СВЕРЯЙ ПОЛЕ.** `python3 scripts/derived_artifact_census.py --surface --json` ∩ каталоги
своей доставки, поле `entries[].source_dirs` (НЕ `calls[].dir` — дешёвая ось дала 0 и ноль
выглядел ответом). Число есть ответ о НАЗВАННОМ ОХВАТЕ: 65 при 5 каталогах, 78 при 9, 77
при 11.

**8. ПЕРЕНЕСЁН из G1066 п. 6: четыре сторожа карточки
`inbox-chetyre-storozha-krasny-na-chistom-origi` красны на `main`**, подтверждены на ТРЁХ
базах ⇒ доставки их не двигали. Чинить У ПИСАТЕЛЯ, по одному, с пробой до работы;
дописывать в базы ЗАПРЕЩЕНО (инв. #16).

**9. ПЕРЕНЕСЁН из G1066 п. 7: класс «подмена, пережившая сцену» ШИРЕ двери launchd и за
её пределами НЕ ИЗМЕРЕН.** Соседний член НАЗВАН замером #1220 и не чинился: при сборе
обоих корней прогон печатает `network guard was RE-INSTALLED mid-run · missing[urlopen]`.

**10. ПЕРЕНЕСЁН из G1066 п. 8: два артефакта офиса НЕ ПРОЧИТАНЫ ЧЕТЫРНАДЦАТЫЙ цикл
подряд** (замер #1226: офис 145 / 2). Причина чужая и названа: `com.spa.decision_loop` во
флоте не загружен, включение — действие ВЛАДЕЛЬЦА (ADR-1053/1061). Мост молчит **611 ч**
при горизонте 192 ч, и отсрочка держится САМИМ его молчанием. Дубля не заводить.

**11. ПЕРЕНЕСЁН из G1066 п. 9, с НОВЫМ замером: прод-копия приказа всё ещё нечитаема, а
прод-ТРЕКЕР отстал на 743 карточки.** Замер #1226: на `origin/main` карточек **1681**, в
прод-дереве — **938**. Шаг 0a-ГОЛОД и читатель очереди БЕЗ флага читают ПРОД-копию.
С ADR-1080 читатель об этом хотя бы ГОВОРИТ и даёт рычаг; синхронизация прод-дерева —
действие ВЛАДЕЛЬЦА, карточка есть
(`owner-decision-rabochaya-kopiya-prikaza-portfolio-cio-n`), дубля не заводить.

**12. ПЕРЕНЕСЁН из G1066 п. 10: ось «тот ли ШАРД» закрыта, ось «те ли СОСЕДИ» — НЕТ.**
Файл мог остаться на шарде 7, а полюттер — приехать к нему; мерить это нечем, кроме
состава шарда целиком.

**13. ПЕРЕНЕСЁН из G1066 п. 11: карточка `inbox-shag-ofis-0-sudit-statusy-kartochek-po-p`**
(`new`, пробы нет). Предмет — строка офиса «критерий выполнен, а карточка открыта»
склеивает ДВА дерева: статусы из прод-копии, числа из дерева прогона. **Родня ADR-1080
прямая:** это тот же вопрос «о каком дереве ответ», только у другого читателя — дверь
`drift.measured_tree` уже есть, и второй копии мерки заводить не нужно (ADR-220).

**14. ПЕРЕНЕСЁН из G1066 п. 12: УРОК О САМОМ МУТАЦИОННОМ ЗАМЕРЕ — читать до того, как
гнать спеку.** `or` возвращает непустой операнд (опустошает `{} if True else {…}`) ·
спека умеет мерить ЧУЖИЕ байты — сверяй `git status` дерева мутаций со своим набором
ПЕРЕД каждым прогоном · якоря спеки СЛЕДУЮТ ЗА БАЙТАМИ, и «НЕ ПРИМЕНЕНА» это третий
исход. **Урок #1226 к этому же:** выжившая мутация бывает НАСТОЯЩЕЙ дырой, а не
эквивалентом — M10 (`_CODE_TRACKER_DIR = None`) выжила на том, что умолчание двери
подставляло дерево ПРИБОРА, и закрылась правкой КОДА плюс различающей сценой, а не
правкой спеки.

**15. Сжимать в архив тем же порядком** (G1059 п. 6): сперва спроси у адреса, несёт ли он
предмет, потом сверь ПОБАЙТОВО, и только потом снимай текст. #1226 так перенёс заказ
G1063 и прогон #1220 (md5 блока `0cdfa53856057a4bd308bdbd3c96a9c3`, 149 строк / 10 299
символов; заголовка в архиве не было — `grep` дал 0 по обоим). Следующему — **заказ G1064
и контрольный прогон #1220**; G1059 снимать НЕЛЬЗЯ, пока его пункты не исполнены.

**16. Пределы `STATE.md` после доставки #1226 — в пост-записи ниже.**

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Контрольный прогон цикла #1226 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `af59d626d78ae65c594f8e68cbb7cb6ef489f2ea` — 12 файлов, база
пинована `--expected-base 0e8941222535b01a861c40f6db844317fe003e44`; слепок байтов сверен
у **34** чтений, режимов — у **2**, разбор уезжающего Python — **4** файла.

**Заказан прогон `45273919338`** (`SPA CI control`, run_number 396 → **397**,
`total_count` 396 → 397) на ПОЛНОЙ sha `af59d626d78ae65c594f8e68cbb7cb6ef489f2ea`,
поданной во **ВХОД** `inputs.sha` при `ref: main` — HTTP **204**, `head_sha` перечитан у
API и СОВПАЛ, статус `queued`. **Вердикт НЕ ИЗМЕРЕН** — читать следующему циклу:
`python3 scripts/ci_control_verdict.py --delta 45217734687 45273919338`.

**База сравнения — `45217734687`, и она НЕ МОЯ вершина.** Её красный набор ИЗМЕРЕН мной:
**60** имён (против `45188707864` дала 66 → 60 при ПРИШЛО 2 — ОБА рода стенных часов, то
есть вердикта о них прогон не вынес; УШЛО 8, из них род часов 7). **Гнаться стоило за 0
именами.** Между базой и моими байтами лежат коммиты цикла #1225
(`40c815599`, `0e8941222`): на обеих его вершинах прогона `SPA CI control` НЕТ НИ ОДНОГО
(спрошено у API), поэтому имя, пришедшее в моей дельте, может принадлежать не мне. Это
названо в заказе G1067 п. 2.

**Четыре предупреждения пушера о провенансе перемерены РУКАМИ, каждое по отдельности —
все три источника оказались верным третьим исходом, НАХОДКИ среди них нет:**

* `inbox-ochered-vladeltsa-chitaetsya-iz-prod-kop.md` теряет строку `status: new` — это
  ровно предмет работы (карточка закрыта `done`);
* `inbox-task-portfolio-cio-dynamic-capital-alloc.md` теряет **121** строку базы — это
  перенесённый в архив блок. Сверено НЕ на слово: из **149** строк снятого блока в
  архиве найдено **149**, НЕ НАЙДЕНО **0** (построчная сверка, не только md5). Пушер сам
  назвал оба раздела перенесёнными и сверил их тела с remote побайтово;
* `_BOARD.md` теряет **2** строки — метку сборки и строку «Сверено с `origin/main`
  (40c815599)». Это churn авто-индекса, не чужая карточка.

**Что мерил своими руками, а не брал из прозы заказа.**

* **Сторож `test_edge_boundary_dataflow_census` красен и на ЧИСТОМ `origin/main`.** Он
  единственный упал в моём прогоне 63 сторожей (**1 failed, 4379 passed, 6 subtests**,
  258.9 с). ПЕРЕМЕРЕН на дереве, откаченном к байтам origin: то же имя, то же сообщение
  `AssertionError: 45 != 35`. Краснота НЕ моя — названный член карточки
  `inbox-chetyre-storozha-krasny-na-chistom-origi` (G1067 п. 8).
* **Мерка «что мои байты способны покрасить» — из БАЙТОВ, поле `entries[].source_dirs`.**
  При **6** объявленных каталогах (`scripts`, `spa_core/monitoring`, `spa_core/tests`,
  `docs/decisions`, `docs/journal`, `nimbalyst-local/tracker`) — **63** сторожа из 510
  записей переписи. Число есть ответ о НАЗВАННОМ ОХВАТЕ (G1067 п. 7).
* **Шаг 1г (ADR-926) прогнан в ОТДЕЛЬНОМ дереве** `/private/tmp/spa_c1226mut`, названном
  входом `--repo-root`: **бомб нет** — при задержке 95 мин ни один вердикт не изменился.
* **Окно мутационного прибора в дереве доставки:** `--window-check` → `no_window`, код 0.

**Пределы `STATE.md` после доставки #1226: 149 строк / 29 957 символов / 695 в самой
длинной** (пределы 150 / 30 000 / 700). Запас — **1 строка, 43 символа, 5 по длиннейшей**.
Строку я не добавлял: ADR-1080 влит в строку ADR-1072 — у них ОДИН предмет («ответ о
другом носителе, выданный за ответ о моём»), и 1072 мерил его по шагам цикла (предмет 0
при знаменателе 3), а 1080 нашёл НЕПУСТЫМ у читателя очереди. Все факты сжатой строки
найдены по адресам (файл решения ADR-1072 и журнал W47) — не найдено нигде **0**.

**Чего этот цикл НЕ сделал и это НАЗВАНО:** два артефакта офиса не прочитаны
ЧЕТЫРНАДЦАТЫЙ цикл подряд (причина чужая — `com.spa.decision_loop` во флоте не загружен,
действие владельца; мост молчит 611 ч при горизонте 192 ч) · остаток населения класса
ADR-1080 — `scripts/build_tracker_board.py` измеренный трекер не называет, карточки не
заводил, назван здесь и в ADR · три карточки без объявленной пробы в работу не брались ·
13 критериев §50 без мерки не двигались · четыре сторожа, красные на чистом `origin/main`,
не чинились (одного перемерил) · прод-трекер отстал на **743** карточки (938 против 1681),
синхронизация прод-дерева — действие ВЛАДЕЛЬЦА · витрина чисел сайта собрана и НЕ
доставлена (ворота публикации, код 4, карточка владельцу уже открыта) — объявлена
`--dropped`.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Контрольный прогон цикла #1223 (вписано ПОСЛЕ доставки)

**Доставлено ДВУМЯ коммитами**, и второй — сам находка (ниже):
`5f887a5150bf1088ad8670b2ff80d4a1c9f47995` (19 файлов, база пинована
`--expected-base f36581710e30f85af602ceec58733a0bdd0795c0`; слепок байтов сверен у **53**
чтений, режимов — у 4, разбор уезжающего Python — **8** файлов) и
`b08347fc60399dc2a6f2fc5328e29880cb2ef9c2` (5 файлов, база пинована `5f887a515`; байты сверены
у 14 чтений, Python — 1 файл).

**Заказан прогон `45217734687`** (`SPA CI control`, run_number 395 → **396**, `total_count`
395 → 396) на ПОЛНОЙ sha `b08347fc60399dc2a6f2fc5328e29880cb2ef9c2`, поданной во **ВХОД**
`inputs.sha` при `ref: main` — HTTP **204**, `head_sha` перечитан у API и СОВПАЛ, статус
`in_progress`. **Вердикт НЕ ИЗМЕРЕН** — читать следующему циклу:
`python3 scripts/ci_control_verdict.py --delta 45188707864 45217734687`.
**База сравнения — `45188707864`**, и её красный набор ИЗМЕРЕН мной: **66** имён (против
`45146707951` она дала 58 → 66 при ПРИШЛО 8, из них род часов 7, ПЕРЕЕХАЛИ 5, УШЛО 0).
Единственное имя, за которым стоило гнаться, разобрано до корня и починено — ADR-1078.

**Предупреждения пушера о провенансе перемерены РУКАМИ, каждое по отдельности, и одно из
четырёх оказалось НАХОДКОЙ, а не третьим исходом:**

* `read.py` теряет 1 строку — подстановка стенных часов; это ПРЕДМЕТ решения (верный третий
  исход);
* `card_acceptance.py` теряет 3 строки — недостижимая проверка `census.code == 0`, заменённая
  достижимой; ПРЕДМЕТ решения;
* `red_set_delta.py` теряет 16 строк — все формы `run=run)` стали `run=run, sha=sha)`, то есть
  утверждение не снято, а расширено; ПРЕДМЕТ решения;
* **`test_derived_artifact_census.py` терял 1 строку — и это НАХОДКА.** Укрепляя тест о двери
  поверхности, я ЗАМЕНИЛ слабое притязание (`assertIn("measure_surface", why)`) сильным
  (`assertIn("нет двери", why)`), а они НЕ покрывают друг друга: «нет двери» верно и о ЧУЖОЙ
  двери. Оба возвращены вторым коммитом. **Списывать все предупреждения разом на «это и есть
  предмет» нельзя — мерять надо каждое.**

**Вторая находка доставки, и она о ГЕЙТАХ, а не о коде.** Досылка получила два отказа подряд на
ВЕРНОЙ работе:

1. **rc=1, интерлок номеров ADR:** «в `INDEX.md` нет ни одной строки ADR-1078» — при том, что
   строка уехала первым же коммитом и на сервере ЕСТЬ. Гейт спрашивает реестр у **ЛОКАЛЬНОЙ**
   ссылки `origin/main`, а пушер её НЕ ОБНОВЛЯЕТ; прямой зов того же сторожа тем же набором
   после `git fetch` — **0 находок, 0 пропусков**.
2. **rc=4, страж перезаписи:** пуш из дерева, чей git-HEAD остался на ПРЕЖНЕЙ вершине
   (`f36581710`), читается как расхождение, хотя содержимое — надмножество. Лечение то же, что у
   урока #1220: СВЕЖЕЕ дерево на новой вершине + копирование набора (дерево `c1223b`).

У обоих отказов есть готовый обход (`--allow-adr-collision`, `--allow-overwrite`), и докстринг
самого интерлока предупреждает: «сторож, который краснеет на верную работу, обходят каждый раз, и
тогда он не поймает настоящее столкновение». **Ни одним флагом я не пользовался.** Карточка —
`inbox-geity-dostavki-sprashivayut-origin-ustar`; **население класса НЕ ИЗМЕРЕНО** (так же
спрашивают origin гейты доски, оси статуса, имён переписи и провенанса базы). Пушер не правил
намеренно: менять путь доставки посреди своей доставки значит мерить мутанта (§ «ОКНО ДОСТАВКИ»).

**Пределы `STATE.md` после доставки #1223: 149 строк / 29 965 символов / 695 в самой длинной**
(пределы 150 / 30 000 / 700). Запас — **1 строка, 35 символов, 5 по длиннейшей.** Строку я не
добавлял, а ОСВОБОДИЛ: слиты пары ADR-1060+ADR-1062 и ADR-1064+ADR-1065 (в каждой паре один
предмет), все факты снятых строк найдены по адресам — **не найдено нигде 0**.

**Чего этот цикл НЕ сделал и это НАЗВАНО:** два артефакта офиса не прочитаны тринадцатый цикл
подряд (причина чужая: `com.spa.decision_loop` во флоте не загружен — действие владельца);
карточка `inbox-proba-sanitara-trassy-na-ci-otvechaet-ko` в работу не бралась (у неё нет
объявленной пробы); четыре сторожа, красные на чистом `origin/main`, не чинились — один из них
(`test_edge_boundary_dataflow_census`, `45 != 35`) попал в мой прогон 78 сторожей, и я ПЕРЕМЕРИЛ
его на чистом дереве: краснота не моя; 13 критериев §50 без мерки не двигались; население трёх
классов, открытых этим циклом, НЕ ИЗМЕРЕНО и нулём не считается.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).
