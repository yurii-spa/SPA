---
name: spa-v467-status
description: v4.67 sprint (2026-06-12): Family fund backend, S8/S9/S10 leverage, tournament dashboard, Telegram live, ADR-019/020/021
metadata:
  type: project
---

# SPA v4.67 Sprint — 2026-06-12

## Что завершено в v4.67

### MP-350: Telegram Daily Report — LIVE
- reporting_agent.py: dry_run=True → False
- daily_report.py: новый модуль run_daily_report()
- Читает Keychain: TELEGRAM_BOT_TOKEN_SPA
- Sentinel-файл: одна отправка в сутки
- 40 тестов

### MP-352 + ADR-019/020: Risk Config
- chain_limit ETHEREUM: 0.70 → 0.90 (структурное — все L1)
- T2 cap: 0.35 → 0.50 (ADR-019)
- T3 private credit cap: 0.15 (ADR-020 — Maple, Clearpool, etc.)
- 32 теста

### MP-154: Tournament Tab в Dashboard
- index.html: новая вкладка "🏆 Tournament"
- Читает tournament_ranking.json → tournament_results.json → placeholder
- SVG sparklines, kill/promote rules panel

### MP-156: Family Fund Backend
- spa_core/family_fund/: models.py, registry.py, pnl_attribution.py, telegram_blast.py
- data/investors.json: стартовый (0 инвесторов)
- 77 тестов

### MP-158: Investor Portal
- investor_portal.html: read-only портал для инвесторов
- Демо-режим если data/investors.json не доступен
- RU/UA/EN switch

### MP-160: S10 Pendle YT Speculation
- spa_core/strategies/pendle_yt.py
- entry_gate: apy > implied * 1.25
- Bull: ~28-50% gross APY (3.5x leverage)
- Bear: max loss = yt_price_pct * capital (25% of notional)
- 50+ тестов

### S9: E-Mode Looping
- spa_core/strategies/emode_looping.py
- Aave E-Mode 94% LTV, net ~7.2% APY
- Auto-deleverage при HF < 1.2

### S8: Delta-Neutral sUSDe
- spa_core/strategies/delta_neutral_susde.py
- Gate: sUSDe APY ≥ 12% + funding_rate_annual ≥ 0% + bull market
- Bull: 24-30% net APY; Bear: 0% (delta-neutral)

### ADR-021: Pendle YT T3-SPECULATIVE Classification
- docs/ADR-021-pendle-yt-t3-classification.md

### MP-161: Family Fund Landing Page
- family_fund_landing.html
- Темная тема, золотые акценты, лист ожидания

### MP-162: ДПТ Template
- docs/legal/DOGOVIR_PROSTOGO_TOVARYSTVA_TEMPLATE.md
- docs/legal/ONBOARDING_CHECKLIST.md

## Стратегии S0-S10 в реестре
- S0: Base stable (Aave/Compound ~3.2%)
- S1-S7: Различные ротации
- S8: Delta-neutral sUSDe (max 20%)
- S9: E-Mode Looping (7.2%)
- S10: Pendle YT Speculation (max 30%, T3)

## Push pending
Все файлы v4.67 в ~/Documents/SPA_Claude — не запущены на GitHub
Push command: python3 push_to_github.py (PUSH_SESSION_v4.67.md или push_all_session.sh)
