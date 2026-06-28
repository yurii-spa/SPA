#!/bin/bash
# verify_fleet_after_reboot.sh — confirm + heal the SPA launchd fleet after a
# reboot / OS update.
#
# WHY: SPA agents are gui-domain LaunchAgents (~/Library/LaunchAgents). They
# auto-load when the user LOGS IN (not at boot). After a reboot you must log in
# once; launchd then loads every plist (RunAtLoad fires the one-shots, KeepAlive
# starts the daemons, schedules resume). This script verifies that happened and
# re-bootstraps anything that didn't — so recovery is one command.
#
# USAGE (after you log in following a reboot):
#   bash ~/Documents/SPA_Claude/scripts/verify_fleet_after_reboot.sh
#
# It is READ-MOSTLY + idempotent: it only (re)bootstraps agents that are not
# loaded; it never mutates the go-live track. stdlib/launchctl only.
set -uo pipefail

REPO="/Users/yuriikulieshov/Documents/SPA_Claude"
LA="$HOME/Library/LaunchAgents"
UID_N="$(id -u)"
GUI="gui/$UID_N"

# RETIRED agents — never (re)bootstrap these even if a stale plist lingers.
# Keep in sync with RETIRED_LABELS in spa_core/monitoring/agent_health_monitor.py.
# (bot_commands→telegram_bot, httpserver→apiserver, the legacy daily/weekly
#  senders→digest_daily/digest_weekly.) Booting these would re-introduce a
# Telegram 409 / duplicate-flood regression.
RETIRED="com.spa.bot_commands com.spa.httpserver com.spa.telegram_daily com.spa.telegram_weekly com.spa.morning_digest com.spa.daily-paper-report"
is_retired() { case " $RETIRED " in *" $1 "*) return 0;; *) return 1;; esac; }

echo "── SPA fleet post-reboot check ── $(date -u '+%Y-%m-%d %H:%M UTC')"

installed=0 loaded=0 healed=0 still_down=0 exit78=0
declare -a DOWN HEALED FAILED

for f in "$LA"/com.spa.*.plist; do
  [ -f "$f" ] || continue
  lbl="$(basename "$f" .plist)"
  if is_retired "$lbl"; then
    # A retired agent should not be running; bootout if a stale plist got loaded.
    launchctl bootout "$GUI/$lbl" >/dev/null 2>&1 && echo "  (retired, booted out: $lbl)"
    continue
  fi
  installed=$((installed+1))
  if launchctl print "$GUI/$lbl" >/dev/null 2>&1; then
    loaded=$((loaded+1))
  else
    # not loaded → bootstrap it (exactly what login does)
    DOWN+=("$lbl")
    if launchctl bootstrap "$GUI" "$f" >/dev/null 2>&1; then
      sleep 1
      if launchctl print "$GUI/$lbl" >/dev/null 2>&1; then
        healed=$((healed+1)); HEALED+=("$lbl")
      else
        still_down=$((still_down+1)); FAILED+=("$lbl")
      fi
    else
      still_down=$((still_down+1)); FAILED+=("$lbl")
    fi
  fi
done

# any exit-78 (the migration regression class) still present?
while read -r pid st lab; do
  [ "$st" = "78" ] && { exit78=$((exit78+1)); echo "  ⚠️ exit-78: $lab"; }
done < <(launchctl list | grep 'com.spa')

echo "  installed=$installed loaded=$loaded healed=$healed still_down=$still_down exit78=$exit78"
[ "${#HEALED[@]}" -gt 0 ] && printf '  healed: %s\n' "${HEALED[*]}"
[ "${#FAILED[@]}" -gt 0 ] && printf '  STILL DOWN (investigate): %s\n' "${FAILED[*]}"

# critical user-facing services
echo "── critical services ──"
ping_code="$(curl -s -m6 -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/api/live/ping 2>/dev/null)"
echo "  apiserver /api/live/ping: ${ping_code:-DOWN}"
bot_st="$(launchctl list | grep -E 'com.spa.telegram_bot\b' | awk '{print $2}')"
echo "  telegram_bot: ${bot_st:-NOT LOADED}"
cf_st="$(launchctl list | grep -c cloudflared)"
echo "  cloudflared tunnel: $([ "$cf_st" -gt 0 ] && echo loaded || echo 'NOT LOADED')"

# Public proof artifacts re-derive (the "verify us" surface — DISASTER_RECOVERY §9b).
# Read-only + advisory: it never mutates the track and never fails the fleet check; it
# just flags if data/rates_desk/ no longer reproduces so you can restore the golden copy.
echo "── proof artifacts (read-only) ──"
PY="/Users/yuriikulieshov/miniconda3/bin/python3"
[ -x "$PY" ] || PY="python3"
if [ -d "$REPO/data/rates_desk" ] && [ -f "$REPO/scripts/verify_spa.py" ]; then
  if "$PY" "$REPO/scripts/verify_spa.py" "$REPO/data/rates_desk/" >/dev/null 2>&1; then
    echo "  verify_spa.py data/rates_desk/: ✅ reproduces"
  else
    echo "  verify_spa.py data/rates_desk/: ⚠️ does NOT reproduce — restore golden copy (DR §5/§9b)"
  fi
else
  echo "  verify_spa.py data/rates_desk/: (skipped — files absent)"
fi

if [ "$still_down" -eq 0 ] && [ "$exit78" -eq 0 ] && [ "$ping_code" = "200" ]; then
  echo "✅ FLEET HEALTHY — all agents loaded, no exit-78, API up."
  exit 0
fi
echo "⚠️ Some items need attention (see above). Re-run, or check scripts/check_agent_before_deploy.sh <name>."
exit 1
