#!/bin/bash
# SPA Push v8.31
# MP-1180: DeFiProtocolVaultAPRQuoteStalenessAnalyzer      (174 tests)
# MP-1181: DeFiProtocolVaultAPRSourceDispersionAnalyzer    (189 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v831.sh

set -e

COMMIT_MSG="feat(v8.31): MP-1180 VaultAPRQuoteStalenessAnalyzer + MP-1181 VaultAPRSourceDispersionAnalyzer | 174+189=363 tests | advisory/read-only | APR quote staleness: the headline APR is itself a QUOTE computed at some point from a trailing window; if it is stale (refreshed N hours ago vs the expected cadence) and/or conditions are volatile, the spot APR may not reflect current yield so the headline is an unreliable signal; distinct from vault_share_price_staleness (age of the vault's reported share price / NAV) and oracle_price_freshness (age of the asset oracle price) (staleness_ratio, hours_overdue, volatility_adjusted_staleness, confidence_pct; FRESH/SLIGHTLY_STALE/STALE/SEVERELY_STALE; high-volatility+stale override to AVOID_OR_VERIFY; higher score=fresher/more reliable) [category yield_quality] + APR source dispersion: when several independent sources/aggregators report DIFFERENT APRs for the same vault the quote is unreliable; high cross-source dispersion (CoV of the APR list) means low confidence in the headline, and a large headline-vs-median gap flags the headline source as possibly broken/stale; distinct from vault_yield_realization_gap (realized vs advertised over time, single source) and apy_anomaly_detector (one-off anomalies in one series) (dispersion_ratio, median_apr_pct, apr_spread_pct, headline_vs_median_pct, headline_is_outlier; TIGHT_CONSENSUS/MINOR/MODERATE/HIGH_DISPERSION + INSUFFICIENT_SOURCES; outlier+>=MODERATE override to AVOID_OR_VERIFY; higher score=more consistent) [category yield_quality] | registry Tier-B +2 (B=432, total 624) | pure stdlib (own _median/_stdev, no statistics dep), atomic ring-buffer logs, no inf/NaN | architect review: v8.31 not a multiple of 5 -> no separate review required (spa_core.dev_agents.architect unreachable in sandbox anyway)"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_apr_quote_staleness_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_apr_source_dispersion_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_apr_quote_staleness_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_apr_source_dispersion_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_apr_quote_staleness_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_apr_source_dispersion_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v831.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.31 — MP-1180 + MP-1181 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.31 complete!"
