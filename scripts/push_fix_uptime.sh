#!/bin/bash
# SPA Push — P0-1 uptime_monitor exit-256 fix
#
# Что исправлено:
#   uptime_monitor выходил с кодом 1 при DEGRADED → launchd писал
#   LastExitStatus=256 на каждом прогоне, монитор выглядел «сломанным»,
#   система казалась слепой. Теперь exit 0 при успешном прогоне (DEGRADED
#   сообщается через uptime_status.json + Telegram), exit 1 только при
#   внутреннем сбое самого монитора. Флаг --strict сохраняет старое поведение.
#
# SECURITY: PAT читается из macOS Keychain (service: GITHUB_PAT_SPA).
# НЕ встраивать PAT или любые креды в этот файл.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_fix_uptime.sh

set -e

COMMIT_MSG="fix(P0-1): uptime_monitor exit 256 — exit 0 on DEGRADED (report via status file + Telegram), --strict for legacy; +21 tests"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/monitoring/uptime_monitor.py
/Users/yuriikulieshov/Documents/SPA_Claude/tests/test_uptime_monitor.py
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/com.spa.uptime_monitor.plist
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_fix_uptime.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push — P0-1 uptime_monitor exit-256 fix"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push fix_uptime complete!"
