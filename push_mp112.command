#!/bin/bash
# Push MP-112: Stress Engine v1
# Запусти двойным кликом из Finder или: bash push_mp112.command

cd "$(dirname "$0")"
python3 push_to_github.py \
  --files \
    spa_core/stress/__init__.py \
    spa_core/stress/stress_engine.py \
    scripts/run_stress_tests.py \
    spa_core/tests/test_stress_engine.py \
    KANBAN.json \
  --message "feat(MP-112): Stress engine v1 — COVID-2020, LUNA-2022, USDC-depeg-2023 scenarios ✅"
