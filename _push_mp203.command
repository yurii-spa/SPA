#!/bin/bash
# MP-203 push — auto-generated, safe to delete after running
set -e
cd /Users/yuriikulieshov/Documents/SPA_Claude

python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/adapters/l2_adapters.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/risk/chain_limits.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/risk/policy.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/agent_runtime/mandates/l2_adapters.json \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_l2_adapters.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json \
  --message "MP-203: L2 adapters Arbitrum+Base, chain limits (<=70% chain, <=50% L2)"

echo "--- Push complete. You can close this window. ---"
