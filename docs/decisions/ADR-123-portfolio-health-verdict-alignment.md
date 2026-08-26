# ADR-123 · Одно число — один вердикт: композитный portfolio health ниже пола = WARNING у обоих сторожей

**Дата:** 2026-08-22 · **Статус:** принято владельцем (вариант 1 из карточки
`agent-task-odno-chislo-dva-verdikta-portfolio-healt`, ответ в сессии 22.08)

## Проблема (замер 07.08, цикл #156)

Одно и то же число — `health_score` из `data/portfolio_health.json` — два сторожа
классифицировали по-разному при ОДНОМ пороге 70:

- `system_health_monitor` (`d6.health`): `score < 70` ⇒ **CRITICAL**, и весь системный
  вердикт становился CRITICAL в домене `d6_risk_gates`;
- `agent_health_monitor`: то же число ⇒ **WARNING**.

В `SYSTEM_BRIEFING` при `health_score = 69.43` это выглядело как «System Health 🔴 CRITICAL»
и рядом «Agents ⚠️ WARNING» — при одном источнике тревоги. Хуже того, имя домена
`d6_risk_gates: CRITICAL` читается как «сработал риск-гейт», хотя RiskPolicy в тот момент
`policy_compliant: true` и ни один гейт не отказывал.

## Решение (владелец, вариант 1)

**Композитная оценка качества портфеля ниже пола — это WARNING у ОБОИХ сторожей.**
CRITICAL в домене `d6_risk_gates` остаётся только за настоящими отказами гейтов:
нарушение T2-cap, kill-switch, критический red-flag по held-протоколу, safety-state.

Цена бездействия была не ложная тревога, а **обесценивание CRITICAL**: если самый громкий
уровень регулярно означает «композит на 0.6 пункта ниже порога», его перестают читать
буквально, и настоящий CRITICAL в том же домене приезжает в глухое ухо.

## Что меняется

- `system_health_monitor._check_portfolio_health`: `score < PORTFOLIO_HEALTH_FLOOR` ⇒
  WARNING (было CRITICAL). Порог 70 НЕ меняется; меняется только уровень.
- `agent_health_monitor` — без изменений (уже WARNING).
- Тест `test_d6_health_low_critical` переименован и ожидает WARNING — изменение
  намеренное, по этому ADR (инв. #16); добавлен контроль, что настоящие отказы гейтов
  в d6 остаются CRITICAL.

## Инварианты

RiskPolicy v1.0, kill-switch, пороги гейтов не тронуты — правка только в классификации
композитного качества у мониторингового сторожа. LLM_FORBIDDEN сохраняется.
