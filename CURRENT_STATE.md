# CURRENT_STATE
> Последнее обновление: 2026-06-12 sprint **v4.68** + MP-367 (обновляй вручную в конце каждого спринта)
> **ЧИТАЙ ЭТОТ ФАЙЛ ПЕРВЫМ** перед любой работой с проектом.

## Инфраструктура (launchd)

| Демон | Статус | Последний запуск | Комментарий |
|-------|--------|-----------------|-------------|
| com.spa.daily_cycle | ✅ РАБОТАЕТ | 2026-06-12T06:00:04Z | Ежедневный paper-trading цикл 08:00 |
| com.spa.autopush | ❌ НЕ УСТАНОВЛЕН | — | PYTHON_PATH-заглушка. Фикс: `bash mp009_fix_launchd.command` |
| com.spa.httpserver | ⚠️ ПРОВЕРИТЬ | — | HTTP дашборд localhost:8765; plist есть, статус launchd неизвестен |
| com.spa.cloudflared | ⚠️ ПРОВЕРИТЬ | — | Cloudflare tunnel; plist есть, статус launchd неизвестен |

> Для проверки реального статуса в Terminal: `launchctl list | grep com.spa`

## Push-метод

```
push_method: manual          # autopush не установлен
autopush_status: not_installed   # PYTHON_PATH-заглушка, нужен bash mp009_fix_launchd.command
push_last_success: unknown   # проверить: git log --oneline -5
push_command: python3 push_to_github.py --files <files> --message "<msg>"
```

**Правило для агента:** если autopush_status=not_installed → ПЕРВЫЙ шаг сессии: `bash mp009_fix_launchd.command` (не ждать, не спрашивать).

## Спринты

- Последний завершённый: **v4.68** (2026-06-12)
- Sprint log синхронизирован: ❌ (пропущены v4.31-v4.47, задача SYS-009)
- Задач в done: 139

## Paper Trading Track

- Старт: 2026-06-10
- Дней трека: 3 (из progress_tracker.json)
- Equity: $100,026.06 (из paper_trading_status.json)
- APY сегодня: 3.1969% (из paper_trading_status.json)
- Go-live решение: ~2026-08-01 (ADR-002; перенос если трек прерывается)

## Алерты

- Telegram: ✅ НАСТРОЕН (TELEGRAM_BOT_TOKEN_SPA / TELEGRAM_CHAT_ID_SPA в Keychain)
- Daily report: ❌ не активирован (dry_run). Задача MP-314.
- cycle_gap_monitor: ✅ в cycle_runner (MP-144)
- milestone_alert: ✅ в cycle_runner (MP-143)

## Активные блокеры (USER ACTION)

| Блокер | Задача | Действие | Критичность |
|--------|--------|----------|-------------|
| Запустить autopush fix | MP-313 | `bash mp009_fix_launchd.command` | P0 — без этого код не пушится автоматически |
| RPC ключи Alchemy/Infura | MP-017 | Добавить в Keychain | P1 — нужно для Pendle PT (+2-3% APY) |
| GitHub Pages | UA-004 | Settings → Pages → main/root | P1 — публичный дашборд |
| Workflow token | UA-006 | PAT с workflow scope | P2 |

---

## v4.68 Sprint Summary (MP-367, 2026-06-12)

### Новые стратегии (Tournament S0–S10)

| Файл | Стратегия | APY |
|------|-----------|-----|
| `spa_core/strategies/delta_neutral_susde.py` | S8 Delta-Neutral sUSDe | ~27.5% (bull) |
| `spa_core/strategies/emode_looping.py` | S9 E-Mode Looping | ~5.84% |
| `spa_core/strategies/pendle_yt.py` | S10 Pendle YT | 14–42% (T3-SPEC) |
| `spa_core/strategies/strategy_registry.py` | Реестр S0–S10 | — |
| `spa_core/paper_trading/tournament_evaluator.py` | Оценка Sharpe/Calmar/Ulcer/Rachev | — |
| `spa_core/paper_trading/multi_strategy_runner.py` | Оркестратор запуска стратегий | — |

### Новые/обновлённые адаптеры

| Файл | Статус | APY |
|------|--------|-----|
| `spa_core/adapters/morpho_steakhouse_adapter.py` | ✅ готов | ~6.5% |
| `spa_core/adapters/compound_v3.py` | ✅ T1 (обновлён) | ~4.8% |
| `spa_core/adapters/aave_v3_arbitrum.py` | 🔧 в разработке | ~4.6% |
| `spa_core/adapters/pendle_pt_rest.py` | 🔧 в разработке | 8–18% |

### Family Fund модуль

| Файл | Назначение |
|------|-----------|
| `spa_core/family_fund/registry.py` | Реестр участников |
| `spa_core/family_fund/pnl_attribution.py` | P&L attribution |
| `spa_core/family_fund/telegram_blast.py` | Telegram рассылка |
| `spa_core/family_fund/http_server.py` | stdlib TCP, port 8765 |

### Прочие новые файлы

