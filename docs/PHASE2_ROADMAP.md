# SPA Phase 2 Roadmap

> **Создан:** 2026-06-12 | **Автор:** architect agent (v4.64)
> **Следующий review:** 2026-07-15 (go-live decision checkpoint)

---

## 1. Вердикт готовности к Phase 2

### Общий балл: **42 / 100** — НЕ ГОТОВ

Phase 1 аналитически завершена с запасом. Система технически зрелая и детерминированная.
Главный блокер — недостаток трека: 3 дня из 30 требуемых. Плюс три USER ACTION блокера,
которые не позволяют считать систему production-ready.

### Субоценки (взвешенные)

| Компонент | Балл | Вес | Обоснование |
|---|---|---|---|
| Paper trading engine | 92 | 15% | cycle_runner, risk gate, kill-switch — всё работает |
| Analytics suite | 88 | 10% | 30+ модулей: Drawdown, Ulcer, Rachev, Bias, Regime, Stress, Walk-Forward |
| Risk management | 82 | 15% | RiskPolicy v1.0 детерминированная; chain-concentration warning активен |
| Security architecture | 75 | 10% | ADR-010 (Safe/Zodiac) + ADR-011 (39-point checklist) — задизайнены, не deployed |
| Мониторинг/алерты | 62 | 10% | gap_monitor ✅, Telegram ✅, но daily report в dry_run, autopush сломан |
| Инфраструктура | 55 | 10% | autopush ❌, GitHub Pages ❌, RPC keys ❌ |
| Track record | 10 | 30% | 3 / 30 дней реального трека (2026-06-10 → 2026-07-10) |

**Формула:** (92×0.15 + 88×0.10 + 82×0.15 + 75×0.10 + 62×0.10 + 55×0.10 + 10×0.30) = **~42**

---

## 2. Текущее состояние (2026-06-12)

```
Equity:         $100,026.06  (+0.026%, 3 дня)
APY сегодня:    3.20% (~$8.76/день)
GoLiveChecker:  READY (все 6 критериев проходят с 2026-06-10)
gap_monitor:    OK (0 пробелов)
Дней до go-live решения: ~50 дней (целевая дата ~2026-08-01)
```

### Что уже сделано (Phase 1 / paper track)

- ✅ Детерминированный ежедневный цикл (launchd 08:00, без LLM в runtime)
- ✅ RiskPolicy v1.0 gate (каждая сделка через policy.check())
- ✅ Kill-switch (drawdown ≥5% → закрыть всё) + kill_switch_drill ✅ (13ms)
- ✅ Gap monitor + автоматическое восстановление
- ✅ Telegram alerts (red flag, gap, milestone, startup test)
- ✅ Capital Ladder enforcement (L0→L1 criteria coded, ADR-010/011)
- ✅ Gnosis Safe + Zodiac Roles архитектура (ADR-010) + key management policy
- ✅ Go-live security checklist 39 пунктов (ADR-011)
- ✅ ADR-002 правило переноса go-live
- ✅ 30+ аналитических модулей (investor DD-grade)
- ✅ Decision Audit Trail
- ✅ Stress Engine (COVID-2020, LUNA-2022, USDC-depeg-2023)
- ✅ Walk-Forward validation
- ✅ E2E fork harness (MP-401)
- ✅ Investor dashboard (v3.0)

---

## 3. Критический путь к первой live-транзакции

Минимальный набор действий в хронологическом порядке:

```
2026-06-12  ● СЕЙЧАС
            │
            ▼ [USER ACTION ~5 мин]
            MP-313: bash mp009_fix_launchd.command   ← P0 BLOCKER
            │
            ▼ [USER ACTION ~2 мин]
            UA-004: GitHub Pages → main/root          ← P1 публичный дашборд
            │
            ▼ [USER ACTION ~15 мин]
            MP-017: RPC keys Alchemy/Infura в Keychain ← P1 Pendle +2-3% APY
            │
            ▼ [autonomous, 0.5d]
            MP-314: Активировать daily Telegram report (снять dry_run)
            │
            ▼ [ждать: ~27 дней непрерывного трека]
2026-07-10  ● 30 дней честного трека ← ADR-002 gate #2
            │  GoLiveChecker READY 7+ дней подряд ← ADR-002 gate #1
            │
            ▼ [manual, ~1ч]
2026-07-15  ● Owner review: equity curve, trades, risk_policy_blocks, golive_status
            │  Обновить ADR-002: вписать дату фактического разрешения
            │
            ▼ [autonomous, 0.5d]
2026-07-17  ● ADR-011 pre-flight: пройтись по 39-point checklist
            │  Проверить activation.py готовность
            │
            ▼ [физические действия: Ledger + Trezor + Safe deploy]
2026-07-25  ● Gnosis Safe deployed (2-of-3: Ledger + Trezor + cold)
            │  Zodiac Roles module настроен (EXECUTOR, GUARDIAN, OPERATOR)
            │  Testnet E2E прогон через fork harness
            │
            ▼ [activate.py с ручным вводом "I CONFIRM LIVE TRADING"]
~2026-08-01 ● ПЕРВАЯ LIVE-ТРАНЗАКЦИЯ (L1: $10-50K личных средств)
```

