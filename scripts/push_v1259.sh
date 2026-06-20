#!/bin/bash
# scripts/push_v1259.sh
# Sprint v12.59 — Governance Watcher v2: Yield Parameter Tracker
#   spa_core/alerts/governance_watcher_v2.py — YieldParameterTracker
#     Tracks Aave/Compound/Morpho/Sky governance proposals that change
#     yield-affecting parameters (interest rate / reserve factor / supply cap / DSR).
#     - Logs to data/governance_alerts.json (atomic, ring-buffer 200, dedup by id)
#     - Telegram alert per new proposal (HTML, Keychain creds)
#     - Deterministic APY-impact heuristics (up/down/unknown) — no LLM
#   Tests: tests/test_governance_watcher_v2.py (39 tests, target 25)
#
# SECURITY: never push scripts/cf_install_token.command (CF tunnel token).
set -e
cd ~/Documents/SPA_Claude

python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/alerts/governance_watcher_v2.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/tests/test_governance_watcher_v2.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/scripts/push_v1259.sh \
  --message "Sprint v12.59 — Governance Watcher v2 YieldParameterTracker (Aave/Compound/Morpho/Sky rate-param monitoring, APY-impact heuristics, Telegram alerts), 39 tests"

echo "✅ v12.59 pushed"
