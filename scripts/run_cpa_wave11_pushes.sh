#!/bin/bash
# run_cpa_wave11_pushes.sh — Wave 11 Pushes: v11.55–v11.70
# MP-1552 (v11.68)
set -e
REPO="$HOME/Documents/SPA_Claude"
PAT=$(security find-generic-password -s "GITHUB_PAT_SPA" -w 2>/dev/null || echo "")

if [ -z "$PAT" ]; then
  echo "ERROR: PAT not found in Keychain (GITHUB_PAT_SPA)"
  exit 1
fi

cd "$REPO"
echo "=== Wave 11 Pushes: v11.55-v11.70 ==="
echo "Started: $(date)"
echo ""

push_sprint() {
  local version=$1
  local msg=$2
  if [ -f "scripts/push_${version}.sh" ]; then
    echo "Pushing $version — $msg..."
    bash "scripts/push_${version}.sh"
    echo "✅ $version pushed"
  else
    echo "⚠️  scripts/push_${version}.sh not found, skipping ($msg)"
  fi
}

# Wave 11 sprints
push_sprint "v1155" "SQLite data layer"
push_sprint "v1156" "JSON→SQLite migration"
push_sprint "v1157" "DB factory"
push_sprint "v1158" "Daily cycle SQLite"
push_sprint "v1159" "Landing meta tags"
push_sprint "v1160" "FAQ + methodology"
push_sprint "v1161" "Blog posts"
push_sprint "v1162" "Landing performance"
push_sprint "v1163" "Fluid + Notional adapters"
push_sprint "v1164" "AaveV3 improvements"
push_sprint "v1165" "Adapter conformance v2"
push_sprint "v1166" "ADR-041"
push_sprint "v1167" "Final KANBAN sync"
push_sprint "v1168" "Wave 11 push script"
push_sprint "v1169" "100-sprint retrospective"
push_sprint "v1170" "CURRENT_STATE v11.70"

echo ""
echo "=== Wave 11 Complete ==="
echo "Finished: $(date)"
