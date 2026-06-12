# Архитектурный Review v4.67 (2026-06-12)

> **Автор:** Principal DeFi Engineer / Product Architect  
> **Дата:** 2026-06-12  
> **Sprint:** v4.67  
> **Статус:** ISSUED — к исполнению

---

## 1. Текущее состояние

SPA работает 3 дня реального трека с 2026-06-10. Система технически здорова: `com.spa.daily_cycle` отрабатывает ежедневно в 08:00, цикл пишет данные атомарно, equity растёт ($100,026.06). Инфраструктура analytics-модулей исключительно зрелая: 130 задач в done, 121 unit-тест в `spa_core/tests/`, data integrity sentinel, tail risk, drawdown analytics, multi-strategy tournament (MP-153/154) — всё реализовано. Однако между аналитической глубиной и реальной yield-доходностью — пропасть: текущий APY 3.2% означает, что $100K генерирует $8.77/день. Целевой доходный профиль (7-10% APY для go-live, 9-11% для family fund) требует конкретных технических шагов, а не ещё одного аналитического модуля.

Критических структурных проблем три. Первая: `com.spa.autopush` не установлен — данные не попадают в GitHub автоматически, трек публично не верифицируется, что подрывает доверие к equity curve как главному активу проекта. Вторая: APY 3.2% — это нижняя граница T1 Aave mainnet; Morpho Blue Steakhouse vault и Aave Arbitrum дают 6-7% без смены риск-профиля, и переключение занимает 1-2 спринта. Третья: `GoLiveChecker trades_real: false` — go-live статус NOT READY не потому что система плохая, а потому что реальных трейдов (`is_demo: false`) ещё 0, что технически корректно на 3-й день трека, но требует понимания почему cycle_runner не генерирует rebalance-трейды.

---

## 2. Критический путь к Go-Live (2026-08-01)

**Что физически блокирует go-live прямо сейчас:**

GoLiveChecker требует 6 критериев. Из них 5 выполнятся автоматически по мере работы цикла. Единственный неочевидный: `trades_real` — нужно хотя бы один rebalance-трейд с `is_demo: false`. Если allocator видит нулевую дельту каждый день (позиции не меняются, потому что APY-спред между протоколами ниже порога ребалансирования), трейдов не будет. Это нужно диагностировать.

**Полный чеклист к 2026-08-01:**

| № | Что | Статус | Блокер |
|---|-----|--------|--------|
| 1 | `com.spa.autopush` работает | ❌ НЕ УСТАНОВЛЕН | USER: `bash mp009_fix_launchd.command` |
| 2 | Telegram daily report активирован | ❌ dry_run | CODE: снять dry_run в MP-350 |
| 3 | `trades_real: true` — есть реальный трейд | ❌ 0 трейдов | ДИАГНОСТИКА: почему нет ребалансов |
| 4 | `data_fresh_48h: true` | ⚠️ зависит от autopush | Фикс autopush |
| 5 | `gap_monitor` — 0 пробелов за 30 дней | ⚠️ нужно ещё 27 дней | Время + autopush |
| 6 | `cycle_runner_exists: true` | ✅ | — |
| 7 | GoLiveChecker READY 7 дней подряд | ❌ | Зависит от 1-6 |
| 8 | Owner manual review | ❌ | Зависит от 1-7 |

**Дата:** при устранении блокеров 1-3 на этой неделе, критерий 5 (30 дней без пробелов) истекает 2026-07-10. GoLiveChecker READY → 7 дней → 2026-07-17. Owner review + буфер → go-live **2026-07-17 — 2026-08-01**. Перенос возможен только при gap в equity curve.

---

## 3. Следующие 15 задач с приоритетом и обоснованием

### P0 — Блокеры (делать НЕМЕДЛЕННО, USER ACTION)

**MP-313 (existing): Починить autopush launchd** | P0 | ~5 мин | USER ACTION  
Why: без autopush данные не попадают в GitHub → трек публично не верифицируется → `data_fresh_48h` в GoLiveChecker может упасть → риск переноса go-live. Это самый дешёвый P0 в проекте.

**MP-350 (existing): Активировать Telegram daily report** | P0 | ~30 мин | CODE  
Why: сейчас алерты в dry_run — никаких реальных уведомлений нет. 30 честных дней трека без мониторинга = слепой полёт. При gap в cycle или drift в positions — узнаешь только при ручной проверке.

