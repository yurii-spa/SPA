#!/bin/bash
# scripts/agent_resource_guard.sh — launchd wrapper for com.spa.resource_guard (ADR-551).
#
# Every 5 minutes: free disk on the Data volume, kernel memory pressure, swap and the heaviest
# processes by class (architecture/resource_policy.json) → data/resource_health.json, one owner alert
# per incident (resource_critical, resolved on recovery), disposable processes re-niced under memory
# pressure, the disk reserve released at CRITICAL. Kills nothing, deletes nothing (cleanup is the
# separate daily com.spa.resource_cleanup). Exit codes: 0 OK · 1 WARN · 2 CRITICAL or NOT MEASURED.
# Canonical bash wrapper (launchd cannot exec miniconda python directly → exit 78); log in /tmp.
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh \
    resource_guard spa_core.monitoring.resource_guard
