#!/usr/bin/env bash
# install_all_agents.sh — Установка ВСЕХ критических SPA LaunchAgents
# v1365 (2026-06-27) — STABLE-AGENT STANDARD: every plist this installs now uses
#   the /bin/bash wrapper (scripts/agent_<name>.sh -> agent_template.sh) and
#   /tmp/spa_<name>.launchd.{out,err} log paths (NEVER ~/Documents — TCC blocks
#   launchd writes there → exit 78). The plists referenced below were migrated to
#   that standard, so a clean reinstall is exit-78-proof. Reconciled 3 missing
#   agents (digest_daily, digest_weekly, telegram_bot); retired duplicate
#   bot_commands (same module as telegram_bot → 409). See CLAUDE.md rule #11.
# v1364 (2026-06-25) — SRE audit: added 18 loaded-but-uninstalled agents
#   (apiserver/httpserver/bot_commands/dashboard_watcher, hy_cycle/lp_cycle,
#    portfolio/peg/red_flag/governance/base_gas/sky/bts monitors,
#    analytics_tier_b/c, checkpoint-7day, weekly_backup) → reboot-survivable.
# v1362 (2026-06-22) — полный список агентов, формат [OK]/[SKIP]/[FAIL]
#
# Запуск: bash ~/Documents/SPA_Claude/scripts/install_all_agents.sh
#
# Агенты делятся на две группы:
#   CRITICAL  — устанавливаются всегда, ошибка = сбой установки
#   MONITORING — устанавливаются если plist существует, иначе [SKIP]

set -uo pipefail  # -e убрано намеренно: каждый агент обрабатывается независимо

LAUNCHD_DIR="$HOME/Library/LaunchAgents"
REPO="/Users/yuriikulieshov/Documents/SPA_Claude"

# Счётчики и лог результатов
declare -a RESULTS=()
OK_COUNT=0
SKIP_COUNT=0
FAIL_COUNT=0

mkdir -p "$LAUNCHD_DIR"

# ---------------------------------------------------------------------------
# install_agent <src_plist> <label> [optional]
#   optional=1 → SKIP если файл не найден (вместо FAIL)
# ---------------------------------------------------------------------------
install_agent() {
    local src="$1"
    local label="$2"
    local optional="${3:-0}"
    local dst="$LAUNCHD_DIR/${label}.plist"

    # Файл не найден
    if [[ ! -f "$src" ]]; then
        if [[ "$optional" == "1" ]]; then
            RESULTS+=("[SKIP] $label — plist not found: $src")
            (( SKIP_COUNT++ )) || true
        else
            RESULTS+=("[FAIL] $label — plist not found (CRITICAL): $src")
            (( FAIL_COUNT++ )) || true
        fi
        return
    fi

    # Unload (игнорируем ошибки — агент мог быть не загружен)
    launchctl unload "$dst" 2>/dev/null || true

    # Копируем plist
    if ! cp "$src" "$dst" 2>/tmp/_spa_install_err.tmp; then
        local err
        err=$(cat /tmp/_spa_install_err.tmp 2>/dev/null)
        RESULTS+=("[FAIL] $label — cp failed: $err")
        (( FAIL_COUNT++ )) || true
        return
    fi

    # Загружаем
    local load_err
    if ! load_err=$(launchctl load "$dst" 2>&1); then
        RESULTS+=("[FAIL] $label — load error: $load_err")
        (( FAIL_COUNT++ )) || true
        return
    fi

    # Небольшая пауза чтобы launchd успел обновить список
    sleep 0.3

    # Проверяем что агент появился в launchctl list
    local entry
    entry=$(launchctl list 2>/dev/null | grep -F "$label" || true)
    if [[ -n "$entry" ]]; then
        local pid
        pid=$(echo "$entry" | awk '{print $1}')
        if [[ "$pid" == "-" ]]; then
            RESULTS+=("[OK] $label — loaded (no PID, waiting for trigger)")
        else
            RESULTS+=("[OK] $label — loaded (PID=$pid)")
        fi
        (( OK_COUNT++ )) || true
    else
        # Загрузился, но ещё не виден в list (редко, но возможно при calendar trigger)
        RESULTS+=("[OK] $label — loaded (not yet in list — calendar/interval trigger normal)")
        (( OK_COUNT++ )) || true
    fi
}

