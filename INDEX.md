# ADR INDEX — реестр архитектурных решений

> Каждое решение, меняющее инвариант / risk-логику / контур, оформляется ADR по шаблону
> `_TEMPLATE.md` (Контекст → Решение → Последствия). **Перед изменением risk-логики —
> прочитать соответствующий ADR.**

| ADR | Заголовок | Статус | Файл |
|---|---|---|---|
| ADR-029 | Research strategies framework | Accepted | [ADR-029](ADR-029-research-strategies-framework.md) |
| ADR-030 | PIT backtest standard | Accepted | [ADR-030](ADR-030-pit-backtest-standard.md) |
| ADR-034 | Two-tier kill-switch (исходный) | Superseded by ADR-048 | *(историческое, см. ADR-048)* |
| ADR-048 | Two-tier kill-switch SOFT −5% / HARD −10% inclusive | Accepted | [ADR-048](ADR-048-two-tier-kill-switch.md) |
| ADR-050 | RiskPolicy → governance-слой; API auth; exec-bypass закрыт | Accepted | [ADR-050](ADR-050-riskpolicy-governance-layer.md) |
| ADR-053 | RTMR real-time monitoring sense-loop | Accepted | [ADR-053](ADR-053-rtmr-sense-loop.md) |
| ADR-YL-011 | Site Custodian — защита earn-defi.com от stale-чисел | Accepted | [ADR-YL-011](ADR-YL-011-site-custodian.md) |
| ADR-YL-012 | SPA Swarm — 5-слойный рой над aggressive-доменом (advisory) | Accepted | [ADR-YL-012](ADR-YL-012-spa-swarm.md) (charter `docs/SWARM_ARCHITECTURE.md`) |
| ADR-OWN-2026-07 | Пакет закрытых решений владельца (июль 2026) | Accepted | [ADR-OWN-2026-07](ADR-OWN-2026-07-owner-decisions-batch.md) |
| ADR-TEST | Smoke-test контура владельца (ENV_SETUP v3, Этап 8) | Accepted | [ADR-TEST](ADR-TEST-smoke-2026-07-15.md) |

## Соглашения

- Нумерация: `ADR-NNN` (сквозная) либо `ADR-YL-NNN` (Yield Lab слой), `ADR-OWN-YYYY-MM` (пакеты owner-решений).
- Новый ADR: скопировать `_TEMPLATE.md` → `ADR-NNN-slug.md`, добавить строку в эту таблицу.
- Superseded-ADR не удаляем — помечаем статус и ссылку на заменяющий.
- `backfill TODO` — решение действует (описано в CLAUDE.md / коде), отдельный ADR-файл ещё не выписан.
