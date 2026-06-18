#!/bin/bash
# SPA Push v8.28
# MP-1174: DeFiProtocolVaultSharePriceStalenessAnalyzer         (178 tests)
# MP-1175: DeFiProtocolVaultBribeDependencyAnalyzer             (177 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v828.sh

set -e

COMMIT_MSG="feat(v8.28): MP-1174 VaultSharePriceStalenessAnalyzer + MP-1175 VaultBribeDependencyAnalyzer | 178+177=355 tests | advisory/read-only | nav staleness: how stale the vault's reported pricePerShare/NAV is vs its expected update cadence (entering/exiting on a stale NAV = mispricing risk; oracle-priced = continuously fresh), distinct from underlying-asset oracle freshness and pending-harvest-premium (staleness_ratio, eff_ratio, hours_overdue, nav_drift_pct, mispricing_risk; FRESH/SLIGHTLY_STALE/STALE/SEVERELY_STALE; higher score=fresher) [category protocol_health] + bribe dependency: what share of headline APR is funded by external vote-incentive/bribe markets (Convex/Votium/Hidden Hand) and how durable it is, distinct from reward-token price exposure, real_yield_ratio and emission_runway (base_apr_pct, bribe_share_pct, apr_if_bribes_vanish_pct, bribes_declining; NO/LOW/MODERATE/HIGH_BRIBE_DEPENDENCY; higher score=more durable) [category yield_quality] | registry Tier-B +2 (B=426, total 618) | pure stdlib, atomic ring-buffer logs, no inf/NaN"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_share_price_staleness_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_bribe_dependency_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_share_price_staleness_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_bribe_dependency_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_share_price_staleness_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_bribe_dependency_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v828.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.28 — MP-1174 + MP-1175 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.28 complete!"
