#!/bin/bash
set -e

REPO="yurii-spa/SPA"
BRANCH="main"
COMMIT_MSG="feat(SPA-V510): CompoundV3Adapter(BaseAdapter) T1 upgrade (MP-564) — RISK_SCORE=0.28/TVL=1.5B/APY=5.2%/PEG_TOLERANCE=0.005; is_peg_healthy/is_eligible/simulate_deposit/simulate_withdraw/get_health; adapter_status.json compound_v3_adapter block; __init__.py BaseAdapter import; 138 tests green"

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || \
      echo "${GITHUB_PAT_SPA:-}" || \
      echo "${SPA_GITHUB_PAT:-}" || \
      cat "$HOME/.github_pat" 2>/dev/null || \
      echo "")

if [ -z "$PAT" ]; then
  echo "ERROR: GitHub PAT not found (tried: Keychain GITHUB_PAT_SPA → \$GITHUB_PAT_SPA → \$SPA_GITHUB_PAT → ~/.github_pat)"
  exit 1
fi

API="https://api.github.com/repos/$REPO/contents"
SPA_DIR="$HOME/Documents/SPA_Claude"

push_file() {
  local file_path="$1"
  local content
  content=$(base64 -i "$SPA_DIR/$file_path")

  local sha
  sha=$(curl -s -H "Authorization: token $PAT" \
    "$API/$file_path?ref=$BRANCH" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('sha', ''))
" 2>/dev/null || echo "")

  local payload
  if [ -n "$sha" ]; then
    payload=$(python3 -c "
import json, sys
print(json.dumps({'message': sys.argv[1], 'content': sys.argv[2], 'sha': sys.argv[3], 'branch': sys.argv[4]}))" \
      "$COMMIT_MSG" "$content" "$sha" "$BRANCH")
  else
    payload=$(python3 -c "
import json, sys
print(json.dumps({'message': sys.argv[1], 'content': sys.argv[2], 'branch': sys.argv[3]}))" \
      "$COMMIT_MSG" "$content" "$BRANCH")
  fi

  result=$(curl -s -X PUT -H "Authorization: token $PAT" \
    -H "Content-Type: application/json" \
    -d "$payload" "$API/$file_path")

  if echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); sys.exit(0 if d.get('content') else 1)" 2>/dev/null; then
    echo "✅ $file_path"
  else
    echo "❌ $file_path — $(echo "$result" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('message','unknown'))" 2>/dev/null)"
  fi
}

echo "=== SPA-V510 Push (MP-564 — CompoundV3Adapter BaseAdapter upgrade) ==="
echo "Files: 7"
echo ""

echo "--- Preflight: проверка EXISTS/MISSING ---"
[ -f "$SPA_DIR/spa_core/adapters/compound_v3_adapter.py" ] \
  && echo "EXISTS : spa_core/adapters/compound_v3_adapter.py" \
  || echo "MISSING: spa_core/adapters/compound_v3_adapter.py"
[ -f "$SPA_DIR/spa_core/adapters/__init__.py" ] \
  && echo "EXISTS : spa_core/adapters/__init__.py" \
  || echo "MISSING: spa_core/adapters/__init__.py"
[ -f "$SPA_DIR/data/adapter_status.json" ] \
  && echo "EXISTS : data/adapter_status.json" \
  || echo "MISSING: data/adapter_status.json"
[ -f "$SPA_DIR/spa_core/tests/test_compound_v3_adapter.py" ] \
  && echo "EXISTS : spa_core/tests/test_compound_v3_adapter.py" \
  || echo "MISSING: spa_core/tests/test_compound_v3_adapter.py"
[ -f "$SPA_DIR/KANBAN.json" ] \
  && echo "EXISTS : KANBAN.json" \
  || echo "MISSING: KANBAN.json"
[ -f "$SPA_DIR/SPA_sprint_log.md" ] \
  && echo "EXISTS : SPA_sprint_log.md" \
  || echo "MISSING: SPA_sprint_log.md"
[ -f "$SPA_DIR/scripts/push_v510.sh" ] \
  && echo "EXISTS : scripts/push_v510.sh" \
  || echo "MISSING: scripts/push_v510.sh"
echo ""

[ -f "$SPA_DIR/spa_core/adapters/compound_v3_adapter.py" ] \
  && push_file "spa_core/adapters/compound_v3_adapter.py" \
  || echo "⚠️  SKIP (not found): spa_core/adapters/compound_v3_adapter.py"

[ -f "$SPA_DIR/spa_core/adapters/__init__.py" ] \
  && push_file "spa_core/adapters/__init__.py" \
  || echo "⚠️  SKIP (not found): spa_core/adapters/__init__.py"

[ -f "$SPA_DIR/data/adapter_status.json" ] \
  && push_file "data/adapter_status.json" \
  || echo "⚠️  SKIP (not found): data/adapter_status.json"

[ -f "$SPA_DIR/spa_core/tests/test_compound_v3_adapter.py" ] \
  && push_file "spa_core/tests/test_compound_v3_adapter.py" \
  || echo "⚠️  SKIP (not found): spa_core/tests/test_compound_v3_adapter.py"

[ -f "$SPA_DIR/KANBAN.json" ] \
  && push_file "KANBAN.json" \
  || echo "⚠️  SKIP (not found): KANBAN.json"

[ -f "$SPA_DIR/SPA_sprint_log.md" ] \
  && push_file "SPA_sprint_log.md" \
  || echo "⚠️  SKIP (not found): SPA_sprint_log.md"

[ -f "$SPA_DIR/scripts/push_v510.sh" ] \
  && push_file "scripts/push_v510.sh" \
  || echo "⚠️  SKIP (not found): scripts/push_v510.sh"

echo ""
echo "=== SPA-V510 Push Complete ==="
