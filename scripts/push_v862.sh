#!/bin/bash
# SPA Push v8.62
# MP-1216: DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer  (166 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v862.sh

set -e

COMMIT_MSG="feat(v8.62): MP-1216 DeFiProtocolVaultEarlyExitYieldForfeitureAnalyzer (166 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | a vault accrues yield continuously but only CRYSTALLIZES it (makes it withdrawable) at discrete points / after a cooldown/lock/vesting window; the slice accrued since the last crystallization but not yet vested is PENDING yield; if capital EXITS before that pending slice vests it is FORFEITED (retained by the remaining LPs) -- a realized-APY drag on an early capital rotation (relevant to SPA's tournament/promotion rotation), distinct from any fee. metrics: total_accrued_yield_pct REQUIRED finite>0 else INSUFFICIENT_DATA; pending_yield_pct (default 0, clamped [0,total]); vesting_progress_pct 0..100 (applied only in LINEAR mode); forfeit_mode CLIFF(default: whole pending forfeited until crystallization)/LINEAR(pro-rata forfeited=pending*(1-vesting_fraction)); kept_yield_pct=total-forfeited; forfeiture_fraction=clamp(forfeited/total,0,1) scale-free classification basis; realization_ratio=1-forfeiture_fraction; safe_fraction=clamp(1-pending/total,0,1) (already-crystallized share). classification NO_FORFEITURE(<=0.05)/MILD_FORFEITURE(<=0.20)/MODERATE_FORFEITURE(<=0.50)/SEVERE_FORFEITURE(>0.50)/INSUFFICIENT_DATA. flags FULLY_VESTED_EXIT / PENDING_YIELD_AT_RISK / FULL_FORFEITURE / CLIFF_VESTING / LINEAR_VESTING / LONG_COOLDOWN (cooldown_days>=14) / GAP_FROM_OVERRIDE. score=clamp(70*realization_ratio + 30*safe_fraction,0,100); INSUFFICIENT->0. HIGHER score = little/no accrued yield forfeited on the planned exit. recommendation EXIT_ANYTIME/MINOR_EXIT_COST/DELAY_EXIT_TO_VEST/AVOID_EARLY_EXIT; grade A-F. override path: direct forfeited_yield_pct verbatim (negative->magnitude, clamped [0,total]) -> geometry (pending/vesting/mode)->None, GAP_FROM_OVERRIDE flag, geometry-only flags suppressed, safe_fraction anchored to realization_ratio. aggregate cleanest_vault/worst_forfeiture_vault/avg_score/full_forfeiture_count/position_count; pure stdlib, atomic ring-buffer log (data/vault_early_exit_yield_forfeiture_log.json, cap 100), no inf/NaN, read-only/advisory | distinct from exit_fee/withdrawal_fee (a fee on PRINCIPAL paid out to the vault, not forfeiture of pending YIELD), idle_cash_drag (uninvested cash earning nothing, here capital WAS deployed and accrued), deployment_ramp_drag (ENTRY-side ramp, here EXIT-side), yield_harvesting_frequency/harvest_cycle_entry_timing (WHEN to harvest, here what is LOST by exiting before crystallization), performance_fee_* (the fee BASE, here no fee), pending_harvest_premium (ENTRY premium captured by a buyer, here the mirror EXIT cost of the seller) -- novel axis: forfeiture of accrued-but-not-yet-crystallized pending yield on an early exit before the vesting/cooldown window elapses | registry Tier-B yield_quality weight 0.5 (B 469->470, ALL 661->662) | self-authored sprint: no type=code&status=ready task in KANBAN (backlog=26: 11 agent_infra needing git/launchd/keychain on Mac + USER ACTION/P0-P2; features=7 P3; ideas=3 LOW), orchestrator chose the topic after a non-overlap grep scan of analytics modules (idle_cash_drag/deployment_ramp/withdrawal_fee/exit_fee/pending_harvest_premium existed; pending-yield early-exit forfeiture did not), added MP-1216 to KANBAN.json done and took it into work; updated KANBAN sprint_completed/sprint_current v8.61->v8.62 (sprint_current v8.63) + done MP-1216 (done_count 909->910), appended sprint_log, created this push script | architect review: last completed v8.61 ends in 1 (not 0/5) -> review NOT due; backlog scanned manually -> no type=code&status=ready, no architectural regressions | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched by this sprint"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_early_exit_yield_forfeiture_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_early_exit_yield_forfeiture_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_early_exit_yield_forfeiture_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v862.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.62 — MP-1216 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.62 complete!"