echo "=============================================="
echo " SPA LaunchAgents Installer v1364 (2026-06-25)"
echo "=============================================="
echo ""
echo "REPO:       $REPO"
echo "LAUNCHD:    $LAUNCHD_DIR"
echo ""

# ===========================================================================
# ГРУППА 1: КРИТИЧЕСКИЕ (должны работать всегда)
# ===========================================================================
echo "--- CRITICAL agents ---"

# 1. Autopush — каждые 90 мин, пушит data-файлы в GitHub
install_agent \
    "$REPO/scripts/com.spa.autopush.plist" \
    "com.spa.autopush"

# 2. Rules Watchdog — Policy Enforcer каждые 5 мин (plist в launchd/)
install_agent \
    "$REPO/launchd/com.spa.rules_watchdog.plist" \
    "com.spa.rules_watchdog"

# 3. Cycle Gap Monitor — детект пропущенных циклов каждые 5 мин
install_agent \
    "$REPO/scripts/com.spa.cycle_gap_monitor.plist" \
    "com.spa.cycle_gap_monitor"

# 4. Daily Cycle — daily paper trading 08:00
install_agent \
    "$REPO/scripts/com.spa.daily_cycle.plist" \
    "com.spa.daily_cycle"

# 5. System Health Morning — health check утром 08:00
install_agent \
    "$REPO/scripts/com.spa.system_health_morning.plist" \
    "com.spa.system_health_morning"

# 6. System Health Evening — health check вечером 20:00
install_agent \
    "$REPO/scripts/com.spa.system_health_evening.plist" \
    "com.spa.system_health_evening"

# 7. Agent Health — мониторинг всех агентов (hourly)
install_agent \
    "$REPO/scripts/com.spa.agent_health.plist" \
    "com.spa.agent_health"

# 8. Tournament Engine — daily runner из launchd/ (09:00)
install_agent \
    "$REPO/launchd/com.spa.tournament_engine.plist" \
    "com.spa.tournament_engine"

echo ""
echo "--- MONITORING agents (optional — skip if plist missing) ---"

# 9. Cycle Health — мониторинг cycle_runner каждые 5 мин
install_agent \
    "$REPO/scripts/com.spa.cycle_health.plist" \
    "com.spa.cycle_health" \
    "1"

# 10. Uptime Monitor — проверка launchd-сервисов и HTTP-сервера каждые 5 мин
install_agent \
    "$REPO/scripts/com.spa.uptime_monitor.plist" \
    "com.spa.uptime_monitor" \
    "1"

# 11. Cloudflared — CF Tunnel (KeepAlive, если файл есть)
install_agent \
    "$REPO/scripts/com.spa.cloudflared.plist" \
    "com.spa.cloudflared" \
    "1"

# 12. (RETIRED 2026-06-24) Morning Digest — was redundant with com.spa.telegram_daily
#     (3 overlapping daily reports). Consolidated to ONE daily report. Do not reinstall.

# 13. System Briefing — auto-updates SYSTEM_BRIEFING.md every 30 min
install_agent \
    "$REPO/scripts/com.spa.system_briefing.plist" \
    "com.spa.system_briefing" \
    "1"

echo ""
echo "--- SELF-HEALING & SAFETY agents (active recovery, not just alerts) ---"

# Self-Heal — revives dead/unloaded agents + recovers missed cycle (every 5 min)
install_agent \
    "$REPO/scripts/com.spa.self_heal.plist" \
    "com.spa.self_heal"

# Threat Reactor — intraday kill-switch on CRITICAL threats to held protocols (every 5 min)
install_agent \
    "$REPO/scripts/com.spa.threat_reactor.plist" \
    "com.spa.threat_reactor"

# Watchdog — guardian-of-guardians: revives self_heal + threat_reactor if dead/stale (every 10 min)
install_agent \
    "$REPO/scripts/com.spa.watchdog.plist" \
    "com.spa.watchdog"

echo ""
echo "--- SERVICES & REPORTING agents ---"

# 14. Family Fund API — uvicorn :8766 (investor cabinet backend)
install_agent \
    "$REPO/scripts/com.spa.familyfund.plist" \
    "com.spa.familyfund" \
    "1"

