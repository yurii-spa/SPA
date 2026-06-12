# SPA Memory File
> Обновляй в конце каждой сессии. Источник истины: KANBAN.json + CURRENT_STATE.md
> Последнее обновление: 2026-06-12 (MP-372, Wave 10 Architect Review)

---

## Текущий спринт

| Поле | Значение |
|------|----------|
| Последний завершённый | **v4.68** (2026-06-12) |
| Следующий | **v4.69** (Wave 10) |
| Задач в done | ~174 (KANBAN.json) |
| Задач в backlog | 14 (включая 5 новых Wave 10) |

---

## Состояние системы (2026-06-12)

```
Equity:          $100,026.06
APY сегодня:     3.1969%
Дней трека:      3 (старт 2026-06-10)
GoLiveChecker:   6/6 checks pass (v1 anti-demo gate)
Gap monitor:     OK, 0 пробелов
Go-live target:  2026-08-01 (ADR-002)
```

**Критический блокер:** `com.spa.autopush` НЕ установлен → `bash mp009_fix_launchd.command`

---

## Wave 10 Summary (MP-372, 2026-06-12)

**Документ:** `docs/ARCHITECT_REVIEW_v4.68.md`

### Ключевые находки review

**Integration Gap (главная проблема):** новые компоненты v4.68 созданы как файлы, но НЕ подключены к cycle_runner.py. APY застрял на 3.2% несмотря на 6 спринтов работы над адаптерами.

| Компонент | Статус | Влияние |
|-----------|--------|---------|
| morpho_steakhouse_adapter.py | ✅ создан, ❌ не в ADAPTER_REGISTRY | APY не растёт |
| pendle_pt_adapter.py | ✅ создан, ❌ не в ADAPTER_REGISTRY | APY не растёт |
| aave_arbitrum (в реестре) | ✅ в ADAPTER_REGISTRY, ❌ нет аллокации | chain concentration warn |
| multi_strategy_runner.py | ✅ создан, ❌ не вызывается из cycle_runner | tournament не работает |
| promotion_engine.py | ✅ создан, ❌ не вызывается из cycle_runner | advisory pipeline не работает |
| com.spa.httpserver.plist | ✅ в репо, ❌ не установлен в LaunchAgents | портал не автостартует |

### Новые задачи Wave 10 (добавлены в KANBAN.json backlog)

| ID | Задача | P | Sprint |
|----|--------|---|--------|
| MP-385 | Cycle_runner: wire MultiStrategyRunner | P1 | v4.69 |
| MP-386 | Cycle_runner: wire PromotionEngine | P1 | v4.69 |
| MP-387 | Chain concentration: ethereum < 70% | P2 | v4.70 |
| MP-388 | E2E интеграционный тест полного цикла | P2 | v4.70 |
| MP-389 | ADAPTER_REGISTRY: Morpho Steakhouse + Pendle PT | P1 | v4.69 |

> Уже существовали в KANBAN: MP-376 (Spark adapter), MP-377 (Fluid adapter), MP-379 (http_server launchd), MP-382 (Dashboard v3.1), MP-383 (APY tracker), MP-384 (GoLiveChecker v2 extended)

### APY roadmap

```
Сейчас:      3.2%  (Aave+Compound+Yearn+Euler+Maple)
После MP-389: ~5-6% (+ Morpho Steakhouse 6.5% + Aave Arbitrum 4.6%)
После MP-385: ~6-7% (tournament выбирает лучшую стратегию)
После MP-387: ~7%  (ethereum chain concentration ниже 70%)
Target go-live: 7-10%
Target FF:      10-15%
```

---

## Предыдущие сессии

### Wave 9 / v4.67 (2026-06-12)

**Документ:** `docs/ARCHITECT_REVIEW_v4.67.md`

Done: MP-162 (ДПТ шаблон), MP-161 (Family Fund Landing Page), MP-158 (Investor Portal HTML), MP-156 (Family Fund Backend MVP), MP-369 (ADR-022 Gnosis Safe)

Ключевые выводы: APY 3.2% → нужны быстрые wins (Morpho Steakhouse, Aave Arbitrum); GoLiveChecker trades_real: false диагностирована (фиксирована в v4.68); autopush = P0 блокер.

