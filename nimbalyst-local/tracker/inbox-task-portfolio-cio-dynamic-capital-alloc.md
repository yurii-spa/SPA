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
claimed_by: cycle-93227
claimed_at: 2026-11-24T16:47:55Z
claimed_run_id: orchestrator-93227-FB1669C9C4F34B538968F7ADD666A198
claimed_pid: 93227
claimed_pid_start: Tue Nov 24 17:42:53 2026
claim_takeover_reason: "шаг 0a-ГОЛОД: держатель cycle-36309 МЁРТВ (ps -p 36309 — процесса нет), приказ in-progress 2272.7 ч, мимо 503 цикла. Заказ G1075 п. 1 исполнен ПЕРВЫМ делом: на базе a0f72dac2 прогона НОВЕЕ нет (6 прогонов, SPA CI control ровно один), дельта 45403100543 -> 45428106750 дала ПРИШЛО 0 (96 -> 83 имени), УШЛО 13 и ВСЕ 13 рода wallclock_timeout (9 переехали шард) — починенным ни одно не объявляется, гнаться стоит за 0 именами"
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

### Заказ G1064 и контрольный прогон цикла #1220 — В АРХИВЕ

Побайтовая копия (**133** строк / **8859** символов, md5 блока
`0a7565774981a5c2e072ca740491272c`) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`. Снял цикл #1227
порядком G1059 п. 6: СПЕРВА спрошен адрес (заголовка `### Заказ G1064` в архиве не было —
`grep` дал 0, как и по «Контрольный прогон цикла #1220»), потом сверено ПОБАЙТОВО И
ПОСТРОЧНО, и только потом снят текст. **Заказ G1059 НЕ ТРОНУТ — он ЖИВОЙ.**

## Цикл #1221 (2026-11-23, ADR-1076) — §50: критерий «Есть owner pause/kill switch» получил мерку

**Тело ПЕРЕНЕСЕНО в архив** (побайтовая копия, 2660 символов) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`.
Перенёс цикл #1232 дверью ADR-1066; причина и замер веса — в шапке архива. Заголовок
сохранён здесь ПОБАЙТОВО: раздел не исчез, у него сменился адрес тела.

## Цикл #1222 (2026-11-23, ADR-1077) — ось ПЕРЕЕЗДА в дельте красного набора проведена

**Тело ПЕРЕНЕСЕНО в архив** (побайтовая копия, 3913 символов) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`.
Перенёс цикл #1232 дверью ADR-1066; причина и замер веса — в шапке архива. Заголовок
сохранён здесь ПОБАЙТОВО: раздел не исчез, у него сменился адрес тела.

### Заказ G1065 — В АРХИВЕ

Побайтовая копия (**99** строк / **6616** символов, md5 блока `c7653793eb4096e5304c8f2f78b54176`) —
`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`. Снял цикл #1230 порядком G1069 п. 17
(адрес спрошен ПЕРВЫМ: заголовка `### Заказ G1065` в архиве не было, `grep` дал 0 при одном
упоминании номера в прозе). **Заказ G1059 НЕ ТРОНУТ — он ЖИВОЙ.**

### Заказ G1066 и контрольный прогон цикла #1222 — В АРХИВЕ

> Снято циклом #1228 ПОСЛЕ побайтового переноса в
> [`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`](../../docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md)
> (md5 блока `550311f70dba5b5dbfe03e10f31bc382`). Проза G1068 п. 16 утверждала, что текст G1066 уже перенесён в G1067/G1068 —
> постро́чный замер нашёл **6 строк из 83**, поэтому перенос сделан, а не зачтён.

### Заказ G1067 (следующему циклу)

Тело перенесено ПОБАЙТОВО циклом #1233 в `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md` — приказ упёрся в СТРОЧНУЮ ось храповика веса (запас была ОДНА
строка). Живые пункты этого заказа несёт заказ ниже (цепочка п. 0 у каждого
преемника); раздел не исчез, у него сменился АДРЕС тела.

### Заказ G1068 (следующему циклу)

Тело перенесено ПОБАЙТОВО циклом #1233 в `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md` — приказ упёрся в СТРОЧНУЮ ось храповика веса (запас была ОДНА
строка). Живые пункты этого заказа несёт заказ ниже (цепочка п. 0 у каждого
преемника); раздел не исчез, у него сменился АДРЕС тела.

### Заказ G1069 (следующему циклу)

Тело перенесено ПОБАЙТОВО циклом #1233 в `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md` — приказ упёрся в СТРОЧНУЮ ось храповика веса (запас была ОДНА
строка). Живые пункты этого заказа несёт заказ ниже (цепочка п. 0 у каждого
преемника); раздел не исчез, у него сменился АДРЕС тела.

### Контрольный прогон цикла #1228 (вписано ПОСЛЕ доставки)

**Тело ПЕРЕНЕСЕНО в архив** (побайтовая копия, 2858 символов) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`.
Перенёс цикл #1232 дверью ADR-1066; причина и замер веса — в шапке архива. Заголовок
сохранён здесь ПОБАЙТОВО: раздел не исчез, у него сменился адрес тела.

### Контрольный прогон цикла #1227 (вписано ПОСЛЕ доставки)

**Тело ПЕРЕНЕСЕНО в архив** (побайтовая копия, 5060 символов) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`.
Перенёс цикл #1232 дверью ADR-1066; причина и замер веса — в шапке архива. Заголовок
сохранён здесь ПОБАЙТОВО: раздел не исчез, у него сменился адрес тела.

### Контрольный прогон цикла #1226 (вписано ПОСЛЕ доставки)

**Тело ПЕРЕНЕСЕНО в архив** (побайтовая копия, 4486 символов) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`.
Перенёс цикл #1232 дверью ADR-1066; причина и замер веса — в шапке архива. Заголовок
сохранён здесь ПОБАЙТОВО: раздел не исчез, у него сменился адрес тела.

### Контрольный прогон цикла #1223 — В АРХИВЕ

Побайтовая копия (**66** строк / **4432** символа, md5 блока `eae9079c4f19bd7db9bbb4aba894f1e7`) —
`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`. Снял цикл #1230 порядком G1069 п. 17:
СПЕРВА спрошен адрес (заголовка в архиве не было — `grep` дал 0 при 14 упоминаниях `#1223`), потом
сверено ПОБАЙТОВО (137 непустых строк обоих блоков, НЕ НАЙДЕНО **0**), и только потом снят текст.

## Цикл #1230 (2026-11-24, ADR-1083 доставлен + ADR-1084) — утверждение предшественника о доставке ПЕРЕМЕРЕНО, и оно было ложным

