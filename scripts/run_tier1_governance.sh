#!/usr/bin/env bash
# run_tier1_governance.sh — keep the Tier-1 governance/audit/DR/SSOT report JSONs fresh.
# Each step is best-effort (set +e) so one failure never blocks the others.
# Invoked daily by com.spa.tier1_governance (07:15 UTC).
set +e

REPO="/Users/yuriikulieshov/Documents/SPA_Claude"
PY="/Users/yuriikulieshov/miniconda3/bin/python3"
cd "$REPO" || exit 1

ts() { date -u "+%Y-%m-%dT%H:%M:%SZ"; }

echo "[$(ts)] tier1_governance: START"

# 1. SSOT manifest → data/ssot_manifest.json
echo "[$(ts)] ssot: writing data/ssot_manifest.json"
"$PY" -m spa_core.governance.ssot

# 2. Governance policy → data/governance_policy.json
echo "[$(ts)] policy: writing data/governance_policy.json"
"$PY" -m spa_core.governance.policy

# 3. Execution readiness audit → data/execution_readiness.json
echo "[$(ts)] readiness_audit: writing data/execution_readiness.json"
"$PY" -m spa_core.execution.readiness_audit

# 4. DR backup snapshot + verify, then prune ring-buffer (keep newest 14)
echo "[$(ts)] dr_backup: snapshot + verify"
"$PY" -m spa_core.backtesting.tier1.dr_backup
echo "[$(ts)] dr_backup: prune (keep=14)"
"$PY" -c "from spa_core.backtesting.tier1 import dr_backup; print(dr_backup.prune(keep=14))"

echo "[$(ts)] tier1_governance: DONE"
