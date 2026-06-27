> ⚠️ **SUPERSEDED for disaster recovery.** This operations runbook is **STALE**
> (retired `com.spa.httpserver`, 26-criteria go-live, pre-rebuild agent list).
> For recovery, use the **canonical**
> **[`DISASTER_RECOVERY.md`](DISASTER_RECOVERY.md)**. This file is retained for
> historical day-to-day-ops context only.

---

# SPA Operations Runbook

**Version:** 1.0  
**Last Updated:** 2026-06-20  
**Audience:** Fund Manager / SPA System Operator  
**Status:** Active — paper trading period (go-live target 2026-08-01)

---

## Overview

This runbook covers day-to-day and emergency operations for the SPA (Smart
Passive Aggregator) system. SPA runs as a set of launchd daemons on macOS,
executing a daily DeFi yield optimisation cycle against a virtual portfolio of
$100,000 USDC. The daily cycle fires at 08:00 local time via
`com.spa.daily_cycle`. Logs are written to `/tmp/spa_cycle.log` and
`/tmp/spa_cycle_err.log`.

**Critical rule:** No real capital is at risk during the paper-trading period.
Do not activate live trading without completing the ADR-002 go-live checklist
and obtaining a GoLive score of READY.

---

## Daily Operations

### Morning Check (08:00 local time, after cycle fires)

1. **Verify launchd health**

   ```bash
   launchctl list | grep spa
   ```

   Expected output: entries for `com.spa.daily_cycle`, `com.spa.httpserver`,
   `com.spa.cloudflared`. All should show a PID (non-zero) or last exit code 0.
   If any daemon shows a non-zero last exit, proceed to the "Daemon Restart"
   procedure below.

2. **Check cycle log for errors**

   ```bash
   tail -50 /tmp/spa_cycle.log
   tail -20 /tmp/spa_cycle_err.log
   ```

   Look for any lines containing `ERROR`, `CRITICAL`, or `Traceback`. A clean
   run ends with `=== cycle complete ===`.

3. **Review Telegram morning digest**

   The daily cycle sends a Telegram digest via `spa_core/alerts/`. It summarises:
   current equity, 7-day return, active strategy, top APY source, and any
   RiskPolicy block. If no Telegram message arrived, check
   `data/paper_trading_status.json` manually.

4. **Check GoLive score**

   ```bash
   python3 -m spa_core.paper_trading.golive_checker
   ```

   Review `data/golive_status.json`. The score should match or exceed the
   previous day. If criteria regress (e.g. `gap_monitor` fails), investigate
   immediately — a missed day breaks the 30-day continuity requirement (ADR-002).

5. **Review APY drift alerts**

   ```bash
   cat data/apy_data.json | python3 -c "import sys,json; d=json.load(sys.stdin); [print(k,v) for k,v in d.items() if isinstance(v,dict)]"
   ```

   If any T1 protocol shows APY deviation > 20% from 7-day mean, cross-check
   on DeFiLlama directly: `https://defillama.com/yields`.

---

### Weekly Review (each Monday)

1. **Run tournament evaluation**

   ```bash
   python3 -m spa_core.paper_trading.multi_strategy_runner --verbose
   ```

   Compare rankings in `data/tournament_results.json` to the previous week.
   Strategies that enter the bottom 2 for 7+ consecutive days enter probation
   per ADR-040.

2. **Review promotion candidates**

   Run the promotion engine:

   ```bash
   python3 promotion_engine.py
   ```

   Any strategies with `advisory_promoted: true` in the output are candidates
   for the next paper-trading window. Document findings in KANBAN.json under
   the relevant MP item.

3. **Update evidence progress**

   GoLive evidence accumulates daily. After each week, verify the evidence
   score in `data/golive_status.json` is increasing. Run:

   ```bash
   python3 -m spa_core.paper_trading.golive_checker
   cat data/golive_status.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('Score:', d.get('score'), 'READY:', d.get('ready'))"
   ```

4. **Check adapter health**

   ```bash
   python3 -c "
   import json, os
   path = 'data/adapter_status.json'
   if os.path.exists(path):
       d = json.load(open(path))
       for k,v in d.items(): print(k, '->', v)
   else:
       print('adapter_status.json not found (execution domain only)')
   "
   ```

   Alternatively, check the DeFiLlama feed directly:

   ```bash
   python3 -c "from spa_core.adapters.defillama_feed import DeFiLlamaFeed; f=DeFiLlamaFeed(); print(f.get_yields())"
   ```

5. **Review circuit breaker state**

   ```bash
   cat data/circuit_breaker_state.json 2>/dev/null || echo "No circuit breaker events"
   ```

   If level is ORANGE or above, escalate immediately (see Emergency Procedures).

6. **Review risk policy blocks**

   ```bash
   python3 -c "import json; d=json.load(open('data/risk_policy_blocks.json')); print(f'{len(d)} blocks in ring-buffer'); [print(b.get('reason','?'), b.get('ts','')) for b in d[-5:]]"
   ```

---

## Emergency Procedures

### Circuit Breaker Triggered

If portfolio drawdown exceeds 2% (YELLOW level) or higher (per ADR-039):

1. **Do NOT attempt a manual rebalance.** The circuit breaker restricts
   allocations for a reason. Overriding it requires fund manager sign-off and
   an ADR annotation.

2. **Assess current state:**

   ```bash
   cat data/circuit_breaker_state.json
   cat data/equity_curve_daily.json | python3 -c "
   import sys,json; curve=json.load(sys.stdin)
   recent=curve[-7:]; [print(r['date'], r['equity']) for r in recent]
   "
   ```

