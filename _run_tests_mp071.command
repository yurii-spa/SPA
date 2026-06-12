#!/bin/bash
# MP-071 regression check — auto-generated, safe to delete
cd "$(dirname "$0")"
echo "=== pytest regression check ===" > /tmp/spa_pytest_mp071.log
python3 -m pytest spa_core/tests/ -q 2>&1 | tail -5 >> /tmp/spa_pytest_mp071.log 2>&1
echo "=== done ===" >> /tmp/spa_pytest_mp071.log
cat /tmp/spa_pytest_mp071.log
