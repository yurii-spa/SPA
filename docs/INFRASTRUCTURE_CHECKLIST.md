# SPA Infrastructure Checklist

**Version:** v1.0  
**Updated:** 2026-06-19 (MP-1418)  
**Verification script:** `python3 scripts/verify_infrastructure.py`  

---

## Overview

This checklist tracks the operational infrastructure required for SPA paper-trading
and eventual go-live. All items should be verified before any deployment or go-live event.

---

## 1. Git Hooks

| Item | Status | Command |
|------|--------|---------|
| Pre-commit hooks installed | ☐ | `bash scripts/install_git_hooks.sh` |
| Hooks executable | ☐ | `ls -la .git/hooks/pre-commit` |
| install_git_hooks.sh present | ✅ | `ls scripts/install_git_hooks.sh` |

**Verify:** `python3 scripts/verify_infrastructure.py` → `git_hooks: PASS`

---

## 2. launchd Daemons (macOS)

| Daemon | PList | Status | Logs |
|--------|-------|--------|------|
| Daily cycle (08:00) | `com.spa.daily_cycle.plist` | ☐ | `/tmp/spa_cycle.log` |
| HTTP dashboard | `com.spa.httpserver.plist` | ☐ | Port 8765 |
| Cloudflare tunnel | `com.spa.cloudflared.plist` | ☐ | Public URL |
| Autopush (90 min) | `com.spa.autopush.plist` | ☐ | Run `mp009_fix_launchd.command` |

**Install all:**
```bash
for plist in ~/Documents/SPA_Claude/scripts/com.spa.*.plist; do
    cp "$plist" ~/Library/LaunchAgents/
    launchctl load ~/Library/LaunchAgents/"$(basename $plist)"
done
```

**Verify:**
```bash
launchctl list | grep com.spa
```

---

## 3. Kill Switch

| Item | Status | Location |
|------|--------|---------|
| `spa_core/safety/safeguard.py` | ✅ | Kill-switch implementation |
| `spa_core/safety/live_trading_gate.py` | ✅ | Live trading gate |
| `spa_core/safety/__init__.py` | ✅ | Module init |
| Kill switch armed in cycle_runner | ☐ | Check `cycle_runner.py` |
| Drawdown threshold set (≥5%) | ✅ | `RiskPolicy.max_drawdown_pct = 0.05` |

**Verify:** `python3 scripts/verify_infrastructure.py` → `kill_switch: PASS`

---

## 4. Data Backups / GitHub Push

| Item | Status | Notes |
|------|--------|-------|
| `push_to_github.py` present | ✅ | Manual push tool |
| `auto_push.py` present | ✅ | Automated push (every 90 min) |
| PAT stored in Keychain | ☐ | `bash setup_pat.sh` |
| Autopush daemon installed | ☐ | See Section 2 above |

**Test push:**
```bash
python3 push_to_github.py --files data/paper_trading_status.json \
    --message "Test push" --dry-run
```

---

## 5. Monitoring / Daily Cycle

| Item | Status | Command |
|------|--------|---------|
| `cycle_runner.py` present | ✅ | `spa_core/paper_trading/cycle_runner.py` |
| `gap_monitor.py` present | ✅ | `spa_core/paper_trading/gap_monitor.py` |
| `golive_checker.py` present | ✅ | 26 criteria checker |
| Telegram alert working | ☐ | Check last alert in `data/telegram_alerts.json` |
| GoLiveChecker: data_fresh_48h | ☐ | Run cycle daily |

**Manual cycle run:**
```bash
cd ~/Documents/SPA_Claude
python3 -m spa_core.paper_trading.cycle_runner --verbose
```

---

## 6. Infrastructure Verification Script

| Item | Status | Notes |
|------|--------|-------|
| `scripts/verify_infrastructure.py` | ✅ | Created MP-1418 |
| All check functions defined | ✅ | 8 checks |
| JSON output supported | ✅ | `--json` flag |
| Strict mode supported | ✅ | `--strict` flag (exit 1 on failure) |

**Run:**
```bash
python3 scripts/verify_infrastructure.py
python3 scripts/verify_infrastructure.py --json
python3 scripts/verify_infrastructure.py --strict
```

---

## 7. GoLive Infrastructure Requirements

These items are checked by `spa_core/paper_trading/golive_checker.py`:

| Check Key | Description | Status |
|-----------|-------------|--------|
| `cycle_runner_exists` | cycle_runner.py present | ✅ |
| `multi_strategy_runner` | multi_strategy_runner.py present | ✅ |
| `promotion_engine` | promotion_engine.py present | ✅ |
| `http_server` | HTTP dashboard running on 8765 | ✅ |
| `autopush_installed` | autopush launchd daemon installed | ✅ |
| `safe_tx_builder` | Gnosis Safe TX builder configured | ✅ |
| `gap_monitor_ok` | No gaps in paper-trading track | ✅ |
| `adr022_exists` | ADR-022 (Gnosis Safe multisig) present | ✅ |

---

## 8. Pre-Go-Live Infrastructure Sign-Off

Before activating live trading, verify all items above plus:

- [ ] All 26 GoLiveChecker criteria PASS
- [ ] `data/golive_status.json` → `ready: true` for 7+ consecutive days
- [ ] Gnosis Safe multisig deployed and configured (ADR-022)
- [ ] Real $100K USDC deposited to Gnosis Safe
- [ ] Telegram alerts confirmed working
- [ ] Owner signs off manually

**Infrastructure verified by:** _______________  
**Date:** _______________

---

*Document maintained by SPA Engineering. Auto-verification: `python3 scripts/verify_infrastructure.py`*
