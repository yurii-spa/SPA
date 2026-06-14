#!/bin/bash
# push_p02_p06_fixes.sh — P0-2 (port 8765 conflict) + P0-6 (cloudflared path)
COMMIT_MSG="fix(p0): fund-api port 8766 (resolve 8765 conflict), cloudflared path-robust wrapper"
FILES="scripts/com.spa.fund-api.plist \
scripts/fund_api_server.py \
scripts/com.spa.cloudflared.plist \
scripts/run_cloudflared.sh \
scripts/install_agents.sh"
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден"; exit 1; }
cd "$(dirname "$0")/.." || exit 1
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
