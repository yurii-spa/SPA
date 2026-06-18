#!/bin/bash
# SPA Push v8.39
# MP-1193: DeFiProtocolVaultHeadlineSpotSnapshotVsTWAPAnalyzer  (206 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v839.sh

set -e

COMMIT_MSG="feat(v8.39): MP-1193 DeFiProtocolVaultHeadlineSpotSnapshotVsTWAPAnalyzer (206 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | A vault's HEADLINE APR is often a SPOT snapshot of the instantaneous rate at the measurement instant; the yield a holder actually captures over the window is the TIME-WEIGHTED AVERAGE (TWAP) of that rate. When the headline is snapshotted during a transient rate SPIKE, spot >> twap and realized yield falls short. This module measures how REPRESENTATIVE the spot snapshot is of the TWAP. HIGHER score = spot representative of (or below) the TWAP -> trustworthy headline. | metrics/thresholds: premium = spot - twap; classification MINOR (<=3pp)/MODERATE (<=8pp)/SEVERE (>8pp) (+ INSUFFICIENT_DATA); spot_at_peak when spot >= 0.98x peak | distinct from yield_realization_gap (headline vs realized share-price growth, aggregate), apr_lookback_window_selection_bias (choosing window LENGTH), apr_source_dispersion (disagreement across sources), utilization_peak_headline_revert (utilization-specific reversion) | pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry Tier-B B=443->444, total 635->636 | RECONCILIATION: code/test/data were authored by a prior orchestrator run (files 19:18) but registry+KANBAN+sprint_log+push were left incomplete; this run finished the bookkeeping | architect review: last completed before this run was v8.38 (minor 38, not a multiple of 5) so no review due; spa_core.dev_agents.architect also unreachable in sandbox | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_headline_spot_snapshot_vs_twap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_headline_spot_snapshot_vs_twap_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_headline_spot_snapshot_vs_twap_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v839.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.39 — MP-1193 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.39 complete!"
