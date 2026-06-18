#!/bin/bash
# SPA Push — uptime_monitor v2: track com.spa.analytics_tier_c (19th agent)
#
# Что добавлено:
#   Аудит показал, что com.spa.analytics_tier_c (19-й агент, daily 05:00) не
#   отслеживался uptime_monitor. Добавлен в AGENT_OUTPUT_FILES и LAUNCHD_SERVICES:
#     - тип: periodic (StartCalendarInterval Hour=5)
#     - output: data/analytics_report_full.json
#     - max_age: 129600s (86400 * 1.5 = 36h — больше суток, не флапает на пропуск)
#
# SECURITY: PAT читается из macOS Keychain (service: GITHUB_PAT_SPA).
# НЕ встраивать PAT или любые креды в этот файл.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_fix_uptime_v2.sh

set -e

COMMIT_MSG="fix(monitoring): track com.spa.analytics_tier_c in uptime_monitor (periodic daily 05:00, data/analytics_report_full.json, 36h max_age); 21/21 tests pass"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/monitoring/uptime_monitor.py
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_fix_uptime_v2.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push — uptime_monitor v2 (analytics_tier_c tracking)"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push fix_uptime_v2 complete!"
