#!/bin/bash
# SPA Push v8.36 (reconciliation)
# MP-1189: DeFiProtocolVaultAPYCompoundingBasisOverstatementAnalyzer  (216 tests)
# MP-1190: DeFiProtocolVaultAPRLookbackWindowSelectionBiasAnalyzer    (247 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v836.sh

set -e

COMMIT_MSG="feat(v8.36): reconcile MP-1189 VaultAPYCompoundingBasisOverstatementAnalyzer (216 tests) + MP-1190 VaultAPRLookbackWindowSelectionBiasAnalyzer (247 tests) | 463 tests total | advisory/read-only yield_quality | RECONCILIATION: code+tests+registry entries for both modules were authored by a prior orchestrator run but the bookkeeping (KANBAN done/sprint_completed/done_count, sprint_log, push script) was left unfinished; this run completes it. Internal docstring MP labels were off-by-one (MP-1188/MP-1189, colliding with MP-1188 EntryFee from v8.35) -> renumbered to MP-1189/MP-1190. | MP-1189: headline APY is derived from APR at SOME ASSUMED compounding cadence; if the storefront advertises APY at a richer cadence (e.g. daily 365x) than the vault actually auto-compounds (e.g. weekly 52x), the achievable effective APY is LOWER than headline -> headline OVERSTATES yield; classification HONEST_BASIS/MINOR/MODERATE/SEVERE_OVERSTATEMENT (+ INSUFFICIENT_DATA), flags COMPOUNDING_SHORTFALL/LARGE_HEADLINE_GAP; distinct from auto_compounding_frequency / yield_compounding_optimizer (which OPTIMIZE cadence vs gas) — this isolates whether the headline's compounding BASIS is actually achievable. | MP-1190: headline APR can be cherry-picked from the most favorable trailing lookback window; given APR across several standard windows (7d/30d/90d), if the headline matches the hottest/shortest window while a neutral longer base is materially lower, the headline reflects window-SELECTION optimism not durable yield; classification NEUTRAL_BASIS/MILD/MODERATE/STRONG_SELECTION (+ INSUFFICIENT_DATA/INSUFFICIENT_WINDOWS), flags HEADLINE_AT_HOTTEST/WIDE_WINDOW_SPREAD; distinct from apr_annualization_basis_risk (extrapolation from one short window's LENGTH) and trailing_window_boost_backdating (expired boost still inside the trailing mean) — this isolates WHICH of several windows was selected. | both pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry already contained both Tier-B entries (B=441, total 633) — counter unchanged | architect review: last completed before this run was v8.35 (multiple of 5) so review was due, but spa_core.dev_agents.architect is unreachable in sandbox (ModuleNotFoundError: anthropic) — skipped with note | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_apy_compounding_basis_overstatement_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_apr_lookback_window_selection_bias_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_apy_compounding_basis_overstatement_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_apr_lookback_window_selection_bias_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_apy_compounding_basis_overstatement_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_apr_lookback_window_selection_bias_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v836.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.36 — MP-1189 + MP-1190 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.36 complete!"
