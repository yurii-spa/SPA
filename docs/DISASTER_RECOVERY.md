# SPA Disaster Recovery Playbook — CANONICAL

*Version: 3.0 · Rewritten 2026-06-27 · Owner: Yurii (yuriycooleshov@gmail.com)*

> **THIS IS THE CANONICAL DR DOCUMENT.** All other DR / runbook docs
> (`DR_PROCEDURE_v1.md`, `DR_PROCEDURE_v2.md`, `RUNBOOK.md`,
> `operator_runbook.md`) are **SUPERSEDED** and carry a header pointing here.
> If anything below conflicts with them, **this file wins.**
>
> Every command in this file is **copy-paste runnable today** against the real
> Mac Mini host. No retired agents, no deleted scripts, no wrong ports.
> The drift-guard test `spa_core/tests/test_doc_drift.py` fails CI if a retired
> token is reintroduced here.

---

## DR docs index (single entry point — start here)

Open **this file** for any recovery. The others exist for history or for a
narrow sub-topic; the **SUPERSEDED** ones must **not** be followed for infra
recovery (they reference retired agents / deleted scripts).

| Doc | Status | Use for |
|---|---|---|
| **`DISASTER_RECOVERY.md`** (this file) | ✅ **CANONICAL** | All disaster recovery — reboot, missed cycle, push fail, data loss, agent fix |
| `DR_PROCEDURE_v1.md` | ⛔ SUPERSEDED | History only |
| `DR_PROCEDURE_v2.md` | ⛔ SUPERSEDED (infra) | History; §7–8 fund-level / investor-exit material not yet folded in here |
| `RUNBOOK.md` | ⛔ SUPERSEDED (recovery) | Historical day-to-day-ops context only |
| `operator_runbook.md` | ⛔ SUPERSEDED (severely stale) | History only |
| `TOKEN_ROTATION_RUNBOOK.md` | ✅ active (sub-topic) | PAT rotation detail (referenced from §4) |
| `kill_switch_drill.md` | ✅ active (sub-topic) | Kill-switch drill record |
| `DEPLOYMENT_RUNBOOK.md` / `LIVE_LAUNCH_RUNBOOK.md` | ✅ active (deploy/launch) | Deploy + go-live launch, not disaster recovery |

Live resilience posture (offsite copy / restore drill / fleet-down drill) is
rolled up in `data/resilience_status.json` and surfaced in the **Resilience**
section of `docs/SYSTEM_BRIEFING.md`.

---

## 0. The 5 facts that make recovery correct (read first)

1. **Agents load on LOGIN, not on boot.** SPA agents are **gui-domain**
   LaunchAgents in `~/Library/LaunchAgents/`. After a reboot or OS update you
   must **log in once**; launchd then loads the whole fleet (RunAtLoad fires the
   one-shots, KeepAlive starts the daemons, schedules resume). Auto-login is
   currently **OFF** → one manual login is required after every reboot.

2. **One command confirms + heals the fleet after login:**
   ```bash
   bash ~/Documents/SPA_Claude/scripts/verify_fleet_after_reboot.sh
   ```
   It is read-mostly + idempotent: it only (re)bootstraps agents that aren't
   loaded, boots out any retired agent that lingers, and never mutates the
   go-live track. Output ends in `✅ FLEET HEALTHY` or tells you what to fix.

3. **The installer is `scripts/install_all_agents.sh`** (NOT the deleted
   standalone `install_agents.sh` — that script no longer exists). It is
   idempotent (unload → cp → load per agent) and prints `[OK]/[SKIP]/[FAIL]`.

4. **NEVER revive a RETIRED agent.** See §6. Reviving any of them re-triggers
   the Telegram-409 / duplicate-flood regression that was just fixed.

5. **NEVER run a live cycle against `data/` during recovery.** `cycle_runner`
   without `--live` (and without `SPA_ALLOW_LIVE_WRITE=1`) is fail-CLOSED and
   writes to a sandbox, not the canonical track. An ad-hoc `--live` run can
   corrupt `data/equity_curve_daily.json`. See §7.

---

## 1. Infrastructure map (current reality)