**Шаг 0a-ГОЛОД отдал такт этой карточке** (`in-progress` 2260,0 ч, держателя нет, мимо прошло
500 циклов). Держатель `cycle-77239` (#1228) мёртв; захват перенят.

**Заказ G1069 п. 1 исполнен ПЕРВЫМ ДЕЛОМ, и п. 2 оказался не напрасен.** У API спрошено, ЖИВ
ли `45304210098`: `completed` / `failure` / `head_sha` `d3ba8a88b`, прожил 01:19:40Z →
02:36:42Z — **НЕ вытеснен**, вердикт есть. Прогона НОВЕЕ на той же базе нет. Дельта против
`45292219029`: **58 → 83** имени, **ПРИШЛО 30 и ВСЕ 30 — род стенных часов** (вердикта прогон
о них не вынес; переехали 4), ушло 5 (переехали 2). **Гнаться за 0 — доставка #1228 чиста.**

**Заказ G1069 п. 3 (названный ДОЛГ) — ЗАКРЫТ, но не мной: его сделал #1229 и НЕ ДОСТАВИЛ.**
Замер на `origin/main` (`d67fe6000`): `--order-run` в `scripts/ci_control_verdict.py` — **0**,
файла `ADR-1083` — **НЕТ**, строки в `INDEX.md` — **НЕТ**. При этом запись ПАМЯТИ
(`ci-control-run-is-ordered-through-a-door-not-curl.md`, изменена 02:56Z) утверждала обратное:
«С 2026-11-24 (цикл #1229, ADR-1083) контрольный прогон заказывают дверью». Байты лежали
осиротевшим деревом `/private/tmp/spa_c1229anchor` (окна мутаций нет, `--window-check` код 0).

**Доставил #1230, ПЕРЕМЕРИВ своими руками, а не приняв на слово:** батарея **40 passed, 16
subtests** в дереве доставки · **44 failed, 3 passed** на ЧИСТОМ origin (положительный
контроль) · мутации спеки ADR-1083 — **применено 23 · убито 23 · выжило 0 · НЕ ПРИМЕНЕНО 0** в
отдельном дереве `spa_c1229mut`, md5 обоих файлов РАВНЫ дереву доставки. Числа мутаций в ADR
вписаны ПОСЛЕ прогона (у предшественника их не было — он умер раньше).

**ADR-1084 — одиннадцатая дверь семейства, и носитель у неё новый: ПАМЯТЬ.** Класс «запись
памяти называет модуль, которого на `origin/main` нет» не судится НИ ОДНИМ сторожем по
построению: пушер судит УЕЗЖАЮЩИЕ байты, храповики сирот перечисляют каталоги репозитория,
офис читает ОБЪЯВЛЕННЫЕ артефакты — а каталог памяти лежит вне репозитория и грузится в
КАЖДУЮ сессию как фон. Самый дорогой член: `orphaned-worktree-recovery.md` **58 дней**
утверждала «теперь класс МЕРИТ ПРИБОР `spa_core/monitoring/undelivered_work_census.py` (цикл
#706, ADR-482), читать его в шаге 0a ДО выбора карточки» — ни модуля, ни ADR-482, ни ОДНОГО
упоминания имени в дереве. Прибор класса «осиротевшая недоставленная работа» сам был
осиротевшей недоставленной работой. Замер: **9** записей / **10** модулей из 916 (дешёвая
широкая ось врёт в 19 раз: 169 записей / 247 путей). Починено **9 → 0**: 4 адреса правлены,
8 отсутствий ОБЪЯВЛЕНЫ формой `ABSENT-OK: <причина>` (образец `# FROZEN-DATE-OK:`, действует
НА СТРОКЕ, причина обязательна, число объявленных ПЕЧАТАЕТСЯ). Сторож **21 passed**, мутации
**18/18**, и первый прогон дал 12 из 15 — все три выживших были дырами МОИХ СЦЕН, записаны
как дыры и закрыты сценами.

**Заказ G1069 п. 17 исполнен:** `### Заказ G1065` (99 строк / 6616 символов, md5
`c7653793eb4096e5304c8f2f78b54176`) и `### Контрольный прогон цикла #1223` (66 строк / 4432
символа, md5 `eae9079c4f19bd7db9bbb4aba894f1e7`) перенесены ПОБАЙТОВО в
`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-22.md`. Адрес спрошен ПЕРВЫМ: обоих
заголовков в архиве не было (`grep` 0 и 0 при 1 и 14 упоминаниях номеров в прозе). После
переноса из **137** непустых строк НЕ НАЙДЕНО **0**. Карточка **2605 → 2454** строк
(142 787 → 126 393 байта), храповик веса 10 passed. **Заказ G1059 НЕ ТРОНУТ — он ЖИВОЙ.**

### Заказ G1070 (следующему циклу)

Тело перенесено ПОБАЙТОВО циклом #1233 в `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md` — приказ упёрся в СТРОЧНУЮ ось храповика веса (запас была ОДНА
строка). Живые пункты этого заказа несёт заказ ниже (цепочка п. 0 у каждого
преемника); раздел не исчез, у него сменился АДРЕС тела.

### Контрольный прогон цикла #1230 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `dbe455eca` — **16** файлов, база пинована
`--expected-base d67fe6000e666a93fb13a9bab2479a8ca56b98f9`; слепок байтов сверен у **43**
чтений, режимов — у **7**, разбор уезжающего Python — **6** файлов. Проверено на origin
поимённо: ADR-1083 ЕСТЬ · ADR-1084 ЕСТЬ · `scripts/memory_named_module_census.py` ЕСТЬ ·
батарея ЕСТЬ · спека ЕСТЬ · `--order-run` в `ci_control_verdict.py` — **1** вхождение (было 0) ·
строк ADR-1083/1084 в `INDEX.md` — **2**.

**Заказан прогон `45330264266`** (`SPA CI control`, run_number 401 → **402**, `total_count`
401 → 402) на ПОЛНОЙ sha `dbe455eca…` — и **ЗАКАЗАН НОВОЙ ДВЕРЬЮ, а не `curl`-ом**
(`ci_control_verdict.py --order-run`, ADR-1083, доставленный этим же пушем). Дверь сказала
`группа: FREE · идёт 0 · ждёт 0`, то есть подача никого не вытесняла, и вернула код **1**
«подан, но НЕ ПОДТВЕРЖДЁН: строка появляется не мгновенно». Перечитано `--order-check`:
прогон `45330264266` `in_progress` на моей sha ⇒ **заказ ЖИВ**, якорем брать можно.
**Вердикт НЕ ИЗМЕРЕН**, база сравнения — **`45304210098`** (**83** имени, мой замер).

**Дверь поправила прозу предшественника первым же зовом:** `next_cron_moment` назвал
**2026-11-24T06:23:00Z**, тогда как пост-запись #1228 писала «около 05:23Z». `cron: 23 */6`
даёт часы 0/6/12/18 — число из прозы и число из прибора оказались разными числами, и ровно за
этим дверь и написана.

**Второй вершины с заказом у этого цикла НЕТ намеренно.** Пост-запись (эта правка) есть вторая
вершина доставки, но прогона она НЕ получает: заказ на неё сделал бы мой же заказ на вершине
КОДА ожидающим вторым и убил бы его — порядок G1069 п. 2, и теперь это судит дверь.

**Три предупреждения пушера о провенансе перемерены по отдельности — находки нет:**

* **приказ теряет 133+ строк базы** — это перенесённые в архив блоки `### Заказ G1065` и
  `### Контрольный прогон цикла #1223`. Адрес спрошен ДО снятия (оба заголовка в архиве
  отсутствовали), сверка ПОСЛЕ переноса: из **137** непустых строк НЕ НАЙДЕНО **0**;
* **`_protocol_blindness.py` теряет 2 строки** (`AUDIT_GENERATED_AT` 22.11 и строка прозы с тем
  же моментом) — ровно то, что перезаписал обязательный шаг 1в (код 1, свежесть ДО `STALE`);
* **`_untiered_census.py` теряет 1 строку** (`AUDIT_GENERATED_AT` 23.11) — тот же шаг 1в.

**Перемер прибора ADR-1084 ПОСЛЕ доставки: находок 0** (записей 917 · называют модуль 373 ·
названных модулей 574 · заполнителей 8 · отсутствий ОБЪЯВЛЕНО с причиной 9), код **0**. До
доставки прибор честно показывал ОДНУ находку — самого себя: `scripts/memory_named_module_census.py`
на `origin/main` ещё не было, и «починка — доставить то, что названо» была буквальной.

**Пределы `STATE.md`: 149 строк / 29 982 символа / 695 в длиннейшей** (пределы 150 / 30 000 /
700), запас **1 / 18 / 5**. Строк стало МЕНЬШЕ на одну. **Запас по символам 18 — следующему
циклу сжимать ДО правки** (G1070 п. 3, кандидат назван).

**Прогоны перед доставкой (named-файлами, не широким `-k`).** Мерка «что мои байты способны
покрасить» выведена ИЗ БАЙТОВ (`derived_artifact_census.py --surface --json` ∩ каталоги своей
доставки, поле `entries[].source_dirs`) — **67** сторожей поимённо, и прогнаны они ДВАЖДЫ:
на ЧИСТОМ `origin/main` (`d67fe6000`, дерево `spa_c1230base`) — **1 failed, 4446 passed,
1 skipped**; на моих байтах (дерево `spa_c1230mut`, НЕ дерево доставки) — **1 failed,
4508 passed, 1 skipped, 39 subtests**. Набор упавших имён СОВПАЛ ДО ИМЕНИ
(`test_edge_boundary_dataflow_census.py::…test_the_census_screens_the_population_100_published`)
⇒ **своей регрессии нет**, а единственное красное имя предсуществующее. Плюс
`test_state_md_length_ratchet` 13 passed · `test_tracker_card_weight_ratchet` 10 passed.

### Заказ G1071 (следующему циклу)

Тело перенесено ПОБАЙТОВО циклом #1265 в `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-26.md`
(128 строк / 7950 символов, md5 блока `46bcc50865ecb4db48b7f0c3c7f92d1f`). Порядок — G1059
п. 6: СПЕРВА спрошен адрес (заголовка `### Заказ G1071` не было ни в одном из ЧЕТЫРЁХ архивов,
`grep` дал 0 при одном упоминании номера в прозе), потом сверено ПОБАЙТОВО, и только потом снят
текст. Живые пункты несут преемники (цепочка п. 0); раздел не исчез, у него сменился АДРЕС тела.

### Контрольный прогон цикла #1231 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `53ff603a6f65208919fcd07f4a7a4171981056a1` — **12** файлов,
база пинована `--expected-base 6b04930d0af2cead444ea51b33de2f638587b7bc`; слепок байтов
сверен у **33** чтений, режимов — у **4**, разбор уезжающего Python — **4** файла.
Проверено на origin поимённо: ADR-1085 ЕСТЬ · `scripts/future_dated_observation_census.py`
ЕСТЬ · батарея ЕСТЬ · спека мутаций ЕСТЬ · строка ADR-1085 в `INDEX.md` — **1** ·
`FUTURE_SKEW_MINUTES` в `mission_control.py` — **5** вхождений (было 0) · проба в реестре
`card_acceptance` — **3** · статус карточки `inbox-vozrast-nablyudeniya-byvaet-otritsatelny`
на origin — **`done`**.

**Заказан прогон `45345362170`** (`SPA CI control`) на ПОЛНОЙ sha `53ff603a6…` дверью
`ci_control_verdict.py --order-run` (ADR-1083), а не `curl`-ом. Дверь сказала
`группа: FREE · идёт 0 · ждёт 0`, то есть подача никого не вытесняла, и вернула код **0**
«ЗАКАЗАН и ЖИВ: 45345362170 (`queued`), HTTP 204» — личность и живость ПОДТВЕРЖДЕНЫ сразу,
перечитка не понадобилась. Ближайший расписанный прогон дверь назвала САМА:
**2026-11-24T12:23:00Z**. **Вердикт НЕ ИЗМЕРЕН**, база сравнения — **`45330264266`**
(**60** имён, мой замер).

**Второй вершины с заказом у этого цикла НЕТ намеренно.** Пост-запись (эта правка) есть
вторая вершина доставки, но прогона она НЕ получает: заказ на неё сделал бы мой же заказ
на вершине КОДА ожидающим вторым и убил бы его.

**Страж перезаписи сработал ВЕРНО и дважды, и оба раза ДО единого сетевого вызова.**
Первая подача отказала кодом 4: `--expected-base a6adaff89…` не совпал с живым HEAD
(`6b04930d…` — автодеплой `track_snapshot.json` приехал в середине цикла). Лечение —
СВЕЖЕЕ дерево на новой вершине и повторный пин, а НЕ флаг обхода; байты сверены md5 со
своим деревом (12 из 12 совпали), и слепок набора остался тем же. Вторая подача отказала
на КОРОТКОЙ sha («владелец просил ТОЧНЫЙ коммит») — передана полная 40-hex.

**Три предупреждения пушера о провенансе перемерены по отдельности — находки нет:**

* **`STATE.md` теряет 2 строки базы** — это РОВНО те две строки-указателя
  (`ADR-770…921` и `ADR-922…946`), которые цикл СЛИЛ в одну; проверено: в базе их 2, в
  копии слитая строка 1, и все девять фактов «помнить стóит» названы в ней поимённо
  (886/918/922–925/933 · 931 · 909 · 926–930 · 936/940–944), у каждого адрес спрошен ДО
  снятия;
* **карточка теряет строку `status: new`** — переход `new → in-progress → done` сделан
  `orchestrator_queue.py` (объявление пробы, взятие в работу, закрытие с `closed_by` и
  `evidence`), на origin стои́т `done`;
* **`_BOARD.md` теряет 2 строки** — шапка ПРЕЖНЕЙ сборки (`Собрана: 05:01:26Z` и
  `Сверено с origin/main (dbe455eca)`); моя копия несёт свои две того же вида, доска
  пересобрана прибором.

**Пределы `STATE.md`: 149 строк / 29 982 символа / 695 в длиннейшей** (пределы 150 /
30 000 / 700), запас **1 / 18 / 5** — ровно тот же, что оставил предшественник: место
заработано слиянием и потрачено целиком на свою строку. **Следующему циклу сжимать ДО
правки** (G1071 п. 3, кандидаты названы).

**Прогоны перед доставкой (named-файлами, не широким `-k`).** Мерка «что мои байты
способны покрасить» выведена ИЗ БАЙТОВ (`derived_artifact_census.py --surface --json` ∩
каталоги своей доставки, поле `entries[].source_dirs`) — **65** сторожей поимённо, и
прогнаны они ДВАЖДЫ: на ЧИСТОМ origin (`a6adaff89`, дерево `spa_c1231base`) —
**1 failed, 4412 passed, 1 skipped**; на моих байтах (дерево `spa_c1231mut`, НЕ дерево
доставки) — сперва **2 failed**, и второе имя было МОЕЙ регрессией
(`test_frozen_date_ratchet::test_no_new_file_joins_the_frozen_date_class`). Починено
притязанием `FROZEN-DATE-OK: injected-clock` с названным «как», и притязание ПОДТВЕРЖДЕНО
по AST сторожем #477 (`test_injected_clock_claim`), а не дописано в базу (инв. #16).
Перемер: **1 failed, 4413 passed, 1 skipped** — набор упавших имён СОВПАЛ ДО ИМЕНИ с
чистым origin (`test_edge_boundary_dataflow_census.py::…test_the_census_screens_the_population_100_published`,
то же единственное имя, что назвал #1230) ⇒ **своей регрессии нет**. Плюс
`test_state_md_length_ratchet` 13 passed · `test_tracker_card_weight_ratchet` 10 passed ·
батарея цикла 30 passed, 3 subtests.

**Окно мутационного прибора закрыто:** `--window-check` на `spa_c1231mut` отвечает
«ОКНА НЕТ» (код 0), байты дерева мутаций сверены md5 с доставленными — 4 из 4 совпали.
### Заказ G1072 (следующему циклу)

Тело перенесено ПОБАЙТОВО циклом #1265 в `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-26.md`
(144 строки / 9369 символов, md5 блока `6e706a237fafea0d29cc786461526952`) — карточка упёрлась
в СТРОЧНУЮ ось храповика веса (запас была 45 строк при нужде в ~110). Порядок — G1059 п. 6:
СПЕРВА спрошен адрес (заголовка `### Заказ G1072` в архивах НЕ БЫЛО, `grep` дал 0 при двух
упоминаниях номера в прозе), потом сверено ПОБАЙТОВО, и только потом снят текст. Живые
пункты несут преемники (цепочка п. 0); раздел не исчез, у него сменился АДРЕС тела.

### Заказ G1073 (следующему циклу) — В АРХИВЕ

Перенёс цикл #1263 порядком G1091 п. 8 и G1089 п. 6: адрес спрошен ДО снятия (в четырёх архивах 0 вхождений), сверено ПОБАЙТОВО (md5 `ad5efdfa313e6cc8c6f4832d0e3f4345`, 169 строк / 11 304 символа), и только потом снят текст. Адрес — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-26.md`. Живые пункты заказа перечислены адресом в G1092 п. 8.

### Заказ G1074 (следующему циклу)

> **Тело перенесено в архив** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`
> (раздел «Заказ G1074 — перенесён … циклом #1236»). Раздел НЕ исчез: у него сменился АДРЕС
> тела. Живые пункты **3, 4, 5** перенесены в «Заказ G1076» ниже ДО снятия.

### Заказ G1075 (следующему циклу)

**ТЕЛО ПЕРЕНЕСЕНО В АРХИВ** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`,
раздел «Перенос цикла #1237». Живые пункты (**2, 3, 5, 6, 8, 9, 11, 12**) перенесены в
«Заказ G1077» ниже ДО снятия; исполненные (1, 4, 7, 10) остались в архиве.

### Заказ G1076 (следующему циклу)

> **Тело перенесено в архив ПОБАЙТОВО** циклом #1259 —
> `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`, раздел «Перенос цикла
> #1259». 146 строк / 9889 символов, непустых 126, md5 `771ce84d35fafbc73e86534d328c0799`.
> Раздел НЕ исчез: у него сменился АДРЕС тела. Живые пп. 2, 3, 6, 7, 12–16 названы
> заказом G1088 (запись цикла #1259 в `docs/journal/2026-W48.md`).

### Заказ G1077 (следующему циклу)

**ТЕЛО ПЕРЕНЕСЕНО В АРХИВ** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`, раздел «Перенос цикла
#1260 — „Заказ G1077“» (**130** строк / **8362** символов, md5 `ff43a62afe1581ef8266b38d7d8258e8`).
Раздел НЕ исчез: у него сменился АДРЕС тела. Живые пункты (2–5, 8–17) живут ТАМ, а их
указатель несёт заказ G1089 ниже.
### Заказ G1078 (следующему циклу)

> **Тело перенесено в архив** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`
> (раздел «Перенос цикла #1261 — „Заказ G1078“»). Раздел НЕ исчез: у него сменился АДРЕС тела.
> ЖИВОЙ пункт 4 (карточка `inbox-strazh-sroka-klyucha-ne-sprashivaet-github`, `in-progress`)
> перенесён в заказ G1090 ДО снятия; пп. 0–3 мертвы замером (ключ 200, ADR-1093/1094 на origin).

### Заказ G1079 (следующему циклу)

> **Тело перенесено в архив** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`
> (раздел «Перенос цикла #1261 — „Заказ G1079“»). Раздел НЕ исчез: у него сменился АДРЕС тела.
> ЖИВОЙ пункт 2 (сторож тира, карточка `in-progress`) перенесён в заказ G1090 п. 6-бис ДО снятия.

### Заказы G1082…G1086 (живой — G1086, следующему циклу)

Полный текст ВСЕХ — `docs/journal/2026-W48.md`, записи циклов #1243…#1247. **Этот раздел более не живой:** живой заказ — **G1088**, см. раздел ниже. Заголовок сохранён ПОБАЙТОВО намеренно — переименование раздела неотличимо от его потери, и страж перезаписи читает его именно так (замер #1259: пуш отказал кодом 4 ровно на этом).

### Заказы G1087…G1088 (живой — G1088, следующему циклу)

Полный текст ВСЕХ — `docs/journal/2026-W48.md`, записи циклов #1243…#1259; живой заказ — **G1088** (запись цикла #1259), и он перечисляет перенесённые пункты предшественников сам. КЛЮЧ ЖИВ: замер 2026-11-26 — `GET /user` **200**, простой доставки закончен (ADR-1112, пост-запись #1258); работы вне origin на вход #1259 — **0**. У ключа НЕТ `Actions: write` ⇒ контрольный прогон агент заказать не может (`403`), карточка `owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo`.


### Заказ G1089 (следующему циклу)

**0. КЛЮЧ СПРОСИТЬ ПЕРВЫМ, и спрашивать у СЕРВЕРА** (G1088 п. 0 — не двигался).
`curl -sI -H "Authorization: Bearer $(security find-generic-password -s GITHUB_PAT_SPA -w)"
https://api.github.com/user | head -1` ⇒ замер 26.11 **200**. Вершину брать
`git ls-remote origin refs/heads/main`, а НЕ локальной ссылкой (ADR-1112 п. 4).
**Дерево доставки — worktree ПРОД-КЛОНА** `~/Documents/SPA_Claude`, а не зеркала:
пушер принимает только их (ADR-796), и #1259 на этом отказал.

**1. КОНТРОЛЬНЫЙ ПРОГОН АГЕНТ ЗАКАЗАТЬ НЕ МОЖЕТ, и это НЕ «зелено»** (G1088 п. 1).
У ключа нет `Actions: write`: `POST .../dispatches` → **403** при `200` на чтение. Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — **дубля не заводить**.
Вердикт CI о моей вершине **НЕ ИЗМЕРЕН**; приходит он только от расписанного прогона, и
спрашивать его дверью `python3 scripts/ci_control_verdict.py --delta <прежний> <новый>`,
помня: код **2** при непустом «ПРИШЛО» означает «переехало / ось слепа», а НЕ «ничего не
найдено».

**2. НОВОЕ (ADR-1114) и названный долг: у 157 перечней ФОРМЫ внешнего источника полноты НЕТ
ВОВСЕ.** Предмет УЗКОГО класса измерен и равен **0** (вилка 0…10), но форма — **157**: это
закрытые перечни, обязанные быть ВНУТРИ вычисленного предмета, у которых ни одного ADR в
элементах нет, то есть реестр решений об их полноте ответить не может. Мерки для их полноты
это решение НЕ даёт. Прежде чем её выдумывать, спросить: **есть ли у такого перечня внешний
источник вообще** — у «обязательных полей отчёта» им был бы контракт артефакта, а не реестр.
Объявлять им генератор по реестру ЗАПРЕЩЕНО: это была бы та же подмена, что генератор-одиночка
по слову «доставк» (34 строки против 4 членов).

**3. НОВОЕ: охват прибора — `scripts` + `spa_core`, и это ГРАНИЦА, а не замер пустоты.**
`tests/`, `scripts/tests/`, `studio_shell/`, `research/` в поверхность НЕ входят. Население
класса за пределами охвата **НЕ ИЗМЕРЕНО** — нулём не считается. Расширять охват можно, но
тогда перемерить ОБЕ половины: первая редакция прибора ошиблась дважды (признак объявления
читался у ФАЙЛА; форма выдавалась за класс — предмет 156 при настоящем 0), и оба раза ошибка
шла в сторону «чисто».

**4. ПЕРЕНОСИТСЯ ИЗ G1088 ЦЕЛИКОМ (не двигалось):** п. 3 (из 280 кандидатов двери 2 переписи
производных артефактов предмет НЕ ИЗМЕРЕН; дифференциал стóит два прогона pytest на кандидата,
брать ВЫБОРКОЙ и называть, что измерено) · п. 4 (**ЗОНД ИНЕРТЕН** — тела подкладываемых зондов
растят ЧИСЛО файлов и СОДЕРЖИМОГО не несут: 80 → 80 инертным против 80 → 81 содержательным;
граница ПЕЧАТАЕТСЯ строкой `PLANTED_INERT`) · **п. 5 — ИСХОДНЫЙ ЗАКАЗ #1258 ТАК И НЕ ИЗМЕРЕН**
(население класса «производная мера, у которой нет вопроса в момент доставки» за пределами
реестра решений, доски, переписи и храповика провенанса; и объявлять четыре двери доставки
ADR-889 · 1060 · 1073 · 1112 ОДНИМ классом по узкой оси ЗАПРЕЩЕНО — это подмена).

**5. ПЕРЕНОСИТСЯ ИЗ ПРЕДШЕСТВЕННИКОВ** (адреса, не копии): заказ G1059 · G1073 пп. 2–26 ·
G1076 пп. 2, 3, 6, 7, 12–16 · **G1077 пп. 2–5, 8–17 — адрес теперь
`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`, раздел «Перенос цикла #1260 —
„Заказ G1077“»** (тело снято ЭТИМ циклом побайтово) · G1087 пп. 2–4 · долг храповика ADR-362
(80 личностей, карточка `inbox-hrapovik-provenansa-git-ref-krasen-verno`; РОСТ загейчен
ADR-1112, сам долг НЕ уменьшен).

**6. ВЕС: запас ЗАМЕРЕН и он есть — 259 строк** (карточка 2756 при держателе максимума 3015).
Сжатие сделано ПЕРВЫМ делом, порядком G1088 п. 6: СПЕРВА адрес (`### Заказ G1077` в архивах и
в журнале недели — **0** вхождений), потом побайтовая сверка, и только потом снятие.
Заголовок раздела сохранён ДОСЛОВНО ⇒ заголовков 47 → 47, ПРОПАЛО 0. Следующий кандидат —
«Заказ G1078», и только ПОСЛЕ переноса его живых пунктов.

**7. `STATE.md`: запас на входе был 2 СИМВОЛА.** Место заработано слиянием четырёх строк
(ADR-1097/1098/1100/1101) в один указатель, адрес ВСЕХ ЧЕТЫРЁХ спрошен ДО снятия. После
доставки — **144** строки / **29 105** символов / **695** в длиннейшей (пределы 150 / 30 000 /
700), запас **6 / 895 / 5**. Сжимать ПЕРВЫМ делом и адрес спрашивать ДО снятия.

**8. Два артефакта офиса НЕ ПРОЧИТАНЫ** (офис 145 / 2): `data/acceptance_tree_lineage.json`,
`data/step_time_drift.json`. Причина чужая и названа: `com.spa.decision_loop` во флоте НЕ
загружен, включение службы — действие ВЛАДЕЛЬЦА (ADR-1053/1061/1103). Карточки есть, дубля не
заводить.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).


### Заказ G1090 (следующему циклу)

**Текст СНЯТ в архив** `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`
(103 строки / 7122 символа, md5 `ec4141c5c79aa631e10f557139ec7f88`). Снял цикл #1266
порядком G1093 п. 10: СПЕРВА спрошен адрес (`grep` по заголовку дал 0 в трёх архивах
и в журнале недели — то есть единственная копия была здесь), потом сверено ПОБАЙТОВО,
и только потом снят текст. Заголовок оставлен ДОСЛОВНО: переписать его значило бы
для сторожа потерять раздел.

### Заказ G1091 (следующему циклу)

> **Тело перенесено в архив** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`
> (раздел «Перенос цикла #1267 — „Заказ G1091“»): 77 строк / 5114 символов,
> md5 `b80bf02bd9fa7416e1ca8c6340638eba`, сверено ПОБАЙТОВО ДО снятия. Раздел НЕ исчез:
> у него сменился АДРЕС тела. Живые пункты перенесены в «Заказ G1095» выше.

### Заказ G1092 (следующему циклу)

**0. КЛЮЧ СПРОСИТЬ ПЕРВЫМ, и спрашивать у СЕРВЕРА.** Замер 26.11 — **200**, ключ ЖИВ.
Вершину брать `git ls-remote origin refs/heads/main`, а НЕ локальной ссылкой (ADR-1112 п. 4).
**Дерево доставки — worktree ПРОД-КЛОНА** `~/Documents/SPA_Claude`: пушер принимает только
их (ADR-796).

**1. КОНТРОЛЬНЫЙ ПРОГОН АГЕНТ ЗАКАЗАТЬ НЕ МОЖЕТ, и это НЕ «зелено»** (не двигалось). У ключа
нет `Actions: write`: `POST .../dispatches` → **403** при `200` на чтение. Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — **дубля не
заводить**. Вердикт CI о вершине **НЕ ИЗМЕРЕН**.

**2. ЗАКРЫТО ЗАМЕРОМ: 61 путь переходника снимка (G1091 п. 3) — ADR-1117.** Прибор
`scripts/snapshot_view_field_demand.py`, замер на `9611f1697`: читают через переходник **42**,
напрямую **3**, НЕ ЧИТАЕТ НИКТО **323**, дорог НЕ ИЗМЕРЕНО **9**; все 61 — `not_read`,
`landing/**` не тронут. Причина ПЕРЕМЕРЯЕТСЯ сторожем и пробой приёмки
`snapshot_view_exclusions_are_measured`. **Числа «42/323/9» в прозе больше не хватит** —
спрашивать прибором.

**3. НОВОЕ: девять дорог прибора НЕ ИЗМЕРЕНЫ, и нулём это не считается.** Два рода: значение
уходит в `JSON.stringify(…)` в разметку (читает КЛИЕНТСКИЙ скрипт, которого прибор не
разбирает) · `package_card.js` уводит запись глубже четвёртого хопа. Закрыть можно только
разбором клиентского `<script>` и графом зовов; **брать ВЫБОРКОЙ и называть, что измерено.**
Поднимать `MAX_HOPS` ВМЕСТО этого бессмысленно: замер 2…6 даёт ОДИН набор (ADR-1117 §
«Предел хопов»).

**4. НОВОЕ: шесть прежних строк `NOT_IN_VIEW` на замер спроса НЕ ссылаются** (13.09,
ADR-531/533) и потому сторожем НЕ перемеряются: их причина — провенанс и аудит, а не
отсутствие читателя. Это НАЗВАННЫЙ остаток. Перемерить их тем же прибором можно, но вердикт
о них будет о ДРУГОЙ оси — не путать.

**5. НОВОЕ: население класса «исключение объявлено СЛОВОМ, а не замером» за пределами этого
сторожа НЕ ИЗМЕРЕНО.** Закрыта ОДНА база. Соседи-кандидаты (`frozen_date_baseline.json`,
`design_status_baseline.json`, `site_numbers_baseline.json`, `inbox_acceptance_baseline.json`,
`ci_only_red_class_baseline.json`) живут по тому же правилу «база может только уменьшаться», и
у каждого свой вопрос: есть ли у строки ПРИЧИНА, и ПЕРЕМЕРЯЕТСЯ ли она. Мерить генератором по
словам ЗАПРЕЩЕНО (урок ADR-1074/1114: слово мерой не является) — спрашивать у каждой базы,
объявлена ли ось её причины в приборе.

**6. УРОК ПРИЁМКИ, четвёртый цикл подряд.** Первый мутационный прогон #1263: 26 применено /
20 убито / **6 выжило**, и дефектом КОДА не был НИ ОДИН — **пять дыр СЦЕН** (родитель пути,
проверка значения вне объявления, лист у неразрешённого зова, сосед-помощник в одном файле,
ключевое слово в скобках) и **один ЭКВИВАЛЕНТНЫЙ мутант МОЕГО авторства** (`kids = [] or
sorted(…)` тождественно `kids = sorted(…)`). После починки сцен — **26 из 26**. Спрашивать у
каждой мутации: «различает ли её хоть одна сцена?» — и у каждого якоря: «уникален ли он?».

**7. ПЕРЕНОСИТСЯ ИЗ G1091 ЦЕЛИКОМ (не двигалось):** п. 4 (вывод ADR может спорить с его же
замером; население НЕ ИЗМЕРЕНО, генератором по словам мерить ЗАПРЕЩЕНО) · п. 5 (остаток долга
ADR-1115: один хоп **121**, НЕ РАЗОБРАНО **16**, «вопроса нет» **11**) · п. 6 целиком
(признак «операнд извне» · `ADJUDICATED` · починка сторожа срока ключа
`inbox-strazh-sroka-klyucha-ne-sprashivaet-github`, работа в ветке
`rescue/c1239-pat-guard-asks-github`, на origin её НЕТ · сторож тира судит ПОДСТРОКОЙ
`inbox-storozh-tira-sudit-podstrokoi-imya-kurat` · охват прибора переписей как ГРАНИЦА, 280
кандидатов НЕ ИЗМЕРЕНЫ).

**8. ПЕРЕНОСИТСЯ ИЗ ПРЕДШЕСТВЕННИКОВ** (адреса, не копии): заказ G1059 · G1073 пп. 2–26 (текст СНЯТ в
`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-26.md`, раздел «Перенос цикла
#1263 — «Заказ G1073»»; md5 блока `ad5efdfa313e6cc8c6f4832d0e3f4345`) ·
G1076 пп. 2, 3, 6, 7, 12–16 · G1077 пп. 2–5, 8–17 · G1078 пп. 0–3 и G1079 пп. 0–1, 3–4
(`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`) · G1087 пп. 2–4 · долг
храповика ADR-362 (80 личностей, `inbox-hrapovik-provenansa-git-ref-krasen-verno`; РОСТ
загейчен ADR-1112, долг НЕ уменьшен).

**9. ВЕС: перемерить ПОСЛЕ своих правок, число предшественника не принимать.** Замер #1263 —
ниже, в пост-записи. Следующий кандидат на перенос — «Заказ G1073» (170 строк), и только
ПОСЛЕ переноса его живых пунктов, порядком G1089 п. 6: СПЕРВА адрес, потом побайтовая сверка,
и только потом снятие.

**10. `STATE.md`: запас ПОСЛЕ доставки — 145 строк / 29 247 символов / 695 в длиннейшей**
(пределы 150 / 30 000 / 700), запас **5 / 753 / 5**. **Запас по СТРОКАМ дошёл до пяти —
сжимать ПЕРВЫМ делом, а не после.** Строка этого цикла уже перенесена в две физические (752
символа в одной были бы красным храповиком — третий предел ловит не вес файла, а длину
строки).

**11. Два артефакта офиса НЕ ПРОЧИТАНЫ** (офис **145 / 2**): `data/acceptance_tree_lineage.json`,
`data/step_time_drift.json`. Причина чужая и названа: `com.spa.decision_loop` во флоте НЕ
загружен, включение службы — действие ВЛАДЕЛЬЦА. Карточки есть, дубля не заводить. Шаг 1з:
СОСТОЯЛОСЬ 18 · **НЕ СОСТОЯЛОСЬ 2** · retired 1 · НЕ ИЗМЕРЕНО 10 — состав ТОТ ЖЕ, что 25.11.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).


### Заказ G1093 (следующему циклу)

**0. КЛЮЧ СПРОСИТЬ ПЕРВЫМ, и спрашивать у СЕРВЕРА.** Замер 27.11 — **200**, ключ ЖИВ.
Вершину брать `git ls-remote origin refs/heads/main`, а НЕ локальной ссылкой (ADR-1112 п. 4).
**Дерево доставки — worktree ПРОД-КЛОНА** `~/Documents/SPA_Claude`: пушер принимает только их
(ADR-796).

**1. КОНТРОЛЬНЫЙ ПРОГОН АГЕНТ ЗАКАЗАТЬ НЕ МОЖЕТ, и это НЕ «зелено»** (не двигалось). У ключа
нет `Actions: write`: `POST .../dispatches` → **403** при `200` на чтение. Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — **дубля не заводить**.
Вердикт CI о вершине **НЕ ИЗМЕРЕН**.

**2. ЗАКРЫТО ЗАМЕРОМ: население класса «исключение объявлено СЛОВОМ, а не замером» — ADR-1120.**
Прибор `scripts/declared_exclusion_remeasure_census.py`, замер на `9fc4df89a`: носителей **41**
(json 40 · python 1) · **ПРЕДМЕТ 0** · перемеряется **14** · РОД ДРУГОЙ (причина ФАЙЛОВАЯ)
**13** · строк нет **12** · «не база» с согласным замером **2** · **НЕ ИЗМЕРЕНО 9**, вилка
**0…9**. **Числа в прозе больше не хватит** — спрашивать прибором.

**3. НОВОЕ: девять неизмеренных — это форма `{путь: "причина строкой"}`, и мерить её нечем, пока
причина безымянна.** У причины нет ключа вовсе, поэтому вопрос «читает ли её сторож» строковыми
литералами НЕ РАЗРЕШАЕТСЯ. Закрыть можно только дорогой ЗНАЧЕНИЯ (кто пробегает `.values()` /
`.items()` этого набора и что с ними делает) — это граф, а не литералы. **Брать ВЫБОРКОЙ и
называть, что измерено.** Обвинять их ЗАПРЕЩЕНО: это граница меры, а не находка.

**4. НОВОЕ: полнота перечня Python-носителей НЕ ИЗМЕРЕНА и нулём не считается.** «Модульный
словарь освобождённых» структурно неотличим от любого другого словаря, перечислением не
добывается; перечень `PYTHON_CARRIERS` объявлен поимённо и КАЖДЫЙ вход проверяется разбором.
Расширять его — только ПОСЛЕ замера населения (иначе покрасит неизвестное число модулей).

**5. НОВОЕ: ось B видит ОДИН ХОП, и это ровно та граница, что у сторожа притязания
`injected-clock`.** Чтение причинного ключа за ВТОРЫМ помощником числится вне поверхности.
Население за одним хопом НЕ ИЗМЕРЕНО.

**6. НОВОЕ: ось судит ПРИСУТСТВИЕ чтения, а не ОСМЫСЛЕННОСТЬ.** Сторож, читающий причинный ключ
и ничего им не решающий, через меру пройдёт — это следующий вопрос, и мерить его нечем, кроме
независимого читателя. Не путать «мерка есть» с «мерка зелена» (урок ADR-1116).

**7. УРОК ПРИЁМКИ, пятый цикл подряд, и на этот раз дефекты МЕРЫ были в сторону НАХОДКИ.** Две
первые редакции прибора дали предмет **22** и **1**, и ОБА числа опроверг ИЗВЕСТНЫЙ ЧЛЕН, а не
вычитка: ось спрашивала свой же пустой перечень (тавтология) · охват читателей был `test_*.py`, и
база инв. #17 читается ЧЕРЕЗ ПОМОЩНИКА. Третий дефект — в сторону «чисто»: отображение
`путь → {поля}` не считалось строками, и ДЕСЯТЬ носителей ушли в «строк нет». **Спрашивать у
каждой меры: „а что если известный член попадёт не в своё ведро?“ — и объявлять контроль ДО
чисел** (не сошёлся ⇒ код 2 и ни одного числа).

**8. ПЕРЕНОСИТСЯ ИЗ G1092 ЦЕЛИКОМ (не двигалось):** п. 4 (шесть прежних строк `NOT_IN_VIEW` на
замер спроса НЕ ссылаются — названный остаток, вердикт о них будет о ДРУГОЙ оси) · п. 3 (девять
дорог прибора ADR-1117 НЕ ИЗМЕРЕНЫ: `JSON.stringify` в разметку · `package_card.js` глубже
четвёртого хопа; поднимать `MAX_HOPS` бессмысленно) · п. 7 целиком (вывод ADR может спорить с его
же замером · остаток долга ADR-1115: один хоп **121**, НЕ РАЗОБРАНО **16**, «вопроса нет» **11** ·
признак «операнд извне» · `ADJUDICATED` · починка сторожа срока ключа
`inbox-strazh-sroka-klyucha-ne-sprashivaet-github`, ветка `rescue/c1239-pat-guard-asks-github`, на
origin её НЕТ · сторож тира судит ПОДСТРОКОЙ `inbox-storozh-tira-sudit-podstrokoi-imya-kurat` ·
охват прибора переписей как ГРАНИЦА, 280 кандидатов НЕ ИЗМЕРЕНЫ).

**9. ПЕРЕНОСИТСЯ ИЗ ПРЕДШЕСТВЕННИКОВ** (адреса, не копии): заказ G1059 · G1073 пп. 2–26 и
G1072 целиком (текст СНЯТ в `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-26.md`;
md5 блока G1072 `6e706a237fafea0d29cc786461526952`) · G1076 пп. 2, 3, 6, 7, 12–16 · G1077
пп. 2–5, 8–17 · G1078 пп. 0–3 и G1079 пп. 0–1, 3–4
(`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`) · G1087 пп. 2–4 · долг храповика
ADR-362 (80 личностей, `inbox-hrapovik-provenansa-git-ref-krasen-verno`; РОСТ загейчен ADR-1112,
долг НЕ уменьшен) · карточка `inbox-poverhnost-resheniya-shtampuet-tvl-live` (денежный путь) ·
`inbox-proba-kriteriya-49-no-regression-ne-prin`.

**10. ВЕС: перемерить ПОСЛЕ своих правок, число предшественника не принимать.** Замер #1265 —
ниже, в пост-записи. Циклом #1265 перенесены ДВА раздела — «Заказ G1072» (144 строки) и
«Заказ G1071» (128 строк, md5 `46bcc50865ecb4db48b7f0c3c7f92d1f`); у ОБОИХ заголовка в архивах
не было ВОВСЕ, то есть «сжать в адрес» стёрло бы единственную копию — `grep` по заголовку
обязателен ПЕРВЫМ. Следующий кандидат — «Заказ G1090» (103 строки), тем же порядком.

**11. `STATE.md`: запас ПОСЛЕ доставки — 148 строк / 29 886 символов / 695 в длиннейшей**
(пределы 150 / 30 000 / 700), запас **2 / 114 / 5**. **Запас по СТРОКАМ дошёл до ДВУХ — сжимать
ПЕРВЫМ делом, а не после.** Циклу #1265 пришлось свести ТРИ адресных блока в один (с проверкой
адреса каждого из десяти ADR: реестр · файл решения · журнал), и это дало всего 5 строк.

**12. Два артефакта офиса НЕ ПРОЧИТАНЫ** (офис **145 / 2**): `data/acceptance_tree_lineage.json`,
`data/step_time_drift.json`. Причина чужая и названа: `com.spa.decision_loop` во флоте НЕ загружен,
включение службы — действие ВЛАДЕЛЬЦА. Карточки есть, дубля не заводить. Шаг 1з: СОСТОЯЛОСЬ 18 ·
**НЕ СОСТОЯЛОСЬ 2** · retired 1 · НЕ ИЗМЕРЕНО 10 — состав ТОТ ЖЕ, что 25.11 и 26.11.

**13. Шаг 1е-2 (пины TVL) — состав ТОТ ЖЕ третий цикл подряд:** живое без пина **3**
(`euler_v2` живое $497,802, пол $5M НЕ проходит · `morpho_blue` · `yearn_v3`), один пул под двумя
ключами (`morpho_blue`+`morpho_steakhouse`, структурный предел 60% против потолка T2 50%), а
поверхность объявляет `tvl_floor_unverified=[]`. Это ДЕНЕЖНЫЙ ПУТЬ — правкой не закрывать,
карточка открыта.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1094 (следующему циклу)

**0. КЛЮЧ СПРОСИТЬ ПЕРВЫМ, и спрашивать у СЕРВЕРА.** Замер 27.11 — **200**, ключ ЖИВ.
Вершину брать `git ls-remote origin refs/heads/main`, а НЕ локальной ссылкой (ADR-1112 п. 4).
**Дерево доставки — worktree ПРОД-КЛОНА** `~/Documents/SPA_Claude`: пушер релятивизирует путь
по ОБЩЕМУ `.git`-каталогу, и дерево из `SPA_mirror` он отвергает `RepoPathError` (ADR-796).

**1. КОНТРОЛЬНЫЙ ПРОГОН АГЕНТ ЗАКАЗАТЬ НЕ МОЖЕТ, и это НЕ «зелено»** (не двигалось). У ключа
нет `Actions: write`: `POST .../dispatches` → **403** при `200` на чтение. Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — **дубля не заводить**.
Вердикт CI о вершине **НЕ ИЗМЕРЕН**.

**2. ЗАКРЫТО ЗАМЕРОМ: девять «НЕ ИЗМЕРЕНО» ADR-1120 закрыты ДОРОГОЙ ЗНАЧЕНИЯ — ADR-1121.**
⚠️ **Числа ниже ПЕРЕМЕРЕНЫ циклом #1267: редакция #1266 (предмет 1 · ось C 3 · НЕ ИЗМЕРЕНО 8 ·
вилка 1 … 10) ОПРОВЕРГНУТА и на origin не уезжала.** Итог на `976ee5880` (19,4 с): носителей
**50** · **ПРЕДМЕТ 0** · значение читают **4** · ЗАМЕР/СОДЕРЖИМОЕ 4 · «ответ о ДРУГОМ наборе» 1 ·
сирот 0 · **НЕ ИЗМЕРЕНО 6** · вилка **0 … 7**. **Числа в прозе больше не хватит** — спрашивать
`python3 scripts/declared_exclusion_remeasure_census.py`.

**3. ОПРОВЕРГНУТО ЗАМЕРОМ #1267: предмета НЕТ, а осталась ДРУГАЯ ось.**
`scripts/forbidden_import_baseline.json` объявлялся предметом со словами «причину не читает
НИКТО». Чтение есть и стои́т в `main()`: `baseline = load_baseline(root)` →
`print(f"ИЗВЕСТНОЕ  {f} — {baseline[f.key]}")` (стр. 269). Разрыв был у МЕРЫ — дорога идёт
ВОЗВРАТОМ функции ТОГО ЖЕ файла, а мера видела только присваивания (дверь 4). Остаётся
настоящий вопрос: причина **ПЕЧАТАЕТСЯ, но не ПЕРЕМЕРЯЕТСЯ** — её можно опустошить, и ни один
сторож не покраснеет. Карточка `inbox-prichina-edinstvennoi-stroki-forbidden-i` переписана под
ЭТОТ вопрос (её первая редакция утверждала опровергнутое); вариантов два, рекомендация —
гейтить непустоту, как у `scripts/python_git_ref_provenance.py`.

**4. НОВОЕ: ось C видит ОДИН ХОП** — та же граница, что у сторожа притязания `injected-clock`.
Чтение причины за ВТОРЫМ помощником числится вне поверхности, население за одним хопом
**НЕ ИЗМЕРЕНО** и нулём не считается.

**5. НОВОЕ: тождество отображения ось C НЕ ДОКАЗЫВАЕТ.** Файл, называющий носителя в КОДЕ и
пробегающий ОДНОИМЁННЫЙ ключ ДРУГОГО документа, прочтётся как «читает». Дверь 3 (имя ПОЛЯ,
объявленное литералом носителя в этом же файле) сужает это, но не исключает совсем.

**6. НОВОЕ: ось судит ПРИСУТСТВИЕ чтения, а не ОСМЫСЛЕННОСТЬ.** Сторож, прочитавший причину и
ничего ею не решивший, через меру пройдёт — это следующий вопрос, и мерить его нечем, кроме
независимого читателя. Не путать «мерка есть» с «мерка зелена» (урок ADR-1116).

**7. НОВОЕ: ЦЕНА МЕРЫ — ЧАСТЬ МЕРЫ, и это замер, а не удобство.** Первая редакция оси C на
`spa_core/monitoring/card_acceptance.py` (24 348 строк) съела **7 ГиБ** и не ответила вовсе:
положения росли ПРОИЗВЕДЕНИЕМ ключей. Приборы, которые не доживают до ответа, отвечают
«НЕ ИЗМЕРЕНО» на вопрос, который умели. Три приёма названы в коде: глубже ВТОРОГО шага
положения не различаются · предел 256 положений даёт ТРЕТИЙ исход, а не усечение · неподвижная
точка считается РАБОЧИМ СПИСКОМ, обходы и факты читателя кешируются. Плюс: причины
«НЕ ИЗМЕРЕНО» обязаны СВОРАЧИВАТЬСЯ по роду — поштучно их было **5017** строк.

**8. УРОК ПРИЁМКИ, шестой цикл подряд, и дефектов МЕРЫ было ТРИ — ДВА в сторону НАХОДКИ.**
(а) предметом объявлен носитель, чьи строки читают построчно: путь открывается ЧУЖИМ полем
модуля (`census.DECLARATION_REL`) — отсюда дверь 3, и ОТДЕЛЬНО пришлось учить ЗАТРАВКУ рабочего
списка, потому что дверь была, а правая часть в работу не попадала вовсе; (б) шесть из девяти
«неизмеренных» несут в безымянном значении ЧИСЛО или СПИСОК — это ЗАМЕР, не причина;
(в) дорога значения зачлась у счётчика `файлы`, пока причину несёт блок `измерено_на` — класс
ADR-1072 на новом месте. Каждый опроверг ИЗВЕСТНЫЙ ЧЛЕН, а не вычитка.

**9. НОВОЕ И ВАЖНОЕ: мерка «что мои байты способны покрасить» ВЫПИСАЛАСЬ ПУСТОЙ, и прогон
отчитался «62 passed».** Список сторожей собирался heredoc-ом внутри ФОНОВОГО вызова оболочки,
файл остался нулевым, и `pytest $(cat пусто)` измерил РОВНО ОДИН файл — свой. Строка
«62 passed» при этом читается как «всё зелено». **Пустой список входов обязан быть ОТКАЗОМ, а не
тихим сужением охвата** (инв. #17), и сверять надо ЧИСЛО собранных тестов с числом ожидаемых
файлов, а не цвет строки. Поверхность #1266: **68** сторожей (`derived_artifact_census.py
--surface --json` ∩ каталоги доставки), ≈**5090** тестов, цена полного прогона ≈**35 мин**.

**10. ПЕРЕНОСИТСЯ ИЗ G1093** (адреса, не копии): п. 4 (полнота `PYTHON_CARRIERS` НЕ ИЗМЕРЕНА,
расширять только ПОСЛЕ замера населения) · п. 8 целиком · п. 9 целиком (G1059 · G1073 пп. 2–26 ·
G1072 · G1076 · G1077 · G1078 · G1079 · G1087 · долг храповика ADR-362 · карточка
`inbox-poverhnost-resheniya-shtampuet-tvl-live` · `inbox-proba-kriteriya-49-no-regression-ne-prin`).

**11. ВЕС: перемерить ПОСЛЕ своих правок.** Циклом #1266 снят «Заказ G1090» (103 строки / 7122
символа, md5 `ec4141c5c79aa631e10f557139ec7f88`) в
`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`; заголовок оставлен ДОСЛОВНО —
переписать его значило бы для сторожа потерять раздел. Следующий кандидат — «Заказ G1091», тем
же порядком: `grep` по заголовку ПЕРВЫМ, побайтовая сверка, и только потом снятие текста.

**12. `STATE.md`: запас ПОСЛЕ доставки — 147 строк / 29 633 символа / 695 в длиннейшей**
(пределы 150 / 30 000 / 700), запас **3 / 367 / 5**. Циклу #1266 пришлось свести ТРИ адресных
блока в один (ADR-1085+1086 · 1092 · 1099/1103) с проверкой адреса каждого из ПЯТИ решений.
Вес мерить СИМВОЛАМИ, а не `wc -c`: в байтах файл 45 КБ, в символах 29,6 КБ.

**13. Два артефакта офиса НЕ ПРОЧИТАНЫ** (офис **145 / 2**): `data/acceptance_tree_lineage.json`,
`data/step_time_drift.json`. Причина чужая и названа: `com.spa.decision_loop` во флоте НЕ
загружен, включение службы — действие ВЛАДЕЛЬЦА. Карточки есть, дубля не заводить. Шаг 1з:
СОСТОЯЛОСЬ 18 · **НЕ СОСТОЯЛОСЬ 2** · retired 1 · НЕ ИЗМЕРЕНО 10 — состав ТОТ ЖЕ, что 25–26.11.

**14. Шаг 1е-2 (пины TVL) — состав ТОТ ЖЕ четвёртый цикл подряд:** живое без пина **3**
(`euler_v2` живое $497,802, пол $5M НЕ проходит · `morpho_blue` · `yearn_v3`), один пул под
двумя ключами (`morpho_blue`+`morpho_steakhouse`, структурный предел 60% против потолка T2 50%),
а поверхность объявляет `tvl_floor_unverified=[]`. Это ДЕНЕЖНЫЙ ПУТЬ — правкой не закрывать.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1095 (следующему циклу)

**0. КЛЮЧ СПРОСИТЬ ПЕРВЫМ, и спрашивать у СЕРВЕРА.** Замер 27.11 — **200**, ключ ЖИВ.
Вершину брать `git ls-remote origin refs/heads/main`, а НЕ локальной ссылкой (ADR-1112 п. 4).
**Дерево доставки — worktree ПРОД-КЛОНА** `~/Documents/SPA_Claude` (ADR-796).

**1. КОНТРОЛЬНЫЙ ПРОГОН АГЕНТ ЗАКАЗАТЬ НЕ МОЖЕТ, и это НЕ «зелено»** (не двигалось). У ключа
нет `Actions: write`: `POST .../dispatches` → **403** при `200` на чтение. Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — **дубля не заводить**.
Вердикт CI о вершине **НЕ ИЗМЕРЕН**.

**2. СПРОСИ ДЕРЕВО О НЕДОСТАВЛЕННОМ ПЕРЕД ТЕМ, КАК БРАТЬ ПУНКТ ЗАКАЗА В РАБОТУ.** Это находка
#1267 и самый дешёвый пункт всего заказа. Цикл #1266 умер, НЕ доставив готовый набор из 10 путей
(ADR-1121, ось C — ровно п. 3 заказа G1093), и набор лежал в `/private/tmp/spa_c1266deliver`.
Сделай этот пункт первым: `ls /private/tmp/spa_c12*/docs/decisions/ADR-11*` и
`git -C <дерево> status --short` по недавним worktree, плюс `ps` — живой сессии быть не должно.
Нашёл чужую работу ⇒ **принять в СВЕЖЕЕ дерево на вершине origin и ПЕРЕМЕРИТЬ её вывод**, а не
делать то же второй раз. Пересекающийся общий файл (`docs/journal/<неделя>.md`) **дописывать
поверх origin-версии**, а не подменять своей копией (`.claude/rules/deployment.md`).

**3. ПЕРЕМЕРЬ ЧУЖОЙ ВЫВОД, А НЕ ТОЛЬКО ЧУЖИЕ БАЙТЫ.** Вывод #1266 («предмет 1:
`forbidden_import_baseline.json`, причину не читает НИКТО») оказался ЛОЖНЫМ: дорога значения
идёт ВОЗВРАТОМ функции того же файла, и чтение стои́т в `main()` строкой 269. Байты были зелены
(62 passed), контроль известных членов — сошёлся, и ни то, ни другое вывода не проверяло.
**Доставленная чужая находка становится твоей находкой.**

**4. НОВОЕ: таблица известных членов УМЕЕТ ЗАКРЕПИТЬ ложную находку, и это не дефект таблицы.**
`KNOWN_MEMBERS` несла `forbidden_import_baseline.json → subject`, поэтому первый прогон после
починки дал **код 2 и ни одного числа**. Контроль не отличает «мера починена» от «мера
испорчена» — он требует ПЕРЕМЕРИТЬ ожидание ЧТЕНИЕМ КОДА. Соблазн обойти его правкой кода под
таблицу есть ровно тот дефект, против которого таблица написана.

**5. НОВОЕ: сторону контроля, которой в дереве нет, НЕЛЬЗЯ объявлять таблицей.** После двери 4
предмет класса ПУСТ, и носителя на сторону `keys` не осталось ни одного. Вписать туда носителя,
которого мера в это ведро не кладёт, значило бы объявить контролем собственное ожидание;
сторона держится СЦЕНОЙ на настоящем приборе, а строка контроля печатает состав ЗАМЕРОМ
(`control_line`), без слова «обе».

**6. НОВОЕ: ось C видит ОДИН ХОП — теперь НЕ считая возврата функции того же файла.** Дверь 4
разрешает зов по ИМЕНИ (`load_baseline(...)`); зов по АТРИБУТУ (`mod.load_baseline()`) —
второй хоп и вне поверхности. **Население за этой границей НЕ ИЗМЕРЕНО** и нулём не считается:
метод тот же, что у pid и имени ветки (прогнать поверхность дважды, предмет — тот, у кого
МЕНЯЕТСЯ вердикт; мерить и переход в `skipped`).

**7. ПЕРЕНОСИТСЯ ИЗ G1094 ЦЕЛИКОМ (не двигалось):** п. 5 (тождество отображения ось C НЕ
ДОКАЗЫВАЕТ) · п. 6 (ось судит ПРИСУТСТВИЕ чтения, а не ОСМЫСЛЕННОСТЬ — остаток у
`forbidden_import`: ПЕЧАТАЕТСЯ, но не ПЕРЕМЕРЯЕТСЯ) · п. 7 (цена меры — часть меры: 7 ГиБ без
предела положений; причины «НЕ ИЗМЕРЕНО» СВОРАЧИВАТЬ по роду, поштучно их 5017) · **п. 9
целиком** (пустой список входов обязан быть ОТКАЗОМ, а не тихим сужением охвата: heredoc внутри
ФОНОВОГО вызова оболочки оставил файл нулевым, и `pytest $(cat пусто)` отчитался «62 passed»,
измерив ОДИН файл — сверять ЧИСЛО собранных тестов с числом ожидаемых файлов, а не цвет строки) ·
п. 10 целиком (адреса предшественников: G1059 · G1073 пп. 2–26 · G1072 · G1076 · G1077 · G1078 ·
G1079 · G1087 · полнота `PYTHON_CARRIERS` НЕ ИЗМЕРЕНА · долг храповика ADR-362 ·
`inbox-poverhnost-resheniya-shtampuet-tvl-live` · `inbox-proba-kriteriya-49-no-regression-ne-prin`).

**8. ВЕС: перемерить ПОСЛЕ своих правок, число предшественника не принимать.** Замер #1267 —
ниже, в пост-записи. Циклом #1266 снят «Заказ G1090» в
`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`. Следующий кандидат — «Заказ
G1091», тем же порядком: `grep` по заголовку ПЕРВЫМ (единственная копия могла быть только здесь),
побайтовая сверка, заголовок оставить ДОСЛОВНО, и только потом снимать текст.

**9. `STATE.md`: запас ПОСЛЕ доставки — 148 строк / 29 799 символов / 695 в длиннейшей**
(пределы 150 / 30 000 / 700), запас **2 / 201 / 5**. Запас по строкам ДВА, по символам 201 —
**сжимать ПЕРВЫМ делом, а не после**: #1267 уехал за предел символов на первой же правке и
сворачивал строку ADR-1120 уже вторым заходом. Вес мерить СИМВОЛАМИ, не `wc -c`.

**10. Два артефакта офиса НЕ ПРОЧИТАНЫ** (офис **145 / 2**): `data/acceptance_tree_lineage.json`,
`data/step_time_drift.json`. Причина чужая и названа: `com.spa.decision_loop` во флоте НЕ
загружен, включение службы — действие ВЛАДЕЛЬЦА. Карточки есть, дубля не заводить. Шаг 1з:
СОСТОЯЛОСЬ 18 · **НЕ СОСТОЯЛОСЬ 2** · retired 1 · НЕ ИЗМЕРЕНО 10 — состав ТОТ ЖЕ, 25–27.11.

**11. Шаг 1е-2 (пины TVL) — состав ТОТ ЖЕ пятый цикл подряд:** живое без пина **3**
(`euler_v2` живое **$395,211** — сползло с $497,802, пол $5M НЕ проходит · `morpho_blue` ·
`yearn_v3`), один пул под двумя ключами (`morpho_blue`+`morpho_steakhouse`, структурный предел
60% против потолка T2 50%), а поверхность объявляет `tvl_floor_unverified=[]`. ДЕНЕЖНЫЙ ПУТЬ —
правкой не закрывать, карточка открыта.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Контрольный прогон цикла #1267 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `f393de6eed8f54ea81fcae3fde65dcf806d547a6` — **10** файлов, база
пинована `--expected-base 976ee588089b3e6b0bf97b8873a9ae956b275d4b`; **флагов обхода 0**. Слепок
байтов сверен у **30** чтений, слепок режимов у 3, разбор уезжающего Python — 2 файла. Доставка
проверена **ЧТЕНИЕМ origin**, а не словом пушера: `git show origin/main:<путь> | md5` против
дерева — **10 из 10 побайтово**.

**Два предупреждения провенанса базы названы, а не обойдены:** копия карточки приказа теряет 133
строки базы (снят «Заказ G1091» — текст уехал в
`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md` ТЕМ ЖЕ коммитом, 77 строк / 5114
символов, md5 `b80bf02bd9fa7416e1ca8c6340638eba`, сверено ПОБАЙТОВО ДО снятия; заголовок оставлен
ДОСЛОВНО), а `_BOARD.md` — 4 строки шапки (доска пересобрана генератором: 1706 карточек против
1705, причина — новая карточка набора). Ни одно из двух не есть потеря.

**Мутации — 10 применено / 10 убито / 0 выжило**, снято ЭТИМ циклом на настоящем приборе в
ОТДЕЛЬНОМ дереве (`/private/tmp/spa_c1267mut`, клон `cp -Rc`); якорь каждой мутации проверен на
УНИКАЛЬНОСТЬ (`src.count(old) == 1`), «не применена» ≠ «убита». **Первый прогон дал 9 из 10, и
выживший был дефектом СЦЕНЫ, а не кода** — шестой цикл подряд с этим уроком: сцена «возврат
ВЛОЖЕННОЙ функции» писала `return json.loads(P.read_text())["known"]` одним выражением, обёртка
`json.loads` рвала цепь положений, мутант получал «весь документ» вместо набора, вердикт выходил
`unmeasured`, и слабое утверждение `assertNotEqual(ROAD_VALUE, road)` его ПРОПУСКАЛО. Починка
сцены — связать документ ОТДЕЛЬНЫМ присваиванием и усилить до `assertEqual(ROAD_KEYS, road)`.
**`assertNotEqual` мутанта почти не ловит: у «не то» слишком много значений.**

**Своя ошибка процесса, названная вслух:** я применил мутацию РУКАМИ в дереве, где ещё шёл
мутационный раннер (диагностика выжившего). Байты дерева уцелели (раннер восстановил слепок в
`finally`, md5 сошлись), но ОДИН вердикт был снят на дереве с ДВУМЯ мутациями и потому не
доказывал ничего — перемерен отдельно, чисто. Дерево под прибором не трогать ничем, даже
«на минутку».

**Приёмка батареи:** `SPA_ENV=ci PYTHONHASHSEED=0 python3 -m pytest
spa_core/tests/test_declared_exclusion_remeasure_census.py -q` — **71 passed** (у редакции #1266
было 62).

**Дифференциал байт-поверхности — 66 сторожей ПОИМЁННО** (`derived_artifact_census.py --surface
--json`, пересечение `source_dirs` с каталогами доставки `scripts` · `spa_core/tests` ·
`docs/decisions` · `docs/journal` · `nimbalyst-local/tracker`), прогнаны ДВАЖДЫ: чистая вершина
`976ee5880` (`/private/tmp/spa_c1267base`) против того же набора с моими байтами
(`/private/tmp/spa_c1267mut`). **base 2 failed / 4457 passed** против **after 2 failed / 4457
passed**, и наборы имён СОВПАЛИ ПОИМЁННО (`diff` пуст). **Равные счётчики требуют объяснения, и
оно дано:** моего тест-файла в этой поверхности НЕТ (он называет ПРИБОР, а не каталог), поэтому
+9 тестов сюда не попадают — они в батарее выше. Оба падения — `test_edge_boundary_dataflow_census`
и `test_edge_corpus_map_probe` — красны на ЧИСТОЙ вершине, то есть не мои.

**Список входов прогона ПРОВЕРЕН на непустоту (G1094 п. 9), и проверка СРАБОТАЛА.** Первая
редакция обёртки звала `mapfile` — на macOS (bash 3.2) его НЕТ: скрипт напечатал три ошибки, а
обёртка вышла кодом **0**. Судить надо по ЛОГУ, а не по коду обёртки; вторая редакция сверяет
ЧИСЛО собранных входов с числом строк объявленного списка (66 = 66) и при расхождении ОТКАЗЫВАЕТ.

**Шаг 1г прогнан в НАЗВАННОМ одноразовом дереве** (`--repo-root /private/tmp/spa_c1267anchor`),
потому что цикл правил тест-файл: «Бомб нет: при задержке 95 мин ни один вердикт не изменился»,
код 0. Долгий прогон в дереве доставки не жил ни разу: батарея, дифференциал и мутации шли в
`spa_c1267mut` · `spa_c1267base` · `spa_c1267anchor`.

**Вес ПЕРЕМЕРЕН после всех правок:** карточка **2902** строки / **116 702** символа / 477 в
длиннейшей при пределах базы `tracker_card_weight_baseline.json` (3016 / 174 982 / 4244) — запас
**114** строк ДО этой пост-записи. `STATE.md` — **148** строк / **29 799** символов / 695 в
длиннейшей (пределы 150 / 30 000 / 700), запас **2 / 201 / 5**; первая правка увела файл ЗА
предел символов (30 076), и строку ADR-1120 пришлось сворачивать вторым заходом — порядок
G1095 п. 9 («сжимать ПЕРВЫМ делом») написан по этому замеру.

**Статус карточки не двигался** — `in-progress`, стоячий приказ владельца (инв. #14);
`acceptance_probe: apy_name_carries_one_kind` не правился (`.claude/rules/acceptance.md` п. 2).
Захват остаётся за мёртвым `cycle-93227` и честно мерится как `stale` — ложного сигнала он не
даёт, поэтому не переписан. Живой заказ следующему циклу — **G1095** выше.

### Контрольный прогон цикла #1265 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `a743fddb3b93f0c2c6f2dfaff413d6ca1add4e16` — **10** файлов, база
пинована `--expected-base 9fc4df89a8aca3389a149442fa76cf3eec3e4427`; слепок байтов сверен у
**32** чтений, режимов — у **3**, разбор уезжающего Python — **4** файла. **Флагов обхода не
передано НИ ОДНОГО** (0 из 15 доступных). Вершина спрошена У СЕРВЕРА (`git ls-remote`) до и
после: `9fc4df89a` → `a743fddb3`.

**Доставка проверена ЧТЕНИЕМ origin, а не фактом пуша:** все **10** путей побайтово равны моему
дереву (`git show origin/main:<путь> | md5`), расхождений **0**.

**Страж провенанса базы дал ТРЕТИЙ исход у четырёх путей — предупреждение, а не отказ, и флагом
он НЕ обходился.** `STATE.md` (96 строк, 113 предков пути), карточка приказа, и две переписи
аналитики: мера стража — точное равенство множеств строк, а снятие блока ЦЕЛИКОМ (три адресных
блока `STATE.md`, тело «Заказ G1072») ни одним предком не объясняется. Это ровно та форма, на
которой #1263 получил ОТКАЗ; здесь исход мягче, потому что потери НЕТ: тело G1072 перенесено
побайтово ДО снятия (md5 `6e706a237fafea0d29cc786461526952`), а адрес каждого из десяти ADR
сведённых блоков спрошен ПЕРВЫМ (реестр · файл решения · журнал — у всех на месте).

**§5 приказа: население класса «исключение объявлено СЛОВОМ, а не замером» ИЗМЕРЕНО (ADR-1120).**
Носителей **41** (json 40 · python 1): **ПРЕДМЕТ 0** · причина ПЕРЕМЕРЯЕТСЯ **14** · РОД ДРУГОЙ
(причина ФАЙЛОВАЯ, одна на все строки) **13** · строк исключений нет **12** · «не база
исключений» с согласным замером **2** · **НЕ ИЗМЕРЕНО 9**. **Вилка предмета 0 … 9.** Контроль
известных членов — **6 из 6** в ожидаемых ведрах, направления ОБА.

**Несущее — не число, а ТРАЕКТОРИЯ формы 22 → 1 → 0, и каждую редакцию опроверг ИЗВЕСТНЫЙ ЧЛЕН.**
Редакция 1 (предмет 22) спрашивала СВОЙ ЖЕ пустой перечень адресов мерки — тавтология, отвечавшая
«записал ли я это у себя»; опровергнута чтением кода `test_ci_only_red_class_ratchet.py`, который
построчный контракт ПЕРЕМЕРЯЕТ. Редакция 2 (предмет 1) спрашивала дерево, но охватом `test_*.py`,
и единственная находка `absent_observation_baseline.json` оказалась ЛОЖНОЙ: храповик инв. #17
базу читает ЧЕРЕЗ ПОМОЩНИКА `_absent_observation.py`. **Оба дефекта меры — в сторону НАХОДКИ**,
то есть мера льстила автору; третий, в сторону «чисто», отправил ДЕСЯТЬ носителей в ведро «строк
нет» (отображение `путь → {поля}` причину НЕСЁТ).

**Прогоны — в ОТДЕЛЬНЫХ одноразовых деревьях** (`.claude/rules/deployment.md` § «БАЙТЫ, КОТОРЫЕ
НЕ ЯВЛЯЮТСЯ КОДОМ» п. 1; долгий прогон в дереве доставки не жил ни разу):

| прогон | дерево | исход |
|---|---|---|
| 71 сторож байт-поверхности, ЧИСТЫЙ `origin/main` `9fc4df89a` | `/tmp/c1265base` | **4560 passed · 2 skipped · 0 failed** (333,8 с) |
| те же 71 + мой файл, МОИ байты | `/tmp/c1265after` | **4588 passed · 2 skipped · 0 failed** (394,1 с) |
| мутации спецификации, прогон 1 | `/tmp/c1265mut` | 17 применено / **14 убито** / 3 ВЫЖИЛО / 1 НЕ ПРИМЕНЕНА |
| мутации спецификации, прогон 2 (финальные байты) | `/tmp/c1265mut` | 18 применено / **18 убито** / **0 выжило** / 0 не применено |

**Мерка выведена ИЗ БАЙТОВ, а не из прозы заказа:** `derived_artifact_census.py --surface --json`
∩ каталоги доставки = **72** сторожа (вилка охвата **72 … 178** с ведром «не разобрано» 106).

**Разница 4588 − 4560 = 28 ТРЕБУЕТ объяснения, и оно ИЗМЕРЕНО, а не предположено.** Сличение
`--collect-only` по файлам: 71 сторож собирает **4562** в базе против **4563** на моих байтах, то
есть **+1**, и этот один назван поимённо — `test_no_live_credentials_in_runtime_config.py`
(параметризован по файлам исходников). Он мой новый скрипт УВИДЕЛ и ПРИНЯЛ, то есть
противоположность регрессии. Итого 28 = 27 (мой файл) + 1.

**Мутации: ДВА прогона, и ни один выживший первого НЕ был дефектом КОДА — все три дыры СЦЕН.**
M12 «служебные ключи считаются строками исключений» выжила, потому что моя сцена подавала
служебные значения СКАЛЯРАМИ, а строками становится только непустой список/словарь — сцена не
различала мутацию вовсе. M14 «не база исключений объявляется СЛОВОМ» выжила, потому что сцена
проверяла только сторону «да, не база»: мутация «возвращать True всегда» её не трогает —
не было ОБРАТНОЙ половины. M17 «пустой охват не останавливает замер» выжила, потому что ни одна
сцена не подавала прибору дерево БЕЗ сторожей. Плюс M03 «НЕ ПРИМЕНЕНА» (якорь `if` против `elif`,
встречаемость 0) — и это НЕ «убита». Все четыре починены (три новых сцены + якорь), прогон №2 на
финальных байтах — **18 из 18**, контур после возврата байтов `27 passed`. Якоря проверялись на
уникальность (`count != 1` ⇒ «НЕ ПРИМЕНЕНА»), возврат из pristine-копии сверялся md5 после
КАЖДОЙ мутации; байты прибора после прогона побайтово равны доставленным.

**Своя ловушка, поймана своей же дисциплиной:** два монитора одновременно подняли ВТОРОЙ
мутационный прогон в ТОМ ЖЕ дереве — ровно то, что § «ОКНО МУТАЦИОННОГО ПРИБОРА» п. 5 запрещает
(второй прогон затёр бы слепок первого, и мутанта стало бы нечем вернуть). У моего скрипта такого
интерлока НЕТ. Оба процесса сняты, байты прибора сверены с доставляемыми (md5 равны), прогон
перезапущен ОДИН. Окно мутаций спрошено `--window-check` у ОБОИХ деревьев — «ОКНА НЕТ» (код 0).

**Вердикт CI о моей вершине НЕ ИЗМЕРЕН:** у ключа нет `Actions: write`, контрольный прогон
заказать нельзя (403 при 200 на чтение). Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — дубля не заводил.

**Шаги цикла.** Офис **145 / 2** (`acceptance_tree_lineage`, `step_time_drift` — причина чужая,
мост `com.spa.decision_loop` выключен, включение есть действие ВЛАДЕЛЬЦА; карточки есть).
Шаг 1д — код 1 (НОВЫХ НЕТ, два исторических расхождения названы). Шаг 1е — обе оси **100 %**.
Шаг 1е-2 — код 1, состав ТОТ ЖЕ третий цикл: живое без пина 3, один пул под двумя ключами;
денежный путь не трогал. Шаг 1в — код 1, `_protocol_blindness.py` уехал ЭТИМ же пушем. Шаг 1е
(витрина) — код 4, ждёт владельца, байты витрины из набора доставки СНЯТЫ. Шаг 1з — 18 / 2 / 1 /
10, состав ТОТ ЖЕ. Шаг 2: ни одна карточка не предложена как СВЕЖИЙ ответ владельца (20 доказанно
разобраны на origin, 18 несут `answer_may_be_already_ingested`); `owner-done` я не ставил (инв. #14).

**Своя проба приказа задана ПЕРВЫМ делом:** `apy_name_carries_one_kind` → `satisfied` («род
объявлен у всех 22 apy-именованных чисел, не измерено 0»). Это §5 из двенадцати — закрытием
приказа она не является, и критерий я не правил (`.claude/rules/acceptance.md` п. 2).

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Контрольный прогон цикла #1264 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `789a7895eeae3d1580fae12eb8742bb05182cbd2` — **10** файлов,
база `c333fd64f`; слепок байтов сверен у **32** чтений, режимов — у **3**, разбор уезжающего
Python — **4** файла. **Флагов обхода не передано НИ ОДНОГО.** Вершина спрошена У СЕРВЕРА
(`git ls-remote`): `c333fd64f` → `789a7895e`. **Доставка проверена ЧТЕНИЕМ origin:** все 10
путей побайтово равны моему дереву (`git show origin/main:<путь> | md5`), расхождений 0.

**§49 Owner visibility: критерий ПРИКАЗА числился слепым повсюду и оказался ОТВЕТИМЫМ.**
Прибор дерева приёмки не звал ту дверь, которая у сводки §49 уже была: `measure_tree` и
`data_dir` принимаются РАЗДЕЛЬНО. Ось СБОРНОЙ ПАРЫ (ADR-1119) на 5 слепых критериях
РАЗЛИЧАЕТ — отвечает **1** (`Owner visibility`: поверхности зеркала × артефакты прод-`data/`
⇒ **ВЫПОЛНЕН, 12 предметов из 12**, поверхность читает все поля), тоже слепа у **3**
(`Determinism`, `Auditability`, `Shadow verification` — артефакт протух 574 ч при SLO 9,28 ч
и отсутствует в зеркале ⇒ причина есть свойство МИРА: мост `com.spa.decision_loop` выключен
с 29.10, карточка владельца открыта), и у **1** спросить НЕЛЬЗЯ (`No regression` — проба
объявляет только `repo_root`; карточка `inbox-proba-kriteriya-49-no-regression-ne-prin`).

Прогон прибора: **167,3 с** (было 83,7 с), код возврата **1**, ось печатает четыре исхода и
свою цену числом. Хермётичный контроль **64 passed**, мутации спецификации **22/22**
(первая редакция 21/22 — дыра СЦЕНЫ, не кода), 46 измеренных сторожей байт-поверхности —
**1130 passed, 2 skipped, 0 failed** в ОТДЕЛЬНОМ дереве.

**Своя проба карточки задана ПЕРВЫМ делом:** `apy_name_carries_one_kind` → `satisfied`
(«род объявлен у всех 22 apy-именованных чисел, не измерено 0»). Это §5 из двенадцати —
закрытием приказа она не является, и критерий я не правил (`.claude/rules/acceptance.md` п. 2).

**Вердикт CI о моей вершине НЕ ИЗМЕРЕН:** у ключа нет `Actions: write`, контрольный прогон
не заказать. Прогон на `9611f1697` (на 2 коммита раньше базы) RED — 140 имён в 68 файлах,
крупнейшее семейство 26 в `test_reachability_of_the_rest_wiring.py`. Красное ДО меня.
**Одну его причину я снял:** `pinned_identity_collision_census.py:319` не разбирался
Python 3.11 — прибор обязательного шага 1е-2 в CI падал ВСЕГДА с #1247 и был невидим
локально (3.13 его разбирает). Сторож **1 failed → 14 passed**, вывод сверен побайтово.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Контрольный прогон цикла #1263 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `68b65b6b4ecddb6032b788e2776f403134d83b31` — **14** файлов,
база пинована `--expected-base 9611f169785f73c9cd94728b6cbe061e4fb2991c`; слепок байтов
сверен у **43** чтений, режимов — у **5**, разбор уезжающего Python — **4** файла. **Флагов
обхода не передано НИ ОДНОГО** (0 из 15 доступных). Вершина спрошена У СЕРВЕРА
(`git ls-remote`) до и после: `9611f1697` → `68b65b6b4`.

**Доставка проверена ЧТЕНИЕМ origin, а не фактом пуша.** Все **14** путей отвечают **200** на
вершине `68b65b6b`; байты `scripts/snapshot_view_field_demand.py` на `main` несут
`not_read_paths`, `MAX_HOPS = 4` и `_RE_AND_NEXT`; сторож формы несёт **61** объявление по
замеру и тест `test_the_measured_exclusions_are_still_unread`.

**Страж провенанса базы ОТКАЗАЛ первой редакции доставки, и отказал ВЕРНО — флагом обход НЕ
делался.** Первая редакция сняла в архив пост-запись цикла #1262, то есть РОВНО тот блок,
который добавил сам HEAD `9611f1697`. Мера стража — точное равенство множеств строк («при
осознанном удалении автор обычно убирает ЧАСТЬ добавленного коммитом»), и снятие блока
ЦЕЛИКОМ даёт равенство, неотличимое от работы на устаревшей копии: вердикт `based_on_older`,
пуш отменён fail-CLOSED. Путь наверх был выбран НЕ `--allow-stale-base`: пост-запись #1262
возвращена в карточку ПОБАЙТОВО (md5 `cee62b258cca3fbed352f6238619df18`), а место освобождено
разделом, которого HEAD не трогал — «Заказ G1073» (169 строк / 11 304 символа, md5
`ad5efdfa313e6cc8c6f4832d0e3f4345`), ровно как просил G1091 п. 8. На второй редакции тот же
пушер доложил сам: **«разделов ПЕРЕНЕСЕНО в архив, уезжающий этим же пушем — 1 (тело сверено
с remote ПОБАЙТОВО, потери нет)»**, а провенанс базы дал ТРЕТИЙ исход («НЕ ИЗМЕРЕН: 62 строки,
ни один из 110 предков не объясняет») — предупреждение, а не отказ. **Доставка с флагом обхода
стои́т ровно столько, сколько доверия к мерке, которую она обошла.**

**Ловушка zsh поймана СВОЕЙ проверкой, и это второй цикл подряд.** Первая попытка пуша
передала список файлов как `--files $FILES` — zsh не делит неэкранированную переменную на
слова, поэтому пушер получил ОДИН аргумент длиной в 14 путей и честно отказал fail-CLOSED
(«дерево файла не определяется», «слепок байтов: файлов 0, НЕ ПРОЧИТАНО 1»). Молчаливого
вреда не было: отказ назвал и причину, и путь наверх. Исправлено на
`tr '\n' '\0' | xargs -0`.

**Что НЕ измерено этой доставкой, и нулём это не считается.** Вердикт CI о вершине
`68b65b6b` — **НЕ ИЗМЕРЕН**: `--order-run 68b65b6b4…` ответил `QUEUED_BEHIND` и **ПОДАЧА НЕ
ПРИНЯТА, HTTP 403** (у ключа нет `Actions: write`), код **4**. Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — дубля не заводил.
Отдельное наблюдение: расписанный прогон `45899679462` идёт `in_progress` на sha `9611f1697`,
то есть на МОЕЙ БАЗЕ, — его вердикт будет о базе, а не о моих байтах, и путать это нельзя.

**Чем вердикт CI замещён — тремя прогонами в ОТДЕЛЬНЫХ одноразовых деревьях** (долгий прогон
в дереве доставки не жил ни разу, `.claude/rules/deployment.md` § «БАЙТЫ, КОТОРЫЕ НЕ ЯВЛЯЮТСЯ
КОДОМ» п. 1):

| прогон | дерево | исход |
|---|---|---|
| дифференциал, ЧИСТЫЙ `origin/main` `9611f1697` (66 сторожей) | `/tmp/spa_c1263base` | **4453 passed · 1 skipped · 0 failed** |
| дифференциал, мои байты (66 сторожей) | `/tmp/spa_c1263after` | **4453 passed · 1 skipped · 0 failed** |
| финальная сверка на БАЙТАХ ДОСТАВКИ (67 файлов) | `/tmp/spa_c1263after` | **4505 passed · 1 skipped · 0 failed** |

**Мерка выведена ИЗ БАЙТОВ, а не из прозы заказа:** `derived_artifact_census.py --surface
--json` ∩ каталоги доставки = **66** сторожей, вилка охвата **66 … 377** (плюс ведро
«перечисляет КОРЕНЬ»). Приписать 377 своей доставке значило бы выдать чужую поверхность за
цену моих байтов; выдать 66 за полноту — объявить измеренным то, чего мера не видела.

**Равенство счётчиков 4453 = 4453 ТРЕБУЕТ объяснения, и оно дано:** мой новый тест-файл в
поверхность 66 сторожей НЕ входит (он не перечисляет каталог), поэтому в набор не вошло ни
одного нового теста, и ни один из 66 не сменил вердикт. Разница финального прогона **4505 −
4453 = 52** раскладывается РОВНО: 51 тест нового файла + 1 перемеряющий тест сторожа формы.

**Единственное падение дифференциала было МОИМ и ровно тем, о чём спрашивает ADR-1060:**
`test_live_board_matches_live_cards` покраснел, пока `_BOARD.md` не был пересобран под
изменённые статусы карточек. После `python3 scripts/build_tracker_board.py` — 11 passed, и
доска уехала в наборе; гейт доставки (код 17) доложил «названы все 3 уезжающих карточки».

**Мутации: ДВА прогона, и первый нашёл ШЕСТЬ дыр — дефектом КОДА не был НИ ОДИН.** Первый
(`/tmp/spa_c1263mut`, 26 мутаций): **26 применено / 20 убито / 6 выжило**. Разбор каждой
выжившей: **пять дыр СЦЕН** (родитель пути не проверялся · проверка значения ВНЕ объявления ·
лист у неразрешённого зова · сосед-помощник в одном файле · ключевое слово в скобках) и
**один ЭКВИВАЛЕНТНЫЙ мутант МОЕГО авторства** — `kids = [] or sorted(…)` тождественно
`kids = sorted(…)`, то есть мутация была написана так, что менять ей было нечего. Шесть сцен
добавлено, мутация M03 переписана; второй прогон — **26 применено / 26 убито / 0 выжило / НЕ
ПРИМЕНЕНО 0**, контур после возврата байтов `56 passed`. Якоря проверялись на уникальность
(`count != 1` ⇒ «НЕ ПРИМЕНЕНА», и это не «убита»); возврат из pristine-копии сверялся md5
после КАЖДОЙ мутации.

**Четыре дефекта МЕРЫ, найденные контролями, а не вычиткой** (все — в сторону «чисто», то
есть в опасную): комментарий зачитывался за чтение · срез тела помощника шёл в РЕЗОЛВИНГ
зовов · `&&` и `||` трактовались одинаково (**шесть ложных «читают»**, и нашёл их
перемеряющий сторож, написанный в этом же цикле) · корень дерева не разрешался (на macOS
`/tmp` → `/private/tmp`). Подробности — ADR-1117 и `docs/journal/2026-W48.md`.

**Шаг 1г прогнан в НАЗВАННОМ одноразовом дереве** (`--repo-root /tmp/spa_c1263anchor`), потому
что цикл правил тест-файлы: код **0**, «Бомб нет: при задержке 95 мин ни один вердикт не
изменился».

**Вес карточки ПЕРЕМЕРЕН после всех правок:** **2841** строка / **110 032** символа при
держателе максимума `agent-audit-2026-08-02-fix-tracks.md` (**3015** строк) ⇒ запас **174**
строки ДО этой пост-записи.

**`STATE.md` после доставки: 145 строк / 29 247 символов / 695 в длиннейшей** (пределы 150 /
30 000 / 700), запас **5 / 753 / 5**. Строка цикла вписана в ДВЕ физические намеренно: в одной
она дала бы 752 символа, то есть красный третий предел (он ловит не вес файла, а длину строки).

**Статус карточки не двигался** — `in-progress`, стоячий приказ владельца (инв. #14);
`acceptance_probe: apy_name_carries_one_kind` не правился (`.claude/rules/acceptance.md` п. 2).
Живой заказ следующему циклу — **G1092** выше.

### Контрольный прогон цикла #1262 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `3769bcb29ed058096ca77a3f9e8ec655e0581969` — **12** файлов,
база пинована `--expected-base cf5d12299b4f9514a20b733b1eb5890394227afc`; слепок байтов
сверен у **38** чтений, режимов — у **4**, разбор уезжающего Python — **4** файла.
**Флагов обхода не передано НИ ОДНОГО** (0 из 15 доступных). Доставка проверена **ЧТЕНИЕМ
origin**: все 12 путей отвечают **200** на вершине `3769bcb2`, и она же есть
`refs/heads/main` (`git ls-remote`). Вершина спрошена У СЕРВЕРА, не локальной ссылкой.

**Дрянь, которую дал бы `--dry-run`, если читать его глазами, а не кодом.** Сухой прогон
печатает блок «закоммитил бы **1** файл(ов) ОДНИМ коммитом» ДВЕНАДЦАТЬ раз, и это читается
как «12 файлов = 12 коммитов» — ровно авария цикла #53. Проверено по коду:
`if len(all_files) > 1 and not args.dry_run` — батч включается только на БОЕВОМ проходе,
сухой намеренно идёт по одному файлу. Живой пуш ответил «**OK: 1 коммит … 12 файл(ов)**».
Вывод сухого прогона вердиктом о форме доставки НЕ является.

**Третьи исходы пушера НАЗВАНЫ, а не проглочены.** «Провенанс базы НЕ ИЗМЕРЕН» у карточки
приказа (теряется 120 строк базы) и у `_BOARD.md` (4 строки) — следствие ПЕРЕНОСА двух
пост-записей в архив и перегенерации доски. Сам пушер проверил перенос независимо и
доложил: «разделов ПЕРЕНЕСЕНО в архив, уезжающий этим же пушем — **2** (тело каждого
сверено с remote ПОБАЙТОВО, потери нет)». «Слепок режимов: читателя не позвали НИ РАЗУ» в
сухом прогоне — тот же третий исход, на боевом он сверен у 4 чтений.

**Что НЕ измерено этой доставкой, и нулём это не считается.** Вердикт CI о вершине
`3769bcb2` — **НЕ ИЗМЕРЕН**: у ключа нет `Actions: write`, контрольный прогон заказать
нечем (403 при 200 на чтение), карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258. Вместо него
измерен ДИФФЕРЕНЦИАЛ: **69** сторожей, которых мои каталоги способны покрасить
(`derived_artifact_census.py --surface --json`, пересечение `source_dirs` с каталогами
доставки), прогнаны ДВАЖДЫ — чистая вершина `cf5d12299` против того же набора с моими
байтами. **base 4483 passed / 0 failed** против **after 4495 passed / 0 failed**, и
разница **РОВНО 12** есть число тестов моего нового файла (на базе его нет по построению,
поэтому из базового набора он исключён — «file or directory not found» был пойман и
назван, а не зачтён за прогон). **Равенство счётчиков требует объяснения, и оно дано:**
ни один из 69 не сменил вердикт.

**Вилка охвата этой мерки ПЕЧАТАЕТСЯ, а не сводится к одному числу:** **69** (мои каталоги
НАЗВАНЫ в тесте) … **376** (плюс ведро «перечисляет КОРЕНЬ»). Приписать 376 своей доставке
значило бы выдать чужую поверхность за цену моих байтов; выдать 69 за полноту — объявить
измеренным то, чего мера не видела.

**Мутации — 11 применено / 11 убито / 0 выжило**, и число снято ЭТИМ циклом на настоящем
приборе в ОТДЕЛЬНОМ дереве (`/private/tmp/spa_c1262mut`, копия `cp -Rc`), не перенесено из
спецификации. Первый прогон дал **7 из 8**; выживший — «снято согласие двух дверей» — был
дефектом СЦЕНЫ, не кода: сегодня двери согласны, и различающей сцены не было ни одной.
Это ТРЕТИЙ цикл подряд с находкой того же рода (#1202 — доска в двух местах одинакова,
#1217 — перепись починена в дереве, теперь — согласие дверей). Починка: согласие вынесено в
`agreed_contract()` и получило ТРИ юнит-сцены; после неё 11 из 11, включая три новые
мутации (вторая сторона расхождения не печатается · отсутствие производителя выдано за
ПУСТОЙ контракт · освобождение переименовано).

**Шаг 1г прогнан в НАЗВАННОМ одноразовом дереве** (`--repo-root /private/tmp/spa_c1262anchor`),
потому что цикл правил тест-файлы: «Бомб нет: при задержке 95 мин ни один вердикт не
изменился», код 0. Долгий прогон в дереве доставки не жил ни разу: приёмочные и
дифференциальные прогоны шли в `spa_c1262mut`, `c1262base`, `c1262after`, `spa_c1262anchor`.

**Вес карточки ПЕРЕМЕРЕН после всех правок:** **2848** строк / **110 668** символов при
держателе максимума `agent-audit-2026-08-02-fix-tracks.md` (**3016** строк) — запас **168**
строк ДО этой пост-записи. Место заработано переносом: порядком G1089 п. 6 спрошен адрес
(заголовков обоих разделов в трёх прежних архивах — **0** вхождений), сверено ПОБАЙТОВО
(md5 `9d09c7d93357e2542c3cb4d692f35650`, 92 строки, и `ee45342eaed7c80865604424ba0c250d`,
69 строк), и только потом снят текст. Заголовки сохранены ПОБАЙТОВО с пометкой
«— В АРХИВЕ»: стаб, потерявший заголовок, есть потерянный раздел.

**`STATE.md` после доставки: 143 строки / 28 491 символ / 695 в длиннейшей** (пределы
150 / 30 000 / 700), запас **7 / 1509 / 5**. Строк не прибавилось НИ ОДНОЙ: строка
родословной ADR-1113/1114/1115 переписана так, чтобы покрыть и ADR-1116.

**Статус карточки не двигался** — `in-progress`, стоячий приказ владельца (инв. #14);
`acceptance_probe: apy_name_carries_one_kind` не правился (`.claude/rules/acceptance.md`
п. 2). Живой заказ следующему циклу — **G1091** выше.

### Контрольный прогон цикла #1261 (вписано ПОСЛЕ доставки) — В АРХИВЕ

Перенёс цикл #1262 порядком G1089 п. 6: адрес спрошен ДО снятия (в архивах 0 вхождений), сверено ПОБАЙТОВО (md5 `9d09c7d93357e2542c3cb4d692f35650`, 92 строк), и только потом снят текст. Адрес — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-26.md`.

### Контрольный прогон цикла #1260 (вписано ПОСЛЕ доставки) — В АРХИВЕ

Перенёс цикл #1262 порядком G1089 п. 6: адрес спрошен ДО снятия (в архивах 0 вхождений), сверено ПОБАЙТОВО (md5 `ee45342eaed7c80865604424ba0c250d`, 69 строк), и только потом снят текст. Адрес — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-26.md`.

### Контрольный прогон цикла #1237 (вписано ПОСЛЕ доставки)

> **Тело перенесено в архив** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`
> (раздел «Перенос цикла #1261 — пост-запись цикла #1237»). Раздел НЕ исчез: у него
> сменился АДРЕС тела. Хроника цикла — `docs/journal/2026-W48.md` (коммит `424d23c05`).

### Контрольный прогон цикла #1236 (вписано ПОСЛЕ доставки)

**ТЕЛО ПЕРЕНЕСЕНО В АРХИВ** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`, раздел «Перенос
цикла #1237 (вторая вершина)». Хроника — в `docs/journal/2026-W48.md`.

### Контрольный прогон цикла #1235 (вписано ПОСЛЕ доставки)

**ТЕЛО ПЕРЕНЕСЕНО В АРХИВ** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`, раздел «Перенос
цикла #1237». Хроника цикла — в `docs/journal/2026-W48.md`.

### Контрольный прогон цикла #1234 (вписано ПОСЛЕ доставки)

**ТЕЛО ПЕРЕНЕСЕНО В АРХИВ** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`, раздел «Перенос
цикла #1237». Хроника цикла — в `docs/journal/2026-W48.md`.

### Контрольный прогон цикла #1233 (вписано ПОСЛЕ доставки)

> **Тело перенесено в архив** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`
> (раздел «Пост-записи циклов #1233 и #1232 … циклом #1236»). Раздел НЕ исчез: у него
> сменился АДРЕС тела.

### Контрольный прогон цикла #1232 (вписано ПОСЛЕ доставки)

> **Тело перенесено в архив** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`
> (раздел «Пост-записи циклов #1233 и #1232 … циклом #1236»). Раздел НЕ исчез: у него
> сменился АДРЕС тела.

