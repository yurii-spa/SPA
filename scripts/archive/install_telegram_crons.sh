#!/usr/bin/env bash
#
# install_telegram_crons.sh (MP v12.48)
# -------------------------------------
# Installs and loads the three launchd agents that drive the Telegram
# reporting pipeline:
#
#   com.spa.telegram_daily     — daily report   08:00 local, every day
#   com.spa.telegram_weekly    — weekly report  10:00 local, Sundays
#   com.spa.telegram_milestone — milestone scan every hour (3600s)
#
# NOTE ON INVOCATION:
#   The reporting scripts use absolute `from spa_core...` imports, so they
#   must be launched as MODULES (`python3 -m spa_core.reporting.<mod>`) with
#   the repo root as WorkingDirectory — exactly like com.spa.daily_cycle.
#   Running them by file path (`python3 .../daily_telegram_report.py`) fails
#   with `ModuleNotFoundError: No module named 'spa_core'`.
#
#   We use the miniconda python that every other com.spa.* agent already
#   uses, for runtime consistency.
#
# The plist files themselves are LOCAL config and are intentionally NOT
# committed to git (see CLAUDE.md). This script is the committed source of
# truth — re-running it regenerates and reloads all three agents idempotently.
#
# Usage:  bash scripts/install_telegram_crons.sh
set -euo pipefail

PY="/Users/yuriikulieshov/miniconda3/bin/python3"
REPO="/Users/yuriikulieshov/Documents/SPA_Claude"
LA="${HOME}/Library/LaunchAgents"
mkdir -p "${LA}"

write_plist() {
    # $1 = label, $2 = plist path, $3 = schedule-xml, $4 = module, $5 = logbase
    local label="$1" path="$2" schedule="$3" module="$4" logbase="$5"
    cat > "${path}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>${label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>${PY}</string>
        <string>-m</string>
        <string>${module}</string>
        <string>--run</string>
    </array>
    <key>WorkingDirectory</key>
    <string>${REPO}</string>
${schedule}
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <false/>
    <key>StandardOutPath</key>
    <string>/tmp/${logbase}.log</string>
    <key>StandardErrorPath</key>
    <string>/tmp/${logbase}_err.log</string>
</dict>
</plist>
PLIST
    echo "  wrote ${path}"
}

reload() {
    # $1 = label, $2 = plist path
    local label="$1" path="$2"
    launchctl unload "${path}" 2>/dev/null || true
    launchctl load "${path}"
    echo "  loaded ${label}"
}

# --- 1. Daily report: 08:00 every day ---------------------------------------
DAILY_SCHED='    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>8</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>'
write_plist "com.spa.telegram_daily" "${LA}/com.spa.telegram_daily.plist" \
    "${DAILY_SCHED}" "spa_core.reporting.daily_telegram_report" "spa_telegram_daily"

# --- 2. Weekly report: Sunday 10:00 -----------------------------------------
WEEKLY_SCHED='    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>10</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>'
write_plist "com.spa.telegram_weekly" "${LA}/com.spa.telegram_weekly.plist" \
    "${WEEKLY_SCHED}" "spa_core.reporting.weekly_telegram_report" "spa_telegram_weekly"

# --- 3. Milestone scan: every hour ------------------------------------------
MILESTONE_SCHED='    <key>StartInterval</key>
    <integer>3600</integer>'
write_plist "com.spa.telegram_milestone" "${LA}/com.spa.telegram_milestone.plist" \
    "${MILESTONE_SCHED}" "spa_core.reporting.alert_on_milestone" "spa_telegram_milestone"

echo "Loading agents..."
reload "com.spa.telegram_daily"     "${LA}/com.spa.telegram_daily.plist"
reload "com.spa.telegram_weekly"    "${LA}/com.spa.telegram_weekly.plist"
reload "com.spa.telegram_milestone" "${LA}/com.spa.telegram_milestone.plist"

echo
echo "Installed Telegram launchd agents:"
launchctl list | grep -E "com\.spa\.telegram_" || echo "  (none found — check errors above)"
