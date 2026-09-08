---
trackerStatus:
  type: inbox
title: "Производители устаревших чисел сайта: дата go-live из API, сверка NAV до цикла, протухшие артефакты, молчащие стражи сайта"
status: backlog
source: nimbalyst
created: 2026-09-08
---

## Что случилось и почему это важно

Аудит сайта 08.09 показал: часть устаревших чисел на earn-defi.com рождается НЕ на сайте, а у производителей данных. Сайт сегодня научили не верить им (коммит `82e20cda`: дата go-live судится по снимку, /status берёт блокеры из живых данных), но источники по-прежнему выдают неверное:
1. `spa_core/paper_trading/golive_checker.py:356-377` эмитит `target_date = anchor + 29 дней = 2026-07-21` — прошедшая дата — при 77/30 и пустых блокерах; через `scripts/generate_track_snapshot.py` она уезжает в `track_snapshot.go_live_target` и в `/api/v1/golive`.
2. `data/tier1_nav_proof.json` пишет `spa_core/backtesting/tier1/nav_proof.py` из `scripts/run_backtest_tier1.sh:39` под `com.spa.mass_tournament` в 06:30 — ДО дневного цикла 08:00. Поэтому «NAV (reconciled) $101,237 · ✓» на /dashboard сверяет вчерашнюю книгу, а рядом стоит equity $101,251 (замер 08.09: nav_proof 06:30 = 101,237.29 при current_equity 19:28 = 101,251.32). Тот же файл питает `/api/tier1/nav`, /proof-of-reserves, /track-record, чип на главной.
3. `/api/strategy-lab/promotion` отдаёт `generated_at 2026-06-25` (75 дней), его читают DashboardLive.jsx, /tournament, /structural-desk, /system.
4. Облачный `site_content_audit.yml` падает три недели подряд; локальный Site Custodian на Маке не загружен (intent=designed, последний отчёт 2026-08-19) — стражи сайта молчат.
5. `artifact_freshness.json` (07:15Z): 4 STALE — dfb_pools 215 ч, rates_desk_rate_surface 1785 ч, refusal_cost 1693 ч, rates_desk_capacity 1772 ч.

## Что чинить

1. `golive_checker`: когда `min_track_days_30` пройден и `blockers == []`, `target_date = None` и `go_live_state = "gate_passed_owner_decision_pending"`; снимок и API отдают null, а не дату в прошлом. Тест: 77/30 ⇒ target_date null; 12/30 ⇒ дата в будущем.
2. `nav_proof`: либо второй запуск после дневного цикла (порядок в `run_daily_paper_cycle.sh` или отдельный шаг 08:40), либо `ssot.py:217-218` обнуляет `nav_reconciliation_ok`, когда `nav_proof.reported_equity_usd != paper_trading_status.current_equity`. Тест: расхождение ⇒ `reconciliation_ok=None` и на дашборде «не сверено», а не «✓».
3. `strategy-lab/promotion`: найти производителя (grep promotion в spa_core/strategy_lab), назвать SLO и подключить к `artifact_freshness`.
4. Разобрать падение `site_content_audit.yml` (лог GitHub Actions) и решить судьбу локального Site Custodian (загрузить через деплой-гейт или снять с манифеста как designed).
5. По четырём STALE артефактам — производитель жив? Если мёртв — карточка на каждого или снятие с манифеста.

## Что не трогать

RiskPolicy, kill-switch, money-path цикла, `data/` руками. Приёмка `deployment_acceptance` до и после; `mass_tournament` и `daily_cycle` — по расписанию, не долгожители.

## Ссылки

Аудит: карточки `owner-decision-sait-ustarevshie-i-spornye-utverzhdeniya`, журнал `docs/journal/2026-W37.md` (08.09 «Три проверки»), коммит сайта `82e20cda` (`landing/src/lib/golive_label.js`).
