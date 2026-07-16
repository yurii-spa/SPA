#!/bin/bash
# Push agent fixes to GitHub and install on Mac mini
set -e
cd /Users/yuriikulieshov/Documents/SPA_Claude

echo "======================================"
echo " SPA Agent Fix — $(date)"
echo "======================================"

PAT=$(security find-generic-password -w -s GITHUB_PAT_SPA)

echo ""
echo "=== Step 1: Push fixed plist files to GitHub ==="
/Users/yuriikulieshov/miniconda3/bin/python3 push_to_github.py --pat "$PAT" \
  --message "fix: system_health plist files + uptime_monitor XML comment fix" \
  --files \
    scripts/com.spa.uptime_monitor.plist \
    scripts/com.spa.system_health_morning.plist \
    scripts/com.spa.system_health_evening.plist \
    scripts/fix_agents.sh \
    scripts/push_and_fix_agents.command

echo ""
echo "=== Step 2: Install agents ==="
chmod +x scripts/fix_agents.sh
bash scripts/fix_agents.sh

echo ""
echo "======================================"
echo " ALL DONE"
echo "======================================"
