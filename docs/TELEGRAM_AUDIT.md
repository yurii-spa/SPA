# Telegram Notification Audit — 2026-06-18

**Symptom:** Telegram sending messages every ~30 minutes.  
**Expected:** Once daily + critical events only.  
**Status:** FIXED — 3 bugs identified and patched.

---

## Root Causes

### Bug #1 — PRIMARY: `com.spa.daily_cycle.plist` ran cycle_runner every 30 minutes

**File:** `scripts/com.spa.daily_cycle.plist`  
**Before:** `<key>StartInterval</key> <integer>1800</integer>` (every 30 min)  
**After:** `<key>StartCalendarInterval</key> Hour=8, Minute=0` (daily at 08:00)

`CLAUDE.md` has always documented "ежедневно 08:00" but the plist was wrong —
`StartInterval 1800` means every 1800 seconds = every **30 minutes**.

`cycle_runner` calls `_run_cycle_alerts()` at the end of every run. That
function sends three alert types. Two of them had no dedup:

| Alert | Dedup before fix | Fires when |
|---|---|---|
| `send_daily_summary` | ✅ `_already_sent_today` | Always — but guarded |
| `send_red_flag` | ❌ **NONE** | `red_flags.json` non-empty |
| `send_gap_alert` | ❌ **NONE** | `gap_monitor.json` gap_detected=true |

With a 30-min cycle and no dedup on red_flag / gap_alert, any time
`red_flags.json` had content (which is normal — the red_flag_monitor runs
every 5 min and writes flags), `send_red_flag` fired every 30 minutes.

---

### Bug #2 — `send_red_flag` and `send_gap_alert` had no dedup

**File:** `spa_core/alerts/alert_manager.py`

`send_daily_summary`, `send_weekly_report`, and `send_monthly_report` all
call `_already_sent_today()` before sending. `send_red_flag` and
`send_gap_alert` did not. They sent unconditionally on every cycle_runner
invocation when conditions were met.

---

### Bug #3 — `AlertDispatcher` dedup state was in-memory only

**File:** `spa_core/alerts/alert_dispatcher.py`

`AlertDispatcher` has a `cooldown_seconds=300` parameter and a
`suppress_duplicates` flag. The dedup is tracked in
`self._title_last_sent: Dict[str, float]` — **in-memory only**.

Monitors like `peg_monitor` run every 5 minutes via launchd
(`StartInterval 300`). Each run is a **new process** → new
`AlertDispatcher()` instance → `_title_last_sent` is empty → the 300-second
cooldown is never applied.

Additionally, `peg_monitor` was creating `AlertDispatcher()` with the
defaults (`suppress_duplicates=False`), meaning dedup was **disabled** even
within a single run.

Combined effect: a CRITICAL peg deviation would fire a Telegram alert every
5 minutes.

---

## Files Modified

| File | Change |
|---|---|
| `scripts/com.spa.daily_cycle.plist` | **StartInterval 1800 → StartCalendarInterval 08:00** |
| `spa_core/alerts/alert_manager.py` | Added `_already_sent_today` / `_mark_sent_today` dedup to `send_red_flag` and `send_gap_alert` |
| `spa_core/alerts/alert_dispatcher.py` | Added disk-persisted dedup state (`alert_dispatcher_dedup.json`); new `dedup_state_path` parameter; `_load_dedup_state` / `_save_dedup_state` methods |
| `spa_core/monitoring/peg_monitor.py` | Changed `AlertDispatcher()` to `AlertDispatcher(suppress_duplicates=True, cooldown_seconds=3600)` |
| `scripts/run_health_check.py` | Wrapped Telegram send with `TelegramManager` (1h cooldown for WARNING, bypass for CRITICAL) |
| `spa_core/alerts/telegram_manager.py` | **NEW** — centralized manager with disk-persisted cooldowns |
| `tests/test_telegram_manager.py` | **NEW** — 16 unit tests (all passing) |

---

## New Architecture

