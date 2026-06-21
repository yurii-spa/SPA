# SYSTEM_HEALTH_MONITOR — Implementation Spec

> **Module:** `spa_core/monitoring/system_health_monitor.py`
> **Schedule:** launchd `com.spa.system_health`, twice daily at **06:00 + 18:00** local.
> **Author:** Systems Architecture · **Status:** ready for implementation · **Version:** 1.0

## 0. Scope & relationship to the hourly monitor

`agent_health_monitor.py` (hourly, `com.spa.agent_health`) answers **"are the processes
alive?"** — launchd load state, PID for always-on servers, `LastExitStatus`, log freshness
derived from each plist schedule, plus a few coarse system-file age checks.

This monitor answers a different question: **"is the system producing correct results
end-to-end?"** It is *semantic* / *outcome* monitoring, not liveness monitoring.

**Non-duplication contract:** this module MUST NOT re-check launchd load state, PIDs,
`LastExitStatus`, plist parseability, or per-agent log freshness. Those belong to the
hourly monitor. The one deliberate overlap — "did the daily cycle run today?" — is
evaluated here by **outcome** (last equity-curve date), not by process state.

### House rules (inherited, non-negotiable — per CLAUDE.md)
- **stdlib only.** No external deps. Network via `urllib.request`.
- **Atomic writes only** via `spa_core.utils.atomic.atomic_save(data, path)`.
- **Fail-safe:** `run()` never raises; process always `exit 0`. Every check is wrapped;
  a check that throws becomes a `WARNING` result with `error=<repr>`, never aborts the run.
- **Read-only** w.r.t. allocator / risk / execution domains. Never writes any file except
  `data/system_health.json` (+ tmp). Never imports `execution/`, `feed_health/`, risk agents
  for mutation. Kill-switch is invoked **`--dry-run` only**.
- **LLM FORBIDDEN** (monitoring is in `LLM_FORBIDDEN_AGENTS`). No model calls anywhere.
- **Telegram** via `from spa_core.alerts.telegram_client import _post_message`
  (`{"text":…, "parse_mode":"HTML"}`), mirroring the hourly monitor.

---

## 1. Severity model

Three levels, ordered. Roll-up = max severity across all emitted check results.

| Level | Meaning | Triggers paging |
|---|---|---|
| `CRITICAL` | System is producing wrong/dangerous results, or a money-adjacent safety gate is broken. Requires human action now. | **Immediate** Telegram |
| `WARNING` | Degraded or drifting; not yet harmful. Investigate within a day. | 12h summary only |
| `INFO` | Observation / trend datapoint. No action. | 12h summary only |

A fourth internal sentinel `SKIPPED` is recorded (not a severity) when a check is skipped
because an upstream dependency failed — see §3. `SKIPPED` never raises roll-up severity but
is surfaced in the summary so silent gaps are visible.

### 1.1 Severity matrix (per check)

Each row is one `CheckResult`. `id` is stable (used in the dedup fingerprint).

#### DOMAIN 1 — Data Pipeline Integrity
| id | Condition → severity |
|---|---|
| `d1.equity.exists` | file missing/unparseable → **CRITICAL** |
| `d1.equity.count` | `summary.num_days` < expected track days (see §4.1) → **WARNING** |
| `d1.equity.range` | any `close_equity` outside **$99,000–$110,000** → **CRITICAL** (capital corruption) |
| `d1.equity.nan` | any non-finite (`NaN`/`inf`) in equity series → **CRITICAL** |
| `d1.equity.dates` | dates not strictly ascending / duplicate / gap >1 calendar day mid-series → **WARNING** |
| `d1.adapter.present` | any expected adapter (§4.2) absent from `adapters` → **CRITICAL** |
| `d1.adapter.apy_range` | any adapter `apy` outside **0.5%–25%** → **WARNING** |
| `d1.adapter.apy_none` | any adapter `apy` is `None`/missing → **WARNING** (single) / **CRITICAL** if ≥3 |
| `d1.tournament.demo` | `is_demo != false` in tournament file → **CRITICAL** |
| `d1.tournament.populated` | zero strategies present, or no valid `winner` → **WARNING** |
| `d1.status.demo` | `paper_trading_status.is_demo != false` → **CRITICAL** |
| `d1.status.equity` | status equity outside $99K–$110K → **CRITICAL** |
| `d1.status.fresh` | `last_updated` age > **26h** → **WARNING** |
| `d1.golive.count` | `passed` decreased vs previous run (regression) → **WARNING**; `passed`==`total` → **INFO** |

