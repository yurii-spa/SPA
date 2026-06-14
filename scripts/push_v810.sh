#!/bin/bash
# SPA Push v8.10
# MP-1144: DeFiProtocolRewardClaimTimingOptimizer       (157 tests)
# MP-1145: DeFiProtocolTVLYieldElasticityAnalyzer       (147 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v810.sh

set -e

COMMIT_MSG="feat(v8.10): MP-1144 RewardClaimTimingOptimizer + MP-1145 TVLYieldElasticityAnalyzer | 157+147=304 tests | optimal reward-claim timing (gas vs price-risk vol*sqrt(t) + reinvest opportunity cost, claim threshold/frequency, net-benefit) | TVL->APR compression elasticity (incentive dilution vs sticky base, self-crowding + external inflow) | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_reward_claim_timing_optimizer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_tvl_yield_elasticity_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_reward_claim_timing_optimizer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_tvl_yield_elasticity_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v810.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.10 — MP-1144 + MP-1145 + tests + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.10 complete!"