### Топ-5 блокеров до go-live

| # | Блокер | Тип | ETA | Критичность |
|---|--------|-----|-----|-------------|
| 1 | Track record 30 дней | Время | 2026-07-10 | P0 — без этого go-live невозможен |
| 2 | MP-313: autopush | USER ACTION | Немедленно | P0 — код не пушится, прогресс невидим |
| 3 | ADR-002 GoLiveChecker 7+ дней | Время | 2026-06-17 | P0 — встроен в правило перехода |
| 4 | UA-004: GitHub Pages | USER ACTION | Немедленно | P1 — публичный дашборд для доверия |
| 5 | Gnosis Safe физический deploy | Человеческое действие | До 2026-07-25 | P1 — нужен перед первым live |

---

## 4. Phase 2 приоритизация (зависимости)

```
MP-402 (Safe+Zodiac) ✅ DONE
    └─► MP-403 (Live пилот $10-50K)  ← минимальный Phase 2
            └─► MP-404 (ERC-4626 vault Conservative) ← 20д работы
                    └─► MP-405 (Smart contract audit #1) ← 4-6 недель внешних
                    └─► MP-503 (Safe Apps/DeBank/Zapper)
                    └─► MP-504 (Vault профили Balanced/Aggressive)
                            └─► MP-506 (Аудиты #2-3 + Hypernative/Forta)
                    └─► MP-410 (Bug bounty Immunefi) ← после аудита
                        └─► MP-507 (Команда: +SC инженер, +0.5 ops)
```

**Минимальный путь к live-пилоту:** MP-402 ✅ → 30d track → ADR-002 → MP-403

**ERC-4626 vault не нужен для личного пилота** ($10-50K собственных).
Vault нужен только для внешнего AUM. Это снижает риск первого шага.

---

## 5. Sprint Plan v4.64 – v4.70

### v4.64 (2026-06-12 — 2026-06-19) — Phase 2 Foundation

**Тема:** Подготовка документации + активация daily report

| Задача | Тип | Статус |
|--------|-----|--------|
| PHASE2_ROADMAP.md (этот файл) | docs | ✅ в процессе |
| MP-314: Активировать Telegram daily report | autonomous | backlog |
| SYS-008: Поставить delivery_status во все done-карточки | KANBAN hygiene | backlog |
| Подготовить ADR-011 pre-flight скрипт | autonomous | backlog |

### v4.65 (2026-06-19 — 2026-06-26) — Pendle + Public Infra

**Тема:** Если MP-017 (RPC keys) сделан — Pendle PT интеграция (+2-3% APY)

| Задача | Блокер | Приоритет |
|--------|--------|-----------|
| MP-201: Pendle PT adapter | MP-017 (USER ACTION) | P1 |
| UA-004: GitHub Pages активация | USER ACTION | P1 |
| GitHub Actions CI matrix | UA-006 (USER ACTION) | P2 |

### v4.66 (2026-06-26 — 2026-07-03) — Analytics & Monitoring Polish

**Тема:** Закрыть оставшиеся аналитические пробелы и усилить monitoring

| Задача | Описание |
|--------|----------|
| Enhanced investor dashboard | Public-facing view с живыми данными |
| Weekly performance summary | Автоматический недельный отчёт в Telegram |
| Chain concentration fix | CHAIN_LIMIT_WARN ethereum 73-84% > 70% — аллокатор |

### v4.67 (2026-07-03 — 2026-07-10) — 30-Day Track Milestone

**Тема:** Финальная подготовка к go-live решению

| Задача | Описание |
|--------|----------|
| ADR-011 pre-flight 39-point checklist | Автоматизированная проверка всего что можно |
| Capital Ladder L0→L1 eligibility report | Автоматический отчёт о соответствии |
| GoLiveChecker streak verification | Убедиться что 7+ дней подряд READY |
| Owner review пакет | Подготовить equity curve + trades + risk summary для ручного review |

