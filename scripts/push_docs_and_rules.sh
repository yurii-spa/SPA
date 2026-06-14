#!/bin/bash
# push_docs_and_rules.sh — пуш документации и операционных улучшений (2026-06-14)
#   - docs/DISASTER_RECOVERY.md      (P3-3: DR playbook)
#   - docs/ADR-032-push-strategy.md  (consolidation push-механизмов)
#   - scripts/update_current_state.sh (P2-1: auto-update CURRENT_STATE)
#   - RULES.md                        (RULE-7 plist install, RULE-8 Sharpe min-days)
#
# SECURITY: PAT читается из macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_docs_and_rules.sh

set -e

COMMIT_MSG="docs: DR playbook, push strategy ADR, RULES update, auto CURRENT_STATE script"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/docs/DISASTER_RECOVERY.md
/Users/yuriikulieshov/Documents/SPA_Claude/docs/ADR-032-push-strategy.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/update_current_state.sh
/Users/yuriikulieshov/Documents/SPA_Claude/RULES.md"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "Push docs_and_rules — DR playbook + ADR-032 + update_current_state.sh + RULES.md"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push docs_and_rules complete!"