| Файл | Назначение |
|------|-----------|
| `promotion_engine.py` | Автопродвижение (advisory, read-only) |
| `DR_PROCEDURE_v2.md` | Disaster Recovery v2 |
| `docs/legal/` | Договір інвестора, onboarding |
| `docs/adr/ADR-019.md` | T2 cap → 50% |
| `docs/adr/ADR-020.md` | T3 Private Credit категория |
| `docs/adr/ADR-021.md` | Pendle YT T3-SPEC (advisory only) |

### Dashboard v3.0 (index.html)

- Tournament tab: рейтинг стратегий S0–S10
- v3.0 hero section
- Risk Attribution раздел

---

## GoLive Status (2026-06-12)

| Метрика | Значение |
|---------|---------|
| Всего критериев | **26** |
| Прошло | **16/26** |
| Статус | **NOT READY** |
| Target go-live | **2026-08-01** |
| Блокер #1 | `trades_real: false` — нет реальных трейдов |
| Блокер #2 | autopush не установлен |
| Блокер #3 | gap_monitor < 30 дней |

---

## Adapter Status (2026-06-12)

| Протокол | Tier | APY | Статус |
|----------|------|-----|--------|
| Aave V3 Ethereum | T1 | ~3.5% | ✅ активен |
| Compound V3 | T1 | ~4.8% | ✅ активен |
| Morpho Steakhouse | T1 | ~6.5% | ✅ активен |
| Morpho Blue | T2 | — | ✅ активен |
| Yearn V3 | T2 | — | ✅ активен |
| Euler V2 | T2 | — | ✅ активен |
| Maple | T2 | — | ✅ активен |
| Aave V3 Arbitrum | T1 | ~4.6% | 🔧 в разработке |
| Pendle PT REST | T3-SPEC | 8–18% | 🔧 в разработке |
| Sky/sUSDS | watch | 0% | ⏸ ждёт GSM ≥ 48h |

---

## APY Target Progress

| Этап | APY | Статус |
|------|-----|--------|
| Текущий | ~3.2% | ✅ базовый уровень (Aave+Compound) |
| Шаг 1: Morpho Steakhouse (MP-355) | ~5.1% | +190 bps, готов к активации |
| Шаг 2: Aave Arbitrum (MP-356) | ~5.5% | +40 bps, в разработке |
| Шаг 3: Pendle PT REST (MP-354) | 7–9% | главный APY unlocker, нужны RPC-ключи |
| Цель (paper period) | **10–15%** | через Tournament + multi-strategy |

Ключевые шаги к цели 10–15%:
1. Активировать Morpho Steakhouse (2ч, P1) → +190 bps немедленно
2. RPC-ключи в Keychain (USER, 15 мин) → разблокирует Pendle PT
3. Pendle PT REST адаптер (MP-354, 3ч) → 7–9% weighted APY
4. S8 Delta-Neutral sUSDe (paper, advisory) → до ~27.5% APY потенциал

---

## Architect Review v4.67 (2026-06-12)

**Статус:** ISSUED — к исполнению  
**Документ:** `docs/ARCHITECT_REVIEW_v4.67.md`  
**Новых задач добавлено:** 12 (MP-353 — MP-364) + MP-160 (review) → backlog  
**Done count:** 139  

**Ключевые выводы review:**
- APY 3.2% → быстрые wins: Morpho Steakhouse (MP-355) + Aave Arbitrum (MP-356) = +290 bps → ~5.1% за 4 часа работы
- Главный yield unlocker: Pendle PT adapter REST (MP-354, нет блокеров) → потенциал 7-9% weighted APY
- Go-live критический путь: autopush (P0) + Telegram (P0) + trades_real диагностика (MP-353, P0)
- Family Fund MVP (investor portal): GitHub Pages + статичная HTML → можно начинать сейчас
- trades_real: false — требует диагностики в MP-353

**TOP-5 следующих действий:**
1. `bash mp009_fix_launchd.command` (MP-313, 5 мин, USER) — P0
2. Активировать Telegram daily report (MP-350, 30 мин) — P0
3. Диагностика trades_real: false (MP-353, 1 ч) — P0
4. Morpho Steakhouse vault switch (MP-355, 2 ч) — P1, немедленный +150 bps
5. Pendle PT REST adapter (MP-354, 3 ч) — P1, главный APY unlocker

---

## Тесты (2026-06-12)

| Набор | Файлов | Команда |
|-------|--------|---------|
| Unit (spa_core/tests/) | **~800+** | `python3 -m pytest spa_core/tests/ -v` |
| Integration (tests/) | 11 | `python3 -m pytest tests/ -v` |

---

## Системные долги (SYS-задачи)

Все 10 SYS-задач в KANBAN backlog. Следующие в очереди:
- SYS-003: Sprint close DoD (обновить RULES.md)
- SYS-004: Infra-first правило (обновить RULES.md)
- SYS-005: Anti-HALT протокол (обновить RULES.md)
- SYS-007: Startup protocol (обновить RULES.md)
- SYS-008: Delivery_status в KANBAN
- SYS-009: Восстановить sprint log v4.31-v4.47