### v4.68 (2026-07-10 — 2026-07-17) — Go-Live Decision

**Тема:** Принятие решения о live-пилоте (требует ручных действий Owner'а)

| Задача | Тип |
|--------|-----|
| Owner: manual review equity curve, trades, blocks | MANUAL |
| Owner: обновить ADR-002 (вписать дату разрешения) | MANUAL |
| Подготовить Gnosis Safe deployment инструкцию | autonomous |
| Testnet E2E через fork harness | autonomous |

### v4.69 (2026-07-17 — 2026-07-24) — Safe Deployment

**Тема:** Physical security setup + deployment

| Задача | Тип |
|--------|-----|
| Owner: Gnosis Safe deployed (Ledger + Trezor + cold key) | USER ACTION |
| Owner: Zodiac Roles module настроен | USER ACTION |
| Executor hot-key первый тест (testnet) | тест |
| activate.py dry-run без подтверждения | autonomous |

### v4.70 (2026-07-24 — ~2026-08-01) — LIVE PILOT

**Тема:** Первая реальная транзакция

| Задача | Описание |
|--------|----------|
| Owner: activate.py "I CONFIRM LIVE TRADING" | USER ACTION — $10-50K |
| First live rebalance observation | мониторинг |
| Daily report проверка в production | верификация |
| Capital Ladder: L0 → L1 transition log | ADR запись |

---

## 6. Phase 2 риски

| Риск | Вероятность | Влияние | Митигация |
|------|-------------|---------|-----------|
| **Gap в треке → перенос go-live** | Средняя | Высокое | gap_monitor + auto-recovery |
| **Smart contract риск (нет аудита)** | Средняя | Критическое | Gnosis Safe 2-of-3, MAX_SINGLE_TX=20% AUM |
| **Protocol incident во время pilot** | Низкая | Высокое | Kill-switch (5% drawdown), diversification (5 протоколов) |
| **RPC keys недоступны → Pendle blocked** | Низкая | Среднее | Aave+Compound T1 достаточны без Pendle |
| **Bus factor = 1** | Высокая | Критическое | MP-507: найм SC инженер после L1 |
| **Chain concentration (ethereum 73-84%)** | Высокая | Среднее | Ждать new T2 протоколов других chain'ов |
| **APY collapse (<1% из-за рыночных условий)** | Средняя | Среднее | Kill-switch не срабатывает при APY-drop, monitor вручную |
| **PAT rotation забыта** | Низкая | Высокое | MP-071: pat_rotation_helper.py; следующий rotate до 2026-09-01 |

---

## 7. Финансовая модель Phase 2

| Ступень | Капитал | Цель | ETA |
|---------|---------|------|-----|
| L1 Live pilot | $10-50K личных | Доказать исполнение | ~2026-08-01 |
| L2 Scale personal | $50-200K | Доказать масштаб | ~2026-10-01 |
| L3 External seed | $200K-1M | Первый внешний инвестор | ~2027-Q1 |
| L4 Fund I | $1M-5M | Настоящий AUM | ~2027-Q3 |
| L5 Institutional | $10M+ | Track record 12+ мес | ~2028 |

**Минимальный бюджет до L3:** ~$200-400K (аудит $100-250K + ops)

---

## 8. Что делать СЕЙЧАС (порядок действий)

### USER ACTION (требует Юрия, ~22 минуты суммарно):

```bash
# 1. Починить autopush (~5 мин) — P0
bash ~/Documents/SPA_Claude/mp009_fix_launchd.command
launchctl list | grep com.spa.autopush   # должно показать активный демон

# 2. Включить GitHub Pages (~2 мин) — P1
# GitHub.com → репо SPA_Claude → Settings → Pages → Source: main / root → Save

# 3. RPC keys (~15 мин) — P1 (нужны для Pendle)
# Зарегистрировать на alchemy.com, добавить в Keychain:
# security add-generic-password -s ALCHEMY_API_KEY -w <key>
# security add-generic-password -s INFURA_API_KEY -w <key>
```

### Autonomous (агент делает сам):

1. Активировать Telegram daily report (снять dry_run флаг) — MP-314
2. ADR-011 pre-flight скрипт — проверить все автоматизируемые пункты checklist
3. Следить за треком ежедневно, алертить при любом gap

---

*Обновлён: 2026-06-12. Следующий review: 2026-07-15 (go-live decision checkpoint).*