**MP-353 (NEW): Диагностика GoLiveChecker trades_real: false** | P0 | ~1 ч | CODE  
Why: go-live невозможен без хотя бы одного реального трейда. Нужно: (a) проверить пороги ребалансирования в cycle_runner, (b) убедиться что APY-дельта между протоколами превышает min_rebalance_threshold, (c) при необходимости временно снизить порог или добавить force-rebalance при первом запуске.

### P1 — Высокий приоритет (APY + инфраструктура)

**MP-354 (NEW): Pendle PT adapter via REST API** | P1 | ~3 ч | CODE  
Why: Pendle имеет публичный REST API `api.pendle.finance/core/v1/1/markets` — RPC не нужен. PT-sUSDe даёт 10-12% фиксированного APY. Это главный yield unlocker проекта: добавление 25-35% аллокации в Pendle PT поднимает weighted APY с 3.2% до 7-9%. Никаких блокеров нет прямо сейчас.

**MP-355 (NEW): Morpho Blue Steakhouse USDC vault — specific pool** | P1 | ~2 ч | CODE  
Why: текущий morpho_blue.py использует generic Morpho pool (~4.5% APY). Morpho Blue Steakhouse curator USDC vault даёт 6-7% на тех же рисках (curator risk, не protocol risk). Смена одной строки конфига + обновление pool_id даёт немедленный +150-200 bps без изменения risk profile. Самый высокий ROI усилий в проекте.

**MP-356 (NEW): Aave V3 Arbitrum adapter** | P1 | ~2 ч | CODE  
Why: Aave Arbitrum USDC даёт 4.8-6.5% vs mainnet 3.2-4.5%. Арбитрум — аудированный L2, те же смарт-контракты что mainnet. +1.5% APY на T1 anchor без новых рисков. DeFiLlama API уже покрывает Arbitrum pools (project=aave-v3, chain=Arbitrum). Нужен только новый adapter (~150 строк по образцу aave_v3.py).

**MP-364 (NEW): Proof of track anchor — устранить anchor_coverage warn** | P1 | ~30 мин | CODE  
Why: data_integrity sentinel показывает warn из-за отсутствия Merkle-якоря за 2026-06-10. Устраняется одной командой: `python3 -m spa_core.paper_trading.proof_of_track --run --date 2026-06-10`. Это единственный warn в текущем data integrity статусе.

**MP-017 (existing): RPC-ключи Alchemy/Infura в Keychain** | P1 | ~10 мин | USER ACTION  
Why: разблокирует on-chain чтение для Aave Arbitrum (альтернативный путь к DeFiLlama), Pendle Oracle, и будущие execution-домен операции. Без этого ключа Gnosis Safe мониторинг невозможен.

### P2 — Средний приоритет (стратегии + Family Fund)

**MP-357 (NEW): MultiStrategyRunner + TournamentEvaluator** | P2 | ~8 ч | CODE  
Why: инфраструктура multi-strategy tournament уже 60% готова (vportfolio.py, strategy_registry, comparator из MP-153). Нужно добавить MultiStrategyRunner (~200 LOC) и TournamentEvaluator (~150 LOC). Без этого невозможно сравнение стратегий и выбор лучшей для go-live.

**MP-358 (NEW): S1 стратегия (T1+T2 Balanced ~6-8% APY)** | P2 | ~3 ч | CODE  
Why: первая shadow-стратегия для сравнения с S0 baseline. Аллокация: Morpho Steakhouse 30% + Aave Arbitrum 20% + Yearn V3 15% + Sky sUSDS 15% + Cash 5%. Weighted APY estimate: 5.9%. Даст первые данные о том насколько реально 6-8% vs текущий 3.2%.

