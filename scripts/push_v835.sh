#!/bin/bash
# SPA Push v8.35
# MP-1188: DeFiProtocolVaultEntryFeeAmortizationAnalyzer            (221 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v835.sh

set -e

COMMIT_MSG="feat(v8.35): MP-1188 VaultEntryFeeAmortizationAnalyzer | 221 tests | advisory/read-only | entry-fee amortization: a vault charges a ONE-TIME fee on principal at entry (deposit_fee_pct) and/or exit (exit_fee_pct), distinct from a streaming management fee or a performance fee on profit; amortized across the holder's intended horizon a one-time round-trip fee lowers the effective NET APR below the headline (gross) APR; over 365 days a 0.5% round-trip fee costs ~0.5%/yr, but over 30 days the SAME fee annualizes to ~6%/yr of drag and can erase most of a modest headline; quantifies round_trip_fee_pct, annualized_fee_drag_pct (= round_trip x 365/horizon), net_apr_pct, retained_fraction, fee_drag_fraction, breakeven_horizon_days and breakeven_beyond_horizon; classification NEGLIGIBLE/MILD/MODERATE/HEAVY/FEE_TRAP (+ INSUFFICIENT_DATA); flags HIGH_DEPOSIT_FEE/SHORT_HORIZON_PENALTY/NET_NEGATIVE/BREAKEVEN_BEYOND_HORIZON; distinct from gas_breakeven / round_trip_cost (fixed GAS/trading costs in \$ vs position size) and performance_fee_high_water_mark / performance_fee_crystallization_frequency (fees on PROFIT) — this is the protocol-charged percentage fee on PRINCIPAL charged once (higher score=fee drag small relative to headline over your horizon) [category yield_quality] | registry Tier-B +1 (B=441, total 633) | pure stdlib, atomic ring-buffer log, no inf/NaN | self-authored yield_quality sprint: no type=code&status=ready tasks in backlog | architect review: v8.34 not a multiple of 5 -> no separate review required (spa_core.dev_agents.architect unreachable in sandbox anyway)"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_entry_fee_amortization_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_entry_fee_amortization_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_entry_fee_amortization_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v835.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.35 — MP-1188 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.35 complete!"
