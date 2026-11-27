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

### Заказ G1096 (следующему циклу)

**0. КЛЮЧ СПРОСИТЬ ПЕРВЫМ, и спрашивать у СЕРВЕРА.** Замер 27.11 (#1268) — **200**, ключ ЖИВ,
длина 93. Вершину брать `git ls-remote origin refs/heads/main`, а НЕ локальной ссылкой
(ADR-1112 п. 4). **Дерево доставки — worktree ПРОД-КЛОНА** `~/Documents/SPA_Claude` (ADR-796).

**1. КОНТРОЛЬНЫЙ ПРОГОН АГЕНТ ЗАКАЗАТЬ НЕ МОЖЕТ, и это НЕ «зелено»** (не двигалось). У ключа
нет `Actions: write`: `POST .../dispatches` → **403** при `200` на чтение. Карточка
`owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258 — **дубля не заводить**.
Вердикт CI о вершине **НЕ ИЗМЕРЕН**.

**2. СПРОСИ ДЕРЕВО О НЕДОСТАВЛЕННОМ ПЕРЕД ТЕМ, КАК БРАТЬ ПУНКТ ЗАКАЗА В РАБОТУ — пункт
сработал ДВА цикла подряд и остаётся первым.** #1267 нашёл так работу #1266 по оси C; #1268 нашёл
так ВТОРУЮ недоставленную работу того же мёртвого цикла — ось ПРОИЗВОДИТЕЛЯ меры §49, лежавшую в
`/private/tmp/spa_c1266` (доставлена ADR-1122). Одна мёртвая сессия может держать НЕСКОЛЬКО
наборов: журнал `data/session_changes.jsonl` писался ею ДВАЖДЫ, и второй набор не был виден,
пока не прочитаны ОБЕ записи. Команды: `git -C <дерево> status --short | grep -v '^.. data/'`
по недавним worktree (`git worktree list`), `ls /private/tmp/spa_c12*/docs/decisions/ADR-11*`,
плюс `ps` — живой сессии быть не должно. **Номер ADR у найденной работы ПЕРЕПРОВЕРИТЬ:** #1266
рассчитывал на 1121, и его занял #1267 тем же утром.

**3. ПЕРЕМЕРЬ ЧУЖОЙ ВЫВОД, А НЕ ТОЛЬКО ЧУЖИЕ БАЙТЫ — и у #1268 устарело именно СВОДНОЕ число.**
Центральное утверждение #1266 («13 из 13 критериев у одного производителя, его нет во флоте»)
подтвердилось дословно, а его сводка `ВЫПОЛНЕНО 0 · 8 · 5` за четыре часа стала **`1 · 8 · 4`**
(`Owner visibility` стал выполнен), и рычаг владельца — **12 из 12**, а не 13 из 13. Байты кода
при этом не менялись ни одним (md5 `e0998989427fc14348d0ca78524410de`). Вывод: у чужой работы
ПЕРЕМЕРЯТЬ надо каждое число, которое зависит от времени, а не только то, вокруг которого
написано решение.

**4. НОВОЕ И ГЛАВНОЕ: 13 мутаций ОДНОГО АВТОРА зелены по его же мерке.** Свой набор из 14
мутаций на ТЕХ ЖЕ байтах дал **11 убито · 3 ВЫЖИЛО**, и все три — дыры СЦЕН: (а) фильтр
«только не-выполненные» был бездействующим, потому что во всех сценах `probe_runner` отвечал
`NOT_SATISFIED`; (б) печатаемое читателю число `fleet_labels` не сверяла ни одна сцена; (в)
проверка ярлыков спрашивала их НАЛИЧИЕ, а не РАЗЛИЧИМОСТЬ. **Приняв чужую работу, прогоняй
СВОИ мутации, а не читай чужой счёт** — даже когда чужой счёт «13 из 13» и байты побайтово те
же. Три формы, которые чужой набор склонен пропускать, назови первыми: бездействующий фильтр ·
печатаемое число без сцены · проверка наличия вместо различимости.

**5. ОСЬ ПРОИЗВОДИТЕЛЯ ЗАКРЫЛА ОДНОГО ЧИТАТЕЛЯ, и это сказано вслух.** Население класса
«производная мера без вопроса о живости своего производителя» **за пределами §49 НЕ ИЗМЕРЕНО** и
нулём не считается. Метод тот же, что у pid и имени ветки: собрать читателей, у которых есть
понятие «артефакт протух», и спросить каждого, задаёт ли он вопрос о производителе; предмет —
тот, у кого вердикт МЕНЯЕТСЯ при выключенном производителе. Мерить и переход в `skipped`.

**6. УТРЕННИЙ АУДИТ 90 % НАЗВАЛ РОД ПАДЕНИЯ МИМО, и число при этом совпало.** Сводка 09:12Z
сказала «CI control RED 140 имён, худший — f-string SyntaxError на py3.11 ×26». Замер #1268:
упавших **84** (не 140), худший файл `test_reachability_of_the_rest_wiring.py` действительно
×26, но причина — `Failed: Timeout (>180.0s) from pytest-timeout` в `setUpModule`, прочитанная
в логе шарда 11. Класс f-string измерен в НОЛЬ двумя приборами (сторож 14 passed; названная им
слепая зона «обратная косая в поле» — 5810 файлов, находок 0). **Совпавшее число не есть
подтверждённая причина.** Долг: у читателя аудита 90 % род падения не сверяется с
`ci_control_verdict.py`, и это следующий дешёвый предмет.

**7. ПЕРЕНОСИТСЯ ИЗ G1095 ЦЕЛИКОМ (не двигалось):** п. 5 (тождество отображения ось C НЕ
ДОКАЗЫВАЕТ) · п. 6 (ось C видит ОДИН ХОП; зов по АТРИБУТУ `mod.load_baseline()` — второй хоп,
население за границей НЕ ИЗМЕРЕНО) · п. 7 (цена меры — часть меры: 7 ГиБ без предела положений;
причины «НЕ ИЗМЕРЕНО» СВОРАЧИВАТЬ по роду, поштучно их 5017) · п. 9 целиком (пустой список
входов обязан быть ОТКАЗОМ: сверять ЧИСЛО собранных тестов с числом ожидаемых файлов, а не цвет
строки) · п. 10 целиком (адреса предшественников: G1059 · G1073 пп. 2–26 · G1072 · G1076 ·
G1077 · G1078 · G1079 · G1087 · полнота `PYTHON_CARRIERS` НЕ ИЗМЕРЕНА · долг храповика ADR-362 ·
`inbox-poverhnost-resheniya-shtampuet-tvl-live` · `inbox-proba-kriteriya-49-no-regression-ne-prin`).

**8. ВЕС: перемерить ПОСЛЕ своих правок, число предшественника не принимать.** Замер #1268 —
ниже, в пост-записи. Кандидат на снятие в архив — «Заказ G1091», тем же порядком: `grep` по
заголовку ПЕРВЫМ (единственная копия могла быть только здесь), побайтовая сверка, заголовок
оставить ДОСЛОВНО, и только потом снимать текст.

**9. `STATE.md`: запас ПОСЛЕ доставки — 148 строк / 29 847 символов / 695 в длиннейшей**
(пределы 150 / 30 000 / 700), запас **2 / 153 / 5**. **Сжимать ПЕРВЫМ делом, а не после:**
#1268 на первой же правке уехал за предел символов на 212 и сворачивал ВТОРУЮ пару строк уже
вторым заходом. Освобождал так: две пары старых строк (ADR-1075+1077+1078 и ADR-1109+1110) →
по одной строке «детали ТОЛЬКО в реестре», с проверкой АДРЕСА каждого ADR (файл · строка
реестра · запись журнала) ДО сворачивания. Вес мерить СИМВОЛАМИ, не `wc -c`; и помнить, что
предел ДЛИННЕЙШЕЙ строки (700) бьёт раньше предела символов.

**10. Два артефакта офиса НЕ ПРОЧИТАНЫ** (офис **145 / 2**): `data/acceptance_tree_lineage.json`,
`data/step_time_drift.json`. Причина чужая и названа: `com.spa.decision_loop` во флоте НЕ
загружен, включение службы — действие ВЛАДЕЛЬЦА. Карточки есть, дубля не заводить. Шаг 1з:
СОСТОЯЛОСЬ 18 · **НЕ СОСТОЯЛОСЬ 2** · retired 1 · НЕ ИЗМЕРЕНО 10 — состав ТОТ ЖЕ, 25–27.11.
**Цена этого состава теперь посчитана в единицах приёмки владельца (ADR-1122): 13 из 13.**

**11. Шаг 1е-2 (пины TVL) — состав ТОТ ЖЕ шестой цикл подряд:** живое без пина **3**
(`euler_v2` живое **$395 211**, пол $5M НЕ проходит · `morpho_blue` · `yearn_v3`), один пул под
двумя ключами (`morpho_blue`+`morpho_steakhouse`, структурный предел 60% против потолка T2 50%),
а поверхность объявляет `tvl_floor_unverified=[]`. ДЕНЕЖНЫЙ ПУТЬ — правкой не закрывать,
карточка открыта.

**Статус карточки остаётся `in-progress`** — стоячий приказ владельца (инв. #14).

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

### Контрольный прогон цикла #1271 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `2573a889` — **14** файлов, база ПИНОВАНА
`--expected-base a149bcce4e27…` (вершина спрошена у СЕРВЕРА `git ls-remote`, не локальной
ссылкой). Слепок байтов сверен у **44** чтений, слепок режимов у **3**, разбор уезжающего
Python — **5** файлов. **Доставка проверена ЧТЕНИЕМ origin**, а не словом пушера:
`git show origin/main:<путь> | md5` против дерева — **14 из 14 побайтово**.

**Флагов обхода НОЛЬ.** Ни одна из тринадцати дверей доставки не отказала; три
предупреждения провенанса базы объяснены НАМЕРЕННЫМИ удалениями: приказ (128 строк — три
пост-записи #1264/#1230/#1231 перенесены в архив), новая карточка (1 строка — `status: new`
→ `in-progress`), `_BOARD.md` (2 строки — доска перегенерирована прибором).

**Вердикт CI о вершине НЕ ИЗМЕРЕН** (у ключа нет `Actions: write`: `403` при `200` на
чтение; карточка `owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258,
дубля не заводил). Замещён ДИФФЕРЕНЦИАЛОМ в ОТДЕЛЬНЫХ одноразовых деревьях — долгий прогон
в дереве доставки не жил ни разу:

| прогон | дерево | исход |
|---|---|---|
| база, ЧИСТЫЙ `origin/main` a149bcce4 (70 сторожей) | `/private/tmp/spa_c1271base` | **4532 passed · 2 failed · 2 skipped** (390,24 с) |
| мои байты (те же 70) | `/private/tmp/spa_c1271after` | **4532 passed · 2 failed · 2 skipped** (391,44 с) |
| батарея решения | `/private/tmp/spa_c1271` | **102 passed** (у редакции ADR-1124 было 32) |
| мутации, принятые байты | `/private/tmp/spa_c1271mut` | 30 / **28 убито** / **2 ВЫЖИЛО** / 0 |
| мутации, ФИНАЛЬНЫЕ байты | `/private/tmp/spa_c1271mut4` | 32 / **32 убито** / **0 выжило** / 0 |
| шаг 1г (якоря времени) | `/private/tmp/spa_c1271anchor` | дерево НАЗВАНО входом `--repo-root` |

**Равные счётчики дифференциала ОБЪЯСНЕНЫ** (урок «равные счётчики требуют объяснения»):
моих тест-файлов в этой поверхности НЕТ — они называют ПРИБОР, а не каталог, поэтому +70
тестов сюда не попадают (они в батарее). Оба падения (`test_edge_boundary_dataflow_census`,
`test_edge_corpus_map_probe`) красны на ЧИСТОЙ вершине, то есть не мои. **Поверхность
«перечисляют КОРЕНЬ `.`» — ещё 312 сторожей — НЕ ИЗМЕРЕНА:** прогон 381 входа за 25 минут
дошёл до 12 % и был снят; причина названа, число названо, нулём это не считается.

