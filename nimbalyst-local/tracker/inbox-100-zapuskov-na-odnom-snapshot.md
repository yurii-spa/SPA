---
trackerStatus:
  type: inbox
title: 100 запусков на одном snapshot.
status: done
source: telegram
created: 2026-08-13
---

## Задание (из Telegram)

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

---
_Оркестратор: классифицируй (задача/идея/непонятно), при исполнении закрой карточку со ссылкой на порождённую работу (§6.4)._

## Закрыто 2026-08-15 — это не задание, а кусок одного документа

Карточка родилась из разреза ОДНОГО сообщения владельца («TASK — Portfolio CIO: Dynamic
Capital Allocation & Rebalancing», 13.08). В отрыве от остального текста смысла не имеет.
Весь документ склеен обратно в **`inbox-task-portfolio-cio-dynamic-capital-alloc`** —
работа ведётся там. Текст владельца не редактировался, порядок восстановлен по нумерации
разделов самого документа (§1…§52).

Сам дефект интейка (длинный текст → семь «заданий») — отдельная карточка
`inbox-dlinnyi-dokument-vladeltsa-priehal-semyu`, она остаётся открытой.

---

## Волна 0 триажа, 16.08 — откуда эта карточка и куда она ведёт

Карточка **не задача, а кусок одного документа владельца**. 13.08 в 13:10 интейк разорвал
спецификацию «TASK — Portfolio CIO: Dynamic Capital Allocation & Rebalancing» на **семь**
карточек за 21 секунду; настоящая из них одна, остальные шесть — заголовки разделов и обрывки
предложений. Замер и список — `inbox-dlinnyi-dokument-vladeltsa-priehal-semyu`.

**Собранная задача:** `inbox-task-portfolio-cio-dynamic-capital-alloc`, которая 16.08 схлопнута
в `agent-head-of-investment-layer` (кластер К14, `docs/BACKLOG_TRIAGE_2026-08-16.md`).
Принятое по теме — `docs/decisions/ADR-088-portfolio-cio-advisory-layer.md` и
`ADR-089-portfolio-cio-followups-2026-08-15.md`.

Статус карточки (`done`) не менялся — дописана только ссылка, которой не хватало для
прослеживаемости. Чинить надо интейк (`spa_core/telegram/inbox_intake.py`), иначе следующий
длинный документ владельца снова раздуется в семь карточек; это открытая карточка
`inbox-dlinnyi-dokument-vladeltsa-priehal-semyu`.