# 15-16. (RETIRED 2026-06-27 — Telegram rebuild) com.spa.telegram_daily and
#     com.spa.telegram_weekly ran the digest BUILDERS (daily/weekly_telegram_report
#     --run) directly → DUPLICATE daily/weekly sends. The daily/weekly Telegram
#     digest is now owned SOLELY by com.spa.digest_daily / com.spa.digest_weekly
#     (installed at 17b/17c below), which collapse the former four+ senders into
#     ONE message each. Do NOT reinstall telegram_daily/telegram_weekly — they are
#     in RETIRED_LABELS (agent_health/self_heal won't flag or revive them).

# 17. Telegram Milestone Alerts — hourly (DISTINCT from the daily digest: one-time
#     celebratory crossings via push_policy; NOT retired).
install_agent \
    "$REPO/scripts/com.spa.telegram_milestone.plist" \
    "com.spa.telegram_milestone" \
    "1"

# 17b. Telegram digest (DAILY) — THE sole daily-alert owner (~08:10 UTC). Writes
#      data/telegram_alert_state.json:daily_summary on a successful send, which is
#      the go-live telegram_alert_today criterion. Was MISSING from installer
#      (audit 2026-06-27); replaces the retired com.spa.telegram_daily.
install_agent \
    "$REPO/scripts/com.spa.digest_daily.plist" \
    "com.spa.digest_daily" \
    "1"

# 17c. Telegram digest (WEEKLY) — THE sole weekly-report owner (Sun 10:00). Was
#      MISSING from installer (audit 2026-06-27); replaces com.spa.telegram_weekly.
install_agent \
    "$REPO/scripts/com.spa.digest_weekly.plist" \
    "com.spa.digest_weekly" \
    "1"

# 18. Dashboard static server — :8767 (moved off :8766 to avoid familyfund conflict)
install_agent \
    "$REPO/scripts/com.spa.dashboard.plist" \
    "com.spa.dashboard" \
    "1"

# 19. Mass Tournament backtest — daily 06:30 local, BEFORE tournament_engine, so the
#     ranking uses a fresh backtest of all strategies (was manual + days-stale).
install_agent \
    "$REPO/scripts/com.spa.mass_tournament.plist" \
    "com.spa.mass_tournament" \
    "1"

# 20. Tier-1 weekly digest — eligible strategies + packages + diversification → Telegram
install_agent \
    "$REPO/scripts/com.spa.tier1_digest.plist" \
    "com.spa.tier1_digest" \
    "1"

# 21. Tier-1 governance — daily 07:15 UTC, refreshes SSOT/policy/readiness/DR report JSONs
install_agent \
    "$REPO/scripts/com.spa.tier1_governance.plist" \
    "com.spa.tier1_governance" \
    "1"

# 22. Strategy-Lab live paper service — hourly single-tick; paper-trades ALL lab strategies
#     on live data into a growing time-series; restart-survival (state restored, not zeroed).
install_agent \
    "$REPO/scripts/com.spa.strategy_lab_paper.plist" \
    "com.spa.strategy_lab_paper" \
    "1"

# 22b. Rates-Desk Refusal Engine — daily 05:45 local (before daily_cycle); scores every tracked
#      underlying from LIVE data with the §8-validated tail-risk scorer → data/refusal_status.json.
#      ADVISORY ONLY: never trades / never touches the go-live track.
install_agent \
    "$REPO/scripts/com.spa.refusal.plist" \
    "com.spa.refusal" \
    "1"

# 22b2. RWA Collateral Safety Board — daily 05:50 local (before daily_cycle); measures the whole
#       tokenized-RWA collateral universe from LIVE DeFiLlama data with the §SPA-RRB-validated
#       LiquidationNAVEngine → per-asset LIQUID/THIN/REDEMPTION_ONLY/UNSAFE verdict + marketing-vs-
#       LiqNAV gap % → data/rwa_safety_board.json. ADVISORY / RESEARCH ONLY: never lends / trades /
#       touches the go-live track.
install_agent \
    "$REPO/scripts/com.spa.rwa_safety_board.plist" \
    "com.spa.rwa_safety_board" \
    "1"

# 22c. Rates-Desk live paper service — hourly single-tick; paper-trades the VALIDATED FixedCarry
#      sleeve (thesis-#1 GO) on the LIVE rate-surface into a growing forward carry track + proof
#      chain; restart-survival (book restored, not zeroed), idempotent per UTC day, fail-CLOSED.
#      ADVISORY ONLY: simulates carry, moves no live capital, never touches the go-live track.
install_agent \
    "$REPO/scripts/com.spa.rates_desk_paper.plist" \
    "com.spa.rates_desk_paper" \
    "1"