**MP-359 (NEW): FastAPI fund backend — /api/public/fund/summary** | P2 | ~4 ч | CODE  
Why: минимальный шаг к Family Fund investor portal. Один endpoint читает data/*.json и возвращает equity, APY, positions, track_record. Можно задеплоить на Railway ($5/мес). Это основа для investor portal — без бэкенда портал невозможен.

**MP-360 (NEW): Investor Portal MVP — статичная HTML страница** | P2 | ~3 ч | CODE  
Why: первый потенциальный инвестор должен видеть данные онлайн. Минимум: одна HTML страница на GitHub Pages (UA-004 нужен) с equity curve, APY, positions. Данные берутся из GitHub raw JSON напрямую — без бэкенда. Это самый быстрый путь к «показать трек инвестору».

**MP-361 (NEW): ADR-019 черновик + 14-day paper test (T2 cap 35%→50%)** | P2 | ~2 ч | CODE  
Why: текущий T2 total cap 35% не позволяет аллоцировать Pendle PT на 35%+ (Pendle = T2). ADR-019 поднимает лимит до 50% для Pendle-heavy стратегий. 14-дневный paper test в isolated vPortfolio (уже есть инфраструктура). Без этого ADR достичь 9-11% APY в рамках RiskPolicy невозможно.

### P3 — Инфраструктура + безопасность

**MP-362 (NEW): DR_PROCEDURE_v2.md — Disaster Recovery с fund scope** | P2 | ~2 ч | DOCS  
Why: FAMILY_FUND_ROADMAP описывает сценарий «macOS умерла» — текущий DR_PROCEDURE_v1.md не покрывает fund context (секреты, данные инвесторов, Gnosis Safe keys). Должен быть задокументирован до первого внешнего инвестора.

**MP-363 (NEW): GitHub Actions CI — automated test run при push** | P3 | ~2 ч | CODE  
Why: 130+ тестов запускаются только локально. Любой push может сломать тесты незаметно. CI занимает ~2 часа, блокирует молчаливые регрессии. Нужен workflow token (UA-006).

---

## 4. APY Gap Analysis: что реально добавит bps прямо сейчас

Текущий APY: **3.2%** (Aave V3 mainnet как T1 anchor, generic Morpho, Compound, Yearn, Euler, Maple)

### Быстрые wins (без ADR, без новых рисков):

| Действие | Ожидаемый прирост | Время на реализацию | Блокер |
|----------|-------------------|---------------------|--------|
| Morpho Steakhouse vault вместо generic Morpho | +150 bps | 2 ч (MP-355) | нет |
| Aave Arbitrum как second T1 anchor | +120 bps | 2 ч (MP-356) | RPC key (MP-017) или DeFiLlama |
| Compound → исключить (grade B снижает вес) | +20 bps | 0 (уже есть risk scoring) | нет |
| **Итого быстрые wins** | **+290 bps** | ~4 ч | — |
| **Новый APY после** | **~5.1%** | | |

### Среднесрочные wins (1-2 спринта):

| Действие | Ожидаемый прирост | Время | Блокер |
|----------|-------------------|-------|--------|
| Pendle PT adapter (S2 стратегия, 25% аллокация) | +200 bps (weighted) | 3+3 ч | нет (REST API) |
| Maple Syrup specific pool (8.5% vs текущий generic 7.5%) | +30 bps | 1 ч | нет |
| Sky/sUSDS (если GSM Pause Delay OK) | +50 bps (weighted 10%) | пассивно | on-chain проверка |
| **Итого среднесрочные** | **+280 bps** | ~7 ч | — |
| **Cumulative APY** | **~7.4%** | | |

### Долгосрочные wins (требуют ADR):

| Действие | Ожидаемый прирост | Условие |
|----------|-------------------|---------|
| ADR-019: T2 cap 35%→50% + Pendle heavy (35%) | +150 bps | 14-day paper test |
| ADR-020: T3 Private Credit category (Maple+Clearpool 20%) | +100 bps | audit check |
| S9 Aave E-Mode loop (если borrow rate < 6%) | +100 bps | Gnosis Safe live |
| **Cumulative APY (long-term)** | **~9-10%** | Q4 2026 |

**Честная оценка:** 7-8% APY достижимо за 2-3 недели работы (MP-354, MP-355, MP-356). 10%+ требует либо bull market (sUSDe APY > 12%) либо ADR-019 Pendle-heavy аллокации. Обещать инвестору 10%+ при текущем рыночном режиме (sUSDe ≈ 5%) — нечестно.

---

## 5. Family Fund Phase 0: минимальный путь к первому инвестору

### Timeline (реалистичный)

Семья/друзья как первые инвесторы — это **2028**, не 2026. Причина: ADR-002 требует 30 честных дней трека → go-live 2026-08-01 → затем 2 года live track record → только потом family fund по FAMILY_FUND_ROADMAP. Это не пессимизм — это защита от репутационного риска: инвестор зашедший с 2-месячным треком не защищён так, как инвестор с 2-летним.

### Минимальный MVP для «показать инвестору» (можно начинать СЕЙЧАС)

**Шаг 1: Публичный дашборд (UA-004 + MP-360)** — GitHub Pages с equity curve и APY. Инвестор может видеть трек в браузере. Стоимость: 0$. Время: 3-4 часа.

**Шаг 2: FastAPI /api/public/fund/summary (MP-359)** — JSON endpoint с метриками. Основа для автоматической отчётности. Стоимость: $5/мес (Railway). Время: 4-6 часов.

**Шаг 3: Юридический пакет Phase 0** — Договір простого товариства (ЦКУ ст.1132-1143) + Risk Disclosure + Term Sheet. Готовить с юристом. Стоимость: $200-500 (украинский юрист). Время: 2-4 недели.

**Шаг 4: Investor Portal MVP (MP-360)** — одна страница: equity, APY, positions, последний трейд. Только чтение, только для приглашённых. Стоимость: $0 (GitHub Pages).

**Чеклист перед первым реальным инвестором:**
- [ ] 30 дней честного live трека (`gap_monitor` чистый)
- [ ] GoLiveChecker READY 7 дней подряд
- [ ] Договір простого товариства подписан юристом
- [ ] Risk Disclosure подписан инвестором
- [ ] Investor Portal работает (equity, APY, positions)
- [ ] Daily Telegram alerts активны (не dry_run)
- [ ] Backup/DR протокол протестирован
- [ ] Gnosis Safe активирован (2-of-3: Ledger + Trezor + cold key)

**Когда первый реальный инвестор может зайти:** Q3 2028 по FAMILY_FUND_ROADMAP. Если Юрий хочет ускорить — legal risk в Phase 0 низкий при 1-2 близких людях и правильном договоре, но **трек record меньше 6 месяцев live** создаёт репутационный риск при любом drawdown.

---

## 6. Риски следующих 30 дней

### R1 (P=HIGH, Impact=HIGH): Gap в equity curve → перенос go-live

Autopush не работает → если macOS не в сети 24-36 часов → цикл пропущен → gap_monitor фиксирует пробел → 30-дневный отсчёт СБРАСЫВАЕТСЯ → go-live переносится. **Фикс: запустить `bash mp009_fix_launchd.command` сегодня.**

### R2 (P=MEDIUM, Impact=HIGH): APY 3.2% — демотивирующий трек-рекорд

За 30 дней при 3.2% APY equity вырастет на $263 ($100K × 3.2% / 12). Это не впечатляет ни инвестора, ни tournament-систему. Переключение на Morpho Steakhouse + Aave Arbitrum (суммарный эффект +290 bps) должно произойти до конца недели 1 трека, иначе трек-рекорд будет начат с низкой базы.

### R3 (P=MEDIUM, Impact=MEDIUM): trades_real: false вечно

Если cycle_runner никогда не генерирует rebalance-трейд (все протоколы попадают в «close enough» дельту), GoLiveChecker никогда не пройдёт `trades_real`. Диагностика обязательна (MP-353). Возможное решение: добавить scheduled rebalance раз в 7 дней вне зависимости от дельты.

### R4 (P=LOW, Impact=HIGH): PAT ротация

По инциденту 2026-06-10 PAT уже один раз утёк. Текущий PAT в Keychain. Нужно убедиться что TOKEN_ROTATION_RUNBOOK.md актуален и следующая ротация запланирована (стандартно: раз в 90 дней).

### R5 (P=LOW, Impact=MEDIUM): Молчаливая регрессия при добавлении новых адаптеров

Добавление Morpho Steakhouse, Aave Arbitrum, Pendle PT изменяет поведение allocator. Если не прогнать полный test suite после каждого спринта — возможна молчаливая регрессия в risk_policy_gate или cycle_runner. CI (MP-363) закрывает этот риск.

### R6 (P=LOW, Impact=LOW): sUSDe funding regime

Текущий sUSDe APY ~5% (bear/neutral). S8 и S10 стратегии (delta-neutral, YT speculation) требуют sUSDe APY ≥ 12%. Запускать их в бумажном трекинге нейтрально, но не закладывать на них как на основной APY-источник при текущем рынке.

---

## Приоритизированный список на следующий sprint (TOP-5)

1. **MP-313** (USER): `bash mp009_fix_launchd.command` — 5 минут, P0
2. **MP-350**: Снять dry_run с Telegram report — 30 минут, P0
3. **MP-353**: Диагностика trades_real: false — 1 час, P0
4. **MP-355**: Morpho Blue Steakhouse specific vault — 2 часа, P1, немедленный +150 bps APY
5. **MP-354**: Pendle PT adapter via REST API — 3 часа, P1, главный yield unlocker

---

*Следующий архитектурный review: v4.80 — 2026-06-19 (после первой недели трека)*  
*Обновлено: 2026-06-12*
