#!/bin/bash
set -e

REPO="yurii-spa/SPA"
BRANCH="main"
COMMIT_MSG="feat(SPA-V509): ScenarioSimulator (MP-586) - run_scenario/get_builtin_scenarios(7)/run_all_scenarios/get_simulation_report/save_report; APY/TVL/peg-break shocks; wildcard *,T1,T2,T3,mainnet,usdc,l2; risk-limit checks; atomic ring-buffer 90; stdlib+math only; 161 tests green"

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

echo "=== SPA-V509 Push (MP-586 — ScenarioSimulator) ==="
echo "Files: 5 (scenario_simulator.py, test_scenario_simulator.py, KANBAN.json, SPA_sprint_log.md, push_v509.sh)"
echo ""

echo "--- Preflight: проверка EXISTS/MISSING ---"
[ -f "$SPA_DIR/spa_core/analytics/scenario_simulator.py" ] \
  && echo "EXISTS : spa_core/analytics/scenario_simulator.py" \
  || echo "MISSING: spa_core/analytics/scenario_simulator.py"
[ -f "$SPA_DIR/tests/test_scenario_simulator.py" ] \
  && echo "EXISTS : tests/test_scenario_simulator.py" \
  || echo "MISSING: tests/test_scenario_simulator.py"
[ -f "$SPA_DIR/KANBAN.json" ] \
  && echo "EXISTS : KANBAN.json" \
  || echo "MISSING: KANBAN.json"
[ -f "$SPA_DIR/SPA_sprint_log.md" ] \
  && echo "EXISTS : SPA_sprint_log.md" \
  || echo "MISSING: SPA_sprint_log.md"
[ -f "$SPA_DIR/scripts/push_v509.sh" ] \
  && echo "EXISTS : scripts/push_v509.sh" \
  || echo "MISSING: scripts/push_v509.sh"
echo ""

[ -f "$SPA_DIR/spa_core/analytics/scenario_simulator.py" ] \
  && push_file "spa_core/analytics/scenario_simulator.py" \
  || echo "⚠️  SKIP (not found): spa_core/analytics/scenario_simulator.py"

[ -f "$SPA_DIR/tests/test_scenario_simulator.py" ] \
  && push_file "tests/test_scenario_simulator.py" \
  || echo "⚠️  SKIP (not found): tests/test_scenario_simulator.py"

[ -f "$SPA_DIR/KANBAN.json" ] \
  && push_file "KANBAN.json" \
  || echo "⚠️  SKIP (not found): KANBAN.json"

[ -f "$SPA_DIR/SPA_sprint_log.md" ] \
  && push_file "SPA_sprint_log.md" \
  || echo "⚠️  SKIP (not found): SPA_sprint_log.md"

[ -f "$SPA_DIR/scripts/push_v509.sh" ] \
  && push_file "scripts/push_v509.sh" \
  || echo "⚠️  SKIP (not found): scripts/push_v509.sh"

echo ""
echo "=== SPA-V509 Push Complete ==="
