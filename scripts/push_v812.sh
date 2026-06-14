#!/bin/bash
# SPA Push v8.12
# MEVProtectionEffectiveness   (MEV sandwich/frontrun protection effectiveness scoring)
# BorrowerConcentrationRisk    (lending-pool borrower HHI / single-borrower exposure)
# 141 tests total
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_v812.sh

set -e

COMMIT_MSG="feat(v8.12): MEVProtectionEffectivenessAnalyzer + BorrowerConcentrationRiskAnalyzer | 141 tests | advisory/read-only | MEV protection effectiveness (sandwich/frontrun exposure, private-orderflow/commit-reveal coverage, protection score) + borrower concentration risk (HHI, single-borrower exposure, bad-debt tail) | registry Tier-B +2 | pure stdlib, atomic ring-buffer logs"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_mev_protection_effectiveness_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/defi_protocol_borrower_concentration_risk_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_mev_protection_effectiveness_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_defi_protocol_borrower_concentration_risk_analyzer.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json
/Users/yuriikulieshov/Documents/SPA_Claude/sprint_log.md
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v812.sh"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push v8.12 — MEVProtectionEffectiveness + BorrowerConcentrationRisk + tests + registry + KANBAN + sprint_log"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push v8.12 complete!"
