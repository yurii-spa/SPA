# Архитектурный Review v4.68 — Wave 10 Strategic Plan
> **Автор:** Principal DeFi Engineer / Product Architect  
> **Дата:** 2026-06-12  
> **Sprint:** v4.68 → v4.69 (Wave 10)  
> **Статус:** ISSUED — к исполнению

---

## 1. Executive Summary v4.68

Sprint v4.68 завершён с 7 задачами в done. Задачи условно делятся на два типа: **инфраструктура** (CI, DR, доказательство трека) и **стратегии/адаптеры** (S8/S9/S10, tournament evaluator, Pendle PT). Оба направления продвинулись, но критический разрыв остался: новые адаптеры и стратегии созданы как файлы, но **не интегрированы в боевой цикл**. Результат — APY по-прежнему 3.1969%, несмотря на наличие компонентов, которые могут поднять его до 6-9%.

**v4.68 Done (7 задач):**

| ID | Задача | Ценность |
|----|--------|----------|
| MP-363 | GitHub Actions CI | Блокирует молчаливые регрессии |
| MP-361 | ADR-019 paper test (T2 cap) | Разблокирует Pendle-heavy аллокации |
| MP-364 | Proof of track anchor | Устраняет единственный warn в data_integrity |
| MP-362 | DR_PROCEDURE_v2.md | Защита перед первым инвестором |
| MP-354 | Pendle PT REST adapter | Главный APY unlocker (~8-18%) — файл создан |
| MP-366 | Tournament auto-promotion engine | Детерминированный promote/demote/kill |
| MP-370 | push_v468.sh batch push | Утилита пуша спринта |

**Главная проблема v4.68:** реализованы компоненты (адаптеры, стратегии, orchestration pipeline), но они НЕ подключены к cycle_runner.py. Цикл продолжает работать со старым набором протоколов и APY 3.2%. Wave 10 посвящён устранению этого разрыва.

---

## 2. APY Progress: 3.2% → Где мы сейчас, куда идём

### Текущее состояние (2026-06-12)

```
Equity:        $100,026.06  (+$26.06 от старта)
APY сегодня:   3.1969%
Ежедневный yield: $8.76 / $100K
Позиции:       aave_v3 / compound_v3 / yearn_v3 / euler_v2 / maple
```

**Почему 3.2%, если сделано столько работы?**

Aave Arbitrum (4.6% APY) добавлен в ADAPTER_REGISTRY, но в `data/current_positions.json` его нет — аллокатор видит его как новый пул с неизвестной TVL историей и не назначает туда капитал, пока APY-преимущество не покрывает порог ребалансирования. Morpho Steakhouse (6.5% APY) создан как адаптер, но **не внесён в ADAPTER_REGISTRY** — цикл его попросту не видит. Pendle PT adapter существует в трёх файлах (pendle_pt.py, pendle_pt_adapter.py, pendle_adapter.py), но ни один не зарегистрирован как PendlePTAdapter в ADAPTER_REGISTRY.

### APY Roadmap (реалистичный)

| Этап | Действие | Ожидаемый APY | Срок |
|------|----------|--------------|------|
| Текущий | — | 3.2% | сейчас |
| Шаг 1 | Morpho Steakhouse в ADAPTER_REGISTRY (MP-375) | ~5.1% | v4.69 (1 день) |
| Шаг 2 | Pendle PT в ADAPTER_REGISTRY + T2 cap (MP-375 + ADR-019) | ~6.5% | v4.69 (1 день) |
| Шаг 3 | Aave Arbitrum allocation активирована (MP-380 диагностика) | ~7.0% | v4.69 (2-3 дня) |
| Шаг 4 | MultiStrategyRunner выбирает лучшую стратегию (MP-377) | ~7.5-9% | v4.70 (5-7 дней) |
| Цель go-live | — | **7-10%** | 2026-08-01 |
| Цель Family Fund | — | **10-15%** | 2027+ |

**Честная оценка:** 7-9% APY реалистично к 2026-07-01 при выполнении MP-375 и MP-380. 10%+ требует либо bull market (sUSDe APY > 15%), либо реальной работы S8 delta-neutral стратегии, которая в текущем нейтральном рынке даёт только 5-7%.

---

## 3. Risk Assessment: Новые стратегии S8 / S9 / S10

### S8 — Delta-Neutral sUSDe (~27.5% APY в bull mode)

**Механика:** spot long sUSDe + perp short ETH-perpetual хедж. Нейтральная к направлению рынка, зарабатывает на funding rate дифференциале (sUSDe staking yield − perp funding cost).