```
Telegram notification senders:
────────────────────────────────────────────────────────────────

DAILY (once at 08:00 — from cycle_runner via daily_cycle launchd)
  cycle_runner._run_cycle_alerts()
    ├── alert_manager.send_daily_summary()   → dedup: _already_sent_today("daily_summary")
    ├── alert_manager.send_red_flag()        → dedup: _already_sent_today("red_flag")  [FIXED]
    └── alert_manager.send_gap_alert()       → dedup: _already_sent_today("gap_alert") [FIXED]

DAILY (once at 09:00 — from daily-paper-report launchd)
  scripts/daily_paper_report.py             → no cooldown needed (StartCalendarInterval)

WEEKLY/MONTHLY (from cycle_runner on Mon / 1st)
  alert_manager.send_weekly_report()        → dedup: _already_sent_today("weekly_report")
  alert_manager.send_monthly_report()       → dedup: _already_sent_today("monthly_report")

THRESHOLD ALERTS (from 5-min monitors)
  peg_monitor → AlertDispatcher(suppress_duplicates=True, cooldown_seconds=3600)
    → dedup state persisted to data/alert_dispatcher_dedup.json   [FIXED]

  uptime_monitor → _process_agent_alerts()
    → dedup state persisted to data/uptime_prev_state.json        [was already OK]

  cycle_gap_monitor → _should_send_alert()
    → dedup state persisted to data/cycle_gap_state.json          [was already OK]

  run_health_check → TelegramManager(category="alert", cooldown=1h)
    → dedup state persisted to data/telegram_cooldowns.json       [FIXED]

P0 ALERTS (always send, no cooldown)
  TelegramManager.send(category="p0")      → bypass all cooldown checks
  Examples: kill-switch, gap > 26h, API down > 2h

SUPPRESSED
  TelegramManager.send(category="debug")   → /dev/null in production
  cycle_health_monitor                     → writes data only, never sends Telegram
  portfolio_monitor                        → writes data only, never sends Telegram
  analytics/* (except telegram_daily_digest) → writes data only, no Telegram
```

---

## Before/After: What Fires When

| Notification | Before fix | After fix |
|---|---|---|
| Daily portfolio summary | 1×/day ✅ (had dedup) | 1×/day ✅ |
| Red-flag digest | Every 30 min ❌ | 1×/day ✅ |
| Gap alert | Every 30 min ❌ | 1×/day ✅ |
| Daily paper report | 1×/day at 09:00 ✅ | 1×/day at 09:00 ✅ |
| Peg CRITICAL alert | Every 5 min ❌ | Max 1×/hour ✅ |
| Health WARNING | Unlimited ❌ | Max 1×/hour ✅ |
| Health CRITICAL | Unlimited ❌ | Always (P0 bypass) ✅ |
| Agent down alert | Max 1×/hour ✅ (uptime_monitor) | Max 1×/hour ✅ |
| Kill-switch | On cycle (daily) ✅ | On cycle + P0 bypass ✅ |
| debug messages | Sent ❌ | Suppressed in production ✅ |

---

## New Files

### `spa_core/alerts/telegram_manager.py`

Centralized manager with disk-persisted cooldowns.

```python
from spa_core.alerts.telegram_manager import TelegramManager

mgr = TelegramManager()
mgr.send("🚨 Kill-switch triggered", title="kill_switch", category="p0")   # always sends
mgr.send("Daily digest", title="daily_summary", category="daily")           # 23h cooldown
mgr.send("Peg deviation", title="peg_critical", category="alert")           # 1h cooldown
mgr.send("Debug info",   title="debug_xyz",   category="debug")             # suppressed
```

Categories and their default cooldowns:

| Category | Cooldown | Use case |
|---|---|---|
| `daily` | 23 h | Daily reports |
| `milestone` | 4 h | GoLive pass-count changes |
| `alert` | 1 h | Risk/peg/red-flag alerts |
| `p0` | None (always sends) | Kill-switch, gap, infra down |
| `debug` | Suppressed | Dev logs — never production |

State persisted to: `data/telegram_cooldowns.json`

### `data/alert_dispatcher_dedup.json` (auto-created)

Disk-persisted dedup state for `AlertDispatcher`. Previously in-memory only,
causing the 5-min monitors to reset their cooldown on every process restart.

---

## Launchd Reload Required

After deploying these changes, reload the daily_cycle agent on the Mac:

```bash
# Unload old (30-min) agent
launchctl unload ~/Library/LaunchAgents/com.spa.daily_cycle.plist

# Copy updated plist
cp /Users/yuriikulieshov/Documents/SPA_Claude/scripts/com.spa.daily_cycle.plist \
   ~/Library/LaunchAgents/com.spa.daily_cycle.plist

# Load new (daily 08:00) agent
launchctl load ~/Library/LaunchAgents/com.spa.daily_cycle.plist

# Verify
launchctl list | grep daily_cycle
```

> NOTE: Do NOT restart other agents — only `com.spa.daily_cycle` changed its
> schedule. The other agents (peg_monitor, uptime_monitor, etc.) will pick up
> the code changes automatically on their next run since they restart every 5 min.

---

## Test Coverage

`tests/test_telegram_manager.py` — 16 tests, all passing:

- Cooldown suppresses second identical send
- Cooldown persists across process restarts (separate manager instances)
- Expired cooldown allows resend
- P0 bypasses cooldown — sends twice without suppression
- `is_in_cooldown` returns False for P0
- debug suppressed in production, allowed in non-production
- State file written atomically after successful send
- State file NOT written on failed send or cooldown suppression
- `cooldown_override_hours=0` forces send even within cooldown
- Category default values: p0=0, debug<0, daily≥22h, alert≥30min

Run: `python3 -m pytest tests/test_telegram_manager.py -v`
