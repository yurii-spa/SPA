# 15 — CANONICAL COMMANDS

**Python:** `/Users/yuriikulieshov/miniconda3/bin/python3`

```bash
# Live state (READ FIRST when asked "what works"):
cat ~/Documents/SPA_Claude/docs/SYSTEM_BRIEFING.md

# Agents (source of truth):
launchctl list | grep spa

# Daily cycle / GoLive / health (manual):
python3 -m spa_core.paper_trading.cycle_runner --verbose   # NEVER against live data/ in dev — use sandbox
python3 -m spa_core.paper_trading.golive_checker
python3 -m spa_core.monitoring.system_health_monitor

# Tests:
python3 -m pytest spa_core/tests/ -q

# Push to GitHub (origin/main, API):
python3 push_to_github_batch.py --files /abs/path/file.py --message "vX.XX: desc"

# SITE FRESHNESS (run before trusting the website / claiming a deploy):
LIVE=$(curl -s https://earn-defi.com/status/ | grep -oE 'st-days"[^>]*>[0-9]+' | grep -oE '[0-9]+$')
PAT=$(security find-generic-password -s GITHUB_PAT_SPA -w)
MAIN=$(curl -s -H "Authorization: token $PAT" \
  "https://api.github.com/repos/yurii-spa/SPA/contents/landing/src/data/track_snapshot.json?ref=main" \
  | python3 -c "import sys,json,base64;print(json.loads(base64.b64decode(json.load(sys.stdin)['content']))['real_track_days'])")
echo "live=$LIVE  main=$MAIN  → equal=fresh; live<main for >30min = CF build lag (owner: CF dashboard)"

# GitHub-latest vs live (deploy sanity):
curl -sI https://earn-defi.com | grep -i server          # expect: cloudflare
curl -s -o /dev/null -w '%{http_code}' https://api.earn-defi.com/api/v1/golive   # expect: 200
```
