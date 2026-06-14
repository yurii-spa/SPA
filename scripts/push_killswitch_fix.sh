#!/bin/bash
# SPA Push — Kill-Switch Sharpe min-days fix
#
# Problem: kill-switch fired on a false positive — with only 5 days of paper
# data the Sharpe came out at -61.35 (small-sample artefact: dividing by a
# near-zero volatility), holding the whole portfolio in cash (daily_yield $0).
#
# Fix:
#   * spa_core/governance/kill_switch.py
#       - MIN_DAYS_FOR_SHARPE = 30 (was an implicit < 5 guard)
#       - Sharpe trigger now skipped unless >= 30 days of data exist
#       - manual trigger now honours explicit "active": false in
#         kill_switch_active.json (deactivation via overwrite, not just unlink)
#   * data/kill_switch_active.json  — reset to active:false (false positive cleared)
#   * tests/test_kill_switch_min_days.py — regression tests (6/6 passing)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_killswitch_fix.sh

set -e

COMMIT_MSG="fix: kill-switch min 30 days for Sharpe; reset false-positive triggered at day 5"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/governance/kill_switch.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/kill_switch_active.json
/Users/yuriikulieshov/Documents/SPA_Claude/tests/test_kill_switch_min_days.py
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_killswitch_fix.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push — Kill-Switch Sharpe min-days fix"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push killswitch_fix complete!"