| Service | launchd label | Schedule | Log |
|---|---|---|---|
| Daily paper cycle | `com.spa.daily_cycle` | 08:00 UTC | `logs/launchd_stdout.log` |
| Autopush → GitHub | `com.spa.autopush` | every 90 min | `/tmp/spa_autopush.log` |
| API server (FastAPI/uvicorn) | `com.spa.apiserver` | KeepAlive | `/tmp/spa_api.log` |
| Family Fund cabinet API | `com.spa.familyfund` | KeepAlive | `/tmp/spa_familyfund.log` |
| Dashboard static server | `com.spa.dashboard` | KeepAlive | `/tmp/spa_dashboard.log` |
| Cloudflare tunnel | `com.spa.cloudflared` | KeepAlive | `/tmp/spa_cloudflared.log` |
| Telegram bot (interactive) | `com.spa.telegram_bot` | KeepAlive | `/tmp/spa_telegram_bot.log` |
| Telegram daily digest | `com.spa.digest_daily` | 08:10 UTC | `/tmp/spa_digest_daily.log` |
| Telegram weekly digest | `com.spa.digest_weekly` | Sun 10:00 | `/tmp/spa_digest_weekly.log` |
| Self-heal watchdog | `com.spa.self_heal` | every 5 min | `/tmp/spa_self_heal.log` |
| Threat reactor | `com.spa.threat_reactor` | every 5 min | `/tmp/spa_threat_reactor.log` |
| Watchdog-of-watchdogs | `com.spa.watchdog` | every 10 min | `/tmp/spa_watchdog.log` |
| Agent health monitor | `com.spa.agent_health` | hourly | `/tmp/spa_agent_health.log` |
| System briefing | `com.spa.system_briefing` | every 30 min | `/tmp/spa_system_briefing.log` |

Full live list is always `launchctl list | grep com.spa` — the table is a
snapshot. Source of truth for fleet state: `verify_fleet_after_reboot.sh` and
`docs/SYSTEM_BRIEFING.md`.

### Ports (canonical — do NOT confuse them)

| Port | Owner | Notes |
|---|---|---|
| **8765** | `com.spa.apiserver` (FastAPI/uvicorn) | `api.earn-defi.com` via cloudflared. **Only the apiserver may bind 8765.** |
| **8766** | `com.spa.familyfund` (investor cabinet API) | |
| **8767** | `com.spa.dashboard` (static dashboard) | |

> The legacy stdlib `com.spa.httpserver` is **RETIRED** — it bound 8765 and
> crash-looped on `EADDRINUSE` against the apiserver. Do **not** revive it (§6).

### Constants

- **Python:** `/Users/yuriikulieshov/miniconda3/bin/python3` (always this path).
- **Repo:** `~/Documents/SPA_Claude`, GitHub `yurii-spa/SPA`.
- **PAT:** Keychain service `GITHUB_PAT_SPA` —
  `security find-generic-password -s GITHUB_PAT_SPA -w`.
- **Plist templates:** `scripts/com.spa.*.plist` and `launchd/com.spa.*.plist`.
  All agents run via a **/bin/bash wrapper** and log to **`/tmp/`** (never under
  `~/Documents` — TCC blocks launchd writes there → exit 78). See §8.

---

## 2. Scenario: Mac Mini rebooted / OS updated

**Symptoms:** dashboard down, no fresh data, agents absent from `launchctl list`.

**Recovery (the whole thing is one login + one script):**

```bash
# 1. Log in to the user account once (agents are gui-domain → load on LOGIN).
#    launchd auto-loads every ~/Library/LaunchAgents/com.spa.*.plist at login.

# 2. Confirm + heal the fleet (idempotent, never touches the track):
bash ~/Documents/SPA_Claude/scripts/verify_fleet_after_reboot.sh
#    → "✅ FLEET HEALTHY" or a list of what to fix.

# 3. If some agents are STILL down, reinstall the whole fleet (idempotent):
bash ~/Documents/SPA_Claude/scripts/install_all_agents.sh

# 4. Spot-check the critical user-facing services:
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/api/live/ping   # → 200
launchctl list | grep -E 'com\.spa\.(apiserver|telegram_bot|cloudflared)'
```

The `self_heal` agent (every 5 min) will also revive any resident agent that
didn't come up and recover a missed cycle — but run the verify script so you
don't wait on the next tick.

**Fully-autonomous recovery without a login** is an owner decision (security
trade-off): either enable auto-login, or move the critical KeepAlive daemons
(apiserver/cloudflared/bot) into system-domain LaunchDaemons (boot without
login, needs sudo). Today auto-login is OFF → one login is required.

---

## 3. Scenario: daily cycle didn't run

**Symptoms:** `data/paper_trading_status.json` `last_cycle_ts` > 26 h old; no
fresh commit; `gap_monitor.json` flags a gap; `agent_health` alert.

```bash
cd ~/Documents/SPA_Claude

# 1. Is the agent loaded? What was its last exit?
launchctl list | grep com.spa.daily_cycle      # col 2 = last exit (0 = ok)

# 2. Read the cycle log:
tail -50 logs/launchd_stdout.log

# 3. Recover the gap the SAFE way (deterministic, file-locked, idempotent 1/day).
#    This is what self_heal calls — it does NOT need --live and won't corrupt
#    the track:
/Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.paper_trading.gap_monitor --recover

# 4. Re-trigger the scheduled agent so the next run is on track:
launchctl kickstart -k gui/$(id -u)/com.spa.daily_cycle

# 5. Confirm freshness:
/Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.paper_trading.golive_checker
```

