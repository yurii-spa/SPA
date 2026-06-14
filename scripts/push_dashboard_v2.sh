#!/bin/bash
# push_dashboard_v2.sh — push audit-v2 fixes to GitHub
# Usage: bash scripts/push_dashboard_v2.sh

COMMIT_MSG="fix(dashboard): audit-v2 — P0-1a dates, P0-3 freshness+adapters, P1-2 lang cleanup, P2-2 hero strip"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/index.html \
/Users/yuriikulieshov/Documents/SPA_Claude/data/meta.json"

# ── Resolve PAT ───────────────────────────────────────────────────────────────
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден"; exit 1; }

# ── Run push ──────────────────────────────────────────────────────────────────
cd "$(dirname "$0")/.." || exit 1
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
