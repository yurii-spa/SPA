#!/bin/bash
# SPA Push v8.47
# MP-1201: DeFiProtocolVaultLeveragedCarrySpreadCompressionAnalyzer  (106 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v847.sh

set -e

COMMIT_MSG="feat(v8.47): MP-1201 DeFiProtocolVaultLeveragedCarrySpreadCompressionAnalyzer (106 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | A leveraged/looping vault (recursive LST looping, leveraged staking, folded lending) advertises a headline NET APR (net_headline = base_yield*L - borrow_snapshot*(L-1)) struck at a favourable SNAPSHOT borrow rate, where L = leverage = total_exposure/equity >= 1 and base_yield is the unlevered supply/staking yield. But the borrow rate is VARIABLE: it rises with utilisation and mean-reverts upward from the snapshot the headline was struck at. Over a holding window the honest realised net carry uses the TRAILING borrow-rate samples (their mean): net_realized = base_yield*L - borrow_realized*(L-1); spread_compression = net_headline - net_realized = (borrow_realized - borrow_snapshot)*(L-1). Crucially the borrow cost is multiplied by the AMPLIFICATION factor (L-1), so a small rise in the borrow rate is magnified into the net carry; if borrow_realized reaches base_yield the GROSS spread inverts and the levered carry goes NEGATIVE. HIGHER score = the realised borrow cost stays near the snapshot (stable, deep spread -> levered net carry survives); LOWER score = the borrow rate compressed (or inverted) the amplified spread, so the net carry realises far below the headline. | metrics: base_yield_apr_pct, leverage_factor, amplification_factor (L-1), borrow_rate_headline_pct (snapshot; default = min of samples), borrow_rate_realized_pct (mean of trailing samples), borrow_rate_volatility_pct (pstdev), max_borrow_rate_pct, gross_spread_headline_pct, gross_spread_realized_pct, net_apr_headline_pct, net_apr_realized_pct, spread_compression_pct, realization_ratio (= clamp(net_realized/net_headline,0,1)), compression_fraction (= clamp(spread_compression/net_headline,0,1), scale-free classification basis), coefficient_of_variation, carry_inverted, borrow_exceeds_base, sample_count; input borrow_rate_samples (trailing APR %, newest last; negative/non-finite skipped; bool rejected; MIN_SAMPLES=2) + optional borrow_rate_snapshot_pct, leverage / leverage_factor (or total_exposure_usd+equity_usd to derive L), OR direct overrides net_apr_headline_pct / borrow_rate_realized_pct (used when <2 samples; stability component neutral on override path); classification on compression_fraction STABLE_SPREAD(<=0.05)/MILD_COMPRESSION(<=0.20)/HEAVY_COMPRESSION(<=0.50)/SEVERE_COMPRESSION(>0.50 or carry_inverted), + INSUFFICIENT_DATA (non-finite/<=0 base_yield, no valid L>=1, <2 samples & no override, non-positive computed/override net_headline); flags CARRY_INVERTED / BORROW_EXCEEDS_BASE / HIGH_LEVERAGE_AMPLIFICATION (L>=3) / NO_LEVERAGE (L~1) / VOLATILE_BORROW (CV>=0.5) / SPREAD_FROM_SNAPSHOT (snapshot below trailing mean) / STABLE_SPREAD_CARRY / COMPRESSION_FROM_OVERRIDE; score = clamp(70*realization_ratio + 30*(1-normalised_borrow_vol), 0,100) | distinct from leverage_adjusted_apy_calculator (PRESCRIPTIVE forward calc of a leveraged APY; here DESCRIPTIVE headline honesty: trailing borrow-cost compression of an already-quoted net carry), leverage_loop_risk_analyzer (LIQUIDATION/unwind risk, protocol_health; here yield realisation/net-carry survival), funding_rate_carry_persistence (signed PERPETUAL FUNDING carry on a delta-neutral position; here the cost leg is a LENDING borrow rate amplified by (L-1)), stablecoin_yield_basis_spread (basis spread across stablecoin venues; here base-minus-borrow on one levered position amplified by leverage), yield_variance_drag (geom<arith SECOND-MOMENT dispersion penalty; here a FIRST-MOMENT borrow-cost rise amplified by (L-1)) | pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry Tier-B B=451->452, total 643->644 | KANBAN sprint_completed/sprint_current v8.46->v8.47, done MP-1201, done_count 896->897 | architect review: last completed before this run was v8.46 (minor 46, not a multiple of 5, not ending 0/5) so no review was due; spa_core.dev_agents.architect is in any case unreachable in sandbox (ModuleNotFoundError: anthropic); backlog scanned programmatically (no ready type=code tasks; 11 backlog items are Mac-bound agent_infra) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_leveraged_carry_spread_compression_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_leveraged_carry_spread_compression_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_leveraged_carry_spread_compression_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v847.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.47 — MP-1201 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.47 complete!"
