#!/bin/bash
# Reinstall system_health plist (RunAtLoad=true) + force agent_health refresh
set -e
cd /Users/yuriikulieshov/Documents/SPA_Claude

echo "=== Push updated plists to GitHub ==="
PAT=$(security find-generic-password -w -s GITHUB_PAT_SPA)
/Users/yuriikulieshov/miniconda3/bin/python3 push_to_github.py --pat "$PAT" \
  --message "fix: system_health RunAtLoad=true so first logs created on install" \
  --files \
    scripts/com.spa.system_health_morning.plist \
    scripts/com.spa.system_health_evening.plist

echo ""
echo "=== Reinstall system_health agents (RunAtLoad=true) ==="
cp scripts/com.spa.system_health_morning.plist ~/Library/LaunchAgents/
cp scripts/com.spa.system_health_evening.plist ~/Library/LaunchAgents/

launchctl unload ~/Library/LaunchAgents/com.spa.system_health_morning.plist 2>/dev/null || true
launchctl unload ~/Library/LaunchAgents/com.spa.system_health_evening.plist 2>/dev/null || true
launchctl load ~/Library/LaunchAgents/com.spa.system_health_morning.plist
launchctl load ~/Library/LaunchAgents/com.spa.system_health_evening.plist
echo "Agents reloaded (RunAtLoad=true means they ran immediately)"

echo ""
echo "=== Wait 5s for logs to be created ==="
sleep 5

echo ""
echo "=== Verify logs ==="
ls -la /tmp/spa_system_health_*.log 2>/dev/null && echo "Logs created!" || echo "WARNING: no logs yet"

echo ""
echo "=== Force agent_health refresh ==="
launchctl start com.spa.agent_health
echo "agent_health_monitor triggered"
sleep 15

echo ""
echo "=== Current agent status ==="
/Users/yuriikulieshov/miniconda3/bin/python3 -c "
import json, datetime
data = json.load(open('data/agent_health.json'))
ts = data.get('timestamp','?')
ok = data.get('healthy_count',0)
crit = data.get('critical_count',0)
warn = data.get('warning_count',0)
print(f'Timestamp: {ts}')
print(f'OK={ok}  CRITICAL={crit}  WARNING={warn}  (total={data.get(\"total_agents\",0)})')
print()
for a in data.get('agents',[]):
    if a.get('status') != 'OK':
        print(f'  {a[\"status\"]:10} {a[\"label\"]}')
        if a.get('issue'):
            print(f'               issue: {a[\"issue\"]}')
"

echo ""
echo "DONE"
