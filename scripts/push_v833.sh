#!/bin/bash
# SPA Push v8.33
# MP-1184: DeFiProtocolVaultTrailingWindowBoostBackdatingAnalyzer (184 tests)
# MP-1185: DeFiProtocolVaultAPRAnnualizationBasisRiskAnalyzer      (190 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v833.sh

set -e

COMMIT_MSG="feat(v8.33): MP-1184 VaultTrailingWindowBoostBackdatingAnalyzer + MP-1185 VaultAPRAnnualizationBasisRiskAnalyzer | 184+190=374 tests | advisory/read-only | trailing-window boost backdating: a vault headline APR is an AVERAGE over a trailing window, so an incentive boost that already (partially) ended INSIDE the lookback window still inflates the trailing average and the headline overstates the forward run-rate; quantifies that overstatement from boost coverage within the window, distinct from gauge_emission_decay_forecaster / protocol_incentive_decay_monitor (higher score=closer to forward run-rate) [category yield_quality] + APR annualization basis risk: a headline APR is annualized by extrapolating a short measurement window x(365/window), so the shorter the window the more a single anomalous period inflates the annualized figure (scaled by intra-period volatility), distinct from apr_quote_staleness (quote AGE) and apr_source_dispersion (cross-source disagreement) (higher score=longer/more trustworthy basis) [category yield_quality] | registry Tier-B +2 (B=436, total 628) | pure stdlib, atomic ring-buffer logs, no inf/NaN | reconciliation: code was authored by a prior orchestrator run, this run completed the bookkeeping (KANBAN/sprint_log/push script) | architect review: v8.33 not a multiple of 5 -> no separate review required (spa_core.dev_agents.architect unreachable in sandbox anyway)"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_trailing_window_boost_backdating_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_apr_annualization_basis_risk_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_trailing_window_boost_backdating_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_apr_annualization_basis_risk_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_trailing_window_boost_backdating_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_apr_annualization_basis_risk_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v833.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.33 — MP-1184 + MP-1185 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.33 complete!"
