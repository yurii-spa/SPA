#!/usr/bin/env bash
# Sprint v10.90 — MP-1474: Atomic final count + migration roadmap
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"

python3 "$REPO_ROOT/push_to_github.py" \
  --files \
    "$REPO_ROOT/spa_core/utils/atomic.py" \
    "$REPO_ROOT/spa_core/reporting/tear_sheet.py" \
    "$REPO_ROOT/spa_core/reporting/pdf_report.py" \
    "$REPO_ROOT/spa_core/telegram/bot.py" \
    "$REPO_ROOT/spa_core/reports/investor_report.py" \
    "$REPO_ROOT/spa_core/agents/strategy_agent_v2.py" \
    "$REPO_ROOT/spa_core/agents/ceo_agent_v2.py" \
    "$REPO_ROOT/spa_core/agents/reporting_agent.py" \
    "$REPO_ROOT/spa_core/tests/test_tear_sheet.py" \
    "$REPO_ROOT/spa_core/tests/test_pdf_report.py" \
    "$REPO_ROOT/spa_core/tests/test_investor_report.py" \
    "$REPO_ROOT/spa_core/tests/test_strategy_agent_v2.py" \
    "$REPO_ROOT/spa_core/tests/test_ceo_agent_v2.py" \
    "$REPO_ROOT/landing/src/pages/status.astro" \
    "$REPO_ROOT/docs/ATOMIC_MIGRATION_ROADMAP.md" \
    "$REPO_ROOT/KANBAN.json" \
    "$REPO_ROOT/scripts/push_v1087.sh" \
    "$REPO_ROOT/scripts/push_v1088.sh" \
    "$REPO_ROOT/scripts/push_v1089.sh" \
    "$REPO_ROOT/scripts/push_v1090.sh" \
  --message "Sprint v10.90 — MP-1474 Atomic final count + migration roadmap (batch 8+9 migrations, landing status page, 449/637 migrated 70.5%)"
