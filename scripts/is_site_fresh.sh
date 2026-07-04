#!/bin/bash
# scripts/is_site_fresh.sh — one-shot, READ-ONLY "can I trust the website right now?" check.
#
# PHASE-11 safe fix (audit stabilization). Answers CORE OBJECTIVE #20 (prevent repeated stale-site
# problems) by comparing the THREE surfaces that must agree:
#   1) LIVE site   earn-defi.com/status  (what the public sees)
#   2) origin/main snapshot  (what Cloudflare Pages SHOULD have built)
#   3) LIVE API    api.earn-defi.com     (freshest backend truth)
#
# It does NOT deploy, push, or change anything. It only reports PASS / STALE / CF-LAG.
# Distinct from scripts/site_freshness_monitor.py (the automated CI Site-Custodian); this is the
# quick human command. Canonical usage lives in PROJECT_CONTROL/15_CANONICAL_COMMANDS.md.
set -uo pipefail

PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w 2>/dev/null)

live=$(curl -s --max-time 10 "https://earn-defi.com/status/?cb=$RANDOM" 2>/dev/null \
        | grep -oE 'st-days"[^>]*>[0-9]+' | grep -oE '[0-9]+$' | head -1)
main=$(curl -s --max-time 10 -H "Authorization: token $PAT" \
        "https://api.github.com/repos/yurii-spa/SPA/contents/landing/src/data/track_snapshot.json?ref=main" 2>/dev/null \
        | python3 -c "import sys,json,base64;print(json.loads(base64.b64decode(json.load(sys.stdin)['content']))['real_track_days'])" 2>/dev/null)
api=$(curl -s --max-time 10 "https://api.earn-defi.com/api/v1/golive" 2>/dev/null \
        | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('evidenced_days') or d.get('real_track_days') or '?')" 2>/dev/null)
apihealth=$(curl -s -o /dev/null -w '%{http_code}' --max-time 8 "https://api.earn-defi.com/api/v1/golive" 2>/dev/null)

echo "site-freshness  live=${live:-?}  main-snapshot=${main:-?}  api=${api:-?}  api-http=${apihealth:-?}"

if [ -z "$live" ] || [ -z "$main" ]; then
  echo "RESULT: UNKNOWN — could not read one surface (network? or the page markup changed)."; exit 2
fi
if [ "$live" = "$main" ]; then
  echo "RESULT: PASS ✅ — live site == origin/main snapshot (${live} days). Site is fresh."; exit 0
elif [ "$live" -lt "$main" ] 2>/dev/null; then
  echo "RESULT: CF-LAG ⚠ — live ($live) is BEHIND origin/main ($main). Cloudflare Pages has not"
  echo "        rebuilt the fresh commit. This is the recurring stale-site cause — the fix is"
  echo "        OWNER-GATED in the Cloudflare Pages dashboard (confirm auto-build-on-push is ON,"
  echo "        the repo is linked, and the build is not failing). Nothing in the repo fixes it."
  exit 1
else
  echo "RESULT: SNAPSHOT-BEHIND ⚠ — live ($live) is AHEAD of main-snapshot ($main): the daily cycle"
  echo "        advanced but the snapshot wasn't regenerated/pushed. Check run_daily_paper_cycle.sh"
  echo "        Step 3 (scripts/deploy_site_snapshot.py) in logs/daily_cycle_*.log."
  exit 1
fi