# 22c2. Realized-at-size standing measurement (Edge-at-Scale month-program, Lane B) — daily;
#       re-runs the realized-at-size KILLER TEST on the freshest books and appends/refreshes ONE
#       row in the growing verdict track (data/rates_desk/paper/realized_at_size_track.jsonl) so the
#       "does the edge survive at scale" verdict can be watched maturing forward. ADVISORY ONLY:
#       moves no capital, never touches the go-live track, never imports execution/. (Was loaded
#       but had no persistent plist here → would be lost on reboot = zombie-class; now persistent.)
install_agent \
    "$REPO/scripts/com.spa.realized_at_size.plist" \
    "com.spa.realized_at_size" \
    "1"

# 22d. Red-team rotation (WS-8 Cutover-Bulletproof) — daily 09:30 UTC; probes a DIFFERENT attack
#      surface each UTC day, hash-anchors the verdict, writes data/redteam_status.json. Read-only
#      against live data/ (scenarios use tmp sandboxes; the runner snapshots live files before/after
#      and FAILS CLOSED if any changed). On-standard (bash-wrapper + /tmp logs), passed the deploy
#      gate (CHECK_ONLY: exit 0, log written, canonical track untouched). ADVISORY.
install_agent \
    "$REPO/scripts/com.spa.redteam_rotation.plist" \
    "com.spa.redteam_rotation" \
    "1"

echo ""
echo "--- LIVE SERVICES (KeepAlive — API / tunnels / dashboards) ---"

# 23. API server — uvicorn :8765 (api.earn-defi.com via cloudflared); was NOT in
#     installer before → would silently vanish after a clean reinstall/reboot.
install_agent \
    "$REPO/scripts/com.spa.apiserver.plist" \
    "com.spa.apiserver" \
    "1"

# 24. (DISABLED 2026-06-27) HTTP server — stdlib family-fund server binds :8765, the
#     SAME port apiserver (uvicorn) owns → crash-loops on EADDRINUSE (exit 1). It was
#     NEVER actually running its module (a stale `http.server` orphan masked this).
#     Do NOT install until the port conflict is resolved (give httpserver its own port,
#     or retire it in favour of apiserver). Its plist is on-standard for when fixed.
# install_agent \
#     "$REPO/scripts/com.spa.httpserver.plist" \
#     "com.spa.httpserver" \
#     "1"

# 25. Telegram bot — the live interactive command poller (long-running, KeepAlive).
#     CANONICAL bot. plist in launchd/. Was MISSING from installer (audit 2026-06-27).
install_agent \
    "$REPO/launchd/com.spa.telegram_bot.plist" \
    "com.spa.telegram_bot" \
    "1"

# 25b. (RETIRED 2026-06-27) bot_commands ran the SAME module (spa_core.telegram.bot)
#      as telegram_bot above → two pollers = Telegram getUpdates 409 conflict. Only
#      ONE poller may run; telegram_bot is canonical. Do NOT reinstall bot_commands.
#      Its plist/wrapper are kept on-standard but it is intentionally not loaded.

# 26. Dashboard watcher — polls live API → Telegram alerts (every 5 min)
install_agent \
    "$REPO/scripts/com.spa.dashboard_watcher.plist" \
    "com.spa.dashboard_watcher" \
    "1"

echo ""
echo "--- ENGINE SLEEVES (HY / LP separate paper books) ---"

# 27. HY/carry sleeve daily cycle (plist in launchd/)
install_agent \
    "$REPO/launchd/com.spa.hy_cycle.plist" \
    "com.spa.hy_cycle" \
    "1"

# 28. LP sleeve daily cycle (plist in launchd/)
install_agent \
    "$REPO/launchd/com.spa.lp_cycle.plist" \
    "com.spa.lp_cycle" \
    "1"

echo ""
echo "--- PROTOCOL & PORTFOLIO MONITORS (cron) ---"

# 29. Portfolio monitor
install_agent \
    "$REPO/scripts/com.spa.portfolio_monitor.plist" \
    "com.spa.portfolio_monitor" \
    "1"

