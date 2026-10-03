#!/bin/bash
# scripts/agent_resource_cleanup.sh — launchd wrapper for com.spa.resource_cleanup (ADR-551).
#
# Daily: (1) remove ONLY allow-listed disposable directories past their TTL
# (architecture/resource_policy.json → cleanup.disposable_dirs; links never followed; never_touch
# honoured; every removal logged to data/resource_cleanup_log.jsonl); (2) linked git worktrees ONLY
# through scripts/reap_stale_worktrees.py (idle ≥ 24 h, every path proven delivered/superseded,
# archived before removal); (3) write the orphan & supervision report data/orphan_report.json, which
# deletes nothing. Anything not clearly disposable is retained and reported.
exec /bin/bash /Users/yuriikulieshov/Documents/SPA_Claude/scripts/agent_template.sh \
    resource_cleanup spa_core.monitoring.resource_cleanup