**Риски:**
- **Funding regime risk** (HIGH): при медвежьем рынке perp funding отрицательный → стратегия убыточна. Текущий sUSDe APY ~5% (нейтральный рынок), а не 12%+.
- **Execution complexity** (HIGH): требует обе позиции одновременно; в paper-режиме perp хедж симулирован, не реален.
- **Counterparty risk** (MEDIUM): Ethena Protocol и centralized perp exchange.
- **Verdict:** ADVISORY ONLY. Не открывать позиции автоматически до go-live. Потенциал бычьего рынка реален, текущий рынок не соответствует профилю.

### S9 — E-Mode Looping (~5.84% net APY)

**Механика:** Aave V3 E-Mode USDC/USDT loop — borrow USDT, поставить как USDC в E-Mode (max LTV 93%), повторить 3-5 раз. Net yield = supply rate * leverage − borrow rate.

**Риски:**
- **Rate spread compression** (MEDIUM): если borrow rate > supply rate * leverage_factor → отрицательный yield. Исторически в E-Mode это случается при market stress.
- **Liquidation risk** (LOW в paper, HIGH при live): leverage 5x → при депег USDT/USDC на 1.5%+ позиция под ликвидацией.
- **Gas costs** (LOW в paper): в live режиме loop требует 3-5 on-chain транзакций при каждом ребалансе → газ съедает часть yield.
- **Verdict:** PAPER ONLY до go-live. После go-live — только с Gnosis Safe и ручным подтверждением каждой транзакции.

### S10 — Pendle YT (14-42% APY, T3-SPEC)

**Механика:** покупка Yield Token (YT) Pendle — право на будущий yield базового актива. При росте APY базового актива (sUSDe) YT дорожает нелинейно.

**Риски:**
- **Convexity risk** (HIGH): YT цена падает до нуля на дату экспирации, даже при правильном направлении.
- **Liquidity risk** (HIGH): Pendle markets имеют ограниченную ликвидность, спред 0.5-2%.
- **Market timing** (HIGH): входить нужно до роста APY, выходить — до экспирации; оба момента сложно предсказать.
- **Verdict:** ADVISORY, T3-SPEC — ADR-021. Открытие позиций только ручное Owner-решением. Не включать в автоматический allocator.

---

## 4. Integration Gaps: Что не подключено к cycle_runner

Это критический раздел. Всё перечисленное **существует как код**, но **не работает в боевом цикле**.

### Gap 1: ADAPTER_REGISTRY (КРИТИЧЕСКИЙ — прямо влияет на APY)

```
Созданы, но НЕ в ADAPTER_REGISTRY:
  spa_core/adapters/morpho_steakhouse_adapter.py  → MorphoSteakhouseAdapter (6.5% APY)
  spa_core/adapters/pendle_pt_adapter.py          → PendlePTAdapter (8-18% APY, T2/T3-SPEC)

Есть в ADAPTER_REGISTRY, но не в current_positions:
  aave_arbitrum  → AaveArbitrumAdapter (4.6% APY) — нет аллокации почему?

Текущий ADAPTER_REGISTRY:
  T1: aave_v3, compound_v3, aave_arbitrum
  T2: morpho_blue (generic!), yearn_v3, euler_v2, maple, pendle (generic!)
```

**Фикс (MP-375):** добавить MorphoSteakhouseAdapter как замену morpho_blue или параллельно; добавить PendlePTAdapter как T2 (cap per ADR-021: advisory only, 0% автоматической аллокации).

### Gap 2: MultiStrategyRunner не вызывается из cycle_runner

```python
# cycle_runner.py — что должно быть, но нет:
from spa_core.paper_trading.multi_strategy_runner import MultiStrategyRunner

# ... внутри run_cycle():
runner = MultiStrategyRunner(data_dir=data_dir)
runner.run(strategies=all_strategies, apy_map=apy_map)
```

MultiStrategyRunner создан в MP-357/v4.68. Без вызова из cycle_runner ежедневный tournament не происходит: стратегии S0-S10 не соревнуются, tournament_ranking.json не обновляется.

### Gap 3: PromotionEngine не вызывается из cycle_runner

```python
# cycle_runner.py — что должно быть, но нет:
from spa_core.paper_trading.promotion_engine import PromotionEngine

# ... после tournament:
promo = PromotionEngine(data_dir=data_dir)
promo.run(tournament_result)
```

PromotionEngine (MP-366/v4.68) реализует PROMOTE_SHARPE=0.8, KILL drawdown < -10%. Без вызова advisory решения никуда не записываются.

### Gap 4: http_server.py не установлен как launchd service