**Do NOT** run `cycle_runner --live` by hand to "catch up" — use
`gap_monitor --recover`. (See §7 on the track-corruption hazard.)

If the agent's `last_exit` is 78 → it's the config/wrapper class of failure; see
§8 (Adding/fixing an agent) — re-bootstrap it through the gate.

---

## 4. Scenario: GitHub push fails (PAT expired / GitHub down)

**Symptoms:** `/tmp/spa_autopush.log` shows 401/403 (PAT) or 50x (GitHub down);
no new commits in `yurii-spa/SPA`.

```bash
cd ~/Documents/SPA_Claude

# 1. Confirm the cause — push manually and read the log:
bash scripts/auto_push.sh
tail -30 /tmp/spa_autopush.log
#    401/403 = PAT expired/revoked;  50x = GitHub outage (SPA keeps running locally).

# 2. PAT check (Keychain is the ONLY source — never a file):
security find-generic-password -s GITHUB_PAT_SPA -w | head -c 8; echo "…"

# 3. If the PAT is bad: the OWNER creates a new fine-grained PAT on GitHub
#    (Contents: Read+write on yurii-spa/SPA) and rotates it into Keychain:
bash ~/Documents/SPA_Claude/setup_pat.sh        # overwrites GITHUB_PAT_SPA
#    Full procedure: docs/TOKEN_ROTATION_RUNBOOK.md

# 4. Re-push the accumulated state:
bash scripts/auto_push.sh
```

SPA trading does **not** depend on GitHub — a GitHub outage only delays the
data mirror. Accumulated commits flush once it returns.

**NEVER embed a PAT in any file** (2026-06-10 incident: a PAT leaked into 90+
files). Keychain only.

---

## 5. Scenario: data corrupted / lost

**Symptoms:** a cycle crashes with `json.JSONDecodeError` / `KeyError`; a
`data/*.json` is empty or garbage.

```bash
cd ~/Documents/SPA_Claude

# 1. Find the damage:
for f in equity_curve_daily paper_trading_status current_positions trades golive_status gap_monitor; do
  /Users/yuriikulieshov/miniconda3/bin/python3 -c "import json;json.load(open('data/${f}.json'));print('OK: ${f}')" 2>&1
done

# 2. Restore the golden copy from GitHub (autopush mirror, ≤ 90 min old):
git fetch origin
git checkout origin/main -- data/equity_curve_daily.json data/paper_trading_status.json \
    data/current_positions.json data/golive_status.json data/gap_monitor.json
#    (or restore everything:  git checkout origin/main -- data/ )

# 3. Fall back to the daily pre-cycle backup snapshots if GitHub is also stale:
ls -lt data/backups/ | head

# 4. Recover the cycle the SAFE way (NOT --live) and confirm:
/Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.paper_trading.gap_monitor --recover
/Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.paper_trading.golive_checker
```

`data/equity_curve_daily.json`, `golive_status.json`,
`paper_evidence_history.json` are the **canonical track snapshots** — restore
them from the GitHub golden copy, never regenerate them with a live cycle.

---

## 6. RETIRED agents — NEVER revive these

These agents are retired. The authoritative set lives in
`spa_core/monitoring/agent_health_monitor.py` → `RETIRED_LABELS`
(`verify_fleet_after_reboot.sh` and `self_heal.py` import / mirror it). Reviving
any of them re-introduces the regression listed:

| Retired agent | Replaced by | Why reviving breaks things |
|---|---|---|
| `com.spa.bot_commands` | `com.spa.telegram_bot` | identical module → two Telegram `getUpdates` long-polls → **409 conflict** |
| `com.spa.httpserver` | `com.spa.apiserver` | bound **:8765** → `EADDRINUSE` crash-loop against the apiserver |
| `com.spa.telegram_daily` | `com.spa.digest_daily` | ran the digest builder directly → **duplicate** daily sends |
| `com.spa.telegram_weekly` | `com.spa.digest_weekly` | duplicate weekly sends |
| `com.spa.morning_digest` | `com.spa.digest_daily` | legacy daily report → **flood** |
| `com.spa.daily-paper-report` | `com.spa.digest_daily` | legacy daily report → **flood** |

If a stale retired plist lingers and got loaded, boot it out:
```bash
launchctl bootout gui/$(id -u)/com.spa.httpserver   # example; substitute the label
```
`verify_fleet_after_reboot.sh` does this automatically.

---

## 7. Track-corruption hazard (recovery-critical)

