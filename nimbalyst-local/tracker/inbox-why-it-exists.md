---
trackerStatus:
  type: inbox
title: WHY IT EXISTS
status: done
source: telegram
created: 2026-08-13
---

## Задание (из Telegram)

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
