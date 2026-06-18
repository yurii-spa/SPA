#!/bin/bash
# SPA Push v8.30
# MP-1178: DeFiProtocolVaultRewardSellPressureRunwayAnalyzer   (165 tests)
# MP-1179: DeFiProtocolVaultTradingFeeAPRVolatilityAnalyzer    (179 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v830.sh

set -e

COMMIT_MSG="feat(v8.30): MP-1178 VaultRewardSellPressureRunwayAnalyzer + MP-1179 VaultTradingFeeAPRVolatilityAnalyzer | 165+179=344 tests | advisory/read-only | reward sell-pressure runway: structural overhang of recurring emission-driven reward-token selling vs the token's organic buy-side liquidity (daily volume); when daily emission-sell USD is a large share of daily volume the token faces persistent downward pressure so the in-kind reward APR is worth less over time and the headline overstates durable yield; distinct from reward_autosell_slippage MP-1177 (per-harvest execution slippage), reward_token_price_exposure MP-1170 (market price risk of holding), bribe_dependency MP-1175 (external bribe funding) and gauge_emission_decay_forecaster MP-1074 (emission schedule decay) (sell_pressure_ratio, est_sell_pressure_pct, reward_share_pct, thin_buyside; NO_EMISSIONS/NEGLIGIBLE/LOW/MODERATE/HIGH_OVERHANG; higher score=more sustainable) [category yield_quality] + trading-fee APR volatility: for a vault whose yield comes from trading fees, the fee APR rides volatile volume; high fee-APR volatility and/or a declining volume trend mean the headline fee-APR is an unreliable forward signal; distinct from volume_to_tvl_efficiency (level), lp_fee_vs_il_breakeven (fees vs IL) and apy_anomaly_detector (one-off anomalies) (normalized_volatility, sustainable_fee_apr_pct, fee_apr_at_risk_pct, volume_collapse override; NO_FEE_YIELD/STABLE/MODERATE/HIGH_VOLATILITY/UNSTABLE; higher score=more durable fee yield) [category yield_quality] | registry Tier-B +2 (B=430, total 622) | pure stdlib, atomic ring-buffer logs, no inf/NaN | architect review (v8.30 multiple of 5): spa_core.dev_agents.architect unreachable in sandbox -> manual gap/backlog grep-review performed instead"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_reward_sell_pressure_runway_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_trading_fee_apr_volatility_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_reward_sell_pressure_runway_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_trading_fee_apr_volatility_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_reward_sell_pressure_runway_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_trading_fee_apr_volatility_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v830.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.30 — MP-1178 + MP-1179 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.30 complete!"
