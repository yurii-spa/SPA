# Memory Facts — SPA Project

Извлечённые memory-факты Claude о проекте SPA, актуальные на момент сборки архива (2026-05-22).

---

## Текущий статус

### Sky / sUSDS

- **Текущий статус:** Вариант A (Watch List, 0% T1).
- **Причина:** GSM Pause Delay = 24h, не соответствует требованию ≥48h.
- **Условие пересмотра:** при следующем фоновом ревью агентами (Q3 2026 или при on-chain подтверждении 48h timelock).
- **При подтверждении 48h timelock:** Sky переходит в Tier 1 с весом 30% (вместо текущих 10% в формальной документации v0.4.5).

> **Заметка:** есть расхождение между memory facts ("Sky Watch List, 0%") и документацией v0.4.5 ADR-006/007 ("Sky T1, 10%"). Это объясняется так: документация v0.4.5 была написана **в предположении**, что 48h timelock будет подтверждён. Memory facts фиксируют, что подтверждения пока **не было** → operationally Sky остаётся на Watch List, аллокация = 0%.
>
> При on-chain подтверждении: документация v0.4.5 становится действующей as-is с пересмотром доли до 30% (вместо 10%).
> При отсутствии подтверждения: позиция Sky в T1 = 0% независимо от документации.

### Архитектура мониторинга

- Агенты делают **фоновое ревью протоколов** по Tier 1 / Tier 2 / Tier 3.
- Whitelist **не статичный** — пересматривается при **каждом цикле**.
- Sky GSM Pause Delay — **первый триггер** для пересмотра whitelist (cycle Q3 2026 или earlier при on-chain event).

---

## Эволюция версий (для контекста)

- **v0.3** (май 2026): Conservative, yield ≥4%, drawdown ≤2%. Aave V3 + Compound V3 в T1; Sky в Watch List.
- **v0.4** (2026-05-01): Aggressive, yield ≥8%, drawdown ≤5%. Sky повышен в T1 (aspirational); TRR → sUSDS.
- **v0.4.5** (2026-05-03): Hybrid + Yearn V3 yvUSDC (T1-05, 10%). Финансовая сверка (ADR-009).
- **Current operational state:** v0.4.5 documentation, но Sky T1 holding 0% pending GSM Pause Delay подтверждения.

---

## Финансовые таргеты (v0.4.5, после ADR-009)

| Капитал | Net APY | Чистый доход / год |
|---|---|---|
| $10K | 4.0% | $400 |
| $25K | 6.2% | $1,545 |
| $50K | 6.9% | $3,452 |
| $100K | 7.3% | $7,266 |
| $250K | 7.5% | $18,707 |

Gross weighted APY (whitelist v0.4.5, расчётный): **7.4%**.
Aspirational target при >$250K: **≥9%** (upside, не baseline).

---

## Build & Sprint Status (2026-06-12 — v4.67)

| Metric | Value |
|--------|-------|
| Current sprint | **v4.67** |
| Tests passing | **~400+** (121 spa_core/tests + 77 family_fund + 40 telegram + 32 risk + 50+ strategies + 11 integration) |
| Dashboard version | v4.67 (7 tabs: Home, Paper Trading, Analytics, Go-Live, Agents, System, 🏆 Tournament) |
| Last sprint date | 2026-06-12 |
| Telegram | **LIVE** (dry_run=False, MP-350) |
| Family Fund | spa_core/family_fund/ (MP-156) — models, registry, pnl_attribution, telegram_blast |
| Strategies | S8 delta-neutral sUSDe, S9 e-mode looping, S10 Pendle YT (ADR-021 T3) |
| ADRs | ADR-019 T2 cap 50%, ADR-020 T3 private credit 15%, ADR-021 Pendle YT T3 |
| Risk config | ETHEREUM chain limit 90%, T2 cap 50%, T3 private credit cap 15% |
| Investor portal | investor_portal.html (MP-158, RU/UA/EN) |
| Legal | docs/legal/: ДПТ template + onboarding checklist (MP-162) |
| Memory file | [spa_v467_status.md](spa_v467_status.md) — детальный статус v4.67 |

### Предыдущий статус (2026-05-22, v1.6)

| Metric | Value |
|--------|-------|
| Sprint | **v1.6** |
| Tests passing | **~140** |
| Files on GitHub | **116+** (manifest 111 + new docs/tests) |
| Dashboard version | v1.6 (6 tabs) |
| Last sprint date | 2026-05-22 |

---

## Paper trading status

- Paper trading **реальный** с 2026-06-10 (сброс демо-данных, is_demo: false).
- Go-live decision date: **~2026-08-01** (перенос с 07-15 — ADR-002).
- 30 честных дней трека истекают ~2026-07-10.
- GoLiveChecker: NOT READY (trades_real: false — реальных трейдов is_demo:false ещё нет).

### Предыдущий статус paper trading (2026-05-22)
- Paper trading активен с 2026-05-20 (Day 2 of 56 as of 2026-05-22).
- Baseline Week 0 зафиксирован на 2026-05-02.
- Go-live decision date: 2026-07-15.
- Current APY: ~4.2% | Target: 7.3%.

---

## Контекст пользователя

- Язык общения: русский.
- Стиль: краткие сообщения, ожидание substantive deep answers.
- Часть документации project knowledge (`/mnt/project/`) переходит через сессии.
