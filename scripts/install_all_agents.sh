#!/usr/bin/env bash
# install_all_agents.sh — Установка ВСЕХ критических SPA LaunchAgents
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
echo " SPA LaunchAgents Installer v1362 (2026-06-22)"
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

echo ""
echo "--- SERVICES & REPORTING agents ---"

# 14. Family Fund API — uvicorn :8766 (investor cabinet backend)
install_agent \
    "$REPO/scripts/com.spa.familyfund.plist" \
    "com.spa.familyfund" \
    "1"

# 15. Telegram Daily Report — 08:00 local daily
install_agent \
    "$REPO/scripts/com.spa.telegram_daily.plist" \
    "com.spa.telegram_daily" \
    "1"

# 16. Telegram Weekly Report — Mon 10:00 local
install_agent \
    "$REPO/scripts/com.spa.telegram_weekly.plist" \
    "com.spa.telegram_weekly" \
    "1"

# 17. Telegram Milestone Alerts — hourly
install_agent \
    "$REPO/scripts/com.spa.telegram_milestone.plist" \
    "com.spa.telegram_milestone" \
    "1"

# 18. Dashboard static server — :8767 (moved off :8766 to avoid familyfund conflict)
install_agent \
    "$REPO/scripts/com.spa.dashboard.plist" \
    "com.spa.dashboard" \
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
echo "  morning_digest:    tail -f $REPO/logs/morning_digest_stdout.log"
echo ""

if [[ "$FAIL_COUNT" -gt 0 ]]; then
    echo "⚠️  $FAIL_COUNT агент(ов) не установлено. Проверь plist-файлы выше."
    exit 1
else
    echo "✅  Все агенты установлены успешно (FAIL=0)."
    exit 0
fi
