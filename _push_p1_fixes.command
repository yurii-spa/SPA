#!/bin/bash
# P1 Audit Fixes Push — 2026-06-20 v12.00
# Пушит: adapter_registry.json, strategy_summary.json, CURRENT_STATE.md

set -e
cd ~/Documents/SPA_Claude

echo "=== SPA P1 Audit Fixes Push v12.00 ==="
echo "Файлы: data/adapter_registry.json, data/strategy_summary.json, CURRENT_STATE.md"
echo ""

python3 push_to_github.py \
  --files \
    /Users/yuriikulieshov/Documents/SPA_Claude/data/adapter_registry.json \
    /Users/yuriikulieshov/Documents/SPA_Claude/data/strategy_summary.json \
    /Users/yuriikulieshov/Documents/SPA_Claude/CURRENT_STATE.md \
  --message "feat: adapter_registry.json + strategy_summary.json generated; CURRENT_STATE v12.00

P1 Audit Fixes:
- data/adapter_registry.json: 28 adapters (T1×7, T2×14, T3×3 + watchlist/research)
- data/strategy_summary.json: 24 strategies S1–S21 with full metadata
- CURRENT_STATE.md: v12.00, GoLive 25/26, P0 fixes noted, Compound V3 OK (38%<40%)"

echo ""
echo "✅ Push завершён"
