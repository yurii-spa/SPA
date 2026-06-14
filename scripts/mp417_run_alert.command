#!/bin/bash
# MP-417: запуск milestone alert из Finder
cd "$(dirname "$0")/.."
python3 scripts/send_milestone_alert.py
echo ""
echo "Press any key to close..."
read -n 1
