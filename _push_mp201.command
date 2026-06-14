#!/bin/bash
# MP-201 push — can be deleted after run
cd /Users/yuriikulieshov/Documents/SPA_Claude
python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/adapters/pendle_pt.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/spa_core/tests/test_pendle_pt.py \
    /Users/yuriikulieshov/Documents/SPA_Claude/KANBAN.json \
  --message "feat(MP-201): Pendle PT read-only APY feed, stablecoin markets ✅"
echo "--- DONE (press any key to close) ---"
read -n 1
