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
| ADR-054 | Kill-switch authority — source-separated latches (manual_pause vs risk/threat/execution), IE-owned effective state, durable state↔audit transaction (marker COMMITTED last), fail-CLOSED. **D-08 accepted: minimal Latch Schema v1** (7-field snapshot). **D-09 accepted (with modification): Transaction Marker & Audit Schema v1** (17-field marker incl. `old_state_hash`, 20-field hash-chained event; retention → future D-10). **D-11 accepted (with modification): Audit Recovery & Segment Schema v1** (16-field recovery metadata, authorized quarantine/segments, recovery ≠ audit authority, reducer never reads recovery.json). Thresholds UNCHANGED (extends ADR-034/048) | Accepted | [ADR-054](ADR-054-kill-switch-authority.md) (RFC `docs/rfcs/RFC-054-kill-switch-authority.md`; impl plan `docs/rfcs/RFC-054-implementation-plan.md`) |
| ADR-055 | Head-of-Investment agent layer — динамические тиры (T1/T2/T3 с движением), капитал-по-тирам по типу стратегии, максимизаторы доходности, решающий агент. Периодичность SENSE часто / ACT редко / DERISK быстро (paper vs реальные активы). Внутри потолков RiskPolicy v1.0 (не меняет пороги) | Accepted | [ADR-055](ADR-055-head-of-investment-agent-layer.md) |
| ADR-056 | rules_watchdog circuit-breaker читает РЕАЛЬНЫЕ файлы стоп-крана (`kill_switch_status.json.triggered` / `derisk_status.json.active`) + свежесть 26h → CRITICAL «missed cycle»; fail-CLOSED. Не меняет RiskPolicy/пороги (Variant A, карта storozh-pravil) | Accepted | [ADR-056](ADR-056-rules-watchdog-real-killswitch-files.md) |
| ADR-057 | go-live gate проверяет адаптеры по ИМПОРТУ, не только `compile()` — мёртвый MP-354 `pendle_pt_adapter` честно краснеет (28/29), закрыт false-green для всех 4 критериев-адаптеров (Variant Б, карта geit-gotovnosti) | Accepted | [ADR-057](ADR-057-golive-gate-import-based-adapter-checks.md) |
| ADR-YL-011 | Site Custodian — защита earn-defi.com от stale-чисел | Accepted | [ADR-YL-011](ADR-YL-011-site-custodian.md) |
| ADR-YL-012 | SPA Swarm — 5-слойный рой над aggressive-доменом (advisory) | Accepted | [ADR-YL-012](ADR-YL-012-spa-swarm.md) (charter `docs/SWARM_ARCHITECTURE.md`) |
| ADR-OWN-2026-07 | Пакет закрытых решений владельца (июль 2026) | Accepted | [ADR-OWN-2026-07](ADR-OWN-2026-07-owner-decisions-batch.md) |
| ADR-OWN-2026-07 (autoship) | Автономный авто-шип сайта под owner-gate (full auto-ship, owner-approved) | Accepted | [ADR-OWN-2026-07-autoship](ADR-OWN-2026-07-autoship.md) |
| ADR-OWN-2026-07 (lead-pings) | Мгновенный Telegram-пинг о крупных/B2B заявках (Q-OWN-16, one-shot key) | Accepted | [ADR-OWN-2026-07-lead-pings](ADR-OWN-2026-07-lead-pings.md) |
| ADR-OWN-2026-07 (repo-freeze) | Инцидент freeze-main-phase0: пуши восстановлены (bypass admin), запрет молчаливых изменений настроек репо/launchd | Accepted | [ADR-OWN-2026-07-repo-freeze-incident](ADR-OWN-2026-07-repo-freeze-incident.md) |
| ADR-OWN-2026-07 (readiness-truth) | Публичный READY ⇔ реальный гейт ready:true И score ≥80 (вариант А) | Accepted | [ADR-OWN-2026-07-readiness-truth](ADR-OWN-2026-07-readiness-truth.md) |
| ADR-TEST | Smoke-test контура владельца (ENV_SETUP v3, Этап 8) | Accepted | [ADR-TEST](ADR-TEST-smoke-2026-07-15.md) |

## Соглашения

- Нумерация: `ADR-NNN` (сквозная) либо `ADR-YL-NNN` (Yield Lab слой), `ADR-OWN-YYYY-MM` (пакеты owner-решений).
- Новый ADR: скопировать `_TEMPLATE.md` → `ADR-NNN-slug.md`, добавить строку в эту таблицу.
- Superseded-ADR не удаляем — помечаем статус и ссылку на заменяющий.
- `backfill TODO` — решение действует (описано в CLAUDE.md / коде), отдельный ADR-файл ещё не выписан.
