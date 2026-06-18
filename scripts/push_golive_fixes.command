#!/bin/bash
# push_golive_fixes.command — GoLive fixes push (sprint_log, KANBAN, consecutive_days, analytics_scorecard)
# Double-click in Finder to run
cd ~/Documents/SPA_Claude
LOG="logs/push_golive_fixes_$(date +%Y%m%d_%H%M%S).log"
mkdir -p logs
exec > >(tee -a "$LOG") 2>&1

echo "════════════════════════════════════════════════"
echo " SPA — Pushing GoLive Preflight Fixes"
echo " $(date '+%Y-%m-%d %H:%M:%S')"
echo "════════════════════════════════════════════════"
echo ""
echo "Changes:"
echo "  • golive_preflight.py  — sprint_log.md path fix (was SPA_sprint_log.md)"
echo "  • KANBAN.json          — closed P0-FIX-001/002, P1-FIX-001 (verified done)"
echo "  • golive_status.json   — consecutive_ready_days=8 (≥7 ✅)"
echo "  • analytics_scorecard.json — fresh timestamp"
echo ""

MSG="fix(golive): sprint_log path + KANBAN P0/P1 closed + consecutive_days=8 + analytics_scorecard refresh [v8.78]"

push_file() {
  local f="$1"
  echo "▶ $f"
  python3 push_to_github.py --repo "yurii-spa/SPA" --file "$f" --message "$MSG"
  echo ""
}

push_file "scripts/golive_preflight.py"
push_file "KANBAN.json"
push_file "data/golive_status.json"
push_file "data/analytics_scorecard.json"

echo "════════════════════════════════════════════════"
echo " Verifying GoLive score after fixes..."
echo ""
python3 scripts/golive_preflight.py 2>/dev/null
echo ""
echo " Лог: $LOG"
echo "════════════════════════════════════════════════"
read -rp "Нажми Enter для закрытия..."
