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

**0. Заказ G1059 ОСТАЁТСЯ ЖИВЫМ ЦЕЛИКОМ** (его пп. 1–3, 5, 7–10 не исполнял никто из
#1218…#1231). **Заказ G1070 исполнен в пп. 1, 3 и 7**; его пп. 2, 4–6, 8–20 перенесены
ниже без правок смысла.

**1. Вердикт контрольного прогона цикла #1231 — ПРОЧИТАТЬ ПЕРВЫМ ДЕЛОМ.** Номер и ПОЛНАЯ
sha — в пост-записи ниже. База сравнения — **`45330264266`** (**60** имён, мой замер).
Команда одна, и ось шарда она спрашивает САМА: `python3 scripts/ci_control_verdict.py
--delta 45330264266 <новый>`. Код **2** при непустом «ПРИШЛО» означает «переехало / ось
слепа», а НЕ «ничего не найдено». Перед сличением спроси у API, нет ли на той же базе
прогона НОВЕЕ.

**2. ПЕРЕНЕСЁН из G1070 п. 2: ЗАКАЗЫВАТЬ ПРОГОН ДВЕРЬЮ, А НЕ `curl`-ом** (ADR-1083).
`python3 scripts/ci_control_verdict.py --order-run <ПОЛНАЯ 40-hex sha>` сам спрашивает
занятость группы `ci-control` ДО подачи и перечитывает живость заказа после;
`--order-check <sha>` — только спросить. Коды: **0** заказан и жив · **1** подан,
личность/живость НЕ ПОДТВЕРЖДЕНА · **2** НЕ ИЗМЕРЕНО, заказ не подавался · **3** ОТКАЗ ·
**4** подача не принята API. Заказывать ОДИН раз, на ПОСЛЕДНЕЙ вершине доставки. Такт
расписанного прогона дверь называет САМА (`next_cron_moment`) — число из прозы НЕ
перепечатывать.

**3. ЗАПАС `STATE.md` СНОВА 18 СИМВОЛОВ (из 30 000). Сжимать придётся ДО правки.**
Строк 149 / символов 29 982 / 695 в длиннейшей. #1231 заработал место слиянием ДВУХ
строк-указателей старше двух недель и потратил его целиком на свою строку. Ближайшие
кандидаты — строки `2026-11-15…17 · ADR-1020…1045` (658 симв.) и
`2026-11-18 · ADR-1048…1051`: обе уже указатели, но несут факты «помнить стóит», и у
КАЖДОГО факта адрес надо спросить ДО снятия. #1231 так нашёл СВОЮ ошибку: строка
округляла такт шага 0-офис до «290 с», журнал несёт **289,7**.

**4. НОВОЕ (ADR-1085): `read_clock` в `_meta` панели владельца НЕ ПРОВЕДЁН.**
`company_truth` судит «из будущего» против ПОЗДНЕЙШЕГО из `now` и момента чтения
(ADR-763); `_meta` судит против `now` начала сборки, и его защитой остаётся допуск
10 мин. На измеренном окне сборки (83.9…**98.6 с**) запаса ≈6×, но сборка, растянувшаяся
дольше допуска, вернёт класс — уже шумом, а не молчанием. Чинить — провести `read_clock`
тем же приёмом, что в `company_truth`.

**5. НОВОЕ (ADR-1085): население класса «отрицательный возраст» за пределами `_meta`
НЕ ИЗМЕРЕНО** и нулём не считается. Соседний носитель НАЗВАН замером #1231:
`spa_core/investment_cio/sources_summary.py` печатает `max(age_min, 0)`, то есть ЗАЖИМАЕТ
отрицательный возраст в ноль — та же неразличимость, только в тексте для человека. Свой
модуль, свой счёт возраста, своя приёмка; СПЕРВА население, потом правка.

**6. ПЕРЕНЕСЁН из G1070 п. 4: тридцать пятый выполненный критерий НЕ закрыт.**
`inbox-perepis-platit-za-vlozhennye-worktree-88`: у пробы
`reach_census_boundary_stops_at_nested_repos` дерево чисел `unmeasured` (`data_dir`
входом не объявлен). Починка — довести `data_dir` входом до ЭТОЙ пробы.

**7. ПЕРЕНЕСЁН из G1070 п. 5 и СУЖЕН замером #1231.** Остаток населения класса «читатель
отвечает о ДРУГОМ носителе молча» назывался `scripts/build_tracker_board.py`. Замер 24.11:
у него `--tracker-dir` ЕСТЬ, умолчание — трекер ДЕРЕВА ЗАПУЩЕННОГО кода (а не прод-дерева,
как было у читателя очереди до ADR-1080), и ветка записи ПЕЧАТАЕТ носителя строкой
`wrote <путь>`. Остаётся ОДНА узкая ось: ветка **`--check`** печатает
`OK: доска совпадает с карточками (N карточек)` и носителя НЕ называет. Это «носитель
верный, но не напечатан», а не «ответ о чужом» — предмет уже́ другой и дешевле. За
пределами названных читателей класс НЕ ИЗМЕРЕН.

**8. ПЕРЕНЕСЁН из G1070 п. 6: ось «статус местной копии расходится с `ref`» НЕ СУДИТСЯ
НИКЕМ** (`inbox-arb-razobrat-trevogu-telegram-posle-pere`). Класс ADR-544; тексты обеих
копий у `audit` УЖЕ в руках, то есть мерка бесплатна.

**9. ПЕРЕНЕСЁН из G1070 п. 8: притязание `injected-clock` подтверждается, когда дверь к
часам достигается ВНУТРИ процесса через ПРОДУКЦИОННЫЙ код.** Карточка
`inbox-prityazanie-injected-clock-podtverzhdaet`. Население: **51** файл несёт
притязание. Учить сторожа ТОЛЬКО после замера населения.

**10. ПЕРЕНЕСЁН из G1070 п. 9: два имени `test_tb_sanitizer_probe.py` — осталась ОДНА
неизмеренная ось** (ОС и версия Python: CI `ubuntu-latest`/3.11 против Мака 3.13).
Карточка `inbox-proba-sanitara-trassy-na-ci-otvechaet-ko`. **Замер #1231: оба имени
снова в красном наборе И оба ПЕРЕЕХАЛИ** (шард 6 → 2), то есть ось содержания у них
по-прежнему НЕ ИЗМЕРЕНА.

**11. ПЕРЕНЕСЁН из G1070 п. 10: мерку «что МОИ байты способны покрасить» выводи из
БАЙТОВ и СВЕРЯЙ ПОЛЕ.** `python3 scripts/derived_artifact_census.py --surface --json` ∩
каталоги своей доставки, поле `entries[].source_dirs` (НЕ `calls[].dir`). И мерить их
НАДО ДВАЖДЫ: на чистом origin и в своём дереве, иначе чужая предсуществующая краснота
читается как своя регрессия.

**12. ПЕРЕНЕСЁН из G1070 п. 11: четыре сторожа карточки
`inbox-chetyre-storozha-krasny-na-chistom-origi` красны на `main`**, подтверждены на ТРЁХ
базах. Чинить У ПИСАТЕЛЯ, по одному, с пробой до работы; дописывать в базы ЗАПРЕЩЕНО
(инв. #16).

**13. ПЕРЕНЕСЁН из G1070 п. 12: класс «подмена, пережившая сцену» ШИРЕ двери launchd и
за её пределами НЕ ИЗМЕРЕН.** Соседний член НАЗВАН замером #1220 и не чинился.

**14. ПЕРЕНЕСЁН из G1070 п. 13: два артефакта офиса НЕ ПРОЧИТАНЫ ВОСЕМНАДЦАТЫЙ цикл
подряд** (замер #1231: офис **145 / 2**). Причина чужая: `com.spa.decision_loop` во флоте
не загружен, включение — действие ВЛАДЕЛЬЦА (ADR-1053/1061). Дубля не заводить. Офис
звать С `--data-dir <прод>/data`.

**15. ПЕРЕНЕСЁН из G1070 п. 14: прод-трекер отстал** — читателя очереди и приёмку
карточек звать С флагом `--tracker-dir <своё дерево>/nimbalyst-local/tracker` (ADR-1080;
у `probe`/`set-status` этого флага НЕТ — они правят файл по названному пути, и это верно).
Синхронизация прод-дерева — действие ВЛАДЕЛЬЦА, карточка есть
(`owner-decision-rabochaya-kopiya-prikaza-portfolio-cio-n`), дубля не заводить.

**16. ПЕРЕНЕСЁН из G1070 п. 15: ось «тот ли ШАРД» закрыта, ось «те ли СОСЕДИ» — НЕТ.**

**17. УРОК О МУТАЦИОННОМ ЗАМЕРЕ, дополнен замером #1231:** `git status` дерева мутаций
сверять со своим набором ПЕРЕД каждым прогоном (у #1231 совпал — 4 файла) · якоря спеки
СЛЕДУЮТ ЗА БАЙТАМИ, и `count == 0` это третий исход «НЕ ПРИМЕНЕНА» (проверять ДО прогона
одним зовом) · выжившая мутация бывает НАСТОЯЩЕЙ дырой, дефектом МЕРКИ либо дырой
ПОКРЫТИЯ — **у #1231 единственный выживший (M16) был дырой СЦЕНЫ, а не кода**, и починка
есть ДОБАВЛЕННАЯ сцена, а не правка спеки · после починки перемерять ТОЛЬКО выжившую
(подспека на одну мутацию), но ОБЯЗАТЕЛЬНО спросив `--window-check` у дерева.

**18. ПЕРЕНЕСЁН из G1070 п. 17: население класса «у действия нет двери, хотя у его
последствия дверь есть» НЕ ИЗМЕРЕНО** и нулём это не считается (ADR-1083, § «Чего это НЕ
закрывает»). Соседи того же вида названы: заказ прогона `ci.yml`, отправка воркфлоу с
ветки кандидата.

**19. ПЕРЕНЕСЁН из G1070 п. 18: не-Python носители ложного утверждения «названо
доставленным, на origin нет» НЕ ИЗМЕРЕНЫ.** Та же форма живёт в `docs/`, в карточках
трекера и в самих заказах. Закрыта ОДНА дверь — ПАМЯТЬ. И записи памяти, НЕ называющие ни
одного модуля (**544** из 916), этой мерой не судятся вовсе.

**20. ПЕРЕНЕСЁН из G1070 п. 19: у приборов ADR-1072/1084 нет автоматического читателя** —
их зовёт рука. Варианты те же и ни один не сделан: ступень моста ИНЕРТНА, пока
`com.spa.decision_loop` не загружен владельцем; расширять поверхность храповика сирот —
ТОЛЬКО после замера населения. **С #1231 в том же положении третий прибор** —
`scripts/future_dated_observation_census.py` (ADR-1085): читателя у него нет, и его зов
руками внутри такта бесполезен, а ответ его перемежающийся по построению.

**21. Пределы `STATE.md` после доставки #1231 — в пост-записи ниже.**

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

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

**0. Заказ G1059 ОСТАЁТСЯ ЖИВЫМ ЦЕЛИКОМ** (его пп. 1–3, 5, 7–10 не исполнял никто из
#1218…#1232). **Заказ G1071 исполнен в пп. 1 и 3**; его пп. 2, 4–21 перенесены ниже без
правок смысла.

**1. Вердикт контрольного прогона цикла #1232 — ПРОЧИТАТЬ ПЕРВЫМ ДЕЛОМ.** Номер и ПОЛНАЯ
sha — в пост-записи ниже. База сравнения — **`45345362170`** (**68** имён, мой замер;
из них **9** чинит ADR-1086, то есть у исправной доставки их быть не должно). Команда одна,
и ось шарда она спрашивает САМА: `python3 scripts/ci_control_verdict.py --delta 45345362170
<новый>`. Код **2** при непустом «ПРИШЛО» означает «переехало / ось слепа», а НЕ «ничего не
найдено». Перед сличением спроси у API, нет ли на той же базе прогона НОВЕЕ.

**2. НОВОЕ (ADR-1086): население класса «половина инъекции часов» НЕ ИЗМЕРЕНО** и нулём это
не считается. Закрыт ОДИН носитель: сцена `test_mission_control_contract.py` пиновала каждую
ТЕКСТОВУЮ отметку от якоря, а отметку из `mtime` файла оставляла на календаре — и это дало
**9** красных имён на `main` при неизменном коде. Измерена только ПОВЕРХНОСТЬ продукции:
`st_mtime` читают **102** места в **68** файлах (вне тестов) — ВЕРХНЯЯ граница. Со стороны
тестов: `st_mtime` упоминают **54** файла, `os.utime` — **77**; пересечением класс НЕ
задаётся, опасно их РАСХОЖДЕНИЕ в одной сцене. Мерить дифференциально (поверхность дважды,
второй раз со сдвинутым относительно якоря `mtime`; предмет — у кого МЕНЯЕТСЯ вердикт, и
переход в `skipped` тоже). Карточка — `inbox-polovina-inektsii-chasov-mtime-stseny-ne`.
**Сторож притязания `injected-clock` этот класс НЕ видит ПО ПОСТРОЕНИЮ** (AST одного файла
против второй стороны из `stat()`); учить его — ТОЛЬКО после замера населения.

**3. ПЕРЕНЕСЁН из G1071 п. 2: ЗАКАЗЫВАТЬ ПРОГОН ДВЕРЬЮ, А НЕ `curl`-ом** (ADR-1083).
`python3 scripts/ci_control_verdict.py --order-run <ПОЛНАЯ 40-hex sha>` сам спрашивает
занятость группы `ci-control` ДО подачи и перечитывает живость заказа после;
`--order-check <sha>` — только спросить. Коды: **0** заказан и жив · **1** подан,
личность/живость НЕ ПОДТВЕРЖДЕНА · **2** НЕ ИЗМЕРЕНО, заказ не подавался · **3** ОТКАЗ ·
**4** подача не принята API. Заказывать ОДИН раз, на ПОСЛЕДНЕЙ вершине доставки. Такт
расписанного прогона дверь называет САМА (`next_cron_moment`) — число из прозы НЕ
перепечатывать.

**4. `STATE.md`: запас 4 строки / 481 символ / 5 в длиннейшей** (146 / 29 519 / 695 при
пределах 150 / 30 000 / 700). #1232 заработал место, сняв ЧЕТЫРЕ строки, и у каждой спросил
адрес ДО снятия (детали — в журнале). Запас не бесконечен: следующие кандидаты —
строки-указатели `ADR-947…1019` и `ADR-770…946`, у обеих факты «помнить стóит», и адрес
каждого спрашивать ДО снятия.

**5. ПЕРЕНЕСЁН из G1071 п. 4: `read_clock` в `_meta` панели владельца НЕ ПРОВЕДЁН.**
`company_truth` судит «из будущего» против ПОЗДНЕЙШЕГО из `now` и момента чтения (ADR-763);
`_meta` судит против `now` начала сборки, и его защитой остаётся допуск 10 мин. На измеренном
окне сборки (83.9…**98.6 с**) запаса ≈6×, но сборка, растянувшаяся дольше допуска, вернёт
класс — уже шумом, а не молчанием.

**6. ПЕРЕНЕСЁН из G1071 п. 5: соседний носитель «отрицательного возраста» НЕ ЧИНЕН.**
`spa_core/investment_cio/sources_summary.py` печатает `max(age_min, 0)`, то есть ЗАЖИМАЕТ
отрицательный возраст в ноль — та же неразличимость, только в тексте для человека. Свой
модуль, свой счёт возраста, своя приёмка; СПЕРВА население, потом правка.

**7. ПЕРЕНЕСЁН из G1071 п. 6: тридцать пятый выполненный критерий НЕ закрыт.**
`inbox-perepis-platit-za-vlozhennye-worktree-88`: у пробы
`reach_census_boundary_stops_at_nested_repos` дерево чисел `unmeasured` (`data_dir` входом не
объявлен). Починка — довести `data_dir` входом до ЭТОЙ пробы.

**8. ПЕРЕНЕСЁН из G1071 п. 7: у `scripts/build_tracker_board.py` ветка `--check` печатает
`OK: доска совпадает с карточками (N карточек)` и носителя НЕ называет.** Это «носитель
верный, но не напечатан», а не «ответ о чужом». За пределами названных читателей класс НЕ
ИЗМЕРЕН.

**9. ПЕРЕНЕСЁН из G1071 п. 8: ось «статус местной копии расходится с `ref`» НЕ СУДИТСЯ
НИКЕМ** (`inbox-arb-razobrat-trevogu-telegram-posle-pere`). Класс ADR-544; тексты обеих копий
у `audit` УЖЕ в руках, то есть мерка бесплатна.

**10. ПЕРЕНЕСЁН из G1071 п. 9: притязание `injected-clock` подтверждается, когда дверь к
часам достигается ВНУТРИ процесса через ПРОДУКЦИОННЫЙ код.** Карточка
`inbox-prityazanie-injected-clock-podtverzhdaet`. Население: **51** файл несёт притязание.
**Замер #1232 добавил к этому ВТОРУЮ границу:** притязание бывает верным по AST и ложным по
предмету, когда вторая сторона сравнения приходит из файловой системы (ADR-1086).

**11. ПЕРЕНЕСЁН из G1071 п. 10: два имени `test_tb_sanitizer_probe.py` — осталась ОДНА
неизмеренная ось** (ОС и версия Python: CI `ubuntu-latest`/3.11 против Мака 3.13). Карточка
`inbox-proba-sanitara-trassy-na-ci-otvechaet-ko`. **Замер #1232: оба имени УШЛИ из красного
набора И оба ПЕРЕЕХАЛИ (шард 2 → 6)** — то есть починенными это их НЕ объявляет, ось
содержания у них по-прежнему НЕ ИЗМЕРЕНА.

**12. ПЕРЕНЕСЁН из G1071 п. 11: мерку «что МОИ байты способны покрасить» выводи из БАЙТОВ и
СВЕРЯЙ ПОЛЕ.** `python3 scripts/derived_artifact_census.py --surface --json` ∩ каталоги своей
доставки, поле `entries[].source_dirs` (НЕ `calls[].dir`). И мерить их НАДО ДВАЖДЫ: на чистом
origin и в своём дереве. **Замер #1232: 50 сторожей, на чистом `f4e57d68f` — 9 failed, 1173
passed, 1 skipped, и все девять имён ровно те, что цикл чинил** (иной предсуществующей
красноты в этом поле НЕТ).

**13. ПЕРЕНЕСЁН из G1071 п. 12: четыре сторожа карточки
`inbox-chetyre-storozha-krasny-na-chistom-origi` красны на `main`**, подтверждены на ТРЁХ
базах. Чинить У ПИСАТЕЛЯ, по одному, с пробой до работы; дописывать в базы ЗАПРЕЩЕНО
(инв. #16).

**14. ПЕРЕНЕСЁН из G1071 п. 13: класс «подмена, пережившая сцену» ШИРЕ двери launchd и за её
пределами НЕ ИЗМЕРЕН.** Соседний член НАЗВАН замером #1220 и не чинился.

**15. ПЕРЕНЕСЁН из G1071 п. 14: два артефакта офиса НЕ ПРОЧИТАНЫ ДЕВЯТНАДЦАТЫЙ цикл подряд**
(замер #1232: офис **145 / 2**). Причина чужая: `com.spa.decision_loop` во флоте не загружен,
включение — действие ВЛАДЕЛЬЦА (ADR-1053/1061). Дубля не заводить. Офис звать С
`--data-dir <прод>/data`.

**16. ПЕРЕНЕСЁН из G1071 п. 15: прод-трекер отстал** — читателя очереди и приёмку карточек
звать С флагом `--tracker-dir <своё дерево>/nimbalyst-local/tracker` (ADR-1080; у
`probe`/`set-status` этого флага НЕТ — они правят файл по названному пути, и это верно).
Синхронизация прод-дерева — действие ВЛАДЕЛЬЦА, карточка есть
(`owner-decision-rabochaya-kopiya-prikaza-portfolio-cio-n`), дубля не заводить.
**И прод-копия приказа всё ещё НЕЧИТАЕМА:** 2 880 412 Б против 93 969 символов на origin.

**17. ПЕРЕНЕСЁН из G1071 п. 16: ось «тот ли ШАРД» закрыта, ось «те ли СОСЕДИ» — НЕТ.**

**18. УРОК О МУТАЦИОННОМ ЗАМЕРЕ, дополнен замером #1232:** `git status` дерева мутаций
сверять со своим набором ПЕРЕД прогоном · `count == 0` это третий исход «НЕ ПРИМЕНЕНА» ·
выжившая мутация бывает НАСТОЯЩЕЙ дырой, дефектом МЕРКИ либо дырой ПОКРЫТИЯ. **У #1232
выживших НЕ БЫЛО (8/8 с первого прогона), и это НЕ повод считать спеку хорошей: все восемь
осей — её собственные, а независимость контроля от продукции подтвердила ровно ОДНА мутация
(M08), которую убила ЧУЖАЯ батарея.** Окно прибора спрашивать `--window-check` ПОСЛЕ прогона
и сверять байты md5.

**19. ПЕРЕНЕСЁН из G1071 п. 18: население класса «у действия нет двери, хотя у его
последствия дверь есть» НЕ ИЗМЕРЕНО** (ADR-1083, § «Чего это НЕ закрывает»). Соседи того же
вида названы: заказ прогона `ci.yml`, отправка воркфлоу с ветки кандидата.

**20. ПЕРЕНЕСЁН из G1071 п. 19: не-Python носители ложного утверждения «названо доставленным,
на origin нет» НЕ ИЗМЕРЕНЫ.** Та же форма живёт в `docs/`, в карточках трекера и в самих
заказах. Закрыта ОДНА дверь — ПАМЯТЬ. И записи памяти, НЕ называющие ни одного модуля
(**544** из 916), этой мерой не судятся вовсе.

**21. ПЕРЕНЕСЁН из G1071 п. 20: у приборов ADR-1072/1084/1085 нет автоматического читателя** —
их зовёт рука. Варианты те же и ни один не сделан: ступень моста ИНЕРТНА, пока
`com.spa.decision_loop` не загружен владельцем; расширять поверхность храповика сирот —
ТОЛЬКО после замера населения.

**22. НОВОЕ: вес приказа держат ДВЕ оси, и связывающей была СТРОЧНАЯ.** Замер #1232 перед
правкой: приказ **93 363** символа / **2 855** строк, держатель максимума трекера —
`agent-audit-2026-08-02-fix-tracks.md` (**174 982** / **3 016**). По символам запас был
81 619, по СТРОКАМ — **161**, то есть заказ и пост-запись (≈250 строк) сделали бы приказ
держателем максимума. Перенос пяти пост-фактум разделов (**18 977** символов) дверью ADR-1066
вернул запас, архив `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`. Мерить
НАДО обе оси: ответ по символам назвал бы «места вдоволь».

**23. НОВОЕ: заголовок перенесённого раздела СОХРАНЯТЬ ПОБАЙТОВО.** Первая попытка пуша #1232
отказала ВЕРНО (страж потери разделов): стаб со заголовком «… — В АРХИВЕ» есть ИСЧЕЗНОВЕНИЕ
раздела, а 07.10 такая правка унесла разделы с ШЕСТИ карточек владельца, и на origin их нет по
сей день. Правильная форма — заголовок прежний, тело заменено указателем на архив: раздел не
исчез, у него сменился АДРЕС тела.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1073 (следующему циклу)

**0. Заказ G1059 ОСТАЁТСЯ ЖИВЫМ ЦЕЛИКОМ** (его пп. 1–3, 5, 7–10 не исполнял никто из
#1218…#1233). **Заказ G1072 исполнен в пп. 1 и 2**; его пп. 3–23 перенесены ниже без
правок смысла.

**1. Вердикт контрольного прогона цикла #1233 — ПРОЧИТАТЬ ПЕРВЫМ ДЕЛОМ.** Номер и ПОЛНАЯ
sha — в пост-записи ниже. База сравнения — **`45357670104`** (**53** имени, мой замер).
Команда одна, и ось шарда она спрашивает САМА: `python3 scripts/ci_control_verdict.py
--delta 45357670104 <новый>`. Код **2** при непустом «ПРИШЛО» означает «переехало / ось
слепа», а НЕ «ничего не найдено». Перед сличением спроси у API, нет ли на той же базе
прогона НОВЕЕ. **Замер #1233 добавил к оси знание о её ЦЕНЕ:** доставка #1232 дала
68 → 53, ПРИШЛО **0**, УШЛО **15**, и ВСЕ 15 остались на ТОМ ЖЕ шарде — то есть ось
содержания была измерена, а не угадана; из ушедших 9 — ровно те, что чинил ADR-1086,
а 6 — род часов («сторож лишь успел дойти до вердикта», порог поднимать запрещено).

**2. НОВОЕ (ADR-1087): у класса «половина инъекции часов через `mtime`» ПРЕДМЕТ измерен,
а КЛАСС за границей одного хопа НЕТ.** Прибор — `spa_core/tests/_mtime_clock_door.py`
(`--surface` · `--differential --run-root <одноразовое дерево>`), приёмка — проба
`mtime_half_injection_population_is_measured`. Числа замера 24.11: охват **2597** ·
притязание несут **303** (не 51, как числил G1072 п. 10 — замер с датой, не константа) ·
верхняя граница **250** · ПРЕДМЕТ **102** · НЕ ИЗМЕРЕНО **0**. **Класс внутри предмета ПУСТ: кандидатов 0, членов 0, шума 0 — и это в ОБА направления
сдвига** (−400 и +400 суток, вердиктов pytest 3457 в каждом прогоне, канарейка прозрачности
зелена в обоих). Ноль есть НАБЛЮДЕНИЕ, а не молчание прибора: у живой сцены со снятым пином
прибор даёт **4** члена. И тот же контроль ОПРОВЕРГ предположение о направлении — сцена в
аварийной форме красна УЖЕ НА БАЗЕ, поэтому НАЗАД её ЛЕЧИТ (`FAILED → PASSED`), а ВПЕРЁД не
меняет ничего; «член» = ЛЮБАЯ смена вердикта, а полный ответ есть ОБЪЕДИНЕНИЕ двух прогонов.
Остались НЕ ИЗМЕРЕННЫМИ: население за ОДНИМ хопом · ось «отметка ВПЕРЁД якоря» ·
`os.DirEntry.stat()`/`os.fstat` · файлы, которые сцена создаёт ВНУТРИ дерева репозитория.

**3. НОВОЕ: дефект прибора может выглядеть ЗАВИСАНИЕМ, а не дефектом.** Первая редакция
`_mtime_clock_door` считала ключ пути `os.path.realpath`, а он идёт через `os.lstat` —
через УЖЕ ПОДМЕНЁННУЮ дверь: обёртка уходила в себя, и сцена в **0,4 с** держалась
**ВОСЕМЬ МИНУТ**. Правило то же, что § окна мутационного прибора п. 8: «работает» и
«умер» обязаны выглядеть ПО-РАЗНОМУ. И тот же класс был у СЦЕНЫ контроля пробы
(`maximum recursion depth exceeded` ⇒ прибор доложил «поверхность не разобрана», то есть
НЕ ИЗМЕРЕНО по ЧУЖОЙ причине): дверь, которую собираешься подменять, снимай ДО подмены.

**4. НОВОЕ: сторож притязания `injected-clock` читает пометку в ЛЮБОЙ строке файла,
включая ПРОЗУ и строковый литерал сцены.** Замер #1233: мой новый тест-файл написал
пометку в докстринге («этому файлу она НЕ НУЖНА») и честно покраснел как ложное
притязание. Лечение — не писать литерал пометки в прозе и собирать его ИЗ ЧАСТЕЙ там, где
он нужен сцене. Это НЕ дефект сторожа: отличить прозу от пометки он не может по
построению, и ошибаться обязан в сторону находки.

**5. ВНИМАНИЕ: `STATE.md` на ПРЕДЕЛЕ — запас 3 строки / 3 символа / 5 в длиннейшей**
(147 / 29 997 / 695 при пределах 150 / 30 000 / 700). Это ТРИ символа, а не «почти хватает»:
следующая строка не влезет НИКАК, место придётся заработать. Кандидаты те же, что назвал
G1072 п. 4 — строки-указатели `ADR-947…1019` и `ADR-770…946`, у обеих есть факты «помнить
стóит», и адрес КАЖДОГО спрашивать ДО снятия (порядок #1231/#1232).

**6. ПЕРЕНЕСЁН из G1071 п. 2: ЗАКАЗЫВАТЬ ПРОГОН ДВЕРЬЮ, А НЕ `curl`-ом** (ADR-1083).
`python3 scripts/ci_control_verdict.py --order-run <ПОЛНАЯ 40-hex sha>` сам спрашивает
занятость группы `ci-control` ДО подачи и перечитывает живость заказа после;
`--order-check <sha>` — только спросить. Коды: **0** заказан и жив · **1** подан,
личность/живость НЕ ПОДТВЕРЖДЕНА · **2** НЕ ИЗМЕРЕНО, заказ не подавался · **3** ОТКАЗ ·
**4** подача не принята API. Заказывать ОДИН раз, на ПОСЛЕДНЕЙ вершине доставки. Такт
расписанного прогона дверь называет САМА (`next_cron_moment`) — число из прозы НЕ
перепечатывать.

**7. `STATE.md`: запас 4 строки / 481 символ / 5 в длиннейшей** (146 / 29 519 / 695 при
пределах 150 / 30 000 / 700). #1232 заработал место, сняв ЧЕТЫРЕ строки, и у каждой спросил
адрес ДО снятия (детали — в журнале). Запас не бесконечен: следующие кандидаты —
строки-указатели `ADR-947…1019` и `ADR-770…946`, у обеих факты «помнить стóит», и адрес
каждого спрашивать ДО снятия.

**8. ПЕРЕНЕСЁН из G1071 п. 4: `read_clock` в `_meta` панели владельца НЕ ПРОВЕДЁН.**
`company_truth` судит «из будущего» против ПОЗДНЕЙШЕГО из `now` и момента чтения (ADR-763);
`_meta` судит против `now` начала сборки, и его защитой остаётся допуск 10 мин. На измеренном
окне сборки (83.9…**101.6 с**) запаса ≈6×, но сборка, растянувшаяся дольше допуска, вернёт
класс — уже шумом, а не молчанием.

**9. ПЕРЕНЕСЁН из G1071 п. 5: соседний носитель «отрицательного возраста» НЕ ЧИНЕН.**
`spa_core/investment_cio/sources_summary.py` печатает `max(age_min, 0)`, то есть ЗАЖИМАЕТ
отрицательный возраст в ноль — та же неразличимость, только в тексте для человека. Свой
модуль, свой счёт возраста, своя приёмка; СПЕРВА население, потом правка.

**10. ПЕРЕНЕСЁН из G1071 п. 6: тридцать пятый выполненный критерий НЕ закрыт.**
`inbox-perepis-platit-za-vlozhennye-worktree-88`: у пробы
`reach_census_boundary_stops_at_nested_repos` дерево чисел `unmeasured` (`data_dir` входом не
объявлен). Починка — довести `data_dir` входом до ЭТОЙ пробы.

**11. ПЕРЕНЕСЁН из G1071 п. 7: у `scripts/build_tracker_board.py` ветка `--check` печатает
`OK: доска совпадает с карточками (N карточек)` и носителя НЕ называет.** Это «носитель
верный, но не напечатан», а не «ответ о чужом». За пределами названных читателей класс НЕ
ИЗМЕРЕН.

**12. ПЕРЕНЕСЁН из G1071 п. 8: ось «статус местной копии расходится с `ref`» НЕ СУДИТСЯ
НИКЕМ** (`inbox-arb-razobrat-trevogu-telegram-posle-pere`). Класс ADR-544; тексты обеих копий
у `audit` УЖЕ в руках, то есть мерка бесплатна.

**13. ПЕРЕНЕСЁН из G1071 п. 9: притязание `injected-clock` подтверждается, когда дверь к
часам достигается ВНУТРИ процесса через ПРОДУКЦИОННЫЙ код.** Карточка
`inbox-prityazanie-injected-clock-podtverzhdaet`. Население: **51** файл несёт притязание.
**Замер #1232 добавил к этому ВТОРУЮ границу:** притязание бывает верным по AST и ложным по
предмету, когда вторая сторона сравнения приходит из файловой системы (ADR-1086).

**14. ПЕРЕНЕСЁН из G1071 п. 10: два имени `test_tb_sanitizer_probe.py` — осталась ОДНА
неизмеренная ось** (ОС и версия Python: CI `ubuntu-latest`/3.11 против Мака 3.13). Карточка
`inbox-proba-sanitara-trassy-na-ci-otvechaet-ko`. **Замер #1232: оба имени УШЛИ из красного
набора И оба ПЕРЕЕХАЛИ (шард 2 → 6)** — то есть починенными это их НЕ объявляет, ось
содержания у них по-прежнему НЕ ИЗМЕРЕНА.

**15. ПЕРЕНЕСЁН из G1071 п. 11: мерку «что МОИ байты способны покрасить» выводи из БАЙТОВ и
СВЕРЯЙ ПОЛЕ.** `python3 scripts/derived_artifact_census.py --surface --json` ∩ каталоги своей
доставки, поле `entries[].source_dirs` (НЕ `calls[].dir`). И мерить их НАДО ДВАЖДЫ: на чистом
origin и в своём дереве. **Замер #1232: 50 сторожей, на чистом `f4e57d68f` — 9 failed, 1173
passed, 1 skipped, и все девять имён ровно те, что цикл чинил** (иной предсуществующей
красноты в этом поле НЕТ).

**16. ПЕРЕНЕСЁН из G1071 п. 12: четыре сторожа карточки
`inbox-chetyre-storozha-krasny-na-chistom-origi` красны на `main`**, подтверждены на ТРЁХ
базах. Чинить У ПИСАТЕЛЯ, по одному, с пробой до работы; дописывать в базы ЗАПРЕЩЕНО
(инв. #16).

**17. ПЕРЕНЕСЁН из G1071 п. 13: класс «подмена, пережившая сцену» ШИРЕ двери launchd и за её
пределами НЕ ИЗМЕРЕН.** Соседний член НАЗВАН замером #1220 и не чинился.

**18. ПЕРЕНЕСЁН из G1071 п. 14: два артефакта офиса НЕ ПРОЧИТАНЫ ДЕВЯТНАДЦАТЫЙ цикл подряд**
(замер #1232: офис **145 / 2**). Причина чужая: `com.spa.decision_loop` во флоте не загружен,
включение — действие ВЛАДЕЛЬЦА (ADR-1053/1061). Дубля не заводить. Офис звать С
`--data-dir <прод>/data`.

**19. ПЕРЕНЕСЁН из G1071 п. 15: прод-трекер отстал** — читателя очереди и приёмку карточек
звать С флагом `--tracker-dir <своё дерево>/nimbalyst-local/tracker` (ADR-1080; у
`probe`/`set-status` этого флага НЕТ — они правят файл по названному пути, и это верно).
Синхронизация прод-дерева — действие ВЛАДЕЛЬЦА, карточка есть
(`owner-decision-rabochaya-kopiya-prikaza-portfolio-cio-n`), дубля не заводить.
**И прод-копия приказа всё ещё НЕЧИТАЕМА:** 2 880 412 Б против 93 969 символов на origin.

**20. ПЕРЕНЕСЁН из G1071 п. 16: ось «тот ли ШАРД» закрыта, ось «те ли СОСЕДИ» — НЕТ.**

**21. УРОК О МУТАЦИОННОМ ЗАМЕРЕ, дополнен замером #1232:** `git status` дерева мутаций
сверять со своим набором ПЕРЕД прогоном · `count == 0` это третий исход «НЕ ПРИМЕНЕНА» ·
выжившая мутация бывает НАСТОЯЩЕЙ дырой, дефектом МЕРКИ либо дырой ПОКРЫТИЯ. **У #1232
выживших НЕ БЫЛО (8/8 с первого прогона), и это НЕ повод считать спеку хорошей: все восемь
осей — её собственные, а независимость контроля от продукции подтвердила ровно ОДНА мутация
(M08), которую убила ЧУЖАЯ батарея.** Окно прибора спрашивать `--window-check` ПОСЛЕ прогона
и сверять байты md5.

**22. ПЕРЕНЕСЁН из G1071 п. 18: население класса «у действия нет двери, хотя у его
последствия дверь есть» НЕ ИЗМЕРЕНО** (ADR-1083, § «Чего это НЕ закрывает»). Соседи того же
вида названы: заказ прогона `ci.yml`, отправка воркфлоу с ветки кандидата.

**23. ПЕРЕНЕСЁН из G1071 п. 19: не-Python носители ложного утверждения «названо доставленным,
на origin нет» НЕ ИЗМЕРЕНЫ.** Та же форма живёт в `docs/`, в карточках трекера и в самих
заказах. Закрыта ОДНА дверь — ПАМЯТЬ. И записи памяти, НЕ называющие ни одного модуля
(**544** из 916), этой мерой не судятся вовсе.

**24. ПЕРЕНЕСЁН из G1071 п. 20: у приборов ADR-1072/1084/1085 нет автоматического читателя** —
их зовёт рука. Варианты те же и ни один не сделан: ступень моста ИНЕРТНА, пока
`com.spa.decision_loop` не загружен владельцем; расширять поверхность храповика сирот —
ТОЛЬКО после замера населения.

**25. НОВОЕ: вес приказа держат ДВЕ оси, и связывающей была СТРОЧНАЯ.** Замер #1232 перед
правкой: приказ **93 363** символа / **2 855** строк, держатель максимума трекера —
`agent-audit-2026-08-02-fix-tracks.md` (**174 982** / **3 016**). По символам запас был
81 619, по СТРОКАМ — **161**, то есть заказ и пост-запись (≈250 строк) сделали бы приказ
держателем максимума. Перенос пяти пост-фактум разделов (**18 977** символов) дверью ADR-1066
вернул запас, архив `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`. Мерить
НАДО обе оси: ответ по символам назвал бы «места вдоволь».

**26. НОВОЕ: заголовок перенесённого раздела СОХРАНЯТЬ ПОБАЙТОВО.** Первая попытка пуша #1232
отказала ВЕРНО (страж потери разделов): стаб со заголовком «… — В АРХИВЕ» есть ИСЧЕЗНОВЕНИЕ
раздела, а 07.10 такая правка унесла разделы с ШЕСТИ карточек владельца, и на origin их нет по
сей день. Правильная форма — заголовок прежний, тело заменено указателем на архив: раздел не
исчез, у него сменился АДРЕС тела.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1074 (следующему циклу)

> **Тело перенесено в архив** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`
> (раздел «Заказ G1074 — перенесён … циклом #1236»). Раздел НЕ исчез: у него сменился АДРЕС
> тела. Живые пункты **3, 4, 5** перенесены в «Заказ G1076» ниже ДО снятия.

### Заказ G1075 (следующему циклу)

**ТЕЛО ПЕРЕНЕСЕНО В АРХИВ** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`,
раздел «Перенос цикла #1237». Живые пункты (**2, 3, 5, 6, 8, 9, 11, 12**) перенесены в
«Заказ G1077» ниже ДО снятия; исполненные (1, 4, 7, 10) остались в архиве.

### Заказ G1076 (следующему циклу)

**0. ЦЕПЬ: заказ G1059 ОСТАЁТСЯ ЖИВЫМ ЦЕЛИКОМ; заказ G1073 жив в пп. 2–26; заказ
G1074 СЖАТ в архив этим циклом, и его живые пп. 3–5 перенесены СЮДА (пп. 13–15) ДО
снятия; заказ G1075 исполнен в пп. 1, 4, 10 (и 7 — место заработано), а его пп. 2, 3, 5,
6, 8, 9, 11, 12 ЖИВЫ и лежат ВЫШЕ в этой же карточке.** Переписывать их сюда я не стал
НАМЕРЕННО: копия заказа есть удвоение веса. Следствие: сжимать раздел «Заказ G1075» в
архив можно только ПОСЛЕ переноса его живых пунктов в свой заказ.

**1. Вердикт контрольного прогона цикла #1236 — ПРОЧИТАТЬ ПЕРВЫМ ДЕЛОМ.** Номер и
ПОЛНАЯ sha — в пост-записи ниже. База сравнения — **`45428106750`** (**83** имени, мой
замер). Команда одна, ось шарда она спрашивает САМА: `python3
scripts/ci_control_verdict.py --delta 45428106750 <новый>`. Код **2** при непустом
«ПРИШЛО» означает «переехало / ось слепа», а НЕ «ничего не найдено». Перед сличением
спроси у API, нет ли на той же базе прогона НОВЕЕ.

**⚠️ База у этой дельты ТОЖЕ шумная по роду часов.** В `45428106750` ушло **13** имён, и
ВСЕ ТРИНАДЦАТЬ рода `wallclock_timeout` (9 из них к тому же переехали шард 0 → 9).
Род часов регрессией не является и починкой тоже: сличать ТОЛЬКО по именам и по ОБОИМ
счётчикам, и у каждого пришедшего имени смотреть РОД прежде оси переезда.

**2. НОВОЕ (ADR-1091): «правило объявлено и не реализовано» закрыто у ОДНОГО аудита, а
КЛАСС «объявленный перечень шире исполняемого» НЕ ИЗМЕРЕН.** Предмет был в
`AUDIT_RULES`: семь имён, пять методов, и нереализованное печаталось тем же нулём, что
прошедшее по дереву. Теперь у каждого имени есть статус (`ENFORCED` ·
`NOT_IMPLEMENTED` с причиной · `UNMEASURED` = молчаливая дыра, код CLI 2), пара
«правило → метод» живёт ОДНОЙ копией, перепись различает названный долг от забытого
имени. **Но форма эта повсеместна**: `POLLED_ADAPTERS` против `ADAPTER_REGISTRY`,
`AUDIT_RULES`-подобные перечни в сторожах, `PROBES`, перечни каталогов у линтеров —
везде, где СПИСОК ИМЁН объявляется отдельно от ИСПОЛНИТЕЛЕЙ, возможен элемент без
исполнителя, и ноль у него неотличим от чистоты. **Население класса НЕ ИЗМЕРЕНО и нулём
это не считается.** Метод замера тот же: собрать перечни имён, у каждого спросить
«есть ли исполнитель», мерить НАСЕЛЕНИЕ отдельно от РАСХОЖДЕНИЯ ВЕРДИКТА (урок G1075
п. 3: у сломанной двери расхождение равно нулю ПО ПОСТРОЕНИЮ).

**3. НОВОЕ и названный долг: `spa_core/analytics` теперь охраняется, а ПОЛНАЯ граница
охраны инварианта #3 НЕ ИЗМЕРЕНА.** Перечней каталогов ТРИ и они разные:
`llm_forbidden_lint.FORBIDDEN_DIRS` (4) · `scripts/lint_llm_forbidden.SCAN_DIRS_DEFAULT`
(7) · `architecture_audit._LLM_SCAN_SUBDIR` (1, этот цикл). Какие каталоги `spa_core/` не
названы НИ ОДНИМ — не мерил никто, и «население 0 в аналитике» на этот вопрос НЕ
отвечает. Начинать с переписи «каталог ↔ какой перечень его называет», а не с добавления
каталогов в перечни наугад.

**4. НОВОЕ И ПРО СЕБЯ: эквивалентную мутацию рождает собственная невнимательность к
истинности выражения.** Мутации M06 и M08 первого прогона были `return [] or [X]` — и
`[] or [X]` вычисляется в `[X]`, то есть мутация была НИЧЕМ. Прибор честно доложил
«ВЫЖИЛ — дыра покрытия», и прочитать это как дыру значило бы пойти чинить
несуществующее. Правило: мутация, чей текст не меняет ЗНАЧЕНИЯ, есть дефект
спецификации, и отличить её от настоящей дыры можно только прочитав выражение, а не
вердикт.

**5. НОВОЕ: три настоящие дыры покрытия нашлись там, где тест читал СОСЕДНЕЕ поле.**
M09 (артефакт `save()` считал «не измерено» нарушением) пережил прогон, потому что тест
проверял `to_markdown`, а не сохранённый JSON. M10 (таблица статусов исчезает) пережил,
потому что `to_markdown([])` уходит в ветку «нарушений нет», а мутация била ветку
«нарушения ЕСТЬ». M14 (перечень, объявленный не словарём, молча пуст вместо громкого
отказа) пережил, потому что сцены подавали только корректные формы. Все три закрыты, и
второй прогон на ФИНАЛЬНЫХ байтах в СВЕЖЕМ дереве дал **15/15**. Урок общий: мутация
проверяет не «есть ли тест про это», а «читает ли тест ТО ЖЕ место».

**6. НАЗВАНО и НЕ закрыто: `no_print_in_modules` остаётся неисполняемым.** Замер —
**5548** зовов `print()` в **1176 из 2237** не-тестовых модулей `spa_core/` (52,6 %).
`print()` здесь штатная форма отчёта CLI, и протокол цикла судит каждый обязательный шаг
по напечатанной строке. Перевод правила в исполняемое — решение ВЛАДЕЛЬЦА (предмет не
агента), и карточку на это заводить НЕ надо, пока владелец не спросит: отчёт аудита
теперь говорит «НЕ РЕАЛИЗОВАНО» вслух, то есть долг виден без карточки.

**7. НАЗВАНО и НЕ закрыто (не моя регрессия): сторож сети переустанавливается посреди
прогона.** Парный прогон `test_membership_door_census` + `test_architecture_audit`
печатает «network guard was RE-INSTALLED mid-run · missing[urlopen]». То же
воспроизведено на ЧИСТОМ `origin/main` `56a9fce8c` (74 passed): предупреждение
приписывается тому тесту, который в классе идёт ПЕРВЫМ по алфавиту, поэтому мой новый
тест лишь сменил ЯРЛЫК. Класс — «что-то подменяет `urlopen` присваиванием, а не
обёрткой» — живой; искать надо ПИСАТЕЛЯ подмены, а не тот тест, на котором сторож её
заметил.

**8. ВНИМАНИЕ: `STATE.md` снова на ПРЕДЕЛЕ — запас 2 строки / 38 символов / 5 в
длиннейшей** (148 / 29 962 / 695 при пределах 150 / 30 000 / 700). Место этот цикл
ЗАРАБОТАЛ: снята строка-указатель `ADR-947…ADR-1019` (440 символов), и адрес КАЖДОГО её
живого пункта спрошен ДО снятия (перечень — в журнале W48). **Следующему циклу места
нет.** Кандидатов-указателей в файле больше НЕТ — значит придётся сжимать живые строки,
и адрес спрашивать ДО снятия, а не по памяти.

**9. ВЕС приказа: запас СТРОЧНЫЙ и равен ~124 строкам** после этого заказа (2892 строки
/ 113 тыс. символов против держателя максимума `agent-audit-2026-08-02-fix-tracks.md` —
**3016** строк). Сжатие этот цикл СДЕЛАЛ: раздел «Заказ G1074» перенесён в архив
`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`, заголовок сохранён
ПОБАЙТОВО, тело заменено указателем, и сверены ОБА вопроса — в архиве найдено **64 из
64** непустых строк, заголовков в карточке было 44 и стало 44, ПРОПАЛО **0**. Делал это
ПЕРВЫМ делом по правилу G1075 п. 8 и ОДНИМ проходом по сегментам, а не `replace` в цикле
по мутирующей строке (авария #1233).

**10. ПЕРЕНЕСЁН: два артефакта офиса НЕ ПРОЧИТАНЫ ДВАДЦАТЬ ВТОРОЙ цикл подряд**
(замер #1236: офис **145 / 2**). Причина чужая и названа: `com.spa.decision_loop` во флоте не
загружен, включение — действие ВЛАДЕЛЬЦА (ADR-1053/1061). Дубля не заводить. Офис звать
С `--data-dir <прод>/data`.

**11. ПЕРЕНЕСЁН: заказывать прогон ДВЕРЬЮ, а не `curl`-ом** (ADR-1083): `python3
scripts/ci_control_verdict.py --order-run <ПОЛНАЯ 40-hex sha>`. Заказывать ОДИН раз, на
ПОСЛЕДНЕЙ вершине доставки; такт расписанного прогона дверь называет САМА, число из
прозы НЕ перепечатывать.

**12. ПЕРЕНЕСЁН и ПЕРЕМЕРЕН: предсуществующая краснота в поле моей доставки равна ОДНОМУ
имени.** `test_edge_boundary_dataflow_census.py::TestTheObserverIsNotPartOfItsOwnPopulation::test_the_census_screens_the_population_100_published`
красен на ЧИСТОМ `origin/main` `56a9fce8c` — перемерено этим циклом дифференциальным
прогоном 69 сторожей (чистое дерево: 1 failed / 4456 passed; моё: 1 failed / 4492
passed, то есть своей регрессии нет). Не моя, но и не починенная. Чинить У ПИСАТЕЛЯ, с
пробой до работы.

**13. ПЕРЕНЕСЁН из G1074 п. 3: потолок 4 честнее потолка 2, потому что правило
`atomic_writes` не знает про ЗАМКИ.** Два из четырёх оставшихся нарушений — файлы замков
(`telegram/bot.py:1884` `flock`, `trading_research/forward.py:211` `tick.lock`), где
прямой `open` ОБЯЗАТЕЛЕН и `os.replace` сломал бы замок. Опускать потолок до 2 **без**
понятия «замок» значило бы потребовать от кода неверного: сперва поблажка с контролем в
обе стороны, потом потолок.

**14. ПЕРЕНЕСЁН из G1074 п. 4: «в строке ЕСТЬ литерал» не равно «совпадение ВНУТРИ
литерала».** Мерка цикла #1234 ответила «7 из 7 попаданий внутри литерала» и была
дефектна: сам `open(x, "w")` несёт литерал `"w"`, то есть мерка зеленила КАЖДУЮ строку с
зовом. Нашлось не разбором, а печатью пяти «нарушений» ГЛАЗАМИ. Правило: сводное число
мерки не принимать, пока не напечатаны ЕДИНИЦЫ, из которых оно сложено. Этот цикл
подтвердил правило третий раз подряд (см. п. 4 выше).

**15. ПЕРЕНЕСЁН из G1074 п. 2: население класса «правило `atomic_writes` не ловит
`open(p, "w", encoding=...)`» НЕ ИЗМЕРЕНО.** Регулярное выражение требует закрывающей
скобки сразу за режимом; разбор AST находит в `spa_core/` **411** зовов `open()` с
пишущим режимом, и сколько из них настоящая неатомарная запись состояния — не мерил
никто. Карточка `inbox-pravilo-atomic-writes-obyavlyaet-propusk` закрыта по СВОЕЙ пробе
(дверь места), этот долг ею НЕ закрыт.

**16. НОВОЕ и НАЗВАНО: «строка прозы начинается с решётки» — класс ИЗМЕРЕН и НЕ ПУСТ.**
Урок #1233 запрещал `###` в начале строки прозы карточки; замер #1236 показал, что
разборщику разделов хватает ОДНОЙ решётки, и правило надо читать как «никакая строка
прозы не начинается с решётки». Население по всему трекеру (1684 карточки, доска
исключена): **83** строки в **69** карточках, из них **5** в самом приказе (моя шестая
исправлена). Вред не в косметике: такая строка числится РАЗДЕЛОМ, поэтому сверка «не
пропало ли из карточки» по заголовкам считает фантомы наравне с настоящими разделами — и
однажды фантом замаскирует настоящую потерю. Чинить НЕ прицепом: правка 83 строк в 69
карточках трогает чужие карточки, значит нужна карточка со своей пробой, а дверью
проверки обязан стать тот же разборщик, которым считает сторож потери разделов (своя
копия разошлась бы с ним при первой правке). Храповика пока нет НАМЕРЕННО: база на 83
строки учит дописывать в неё, пока не измерено, сколько из них настоящие фантомы, а
сколько — законные заголовки без пробела.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1077 (следующему циклу)

**0. ЦЕПЬ: заказ G1059 ОСТАЁТСЯ ЖИВЫМ ЦЕЛИКОМ; заказ G1073 жив в пп. 2–26; заказ G1076
жив в пп. 2, 3, 6, 7, 12–16 и лежит ВЫШЕ в этой же карточке.** Переписывать их сюда я не
стал НАМЕРЕННО: копия заказа есть удвоение веса. **Заказ G1075 СЖАТ в архив этим
циклом**, и его живые пункты перенесены СЮДА (пп. 10–17) ДО снятия — иначе указатель
остался бы без предмета. Следствие прежнее: сжимать «Заказ G1076» можно только ПОСЛЕ
переноса его живых пунктов в свой заказ.

**1. Вердикт контрольного прогона цикла #1237 — ПРОЧИТАТЬ ПЕРВЫМ ДЕЛОМ.** Номер и
ПОЛНАЯ sha — в пост-записи ниже. База сравнения — **`45450462551`** (**70** имён, мой
замер). Команда одна, ось шарда она спрашивает САМА: `python3
scripts/ci_control_verdict.py --delta 45450462551 <новый>`. Код **2** при непустом
«ПРИШЛО» означает «переехало / ось слепа», а НЕ «ничего не найдено». Перед сличением
спроси у API, нет ли на той же базе прогона НОВЕЕ.

**⚠️ База у этой дельты шумная по роду часов, и счёт назван.** В `45450462551` род
`pytest-timeout` несёт **22** имени, род `runner_environment` — **11**; оба в вилку
дефектов НЕ входят, вилка — **31…37**. Сличать ТОЛЬКО по именам и по ОБОИМ счётчикам, и
у каждого пришедшего имени смотреть РОД прежде оси переезда.

**2. НОВОЕ (ADR-1092): предмет закрыт у ОДНОГО сторожа, а КЛАСС «одно правило — N
спорящих копий» на инварианте #3 НЕ ИЗМЕРЕН.** Копий правила ТРИ, и они расходятся по
ДВУМ осям сразу:

| копия | как решает | модули | каталоги | дверь-запуск |
|---|---|---|---|---|
| `spa_core/ci/llm_forbidden_lint` (канон) | **AST** | **5** (вкл. `litellm`) | 4 | есть |
| `scripts/lint_llm_forbidden.py` (CI) | регулярные выражения по НАЧАЛУ строки | 5, но `llama` вместо `litellm` | 7 | есть |
| `spa_core/monitoring/rules_watchdog` | **теперь канон** (было: подстрока) | канон | 3, оба перечня ПЕЧАТАЮТСЯ | канон |

То есть `litellm` невидим CI-линтеру, а `llama` — канону и стороже. **Население класса НЕ
ИЗМЕРЕНО и нулём это не считается.** Начинать с переписи «модуль ↔ какой перечень его
называет» и «каталог ↔ какой перечень его называет», а НЕ с добавления имён наугад
(дословно правило G1076 п. 3). Выравнивать область охраны сторожа наугад тоже запрещено:
молчаливое расширение вынесло бы вердикт о домене, про который он никогда не говорил.

**3. НОВОЕ И ПРО СЕБЯ: выживший мутант бывает дефектом СЦЕНЫ, и ПЕРВЫЙ прогон контроля
нашёл ровно это.** Сцена `_door_absence_is_clean` делегировала в
`w.check_llm_forbidden_violations`, которую `monkeypatch` в тот момент уже заменил на неё
саму ⇒ `RecursionError`, и проба честно ответила `unmeasured`. Прочитать это как находку
о коде значило бы пойти чинить несуществующее. Настоящая функция связана на импорте
(`_REAL_CHECK`). Правило: подмена мерит СЕБЯ, если сцена зовёт имя, а не связанную
ссылку.

**4. НОВОЕ: различающую сцену надо писать ДО мутационного прогона, а не после.** Два
звена пробы («дверь неполна» и «двери нет») ловили друг друга, поэтому снятие первого
мутация бы не убила — и выживший мутант указал бы на отсутствие РАЗЛИЧАЮЩЕЙ сцены, а не
на дефект кода (урок #1202, третий повтор). Сцена `_only_a_half_door_is_clean` написана
ДО прогона именно по этому предвидению; то же — тест притязания `decision_by`
(литерал вместо `getattr` иначе выжил бы).

**5. НОВОЕ: находка офиса возрастом 632 ч была УСТАРЕВШЕЙ, и прибор это опроверг.**
`cio_architecture_constraints` (помечен «ВЫВОД ПРЕЖНЕЙ РЕДАКЦИИ») утверждал: «дверь-
subprocess к бинарю claude … НЕТ (0 нарушений)». Спросил прибор ИЗ ДЕРЕВА, а не
напечатанное: у `scripts/lint_llm_forbidden.py` дверь-запуск ЕСТЬ и работает
(`Launch door: scanned 398 files, found 0 violations`). Правило подтверждено: при метке
«вывод прежней редакции» действовать по напечатанному запрещено — только перемер.

**6. ВНИМАНИЕ: `STATE.md` снова на ПРЕДЕЛЕ — запас 4 строки / 274 символа / 5 в
длиннейшей** (146 / 29 726 / 695 при пределах 150 / 30 000 / 700). Место этот цикл
ЗАРАБОТАЛ сжатием ЖИВЫХ строк, потому что указателей не осталось (G1076 п. 8 это и
предсказал): четыре строки (`ADR-1063`, `ADR-1067`, `ADR-1068`, `ADR-1069`, суммарно
1587 символов) свёрнуты в один указатель, и адрес КАЖДОГО спрошен ДО снятия — у всех
четырёх есть строка реестра, файл решения и запись в `docs/journal/2026-W47.md`.
Освобождено 909 символов / 3 строки. **Следующему циклу снова придётся сжимать живые
строки**, и адрес спрашивать ДО снятия, а не по памяти.

**7. ВЕС приказа: запас СТРОЧНЫЙ и равен ~150 строкам** после этого заказа (2863 строки
до заказа против держателя максимума `agent-audit-2026-08-02-fix-tracks.md` — **3015**).
Сжатие этот цикл СДЕЛАЛ ПЕРВЫМ делом (правило G1075 п. 8): раздел «Заказ G1075»
перенесён в архив `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-24.md`,
заголовок сохранён ПОБАЙТОВО, тело заменено указателем, и сверены ОБА вопроса — в архиве
найдено **86 из 86** непустых строк, заголовков в карточке было 41 и стало 41, ПРОПАЛО
**0**. Правка шла ОДНИМ проходом по сегментам, а не `replace` в цикле по мутирующей
строке (авария #1233).

**8. НИ ОДНА строка прозы не начинается с решётки** (урок #1236 / G1076 п. 16): проверено
у этого заказа и пост-записи. Класс по трекеру (**83** строки в **69** карточках) по-
прежнему НЕ закрыт — чинить не прицепом, а карточкой со своей пробой, и дверью проверки
обязан стать тот же разборщик, которым считает сторож потери разделов.

**9. ПЕРЕНЕСЁН: два артефакта офиса НЕ ПРОЧИТАНЫ ДВАДЦАТЬ ТРЕТИЙ цикл подряд** (замер
цикла #1237: офис **145 / 2** — `data/acceptance_tree_lineage.json` и
`data/step_time_drift.json`). Причина чужая и названа: `com.spa.decision_loop` во флоте
не загружен, включение — действие ВЛАДЕЛЬЦА (ADR-1053/1061). Дубля не заводить. Офис
звать С `--data-dir <прод>/data`.

**10. ПЕРЕНЕСЁН из G1075 п. 2: класс «мера объявляет пропуск тестов, а спрашивает ИМЯ
файла» закрыт у ОДНОЙ двери, а за её пределами НЕ ИЗМЕРЕН.** Прибор —
`scripts/test_membership_door_census.py` (`--repo-root <дерево>`, коды 0/1/2/3), приёмка
— проба `test_membership_is_asked_about_place_not_name`. Судится ОДНА дверь ОДНОГО модуля
(`spa_core/analytics/architecture_audit.py`); любая другая мера, решающая «это тест?» по
имени файла, этой мерой НЕ судится.

**11. ПЕРЕНЕСЁН из G1075 п. 3: расхождение вердикта мерой класса НЕ является, и причин
ДВЕ.** Первая известна (ADR-897: «красен сегодня» мерой класса не является). Вторая
жёстче: **у СЛОМАННОЙ двери расхождение вердикта равно нулю ПО ПОСТРОЕНИЮ** — обе
сравниваемые формы совпадают, — а население равно единице. Любой дифференциальный прибор
обязан считать НАСЕЛЕНИЕ отдельно от РАСХОЖДЕНИЯ и печатать оба.

**12. ПЕРЕНЕСЁН из G1075 п. 5: сводное число мерки не принимать, пока не напечатаны
ЕДИНИЦЫ.** Подтверждено уже четырьмя циклами подряд (#1234, #1235, #1236, #1237).

**13. ПЕРЕНЕСЁН из G1075 п. 6: мутация без ДОЕХАВШЕЙ до мерки сцены ВЫЖИВАЕТ, и это
дефект сцены, а не кода.** Выжившую мутацию записывают, а не замазывают.

**14. ПЕРЕНЕСЁН из G1075 п. 9: ответ владельца про earn-defi KC-1 ЗАФИКСИРОВАН, действие
— ЗА ВЛАДЕЛЬЦЕМ.** Перемер дверью `python3 -m earn_defi status` (только чтение) 24.11:
`system_mode` **INCIDENT**, блокировка НЕ снята. Это НЕ находка и НЕ повод переспрашивать
(ADR-1089, карточка `ingested`). Снято ⇒ сверить режим на пульте и в боте и записать итог
в журнал.

**15. ПЕРЕНЕСЁН из G1075 п. 11: заказывать прогон ДВЕРЬЮ, а не `curl`-ом** (ADR-1083):
`python3 scripts/ci_control_verdict.py --order-run <ПОЛНАЯ 40-hex sha>`. Заказывать ОДИН
раз, на ПОСЛЕДНЕЙ вершине доставки; такт расписанного прогона дверь называет САМА, число
из прозы НЕ перепечатывать.

**16. ПЕРЕНЕСЁН из G1075 п. 12 и G1076 п. 12, ПЕРЕМЕРЕН: предсуществующая краснота в
поле моей доставки.** `test_edge_boundary_dataflow_census.py::TestTheObserverIsNotPartOfItsOwnPopulation::test_the_census_screens_the_population_100_published`
красен на ЧИСТОМ `origin/main` третий цикл подряд. Не моя, но и не починенная. Чинить У
ПИСАТЕЛЯ, с пробой до работы.

**17. ПЕРЕНЕСЁН из G1075 п. 8 и G1076 п. 9: сжимать приказ ПЕРВЫМ делом цикла, а не
последним.** Сжатие дверью ADR-1066 с первой попытки унесло три заголовка у #1233;
делать его последним действием — приглашать ту же аварию. Сверять ДВА вопроса (попало в
архив · не пропало из карточки), второй — ПО ЗАГОЛОВКАМ.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1078 (следующему циклу)

**0. ЧИТАТЬ ПЕРВЫМ: ДОСТАВКА НА `origin` БЫЛА ОСТАНОВЛЕНА.** Единственный ключ
`GITHUB_PAT_SPA` истёк 2026-11-24 (ADR-1093): замер 20:48Z — `401 Bad credentials`, при
том что в 19:45:50Z он ещё пушил. Дорог измерено ТРИ и закрыты все три (API 401 · `gh`
отсутствует · SSH `publickey`); чтение без ключа работает, репозиторий публичный.
**Первое действие цикла — спросить ключ, а не заказывать прогон:**
`curl -sI -H "Authorization: Bearer $(security find-generic-password -s GITHUB_PAT_SPA -w)"
https://api.github.com/user | head -1`. Ответ 401 ⇒ доставки нет, и это НЕ повод
переспрашивать владельца: карточка `own-klyuch-github-protuh-dostavka-ostanovlena` уже
открыта и уведомление ушло (Telegram `message_ids=[11691]`).

**1. РАБОТА ЦИКЛА #1238 НЕ НА `origin`.** Она лежит в локальной ветке
`rescue/c1238-token-expired` (worktree `/Users/yuriikulieshov/Documents/SPA_worktrees/c1238`,
база `ea5199701`): ADR-1093 + строка реестра · две карточки · строка `docs/STATE.md` ·
запись `docs/journal/2026-W48.md` · пересобранный `_BOARD.md` · ЭТОТ заказ. Ключ ожил ⇒
довезти ЭТО первым делом, одним пушем, прежде любой новой работы. Набор зелен: 35 модулей,
выведенных ИЗ БАЙТОВ доставки, — **958 passed / 1 skipped / 0 failed**.

**2. ВЕРДИКТ ПРОГОНА #1237 ТАК И НЕ ИЗМЕРЕН** — `--delta 45450462551 45473114837` ответил
`НЕ ИЗМЕРЕНО: HTTP 401`. База сравнения остаётся **`45450462551`** (70 имён; род
`pytest-timeout` 22, род `runner_environment` 11, вилка дефектов 31…37). Прогон
`45473114837` был заказан #1237 и, вероятно, успел отработать до смерти ключа — спросить
его первым, а НЕ заказывать новый на той же базе.

**3. СЖАТИЕ ПРИКАЗА ЭТИМ ЦИКЛОМ НЕ ДЕЛАЛОСЬ НАМЕРЕННО** (G1077 пп. 7/17): недоставляемая
правка единственной копии приказа — приглашение к аварии #1233. Запас веса ПЕРЕМЕРЕН после
этого заказа и напечатан в пост-записи ниже. Сжимать обязан первый же цикл с живой
доставкой, кандидат прежний — «Заказ G1076» и только ПОСЛЕ переноса его живых пунктов.

**4. ПОЧИНКА СТОРОЖА СРОКА — карточка `inbox-strazh-sroka-klyucha-ne-sprashivaet-github`**
(`new`, пробу объявляет берущая сессия). Сторож НЕ был слеп: он сказал `WARNING "due soon:
2026-11-24 (0 days)"` за 45 минут до смерти — и был девятым предупреждением из девяти при
`overall_status` `WARNING` и без него. Чинить три вещи, а не одну: лестница (`is_overdue =
days_until < 0` ⇒ `CRITICAL` только НА СЛЕДУЮЩИЙ день) · голос (`WARNING` не рождает
карточки) · наблюдение (GitHub не спрашивается НИ РАЗУ — 0 попаданий `api.github|urlopen`).

**5. ПЕРЕНЕСЕНЫ ЦЕЛИКОМ:** заказ G1059 · G1073 пп. 2–26 · G1076 пп. 2, 3, 6, 7, 12–16 ·
G1077 пп. 2–5, 8–17. Ни один не двигался: кода этот цикл не менял ни байтом.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1079 (следующему циклу)

Полный разбор — журнал `docs/journal/2026-W48.md`, запись цикла #1240. Здесь только то,
что меняет ДЕЙСТВИЕ.

**0. КЛЮЧ СПРОСИТЬ ПЕРВЫМ** (G1078 п. 0). Замер #1240 2026-11-25T00:0xZ: **401**. Ответ
200 ⇒ довезти ВЕРХНЮЮ ветку стека, она содержит две нижние: c1238 → c1239 →
`rescue/c1240-work`, база `ea5199701`. Доставка цепочки — ПЕРЕД новой работой.

**1. G1078 п. 2 ИСПОЛНЕН; прогон на той же базе НЕ ЗАКАЗЫВАТЬ.** Вердикт `45473114837`
измерен БЕЗ ключа (ADR-1095 §7): `completed`/`failure`/`424d23c05`, джоб 14, упало 13,
отменён НЕ был; артефакт `ci-control-report` ЖИВ ⇒ дельта к `45450462551` снимается
первым циклом с ключом одним зовом. Имена падений без ключа неизмеримы (ZIP=401 и
анонимно) — это НЕ «их нет».

**2. ПРЕДСУЩЕСТВУЮЩЕЕ КРАСНОЕ В ПОЛЕ ДОСТАВКИ — ОДНО, и оно НЕ от #1240.**
`test_tier_curator.py::test_no_module_consumes_report_to_mutate_tiers` красен и на чистой
базе (перемерено в одноразовом дереве БЕЗ моих байтов). Сторож судит ПОДСТРОКОЙ:
`cadence_census.py:302` называет `tier_curator` ДАННЫМИ; починка #875 была белым списком
имён и класс не закрыла. Карточка `inbox-storozh-tira-sudit-podstrokoi-imya-kurat`
(`new`). Дописывать модуль в `allowed` ЗАПРЕЩЕНО (инв. #16).

**3. ЗАПАС ВЕСА ПРИКАЗА — ЗАМЕР, не константа: 3010 строк из 3016**, предел держит ЧУЖАЯ
карточка `agent-audit-2026-08-02-fix-tracks.md`; бьёт ось СТРОК (символов ~120 тыс из
174 982, длиннейшая 447 из 4244). Сжатие G1078 п. 3 — не «когда-нибудь»: свой заказ
следующий цикл не впишет, не вынеся прежние в архив дверью ADR-1066.

**4. ПЕРЕНЕСЕНЫ ЦЕЛИКОМ:** G1059 · G1073 пп. 2–26 · G1076 пп. 2, 3, 6, 7, 12–16 · G1077
пп. 2–5, 8–17 · G1078 п. 3 (см. п. 3) и п. 4 (сторож срока ПОЧИНЕН #1239 / ADR-1094, но
НЕ ДОСТАВЛЕН — в проде прежний слепой код).

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказы G1082…G1086 (живой — G1086, следующему циклу)

Полный текст ВСЕХ — `docs/journal/2026-W48.md`, записи циклов #1243…#1247; живой заказ — **G1086**, он перечисляет перенесённые пункты предшественников сам. КЛЮЧ СПРОСИТЬ ПЕРВЫМ (G1086 п. 0): замер 2026-11-25 12:19Z — `GITHUB_PAT_SPA` отвечает **401**, доставки нет, верхняя ветка стека `rescue/c1247-work`.

### Контрольный прогон цикла #1237 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `424d23c05bb2198688070a490c32f493f8de763f` — **13**
файлов, база пинована `--expected-base b74fd8cbced162767515e3d62f70a4cee07b1826`; слепок
байтов сверен у **36** чтений, режимов — у **4**, разбор уезжающего Python — **4** файла.
Флагов обхода не было ни одного; origin за цикл не сдвинулся (пин снят на той же вершине,
с которой начинался цикл). Ворота пушера прошли молча: колонка «Заголовок» реестра — все
**197** строк в пределе 200 (моя 108), строка доски названа у **обеих** уезжающих
карточек, подделанной записи ответа владельца нет, модулей аналитики в наборе нет.

**НЕ доставлено НАМЕРЕННО:** `landing/src/data/site_numbers.json` — витрина собрана шагом
1е (код **4**, ворота публикации отказали названными находками), файлы сайта уезжают
ТОЛЬКО через `safe_site_push.py`, карточка владельца уже открыта. Байты витрины в дереве
доставки возвращены к origin-версии, чтобы она не уехала попутно.

**Заказан прогон `45473114837`** (`SPA CI control`) на ПОЛНОЙ sha `424d23c05…` дверью
`ci_control_verdict.py --order-run` (ADR-1083), а не `curl`-ом: группа `ci-control` FREE,
идёт 0, ждёт 0, код **0** «ЗАКАЗАН и ЖИВ (`queued`), HTTP 204». Ближайший расписанный
прогон дверь назвала САМА: **2026-11-25T00:23:00Z**. **Вердикт НЕ ИЗМЕРЕН**, база
сравнения для следующего цикла — **`45450462551`** (**70** имён, мой замер; род
`pytest-timeout` 22, род `runner_environment` 11, вилка дефектов 31…37).

**Второй вершины с заказом у этого цикла НЕТ намеренно** — пост-запись есть вторая
вершина доставки, но прогона она не получает: заказ на неё сделал бы мой же заказ на
вершине кода ожидающим вторым и убил бы его.

**Дифференциальный прогон 50 модулей, выведенных ИЗ БАЙТОВ** (`derived_artifact_census
--surface --json` ∩ каталоги доставки = 46 сторожей, плюс 4 прямых соседа правленых
модулей):

| дерево | исход |
|---|---|
| ЧИСТЫЙ `origin/main` `b74fd8cbc` (`spa_c1237clean`) | **2 failed** / 1253 passed / 1 skipped |
| моё дерево | **0 failed** / 1298 passed / 1 skipped |

Упавшие на чистом дереве — РОВНО два имени регрессии
(`test_rules_watchdog_honesty::test_healthy_state_reports_ok`,
`test_policy_enforcer::test_check_llm_forbidden_violations`), то есть предсуществующей
красноты в поле этой доставки НЕТ, и своей регрессии тоже нет. Финальная сверка
документных и карточных сторожей шла в ОТДЕЛЬНОМ свежем дереве `spa_c1237final` на
финальных байтах — **438 passed / 1 skipped**.

**Мутации: два прогона, и первый нашёл ОДНУ настоящую дыру и ОДИН дефект моей сцены.**
Первый (`spa_c1237mut`) — 13 применено / 11 убито / **2 выжило**:

* **M06** («имя решившего подменено литералом») выжил не из-за кода: контроль шума того
  прогона честно напечатал «уже красных имён 1», и этим именем был МОЙ ЖЕ тест
  `test_the_verdict_names_the_door_that_actually_decided` — его первая редакция задавала
  `__name__` в теле КЛАССА, а у класса это имя отдаёт метакласс. Дефект СЦЕНЫ, не кода;
* **M11** («звено пробы ТРЕТИЙ ИСХОД снято») — **настоящая дыра покрытия**: соседнее
  подзвено «SKIPPED без имени файла» ловило ту же сцену и тем же словом, поэтому снятие
  первого подзвена вердикта не меняло. Закрыто РАЗЛИЧАЮЩЕЙ сценой
  `_unparsed_is_a_violation` (неразбираемый файл объявлен НАРУШЕНИЕМ, но в `unscanned`
  назван) — без неё мера перестала бы отличать `CRITICAL` от `SKIPPED` на том же файле.

Второй прогон в СВЕЖЕМ дереве `spa_c1237mut2` на ФИНАЛЬНЫХ байтах — **13 применено / 13
убито / 0 выжило / НЕ ПРИМЕНЕНО 0**, и контроль шума там сказал «упавших имён нет — контур
зелен», то есть все тринадцать убийств честные. Окно прибора снято в ОБОИХ деревьях, байты
сверены ПОБАЙТОВО; `--window-check` у всех трёх деревьев (включая дерево доставки) — код 0.

**Шаг 1г** — «Бомб нет: при задержке 95 мин ни один вердикт не изменился» (дерево НАЗВАНО
входом `--repo-root`, одноразовое `spa_c1237anchor`).

**Шаг 2 (инжест ответов владельца) отработал не вхолостую, и ноль ИЗМЕРЕН:** `owner-done`
на `origin/main` — **0** (спрошено `git grep` по вершине origin, а не читателем очереди:
он мерит ПРОД-копию трекера, и это дало бы ответ о другом носителе).

**ОТСТУПЛЕНИЕ, названное как есть.** Дифференциальный прогон моего дерева шёл В ДЕРЕВЕ
ДОСТАВКИ, а `.claude/rules/deployment.md` § «БАЙТЫ, КОТОРЫЕ НЕ ЯВЛЯЮТСЯ КОДОМ» п. 1 этого
не разрешает. Цена проверена, а не предположена: md5 трёх из четырёх правленых файлов до и
после прогона СОВПАЛИ побайтово (`3a875422…`, `77756c52…`, `4cec4441…`), четвёртый сменился
МОИМИ правками, и финальная сверка всё равно шла в отдельном дереве. Следующему циклу:
заводить дерево прогона сразу, а не после.

**Своя проза: строка, начинающаяся с решётки, поймана ДО пуша.** В черновике заказа G1077
одна строка начиналась с `#1237:` — ровно класс G1076 п. 16. Нашла её не вычитка, а
собственная проверка, поставленная перед вставкой раздела: `assert` на любую строку прозы с
решёткой в начале. Исправлено переносом слова; класс по трекеру (83 строки в 69 карточках)
НЕ закрыт и остаётся пунктом 8 заказа G1077.

**Пределы `STATE.md`: 146 строк / 29 726 символов / 695 в длиннейшей** (пределы 150 /
30 000 / 700), запас **4 / 274 / 5**. Место ЗАРАБОТАНО сжатием ЖИВЫХ строк — указателей в
файле не осталось, и G1076 п. 8 это предсказал: четыре строки (`ADR-1063`, `ADR-1067`,
`ADR-1068`, `ADR-1069`, 1587 символов) свёрнуты в один указатель, адрес КАЖДОГО спрошен ДО
снятия (строка реестра + файл решения + запись в `docs/journal/2026-W47.md` — у всех
четырёх). Освобождено 909 символов / 3 строки.

**Вес приказа: сжатие сделано ПЕРВЫМ делом** (правило G1075 п. 8), и сверены ОБА вопроса
на каждом переносе:

| перенесено в архив | непустых строк найдено | заголовки карточки |
|---|---|---|
| «Заказ G1075» (живые пп. перенесены в G1077 ДО снятия) | **86 из 86** | 41 → 41, ПРОПАЛО 0 |
| пост-записи #1234 и #1235 | **82 из 82** | 42 → 42, ПРОПАЛО 0 |

Правка шла ОДНИМ проходом по сегментам, а не `replace` в цикле по мутирующей строке
(авария #1233). `--allow-overwrite` не использован.

**⚠️ ЗАПАС ВЕСА ПЕРЕМЕРЕН ПОСЛЕ пост-записи и он равен 13 СТРОКАМ, а не 150.** Приказ:
2960 → 2902 строки после сжатия и заказа G1077 → **3002** после ЭТОЙ пост-записи, при
держателе максимума `agent-audit-2026-08-02-fix-tracks.md` — **3015**. Число «~150» в
пункте 7 заказа G1077 снято ДО пост-записи и к моменту чтения УСТАРЕЛО: пост-запись стóит
сотню строк, то есть больше, чем весь остаток. **Следующий цикл обязан сжимать ПЕРВЫМ
делом** — кандидат: «Заказ G1076», и только ПОСЛЕ переноса его живых пп. 2, 3, 6, 7,
12–16 в свой заказ. Пост-запись #1236 эту вершину уже сжала (68 из 68 строк в архиве,
заголовков 43 → 43, ПРОПАЛО 0), и ПОСЛЕ неё запас — **81 строка**. Это ровно тот дефект, от
которого предупреждает G1074 п. 4: сводное число мерки не принимать, пока не перемерено
на том состоянии, о котором утверждаешь.

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

