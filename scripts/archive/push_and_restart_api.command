#!/bin/bash
cd /Users/yuriikulieshov/Documents/SPA_Claude

echo "=== Push API + monitor fixes ==="
PAT=$(security find-generic-password -w -s GITHUB_PAT_SPA)
/Users/yuriikulieshov/miniconda3/bin/python3 push_to_github.py --pat "$PAT" \
  --message "fix: live API no-cache headers + agent_health false CRITICAL for restarted always_on" \
  --files \
    spa_core/api/server.py \
    spa_core/monitoring/agent_health_monitor.py

echo ""
echo "=== Restart apiserver ==="
launchctl stop com.spa.apiserver
sleep 3
launchctl start com.spa.apiserver
echo "apiserver restarted"

echo ""
echo "=== Force agent_health refresh ==="
launchctl start com.spa.agent_health
sleep 15

echo ""
echo "=== New status ==="
/Users/yuriikulieshov/miniconda3/bin/python3 -c "
import json
data = json.load(open('data/agent_health.json'))
print(f'OK={data[\"healthy_count\"]}  CRITICAL={data[\"critical_count\"]}  WARNING={data[\"warning_count\"]}  total={data[\"total_agents\"]}')
for a in data.get('agents',[]):
    if a.get('status') != 'OK':
        print(f'  {a[\"status\"]:10} {a[\"label\"]} — {a[\"issue\"]}')
"
echo "DONE"
