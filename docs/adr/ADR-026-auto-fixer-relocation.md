# ADR-026: Перенос auto_fixer из monitoring в dev_agents (LLM вне капитального домена)

**Статус:** ACCEPTED
**Дата:** 2026-06-22
**Владелец:** Yurii (Owner)

---

## Контекст

Аудит кода (`CODE_AUDIT_BACKLOG.md`, AUD-02) выявил нарушение FORBIDDEN-правила 4:

> `LLM_FORBIDDEN_AGENTS = {risk, execution, monitoring}` — в этих компонентах
> LLM-вызовы запрещены (prompt injection в капитал — критический вектор атаки).

Файл `spa_core/monitoring/auto_fixer.py` (автономный багфиксер) делал реальный
вызов Claude API (`anthropic.Anthropic().messages.create(...)` + raw-HTTP
fallback на `api.anthropic.com`) для починки исходного кода по алерту. Будучи в
`spa_core/monitoring/`, он формально нарушал правило 4.

Проект уже держал осознанный, но недокументированный carve-out:
`spa_core/monitoring/rules_watchdog.py` whitelist-ил `auto_fixer.py`
(`_KNOWN_EXCEPTIONS`), чтобы скан паттерна `anthropic.Anthropic(` его не валил.

По существу `auto_fixer` — **dev/repair-инструмент**, а не капитальный мониторинг:
он не читает рыночные данные и не влияет на `risk`/`execution`/`allocator`/
cycle-решения. В дневной цикл и launchd он не вшит.

## Решение

**Перенести `auto_fixer.py` из `spa_core/monitoring/` в `spa_core/dev_agents/`**
(Layer 1 development agents, где LLM разрешён — рядом с `architect.py`).

Следствия:

1. `spa_core/monitoring/` снова **буквально** чист по правилу 4 — никаких LLM-
   вызовов, carve-out больше не нужен.
2. `rules_watchdog._KNOWN_EXCEPTIONS` опустошён (`set()`); скан monitoring/risk/
   execution проходит без исключений.
3. Тесты `tests/test_auto_fixer.py` перенацелены на
   `spa_core.dev_agents.auto_fixer`. `BASE_DIR` неизменен (глубина пути та же:
   `spa_core/<dir>/file.py` → repo root через `parents[2]`).

Поведение `auto_fixer` не меняется; меняется только его доменная принадлежность.

## Последствия

- **+** FORBIDDEN-правило 4 выполняется без исключений; область «monitoring» как
  капитального домена больше не содержит LLM-кода.
- **+** Намерение явно зафиксировано в коде и ADR (раньше — только whitelist).
- **−** Никаких функциональных потерь; авто-починка сохранена.
- `RiskPolicy.version` не затрагивается (остаётся `v1.0`).

## Прочее (вне scope этого ADR)

- `auto_fixer.run_auto_fix` ссылается на несуществующий модуль
  `spa_core.monitoring.telegram_watcher` (`parse_alert_type`) — предсуществующий
  висячий импорт, ломающий 2 теста. Отслеживается в `CODE_AUDIT_BACKLOG.md`
  (AUD-15).
