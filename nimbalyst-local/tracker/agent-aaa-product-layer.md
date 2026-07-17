---
trackerStatus:
  type: agent-task
title: 🅰🅰🅰 Продуктовый слой агентов (супер-студия)
status: in-progress
source: session-2026-07-16
created: 2026-07-16
---

AAA: активировать+вылизать продуктовый слой агентов (архитектор+CMO+16 аналитиков, уже спроектированы в docs/08,10). Супер-студия: реально трудится, с умом. Разбор — отдельно с владельцем.

## Прогресс 2026-07-16/17
- **Шаг 2 (harness) — DONE:** `spa_core/investment_os/harness.py` (база аналитиков, 16 тестов). Genuinely new.
- **CMO-слой — обнаружено, что прошлая сессия его УЖЕ построила на origin** (honesty_gate/draft_store/
  template_rewriter/pipeline + router approve/reject + server.py). Скоуп-субагент пропустил (сканил локально).
- **Шаг 1/3 клоббер + фикс:** мой дубль honesty_gate сломал template_rewriter → восстановил prior gate;
  `editorial_agent` переписан в тонкий ЖИВОЙ RUNNER (делегирует в prior pipeline). Задеплоил
  `com.spa.cmo_editorial` через gate (advisory, draft-only, НИКОГДА не публикует — flow B owner-gate). 116 тестов.
- **Дальше (Phase 2):** аналитики на harness (Stablecoin Yield → Reporting → Red Team → …), по одному, ≤3 деплой.
  Публикация CMO-драфтов (Шаг 6) и allocation-proposals (Chief Investment) — HARD owner-gate.

## Phase 2 ЗАВЕРШЕНА 2026-07-17
Полный analyst-набор LIVE: harness + CMO editorial + 6 аналитиков (stablecoin_yield/market_regime/reporting/
red_team/liquidity/chief_investment=Head of Product синтез) + `/api/investment-os` (6 эндпоинтов). Реестр
65/0, reboot-safe. Chief Investment: RECOMMENDS only, owner_gate — allocation-решения за владельцем. Advisory,
капитал не двигают. ~50 тестов. Остаток: доп. аналитики docs/08 (BTC/ETH/Risk/News/Quant) + owner-gate публикация.