# 30. Peg monitor (stablecoin peg drift)
install_agent \
    "$REPO/scripts/com.spa.peg_monitor.plist" \
    "com.spa.peg_monitor" \
    "1"

# 31. Red-flag monitor
install_agent \
    "$REPO/scripts/com.spa.red_flag_monitor.plist" \
    "com.spa.red_flag_monitor" \
    "1"

# 32. Governance watcher
install_agent \
    "$REPO/scripts/com.spa.governance_watcher.plist" \
    "com.spa.governance_watcher" \
    "1"

# 33. Base gas monitor
install_agent \
    "$REPO/scripts/com.spa.base_gas_monitor.plist" \
    "com.spa.base_gas_monitor" \
    "1"

# 34. Sky/sUSDS monitor (GSM Pause Delay watch)
install_agent \
    "$REPO/scripts/com.spa.sky_monitor.plist" \
    "com.spa.sky_monitor" \
    "1"

# 35. BTS feed
install_agent \
    "$REPO/scripts/com.spa.bts-feed.plist" \
    "com.spa.bts-feed" \
    "1"

# 36. BTS monitor
install_agent \
    "$REPO/scripts/com.spa.bts-monitor.plist" \
    "com.spa.bts-monitor" \
    "1"

echo ""
echo "--- ANALYTICS & BACKUP (cron) ---"

# 37. Analytics tier B
install_agent \
    "$REPO/scripts/com.spa.analytics_tier_b.plist" \
    "com.spa.analytics_tier_b" \
    "1"

# 38. Analytics tier C
install_agent \
    "$REPO/scripts/com.spa.analytics_tier_c.plist" \
    "com.spa.analytics_tier_c" \
    "1"

# 39. 7-day checkpoint
install_agent \
    "$REPO/scripts/com.spa.checkpoint-7day.plist" \
    "com.spa.checkpoint-7day" \
    "1"

# 40. Weekly backup
install_agent \
    "$REPO/scripts/com.spa.weekly_backup.plist" \
    "com.spa.weekly_backup" \
    "1"

# 41. Daily data/*.json backup (pre-cycle snapshot, 30-day retention)
install_agent \
    "$REPO/scripts/com.spa.daily_backup.plist" \
    "com.spa.daily_backup" \
    "1"

# ===========================================================================
# ИТОГОВАЯ ТАБЛИЦА
# ===========================================================================
echo ""
echo "=============================================="
echo " РЕЗУЛЬТАТ УСТАНОВКИ"
echo "=============================================="
for line in "${RESULTS[@]}"; do
    echo "  $line"
done
echo ""
echo "  Итого: OK=$OK_COUNT  SKIP=$SKIP_COUNT  FAIL=$FAIL_COUNT"
echo ""

# Текущее состояние всех com.spa.* агентов
echo "--- Текущий launchctl list (com.spa.*) ---"
launchctl list 2>/dev/null | grep "com\.spa" | sort || echo "  (нет com.spa агентов)"
echo ""

echo "--- Логи ---"
echo "  autopush:          tail -f /tmp/spa_autopush.log"
echo "  rules_watchdog:    tail -f /tmp/spa_watchdog.log"
echo "  cycle_gap_monitor: tail -f /tmp/spa_cycle_gap_monitor.log"
echo "  daily_cycle:       tail -f $REPO/logs/launchd_stdout.log"
echo "  system_health:     tail -f /tmp/spa_system_health_morning.log"
echo "  agent_health:      tail -f /tmp/spa_agent_health.log"
echo "  tournament_engine: tail -f /tmp/spa_tournament_engine.log"
echo "  cycle_health:      tail -f /tmp/spa_cycle_health.log"
echo "  uptime_monitor:    tail -f /tmp/spa_uptime_monitor.log"
echo "  cloudflared:       tail -f /tmp/spa_cloudflared.log"
echo "  apiserver:         tail -f /tmp/spa_api.log"
echo "  strategy_lab:      tail -f $REPO/logs/strategy_lab_paper.err"
echo "  rates_desk_paper:  tail -f $REPO/logs/rates_desk_paper.log"
echo ""

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    echo "⚠️  $FAIL_COUNT агент(ов) не установлено. Проверь plist-файлы выше."
    exit 1
else
    echo "✅  Все агенты установлены успешно (FAIL=0)."
    exit 0
fi