```
Есть: spa_core/family_fund/http_server.py (stdlib TCP, port 8765)
Есть: com.spa.httpserver.plist в репо
Нет:  ~/Library/LaunchAgents/com.spa.httpserver.plist (не установлен)
```

Семейный инвесторский портал не доступен без постоянно запущенного http_server. Для перезапуска после reboot нужен plist в LaunchAgents.

### Gap 5: GoLiveChecker — только 6 из планируемых 26 критериев

Текущий golive_checker.py реализует 6 anti-demo проверок (equity_curve_real, trades_real, status_real, no_demo_data, data_fresh_48h, cycle_runner_exists). Все 6 сейчас проходят (`"ready": true`). Однако CLAUDE.md описывает 26-критериальную систему с группами:

1. Data integrity (4 чека)
2. Freshness (2 чека)
3. Continuity — gap_monitor 30 дней (3 чека)
4. Infrastructure — autopush, Telegram, launchd health (5 чеков)
5. Performance — min track days, APY threshold, drawdown (5 чеков)
6. Compliance — adapter audit, ADR confirmations, risk policy snapshot (7 чеков)

20 дополнительных чеков не реализованы. До go-live нужна полная версия.

---

## 5. Wave 10 Plan: 10 задач с обоснованием

### P0 — Незакрытые блокеры из прошлых спринтов

**MP-374** (P0, v4.69) | Telegram daily report: снять dry_run → production  
Telegram настроен, токены в Keychain, но `daily_report` работает в dry_run. Без реальных алертов мониторинг 30-дневного трека — слепой полёт. **30 минут работы, ноль блокеров.**

### P1 — APY и интеграция (Week 1 of Wave 10)

**MP-375** (P1, v4.69) | ADAPTER_REGISTRY: добавить Morpho Steakhouse + Pendle PT  
Единственное действие, которое немедленно двигает APY с 3.2% к 5-6%. Morpho Steakhouse заменяет generic Morpho Blue в реестре (+150-190 bps). Pendle PT добавляется как T2/advisory (0% автоматической аллокации per ADR-021). Aave Arbitrum диагностика: почему нет в current_positions при наличии в реестре?

**MP-376** (P1, v4.69) | GoLiveChecker v2: расширить до 26 критериев  
Текущий 6-чековый checker проходит — это хорошо, но недостаточно для честного go-live decision. Реализовать группы Infrastructure (autopush, Telegram, launchd) и Performance (min 30 track days, APY > threshold, 0 drawdown events). При этом сохранить обратную совместимость: `"checks_v1": {...}` (6 чеков, источник истины для dashboard), `"checks_v2": {...}` (20 новых, advisory).

**MP-377** (P1, v4.69) | Cycle_runner: wire MultiStrategyRunner (ежедневный tournament)  
После добавления вызова в cycle_runner ежедневный tournament начинает работать. S0-S10 соревнуются по Sharpe/Calmar/Ulcer/Rachev, winner логируется. Данные tournament_ranking.json обновляются каждый день. Без этой интеграции tournament — мёртвая аналитика.

**MP-378** (P1, v4.69) | Cycle_runner: wire PromotionEngine post-tournament  
После MP-377: добавить вызов PromotionEngine после tournament. Решение PROMOTE/DEMOTE/HOLD/KILL записывается в data/promotion_report.json. Advisory pipeline завершён: APY feed → tournament → promotion decision → log.

### P2 — Инфраструктура и качество (Week 2 of Wave 10)

**MP-379** (P2, v4.70) | http_server: install launchd plist в ~/Library/LaunchAgents/  
com.spa.httpserver.plist существует в репо, но не установлен. Семейный инвесторский портал (`/api/public/fund/summary`, `/api/private/investors`) недоступен при перезагрузке Mac. Добавить USER ACTION checklist: `launchctl load ~/Library/LaunchAgents/com.spa.httpserver.plist`, верифицировать `curl localhost:8765/health`.

**MP-380** (P2, v4.70) | Chain concentration: диагностика + снижение ethereum alloc < 70%  
Текущий статус: `CHAIN_LIMIT_WARN: ethereum 73-85% > 70%`. Aave Arbitrum (Arbitrum chain) уже в ADAPTER_REGISTRY — но capital не аллоцирован туда, потому что у него нет истории APY в data/apy_history.json. Фикс: засеять apy_history для aave_arbitrum адаптера, запустить цикл с verbose, убедиться что аллокатор даёт ему вес.

