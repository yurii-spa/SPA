#!/bin/bash
cd ~/Documents/SPA_Claude
python3 push_to_github.py \
  --files spa_core/paper_trading/alpha_decay.py \
          spa_core/tests/test_alpha_decay.py \
          KANBAN.json \
  --message "feat(SPA-V430): MP-130 Alpha Persistence & Decay Curve — 74 tests"
echo "--- done (exit $?) ---"