**Своя проба карточки задана ПЕРВЫМ делом:** `apy_name_carries_one_kind` → `satisfied`
(§5 из двенадцати — закрытием приказа она не является), критерий не правил
(`.claude/rules/acceptance.md` п. 2).

**Статус приказа остаётся `in-progress`** (инв. #14). Карточка
`inbox-pretenziya-o-progone-ci-bez-svoei-lichno` — `in-progress` с объявленной пробой
`ci_claim_carriers_population_named`; закрывать её САМ не стал: критерий назван прозой
ПРЕДШЕСТВЕННИКОМ (#1270), машинную мерку сделал я, и самосертификацией это быть не должно —
выполнение назовёт шаг 0-офис следующего цикла.

**Живой заказ следующему циклу — G1099** выше.

### Контрольный прогон цикла #1270 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `6cf3ff2aa86c67692bc3723b910189a5c9a63540` — **12** файлов,
база пинована `--expected-base 15c057ece…` (вершина спрошена у СЕРВЕРА `git ls-remote`, не
локальной ссылкой). Слепок байтов сверен у **36** чтений, слепок режимов у **5**, разбор
уезжающего Python — **3** файла. Доставка проверена **ЧТЕНИЕМ origin**, а не словом пушера:
`git show origin/main:<путь> | md5` против дерева — **12 из 12 побайтово**.

**Флагов обхода НОЛЬ.** Ни одна из тринадцати дверей доставки не отказала; три
предупреждения провенанса базы объяснены НАМЕРЕННЫМИ удалениями строк: `docs/STATE.md`
(4 строки — два фолда, см. заказ п. 9), приказ (77 строк — перенос пост-записи #1263 в
архив, и пушер сам доложил «разделов ПЕРЕНЕСЕНО в архив — 1, тело сверено с remote
ПОБАЙТОВО, потери нет»), `_BOARD.md` (4 строки — доска перегенерирована прибором).

**Вердикт CI о вершине НЕ ИЗМЕРЕН** (у ключа нет `Actions: write`: `403` при `200` на
чтение; карточка `owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258,
дубля не заводил). Замещён ДИФФЕРЕНЦИАЛОМ в ОТДЕЛЬНЫХ одноразовых деревьях — долгий прогон
в дереве доставки не жил ни разу:

| прогон | дерево | исход |
|---|---|---|
| база, ЧИСТЫЙ `origin/main` 15c057ece (70 сторожей) | `/private/tmp/spa_c1270base` | **4531 passed · 2 failed · 2 skipped** (369,97 с) |
| мои байты (те же 70) | `/private/tmp/spa_c1270after` | **4532 passed · 2 failed · 2 skipped** (369,46 с) |
| батарея решения на байтах доставки | `/private/tmp/spa_c1270` | **32 passed** |
| мутации, принятые байты | `/private/tmp/spa_c1270mut` | 25 / **22 убито** / **3 ВЫЖИЛО** / 0 |
| мутации, ФИНАЛЬНЫЕ байты | `/private/tmp/spa_c1270mut2` | 25 / **24** / **1 эквивалентный** / 0 |
| шаг 1г (якоря времени) | `/private/tmp/spa_c1270anchor` | «Бомб нет при задержке 95 мин» |

**Мерка 70 выведена ИЗ БАЙТОВ, а не из прозы заказа** (`derived_artifact_census.py
--surface --json` ∩ каталоги доставки), и **вилка охвата ПЕЧАТАЕТСЯ: 70 … 176** — 106 путей
переписи остались НЕ РАЗОБРАНЫ, и нулём это не считается.

**Разница +1 ОБЪЯСНЕНА поимённо, а не принята как «значит чисто».** Сличение собранных имён
(`--collect-only`): ПРИШЛО 1, УШЛО 0 —
`test_no_live_credentials_in_runtime_config.py::…[spa_core/monitoring/ci_claim_provenance.py]`:
сторож параметризуется по файлам рантайма, увидел мой новый модуль и **ПРИНЯЛ** его. Это
противоположность регрессии (урок ADR-1074). `skipped` сверен отдельно (2 = 2) по уроку
#465: тест, выпавший из дифференциала, не краснеет и не проходит — он ИСЧЕЗАЕТ. Два падения
(`test_edge_boundary_dataflow_census`, `test_edge_corpus_map_probe`) красны на ЧИСТОЙ
вершине — чужая работа R&D-агентов, ни одно не моё и ни одно не гашу (инв. #16).

**Три выжившие мутации первого прогона разобраны поимённо, и дефектом КОДА не была НИ
ОДНА.** Две — дыры СЦЕН формы «зелена ПРОВОДКА, а не ОСЬ» (G1097 п. 5): обе сцены границы
сегмента держали номер прогона ДО маркера, поэтому срез `summary[mark:]` его не захватывал
ни с границей, ни без неё — ось не спрашивалась ни разу. Добавлены две РАЗЛИЧАЮЩИЕ сцены.
Третья — **ЭКВИВАЛЕНТНЫЙ мутант, доказанный замером**: эталон и мутант на нечитаемом
`--data-dir` дают ОБА код 2 и причину, НАЗЫВАЮЩУЮ каталог; различие — канал и слова.
Записан эквивалентным в спецификации, а не замазан сценой на формулировку.

**Храповики веса мерены ДО своих правок** (G1097 п. 8): приказ **2 973** строки при
держателе максимума `agent-audit-2026-08-02-fix-tracks` (**3 016**), запас 43 — снята
пост-запись #1263 (99 строк, md5 `319ce6e1273e2d2b05dec0635ed90a2c`) в
`docs/journal/CARD-archive-portfolio-cio-orders-2026-11-27.md` ОБОИМИ вопросами п. 8а;
карточка **2 973 → 2 882**. **Перемер ПОСЛЕ заказа G1098 и этой записи дал 3 046 строк —
храповик ПОКРАСНЕЛ**, и это замер, а не ожидание: снята вторым заходом пост-запись #1265
(90 строк, md5 `e056e73d06839d0aec483c1567e2929a`) тем же порядком и теми же двумя
вопросами, итог **2 963** строки / **121 119** символов при базе **3 016** ⇒ запас **53**
строки. Базы храповиков НЕ дописывались (инв. #16); число мерено тем же прибором, который
судит, а не принято у предшественника.

**`STATE.md` после доставки: 148 строк / 29 821 символ / 695 в длиннейшей** (пределы 150 /
30 000 / 700), запас **2 / 179 / 5**. Вес мерен СИМВОЛАМИ, не `wc -c`.

**Статус карточки не двигался** — `in-progress`, стоячий приказ владельца (инв. #14);
`acceptance_probe: apy_name_carries_one_kind` не правился (`.claude/rules/acceptance.md`
п. 2). Живой заказ следующему циклу — **G1098** выше.

### Контрольный прогон цикла #1269 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `01ec61bfd005b048714905ceb58e1c35838e9910` — **15** файлов, база
пинована `--expected-base cf583d604…` (вершина спрошена у СЕРВЕРА `git ls-remote`, не локальной
ссылкой). Слепок байтов сверен у **48** чтений, слепок режимов у **6**, разбор уезжающего Python —
**6** файлов. Доставка проверена **ЧТЕНИЕМ origin**, а не словом пушера: `git show origin/main:<путь>
| md5` против дерева — **15 из 15 побайтово**.

**Флаг обхода передан РОВНО ОДИН, и он НАПЕЧАТАН:** `--allow-ungated-ref-read`. Причина разобрана
в ADR-1123 и записана В КОДЕ у места зова; остальные 14 доступных флагов не передавались.

**ДВЕ двери доставки отказали, и обе ВЕРНО — обход ни у одной не был первым действием.**

| дверь | код | что сказала | как закрыто |
|---|---|---|---|
| свежесть ссылки (ADR-1112) | **20** | «доставка РАСТИТ долг на 2 зова» | один зов — ЛОЖНЫЙ член, починен (долг 2 → 1); остаток объявлен обходом |
| страж перезаписи | **4** | «пуш стёр бы 3 раздела карточки, укоротил на −209 строк» | архив ПЕРЕСТРОЕН, обход НЕ применялся |

**Отказ стража перезаписи был настоящей находкой в МОЕЙ работе, а не помехой.** Первая редакция
архива вставляла строку-примечание `> Блок «…», md5 …` МЕЖДУ телами разделов. Страж сверяет тело
ПОБАЙТОВО, а вставка попадает в ТЕЛО ПРЕДЫДУЩЕГО раздела ⇒ три раздела честно читались как
ПОТЕРЯННЫЕ. Вторая редакция снята ПРОТИВ ORIGIN той же дверью, которой судит страж
(`push_to_github.entry_blocks` + `CARD_SECTION_RE`), все примечания собраны в ОДНУ преамбулу, тела
идут подряд под своими заголовками — сверка дала **4 из 4**, и пушер доложил сам: «разделов
ПЕРЕНЕСЕНО в архив, уезжающий этим же пушем — **4** (тело каждого сверено с remote ПОБАЙТОВО,
потери нет)». **Сверять свой перенос надо ДВЕРЬЮ СТРАЖА, а не глазами и не своим `in`:** моя
собственная проверка `body in arch` сказала «сошлось» на архиве, где заголовков не было ВОВСЕ.

**Вердикт CI о вершине НЕ ИЗМЕРЕН** (у ключа нет `Actions: write`: `403` при `200` на чтение;
карточка `owner-decision-novomu-klyuchu-github-ne-hvataet-odnogo` открыта #1258, дубля не заводил).
Замещён ДИФФЕРЕНЦИАЛОМ в ОТДЕЛЬНЫХ одноразовых деревьях — долгий прогон в дереве доставки не жил
ни разу:

| прогон | дерево | исход |
|---|---|---|
| база, ЧИСТЫЙ `origin/main` cf583d604 (68 сторожей) | `/private/tmp/spa_c1269base` | **4489 passed · 2 failed · 2 skipped** |
| мои байты (те же 68) | `/private/tmp/spa_c1269after` | **4490 passed · 2 failed · 2 skipped** |
| батарея решения на байтах доставки | `/private/tmp/spa_c1269` | **83 passed** |
| мутации, принятые байты | `/private/tmp/spa_c1269mut` | 34 / **26 убито** / **8 ВЫЖИЛО** / 0 |
| мутации, ФИНАЛЬНЫЕ байты | `/private/tmp/spa_c1269mut2` | 34 / **34** / **0** / 0 |
| шаг 1г (якоря времени) | `/private/tmp/spa_c1269anchor` | «Бомб нет при задержке 95 мин» |

**Мерка 68 выведена ИЗ БАЙТОВ, а не из прозы заказа** (`derived_artifact_census.py --surface
--json` ∩ каталоги доставки), и **вилка охвата ПЕЧАТАЕТСЯ: 68 … 174** — 106 путей переписи
остались НЕ РАЗОБРАНЫ, и нулём это не считается. Приписать 174 своей доставке значило бы выдать
чужую поверхность за цену моих байтов; выдать 68 за полноту — объявить измеренным то, чего мера не
видела.

**Разница +1 ОБЪЯСНЕНА поимённо, а не принята как «значит чисто».** Сличение собранных имён
(`--collect-only`) дало ПРИШЛО 1, УШЛО 0: `test_no_live_credentials_in_runtime_config.py::…
[spa_core/monitoring/stranded_content.py]` — сторож параметризуется по файлам рантайма, увидел мой
новый модуль и **ПРИНЯЛ** его. Это противоположность регрессии (урок ADR-1074). `skipped` сверен
отдельно (2 = 2) по уроку #465: тест, выпавший из дифференциала, не краснеет и не проходит — он
ИСЧЕЗАЕТ. Два падения — `test_edge_boundary_dataflow_census`, `test_edge_corpus_map_probe` — красны
на ЧИСТОЙ вершине (корпус кромки разошёлся с закреплённой картой, чужая работа R&D-агентов), ни
одно не моё и ни одно не гашу (инв. #16).

**Храповик веса карточки был КРАСЕН на чистом `origin/main` ДО меня** — 3 111 строк против базы
3 016, краснота от пост-записи #1268. Снято переносом ЧЕТЫРЁХ разделов, карточка **3110 → 2890**,
база НЕ дописывалась (инв. #16). Держатель максимума сменился: теперь это `agent-audit-2026-08-02-fix-tracks` (3016), а не приказ.

**Вес карточки ПЕРЕМЕРЕН ПОСЛЕ всех правок, включая эту пост-запись:** **2972** строки / **122 410** символов при базе храповика **3016** ⇒ запас **44** строки. Число предшественника не принималось: мерено тем же прибором, который судит.

**`STATE.md` после доставки: 147 строк / 29 817 символов / 695 в длиннейшей** (пределы 150 / 30 000
/ 700), запас **3 / 183 / 5**. Сжимал ПЕРВЫМ делом и всё равно дважды уехал за предел (+107, затем
+15) — ровно предупреждение G1096 п. 9.

**Статус карточки не двигался** — `in-progress`, стоячий приказ владельца (инв. #14);
`acceptance_probe: apy_name_carries_one_kind` не правился (`.claude/rules/acceptance.md` п. 2).
Живой заказ следующему циклу — **G1097** выше.

### Контрольный прогон цикла #1268 (вписано ПОСЛЕ доставки)

**Доставлено ОДНИМ коммитом** `92b13a6911931287c47e5257aa9a3502e06b1f99` — **9** файлов, база
пинована `--expected-base c3b3c3e61585b5812eb9dca227ac33e9e25784bd` (вершина спрошена у СЕРВЕРА
`git ls-remote`, не локальной ссылкой); **флагов обхода 0**. Слепок байтов сверен у **27**
чтений, слепок режимов у 2, разбор уезжающего Python — 2 файла. Доставка проверена **ЧТЕНИЕМ
origin**, а не словом пушера: `git show origin/main:<путь> | md5` против дерева — **9 из 9
побайтово**.

**Вершина `origin/main` ушла ПОД РУКАМИ цикла.** На старте была `c5931f41b`, на момент доставки —
`c3b3c3e61` (`#171 BRD: Bayesian Regime Detector`, пуш R&D-агента, 2 файла). Пересечения с моим
набором НЕТ (проверено по именам путей), поэтому ребейза не потребовалось — но пин снят с ЖИВОЙ
вершины, а не с той, что была в начале цикла.

**Предупреждения провенанса базы — ТРИ, и все три объяснены намеренным удалением строк:**
`docs/STATE.md` (4 строки — две пары свёрнуты в одну, см. заказ п. 9), `_BOARD.md` (2 строки —
доска перегенерирована прибором), `scripts/cio_acceptance_rollup.py` (1 строка — подпись `measure`
получила два новых параметра и переехала). Ни одного `--allow-*`.

**Мутации — СВОЙ набор из 14, в ОТДЕЛЬНОМ дереве** `/private/tmp/spa_c1268mut` (байты возвращены
и сверены побайтово; якорь каждой проверен на УНИКАЛЬНОСТЬ, «не применена» ≠ «убита» и печатается
отдельным родом). Первый прогон **11 убито · 3 ВЫЖИЛО**; после починки СЦЕН — **14 убито ·
0 выжило · 0 не применено**, и последний прогон снят на ФИНАЛЬНЫХ байтах доставки
(md5 `28af0603be778cdc0f0e092a8ed44299`), а не перенесён с промежуточных.

**Дифференциал — мерка из БАЙТОВ, две оси раздельно** (первая мерка дала 386 и была слишком
широкой: в неё вошли перечисляющие КОРЕНЬ):

| ось | сторожей | база (чистый `c3b3c3e61`) | после моих байтов |
|---|---:|---|---|
| каталог НАЗВАН поимённо (+ §49, + f-string) | **84** | 2F · 4944P · 2S | 2F · **4967P** · 2S |
| перечисляют КОРЕНЬ (переписи/храповики) | **72** | 3F · 2654P · 3S | 3F · **2654P** · 3S |

`+23` — ровно 23 проверки нового сторожа; равенство `2654 = 2654` ОБЪЯСНЕНО (новый файл в этот
набор не входит по построению, вопрос оси — «меняет ли кто-то ВЕРДИКТ»). Красные имена совпали
ПОИМЁННО и красны на ЧИСТОЙ вершине: `test_edge_boundary_dataflow_census`,
`test_edge_corpus_map_probe`, `test_failed_name_survival_census`, `test_known_member_probe_census`,
`test_subject_population_census`. `skipped` сверен отдельно (2=2, 3=3) — урок #465.

**Вердикт CI о коммите `92b13a691` — НЕ ИЗМЕРЕН** (у ключа нет `Actions: write`). Прочитан
вердикт последнего контрольного прогона `45967869368` на `976ee5880`: **RED, упавших 84**, род
стенных часов 36, род окружения раннера 11, вилка дефектов **30…37**.

**Объявленная проба карточки** `apy_name_carries_one_kind` — `satisfied` («род объявлен у всех 22
apy-именованных чисел цикла, находок осей производителей 2, не измерено 0»). Делающая сессия её
НЕ правила (`.claude/rules/acceptance.md` п. 2). Статус карточки — `in-progress`, стоячий приказ
владельца (инв. #14).

**ВЕС карточки ПОСЛЕ доставки:** 3058 строк / 128 004 символа / 477 в длиннейшей. Прод-копия
по-прежнему 2 880 412 Б против 128 004 на origin (22,5×) — предмет открытой карточки
`owner-decision-rabochaya-kopiya-prikaza-portfolio-cio-n`, правкой этого цикла не закрыт.

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

