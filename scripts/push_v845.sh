#!/bin/bash
# SPA Push v8.45
# MP-1199: DeFiProtocolVaultPriceReturnContaminationAnalyzer  (167 tests)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v845.sh

set -e

COMMIT_MSG="feat(v8.45): MP-1199 DeFiProtocolVaultPriceReturnContaminationAnalyzer (167 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | A vault quotes a headline trailing 'APY' computed from its share-price (NAV) growth over a window, but NAV growth BLENDS two distinct components: (1) RECURRING YIELD (fees/interest/emissions accrued into share-price) — persistent, repeatable productive income a holder keeps forward; and (2) PRICE RETURN of the underlying volatile asset (governance token, LST, LP/basket) whose spot price rose/fell over the window — a ONE-OFF mark-to-market move that mean-reverts and is NOT a repeatable yield (a capital gain that happened to land inside the measurement window). A vault that rode a token rally prints an INFLATED trailing APY that overstates the forward recurring yield. The honest realisable recurring yield SUBTRACTS the price-return contamination: recurring_return_i = total_return_i - price_return_i; recurring_yield_apr = mean(recurring_return_i)*ppy; price_return_contribution = mean(price_i)*ppy. HIGHER score = headline almost all recurring yield (low contamination) -> forward-realisable. | metrics: recurring_yield_apr_pct (realisable persistent part), price_return_contribution_pct (annualized price component, may be < 0), total_window_apr_pct (= recurring + price), overstatement_pct (= headline - recurring), realization_ratio (= recurring/headline via safe-div), contamination_fraction (scale-free = |price|/(|recurring|+|price|), in [0,1]; classification basis), price_return_volatility_pct / recurring_yield_volatility_pct (pstdev when >=2 samples), coefficient_of_variation, periods_per_year (default 365), sample_count, used_samples, used_override; input total_return_samples + price_return_samples (per-period %, newest last; paired filtering — pair skipped if either element non-interpretable to a finite number; bool rejected; MIN_SAMPLES=2) OR direct overrides recurring_yield_apr_pct / price_return_contribution_pct (if only one given the other is derived from headline); classification on contamination_fraction PURE_YIELD(<=0.05)/LIGHTLY_CONTAMINATED(<=0.20)/MODERATELY_CONTAMINATED(<=0.50)/PRICE_DRIVEN(>0.50), + INSUFFICIENT_DATA (no >=2 valid pairs and no valid override, or non-finite headline, or degenerate all-zero); flags PRICE_RALLY_INFLATED (price>0 and contamination>=0.20) / RECURRING_YIELD_NEGATIVE (recurring<0 — the 'yield' was entirely price, masking a fee/IL bleed) / MEAN_REVERSION_EXPOSED (price>0 with material price-vol) / HEADLINE_FROM_APPRECIATION (contamination>0.50) / GENUINE_YIELD (PURE_YIELD) / CONTRIBUTION_FROM_OVERRIDE; score = clamp(70*clamp(1-contamination_fraction,0,1) + 30*clamp(1-normalized_price_vol,0,1), 0,100) | distinct from reward_token_price_exposure (FORWARD price-RISK of reward tokens on future income; here BACKWARD-looking DECOMPOSITION of already-realised trailing return into recurring vs price-return), headline_spot_snapshot_vs_twap (representativeness of the rate LEVEL spot-vs-TWAP — first moment / is the quote a spike; here the quote may be a perfectly representative average yet still inflated by price appreciation in NAV growth — we separate non-repeatable capital-gain from repeatable yield), yield_variance_drag (geom<arith deficit from DISPERSION of positive yield — second moment; here a first-moment subtraction of the price component, not a variance penalty), share_price_premium (premium of share PRICE to NAV — entry overpayment; here the COMPOSITION of NAV growth) | paired non-finite samples filtered before stats | pure stdlib, atomic ring-buffer log, no inf/NaN, read-only/advisory | registry Tier-B B=449->450, total 641->642 | KANBAN sprint_completed/sprint_current v8.44->v8.45, done MP-1199, done_count 894->895 | architect review: last completed before this run was v8.44 (minor 44, not a multiple of 5) so no review required; spa_core.dev_agents.architect unreachable in sandbox anyway (ModuleNotFoundError: anthropic), backlog scanned programmatically (no ready type=code tasks) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_price_return_contamination_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_price_return_contamination_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_price_return_contamination_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v845.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.45 — MP-1199 + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.45 complete!"