The canonical go-live track (`data/equity_curve_daily.json` and the evidence
files) anchors on `PAPER_REAL_START` and accrues one **evidenced** bar per day.
It is fragile:

- An ad-hoc `cycle_runner --live` (or `SPA_ALLOW_LIVE_WRITE=1`) run in dev/QA
  **mutates the live track** and has corrupted it before (2026-06-25).
- The runner is **fail-CLOSED**: without `--live` / `SPA_ALLOW_LIVE_WRITE=1`, or
  with an explicit non-canonical `--data-dir` / `SPA_DATA_DIR`, all writes go to
  a sandbox and the canonical track is provably untouched.

**Rules during any recovery:**
- To advance the track: only the scheduled `com.spa.daily_cycle`, or
  `gap_monitor --recover` (deterministic, idempotent 1/day).
- To test/inspect: run with a sandbox data dir, never `--live`:
  ```bash
  /Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.paper_trading.cycle_runner \
      --verbose --data-dir /tmp/spa_recovery_sandbox
  ```
- To restore a damaged track: `git checkout origin/main -- data/…` (§5),
  never regenerate it live.

---

## 8. Adding / fixing an agent (the deploy gate)

Before `launchctl bootstrap`/`load` of any new or changed plist, ALWAYS run the
gate (CLAUDE.md FORBIDDEN rule #11):

```bash
bash ~/Documents/SPA_Claude/scripts/check_agent_before_deploy.sh <name>
#    e.g.  check_agent_before_deploy.sh watchdog
#    Runs the command once (SANDBOXED — strips --live, can't touch the track),
#    asserts exit 0 + a log was written + the canonical track is byte-identical,
#    THEN bootout → bootstrap → kickstart and asserts the loaded exit != 78.
```

Deploy **≤ 3 agents at a time**. Every plist must:
- run via a **/bin/bash wrapper** (`scripts/agent_<name>.sh` →
  `agent_template.sh`), **never** a direct `python3 -m` / miniconda-python in
  `ProgramArguments` — launchd can't exec miniconda-python directly → **exit 78
  EX_CONFIG** (the program never even starts; no log is written).
- point `StandardOutPath`/`StandardErrorPath` at **`/tmp/`**, never under
  `~/Documents` — TCC blocks launchd writes there → also **exit 78**.

If you see `exit 78` in `launchctl list | grep com.spa`, it's one of the two
causes above. `verify_fleet_after_reboot.sh` reports any exit-78 agents.

---

## 9. Self-heal & circuit-breaker behaviour (what auto-recovers)

`com.spa.self_heal` (every 5 min, deterministic, stdlib, LLM-forbidden) actively
recovers — the other monitors only alert:

- **Revives** an expected resident agent (KeepAlive daemon / StartInterval
  guardian) that's missing from `launchctl list`. Calendar/one-time agents that
  correctly exit between runs are **not** churned.
- **Kickstarts** a down server (loaded but PID 0) and any local port that isn't
  listening (probes 8765/8766/8767).
- **Recovers a missed cycle** (`gap_monitor --recover`) when the last cycle is
  > 28 h old.
- **Circuit breaker:** an agent revived > 5 times/hour is treated as
  crash-looping — self_heal **stops reviving it** and alerts instead (so a
  flooding bot can't be revived into a loop). `com.spa.watchdog` (every 10 min)
  revives self_heal / threat_reactor themselves if they die.

State: `data/self_heal_status.json`, `data/self_heal_revivals.json`. `healthy`
is true only when no failures/breakers AND every residency-required agent is
resident.

---

## 10. Universal diagnostics

```bash
# Fleet snapshot:
launchctl list | grep com.spa | sort

# Post-reboot confirm + heal:
bash ~/Documents/SPA_Claude/scripts/verify_fleet_after_reboot.sh

# Reinstall the whole fleet (idempotent):
bash ~/Documents/SPA_Claude/scripts/install_all_agents.sh

# Self-heal dry-run (shows what it WOULD do, mutates nothing):
/Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.monitoring.self_heal --dry-run

# Agent health (compute + write, no Telegram):
/Users/yuriikulieshov/miniconda3/bin/python3 -m spa_core.monitoring.agent_health_monitor --check

# Critical service ping:
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8765/api/live/ping   # → 200

# Force a push:
bash ~/Documents/SPA_Claude/scripts/auto_push.sh
```

---

*Canonical DR doc. Supersedes DR_PROCEDURE_v1.md, DR_PROCEDURE_v2.md, RUNBOOK.md,
operator_runbook.md. Drift-guarded by `spa_core/tests/test_doc_drift.py`
(retired tokens sourced from `agent_health_monitor.RETIRED_LABELS`).*
