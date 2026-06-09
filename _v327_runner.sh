#!/bin/bash
# Temporary V327 verification runner. Writes results to _v327_results.txt.
cd /sessions/happy-jolly-wozniak/mnt/Documents/SPA_Claude || exit 99
OUT=_v327_results.txt
: > "$OUT"
if [ ! -x /tmp/spavenv/bin/python ]; then
  python3 -m venv /tmp/spavenv >>"$OUT" 2>&1
  /tmp/spavenv/bin/pip install -q pytest requests >>"$OUT" 2>&1
fi
echo "PYTHON: $(/tmp/spavenv/bin/python --version 2>&1)" >> "$OUT"
echo "===== NEW TEST FILE (tests/test_defillama_feed.py) =====" >> "$OUT"
PYTHONPATH=. /tmp/spavenv/bin/python -m pytest tests/test_defillama_feed.py -q >> "$OUT" 2>&1
echo "NEW_EXIT=$?" >> "$OUT"
echo "===== FULL SUITE (tests/) =====" >> "$OUT"
PYTHONPATH=. /tmp/spavenv/bin/python -m pytest tests/ -q >> "$OUT" 2>&1
echo "FULL_EXIT=$?" >> "$OUT"
echo "===== DONE =====" >> "$OUT"
