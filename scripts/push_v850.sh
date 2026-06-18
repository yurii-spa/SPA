#!/bin/bash
# SPA Push v8.50
# MP-1204: DeFiProtocolVaultNetOfLossYieldRealizationAnalyzer  (201 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v850.sh

set -e

COMMIT_MSG="feat(v8.50): MP-1204 DeFiProtocolVaultNetOfLossYieldRealizationAnalyzer (201 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | A vault advertises a headline 'yield APY' computed ONLY from its POSITIVE income stream (harvested rewards, trading fees, interest) annualised. But a depositor's TRUE realised return must NET that headline yield against a SEPARATE stream of LOSS epochs the headline omits — share-price drawdowns from IL realisation, slashing, bad-debt socialisation, negative trading epochs — which hit NAV separately and are not subtracted from the advertised number. So the headline overstates the downside-inclusive realised total APR. This module subtracts the omitted loss stream from the advertised yield stream and quantifies the overstatement. metrics: headline_yield_apr_pct (= mean(yield_samples)*ppy), loss_drag_apr_pct (= mean(loss magnitudes)*ppy), net_realized_apr_pct (= headline - loss_drag), overstatement_pct (= headline - net), realization_ratio (= clamp(net/headline,0,1)), loss_fraction (= clamp(loss_drag/headline,0,1); scale-free classification basis), masked_epoch_fraction (= loss-epoch count / total epochs), worst_loss_epoch_pct, loss_epoch_count, gross_yield_total, loss_total, net_is_negative. Override path for <MIN_SAMPLES(=2) yield samples uses direct headline_yield_apr_pct + loss_drag_apr_pct. classification by loss_fraction: CLEAN_YIELD(<=0.05)/MILD_LOSS_DRAG(<=0.20)/MODERATE_LOSS_DRAG(<=0.50)/SEVERE_LOSS_DRAG(>0.50 or net_is_negative)/INSUFFICIENT_DATA. score = clamp(70*realization_ratio + 30*(1-loss_fraction),0,100). HIGHER score = losses negligible (realised ~ headline). flags NET_NEGATIVE_YIELD / FREQUENT_LOSS_EPOCHS / SINGLE_LARGE_LOSS / CLEAN_RECURRING / LOSS_FROM_OVERRIDE / FEW_SAMPLES; pure stdlib, atomic ring-buffer log (data/vault_net_of_loss_yield_realization_log.json, cap 100), no inf/NaN, read-only/advisory | distinct from vault_share_price_drawdown (magnitude/recovery of ONE drawdown event; here NET a recurring loss stream against the positive YIELD stream -> downside-inclusive realised APR), vault_loss_socialization_exposure (exposure to socialised bad debt as a risk; here realised-yield honesty: subtract the loss stream from the advertised positive-yield APR), vault_yield_variance_drag (geom<arith penalty from DISPERSION of one series, second moment; here an explicit two-stream FIRST-moment net of an omitted loss stream that vanishes when the loss stream is empty even if yield is volatile), vault_dollar_weighted_return_gap (cashflow-timing TWR vs DWR; here no cashflow timing), price_return_contamination (splits positive NAV growth into recurring-yield vs price-gain; here subtracts the omitted LOSS stream, opposite-sign component), real_yield_vs_incentive_yield (splits positive yield into real-fee vs incentive-token, both positive; here positive yield minus realised losses), performance_fee_volatility_tax (asymmetric FEE drag; here realised investment LOSSES, not fees) | registry Tier-B B=454->455, total 646->647 | self-authored sprint: no type=code&status=ready task in KANBAN (backlog=26: agent_infra needing git/launchd/keychain on Mac + P0/P1-FIX/USER ACTION; features=7 P3; ideas=3 LOW), orchestrator chose the topic, added MP-1204 to KANBAN.json done and took it into work; updated KANBAN sprint_completed/sprint_current v8.49->v8.50 + done MP-1204 done_count 898->899, appended sprint_log, created this push script | architect review: last completed before this was v8.49 (minor 49, not ending 0/5) so no review was due | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_net_of_loss_yield_realization_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_net_of_loss_yield_realization_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_net_of_loss_yield_realization_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v850.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.50 — MP-1204 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.50 complete!"
