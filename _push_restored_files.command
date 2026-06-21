#!/bin/bash
cd "$(dirname "$0")"
echo "=== Push: spa_core/base.py + spa_core/utils/kanban.py ==="
python3 push_to_github.py \
  --files spa_core/base.py spa_core/utils/kanban.py \
  --message "fix: restore spa_core/base.py + utils/kanban.py lost after git reset"

echo ""
echo "=== Проверка тестов ==="
python3 -m pytest tests/test_baseanalytics_complete.py tests/test_spaerror_complete.py tests/test_metrics_collector.py -v --tb=short 2>&1 | tail -25

echo ""
read -p "Нажми Enter чтобы закрыть..."