**MP-381** (P2, v4.70) | E2E интеграционный тест полного цикла  
После MP-375+MP-377+MP-378: создать tests/test_e2e_cycle.py. Сценарий: mock APY feed (Morpho 6.5%, Pendle PT 8%, Aave Arb 4.6%) → StrategyAllocator → RiskPolicy gate → cycle_runner dry-run → GoLiveChecker. Assert: apy_today > 5%, risk_policy_approved=True, tournament_ranking.json written. Закрывает риск регрессии при интеграции новых компонентов.

### P3 — Долгосрочная ценность (Wave 10+)

**MP-382** (P3, v4.71) | Dashboard v3.1: Tournament tab с live данными  
index.html Tournament tab существует, но показывает статичные данные. После MP-377: читать tournament_ranking.json из GitHub raw → показывать live лидерборд S0-S10 с реальными метриками Sharpe/Calmar/APY. Ценность: первые инвесторы видят работающий tournament.

**MP-383** (P3, v4.71) | APY milestone tracker: daily log vs 5%/7%/10%/15% targets  
Создать spa_core/paper_trading/apy_tracker.py: читает equity_curve_daily.json, вычисляет 7d/30d rolling APY, сравнивает с milestones (5%/7%/10%/15%), логирует в data/apy_progress.json. Показывает estimated_date_to_10pct. Используется в ARCHITECT_REVIEW и daily_report.

---

## 6. Go-Live Blockers (2026-08-01)

### Текущий статус GoLiveChecker (6/6 чеков v1)

```json
{
  "ready": true,
  "checks": {
    "equity_curve_real": true,
    "trades_real": true,
    "status_real": true,
    "no_demo_data": true,
    "data_fresh_48h": true,
    "cycle_runner_exists": true
  }
}
```

Хорошая новость: базовый anti-demo gate пройден. Плохая: это только 6 из 26 планируемых проверок.

### Полный чеклист к 2026-08-01

| № | Критерий | Статус | Блокер/Действие |
|---|----------|--------|-----------------|
| 1 | equity_curve_real | ✅ PASS | — |
| 2 | trades_real | ✅ PASS | — |
| 3 | status_real | ✅ PASS | — |
| 4 | no_demo_data | ✅ PASS | — |
| 5 | data_fresh_48h | ✅ PASS | — |
| 6 | cycle_runner_exists | ✅ PASS | — |
| 7 | autopush работает | ❌ FAIL | USER: `bash mp009_fix_launchd.command` |
| 8 | Telegram daily alerts (не dry_run) | ❌ FAIL | CODE: MP-374 (30 мин) |
| 9 | gap_monitor 30 дней без пробелов | ⏳ 27/30 дней | Время + autopush P0 |
| 10 | APY > 5% (go-live threshold) | ❌ FAIL (3.2%) | CODE: MP-375 (интеграция адаптеров) |
| 11 | Min track days ≥ 30 | ⏳ 2/30 дней | Время (2026-07-10) |
| 12 | GoLiveChecker READY 7 дней подряд | ❌ | Зависит от п.7-11 |
| 13 | Owner manual review | ❌ | Зависит от п.12 |
| 14 | Gnosis Safe 2-of-3 активирован | ❌ | USER: setup Ledger+Trezor+cold |
| 15 | Kill-switch drill пройден | ❌ | После autopush + Telegram |

**Критический путь:** п.7 (autopush, 5 мин USER) → п.9 (ждать 27 дней) → п.12 (7 дней READY) = минимально 34 дня. При старте сегодня — go-live не ранее **2026-07-17**. Буфер для reviews и Gnosis Safe setup → **2026-08-01** реалистично.

### Самый опасный риск

**R1 (P=HIGH):** Gap в equity curve из-за неработающего autopush → 30-дневный счётчик сбрасывается → go-live переносится.  
**Фикс:** `bash mp009_fix_launchd.command` — 5 минут, сегодня.

**R2 (P=MEDIUM):** APY 3.2% к дате go-live → трек-рекорд не убедителен для инвесторов.  
**Фикс:** MP-375 (регистрация адаптеров) → ожидаемый APY ~5-6% за 1 день работы.

**R3 (P=MEDIUM):** chain concentration ethereum 73-85% > 70% → risk_policy_warnings не очищаются → может блокировать GoLiveChecker v2 Infrastructure чек.  
**Фикс:** MP-380 (Aave Arbitrum allocation activation).

---

## 7. Strategic Outlook: Что важно для Family Fund

### Честная временная шкала

```
2026-06-10  Реальный трек начат
2026-07-10  30 дней honest track (если нет gaps)
2026-07-17  GoLiveChecker READY 7 дней подряд (при APY > 5%)
2026-08-01  Target go-live (L1: $10K собственных)
2026-09-01  1 месяц live → первый monthly report
2026-12-01  6 месяцев live → Capital Ladder L2 ($50K)
2027-06-01  1 год live track record
2027-09-01  Family Fund Phase 0 открыт для первых участников
             (минимальный track: 1 год live + договір підписан)
```

