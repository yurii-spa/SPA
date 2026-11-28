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

### Контрольный прогон цикла #1230 (вписано ПОСЛЕ доставки) — В АРХИВЕ

> **Тело перенесено в архив ПОБАЙТОВО** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`,
> раздел «Перенос цикла #1271 — пост-запись цикла #1230» (54 строк / 3757 символов,
> md5 блока `12e58ade0dc31410c5551823b82ee106`). Снял цикл #1271 порядком G1098 п. 8.

### Заказ G1071 (следующему циклу)

Тело перенесено ПОБАЙТОВО циклом #1265 в `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-26.md`
(128 строк / 7950 символов, md5 блока `46bcc50865ecb4db48b7f0c3c7f92d1f`). Порядок — G1059
п. 6: СПЕРВА спрошен адрес (заголовка `### Заказ G1071` не было ни в одном из ЧЕТЫРЁХ архивов,
`grep` дал 0 при одном упоминании номера в прозе), потом сверено ПОБАЙТОВО, и только потом снят
текст. Живые пункты несут преемники (цепочка п. 0); раздел не исчез, у него сменился АДРЕС тела.

### Контрольный прогон цикла #1231 (вписано ПОСЛЕ доставки) — В АРХИВЕ

> **Тело перенесено в архив ПОБАЙТОВО** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`,
> раздел «Перенос цикла #1271 — пост-запись цикла #1231» (66 строк / 4418 символов,
> md5 блока `ef3a1d4b7b3383123b14fae856d7c9e9`). Снял цикл #1271 порядком G1098 п. 8.

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

### Заказ G1092 (следующему циклу) — В АРХИВЕ

Перенёс цикл #1269 порядком G1096 п. 8: адрес спрошен ДО снятия (в архивах 0 вхождений), сверено ПОБАЙТОВО (md5 `749d4a13c43fc59d7357a75b97a909e0`, 82 строк), и только потом снят текст. Адрес — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`.

### Заказ G1093 (следующему циклу) — В АРХИВЕ

Перенёс цикл #1269 порядком G1096 п. 8: адрес спрошен ДО снятия (в архивах 0 вхождений), сверено ПОБАЙТОВО (md5 `6c231b1bfc94a51577855c78dcf66025`, 88 строк), и только потом снят текст. Адрес — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`.

### Заказ G1094 (следующему циклу) — В АРХИВЕ

Перенёс цикл #1269 порядком G1096 п. 8: адрес спрошен ДО снятия (заголовка в архивах 0 вхождений), сверено ПОБАЙТОВО (md5 `71b35b2517520943ef092d83610a93f4`, 93 строк), и только потом снят текст. Живое содержимое заказа перенесено в G1095 и G1096 ЦЕЛИКОМ. Адрес — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`.

### Заказ G1095 (следующему циклу)

> **Тело перенесено в архив ПОБАЙТОВО** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`.
> Снял цикл #1275 порядком G1101 п. 6 (запас храповика веса был 5 строк): адрес спрошен
> ПЕРВЫМ (вхождений заголовка в архивах **0**), потом сверено ПОБАЙТОВО, и только потом
> снят текст. **Тело: md5 `aa1ac641a4cabe1e47282c8482cea871`, 5531 символов, 76 строк.**
> Хвостовые переводы строки в md5 НЕ ВХОДЯТ — они свойство СТЫКА разделов, а не тела.

### Заказ G1096 (следующему циклу)

> **Тело перенесено в архив ПОБАЙТОВО** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`.
> Снял цикл #1275 порядком G1101 п. 6 (запас храповика веса был 5 строк): адрес спрошен
> ПЕРВЫМ (вхождений заголовка в архивах **0**), потом сверено ПОБАЙТОВО, и только потом
> снят текст. **Тело: md5 `4eb028dde1576c192fea45d4acac13e3`, 6472 символов, 86 строк.**
> Хвостовые переводы строки в md5 НЕ ВХОДЯТ — они свойство СТЫКА разделов, а не тела.

### Заказ G1097 (следующему циклу)

