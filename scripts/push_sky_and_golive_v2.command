#!/bin/bash
# push_sky_and_golive_v2.command — sky_monitor fix + golive_checker consecutive_days + Gnosis guide
# Double-click in Finder to run
cd ~/Documents/SPA_Claude
LOG="logs/push_sky_golive_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs
exec > >(tee -a "$LOG") 2>&1

echo "════════════════════════════════════════════════"
echo " SPA — Sky + GoLive v2 Push"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════"
echo ""
echo "Changes:"
echo "  • sky_monitor.py         — last_checked uses now_iso (not hardcoded 2026-05-22)"
echo "  • golive_checker.py      — consecutive_ready_days tracked + seeded from paper start"
echo "  • docs/GNOSIS_SAFE_SETUP.md — step-by-step Gnosis Safe deployment guide"
echo "  • KANBAN.json            — P0-FIX-004 closed, guide added to done"
echo ""

# Refresh sky_status.json on real Mac (has network access)
echo "▶ Refreshing sky_status.json (on-chain query)..."
python3 -c "
import sys; sys.path.insert(0,'.')
from spa_core.data_pipeline.sky_monitor import check_sky_status_live, export_sky_status_json
status = check_sky_status_live()
path = export_sky_status_json(status)
print(f'  status={status[\"status\"]} source={status[\"source\"]} last_checked={status[\"last_checked\"][:19]}')
"
echo ""

# Run golive_checker to update consecutive_ready_days in golive_status.json
echo "▶ Updating golive_status.json (consecutive_ready_days)..."
python3 -c "
import sys; sys.path.insert(0,'.')
from spa_core.paper_trading.golive_checker import GoLiveChecker
import pathlib
r = GoLiveChecker(pathlib.Path('data')).check(write=True)
print(f'  ready={r.ready} consecutive_ready_days={r.consecutive_ready_days}')
"
echo ""

MSG_SKY="fix(sky_monitor): last_checked uses now_iso in manual fallback; golive_checker tracks consecutive_ready_days [v8.78]"

push_file() {
  local f="$1"
  local msg="$2"
  echo "▶ $f"
  python3 push_to_github.py --repo "yurii-spa/SPA" --file "$f" --message "$msg"
  echo ""
}

push_file "spa_core/data_pipeline/sky_monitor.py" "$MSG_SKY"
push_file "data/sky_status.json" "$MSG_SKY"
push_file "spa_core/paper_trading/golive_checker.py" "$MSG_SKY"
push_file "data/golive_status.json" "$MSG_SKY"
push_file "docs/GNOSIS_SAFE_SETUP.md" "docs: Gnosis Safe 2-of-3 step-by-step setup guide (ADR-010) [v8.78]"
push_file "KANBAN.json" "chore(kanban): P0-FIX-004 closed, Gnosis guide added [v8.78]"

echo ""
echo "▶ Final GoLive score:"
python3 scripts/golive_preflight.py 2>/dev/null | head -5
echo ""
echo "════════════════════════════════════════════════"
echo " Лог: $LOG"
echo "════════════════════════════════════════════════"
read -rp "Нажми Enter для закрытия..."
