#!/bin/bash
# push_sky_fix.command — sky_monitor last_checked bug fix + fresh status
# Double-click in Finder to run
cd ~/Documents/SPA_Claude
LOG="logs/push_sky_fix_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs
exec > >(tee -a "$LOG") 2>&1

echo "════════════════════════════════════════════════"
echo " SPA — Sky Monitor Fix Push"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════"
echo ""
echo "Fix: manual fallback now uses now_iso instead of hardcoded date"
echo "     sky_status.json last_checked was stuck at 2026-05-22"
echo ""

# Refresh sky_status.json before push (on Mac has real network)
echo "▶ Refreshing sky_status.json (on-chain query)..."
python3 -c "
import sys
sys.path.insert(0,'.')
from spa_core.data_pipeline.sky_monitor import check_sky_status_live, export_sky_status_json
status = check_sky_status_live()
path = export_sky_status_json(status)
print(f'  status={status[\"status\"]} source={status[\"source\"]} last_checked={status[\"last_checked\"][:19]}')
print(f'  written → {path}')
"
echo ""

MSG="fix(sky_monitor): last_checked uses now_iso in manual fallback (was hardcoded 2026-05-22) [v8.78]"

push_file() {
  local f="$1"
  echo "▶ $f"
  python3 push_to_github.py --repo "yurii-spa/SPA" --file "$f" --message "$MSG"
  echo ""
}

push_file "spa_core/data_pipeline/sky_monitor.py"
push_file "data/sky_status.json"

echo "════════════════════════════════════════════════"
echo " ✅ sky_monitor fix pushed — P0-FIX-004 CLOSED"
echo " Лог: $LOG"
echo "════════════════════════════════════════════════"
read -rp "Нажми Enter для закрытия..."