#### DOMAIN 2 — Protocol Connectivity (spot-check, network)
| id | Condition → severity |
|---|---|
| `d2.defillama.reach` | DeFiLlama unreachable/timeout → **WARNING** (never CRITICAL — external) |
| `d2.defillama.deviation` | stored adapter APY deviates **>50%** from live for a sampled pool → **WARNING** |

#### DOMAIN 3 — Strategy Execution Quality
| id | Condition → severity |
|---|---|
| `d3.cycle.ran_today` | last equity date < today (cycle didn't run) → **CRITICAL** if ≥2 days stale, else **WARNING** |
| `d3.tournament.differentiated` | all strategy APYs identical (variance≈0) → **WARNING** (engine likely stuck) |
| `d3.alloc.cap` | any single allocation weight > **30%** → **WARNING** (Kelly/cap drift; note RiskPolicy T1 cap is 40% — 30% is the *monitor* tripwire) |
| `d3.equity.trend7` | 7-day trend classification → **INFO** (growing/flat); **WARNING** if declining beyond −1.0% over 7d |

#### DOMAIN 4 — External Services (network)
| id | Condition → severity |
|---|---|
| `d4.earndefi` | `https://earn-defi.com` not HTTP 200 within 10s → **WARNING** |
| `d4.github_raw` | `raw.githubusercontent.com/.../data/adapter_status.json` unreachable → **WARNING** |
| `d4.github_rate` | GitHub API `X-RateLimit-Remaining` ≤ **100** → **WARNING** |
| `d4.local_api` | local `http://127.0.0.1:8765/` no response → **WARNING** |

#### DOMAIN 5 — Code Integrity (subprocess + fs)
| id | Condition → severity |
|---|---|
| `d5.import.adapters` | any T1 adapter import fails in clean subprocess → **CRITICAL** |
| `d5.import.cycle_runner` | `cycle_runner` import fails → **CRITICAL** |
| `d5.security.secrets` | new untracked file matching `*token*\|*secret*\|*key*\|*password*` → **CRITICAL** |

#### DOMAIN 6 — Financial Risk Gates
| id | Condition → severity |
|---|---|
| `d6.t2.cap` | T2 concentration > **50%** cap → **CRITICAL** (ADR-019 breach) |
| `d6.health` | portfolio health score < **70** → **CRITICAL** |
| `d6.red_flags` | any `red_flags[*].severity == CRITICAL` → **CRITICAL** |
| `d6.killswitch` | kill-switch `--dry-run` does not respond correctly / errors → **CRITICAL** |

#### DOMAIN 7 — Operational Hygiene
| id | Condition → severity |
|---|---|
| `d7.kanban.stale` | any task `in_progress` > **7 days** → **WARNING** |
| `d7.logs.size` | total `/tmp/spa_*.log` > **500MB** → **WARNING** |
| `d7.scripts.clutter` | > **25** non-archived `push_*` scripts in repo root → **INFO** |

---

## 2. Check dependency graph (skip logic)

A check is **SKIPPED** (not run, recorded as `SKIPPED`, excluded from severity roll-up but
listed in summary) when its upstream prerequisite failed. This prevents cascade noise (one
missing file → 10 spurious CRITICALs).

```
                       ┌─────────────────────────────────────────┐
                       │ PRELUDE (always runs, no deps)           │
                       │  • locate data dir, load previous health │
                       │  • git status snapshot (for d5/d7)       │
                       └─────────────────────────────────────────┘

D1 file-load gates downstream semantic checks:
  d1.equity.exists ──FAIL──▶ skip d1.equity.{count,range,nan,dates}, d3.cycle.ran_today,
                                  d3.equity.trend7
  d1.adapter.present(file load) ──FAIL──▶ skip d1.adapter.{apy_range,apy_none},
                                  d2.defillama.deviation, d6.t2.cap
  d1.tournament load ──FAIL──▶ skip d1.tournament.*, d3.tournament.differentiated, d3.alloc.cap

D2 network root gate:
  d2.defillama.reach ──FAIL──▶ skip d2.defillama.deviation   (can't compare to unreachable live)

D4 each external check is INDEPENDENT (no skip chaining) — one down service must not mask others.

D5 import gate:
  d5.import.cycle_runner ──FAIL──▶ does NOT skip adapters (independent imports);
                                   both feed roll-up independently.

D6 source gates:
  red_flags.json load FAIL ──▶ d6.red_flags → WARNING("unreadable"), do not skip others.
  portfolio health source FAIL ──▶ d6.health → WARNING("no score"), not CRITICAL (absence ≠ breach).
```

**Rule:** *absence of evidence* downgrades to WARNING; *evidence of breach* is CRITICAL.
A check may only emit CRITICAL when it positively read a bad value, never on a load failure
of its own source (load failure → WARNING + `error`), except D1 capital/demo files whose
very absence is itself a CRITICAL data-integrity failure (`d1.equity.exists`, demo flags).

---

## 3. Execution model & time budget

Domains run **sequentially** in id order (1→7) for deterministic output, but the two
**network domains (2 & 4)** dispatch their HTTP calls **concurrently** inside the domain via
`concurrent.futures.ThreadPoolExecutor(max_workers=5)`, each call hard-capped by
`urllib` `timeout=`. No domain may exceed its budget; a domain-level wall-clock guard marks
any unfinished check `SKIPPED("budget")`.

| Domain | Budget | Dominant cost |
|---|---|---|
| 1 Data Pipeline | 5s | local JSON parse |
| 2 Connectivity | 20s | 3–5 DeFiLlama calls (10s timeout each, parallel) |
| 3 Strategy Quality | 3s | local compute |
| 4 External Services | 25s | 4 HTTP probes (10s timeout, parallel) |
| 5 Code Integrity | 30s | 3–4 subprocess imports (cold interpreter) |
| 6 Risk Gates | 15s | kill-switch `--dry-run` subprocess |
| 7 Hygiene | 5s | fs walk + git |
| **Total target** | **< 120s** | hard ceiling 150s |

Per-call network `timeout=10`. Per-subprocess `timeout=20`, `kill` on expiry → that check
becomes WARNING. The launchd `plist` sets no `TimeOut`; the module self-limits.

---

## 4. Constants (single source — top of module)

### 4.1 Expected track days
Derived, not hard-coded: `PAPER_REAL_START = date(2026,6,10)`. Expected days =
`(today - PAPER_REAL_START).days + 1`. `d1.equity.count` warns if `num_days <
expected − 1` (one-day grace for not-yet-run cycle). Avoids the stale-constant trap.

### 4.2 Expected adapters & tiers
Source of truth at runtime: `ADAPTER_REGISTRY` from `spa_core.adapters.__init__`. The
monitor reads it for the *expected set* rather than hard-coding, so registry growth doesn't
silently pass. **T1 import-probe set** (for `d5.import.adapters`) is the registry entries
with tier T1: `aave_v3`, `compound_v3`, `morpho_steakhouse` (+ `aave_arbitrum` when promoted).

> ⚠️ **Known data shape hazards (verified against live files — encode defensively):**
> - `adapter_status.json` → adapters live under the **`adapters`** key (dict).
> - **`tier` field is heterogeneous**: integer `1` (aave_v3) *and* string `"T1"` (morpho).
>   Normalize: `1|"1"|"T1"→"T1"`, `2|"2"|"T2"→"T2"`. Unknown → treat as `"T2"` (matches
>   existing concentration-monitor convention) but record `INFO` note.
> - **`apy` is in percent** for newer adapters and **decimal** for some older ones
>   (see memory: adapter-apy-units-inconsistent). Normalize before the 0.5–25 range test:
>   if `0 < apy < 0.5` and a sibling `live_apy`/`fallback_apy` is ~×100 larger, treat as
>   decimal and ×100. Conservative: only flag range violations after normalization.
> - `equity_curve_daily.json` → series under **`daily`** (list); value field
>   **`close_equity`**; meta under `summary` (`num_days`, `end_equity`).
> - `golive_status.json` → `passed`/`total` ints + `checks` dict + `criteria` list.
> - `red_flags.json` → `red_flags` list, each with `severity` ∈ {`CRITICAL`,`WARN`,…}.

### 4.3 Tournament / status / allocation file names
`strategy_tournament.json` (fallback `tournament_results.json` if absent — try both, warn if
neither). Allocation weights from `current_positions.json` (compute pct of total).

### 4.4 Network endpoints
```
DEFILLAMA_POOLS   = https://yields.llama.fi/pools          (sample 3–5 pool ids)
EARNDEFI          = https://earn-defi.com/
GITHUB_RAW        = https://raw.githubusercontent.com/yurii-spa/SPA/main/data/adapter_status.json
GITHUB_API_RATE   = https://api.github.com/rate_limit
LOCAL_API         = http://127.0.0.1:8765/
```
DeFiLlama responses may be **gzip-encoded but not auto-decompressed** by urllib (see memory:
defillama-gzip-not-decompressed). Send **no** `Accept-Encoding` header, or decode gzip
explicitly. A `0x8b` byte → you forgot this.

---

## 5. Output schema — `data/system_health.json`

Atomic write, single object. `history` is a **ring buffer of the last 30 runs** (60 entries ≈
30 days at 2/day → keep 30 to bound size; configurable `_HISTORY_MAX = 30`).

```jsonc
{
  "schema_version": 1,
  "generated_at": "2026-06-21T18:00:03.221Z",   // UTC ISO8601
  "generated_by": "system_health_monitor",
  "run_id": "20260621T1800",                     // YYYYMMDDTHHMM, also launchd slot key
  "overall_status": "WARNING",                   // max roll-up over checks (excl. SKIPPED)
  "fingerprint": "a1b2c3d4",                     // see §6 — for alert dedup
  "duration_ms": 41230,
  "counts": { "CRITICAL": 0, "WARNING": 3, "INFO": 4, "SKIPPED": 1, "OK": 18 },
  "domains": {
    "d1_data_pipeline":   { "status": "OK",       "ms": 120 },
    "d2_connectivity":    { "status": "WARNING",  "ms": 8200 },
    "d3_strategy_quality":{ "status": "OK",       "ms": 90 },
    "d4_external":        { "status": "WARNING",  "ms": 9100 },
    "d5_code_integrity":  { "status": "OK",       "ms": 14300 },
    "d6_risk_gates":      { "status": "OK",       "ms": 6400 },
    "d7_hygiene":         { "status": "INFO",     "ms": 300 }
  },
  "checks": [
    {
      "id": "d2.defillama.deviation",
      "domain": "d2_connectivity",
      "status": "WARNING",
      "title": "Aave V3 stored APY 3.11% vs live 6.40% (+105%)",
      "value": 6.40, "expected": 3.11, "deviation_pct": 105.7,
      "evidence": { "pool": "aave-v3-usdc", "live": 6.40, "stored": 3.11 },
      "error": null,
      "skipped_reason": null
    }
    // … one object per check, stable order by id
  ],
  "trend": {
    "equity_7d_pct": -0.42,                       // d3.equity.trend7 datapoint
    "equity_direction": "declining",
    "golive_passed": 27, "golive_total": 29,
    "golive_delta": 0                             // vs previous run
  },
  "history": [                                     // ring buffer, newest last, max 30
    { "run_id": "20260621T0600", "overall_status": "OK",
      "counts": {"CRITICAL":0,"WARNING":1,"INFO":4},
      "fingerprint": "9f8e...", "equity_7d_pct": -0.30 }
  ]
}
```

**Field notes**
- `value`/`expected`/`evidence` are optional per check; omit when N/A.
- `skipped_reason` set only when `status=="SKIPPED"` (e.g. `"upstream d1.equity.exists failed"`).
- `history` entries are compact (no full `checks`) to bound file size; full detail lives only
  in the current run.

---

## 6. Alert strategy

Two tracks, both via the shared Telegram client (HTML, fail-safe):

### 6.1 Immediate page — CRITICAL only
If `overall_status == CRITICAL` **and** the CRITICAL set is *new* (fingerprint changed, see
below), send immediately. Message lists only CRITICAL check titles + a one-line `run_id`.
No repeat for an unchanged CRITICAL set across consecutive runs (dedup) — re-page only when a
*new* CRITICAL id appears or it clears-then-returns.

### 6.2 12-hour summary — always
Every run (06:00 + 18:00) sends one compact summary: counts line, overall status, domain
status row, any WARNING/CRITICAL titles, the equity trend, and golive `passed/total`.
This is the heartbeat — its presence proves the monitor itself is alive (absence of the
18:00 summary is itself a signal the hourly monitor can't give).

> Design choice: unlike the hourly monitor (which is silent when healthy), this monitor is
> **always vocal** at its 2 daily slots — it doubles as a twice-daily "all green" digest. The
> CRITICAL track is the only one that's dedup-gated against spam.

### 6.3 Fingerprint (dedup)
`fingerprint = sha1( sorted( f"{c.id}:{c.status}" for c in checks if c.status in
{CRITICAL,WARNING} ) )[:8]`. Stored in output + history. Immediate page fires only when the
**CRITICAL subset** of the fingerprint differs from the previous run's. (Mirrors the hourly
monitor's `should_alert` dedup approach, but keyed on stable check ids, not free-text.)

### 6.4 CLI
```
python3 -m spa_core.monitoring.system_health_monitor --check   # compute + write + print, NO telegram
python3 -m spa_core.monitoring.system_health_monitor --run     # compute + write + SEND (page + summary)
python3 -m spa_core.monitoring.system_health_monitor --run --data-dir <dir>
```
launchd uses `--run`. `--check` is for manual/local inspection and CI.

---

## 7. launchd plist — `~/Library/LaunchAgents/com.spa.system_health.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.spa.system_health</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/python3</string>
    <string>-m</string>
    <string>spa_core.monitoring.system_health_monitor</string>
    <string>--run</string>
  </array>
  <key>WorkingDirectory</key><string>/Users/yuriikulieshov/Documents/SPA_Claude</string>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Hour</key><integer>6</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Hour</key><integer>18</integer><key>Minute</key><integer>0</integer></dict>
  </array>
  <key>StandardOutPath</key><string>/tmp/spa_system_health.log</string>
  <key>StandardErrorPath</key><string>/tmp/spa_system_health_err.log</string>
  <key>RunAtLoad</key><false/>
</dict></plist>
```
> Note for the hourly monitor's freshness map: this agent is category `daily`
> (StartCalendarInterval), 26h threshold — but it runs 2×/day, so a >26h-old
> `spa_system_health.log` already implies a missed slot. No comment may contain `--`
> inside the XML (plist-comment hazard — see memory: agent-health-monitor).

---

## 8. Module skeleton (for the implementer)

```python
"""system_health_monitor.py — SPA end-to-end SYSTEM health monitor (12-hourly).
   Outcome/semantic monitoring; complements process-level agent_health_monitor.
   stdlib only · atomic writes · fail-safe (never raises, exit 0) · LLM FORBIDDEN."""
from __future__ import annotations
import argparse, json, glob, hashlib, logging, os, subprocess, sys, urllib.request, gzip
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone, date
from pathlib import Path

CRITICAL, WARNING, INFO, OK, SKIPPED = "CRITICAL","WARNING","INFO","OK","SKIPPED"
_SEV = {OK:0, INFO:1, WARNING:2, CRITICAL:3}              # SKIPPED excluded from rollup
PAPER_REAL_START = date(2026, 6, 10)

@dataclass
class CheckResult:
    id: str; domain: str; status: str = OK; title: str = ""
    value: object = None; expected: object = None
    evidence: dict = field(default_factory=dict)
    error: str | None = None; skipped_reason: str | None = None
    def to_dict(self): ...

class SystemHealthMonitor:
    def __init__(self, data_dir, project_root): ...
    # one method per check group, each returns list[CheckResult], each fully try/except'd
    def check_d1_data_pipeline(self) -> list[CheckResult]: ...
    def check_d2_connectivity(self) -> list[CheckResult]: ...
    def check_d3_strategy_quality(self) -> list[CheckResult]: ...
    def check_d4_external(self) -> list[CheckResult]: ...
    def check_d5_code_integrity(self) -> list[CheckResult]: ...
    def check_d6_risk_gates(self) -> list[CheckResult]: ...
    def check_d7_hygiene(self) -> list[CheckResult]: ...
    def collect(self) -> dict:        # run domains, apply skip graph, build report
        ...
    def run(self, send: bool = True) -> dict:
        report = self.collect()
        prev = self._load_previous()
        if send:
            if report["overall_status"] == CRITICAL and self._new_critical(report, prev):
                _send_telegram(self._format_page(report))
            _send_telegram(self._format_summary(report))    # always
        from spa_core.utils.atomic import atomic_save
        atomic_save(report, str(self.data_dir / "system_health.json"))
        return report

def _send_telegram(msg: str) -> bool:
    try:
        from spa_core.alerts.telegram_client import _post_message
        return _post_message({"text": msg, "parse_mode": "HTML"})
    except Exception as exc:
        logging.getLogger("spa.monitoring.system_health").warning("tg: %s", exc); return False

def main(argv=None) -> int:
    p = argparse.ArgumentParser()
    g = p.add_mutually_exclusive_group(); g.add_argument("--check", action="store_true")
    g.add_argument("--run", action="store_true"); p.add_argument("--data-dir")
    a = p.parse_args(argv)
    try:
        SystemHealthMonitor(...).run(send=bool(a.run))
    except Exception as exc:                                  # ultimate fail-safe
        logging.exception("system_health crashed: %s", exc)
    return 0                                                  # ALWAYS exit 0
```

### 8.1 Kill-switch `--dry-run` probe (d6.killswitch)
Invoke the existing kill-switch entry point as a subprocess **with `--dry-run`**, capture
exit code + stdout, assert it reports an actionable, *non-executed* plan. Never call it
without `--dry-run`. If the entry point name is uncertain at implementation time, the
implementer must confirm it from `spa_core/golive/` / risk tooling before wiring — do **not**
guess a path that could fire a real kill-switch.

### 8.2 Secrets scan (d5.security.secrets)
`git status --porcelain --untracked-files=all`, filter untracked (`??`) paths whose basename
matches `re.compile(r"(token|secret|key|password)", re.I)`, **excluding** known-safe
(`*.lock`, `keystore`-less). Any hit → CRITICAL with the path list (never print contents).
This is the automated tripwire for the 2026-06-10 PAT-leak incident class.

---

## 9. Test plan (must ship with module)
`spa_core/tests/test_system_health_monitor.py`:
- Fixtures: synthetic good + each-failure-mode `data/` dirs (tmp_path).
- Network checks: monkeypatch `urllib.request.urlopen` (no real egress in CI).
- Subprocess checks: monkeypatch `subprocess.run` for import/kill-switch probes.
- Assert: skip-graph (missing equity file → dependents `SKIPPED`, not CRITICAL-spam);
  severity roll-up; fingerprint stability + change-on-new-critical; history ring buffer
  caps at 30; `run()` never raises and returns dict; `--check` sends no telegram
  (assert `_send_telegram` not called).

---
*Spec v1.0 — 2026-06-21. Field paths verified against live data files on this date.*
