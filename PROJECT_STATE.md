# PROJECT_STATE.md — Актуальное состояние проекта SPA
> **Шаблон:** заполняется в конце каждого спринта агентом
> **Источник истины:** KANBAN.json (этот файл — его читаемая копия)
> **Последнее обновление:** 2026-06-13 (аудит governance)

---

## ⚡ БЫСТРЫЙ СТАТУС

| Поле | Значение |
|------|----------|
| Текущий спринт | **v6.80** |
| Done count | **553** задач |
| Paper track start | 2026-06-10 |
| Дней трека | ~3 (цель: 30 к 2026-07-10) |
| Go-live target | **2026-08-01** (ADR-002) |
| GoLiveChecker | **16/26** pass (NOT READY) |
| Equity (last cycle) | ~$100,026 USDC (виртуальная) |
| Лучшая стратегия | S7 Pendle YT+PT (~10.115% APY) |

---

## 🏗️ ИНФРАСТРУКТУРА

| Демон | Статус | Комментарий |
|-------|--------|-------------|
| com.spa.daily_cycle | ✅ РАБОТАЕТ | Ежедневно 08:00, cycle_runner.py |
| com.spa.autopush | ❌ НЕ УСТАНОВЛЕН | **USER ACTION P0:** `bash mp009_fix_launchd.command` |
| com.spa.httpserver | ⚠️ ПРОВЕРИТЬ | Портал 8765; проверить launchctl list |
| com.spa.cloudflared | ⚠️ ПРОВЕРИТЬ | Туннель; проверить launchctl list |

```bash
# Проверка всех демонов:
launchctl list | grep com.spa
```

---

## 📦 PUSH-СТАТУС

```
Push-метод: РУЧНОЙ (autopush не установлен)
Последний push-скрипт создан: scripts/push_v680.sh
Последний успешный пуш в GitHub: НЕИЗВЕСТНО (проверить .push_log)

Для синхронизации GitHub:
  bash ~/Documents/SPA_Claude/scripts/run_all_pushes.sh
```

**Pending pushes (скрипты к запуску):**
- Проверить: `cat scripts/.push_log` (что уже отправлено)
- Отправить всё: `bash ~/Documents/SPA_Claude/scripts/run_all_pushes.sh`

---

## 🎯 АКТИВНЫЕ ЗАДАЧИ (backlog)

| ID | Название | Приоритет | USER ACTION? |
|----|----------|-----------|--------------|
| MP-313 | Fix autopush launchd | **P0** | ✅ ДА |
| MP-017 | RPC-ключи Alchemy/Infura | P1 | ✅ ДА |
| UA-004 | GitHub Pages включить | P1 | ✅ ДА |
| UA-006 | Workflow-scope GitHub token | P2 | ✅ ДА |
| MP-379 | http_server Family Fund launchd | P2 | Нет |

---

## ⚠️ АКТИВНЫЕ БЛОКЕРЫ

| # | Блокер | Задача | Что нужно от USER | Критичность |
|---|--------|--------|-------------------|-------------|
| 1 | autopush не работает | MP-313 | `bash mp009_fix_launchd.command` | P0 |
| 2 | GitHub stale (пуш-долг) | — | `bash run_all_pushes.sh` | P1 |
| 3 | RPC ключи (Pendle PT APY) | MP-017 | Добавить в Keychain | P1 |
| 4 | GitHub Pages | UA-004 | Settings → Pages → main | P1 |

---

## 📈 PAPER TRADING

```
Equity curve: data/equity_curve_daily.json
Positions: data/current_positions.json
Trades: data/trades.json (ring-buffer 500)
Gap monitor: data/gap_monitor.json

Tournament (S0–S13):
  Лидер: S7 Pendle YT+PT (~10.115% APY)
  Статус: Advisory mode, auto_promote_enabled=false до 2026-07-12

GoLive status: data/golive_status.json
  Проверить: python3 -m spa_core.paper_trading.golive_checker
```

---

## 🔐 SECURITY

```
PAT: macOS Keychain → service name "GITHUB_PAT_SPA"
  Проверить: security find-generic-password -s GITHUB_PAT_SPA -w | wc -c
  Ротация: docs/TOKEN_ROTATION_RUNBOOK.md

Telegram tokens:
  TELEGRAM_BOT_TOKEN_SPA, TELEGRAM_CHAT_ID_SPA → Keychain
  Статус: настроен, dry_run=True (MP-314)

ИЗВЕСТНО: ~/.github_pat содержит "INVALID_PLACEHOLDER" — не использовать
```

---

## 📊 КЛЮЧЕВЫЕ DATA-ФАЙЛЫ

| Файл | Что | Последнее обновление |
|------|-----|---------------------|
| data/golive_status.json | 26 GoLive критериев | При каждом цикле |
| data/gap_monitor.json | Непрерывность трека | При каждом цикле |
| data/equity_curve_daily.json | Дневная equity (365d ring) | При каждом цикле |
| data/current_positions.json | Позиции | При каждом цикле |
| data/trades.json | Трейды (500 ring) | При rebalance |
| data/risk_policy_blocks.json | Блокировки RiskPolicy (100 ring) | При блокировке |
| data/tournament_results.json | Sharpe/Calmar по S0-S13 | При цикле |
| data/health_report.json | CycleHealthMonitor | Daily |

---

## 🗓️ СЛЕДУЮЩИЕ MILESTONE

| Дата | Событие |
|------|---------|
| 2026-07-10 | 30 дней непрерывного трека (минимум для ADR-002) |
| 2026-07-12 | Est. S7 promotion (ADR-023: 14d + Sharpe ≥0.80) |
| 2026-07-15 | Manual review Owner (ADR-002 pre-requisite) |
| 2026-08-01 | Go-live target (ADR-002: READY 7+ days + 30d track) |

---

## 📝 ИСТОРИЯ ПОСЛЕДНИХ СПРИНТОВ

| Sprint | Дата | Что сделано |
|--------|------|-------------|
| v4.88 | 2026-06-12 | EmergencyBreakers, CycleHealthMonitor, PositionTracker, ADR-030/031 |
| v4.87 | 2026-06-12 | ADR-029 Strategy Promotion, auto_promoter.py, APY Consensus dashboard |
| v6.75 | 2026-06-13 | (по sprint_log KANBAN) |
| v6.80 | 2026-06-13 | MP-883 LeverageSafetyMonitor, MP-884 AuditCoverageScorer (196 тестов) |

---

## 🔧 КАК ОБНОВЛЯТЬ ЭТОТ ФАЙЛ

В конце каждого спринта агент обновляет:
1. "Текущий спринт" → новый номер
2. "Done count" → из KANBAN.json done_count
3. "Pending pushes" → добавить новый push_vNNN.sh
4. "История последних спринтов" → добавить строку
5. Блокеры → убрать решённые, добавить новые

---

*Этот файл заменяет MEMORY.md (устарел) как оперативный статус проекта.*
*Источник: docs/governance/PROJECT_STATE.md v1.0 (2026-06-13)*
