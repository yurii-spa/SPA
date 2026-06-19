# SPA Deployment Runbook

**Version:** v1.2  
**Updated:** 2026-06-19 (MP-1417)  
**Applies to:** Local macOS deployment via launchd  

---

## 1. Prerequisites

| Requirement | Check |
|-------------|-------|
| Python 3.10+ | `python3 --version` |
| macOS 13+ (Ventura) | `sw_vers -productVersion` |
| Repo cloned at `~/Documents/SPA_Claude/` | `ls ~/Documents/SPA_Claude/CLAUDE.md` |
| GitHub PAT in Keychain | `security find-generic-password -s GITHUB_PAT_SPA -w` |
| No external Python deps | `pip list` — only stdlib |

---

## 2. Initial Setup

### 2.1 Clone Repository

```bash
git clone https://github.com/<org>/spa.git ~/Documents/SPA_Claude
cd ~/Documents/SPA_Claude
```

### 2.2 Store GitHub PAT

```bash
bash setup_pat.sh
# Follow prompts — PAT stored in macOS Keychain only, never in files
```

See `docs/TOKEN_ROTATION_RUNBOOK.md` for PAT rotation procedures.

### 2.3 Install launchd Daemons

```bash
# Daily cycle (08:00 every day)
cp scripts/com.spa.daily_cycle.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.spa.daily_cycle.plist

# HTTP Dashboard server (port 8765)
cp scripts/com.spa.httpserver.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.spa.httpserver.plist

# Cloudflare tunnel (public access)
cp scripts/com.spa.cloudflared.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.spa.cloudflared.plist

# Autopush (every 90 min) — fix PYTHON_PATH first:
bash mp009_fix_launchd.command
launchctl load ~/Library/LaunchAgents/com.spa.autopush.plist
```

### 2.4 Verify All Daemons Running

```bash
launchctl list | grep com.spa
# Expected: com.spa.daily_cycle, com.spa.httpserver, com.spa.cloudflared, com.spa.autopush
```

---

## 3. Daily Cycle Manual Run

```bash
cd ~/Documents/SPA_Claude
python3 -m spa_core.paper_trading.cycle_runner --verbose
```

**Expected output sequence:**
1. Adapter orchestrator fetches live APY/TVL
2. Multi-strategy runner (S0–S10 tournament)
3. StrategyAllocator computes target allocation
4. RiskPolicy gate — if `approved=False`, cycle stops here
5. Delta > threshold → virtual rebalance trade written to `data/trades.json`
6. Daily yield accrued to positions
7. `data/equity_curve_daily.json` updated
8. GoLiveChecker runs (26 criteria) → `data/golive_status.json`

---

## 4. Log Monitoring

```bash
# Cycle logs
tail -f /tmp/spa_cycle.log
tail -f /tmp/spa_cycle_err.log

# HTTP server
tail -f /tmp/spa_httpserver.log

# Autopush
tail -f /tmp/spa_autopush.log
```

---

## 5. Dashboard Access

- **Local:** http://localhost:8765
- **Remote (tunnel):** Check `data/cloudflared_url.txt` for current public URL

---

## 6. Go-Live Activation

Go-live **must not** be triggered until:
- GoLiveChecker: 26/26 criteria PASS
- ADR-002 criteria met (30 gap-free paper days + manual owner review)
- `data/golive_status.json` shows `ready: true` for 7+ consecutive days

Activation command (requires manual confirmation):
```bash
python3 -m spa_core.golive.activate
# Will prompt: "I CONFIRM LIVE TRADING"
```

---

## 7. Disaster Recovery

See `docs/DISASTER_RECOVERY.md` for full DR procedure v2.

Quick recovery:
```bash
# Restore from last GitHub push
git fetch origin && git reset --hard origin/main

# Restart all daemons
launchctl unload ~/Library/LaunchAgents/com.spa.*.plist
launchctl load ~/Library/LaunchAgents/com.spa.*.plist
```

---

## 8. Secrets Policy

**NEVER** write tokens, keys, or passwords in any file. PAT lives in macOS Keychain only.
If a secret leaks into a file: immediately revoke at github.com/settings/tokens, clean
files, clean git history. See CLAUDE.md §SECRETS POLICY.

---

## 9. Infrastructure Verification

```bash
python3 scripts/verify_infrastructure.py
# Checks: git hooks, launchd plists, kill switch, backups, monitoring
```

---

*Maintained by SPA Engineering. Runbook version must be updated with each infrastructure change.*
