#!/bin/bash
cd /Users/yuriikulieshov/Documents/SPA_Claude
python3 push_to_github.py \
  --files \
    spa_core/paper_trading/protocol_scorecard.py \
    spa_core/tests/test_protocol_scorecard.py \
    KANBAN.json \
  --message "feat(SPA-V436): MP-129 Protocol Onboarding Scorecard — 72 tests"
