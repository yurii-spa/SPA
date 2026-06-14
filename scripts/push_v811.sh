#!/bin/bash
# SPA Push v8.11
# MP-1146: DeFiProtocolRiskAdjustedYieldHurdleAnalyzer        (119 tests)
# MP-1147: DeFiProtocolFixedVsFloatingYieldDecisionAnalyzer   (130 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v811.sh

set -e

COMMIT_MSG="feat(v8.11): MP-1146 RiskAdjustedYieldHurdleAnalyzer + MP-1147 FixedVsFloatingYieldDecisionAnalyzer | 119+130=249 tests | risk-adjusted yield hurdle (expected-loss drag from annual loss prob * loss-given-event, required hurdle APR vs risk-free, excess-over-hurdle, premium coverage ratio, clearance score) | fixed-vs-floating earn-side decision (spread, breakeven avg floating, P(floating beats fixed) via normal CDF, lock-vs-float score/recommendation) | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_risk_adjusted_yield_hurdle_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_fixed_vs_floating_yield_decision_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_risk_adjusted_yield_hurdle_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_fixed_vs_floating_yield_decision_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v811.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.11 — MP-1146 + MP-1147 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.11 complete!"
