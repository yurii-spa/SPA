# SPA — Архитектура AI-операционного фонда Tier-1 (канонический север)

> **Тезис.** Моат — один оператор управляет операциями институционального уровня через
> ИИ-control-plane: ресёрч/риск/devops/реконсиляция/отчётность делает рой агентов, капиталом
> распоряжается человек через жёсткие гейты. Это и есть защитимая история.
>
> Этот документ — **канон архитектуры (SSOT)**. Презентация (сайт/бот) отражает SSOT, не наоборот.

## Три закона (нарушение любого → не Tier-1)

1. **Fail-safe, не fail-open.** Сбой/таймаут/неоднозначность → безопасное состояние (стоп
   действий, заморозка), не «продолжаем как ок». _Статус: threat_reactor fail-safe ✅; устранение
   fail-open в risk/EB-гейтах cycle_runner — в работе (см. карту)._
2. **Разделение мозга и рук.** Думающий слой физически отделён от действующего; плохая модель
   не двигает средства, только предлагает → риск → гейт. _Статус: ✅ (read-only не импортит
   execution; RiskPolicy детерминирован, LLM forbidden; execution dry-run)._
3. **Истина одна и неизменяема (SSOT).** Один канон на тип данных, остальное — read-only зеркала;
   каждое решение в неизменяемый аудит-лог. _Статус: hash-chain аудит ✅; SSOT-манифест — в работе._

## Восемь плоскостей — карта текущего покрытия

| Plane | Назначение | Что построено (this codebase) | Статус |
|---|---|---|---|
| **1.1 Strategy/Research** | стратегии как версионируемые конфиги; только предлагает | strategy_registry, tournament S0-S77, конфиг-аллокации | 🟡 (конфиги частично хардкод) |
| **1.2 Risk** | независимый, default-deny, kill-switch, инварианты | RiskPolicy v1.0 (LLM-forbidden) + kill_switch + emergency_breakers + tier1/limits + tail_risk + VaR/CVaR + stress | ✅ сильный |
| **1.3 Execution** | единственный двигает средства, в конверте риска, dual-control | execution/ (adapters dry_run, router, safety_checks: multisig/gas/sim/killswitch, engine_bridge live-gated) + tier1 readiness_audit + reconciliation | ✅ paper; live=custody |
| **1.4 Observability** | 24/7 мониторинг рынка+портфеля, anomaly→Risk | peg/red_flag/governance/gas/uptime/cycle мониторы + threat_reactor (интрадей kill) | ✅ |
| **1.5 Truth/SSOT** | канон на тип данных | GitHub=код/конфиг (GITHUB_ROLE.md); data/=стейт; run_manifest=версии+хэши | 🟡 (нужен явный SSOT-манифест) |
| **1.6 Presentation** | read-only зеркала SSOT | earn-defi.com (live API /api/live + /api/tier1) → дашборд/пакеты/агенты | 🟡 (убрали stale-цифры; добиваем live-mirror) |
| **1.7 Self-Healing** | супервизор+watchdog, safe-mode, backoff | self_heal (revive+probes) + threat_reactor + KeepAlive + dr_backup | 🟡 (watchdog-of-watchdog + один хост=SPOF) |
| **1.8 Audit/Provenance** | неизменяемый append-only, воспроизводимость | audit/hash_chain (tamper-evident) + run_manifest + nav_proof (verifiable NAV) | ✅ |

## Promotion Pipeline (ядро диверсификации) — покрытие

```
RESEARCH → BACKTEST → WALK-FORWARD → PAPER → CANARY → FULL
   🟡         ✅          ✅(OOS)        ✅      🔴       🔴
```
- BACKTEST: real-data + deflated-Sharpe + net-of-cost (tier1/evaluator). ✅
- WALK-FORWARD: tier1/oos (in-sample vs OOS, yield-hold). ✅
- PAPER→gate: tier1/gate (validated→eligible, is_eligible). ✅ + tournament консультирует.
- **CANARY (микро-капитал, реальное исполнение, узкие лимиты): 🔴 не построено** — следующий шаг.
- FULL: требует custody + dual-control (см. ниже).

## Governance: авто (ИИ) vs человек

Авто: витрина→SSOT, GitHub/CI, рестарт сервисов, бэктест/paper, отчёты/реконсиляция/аудит,
**заморозка при нарушении риск-инварианта (fail-safe)**. Человек: промоут canary→full, смена
аллокаций/лимитов, **любое движение средств (2 подписи)**, GoLive-даты/публичные APY, удаление/права.
_Статус: execution readiness_audit честно держит ready_for_live=False; dual-control = safety_checks
multisig-гейт (порог), полный 2-of-3 multisig = infra/custody._

## Дорожная карта (статус)

- **Фаза 0 — Фундамент истины:** SSOT-манифест 🟡, GitHub-назначение ✅, бэклог-канон 🔴.
- **Фаза 1 — Безопасные победы:** Presentation read-only 🟡, Telegram-бот 🟡 (флуд-guard ✅), watchdog/супервизор ✅.
- **Фаза 2 — Risk Plane:** default-deny/kill-switch/инварианты ✅; **fail-safe вместо fail-open 🟡 (в работе)**.
- **Фаза 3 — Promotion + Strategy:** конвейер ✅ до paper; **canary 🔴**; стратегии-конфиги 🟡.
- **Фаза 4 — Observability+Execution+Audit:** ✅ paper-уровень.
- **Фаза 5 — Развитие:** dev-агенты (нужен API-ключ/Max), авто-улучшения.

## Ближайшие кодовые гейты к 100/100 (что строю)
1. **Fail-safe enforcement** (Закон 1): убрать fail-open в risk/EB-проверках cycle_runner — сбой проверки = заморозка, не продолжение.
2. **Canary stage** в promotion pipeline (микро-капитал, узкие лимиты, человеческий гейт).
3. **Governance-as-code**: машиночитаемая политика авто-vs-человек + проверка dual-control-постуры.
4. **SSOT-манифест**: реестр «тип данных → канонический источник», презентация валидируется против него.

_Не-код (требует тебя/внешних): custody/MPC 2-of-3, внешний аудит, второй хост для HA, 30д трека._

*Принято 2026-06-24 как канон. Источники: [[TIER1_BACKTEST.md]], [[GITHUB_ROLE.md]], [[PACKAGES.md]].*