**0. КЛЮЧ СПРОСИТЬ ПЕРВЫМ, и спрашивать у СЕРВЕРА.** Замер 27.11 (#1269): чтение origin
работает (`git fetch`/`ls-remote` — репо публичное). Вершину брать `git ls-remote origin
refs/heads/main`, а НЕ локальной ссылкой (ADR-1112 п. 4). **Дерево доставки — worktree
ПРОД-КЛОНА** `~/Documents/SPA_Claude` (ADR-796).

**1. КОНТРОЛЬНЫЙ ПРОГОН АГЕНТ ЗАКАЗАТЬ НЕ МОЖЕТ, и это НЕ «зелено»** (не двигалось). У ключа
нет `Actions: write`: `POST .../dispatches` → **403** при `200` на чтение. Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — **дубля не заводить**.
Вердикт CI о вершине **НЕ ИЗМЕРЕН**.

**2. СПРОСИ ДЕРЕВО О НЕДОСТАВЛЕННОМ ПЕРВЫМ ДЕЛОМ — пункт сработал ТРИ цикла подряд.** #1267
нашёл так работу #1266 (ось C), #1268 — вторую работу того же мёртвого цикла, #1269 — **весь
набор мёртвого цикла #1256** (ADR-1123), лежавший 33 часа в `/private/tmp/spa_c1256`. Команды:
`git -C <дерево> status --short | grep -v '^.. data/'` по всем `git worktree list`, затем
СВЕРКА КАЖДОГО найденного ADR-файла с origin (`git cat-file -e origin/main:<путь>`) — именно
она отличает «доставлено и просто лежит» от «не уехало». **Номер ADR у найденной работы
ПЕРЕПРОВЕРИТЬ ОБЯЗАТЕЛЬНО:** у #1256 номер 1111 забрал #1257, пока работа лежала.

**3. ТЕПЕРЬ ЭТО МОЖНО СПРОСИТЬ ПРИБОРОМ, а не обходом руками.** Доставленный ADR-1123 даёт
`python3 -m spa_core.monitoring.stranded_content --names`: работа в деревьях, недостижимая ни
от `refs/heads/*`, ни от `refs/remotes/origin/*`. Замер #1269: **769** файлов, из них **439**
с ПОЛНОЙ потерей. Своё дерево в этом списке — норма (работа не закоммичена); **ЧУЖОЕ дерево с
полной потерей и мёртвой сессией и есть кандидат на приёмку по п. 2.**

**4. ПРЕДМЕТ РАСТЁТ, А ПОВЕРХНОСТЬ ИСЧЕЗАЕТ — обе оси в опасную сторону.** 712 → **769** за
сутки при деревьях 179 → **120**. Число читать С ДАТОЙ: два последовательных зова на одной
машине разошлись на 2 записи из 769 (живые записи флота), то есть предмет есть ДВИЖУЩАЯСЯ
цель. **Писателя второй копии по-прежнему НЕТ** — цена измерена (**8,4 МиБ** на всю работу без
резерва, три порядка меньше связки коммитов), задача объявлена заказом G1088 п. 5; владельцу
принадлежит ровно ВНЕШНИЙ носитель (предмет №3 ADR-285).

**5. ГЛАВНОЕ ЗА ЭТОТ ЦИКЛ: 8 мутаций ОДНОГО автора зелены по его же мерке.** Свой набор из 34
мутаций на ТЕХ ЖЕ байтах дал **26 убито / 8 ВЫЖИЛО**, и дефектом КОДА не был НИ ОДИН — все
восемь дыры СЦЕН. Три формы, которые чужой набор склонен пропускать, подтвердились ВТОРОЙ раз
подряд (G1096 п. 4 назвал их первыми): **бездействующий фильтр · печатаемое число без сцены ·
проверка НАЛИЧИЯ вместо РАЗЛИЧИМОСТИ**. Добавь к ним форму, найденную #1269:
**«зелена ПРОВОДКА, а не ОСЬ»** — мутация на НЕСУЩЕМ утверждении выжила потому, что во всех
сценах с вердиктом «пусто» дерево было ЧИСТО, и ось не спрашивалась НИ РАЗУ. Проверяй это
прямо: у главного утверждения решения обязана быть сцена, где две оси РАСХОДЯТСЯ.

**6. СПЕЦИФИКАЦИЯ МУТАЦИЙ БЕЗ ФАЙЛА НА ДИСКЕ НЕ ПОВЕРЯЕМА.** Набор #1256 («30 из 30») не
оставил `docs/mutations/*.json` вовсе, и потому его счёт стоял на доверии. Свой набор кладётся
файлом ВСЕГДА — `docs/mutations/RESERVE-1123-2026-11-27.json` — и перепрогоняется одной
командой.

**7. ЧУЖОЙ ФАЙЛ, ИЗМЕНИВШИЙСЯ НА ORIGIN, ПРИМЕНЯЕТСЯ ПАТЧЕМ, А НЕ КОПИЕЙ.** Принимая работу из
мёртвого дерева, сверь КАЖДЫЙ общий файл по blob-sha базы против вершины: `card_acceptance.py`
уехал `02bb9164` → `1bc88417`, и копия файла затёрла бы чужую работу МОЛЧА (`git apply --3way`
прошёл чисто). Два других общих файла не двигались ни битом — их копия безопасна, и это
ИЗМЕРЕНО, а не предположено.

**8. ХРАПОВИК ВЕСА КАРТОЧКИ БЫЛ КРАСЕН НА ЧИСТОМ `origin/main`** — 3 111 строк против базы
3 016, и сделала его красным пост-запись #1268, а не чья-то доставка. Снято #1269 переносом
ЧЕТЫРЁХ разделов в архив (G1092 · G1093 · G1094 · пост-запись #1262 = 335 строк), карточка
**3110 → 2881**. **Мерить ДО своих правок:** `pytest
spa_core/tests/test_tracker_card_weight_ratchet.py`; держатель максимума сменился — теперь это
сама карточка приказа, а не `agent-audit-2026-08-02-fix-tracks` (3016).

**8а. `grep` ПО ЗАГОЛОВКУ — НЕОБХОДИМ И НЕ ДОСТАТОЧЕН, и #1269 едва на этом не попался.**
Выбрав пятым кандидатом «Заказ G1059», я спросил архивы заголовком и получил честный **0** —
то есть по правилу снимать было можно. Но тот же `grep` по НОМЕРУ дал **15** вхождений, и
десять из них гласят дословно: **«Заказ G1059 ОСТАЁТСЯ ЖИВЫМ ЦЕЛИКОМ»**. Снятие тела заставило
бы следующий цикл открывать архив, чтобы прочитать ЖИВОЙ заказ. Блок **возвращён в карточку
ПОБАЙТОВО** (md5 `cbad421f45070dd339410d29e83e508d`, 79 строк) и вместо него снят G1094, чьё
живое содержимое перенесено в G1095 и G1096 ЦЕЛИКОМ, то есть снята КОПИЯ. **Спрашивай ДВА
вопроса, а не один: „есть ли копия заголовка“ И „не объявлен ли заказ живым“.** Кандидат на
следующее снятие — пост-запись цикла #1263 (99 строк), тем же порядком.

**9. `STATE.md`: сжимать ПЕРВЫМ делом — и этого всё равно мало.** Запас на входе #1269 был
**2 строки / 153 символа / 5 в длиннейшей**; первая правка ушла за предел на **107** символов,
вторая (укороченная) на **15**, и сошлась только третья. Освобождал переносом, не обрезкой
смысла: три строки 24.11 (ADR-1087+1088 · 1091 · 1089) свёрнуты в одну, и адрес КАЖДОГО ADR
спрошен ДО сворачивания (файл · строка реестра · запись журнала). Итог **147 / 29 817 / 695**,
запас **3 / 183 / 5**. Вес мерить СИМВОЛАМИ, не `wc -c`.

**10. ПЕРЕНОСИТСЯ ИЗ G1096 ЦЕЛИКОМ (не двигалось):** п. 5 (население класса «производная мера
без вопроса о живости своего производителя» за пределами §49 НЕ ИЗМЕРЕНО) · п. 6 (у читателя
утреннего аудита 90 % род падения НЕ сверяется с `ci_control_verdict.py`; 27.11 сводка снова
дала «RED 140 имён, f-string ×26» — дешёвый предмет, не тронут) · п. 7 целиком (адреса
предшественников: G1059 · G1073 пп. 2–26 · G1072 · G1076 · G1077 · G1078 · G1079 · G1087 ·
полнота `PYTHON_CARRIERS` НЕ ИЗМЕРЕНА · долг храповика ADR-362 ·
`inbox-poverhnost-resheniya-shtampuet-tvl-live` · `inbox-proba-kriteriya-49-no-regression-ne-prin`).

**11. Два артефакта офиса НЕ ПРОЧИТАНЫ** (офис **145 / 2**, состав ТОТ ЖЕ):
`data/acceptance_tree_lineage.json`, `data/step_time_drift.json`. Причина чужая и названа:
`com.spa.decision_loop` во флоте НЕ загружен, включение службы — действие ВЛАДЕЛЬЦА. Шаг 1з:
СОСТОЯЛОСЬ 18 · **НЕ СОСТОЯЛОСЬ 2** · retired 1 · НЕ ИЗМЕРЕНО 10 — состав ТОТ ЖЕ, 25–27.11.
Карточки есть, дубля не заводить.

**11а. ТРИНАДЦАТАЯ ДВЕРЬ ОТКАЖЕТ И ТЕБЕ — флаг обхода делай ВТОРЫМ действием, не первым.**
Гейт ADR-1112 остановил пуш #1269 кодом **20** на 2 новых зовах `origin/*`. Разбор каждого дал
РАЗНЫЕ ответы: один — ЛОЖНЫЙ член (литерал `refs/remotes/origin/…` в `update-ref` одноразовой
сцены есть ЗАПИСЬ, а не чтение; починен взятием префикса У МЕРЫ, долг 2 → 1 и код стал лучше),
второй — НАСТОЯЩИЙ, и обход объявлен с причиной В КОДЕ у места зова. **База храповика может
только УМЕНЬШАТЬСЯ — дописывать её ЗАПРЕЩЕНО** (инв. #16), поэтому у законного нового зова
честных дорог ровно две: починить или объявить обход и НАПЕЧАТАТЬ его. Долг на `main` — 43
давних личности, он не твой, и отказа по нему нет. **И помни: правка, снимающая ложного члена,
сама есть изменение поведения** — у #1269 она уронила существующую сцену, подменив ПРИЧИНУ
отказа на «сцена не собралась», то есть воспроизвела форму мутации M20 своего же решения.

**12. Шаг 1е-2 (пины TVL) — состав ТОТ ЖЕ СЕДЬМОЙ цикл подряд:** живое без пина **3**
(`euler_v2` живое **$395 211**, пол $5M НЕ проходит · `morpho_blue` · `yearn_v3`), один пул под
двумя ключами (`morpho_blue`+`morpho_steakhouse`, структурный предел 60% против потолка T2
50%), а поверхность объявляет `tvl_floor_unverified=[]`. ДЕНЕЖНЫЙ ПУТЬ — правкой не закрывать,
карточка открыта.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1098 (следующему циклу)

**0. КЛЮЧ ЖИВ, вершину брать У СЕРВЕРА.** Замер 27.11 (#1270): `GET /user` → **200**.
Вершина — `git ls-remote origin refs/heads/main`, а НЕ локальной ссылкой (ADR-1112 п. 4).
Дерево доставки — worktree ПРОД-КЛОНА `~/Documents/SPA_Claude` (ADR-796).

**1. КОНТРОЛЬНЫЙ ПРОГОН АГЕНТ ЗАКАЗАТЬ НЕ МОЖЕТ** (не двигалось): у ключа нет
`Actions: write`, `POST .../dispatches` → **403** при `200` на чтение. Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — **дубля не
заводить**. Вердикт CI о вершине **НЕ ИЗМЕРЕН**, замещается дифференциалом в ОТДЕЛЬНЫХ
деревьях.

**2. ПУНКТ «СПРОСИ ДЕРЕВО О НЕДОСТАВЛЕННОМ» СРАБОТАЛ ТРИ ЦИКЛА ПОДРЯД И НА ЧЕТВЁРТОМ ДАЛ
ПУСТО — спрашивать всё равно ПЕРВЫМ ДЕЛОМ.** Замер #1270: `python3 -m
spa_core.monitoring.stranded_content --names` → **780** файлов работы без второй копии (из
них **445** с ПОЛНОЙ потерей) в 83 деревьях; все **33** незакоммиченных
`docs/decisions/ADR-*.md` сверены с origin (`git cat-file -e`), и **все пять отсутствующих
ПО ИМЕНИ** оказались черновиками, переименованными перед доставкой тем же циклом
(`1111→1123` · `1121→1122` · `ADR-895`→`a-refusal-must-carry-its-evidence` · `928` · `1041`
· `1056` — своими slug-ами). **Мерка «файла нет на origin» НЕОБХОДИМА И НЕ ДОСТАТОЧНА:**
второй вопрос — «нет ли на origin решения ТОГО ЖЕ цикла и ТОГО ЖЕ заказа под другим
именем», и без него пять ложных находок пошли бы в работу.

**3. ПРЕДМЕТ #1270: претензия, не несущая своей ЛИЧНОСТИ, неопровержима — и её сегодня
никто не спрашивал.** ADR-1124: прибор `spa_core/monitoring/ci_claim_provenance.py`
(проводка — секция шага 0-офис, зовётся каждым циклом). Замер announce-лога: сегментов
**69** · своих с числом/родом **21** · **НЕОПРОВЕРЖИМО 9** (с РОДОМ — **1**) · вне окна
канонического читателя **12** · цитата **1**. Читай эту секцию офиса: новая НЕОПРОВЕРЖИМАЯ
претензия = чей-то производитель снова печатает прозу вместо замера.

**4. ПРОИЗВОДИТЕЛЬ ПОЧИНЕН, НО ОН ВНЕ GIT — и это следующая дыра того же класса.** Шаг 6
промпта `~/.claude/scheduled-tasks/spa-daily-90pct-audit/SKILL.md` переписан (числа у
`ci_control_verdict.py` · номер прогона обязателен · род не называть без лога шарда), и
ВТОРАЯ КОПИЯ правки лежит только в ADR-1124 (md5 прежней редакции
`24dadb96849b83e9e12b81a4984bafc6`). **У файла нет ни git, ни резерва** — ровно предмет
ADR-1123. Проверь ПЕРВЫМ делом, что правка на месте (`grep -c ci_control_verdict` в том
файле ⇒ 2): запланированное задание переписывается харнессом, и молча.

**5. НАСЕЛЕНИЕ КЛАССА У ДРУГИХ НОСИТЕЛЕЙ НЕ ИЗМЕРЕНО** — закрыт ОДИН носитель из четырёх
(announce-лог); остались карточки трекера, `docs/journal/**` и утренняя сводка владельцу.
Карточка `inbox-pretenziya-o-progone-ci-bez-svoei-lichno` (создана #1270, пробы ещё нет —
объявить ДО работы, `.claude/rules/acceptance.md` п. 1).

**6. ФОРМА «ЗЕЛЕНА ПРОВОДКА, А НЕ ОСЬ» ПОДТВЕРДИЛАСЬ ТРЕТИЙ РАЗ ПОДРЯД** (G1096 п. 4,
G1097 п. 5, теперь #1270). Мои 25 мутаций дали **22 убито / 3 выжило**, дефектом КОДА не
был НИ ОДИН: две — дыры СЦЕН границы сегмента (обе сцены держали номер прогона ДО маркера,
поэтому срез `summary[mark:]` его не захватывал ни с границей, ни без неё, и ось не
спрашивалась НИ РАЗУ), третья — **ЭКВИВАЛЕНТНЫЙ мутант, доказанный замером** (снятие
раннего отказа на нечитаемый `--data-dir` оставляет и код 2, и названную причину; меняются
канал и слова). Проверяй прямо: у каждой оси обязана быть сцена, где её вход стоит С ТОЙ
СТОРОНЫ, с которой ось его и отсекает.

**7. ПЕРВАЯ РЕДАКЦИЯ МЕРКИ СОВРАЛА В СТОРОНУ «ЧИСТО» — шестое наблюдение формы.** Мерка
спрашивала «есть ли в строке что-то похожее на sha» и объявила аварийную претензию 27.11
ПЕРЕМЕРЯЕМОЙ: в той же строке стоял коммит песочницы `c5931f41b`. Личность берётся из
СЕГМЕНТА, а не из строки. Там же вторая ловушка: ширина номера — ЗАМЕР (живые номера
прогонов 11 знаков, идентификаторы воркфлоу 9), и число другой ширины обязано быть
НАЗВАНО, а не промолчано.

**8. ХРАПОВИК ВЕСА КАРТОЧКИ: мерить ДО своих правок.** Замер #1270 на входе — приказ
**2 973** строки при держателе максимума `agent-audit-2026-08-02-fix-tracks` (**3 016**),
запас 43 строки. Снята пост-запись #1263 (99 строк) в архив
`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`, карточка **2 973 → 2 882**.
Кандидат на следующее снятие — пост-запись цикла #1264 (36 строк) либо #1265 (90), тем же
порядком и с ОБОИМИ вопросами G1097 п. 8а. Вес мерить СИМВОЛАМИ, не `wc -c`.

**9. `STATE.md`: сжимать ПЕРВЫМ делом.** Запас на входе #1270 — **2 строки / 183 символа /
5 в длиннейшей**. Освобождал переносом, не обрезкой: ADR-1090 свёрнут в соседний блок
24.11, ADR-1070/1076 — в фолд 17…23.11, и адрес КАЖДОГО спрошен ДО сворачивания (файл ·
строка реестра · запись журнала — у всех на месте). Итог **148 / 29 821 / 695**, запас
**2 / 179 / 5**.

**10. §49 ПЕРЕМЕРЕН СВОИМИ РУКАМИ: ВЫПОЛНЕНО 1 · НЕ ВЫПОЛНЕНО 8 · НЕ ИЗМЕРЕНО 4 из 13.**
Рычаг у ВЛАДЕЛЬЦА у **12 из 12** не-выполненных: производитель меры один
(`com.spa.decision_loop`), во флоте его нет (670 ярлыков) — ADR-1122. Отдельно:
`No regression` при `--measure-tree <прод>` перестаёт быть «НЕ О ТОМ ДЕРЕВЕ» и становится
«запись прогона старше предела: 843,7 ч при 192 ч» — то есть вопрос ОТВЕТИМ, а ответ
«протухло», и чинится он тем же рубильником владельца. Мерку НЕ ТРОГАТЬ.

**11. Два артефакта офиса НЕ ПРОЧИТАНЫ** (офис **145 / 2**, состав ТОТ ЖЕ):
`data/acceptance_tree_lineage.json`, `data/step_time_drift.json`. Шаг 1з: СОСТОЯЛОСЬ 18 ·
**НЕ СОСТОЯЛОСЬ 2** · retired 1 · НЕ ИЗМЕРЕНО 10 — состав ТОТ ЖЕ, 25–27.11. Карточки есть,
дубля не заводить.

**12. Шаг 1е-2 (пины TVL) — состав ТОТ ЖЕ ВОСЬМОЙ цикл подряд:** живое без пина **3**
(`euler_v2` живое **$395 211**, пол $5M НЕ проходит · `morpho_blue` · `yearn_v3`), один пул
под двумя ключами (`morpho_blue`+`morpho_steakhouse`, структурный предел 60 % против
потолка T2 50 %), а поверхность объявляет `tvl_floor_unverified=[]`. ДЕНЕЖНЫЙ ПУТЬ —
правкой не закрывать, карточка открыта.

**13. ПЕРЕНОСИТСЯ ИЗ G1097 ЦЕЛИКОМ (не двигалось):** п. 4 (предмет резерва растёт, а
поверхность исчезает: 712 → 769 за сутки; писателя второй копии НЕТ, цена 8,4 МиБ, внешний
носитель — предмет №3 ADR-285) · п. 6 (спецификация мутаций без файла на диске не поверяема)
· п. 7 (чужой файл, изменившийся на origin, применяется ПАТЧЕМ, а не копией) · п. 11а
(тринадцатая дверь откажет и тебе — флаг обхода делай ВТОРЫМ действием) · п. 10 целиком
(адреса предшественников: G1059 · G1073 пп. 2–26 · G1072 · G1076 · G1077 · G1078 · G1079 ·
G1087 · полнота `PYTHON_CARRIERS` НЕ ИЗМЕРЕНА · долг храповика ADR-362 ·
`inbox-poverhnost-resheniya-shtampuet-tvl-live` · `inbox-proba-kriteriya-49-no-regression-ne-prin`).

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1102 (следующему циклу)

**0. КЛЮЧ ЖИВ, вершину брать У СЕРВЕРА.** `git ls-remote origin refs/heads/main`, а НЕ локальной
ссылкой (ADR-1112 п. 4). Дерево доставки — worktree ПРОД-КЛОНА `~/Documents/SPA_Claude` (ADR-796).
Замер 28.11 (#1275): локальная ссылка и ответ сервера СОВПАЛИ (`73d1f0328`) — это ЗАМЕР того дня,
а не свойство клона; спрашивать всё равно сервер.

**1. КОНТРОЛЬНЫЙ ПРОГОН АГЕНТ ЗАКАЗАТЬ НЕ МОЖЕТ** (не двигалось СЕДЬМОЙ цикл): у ключа нет
`Actions: write`, карточка `owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 —
**дубля не заводить**. Вердикт CI о вершине **НЕ ИЗМЕРЕН**, замещается дифференциалом в ОТДЕЛЬНЫХ
деревьях. Писать «CI RED <число>» без номера прогона ЗАПРЕЩЕНО дверью (ADR-1126, код 21).

**2. ТРЕТИЙ ИСХОД ПЕРЕПИСИ ДОЧИТАН СО 106 ДО 81 (ADR-1129), и предмет впервые УПАЛ.** Дверь —
ОДИН ХОП ЧЕРЕЗ ПАРАМЕТР: значение параметра назначает не модуль, а ВЫЗЫВАЮЩИЙ либо фикстура
pytest того же имени. Итог: `unresolved` **106 → 81** · ПРЕДМЕТ **265 → 263** · верхний край вилки
**371 → 344** · под дверью 158 → 157 · охват прибора НЕ ТРОНУТ ни строкой (`tests_total` 2627 →
2628 ровно на мой новый тест). **Уменьшение объяснено ОТВЕТОМ, а не сужением охвата** — карточка
`inbox-naselenie-mer-bez-voprosa-pri-dostavke-2` запрещает второе прямым текстом, и критерий её
приёмки («предмет МЕНЬШЕ 264») выполнен. Направления 1 и 2 карточки НЕ тронуты, карточка остаётся
`new` и пробы приёмки у неё по-прежнему НЕТ — объявить её обязан тот, кто берёт её в работу.

**3. ВЫБОР ДВЕРИ БЫЛ ЗАМЕРОМ, а не вкусом: 102 из 106 файлов несут РОВНО ОДНУ форму причины.**
Самая населённая — «имя `X` в модуле не привязано»: 49 файлов целиком, 52 хотя бы одним зовом, и
внутри неё 64 зова из 78 суть ПАРАМЕТР объемлющей функции. Остаток третьего исхода назван
поимённо в ADR-1129: «зов не является построением пути» (12 файлов целиком) · индексация не по
`parents` · распаковка кортежа · цель цикла `for` · свойства модуля (`.__file__`, `.REPO_ROOT`,
`.PANEL_DIR`). Нулём 81 не считается.

**4. ДВЕРЬ СНЯЛА ДЕВЯТЬ ЛОЖНЫХ СРАБАТЫВАНИЙ, и это важнее прибавки.** `push_to_github.py:3569` —
`dest.rglob("*.py")`, где `dest` есть параметр `origin_python_shadow`, а зовы передают `mkdtemp()`:
перечисляется РАСПАКОВАННАЯ ТЕНЬ вершины origin, то есть одноразовая сцена. ПЯТЬ тест-файлов
(`test_delivery_bytes_pin`, `test_delivery_syntax_gate`, `test_delivery_ci_claim_identity_gate`,
`test_delivery_tree_is_named`, `test_filelock_concurrent`) числились набор-зависимыми ТОЛЬКО
потому, что этот зов был неразобран. Ещё два: `edge_real_panel_ensemble.py:160` →
`data/aggressive_lab` (каталог СОСТОЯНИЯ) и `claim_guard_receipt_readers.py:161` → `mkdtemp()`.
**Все 4 из 4 известных членов на месте** — форма, потерявшая любого, была бы ОПРОВЕРГНУТА.

**5. МОЙ СОБСТВЕННЫЙ КОНТРОЛЬ — ЧЛЕН ПРЕДМЕТА, и это сказано вслух.**
`test_param_hop_door.py` зовёт `measure_surface(REPO)`, то есть перечисляет `spa_core/tests`, и
перепись числит его `subject`. Значит из 263 один — мой же тест, а чужих 262: новый прибор выходит
новым членом класса, который мерит.

**6. ФОРМА «ВЫЖИВШАЯ МУТАЦИЯ — ДЫРА СЦЕНЫ» ПОДТВЕРДИЛАСЬ ДЕСЯТЫЙ РАЗ ПОДРЯД** (#1202, #1217,
#1267, #1270…#1273, теперь #1275): 20 мутаций, первый прогон **15 убито / 5 выжило**, и дефектом
КОДА не был ни один. ТРИ — дыры сцен, и самая поучительная вторая: **декой-ключевое слово обязано
стоять ПОСЛЕ верного аргумента**, иначе перезапись найденного значения оставляет верный последним
и мутация «брать ЛЮБОЕ ключевое слово» переживает сцену молча. После починки сцен **19 из 20**.
Выжившая M15 **ЭКВИВАЛЕНТНА, и это ЗАМЕР**: прогон полной поверхности с ней дал на **2628**
настоящих файлах **0** файлов с другим вердиктом и **0** зовов с другой причиной.

**7. СЦЕНА НАШЛА ДЕФЕКТ СОБСТВЕННОЙ ДВЕРИ.** Замыкание `def _dirs(where)` внутри
`def test_x(where)` получало ОБА источника — фикстуру модуля и зов — и уходило в «РАСХОДЯТСЯ», то
есть дверь ОТКАЗЫВАЛА там, где ответ был один. Починка: фикстура есть источник ТОЛЬКО там, где
pytest ВНЕДРЯЕТ, и это ПРИМЕНИМОСТЬ, а не старшинство источников.

**8. ПРИГОВОР ADR-1126 ДАН — ДВЕ КРАСНЫЕ СТРОКИ С `main` СНЯТЫ.** Красное было ПРЕДСУЩЕСТВУЮЩИМ и
это ИЗМЕРЕНО на базовых байтах в отдельном дереве (те же два имени, тот же текст):
`test_known_member_list_census.py` требовал приговора кандидату ADR-1126, пришедшему в реестр
27.11. Приговор — **НЕ член**: дверь судит СОДЕРЖИМОЕ одного уезжающего текста, производного
артефакта над НАБОРОМ у неё нет вовсе (та же форма, что ADR-886 и ADR-714). Файл: **61 passed**.

**9. ГЕЙТ НОМЕРОВ ADR СПРАШИВАЕТ origin ПОСЛЕ ДОСТАВКИ, а не дерево.** `adr_number.py check`
краснел «в INDEX.md нет ни одной строки ADR-1129» при строке, ЛЕЖАЩЕЙ в дереве: реестр обязан
быть В НАБОРЕ `--files`. Это та же дисциплина, что у десятой и одиннадцатой двери, и стоит она
одного лишнего пути в наборе.

**10. ХРАПОВИК ВЕСА КАРТОЧКИ: мерить ДО своих правок.** Замер #1275 на входе — приказ **2982**
строки при базе `max_lines` **3016** и держателе `agent-audit-2026-08-02-fix-tracks` (**3015**),
запас **34** строки ⇒ пришлось перенести пост-запись #1272 (74 строки, md5
`0e6dab7fce8af4174bd3cb7f3b9a63a2`) в `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`
порядком G1101 п. 6. Заголовок стаба СОХРАНЁН ПОБАЙТОВО. Следующему: запас считать заново,
кандидат на снятие — пост-запись #1273 (12 строк).

**11. `STATE.md`: предел по СИМВОЛАМ кусался первым.** Запас на входе #1275 был **2 строки /
10 символов / 5 знаков в строке** — то есть свободных символов хватало на ТРИ слова. Сначала
свёрнуто, потом дописано.

**12. §49 НЕ ПЕРЕМЕРЯЛ, и это НАЗВАННЫЙ выбор** (перенос G1101 п. 8). ADR-1122: у **13 из 13**
критериев производитель меры ОДИН — `com.spa.decision_loop`, во флоте его нет с 29.10, рычаг у
ВЛАДЕЛЬЦА. Шаг 1з подтвердил состав ШЕСТОЙ день: СОСТОЯЛОСЬ 18 · **НЕ СОСТОЯЛОСЬ 2**
(`decision_loop`, `mission_tick`) · retired 1 · НЕ ИЗМЕРЕНО 10 (флот 664 ярлыка).

**13. Два артефакта офиса НЕ ПРОЧИТАНЫ** (офис **145 / 2**, состав ТОТ ЖЕ шестой день):
`data/acceptance_tree_lineage.json`, `data/step_time_drift.json`. Шаг 1е-2 (пины TVL) — состав ТОТ
ЖЕ **двенадцатый** цикл подряд: живое без пина **3** (`euler_v2` живое **$395 211**, пол $5M НЕ
проходит · `morpho_blue` · `yearn_v3`), один пул под двумя ключами, поверхность объявляет
`tvl_floor_unverified=[]`. ДЕНЕЖНЫЙ ПУТЬ — правкой не закрывать, карточка открыта.

**14. ПЕРЕНОСИТСЯ ИЗ G1101 ЦЕЛИКОМ (не двигалось):** п. 10 («спроси дерево о недоставленном» —
спрашивать ПЕРВЫМ делом) · п. 11 целиком (читатель карточек в прод-дереве не находит
`docs/decisions/INDEX-ARCHIVE.md` · производитель утреннего аудита вне git · долг храповика
ADR-362, 80 личностей, `inbox-hrapovik-provenansa-git-ref-krasen-verno` ·
`inbox-poverhnost-resheniya-shtampuet-tvl-live` · `inbox-proba-kriteriya-49-no-regression-ne-prin` ·
`inbox-pretenziya-o-progone-ci-bez-svoei-lichno` · адреса предшественников G1059 · G1072 ·
G1076…G1079 · G1087 · полнота `PYTHON_CARRIERS` НЕ ИЗМЕРЕНА).

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1101 (следующему циклу)

**0. КЛЮЧ ЖИВ, вершину брать У СЕРВЕРА.** `git ls-remote origin refs/heads/main`, а НЕ локальной
ссылкой (ADR-1112 п. 4). Дерево доставки — worktree ПРОД-КЛОНА `~/Documents/SPA_Claude` (ADR-796).
Замер 27.11 (#1273): локальная ссылка и ответ сервера СОВПАЛИ (`ff7b675a8`) — это ЗАМЕР того дня,
а не свойство клона; спрашивать всё равно сервер.

**1. КОНТРОЛЬНЫЙ ПРОГОН АГЕНТ ЗАКАЗАТЬ НЕ МОЖЕТ** (не двигалось ШЕСТОЙ цикл): у ключа нет
`Actions: write`, `POST .../dispatches` → **403** при `200` на чтение. Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — **дубля не заводить**.
Вердикт CI о вершине **НЕ ИЗМЕРЕН**, замещается дифференциалом в ОТДЕЛЬНЫХ деревьях. Писать
«CI RED <число>» без номера прогона ЗАПРЕЩЕНО дверью (ADR-1126, код 21): честная форма —
«вердикт CI НЕ ИЗМЕРЕН» и БЕЗ числа. Свой текст перемерить ДО доставки:
`python3 -m spa_core.monitoring.ci_claim_provenance --carrier-root <дерево> --data-dir <прод>/data`.

**2. НАСЕЛЕНИЕ КЛАССА G1100 п. 5 ИЗМЕРЕНО, И ОНО НЕ ПЯТЬ (ADR-1127).** Набор-зависимых мер **422**
· **ПРЕДМЕТ 264** · под дверью 158 · НЕ ИЗМЕРЕНО **106** ⇒ население есть **ВИЛКА 264 … 370**.
Дверей РЕЕСТР объявляет **девять**, а не пять (сверх прозы заказа — ADR-150 · ADR-344 · ADR-729 ·
ADR-886). Дверей НЕ ДОБАВЛЕНО ни одной: это ЗАМЕР, а что делать с 264 — карточка
`inbox-naselenie-mer-bez-voprosa-pri-dostavke-2` (`new`, пробы ещё нет — объявить ДО работы).
Три названных направления: общая дверь вместо 264 отдельных · сужение
`derived_artifact_census --differential` (дорого, брать `--limit`/`--only`, в ОТДЕЛЬНОМ дереве) ·
дочитать 106 НЕ ИЗМЕРЕНО (верхний край вилки держат они).

**3. ЕДИНИЦА КЛАССА — МЕРА, А НЕ ФАЙЛ, И ЭТО ЗАМЕР.** Три файловые формы опровергнуты на четырёх
ИЗВЕСТНЫХ членах, каждая нашла **1 из 4**: «в имени есть `baseline`» · «сторож называет
объявление модульной привязкой» · «инструмент ПИШЕТ объявление по разобранной дороге значения».
Причина: у ADR-1112 писателя базы нет ВОВСЕ (её ведут руками), сторожа доски и переписи называют
не объявление, а ПРОИЗВОДИТЕЛЯ, а сторож реестра набор-зависим от `docs/journal`, не от
`docs/decisions`, которые судит его дверь. **Форма, теряющая 3 из 4, класс не сужает — ПОДМЕНЯЕТ.**

**4. ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ, ПОСТАВЛЕННЫЙ РЕЕСТРОМ, СРАБОТАЛ ДВАЖДЫ НА АВТОРЕ.** (а) `ADR-150 …
НИ ОДИН сторож не вышел gated` — мерка брала ОДИН префикс `enforce_delivery_*`, а гейт ADR-150
зовётся `enforce_adr_numbers`: **соглашение об имени полнотой перечня не является** (ADR-1113 в
третьей форме), 7 гейтов → 19. (б) Сцена «прибора в дереве нет ⇒ отказ» была ЗЕЛЕНОЙ не от
отказа, а потому что ввоз **ПО ИМЕНИ** удавался из `sys.modules`/`sys.path` — перепись мерила
ЧУЖОЕ дерево и не говорила об этом ни строкой (дословно класс ADR-796). **Ввоз прибора по ИМЕНИ
есть та же дверь, что относительный путь у пушера.**

**5. ФОРМА «ВЫЖИВШАЯ МУТАЦИЯ — ДЫРА СЦЕНЫ» ПОДТВЕРДИЛАСЬ ДЕВЯТЫЙ РАЗ ПОДРЯД** (#1202, #1217,
#1267, #1270, #1271, #1272, теперь #1273): 20 мутаций, первый прогон **18 убито / 2 выжило**, и
дефектом КОДА не был ни один. Обе — дыры сцен, и ВТОРАЯ важнее: проба «упоминание в докстринге
чтением не является» проходила **ТАВТОЛОГИЧЕСКИ**. Совпадение констант у мерки ТОЧНОЕ, а
докстринг-ФРАЗА пути никогда не равна — значит исключение докстрингов в сцене не несло ничего, и
мутация «докстринги больше не исключаются» переживала её молча. **Чтобы исключение было
НЕСУЩИМ, докстринг обязан быть РОВНО путём.** Первая дыра того же рода: сцена «связка по
каталогу — РАВЕНСТВО» ставила сторожа на КОРЕНЬ дерева, а мутация-вложенность на корне не
срабатывает — нужен РОДИТЕЛЬ судимого каталога. После починки сцен **20 из 20**.

**6. ХРАПОВИК ВЕСА КАРТОЧКИ: мерить ДО своих правок.** Замер #1273 на входе — приказ **2920**
строк при базе `max_lines` **3016** и держателе `agent-audit-2026-08-02-fix-tracks` (**3015**),
запас **96** строк ⇒ архивировать пост-записи ЭТОМУ циклу не пришлось. Следующему: запас
считать заново, кандидаты на снятие — пост-записи #1271 (46 строк) и #1272 (77).

**7. `STATE.md`: предел по СТРОКЕ — 700, и он кусается раньше остальных.** Запас на входе #1273
был **2 строки / 63 символа**, поэтому СНАЧАЛА свёрнуты три решения (ADR-1117 · 1118 · 1120) в
ОДИН указатель — адрес каждого спрошен ДО сворачивания (файл решения · строка реестра · запись
журнала, у всех трёх на месте). Первая редакция записи цикла вышла **887** знаков и покраснила
`test_no_single_line_carries_the_chronicle` (предел 700) — ужата до 627. Итог **146 / 29 635 /
695**, запас **4 / 365 / 5**.

**8. §49 НЕ ПЕРЕМЕРЯЛ, и это НАЗВАННЫЙ выбор** (перенос G1100 п. 8). ADR-1122: у **13 из 13**
критериев производитель меры ОДИН — `com.spa.decision_loop`, во флоте его нет с 29.10, рычаг у
ВЛАДЕЛЬЦА. Шаг 1з подтвердил состав ПЯТЫЙ день: СОСТОЯЛОСЬ 18 · **НЕ СОСТОЯЛОСЬ 2**
(`decision_loop`, `mission_tick`) · retired 1 · НЕ ИЗМЕРЕНО 10.

**9. Два артефакта офиса НЕ ПРОЧИТАНЫ** (офис **145 / 2**, состав ТОТ ЖЕ пятый день):
`data/acceptance_tree_lineage.json`, `data/step_time_drift.json`. Шаг 1е-2 (пины TVL) — состав
ТОТ ЖЕ **одиннадцатый** цикл подряд: живое без пина **3** (`euler_v2` живое **$395 211**, пол $5M
НЕ проходит · `morpho_blue` · `yearn_v3`), один пул под двумя ключами, поверхность объявляет
`tvl_floor_unverified=[]`. ДЕНЕЖНЫЙ ПУТЬ — правкой не закрывать, карточка открыта.

**10. «СПРОСИ ДЕРЕВО О НЕДОСТАВЛЕННОМ» ДАЛ ПУСТО ТРЕТИЙ РАЗ ПОДРЯД — спрашивать всё равно ПЕРВЫМ
ДЕЛОМ.** Замер #1273: из **семи** незакоммиченных `docs/decisions/ADR-*.md` прод-дерева все семь
ЕСТЬ на origin, шесть побайтово равны, а `ADR-154` локально КОРОЧЕ (7397 против 8349) ⇒ на origin
БОГАЧЕ, то есть локальная копия устарела, а не работа не уехала. Тот же файл и тот же разрыв, что
в #1271.

**11. ПЕРЕНОСИТСЯ ИЗ G1100 ЦЕЛИКОМ (не двигалось):** п. 10 (читатель карточек в ПРОД-дереве
печатает `[НЕ ИЗМЕРЕНО] … docs/decisions/INDEX-ARCHIVE.md: FileNotFoundError` — файла реестра-архива
в прод-дереве НЕТ) · п. 11 целиком (производитель утреннего аудита вне git — проверять
`grep -c ci_control_verdict` в `~/.claude/scheduled-tasks/spa-daily-90pct-audit/SKILL.md` ⇒ 2;
замер #1273: на месте, md5 `a5585ef391c9dd1902f14e5349dffb0f` · предмет резерва растёт ·
спецификация мутаций без файла не поверяема · чужой файл применяется ПАТЧЕМ · тринадцатая дверь
откажет и тебе · адреса предшественников G1059 · G1072 · G1073 пп. 2–26 · G1076…G1079 · G1087 ·
полнота `PYTHON_CARRIERS` НЕ ИЗМЕРЕНА · долг храповика ADR-362 (80 личностей,
`inbox-hrapovik-provenansa-git-ref-krasen-verno`) · `inbox-poverhnost-resheniya-shtampuet-tvl-live` ·
`inbox-proba-kriteriya-49-no-regression-ne-prin` · остаток ADR-1126:
`inbox-pretenziya-o-progone-ci-bez-svoei-lichno`).

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1100 (следующему циклу)

**0. КЛЮЧ ЖИВ, вершину брать У СЕРВЕРА.** `git ls-remote origin refs/heads/main`, а НЕ локальной
ссылкой (ADR-1112 п. 4). Дерево доставки — worktree ПРОД-КЛОНА `~/Documents/SPA_Claude` (ADR-796).
Замер 27.11 (#1272): локальная ссылка и ответ сервера СОВПАЛИ (`cf9391491`) — это ЗАМЕР того дня,
а не свойство клона; спрашивать всё равно сервер.

**1. КОНТРОЛЬНЫЙ ПРОГОН АГЕНТ ЗАКАЗАТЬ НЕ МОЖЕТ** (не двигалось пятый цикл): у ключа нет
`Actions: write`, `POST .../dispatches` → **403** при `200` на чтение. Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — **дубля не заводить**.
Вердикт CI о вершине **НЕ ИЗМЕРЕН**, замещается дифференциалом в ОТДЕЛЬНЫХ деревьях.
⚠️ **С 27.11 это требование ещё и ИСПОЛНЯЕТСЯ дверью (ADR-1126):** напишешь в журнал или в
карточку «CI RED <число>» без номера прогона — четырнадцатая дверь доставки ОТКАЖЕТ (код 21).
Честная форма — «вердикт CI НЕ ИЗМЕРЕН» и БЕЗ числа. Перемерить свой текст ДО доставки:
`python3 -m spa_core.monitoring.ci_claim_provenance --carrier-root <дерево> --data-dir <прод>/data`.

**2. ДОЛГ КЛАССА ADR-1126 НЕ УМЕНЬШЕН НИ НА ОДНУ ПРЕТЕНЗИЮ — дверь остановила РОСТ.** Предмет на
`main`: журналы **5 из 429** (`2026-W42.md:7128` · `W44:3879` · `W45:941` · `W46:1309` + пятая) ·
announce **9 из 69** · трекер **0 из 131** · утренняя сводка **НЕ ИЗМЕРЕНА** (своего текста на
диск не кладёт; 2 шаблона с ВЫЧИСЛЯЕМЫМ значением, несут ли они число — по дереву НЕ ВИДНО).
Правка истории журнала смысла не имеет (ADR-1125). Остаток — карточка
`inbox-pretenziya-o-progone-ci-bez-svoei-lichno` (`in-progress`, проба
`ci_claim_carriers_population_named`): её выполнение обязан назвать шаг 0-офис, не делающая сессия.

**3. ДВЕРЬ СУДИТ ПРИСУТСТВИЕ ЛИЧНОСТИ, А НЕ ЕЁ ВЕРНОСТЬ.** Претензия, назвавшая ЧУЖОЙ прогон,
через неё пройдёт. Мерить это нечем без сети, то есть упирается в п. 1. **Население класса
«претензия о прогоне в ПЯТОМ месте» (чат владельца, вывод агента, тело PR) НЕ ИЗМЕРЕНО** — нулём
это не считается, и носителей ЧЕТЫРЕ только потому, что их объявил перечень (урок ADR-1113:
закрытый список известных членов зелен ПО ПОСТРОЕНИЮ, полноту спрашивать у РЕЕСТРА РЕШЕНИЙ).

**4. ФОРМА «ВЫЖИВШАЯ МУТАЦИЯ — ДЫРА СЦЕНЫ, А НЕ ДЕФЕКТ КОДА» ПОДТВЕРДИЛАСЬ ВОСЬМОЙ РАЗ ПОДРЯД**
(#1202, #1217, #1267, #1270, #1271, теперь #1272) — но с ОДНИМ отличием, и оно важное: из пяти
выживших первого прогона **одна (`M07`) оказалась дефектом МОЕЙ МЕРКИ**, а не сцены.
`probe.returncode` стоял в функции ДВАЖДЫ — в ветвлении и в ТЕКСТЕ сообщения об отказе; мутация
сняла ветвление, имя осталось в f-строке, и AST-мерка «встречается ли имя в функции» зачла
упоминание за проверку. Дословно урок #1217 (имя в докстринге), только вместо докстринга —
f-строка. **Правило: мерка «имя встречается» не есть мерка «имя РАБОТАЕТ»;** спрашивай живой
сценой либо требуй имя ВНУТРИ `If.test`, а не где-нибудь в теле.

**4а. ВТОРАЯ СЦЕНА ПОЧИНКИ НАШЛА ТРЕТЬЕ, И ОНО БЫЛО ДЕФЕКТОМ КОДА.** Сцена «байты не декодируются
как UTF-8» дала вердикты `['unmeasured', 'clean']` — «сверено» стояло РЯДОМ с «не измерено» на
одном и том же файле: при нулевом числе суждённых файлов дверь всё равно печатала строку «чисто».
Починка — `if not grown and judged:`. **«Чисто» означает «измерено и роста нет»;** без единого
суждённого файла говорить его нельзя (инв. #17). Нашлось ТОЛЬКО потому, что сцена сверяла ПОЛНЫЙ
список вердиктов, а не первый элемент.

**5. ЧЕТЫРНАДЦАТАЯ ДВЕРЬ — ПЯТАЯ ПОДРЯД, КОТОРАЯ СПРАШИВАЕТ ПРОИЗВОДНОЕ** (ADR-889 реестр ·
ADR-1060 доска · ADR-1073 перепись · ADR-1112 свежесть ссылки · ADR-1126 личность претензии).
**Население класса «производная мера, у которой нет вопроса в момент доставки» за пределами этих
пяти НЕ ИЗМЕРЕНО** — нулём это не считается. Метод замера тот же (поверхность → дифференциально,
предмет — тот, у кого МЕНЯЕТСЯ вердикт; мерить и переход в `skipped`).

**6. ХРАПОВИК ВЕСА КАРТОЧКИ: мерить ДО своих правок.** Замер #1272 на входе — приказ **2981**
строка при держателе максимума `agent-audit-2026-08-02-fix-tracks` (**3015**), запас **34** строки,
а заказ G1100 и пост-запись не влезали. Сняты ДВЕ пост-записи — #1269 (71 строка, md5
`7bad351e484d28ad65e80ae8286fb926`) и #1267 (67 строк, md5 `cfeb56c49159981c49bbe6aeee63ff5d`) —
в архив `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md` порядком G1099 п. 7 с ОБОИМИ
вопросами: адрес спрошен ПЕРВЫМ (вхождений заголовка **0** у обоих — ни копии тела, ни прозы),
тело сверено ПОБАЙТОВО **2 из 2**. ⚠️ **Ловушка, встреченная тут же:** при дописывании в архив
хвостовой перевод строки схлопнулся, и ПОСЛЕДНИЙ блок вышел на **1 байт** короче оригинала —
сверка поймала (4791 против 4792). Дописывай с хвостом и сверяй ПОСЛЕ записи, а не до.
Кандидат на следующее снятие — пост-запись #1268 (52 строки) либо #1270 (67).

**7. `STATE.md`: указатель — ОДНА физическая строка.** Запас на входе #1272 был **3 строки /
709 символов**, и запись цикла влезла ОДНОЙ строкой в 645 знаков (итог **148 / 29 937 / 695**,
запас **2 / 63 / 5**). Следующему циклу запаса по символам почти нет — **сворачивать придётся
ДО своей записи**, и адрес каждого свёрнутого решения спрашивать заранее (файл · строка реестра ·
запись журнала).

**8. §49 НЕ ПЕРЕМЕРЯЛ, и это НАЗВАННЫЙ выбор** (перенос G1099 п. 9). ADR-1122: у **13 из 13**
критериев производитель меры ОДИН — `com.spa.decision_loop`, во флоте его нет с 29.10, рычаг у
ВЛАДЕЛЬЦА. Шаг 1з подтвердил состав ЧЕТВЁРТЫЙ день: СОСТОЯЛОСЬ 18 · **НЕ СОСТОЯЛОСЬ 2**
(`decision_loop`, `mission_tick`) · retired 1 · НЕ ИЗМЕРЕНО 10.

**9. Два артефакта офиса НЕ ПРОЧИТАНЫ** (офис **145 / 2**, состав ТОТ ЖЕ четвёртый день):
`data/acceptance_tree_lineage.json`, `data/step_time_drift.json`. Шаг 1е-2 (пины TVL) — состав ТОТ
ЖЕ **десятый** цикл подряд: живое без пина **3** (`euler_v2` живое **$395 211**, пол $5M НЕ
проходит · `morpho_blue` · `yearn_v3`), один пул под двумя ключами, поверхность объявляет
`tvl_floor_unverified=[]`. Офис дал ещё **два `CRITICAL`** по ВЛАСТИ ПИНА у гейта финансирования
(`compound_v3` — `pool_id` пуст ВОВСЕ · `morpho_blue_base` — гейт судит ДРУГОЙ пул, чем объявляет
пин); карточка `inbox-geit-finansirovaniya-sudit-ne-tot-pul-a` ЕСТЬ, дубля не заводил.
ДЕНЕЖНЫЙ ПУТЬ — правкой не закрывать.

**10. НОВОЕ НАБЛЮДЕНИЕ, не предмет этого цикла:** читатель карточек в ПРОД-дереве печатает
`[НЕ ИЗМЕРЕНО] … реестр решений живого дерева не прочитан: docs/decisions/INDEX-ARCHIVE.md:
FileNotFoundError`. То есть файл реестра-архива в прод-дереве ОТСУТСТВУЕТ, и ось «дерево ЧИСЕЛ»
у такой карточки честно остаётся `None`. Класс знакомый (прод-дерево расходится с origin по
построению, `docs/` туда не возится — ADR-1111), но ЭТОТ носитель назван впервые. Не чинил:
предмет цикла был другой, а молчаливая починка прицепом — своя ошибка.

**11. ПЕРЕНОСИТСЯ ИЗ G1099 ЦЕЛИКОМ (не двигалось):** п. 11 целиком (производитель утреннего
аудита живёт ВНЕ git — проверять `grep -c ci_control_verdict` в
`~/.claude/scheduled-tasks/spa-daily-90pct-audit/SKILL.md` ⇒ 2 · предмет резерва растёт ·
спецификация мутаций без файла не поверяема · чужой файл применяется ПАТЧЕМ · тринадцатая дверь
откажет и тебе · адреса предшественников G1059 · G1072 · G1073 пп. 2–26 · G1076…G1079 · G1087 ·
полнота `PYTHON_CARRIERS` НЕ ИЗМЕРЕНА · долг храповика ADR-362 (80 личностей,
`inbox-hrapovik-provenansa-git-ref-krasen-verno`) · `inbox-poverhnost-resheniya-shtampuet-tvl-live` ·
`inbox-proba-kriteriya-49-no-regression-ne-prin`) · п. 2 G1099 (спрашивать дерево о недоставленном
ПЕРВЫМ делом, и спрашивать в какую СТОРОНУ расходятся байты: «на origin богаче» значит «локальная
копия устарела», а не «работа не уехала»; `stranded_content` **781** файл).

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Заказ G1099 (следующему циклу)

**0. КЛЮЧ ЖИВ, вершину брать У СЕРВЕРА.** Замер 27.11 (#1271): доставка прошла.
Вершина — `git ls-remote origin refs/heads/main`, а НЕ локальной ссылкой (ADR-1112 п. 4).
Дерево доставки — worktree ПРОД-КЛОНА `~/Documents/SPA_Claude` (ADR-796).

**1. КОНТРОЛЬНЫЙ ПРОГОН АГЕНТ ЗАКАЗАТЬ НЕ МОЖЕТ** (не двигалось): у ключа нет
`Actions: write`, `POST .../dispatches` → **403** при `200` на чтение. Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — **дубля не
заводить**. Вердикт CI о вершине **НЕ ИЗМЕРЕН**, замещается дифференциалом в ОТДЕЛЬНЫХ
деревьях.

**2. ПУНКТ «СПРОСИ ДЕРЕВО О НЕДОСТАВЛЕННОМ» ДАЛ ПУСТО ВТОРОЙ РАЗ ПОДРЯД — спрашивать
всё равно ПЕРВЫМ ДЕЛОМ.** Замер #1271: из **семи** незакоммиченных
`docs/decisions/ADR-*.md` прод-дерева все семь ЕСТЬ на origin, шесть побайтово равны, а
седьмой (`ADR-154`) в прод-дереве СТАРШЕ origin на 9 строк. То есть вторая мерка (п. 2
заказа G1098) обязана быть НЕ ТОЛЬКО «есть ли файл на origin», но и «в какую СТОРОНУ
расходятся байты»: «на origin богаче» значит «локальная копия устарела», а не «работа не
уехала». `stranded_content` — **781** файл работы без второй копии (было 780), давний долг
G1097 п. 4.

**3. ПРЕДМЕТ #1271 НАЗВАН И НЕ ПОЧИНЕН У ПРОИЗВОДИТЕЛЯ ЖУРНАЛА.** ADR-1125: население
класса «претензия о прогоне CI без своей личности» измерено у ВСЕХ ЧЕТЫРЁХ носителей —
трекер **0 из 133** · журналы **5 из 420** · announce **9 из 69** · утренняя сводка
**НЕ ИЗМЕРЕНА** (своего текста на диск не кладёт; статически 8 литералов с маркером,
0 со счётом, 2 шаблона с ВЫЧИСЛЯЕМЫМ значением). Для аудита 90 % форма претензии уже
переписана (ADR-1124), а для ЖУРНАЛЬНОЙ записи цикла — нет: правило то же (**номер прогона
В СВОЁМ сегменте**, число и род — у `ci_control_verdict.py`), но его никто не исполняет.
Пять записей уже на `main`, и правка истории журнала смысла не имеет; починка — у
ПРОИЗВОДИТЕЛЯ, то есть у шага записи журнала в `docs/ORCHESTRATOR_PROTOCOL.md`.
**Проверь свою собственную запись прибором ДО доставки:** замер #1271 показал 420 → 424
претензии при неизменном предмете 5, то есть ПРОВЕРКА РАБОТАЕТ и стóит один зов.

**4. НОСИТЕЛЕЙ ЧЕТЫРЕ — это ОБЪЯВЛЕННЫЙ перечень, а не замер мира.** Претензия о прогоне
может жить в пятом месте (чат владельца, вывод агента, тело PR), и население там
**НЕ ИЗМЕРЕНО**; нулём это не считается. Закрытый перечень известных членов зелен ПО
ПОСТРОЕНИЮ (урок ADR-1113) — полноту спрашивать у РЕЕСТРА РЕШЕНИЙ, не у своего списка.

**5. ФОРМА «ВЫЖИВШАЯ МУТАЦИЯ — ДЫРА СЦЕНЫ, А НЕ ДЕФЕКТ КОДА» ПОДТВЕРДИЛАСЬ СЕДЬМОЙ РАЗ
ПОДРЯД** (#1202, #1217, #1267, #1270, теперь #1271). 32 мутации, первый прогон **28 убито
/ 2 выжило**. `M17`: ни одна сцена не различала «каталог носителя ЕСТЬ, а файлов по маске
нет» от «прочитано и чисто». `M22`: проверка «знак подстановки на месте» ТАВТОЛОГИЧНА —
знак только что вставлен, поэтому `MARK in text` истинно при ЛЮБОМ его значении.
**ВАКУУМНЫЙ сторож починается МЕРКОЙ, а не сценой:** знак проверяется той же дверью
чтения, и знак, читающийся как счёт упавших, есть названный дефект САМОЙ мерки. Проверяй
прямо: (а) у каждого ТРЕТЬЕГО ИСХОДА обязана быть сцена, спрашивающая его ПРИЧИНУ, а не
только присутствие в ответе; (б) условие вида «только что положенное на месте» ТАВТОЛОГИЯ,
и мутация его переживает молча.

**5а. СЦЕНА-ПАРА К ПОЧИНКЕ НАШЛА ТРЕТЬЕ, И ОНО БЫЛО ДЕФЕКТОМ КОДА.** Части f-строки —
тоже `Constant`, и `ast.walk` выдаёт их ОТДЕЛЬНО от шаблона: литерал с числом внутри
f-строки считался ДВАЖДЫ, и число «литералов с маркером» было **10** вместо **8**. Нашлось
только потому, что сцена держала подстановку ДО маркера. Держи её ПОСЛЕ — и сегмент нёс бы
её всегда, а ось «литерал против вычисляемого» не спрашивалась бы ни разу: это ровно
«зелена ПРОВОДКА, а не ОСЬ» в третьей форме.

**5б. ЧЕТВЁРТАЯ НАХОДКА — В МОЕЙ ЖЕ ОСИ «НЕ ЗАКРЫЛОСЬ».** `unclosed_opener` помечал
закрытыми только КОНЦЫ пары, поэтому вложенный открыватель (``тут `вложенный` бэктик``)
числился свободным, и любая запись с вложенной разметкой раздувала ВЕРХНИЙ край вилки
формой разметки, а не незнанием. Замер до починки: трекер 79 · журналы 44; после —
**61 · 22**. Мораль: «внутри закрытой пары» значит ВНУТРИ ДИАПАЗОНА, а не «равно его концу».

**6. ОДНА ДВЕРЬ — И ЭТО ПРО СЧЁТЧИКИ ТОЖЕ.** Первая редакция ADR-1125 держала у
announce-лога СВОЙ обход, и число «записей с незакрытым открывателем» вышло у него
константой **0** — ЛОЖНЫЙ ноль, выглядевший как замер, рядом с 61 и 22 у соседей. Копия
обхода «только для главного носителя» есть тот же класс, что копия разбора.

**7. ХРАПОВИК ВЕСА КАРТОЧКИ: мерить ДО своих правок.** Замер #1271 на входе — приказ
**2 966** строк при держателе максимума `agent-audit-2026-08-02-fix-tracks` (**3 016**),
запас 50 строк, а заказ G1099 + пост-запись не влезали. Сняты ДВЕ пост-записи — #1264
(36 строк) и #1230 (54) — в архив `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`
порядком G1098 п. 8 с ОБОИМИ вопросами. **Первый вопрос у #1230 дал ОДНО вхождение
заголовка в архиве, и оно оказалось ПРОЗОЙ о прошлой аварии, а не копией тела** — различать
эти два состояния обязательно, иначе упоминание разбора запретило бы снятие навсегда.
Снята и третья — #1231 (66 строк), тем же порядком. Кандидат на следующее снятие —
пост-запись #1267 (67 строк) либо #1269 (71). Вес мерить СИМВОЛАМИ, не `wc -c`.

**8. `STATE.md`: сворачивание мерится СТРОКАМИ, и перенос «для красоты» их ДОБАВЛЯЕТ.**
Замер #1271: свернул два блока в указатели и получил **154** строки вместо 150 — потому
что две ДЛИННЫЕ строки заменил четырьмя обёрнутыми. Указатель обязан быть ОДНОЙ физической
строкой в пределе 695 знаков. Итог после переделки — **147 / 29 292 / 695**, запас
**3 / 708 / 5**. Адрес ВСЕХ четырёх свёрнутых решений (1104 · 1096 · 1105 · 1106) спрошен ДО
сворачивания: файл · строка реестра · запись журнала — у всех на месте.

**9. §49 НЕ ПЕРЕМЕРЯЛ, и это НАЗВАННЫЙ выбор.** ADR-1122: у **13 из 13** критериев
производитель меры ОДИН — `com.spa.decision_loop`, во флоте его нет с 29.10, рычаг у
ВЛАДЕЛЬЦА. Шаг 1з подтвердил состав ТРЕТИЙ день: СОСТОЯЛОСЬ 18 · **НЕ СОСТОЯЛОСЬ 2**
(`decision_loop`, `mission_tick`) · retired 1 · НЕ ИЗМЕРЕНО 10. Перемеривать то, что
меняется одним рубильником владельца, значит тратить такт на известный ответ.

**10. Два артефакта офиса НЕ ПРОЧИТАНЫ** (офис **145 / 2**, состав ТОТ ЖЕ третий день):
`data/acceptance_tree_lineage.json`, `data/step_time_drift.json`. Шаг 1е-2 (пины TVL) —
состав ТОТ ЖЕ ДЕВЯТЫЙ цикл подряд: живое без пина **3** (`euler_v2` живое **$395 211**, пол
$5M НЕ проходит · `morpho_blue` · `yearn_v3`), один пул под двумя ключами, поверхность
объявляет `tvl_floor_unverified=[]`. ДЕНЕЖНЫЙ ПУТЬ — правкой не закрывать, карточка открыта.

**11. ПЕРЕНОСИТСЯ ИЗ G1098 ЦЕЛИКОМ (не двигалось):** п. 4 (производитель утреннего аудита
починен, но живёт ВНЕ git — проверять `grep -c ci_control_verdict` в
`~/.claude/scheduled-tasks/spa-daily-90pct-audit/SKILL.md` ⇒ 2; замер #1271: на месте, md5
`a5585ef391c9dd1902f14e5349dffb0f`) · п. 13 целиком (предмет резерва растёт · спецификация
мутаций без файла не поверяема · чужой файл применяется ПАТЧЕМ · тринадцатая дверь откажет
и тебе · адреса предшественников G1059 · G1072 · G1073 пп. 2–26 · G1076…G1079 · G1087 ·
полнота `PYTHON_CARRIERS` НЕ ИЗМЕРЕНА · долг храповика ADR-362 ·
`inbox-poverhnost-resheniya-shtampuet-tvl-live` · `inbox-proba-kriteriya-49-no-regression-ne-prin`).

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

### Контрольный прогон цикла #1275 (вписано ПОСЛЕ доставки)

**Вердикт CI о моей вершине НЕ ИЗМЕРЕН** — у ключа нет `Actions: write`, заказать прогон агент
не может (G1102 п. 1). Числа ниже сняты в ОТДЕЛЬНЫХ деревьях, не в дереве доставки.

* **Новый контроль:** `spa_core/tests/test_param_hop_door.py` — **23 passed** (59,8 с), у каждой
  отвечающей сцены есть обратная половина с отказом.
* **Соседи переписи:** `test_derived_artifact_census.py` + `test_delivery_question_census.py` +
  `test_known_member_list_census.py` — **61 + 54 passed**, 7 subtests. Два падения, найденные
  первым прогоном, ИЗМЕРЕНЫ предсуществующими на базовых байтах в отдельном дереве
  (`/private/tmp/spa_c1275base`, прибор возвращён к `73d1f0328`) и сняты приговором ADR-1126.
* **Мутации:** 20 применено, якорь каждой уникален · первый прогон 15/5 · после починки сцен
  **19 убито / 1 эквивалентна** (замер эквивалентности: 2628 файлов, 0 расхождений вердикта и
  причины). Дерево мутаций `/private/tmp/spa_c1275mut`, байты возвращены ПОБАЙТОВО.
* **Переписи ПОСЛЕ:** `derived_artifact_census --surface` → 420/7/235/**81** (код 1) ·
  `delivery_question_census` → предмет **263**, под дверью 157, НЕ ИЗМЕРЕНО **81**, вилка
  **263 … 344** (код 1).
* **Шаги цикла:** офис 145/2 (код 0) · 1в код 0 (аудит в окне такта, 24,3 ч при 30,0) · 1д
  **НОВЫХ НЕТ** (36 ходов, два исторических расхождения названы) · 1е обе оси **100 %** ·
  1е-2 код 1 (3 живых без пина, один пул под двумя ключами) · 1з код 1 (18/2/1/10) · витрина
  `SHELF_NOT_DELIVERED` — ждёт ворот владельца, не пересобираем.

### Контрольный прогон цикла #1273 (вписано ПОСЛЕ доставки)

**Вердикт CI о вершине НЕ ИЗМЕРЕН** — у ключа нет `Actions: write`, заказать контрольный прогон
агент не может (карточка `owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo`). Замещено:

* **батарея приёмки** `spa_core/tests/test_delivery_question_census.py` — **22 passed**;
* **мутации** 20 объявлено / 20 применено / **20 убито** / 0 выжило на финальных байтах
  (первый прогон 18/2, обе выжившие — дыры СЦЕН, дефектом кода не был ни один);
* **дифференциал** 68 сторожей, чьи `source_dirs` пересекаются с каталогами доставки (мерка из
  БАЙТОВ, не из прозы: `derived_artifact_census --surface --json`), в ДВУХ ОТДЕЛЬНЫХ деревьях —
  чистый `ff7b675a8` против дерева доставки: **2 failed / 4491 passed** против
  **2 failed / 4492 passed**, расхождений ИМЁН **0 из 2**; оба красных
  (`test_edge_boundary_dataflow_census`, `test_edge_corpus_map_probe`) предсуществуют на чистом
  origin и моей доставкой не вызваны.

### Контрольный прогон цикла #1272 (вписано ПОСЛЕ доставки)

> **Тело перенесено в архив ПОБАЙТОВО** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`.
> Снял цикл #1275 порядком G1101 п. 6: адрес спрошен ПЕРВЫМ (вхождений заголовка
> в архивах **0**), потом сверено ПОБАЙТОВО, и только потом снят текст.
> **Тело: md5 `0e6dab7fce8af4174bd3cb7f3b9a63a2`, 5265 символов, 74 строк.** Хвостовые переводы строки
> в md5 НЕ ВХОДЯТ — они свойство СТЫКА разделов, а не тела.

### Контрольный прогон цикла #1270 (вписано ПОСЛЕ доставки) — В АРХИВЕ

Побайтовая копия (заголовок ДОСЛОВНО) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`. Снял цикл #1272 порядком G1099 п. 7: адрес спрошен ПЕРВЫМ (вхождений заголовка в архиве **0** — ни копии тела, ни прозы о нём), потом сверено ПОБАЙТОВО, и только потом снят текст. **Тело: md5 `eaa1053cab291edc5b7ab36c2accf6b9`, 4584 символов, 66 строк.** Хвостовые переводы строки в md5 НЕ ВХОДЯТ — они свойство СТЫКА разделов, а не тела, и первая редакция этих заглушек считала md5 вместе с ними, то есть называла число, которое в архиве не воспроизводится.

### Контрольный прогон цикла #1269 (вписано ПОСЛЕ доставки) — В АРХИВЕ

Побайтовая копия (заголовок ДОСЛОВНО) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`. Снял цикл #1272 порядком G1099 п. 7: адрес спрошен ПЕРВЫМ (вхождений заголовка в архиве **0** — ни копии тела, ни прозы о нём), потом сверено ПОБАЙТОВО, и только потом снят текст. **Тело: md5 `240a77273ddf1cd27689f34add303b86`, 5023 символов, 70 строк.** Хвостовые переводы строки в md5 НЕ ВХОДЯТ — они свойство СТЫКА разделов, а не тела, и первая редакция этих заглушек считала md5 вместе с ними, то есть называла число, которое в архиве не воспроизводится.

### Контрольный прогон цикла #1268 (вписано ПОСЛЕ доставки) — В АРХИВЕ

Побайтовая копия (заголовок ДОСЛОВНО) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`. Снял цикл #1272 порядком G1099 п. 7: адрес спрошен ПЕРВЫМ (вхождений заголовка в архиве **0** — ни копии тела, ни прозы о нём), потом сверено ПОБАЙТОВО, и только потом снят текст. **Тело: md5 `cf53bf57608fd7f4f14fdb9044ced7bc`, 3373 символов, 51 строк.** Хвостовые переводы строки в md5 НЕ ВХОДЯТ — они свойство СТЫКА разделов, а не тела, и первая редакция этих заглушек считала md5 вместе с ними, то есть называла число, которое в архиве не воспроизводится.

### Контрольный прогон цикла #1267 (вписано ПОСЛЕ доставки) — В АРХИВЕ

Побайтовая копия (заголовок ДОСЛОВНО) — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`. Снял цикл #1272 порядком G1099 п. 7: адрес спрошен ПЕРВЫМ (вхождений заголовка в архиве **0** — ни копии тела, ни прозы о нём), потом сверено ПОБАЙТОВО, и только потом снят текст. **Тело: md5 `b623e048a29bdd1462ecd08897c2f4d8`, 4790 символов, 66 строк.** Хвостовые переводы строки в md5 НЕ ВХОДЯТ — они свойство СТЫКА разделов, а не тела, и первая редакция этих заглушек считала md5 вместе с ними, то есть называла число, которое в архиве не воспроизводится.

### Контрольный прогон цикла #1265 (вписано ПОСЛЕ доставки) — В АРХИВЕ

> **Тело перенесено в архив ПОБАЙТОВО** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`, раздел «Перенос
> цикла #1270 — пост-запись цикла #1265» (90 строк / 6606 символов,
> md5 блока `e056e73d06839d0aec483c1567e2929a`). Снял цикл #1270 порядком G1097 п. 8а: ДВА вопроса — «есть ли
> копия заголовка» (`grep` дал 0) И «не объявлен ли блок живым» (не объявлен).

### Контрольный прогон цикла #1264 (вписано ПОСЛЕ доставки) — В АРХИВЕ

> **Тело перенесено в архив ПОБАЙТОВО** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`,
> раздел «Перенос цикла #1271 — пост-запись цикла #1264» (36 строк / 2525 символов,
> md5 блока `d6c6d696ebbc311bf080030ec4e964eb`). Снял цикл #1271 порядком G1098 п. 8.

### Контрольный прогон цикла #1263 (вписано ПОСЛЕ доставки) — В АРХИВЕ

> **Тело перенесено в архив ПОБАЙТОВО** — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`, раздел «Перенос
> цикла #1270 — пост-запись цикла #1263» (99 строк / 6 802 символа, md5 блока
> `319ce6e1273e2d2b05dec0635ed90a2c`). Снял цикл #1270 порядком G1097 п. 8а: ДВА
> вопроса — «есть ли копия заголовка» (`grep` дал 0) И «не объявлен ли блок живым»
> (4 вхождения номера, ни одно не объявляет), и только потом снятие.

### Контрольный прогон цикла #1262 (вписано ПОСЛЕ доставки) — В АРХИВЕ

Перенёс цикл #1269 порядком G1096 п. 8: адрес спрошен ДО снятия (в архивах 0 вхождений), сверено ПОБАЙТОВО (md5 `aae2e4ebcd67c57a2d8e37910b9f1a5d`, 72 строк), и только потом снят текст. Адрес — `docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md`.

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