### Sprint v4.68 (2026-06-12)

Done (7): MP-363 (CI), MP-361 (ADR-019), MP-364 (proof of track), MP-362 (DR_v2), MP-354 (Pendle PT adapter), MP-366 (PromotionEngine), MP-370 (push script)

Done (earlier in session): MP-373 (APYAggregator интеграция), MP-357 (MultiStrategyRunner), MP-358 (S1 strategy), MP-371 (Frontend новые адаптеры), MP-374 (GoLiveChecker audit), MP-375 (Spark/Fluid research), MP-378 (Sterling/Burke ratio), MP-380 (S2 Pendle PT + Morpho Heavy), MP-381 (S3 Aave Arbitrum L2)

Стратегии добавлены: S8 (delta_neutral_susde.py, ~27.5% bull), S9 (emode_looping.py, ~5.84%), S10 (pendle_yt.py, 14-42% T3-SPEC), S1 (s1_t1t2_balanced.py, target 6-8%)

Адаптеры: morpho_steakhouse_adapter.py (6.5%), pendle_pt_adapter.py (8-18%), aave_arbitrum_adapter.py (4.6%), compound_v3_adapter.py (4.8%), apy_aggregator.py

Family Fund: http_server.py (stdlib TCP port 8765), promotion_engine.py в spa_core/paper_trading/

---

## Архитектурные решения (ADR)

| ADR | Суть | Статус |
|-----|------|--------|
| ADR-002 | Go-live transfer rule: 30 дней + 7 READY + manual review | ACTIVE |
| ADR-019 | T2 cap 35%→50% для Pendle-heavy аллокаций | PAPER TEST (14 дней) |
| ADR-020 | T3 Private Credit category (Maple+Clearpool) | DRAFT |
| ADR-021 | Pendle YT = T3-SPEC, advisory only, no auto-alloc | ACTIVE |
| ADR-022 | Gnosis Safe 2-of-3 multisig | PLAN (pre-live) |

---

## Инфраструктура (launchd)

| Демон | Статус | Действие |
|-------|--------|----------|
| com.spa.daily_cycle | ✅ РАБОТАЕТ | 08:00 ежедневно |
| com.spa.autopush | ❌ НЕ УСТАНОВЛЕН | USER: `bash mp009_fix_launchd.command` |
| com.spa.httpserver | ⚠️ plist в репо, не в LaunchAgents | USER ACTION: MP-379 |
| com.spa.cloudflared | ⚠️ plist в репо, статус неизвестен | проверить launchctl |

---

## Ключевые файлы

| Путь | Что |
|------|-----|
| `data/paper_trading_status.json` | APY, equity, positions, risk_policy |
| `data/golive_status.json` | 6 anti-demo checks (all pass) |
| `data/gap_monitor.json` | Непрерывность трека (ok, 0 пробелов) |
| `data/current_positions.json` | Текущие позиции |
| `data/tournament_ranking.json` | Tournament результаты (обновляется после MP-385) |
| `data/promotion_report.json` | Advisory promotions (после MP-386) |
| `spa_core/adapters/__init__.py` | ADAPTER_REGISTRY — ключевой файл APY |
| `spa_core/paper_trading/cycle_runner.py` | Боевой цикл |
| `docs/ARCHITECT_REVIEW_v4.68.md` | Текущий стратегический review |
| `docs/adr/ADR-002-golive-transfer-rule.md` | Go-live правила |

---

## SECRETS POLICY (строго)

- **НИКОГДА** не писать токены/ключи в файлы
- PAT в macOS Keychain: `security find-generic-password -s GITHUB_PAT_SPA -w`
- Telegram tokens в Keychain: TELEGRAM_BOT_TOKEN_SPA, TELEGRAM_CHAT_ID_SPA
- Ротация PAT каждые 90 дней → `bash setup_pat.sh`

---

## Следующий архитектурный review

**v4.80** — 2026-06-26 (после двух недель Wave 10)  
Критерии: `apy_today > 5.0%`, `tournament_ranking.json` обновляется ежедневно, ethereum chain < 70%.