### Минимальные требования перед первым внешним инвестором

1. **Трек:** 12+ месяцев live (не paper), APY > 7%, max drawdown < 5%
2. **Юридика:** Договір простого товариства подписан с юристом (не шаблон)
3. **Безопасность:** Gnosis Safe 2-of-3, hardware wallets, DR процедура протестирована
4. **Прозрачность:** публичный дашборд, monthly PDF reports, Telegram alerts
5. **Аудит:** external review стратегий (не смарт-контрактов — они позже)

**Главный принцип:** Track record — единственный актив фонда на ранней стадии. Каждый пропущенный день, каждый разрыв в данных, каждый демо-след подрывает доверие. Поэтому P0-блокеры (autopush, Telegram) важнее любых новых аналитических модулей.

---

## 8. Архитектурные решения Wave 10

### ADR-023 (предложение): APYAggregator как единственный источник APY в cycle_runner

`spa_core/adapters/apy_aggregator.py` создан в v4.68, но cycle_runner читает APY напрямую из orchestrator. Предложение: после MP-375 — все APY данные идут через APYAggregator (кэш TTL 300c, fallback к deFiLlama feed, single source of truth). Это упрощает тестирование (mock одного объекта вместо N адаптеров) и дает центральное место для APY sanity checks.

### Принцип интеграции v4.69

Правило: **no new adapters without ADAPTER_REGISTRY registration + E2E test**. Все адаптеры из v4.68 (morpho_steakhouse, pendle_pt) должны пройти: (1) регистрация в ADAPTER_REGISTRY, (2) засев APY в data/apy_history.json, (3) прогон полного цикла с --verbose, (4) проверка current_positions после цикла.

### Separation of concerns (строгое)

```
Read-only domain:      spa_core/adapters/  ← APY/TVL feed (NO execution)
Allocation domain:     spa_core/allocator/ ← target weights
Risk gate:             spa_core/risk/      ← approve/reject (NO LLM)
Tournament (advisory): spa_core/paper_trading/multi_strategy_runner.py
Promotion (advisory):  spa_core/paper_trading/promotion_engine.py
Execution domain:      spa_core/execution/ ← ЗАПРЕЩЕНО импортировать из выше
Family Fund:           spa_core/family_fund/ ← портал, отчётность
```

Никаких перекрёстных импортов. Никаких LLM-вызовов в risk/execution/monitoring.

---

## 9. Метрики Sprint Velocity

| Спринт | Done | Ключевые достижения |
|--------|------|---------------------|
| v4.65–v4.66 | 18+ | Analytics suite (30+ модулей), advanced ratios |
| v4.67 | 12 | Family Fund MVP, investor portal, legal docs, ADR-022 Gnosis Safe |
| v4.68 | 7 | Strategies S8/S9/S10, tournament, Pendle PT, CI, DR_v2 |
| **v4.69 (цель)** | **5** | MP-375–MP-378: интеграция, APY, tournament wiring |

Замедление с 12 → 7 → цель 5 объясняется: (а) задачи стали сложнее (интеграция сложнее создания), (б) правильно фокусироваться на качестве a не количестве. Velocity = done/sprint — неправильная метрика; правильная: **APY delta** и **GoLiveChecker score delta**.

---

## 10. Следующий шаг: TOP-5 для v4.69

| # | Задача | KANBAN ID | Время | P |
|---|--------|-----------|-------|---|
| 1 | USER: `bash mp009_fix_launchd.command` | MP-313 | 5 мин | P0 |
| 2 | ADAPTER_REGISTRY: Morpho Steakhouse + Pendle PT | **MP-389** | 3 ч | P1 |
| 3 | Cycle_runner: wire MultiStrategyRunner | **MP-385** | 4 ч | P1 |
| 4 | Cycle_runner: wire PromotionEngine | **MP-386** | 2 ч | P1 |
| 5 | Chain concentration fix (ethereum < 70%) | **MP-387** | 3 ч | P2 |

> Telegram daily report (GoLiveChecker audit MP-374/MP-384 вже виконано в done).  
> E2E тест після інтеграції: **MP-388**.

**Критерій успіху v4.69:** `apy_today > 5.0%` в `data/paper_trading_status.json` і `tournament_ranking.json` оновлюється щодня.

---

*Следующий архитектурный review: v4.80 — 2026-06-26 (после двух недель Wave 10)*  
*Обновлено: 2026-06-12 (MP-372 Wave 10 — Architect Review v4.68)*
