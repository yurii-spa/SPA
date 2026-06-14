#!/usr/bin/env bash
# Push script for sprint v7.16 — MP-956 + MP-957
# DeFi Insurance Coverage Analyzer + Protocol Yield Source Authenticity Checker
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

# --- PAT resolution (never embed tokens in files) ---
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "❌ PAT не найден"; exit 1; }

echo "✅ PAT найден"

FILES=(
  "$REPO_ROOT/spa_core/analytics/defi_insurance_coverage_analyzer.py"
  "$REPO_ROOT/spa_core/analytics/protocol_yield_source_authenticity_checker.py"
  "$REPO_ROOT/spa_core/tests/test_defi_insurance_coverage_analyzer.py"
  "$REPO_ROOT/spa_core/tests/test_protocol_yield_source_authenticity_checker.py"
  "$REPO_ROOT/data/insurance_coverage_log.json"
  "$REPO_ROOT/data/yield_authenticity_log.json"
  "$REPO_ROOT/KANBAN.json"
  "$REPO_ROOT/scripts/push_v716.sh"
)

echo "📦 Пушим файлы sprint v7.16 (MP-956 + MP-957)…"
python3 "$REPO_ROOT/push_to_github.py" \
  --files "${FILES[@]}" \
  --message "feat: MP-956+MP-957 DeFiInsuranceCoverageAnalyzer + ProtocolYieldSourceAuthenticityChecker; 188 tests; KANBAN v7.16 done_count=618"

echo "✅ Push v7.16 завершён"
