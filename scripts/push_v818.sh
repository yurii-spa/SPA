#!/bin/bash
# SPA Push v8.18
# MP-1154: DeFiProtocolDepositCapHeadroomAnalyzer        (123 tests)
# MP-1155: DeFiProtocolDepositorConcentrationAnalyzer    (117 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v818.sh

set -e

COMMIT_MSG="feat(v8.18): MP-1154 DepositCapHeadroomAnalyzer + MP-1155 DepositorConcentrationAnalyzer | 123+117=240 tests | advisory/read-only vault_capacity | deposit-cap headroom (cap_utilization, remaining_headroom, intended_fits, days_to_cap_at_current_inflow, projected_dilution, headroom_score; AMPLE/MODERATE/TIGHT_HEADROOM/CAP_REACHED) + depositor concentration / bank-run risk (top1/top5_share, effective_depositor_count, whale_exit_tvl_drop, HHI, concentration_score; WELL_DISTRIBUTED/MODERATELY/HIGHLY_CONCENTRATED/WHALE_DOMINATED) | closes gap deposit_cap/depositor_concentration=0 | registry Tier-B +2 (new category vault_capacity) | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_deposit_cap_headroom_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_depositor_concentration_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_deposit_cap_headroom_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_depositor_concentration_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v818.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.18 — MP-1154 + MP-1155 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.18 complete!"
