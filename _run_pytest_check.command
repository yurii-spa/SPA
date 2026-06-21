#!/bin/bash
cd ~/Documents/SPA_Claude

OUT=_pytest_check_result.txt
echo "=== pytest check v2 — $(date) ===" > "$OUT"
echo "" >> "$OUT"

echo "=== STEP 1: tests/ (tail 40) ===" >> "$OUT"
python3 -m pytest tests/ -q --tb=line 2>&1 | tail -40 >> "$OUT"

echo "" >> "$OUT"
echo "=== STEP 2: spa_core/tests/ (tail 10) ===" >> "$OUT"
python3 -m pytest spa_core/tests/ -q --tb=no 2>&1 | tail -10 >> "$OUT"

echo "" >> "$OUT"
echo "=== STEP 3: collection errors tests/ ===" >> "$OUT"
python3 -m pytest tests/ --co -q --tb=short 2>&1 \
  | grep -E "ModuleNotFoundError|ImportError|ERROR collecting|ERRORS" \
  | sort -u | head -30 >> "$OUT"

echo "" >> "$OUT"
echo "=== STEP 4: collection errors spa_core/tests/ ===" >> "$OUT"
python3 -m pytest spa_core/tests/ --co -q --tb=short 2>&1 \
  | grep -E "ModuleNotFoundError|ImportError|ERROR collecting|ERRORS" \
  | sort -u | head -30 >> "$OUT"

echo "" >> "$OUT"
echo "=== DONE ===" >> "$OUT"
cat "$OUT"
