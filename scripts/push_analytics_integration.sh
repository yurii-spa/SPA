#!/bin/bash
# SPA Push — MP-1146 Analytics Integration (ADR-031)
#
# signal_aggregator Tier-A/B/C + scoring_engine analytics_composite subscore.
# Tier-A=12 (BLOCK gate), Tier-B=386 (advisory→scoring), Tier-C=180 (background).
#
# SECURITY: PAT is read from macOS Keychain (service: GITHUB_PAT_SPA).
# DO NOT embed PAT or any credentials in this file.
#
# Usage: bash ~/Documents/SPA_Claude/scripts/push_analytics_integration.sh

set -e

COMMIT_MSG="feat: MP-1146 analytics integration — signal_aggregator Tier-A/B/C, scoring_engine analytics_composite subscore"

FILES="/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/_module_registry.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/analytics/signal_aggregator.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/risk/scoring_engine.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/paper_trading/cycle_runner.py
/Users/yuriikulieshov/Documents/SPA_Claude/scripts/com.spa.analytics_tier_c.plist
/Users/yuriikulieshov/Documents/SPA_Claude/tests/test_signal_aggregator.py
/Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_scoring_engine.py
/Users/yuriikulieshov/Documents/SPA_Claude/docs/ADR-031-analytics-integration.md"

# PAT resolution: Keychain → env GITHUB_PAT_SPA → env SPA_GITHUB_PAT → ~/.github_pat
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null || echo "")
[ -z "$PAT" ] && PAT="${GITHUB_PAT_SPA:-${SPA_GITHUB_PAT:-}}"
[ -z "$PAT" ] && [ -f ~/.github_pat ] && PAT=$(cat ~/.github_pat)
[ -z "$PAT" ] && { echo "PAT not found — run: bash setup_pat.sh"; exit 1; }

cd ~/Documents/SPA_Claude
echo "SPA Push — MP-1146 Analytics Integration (ADR-031)"
python3 push_to_github.py --files $FILES --message "$COMMIT_MSG" --pat "$PAT"
echo "Push MP-1146 analytics integration complete!"
