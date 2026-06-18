#!/bin/bash
# SPA Push v8.52
# MP-1206: DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer  (177 tests)
# + reconcile: MP-1205 added to KANBAN done column (was shipped v8.51, missing from done)
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v852.sh

set -e

COMMIT_MSG="feat(v8.52): MP-1206 DeFiProtocolVaultHeadlineYieldHonestyCompositeAnalyzer (177 tests) | advisory/read-only yield_quality Tier-B (weight 0.5) | composite BOTTOM-UP roll-up of the per-mechanism headline-drag family (entry/exit fee amortisation, management-fee accrual, performance-fee volatility tax, net-of-loss realisation, dollar-weighted return gap, reward autosell slippage, idle-cash/deployment-ramp drag, emission-decay/boost-revert, ...) into ONE number: net realised APR after ALL known drags, total overstatement, a single honesty score, and the SINGLE dominant culprit. Does NOT model any mechanism itself — it CONSUMES the per-mechanism annualised drags and decomposes the headline additively: raw_total_drag = sum(component.drag_apr_pct); net_realized = headline - raw_total_drag; overstatement = headline - net = raw_total_drag; realization_ratio = clamp(net/headline,0,1); drag_fraction = clamp(raw_total/headline,0,1) (scale-free classification basis); dominant_source/dominant_drag/dominant_share = clamp(dominant/raw_total,0,1). input: headline_apr_pct (required positive, else INSUFFICIENT_DATA) + drag_components (list of {source,drag_apr_pct} with alt keys drag/value/apr_pct and name/label; OR a {source: drag} mapping; OR bare numbers with positional names; each drag coerced finite>=0 magnitude, negatives->abs, invalid/non-finite skipped, exact 0 kept). override path: direct total_drag_apr_pct (finite, negative->magnitude; NaN/inf fall through to components) + positive headline -> verbatim, component_count=0, dominant_*->None. no override AND no valid components -> INSUFFICIENT_DATA. classification by drag_fraction: CLEAN_HEADLINE(<=0.05)/MILD_EROSION(<=0.20)/MODERATE_EROSION(<=0.50)/SEVERE_EROSION(>0.50 or net_is_negative)/INSUFFICIENT_DATA. score = clamp(70*realization_ratio + 30*(1-drag_fraction),0,100). HIGHER score = stacked drags negligible vs headline (realised ~ headline). flags CLEAN_HEADLINE_CONFIRMED / NET_NEGATIVE_AFTER_DRAGS / SINGLE_DOMINANT_DRAG (dominant_share>=0.5) / MANY_DRAG_SOURCES (count>=4) / DRAG_FROM_OVERRIDE (component-only flags suppressed on the override path); aggregate cleanest_headline_vault/worst_eroded_vault/avg_score/net_negative_count/position_count; pure stdlib, atomic ring-buffer log (data/vault_headline_yield_honesty_composite_log.json, cap 100), no inf/NaN, read-only/advisory | distinct from yield_realization_gap (MP-1169: top-down EMPIRICAL realised-vs-promised gap from share-price growth, cause-agnostic; here BOTTOM-UP additive attribution naming the culprit), from the single-mechanism analyzers (each isolates ONE drag; here the roll-up consuming their outputs), from position_health_score_aggregator/integrated_risk_dashboard (aggregate RISK signals; here yield-honesty drags into a realised-APR decomposition) | registry Tier-B B=456->457, total 648->649 | RECONCILE: MP-1205 (v8.51 EntryExitFeeAmortization) was shipped (module/test/registry/sprint_log, done_count=900) but missing from the KANBAN done column -> added | self-authored sprint: no type=code&status=ready task in KANBAN (backlog: agent_infra needing git/launchd/keychain on Mac + P0/P1-FIX/USER ACTION; features=P3; ideas=LOW), orchestrator chose the topic, added MP-1206 to KANBAN.json done and took it into work; updated KANBAN sprint_completed/sprint_current v8.51->v8.52 + done MP-1205(reconcile)+MP-1206 done_count 900->901, appended sprint_log, created this push script | architect review: last completed before this was v8.51 (not ending in 0/5) -> no separate review due; spa_core.dev_agents.architect unavailable in sandbox anyway (ModuleNotFoundError: anthropic) | STRICTLY READ-ONLY (SPA-BL-011): risk/execution/monitoring/allocator/cycle_runner.py/golive_checker.py untouched"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_vault_headline_yield_honesty_composite_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_vault_headline_yield_honesty_composite_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/data/vault_headline_yield_honesty_composite_log.json
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/.gitignore
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v852.sh"

# PAT resolution: Keychain -> env GITHUB_PAT_SPA -> env SPA_GITHUB_PAT -> ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.52 — MP-1206 + tests + registry + KANBAN + sprint_log (+ MP-1205 reconcile)"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.52 complete!"
