#!/bin/bash
# SPA Push v8.51
# MP-1205: DeFiProtocolVaultEntryExitFeeAmortizationAnalyzer  (260 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v851.sh

set -e

COMMIT_MSG="feat(v8.51): MP-1205 DeFiProtocolVaultEntryExitFeeAmortizationAnalyzer (260 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | A vault quotes a headline RUNNING APR that EXCLUDES the one-off ENTRY (deposit) and EXIT (withdrawal) fees the LP pays. Amortised over the LP's actual holding horizon those one-off round-trip fees are a drag on the realised APR — and the SHORTER the holding period the LARGER the annualised drag (a 0.50% round-trip fee held 30 days ~= 6.08% APR drag; held 365 days = 0.50%; held 730 days = 0.25%). So the headline overstates the holding-period-adjusted realised APR, especially for short-term holders. metrics: headline_apr_pct (running yield ex-fees, required positive), round_trip_fee_pct (= entry+exit, or direct override), amortized_fee_drag_apr_pct (= round_trip * 365/holding_days), net_realized_apr_pct (= headline - drag), overstatement_pct (= headline - net = drag), realization_ratio (= clamp(net/headline,0,1)), fee_drag_fraction (= clamp(drag/headline,0,1); scale-free classification basis), breakeven_days (= round_trip/headline*365; holding below -> net negative), holding_days, net_is_negative. Override path for direct amortized_fee_drag_apr_pct (+ positive headline) takes the drag directly, holding geometry (round_trip/breakeven/holding) -> None. classification by fee_drag_fraction: CLEAN_LOW_FEE(<=0.05)/MILD_FEE_DRAG(<=0.20)/MODERATE_FEE_DRAG(<=0.50)/SEVERE_FEE_DRAG(>0.50 or net_is_negative)/INSUFFICIENT_DATA. score = clamp(70*realization_ratio + 30*(1-fee_drag_fraction),0,100). HIGHER score = amortised fee drag negligible vs headline (long hold and/or low fees -> realised ~ headline). flags CLEAN_LOW_FEE_HOLD / NET_NEGATIVE_AFTER_FEES / SHORT_HOLD_PENALTY (holding<60d) / HIGH_ROUND_TRIP_FEE (round_trip>=1.0%) / DRAG_FROM_OVERRIDE; holding-only flags suppressed on the override path; pure stdlib, atomic ring-buffer log (data/vault_entry_exit_fee_amortization_log.json, cap 100), no inf/NaN, read-only/advisory | distinct from performance_fee_volatility_tax (asymmetric HWM perf-fee on profit; here one-off entry/exit fees amortised over the horizon), net_of_loss_yield_realization (subtracts an investment LOSS stream; here amortises fixed transaction fees), lockup_opportunity_cost / vault_reward_lock_discount (time PV discount of LOCKED REWARDS; here transaction fees, not rewards), fee_calculator / yield_aggregator_fee_analyzer (mgmt/perf/gas fees; here specifically entry/exit amortised over holding_days with breakeven_days) | registry Tier-B B=455->456, total 647->648 | self-authored sprint: no type=code&status=ready task in KANBAN (backlog: agent_infra needing git/launchd/keychain on Mac + P0/P1-FIX/USER ACTION; features=P3; ideas=LOW), orchestrator chose the topic, added MP-1205 to KANBAN.json done and took it into work; updated KANBAN sprint_completed/sprint_current v8.50->v8.51 + done MP-1205 done_count 899->900, appended sprint_log, created this push script | architect review: last completed before this was v8.50 (ends in 0) so a review WAS due; python3 -m spa_core.dev_agents.architect --command review-backlog -> ModuleNotFoundError: anthropic (LLM architect unavailable in sandbox), did a manual deterministic backlog review instead (no ready code tasks; backlog unchanged) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_entry_exit_fee_amortization_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_entry_exit_fee_amortization_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_entry_exit_fee_amortization_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v851.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.51 — MP-1205 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.51 complete!"
