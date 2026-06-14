#!/bin/bash
# SPA Agent Topology — установка всех launchd агентов
# Запуск: bash scripts/install_agents.sh
# Безопасно: idempotent (unload перед load), не трогает уже запущенные сервисы.

set -e
PLIST_DIR="$(cd "$(dirname "$0")" && pwd)"
LAUNCH_AGENTS="$HOME/Library/LaunchAgents"
PYTHON="/Users/yuriikulieshov/miniconda3/bin/python3"

# Проверяем python
if [ ! -f "$PYTHON" ]; then
    echo "ERROR: python3 не найден: $PYTHON"
    echo "Проверь путь miniconda или укажи другой python."
    exit 1
fi
echo "✅ Python: $($PYTHON --version)"

# Список плистов для установки (L1 + L2 + L3b + L4-new)
declare -a AGENTS=(
    # L1 — persistent daemons
    "com.spa.httpserver"
    "com.spa.cloudflared"
    # L2 — every 5 min
    "com.spa.uptime_monitor"
    "com.spa.cycle_health"
    "com.spa.cycle_gap_monitor"
    "com.spa.portfolio_monitor"
    "com.spa.peg_monitor"
    "com.spa.red_flag_monitor"
    # L2b — every 15 min
    "com.spa.governance_watcher"
    # L3b — every 90 min
    "com.spa.autopush"
    # L4 — daily (NEW)
    "com.spa.base_gas_monitor"
    "com.spa.sky_monitor"
    "com.spa.analytics_tier_c"
    # L1b — persistent Telegram bot (KeepAlive long-poll)
    "com.spa.bot_commands"
    # L4 — daily reports / weekly backup
    "com.spa.daily-paper-report"
    "com.spa.weekly_backup"
    # L5 — одноразовый checkpoint (конкретная дата 2026-06-19 в plist;
    #       после выполнения не повторяется, повторная установка безопасна)
    "com.spa.checkpoint-7day"
)

echo ""
echo "=== SPA Agent Topology — Install ==="
echo "Plist dir: $PLIST_DIR"
echo "LaunchAgents: $LAUNCH_AGENTS"
echo ""

INSTALLED=0
SKIPPED=0
ERRORS=()

for AGENT in "${AGENTS[@]}"; do
    PLIST_SRC="$PLIST_DIR/${AGENT}.plist"
    PLIST_DST="$LAUNCH_AGENTS/${AGENT}.plist"

    if [ ! -f "$PLIST_SRC" ]; then
        echo "⚠️  SKIP  $AGENT — plist не найден: $PLIST_SRC"
        SKIPPED=$((SKIPPED + 1))
        continue
    fi

    # Копируем plist
    cp "$PLIST_SRC" "$PLIST_DST"

    # Unload (если уже загружен — игнорируем ошибку)
    launchctl unload "$PLIST_DST" 2>/dev/null || true

    # Load
    if launchctl load "$PLIST_DST" 2>&1; then
        echo "✅ LOADED $AGENT"
        INSTALLED=$((INSTALLED + 1))
    else
        echo "❌ FAIL  $AGENT"
        ERRORS+=("$AGENT")
    fi
done

echo ""
echo "=== Результат ==="
echo "Установлено: $INSTALLED"
echo "Пропущено:   $SKIPPED"
echo "Ошибок:      ${#ERRORS[@]}"
if [ ${#ERRORS[@]} -gt 0 ]; then
    echo "Ошибки в: ${ERRORS[*]}"
fi

echo ""
echo "=== Статус всех spa агентов ==="
launchctl list | grep com.spa | sort

echo ""
echo "=== Логи (последние 3 строки каждого) ==="
for LOG in /tmp/spa_*.log; do
    [ -f "$LOG" ] && echo "--- $LOG ---" && tail -3 "$LOG" 2>/dev/null
done