3. **Review positions:**

   ```bash
   cat data/current_positions.json | python3 -m json.tool | head -60
   ```

4. **For RED (drawdown ≥ 4%) or BLACK (drawdown ≥ 5%):** All T2/T3 positions
   are automatically zeroed by the circuit breaker. Confirm:

   ```bash
   python3 -m spa_core.paper_trading.cycle_runner --verbose
   ```

5. **Consult ADR-039** for recovery conditions before re-enabling full
   allocation.

---

### Data Source Outage (DeFiLlama Unavailable)

If DeFiLlama is unreachable or returns invalid data:

1. The system falls back to `FALLBACK_APY` constants defined in
   `spa_core/adapters/config.py`. Check that fallbacks are still reasonable:

   ```bash
   grep FALLBACK_APY spa_core/adapters/config.py
   ```

2. Check data freshness:

   ```bash
   python3 -c "
   import os, json, datetime
   for fname in ['data/apy_data.json']:
       if os.path.exists(fname):
           mtime = os.path.getmtime(fname)
           age_h = (datetime.datetime.now().timestamp() - mtime) / 3600
           print(f'{fname}: {age_h:.1f}h old')
   "
   ```

   If `apy_data.json` is > 48 hours old, the `data_fresh_48h` GoLive criterion
   will fail. Investigate DeFiLlama status and manually trigger a cycle once
   data is available.

3. All T1 adapters (Aave V3, Compound V3, Morpho Steakhouse) continue with
   cached APY during outages. The cycle will still run and yield will still
   accrue on existing positions.

4. If DeFiLlama is down for > 24 hours, open a manual note in KANBAN.json
   and check https://status.defillama.com.

---

### Daemon Restart (launchd)

If `launchctl list | grep spa` shows a daemon that is not running:

```bash
# Unload and reload the daemon
launchctl bootout gui/$(id -u) ~/Library/LaunchAgents/com.spa.daily_cycle.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.spa.daily_cycle.plist

# Verify
launchctl list | grep spa
```

For `com.spa.autopush`: see `CURRENT_STATE.md` — this daemon requires the
`mp009_fix_launchd.command` fix before loading.

---

### Gap in Daily Cycle (GoLive Continuity Risk)

If `gap_monitor.json` shows a gap (missed cycle day):

1. Check the gap:

   ```bash
   python3 -m spa_core.paper_trading.gap_monitor
   cat data/gap_monitor.json | python3 -c "import sys,json; d=json.load(sys.stdin); print('Gaps:', d.get('gaps',[]))"
   ```

2. A single missed day resets the 30-day continuity counter for ADR-002.
   The go-live date shifts accordingly. Update the target date in CLAUDE.md and
   KANBAN.json.

3. If the gap was caused by a daemon failure, address the daemon issue first,
   then run the cycle manually:

   ```bash
   python3 -m spa_core.paper_trading.cycle_runner --verbose
   ```

---

### Live Trading Gate Protocol

**The live trading gate is LOCKED by default and MUST remain locked during
the paper-trading period.**

The gate is implemented in `spa_core/golive/activate.py`. Activation requires:

1. GoLive score READY (26/26 criteria pass, sustained ≥ 7 days — ADR-002).
2. `gap_monitor.json` shows 30 consecutive days without gaps.
3. Manual review by fund manager (documented in KANBAN.json).
4. Execution of `spa_core/golive/activate.py` with explicit confirmation
   string `"I CONFIRM LIVE TRADING"` typed interactively.

**Do not attempt to activate live trading before 2026-08-01.**

---

## Monitoring Reference

| Channel        | Command / URL                                   | Purpose                        |
|----------------|-------------------------------------------------|--------------------------------|
| Telegram       | `/status`, `/golive`, `/apy`, `/evidence`       | Real-time alerts               |
| Local dashboard| `http://localhost:8765`                         | Investor portal (Family Fund)  |
| Public tunnel  | `earn-defi.com/dashboard` (when cloudflared up) | External dashboard             |
| Cycle log      | `/tmp/spa_cycle.log`                            | Full daily cycle output        |
| Error log      | `/tmp/spa_cycle_err.log`                        | Stderr from cycle              |
| GoLive status  | `data/golive_status.json`                       | 26 criteria + score            |
| Gap monitor    | `data/gap_monitor.json`                         | Continuity tracker             |
| Risk blocks    | `data/risk_policy_blocks.json`                  | RiskPolicy gate blocks         |
| Tournament     | `data/tournament_results.json`                  | Strategy rankings              |

---

## Push to GitHub

After each sprint or significant change:

```bash
# Use the sprint-specific push script
bash scripts/push_v{VERSION}.sh

# Or push manually
python3 push_to_github.py \
  --files /abs/path/to/file.py /abs/path/to/other.json \
  --message "Sprint vX.Y — description"
```

**SECRETS POLICY:** Never embed PAT tokens in push scripts or generated files.
The PAT is read from macOS Keychain at runtime:
`security find-generic-password -s GITHUB_PAT_SPA -w`

For PAT rotation: `bash setup_pat.sh` and see `docs/TOKEN_ROTATION_RUNBOOK.md`.

---

## Contact & Escalation

| Role              | Contact                     |
|-------------------|-----------------------------|
| Fund Manager      | Yurii Kulieshov             |
| Family Fund Portal| `http://localhost:8765`     |
| Compliance Docs   | `docs/COMPLIANCE_POLICY.md` |
| Disaster Recovery | `DR_PROCEDURE_v2.md`        |

---

*Maintained by: SPA Engineering. See MASTER_PLAN_v1.md for strategic context.*
