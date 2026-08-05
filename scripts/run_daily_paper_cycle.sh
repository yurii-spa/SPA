#!/bin/bash
# scripts/run_daily_paper_cycle.sh
# Daily paper trading cycle — CANONICAL runner (called by launchd com.spa.daily_cycle).
#
# Replaces the legacy com.spa.cyclerunner agent (disabled 2026-06-20). That agent
# was the only thing actually advancing the paper track; this script now owns that job.
#
# Two steps, in order:
#   1. cycle_runner — THE engine. Pulls live APY/TVL, runs strategies + RiskPolicy,
#      rebalances the virtual portfolio, writes paper_trading_status.json /
#      equity_curve_daily.json / trades.json / audit_trail (source="cycle_runner").
#      This is what makes the track advance. WITHOUT it the track silently freezes.
#   2. CPACycleWithEvidence — evidence report built ON TOP of the fresh state (non-fatal).
#
# Logs to logs/daily_cycle_YYYYMMDD.log
#
# NOTE: no `set -e` — we capture the cycle's exit code and still run the evidence
# report even if the cycle returns non-zero, then exit with the cycle's code.
#
# HEARTBEAT: status lines go through `tee` so they reach BOTH the dated log and
# this script's stdout. Under launchd, stdout is captured into the plist's
# StandardOutPath (logs/launchd_stdout.log) — which is what agent_health checks
# for freshness. The heavy cycle/evidence output stays in the dated log only.
# Result: agent fired → fresh launchd_stdout.log; cycle failed → non-zero exit
# (agent_health flags last_exit); never ran → stale/missing log → CRITICAL.
#
# PATH: launchd does not inherit the shell PATH, so PYTHON is hardcoded (miniconda).

PYTHON=/Users/yuriikulieshov/miniconda3/bin/python3

cd ~/Documents/SPA_Claude

LOG_DIR=~/Documents/SPA_Claude/logs
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily_cycle_$(date +%Y%m%d).log"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Starting daily paper cycle (cycle_runner)" | tee -a "$LOG_FILE"

# ── Step 0: code sync from origin/main (agent-prod-clean-checkout-variant2) ─
# Pushes land on origin via API and never touch this tree; without this step the cycle
# executes stale code (2026-08-03: prod ran July-15 code for weeks). Whole-dir sync of
# spa_core/scripts/tests + pushers, fail-safe (rolls back on broken imports, non-zero exit).
# NON-FATAL for the cycle: on sync failure we run on the previous (verified) code — the
# failure is loud in data/code_sync_status.json + /tmp/spa_code_sync.log + drift monitor.
# NOTE: this may replace run_daily_paper_cycle.sh itself on disk. Safe: git-checkout/tar
# replace files by unlink+create (new inode), so the running shell keeps reading the OLD
# inode to completion; code_sync additionally wraps itself in main() for the same reason.
bash scripts/code_sync_from_origin.sh >> "$LOG_FILE" 2>&1
SYNC_EXIT=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] code_sync exit=$SYNC_EXIT (0=synced/in-sync, 1=rolled back)" | tee -a "$LOG_FILE"

# ── Step 1: real cycle engine — advances the paper track ───────────────────
# OWNER-APPROVED 2026-07-06 (money-path allocation dial): use the constrained yield
# optimizer instead of the risk_adjusted heuristic. It concentrates into the highest-yield
# protocols WITHIN the RiskPolicy caps (TVL floor, 40% T1 / 20% T2 per-protocol, T2≤50%,
# APY≤30%) — targets ~6-8% projected (~5-7% realized after cash buffer/costs) vs the ~3.2%
# the risk_adjusted default was delivering. Reversible: unset this env to revert to the default.
export SPA_ALLOCATOR_MODEL="optimized_yield"

# WRITE-INTERLOCK (track-integrity): cycle_runner is fail-CLOSED by default and
# will NOT write the canonical live track without an explicit opt-in. This is
# THE production cycle, so it MUST pass --live (== SPA_ALLOW_LIVE_WRITE=1).
# Without --live the daily track would silently freeze (writes go to a sandbox).
"$PYTHON" -m spa_core.paper_trading.cycle_runner --verbose --live >> "$LOG_FILE" 2>&1
CYCLE_EXIT=$?
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] cycle_runner exit=$CYCLE_EXIT" | tee -a "$LOG_FILE"

# ── Step 2: evidence report on top of the fresh state (non-fatal) ──────────
"$PYTHON" -c "
import sys
sys.path.insert(0, '.')
from spa_core.backtesting.cpa_cycle_with_evidence import CPACycleWithEvidence
print(CPACycleWithEvidence(base_dir='.').run())
" >> "$LOG_FILE" 2>&1 \
  || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] evidence report failed (non-fatal)" >> "$LOG_FILE"

# ── Step 3: Site Custodian auto-deploy (ADR-YL-011) — regenerate the public track_snapshot from the
# fresh golive/equity state and push it if changed, triggering deploy-landing.yml (landing/** trigger).
# Non-fatal: a deploy hiccup must never fail the cycle. Result: fresh snapshot -> fresh site, <=30 min lag.
"$PYTHON" scripts/deploy_site_snapshot.py >> "$LOG_FILE" 2>&1 \
  || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] site snapshot deploy failed (non-fatal)" >> "$LOG_FILE"

# ── Step 4: fleet-parity drift guard (Q3-2) — the THIRD watchman of .claude/rules/deployment.md:
# "is the fleet COMPOSITION the one we declared?" (drift monitor answers "is it the code we accepted",
# acceptance answers "can it start", agent_health answers "is it alive" — none of them answers this one).
# It had no caller at all: written in July, invoked once by hand, then silent for 597h while
# agent_health honestly repeated "fleet parity stale" into a void (agent-fleet-parity-guard-never-scheduled).
# Here instead of its own LaunchAgent on purpose: the fleet must not grow by one just to watch itself,
# and a guard that lives inside the cycle cannot be forgotten by the installer the way it just was.
# NON-FATAL and deliberately so: exit 1 means DRIFT (a real finding to read in data/fleet_parity.json),
# not a broken cycle. If this step stops running, fleet_parity.json goes stale and agent_health WARNs
# within 26h — the silence itself is alarmed.
"$PYTHON" scripts/fleet_parity_check.py >> "$LOG_FILE" 2>&1 \
  || echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] fleet parity: DRIFT or check failed (non-fatal, see data/fleet_parity.json)" >> "$LOG_FILE"

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] Cycle completed (cycle_runner exit $CYCLE_EXIT)" | tee -a "$LOG_FILE"
exit $CYCLE_EXIT
