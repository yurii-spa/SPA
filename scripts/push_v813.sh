#!/bin/bash
# SPA Push v8.13
# InsuranceFundAdequacy      (protocol insurance/backstop fund coverage vs at-risk TVL)
# YieldHarvestingFrequency   (optimal reward harvest cadence: gas vs compounding gain)
# 131 tests total
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v813.sh

set -e

COMMIT_MSG="feat(v8.13): InsuranceFundAdequacyAnalyzer + YieldHarvestingFrequencyOptimizer | 131 tests | advisory/read-only | insurance fund adequacy (coverage ratio vs at-risk principal, shortfall, adequacy score/grade) + yield harvesting frequency (gas-vs-compounding optimal cadence, net APY uplift, breakeven harvests) | registry Tier-B +2 | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_insurance_fund_adequacy_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_yield_harvesting_frequency_optimizer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_insurance_fund_adequacy_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_yield_harvesting_frequency_optimizer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v813.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.13 — InsuranceFundAdequacy + YieldHarvestingFrequency + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.13 complete!"
