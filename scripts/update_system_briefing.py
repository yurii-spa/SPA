#!/usr/bin/env python3
"""
update_system_briefing.py — SPA System Briefing Auto-Updater

Runs every 30 minutes via com.spa.system_briefing LaunchAgent.
Reads real system state from data/*.json + launchctl, writes docs/SYSTEM_BRIEFING.md.

Pure stdlib — no external dependencies.
Atomic write: tmp → os.replace.
"""

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

# ── Paths ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SCRIPT_DIR)
# Make spa_core importable when run as a standalone script (launchd invokes this
# file directly) so the canonical RETIRED_LABELS source of truth is reachable.
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")
OUTPUT = os.path.join(DOCS_DIR, "SYSTEM_BRIEFING.md")

# agent_health.json is written by com.spa.agent_health (hourly). The briefing
# (every 30 min) CONSUMES it as the single source of truth for the agent fleet —
# it must NOT independently re-derive agent freshness (that was the chronic
# "log missing (never ran?)" detector bug: the briefing read raw logs/<name>.log
# while agents migrated to /tmp/spa_<name>.*). If the snapshot is older than this
# threshold the briefing marks it STALE (fail-honest) rather than presenting a
# possibly-contradictory number. 35 min = the hourly writer's cadence is 60 min;
# anything materially past one extra 30-min briefing tick is suspect.
AGENT_SNAPSHOT_STALE_MIN = 35

# Hard fallback list mirroring agent_health_monitor.RETIRED_LABELS, used ONLY if
# that module cannot be imported (e.g. a stripped sandbox). The live import below
# is the source of truth; this keeps the briefing honest about retired agents
# even when spa_core is unavailable.
_RETIRED_FALLBACK = frozenset({
    "com.spa.bot_commands",
    "com.spa.httpserver",
    "com.spa.telegram_daily",
    "com.spa.telegram_weekly",
    "com.spa.morning_digest",
    "com.spa.daily-paper-report",
})


def _retired_labels() -> frozenset:
    """Single source of truth for retired agents = agent_health_monitor.RETIRED_LABELS.

    The briefing must NOT flag a retired agent (httpserver, morning_digest, …) as
    "Missing" / "Non-zero exit" — they were retired by owner decision, so a
    healthy fleet that correctly does NOT load them must read healthy. Falls back
    to a literal mirror only if the canonical module can't be imported.
    """
    try:
        from spa_core.monitoring.agent_health_monitor import RETIRED_LABELS
        return frozenset(RETIRED_LABELS)
    except Exception:
        return _RETIRED_FALLBACK


# ── JSON helpers ───────────────────────────────────────────────────────────────
def read_json(name: str) -> dict:
    path = os.path.join(DATA_DIR, name)
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {}


def _age_str(ts: str) -> str:
    """Return human-readable age since ISO timestamp."""
    if not ts:
        return "unknown"
    try:
        # strip microseconds noise
        ts_clean = ts[:19].replace(" ", "T")
        dt = datetime.fromisoformat(ts_clean).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = int((now - dt).total_seconds())
        if diff < 0:
            return "just now"
        if diff < 60:
            return f"{diff}s ago"
        if diff < 3600:
            return f"{diff // 60}m ago"
        if diff < 86400:
            return f"{diff // 3600}h ago"
        return f"{diff // 86400}d ago"
    except Exception:
        return ts[:10]


def _age_minutes(ts: str):
    """Return age in minutes since ISO timestamp ``ts``, or None if unparseable.

    Used by the agent-snapshot staleness guard so the briefing can fail-honest
    (mark the agent_health.json snapshot STALE) instead of presenting a number
    that may no longer reflect the live fleet.
    """
    if not ts:
        return None
    try:
        ts_clean = ts[:19].replace(" ", "T")
        dt = datetime.fromisoformat(ts_clean).replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        return max(0.0, (now - dt).total_seconds() / 60.0)
    except Exception:
        return None


def agent_snapshot_state(d: dict):
    """Classify the agent_health.json snapshot for the briefing.

    Returns one of:
      * ("missing", None)  — file absent/empty/unreadable → fail-honest
      * ("stale", age_min) — present but older than AGENT_SNAPSHOT_STALE_MIN
      * ("fresh", age_min) — present and recent (or unknown age but present)

    The briefing reflects agent_health.json VERBATIM when fresh, and refuses to
    present its counts when missing/stale (it says so instead).
    """
    if not d:
        return ("missing", None)
    age = _age_minutes(d.get("timestamp", ""))
    if age is None:
        # Present but timestamp unparseable — cannot prove freshness → treat as
        # stale (fail-CLOSED: don't vouch for a snapshot we can't date).
        return ("stale", None)
    if age > AGENT_SNAPSHOT_STALE_MIN:
        return ("stale", age)
    return ("fresh", age)


# ── Section builders ───────────────────────────────────────────────────────────
def build_golive_section() -> str:
    d = read_json("golive_status.json")
    if not d:
        return "## 🎯 GoLive Status\n_golive_status.json not found_\n"

    ready = d.get("ready", False)
    pass_count = d.get("pass_count") or d.get("passed") or sum(
        1 for v in d.get("checks", {}).values() if v
    )
    total = d.get("total", 29)
    blockers = d.get("blockers", [])
    ts = d.get("timestamp", "")
    icon = "✅ READY" if ready else "⛔ NOT READY"

    lines = [
        "## 🎯 GoLive Status",
        f"**{icon}** — {pass_count}/{total} pass  ·  updated {_age_str(ts)}",
    ]
    if blockers:
        lines.append("\n**Blockers:**")
        for b in blockers:
            # shorten long blocker text
            short = b[:120] + ("…" if len(b) > 120 else "")
            lines.append(f"- {short}")
    else:
        lines.append("_No blockers — system eligible for go-live review_")
    return "\n".join(lines) + "\n"


def build_agents_section() -> str:
    """Agent fleet section — agent_health.json is the SINGLE SOURCE OF TRUTH.

    The briefing CONSUMES the hourly com.spa.agent_health snapshot verbatim; it
    does NOT independently re-derive per-agent freshness from raw logs (the old
    "log missing (never ran?)" detector bug read the pre-migration
    logs/<name>.log path and false-flagged agents that demonstrably ran — the
    canonical freshness logic now lives in agent_health_monitor.candidate_log_paths
    reading /tmp/spa_<name>.* + the plist streams). Counts and per-agent verdicts
    here equal agent_health.json's ±0.

    Fail-honest: if the snapshot is missing or stale (> AGENT_SNAPSHOT_STALE_MIN),
    the briefing SAYS SO instead of presenting a number that may no longer reflect
    the live fleet.
    """
    d = read_json("agent_health.json")
    state, age_min = agent_snapshot_state(d)

    if state == "missing":
        return ("## 🤖 Agent Health\n"
                "❓ **SNAPSHOT UNAVAILABLE** — `data/agent_health.json` missing/unreadable. "
                "Cannot vouch for the agent fleet. "
                "Run `python3 -m spa_core.monitoring.agent_health_monitor --check` "
                "(or check `launchctl list | grep spa`).\n")

    overall = d.get("overall_status", "UNKNOWN")
    total = d.get("total_agents", 0)
    ok = d.get("healthy_count", 0)
    warn = d.get("warning_count", 0)
    crit = d.get("critical_count", 0)
    ts = d.get("timestamp", "")

    if state == "stale":
        age_txt = f"{age_min:.0f} min" if age_min is not None else "unknown age"
        return ("## 🤖 Agent Health\n"
                f"⚠️ **SNAPSHOT STALE** — `agent_health.json` is {age_txt} old "
                f"(> {AGENT_SNAPSHOT_STALE_MIN} min); the com.spa.agent_health writer may be lagging. "
                "Counts below are LAST-KNOWN, not live — verify with "
                "`launchctl list | grep spa`.\n"
                f"_Last-known: {ok} OK / {warn} WARN / {crit} CRIT (of {total}), "
                f"overall {overall}, snapshot {_age_str(ts)}._\n")

    icon_map = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🔴", "UNKNOWN": "❓"}
    icon = icon_map.get(overall, "❓")

    lines = [
        "## 🤖 Agent Health",
        f"{icon} **{overall}** — {ok} OK / {warn} WARN / {crit} CRIT  (of {total})  ·  snapshot {_age_str(ts)}",
    ]

    agents = d.get("agents", [])
    problems = [a for a in agents if a.get("status") in ("CRITICAL", "WARNING")]
    if problems:
        lines.append("\n**Problems (verbatim from agent_health.json):**")
        for a in problems:
            icon2 = "🔴" if a.get("status") == "CRITICAL" else "⚠️"
            issue = a.get("issue", "")
            lines.append(f"- {icon2} `{a['label']}` — {issue}")
    else:
        lines.append("_All agents nominal_")
    return "\n".join(lines) + "\n"


def build_launchd_section() -> str:
    """Check launchctl directly — only works on real macOS host.

    Honesty contract (cry-wolf fix): RETIRED agents (the single source of truth
    is ``agent_health_monitor.RETIRED_LABELS`` — e.g. com.spa.httpserver,
    com.spa.morning_digest, com.spa.daily-paper-report) are NEVER counted as
    expected and NEVER flagged "Missing" or "Non-zero exit". They were retired by
    owner decision; a healthy fleet that has correctly NOT loaded them must read
    healthy here, not cry wolf. A retired agent still resident in launchctl is
    likewise not error-flagged.
    """
    retired = _retired_labels()
    try:
        result = subprocess.run(
            ["launchctl", "list"],
            capture_output=True, text=True, timeout=5
        )
        lines_raw = [l for l in result.stdout.splitlines() if "com.spa" in l]
    except Exception:
        return "## ⚙️ LaunchAgents (launchctl)\n_launchctl unavailable in this environment_\n"

    loaded_labels = set()
    errored = []
    for line in lines_raw:
        parts = line.split()
        if len(parts) >= 3:
            pid, exit_code, label = parts[0], parts[1], parts[2]
            loaded_labels.add(label)
            # Retired agents are out of the fleet — never error-flag them even if
            # a stale .plist lingers and launchd retains a non-zero exit for them.
            if label in retired:
                continue
            # Skip non-zero exit for currently-RUNNING agents (numeric PID):
            # launchctl retains the previous run's exit code, so a live server that
            # was cleanly restarted shows e.g. -15 (SIGTERM) — a false alarm.
            _running = pid not in ("-", "0") and pid.lstrip("-").isdigit()
            if exit_code not in ("0", "-") and not _running:
                errored.append(f"`{label}` (exit {exit_code})")

    # Expected agents from agent_status.sh, MINUS any that have been retired
    # (RETIRED_LABELS). Retired agents being absent is correct, not a fault.
    expected = [
        "com.spa.httpserver", "com.spa.cloudflared", "com.spa.familyfund",
        "com.spa.uptime_monitor", "com.spa.cycle_health", "com.spa.cycle_gap_monitor",
        "com.spa.portfolio_monitor", "com.spa.peg_monitor", "com.spa.red_flag_monitor",
        "com.spa.governance_watcher", "com.spa.autopush", "com.spa.daily_cycle",
        "com.spa.base_gas_monitor", "com.spa.sky_monitor", "com.spa.daily-paper-report",
        "com.spa.checkpoint-7day", "com.spa.weekly_backup", "com.spa.analytics_tier_c",
        "com.spa.analytics_tier_b", "com.spa.bts-feed", "com.spa.bts-monitor",
    ]
    expected = [e for e in expected if e not in retired]
    missing = [e for e in expected if e not in loaded_labels]

    lines = [
        "## ⚙️ LaunchAgents (launchctl)",
        f"Loaded: **{len(loaded_labels)}**  ·  Missing from expected list: **{len(missing)}**",
    ]
    if missing:
        lines.append("\n**Missing (not loaded):**")
        for m in missing:
            lines.append(f"- ❌ `{m}`")
    if errored:
        lines.append("\n**Non-zero exit codes:**")
        for e in errored:
            lines.append(f"- ⚠️ {e}")
    if not missing and not errored:
        lines.append("_All expected agents loaded and healthy (retired agents excluded)_")
    return "\n".join(lines) + "\n"


def build_portfolio_section() -> str:
    pos = read_json("current_positions.json")
    eq = read_json("equity_curve_daily.json")
    golive = read_json("golive_status.json")

    if not pos:
        return "## 💰 Portfolio\n_current_positions.json not found_\n"

    capital = pos.get("capital_usd", 100000)
    deployed = pos.get("deployed_usd", 0)
    cash = pos.get("cash_usd", 0)
    apy_expected = pos.get("tuner_expected_apy", 0)
    compliant = pos.get("policy_compliant", False)
    ts = pos.get("generated_at", "")

    # Equity summary
    eq_summary = eq.get("summary", {})
    end_equity = eq_summary.get("end_equity", capital)
    total_return = eq_summary.get("total_return_pct", 0.0)
    # CANONICAL track length = evidenced count from golive_checker
    # (golive_status.real_track_days). Single honest number, shared with the header.
    # Fall back to summary.real_days then non-warmup bar count only if unavailable.
    num_days = golive.get("real_track_days")
    if num_days is None:
        num_days = eq_summary.get("real_days")
    if num_days is None:
        _real = [b for b in eq.get("daily", []) if not b.get("is_warmup", False)]
        num_days = len(_real) if _real else eq_summary.get("num_days", 0)

    # positions dict
    positions = pos.get("positions", {})
    val_sum = pos.get("validation_summary", {})
    t1_pct = val_sum.get("t1_pct", 0)
    t2_pct = val_sum.get("t2_pct", 0)
    cash_pct = val_sum.get("cash_pct", 0)

    compliant_str = "✅ policy compliant" if compliant else "⚠️ NOT compliant"
    lines = [
        "## 💰 Portfolio",
        f"Capital: **${end_equity:,.2f}** ({total_return:+.2f}% over {num_days}d)  ·  updated {_age_str(ts)}",
        f"Deployed: ${deployed:,.0f} ({100 - cash_pct:.0f}%)  ·  Cash: ${cash:,.0f} ({cash_pct:.0f}%)  ·  Expected APY: **{apy_expected:.2f}%**  ·  {compliant_str}",
        f"T1: {t1_pct:.0f}%  ·  T2: {t2_pct:.0f}%  ·  Cash: {cash_pct:.0f}%",
    ]
    if isinstance(positions, dict) and positions:
        lines.append("\n**Positions:**")
        for proto, usd in sorted(positions.items(), key=lambda x: -x[1]):
            pct = usd / capital * 100
            lines.append(f"- `{proto}`: ${usd:>10,.0f}  ({pct:.1f}%)")
    return "\n".join(lines) + "\n"


def build_system_health_section() -> str:
    d = read_json("system_health.json")
    if not d:
        return "## 🏥 System Health\n_system_health.json not found_\n"

    overall = d.get("overall_status", "UNKNOWN")
    counts = d.get("counts", {})
    ts = d.get("generated_at", "")
    icon_map = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🔴"}
    icon = icon_map.get(overall, "❓")

    domains = d.get("domains", {})
    problem_domains = {k: v for k, v in domains.items() if v.get("status") not in ("OK", "INFO")}

    lines = [
        "## 🏥 System Health",
        f"{icon} **{overall}** — "
        f"OK:{counts.get('OK',0)} WARN:{counts.get('WARNING',0)} CRIT:{counts.get('CRITICAL',0)}  ·  updated {_age_str(ts)}",
    ]
    if problem_domains:
        lines.append("\n**Problem domains:**")
        for domain, info in problem_domains.items():
            lines.append(f"- ⚠️ `{domain}`: {info.get('status')}")
    return "\n".join(lines) + "\n"


def build_resilience_section() -> str:
    """Resilience posture — mirrors the T1 snapshot-age / fail-honest style.

    Reads data/resilience_status.json (written by
    spa_core.monitoring.resilience_status), which itself rolls up the three
    resilience proofs (offsite copy R6, restore drill R7, fleet-down drill R4).
    Each proof shows its last pass date + a visible STALE / never-run marker so
    a dormant or failed proof can never hide behind a green headline.
    """
    d = read_json("resilience_status.json")
    if not d:
        return ("## 🛡️ Resilience (DR posture)\n"
                "❓ **ROLLUP UNAVAILABLE** — `data/resilience_status.json` missing. "
                "Run `python3 -m spa_core.monitoring.resilience_status` to generate it.\n")

    overall = d.get("overall", "UNKNOWN")
    ts = d.get("generated_at", "")
    icon = {"OK": "✅", "WARNING": "⚠️", "UNKNOWN": "❓"}.get(overall, "❓")

    def _proof_line(label: str, p: dict, pass_key: str, pass_label: str) -> str:
        if not p:
            return f"- ❓ **{label}** — no data"
        if p.get("never_run"):
            return f"- 🔴 **{label}** — ⛔ NEVER RUN (proof not yet exercised)"
        last = p.get("last_ts") or "unknown"
        last_date = last[:10] if isinstance(last, str) else "unknown"
        passed = p.get(pass_key, False)
        stale = p.get("stale", False)
        bits = []
        bits.append("✅ " + pass_label if passed else "🔴 NOT " + pass_label)
        if stale:
            bits.append("⚠️ STALE")
        marker = "  ·  ".join(bits)
        return f"- {'⚠️' if (stale or not passed) else '✅'} **{label}** — last {last_date}  ·  {marker}"

    off = d.get("offsite", {})
    real_remote = off.get("is_real_remote", False)
    remote_txt = "real remote" if real_remote else "local stand-in (owner-flagged)"

    lines = [
        "## 🛡️ Resilience (DR posture)",
        f"{icon} **{overall}** — offsite + restore-drill + fleet-drill rollup  ·  updated {_age_str(ts)}",
        _proof_line(f"Offsite copy ({remote_txt})", off, "verified", "verified"),
        _proof_line("Restore drill", d.get("restore_drill", {}), "all_ok", "passed"),
        _proof_line("Fleet-down drill", d.get("fleet_drill", {}), "all_ok", "passed"),
    ]
    notes = d.get("notes", [])
    if notes:
        lines.append("\n**Why WARNING:**" if overall != "OK" else "\n**Notes:**")
        for n in notes:
            lines.append(f"- {n}")
    return "\n".join(lines) + "\n"


def build_sprint_section() -> str:
    try:
        kanban_path = os.path.join(PROJECT_ROOT, "KANBAN.json")
        with open(kanban_path) as f:
            k = json.load(f)
        sprint = k.get("sprint_current", "?")
        done = k.get("done_count", "?")
        backlog = [t for t in k.get("tasks", []) if t.get("status") == "backlog"]
        in_prog = [t for t in k.get("tasks", []) if t.get("status") == "in_progress"]
        lines = [
            "## 📋 Sprint / KANBAN",
            f"Sprint: **{sprint}**  ·  Done: **{done}**  ·  Backlog: {len(backlog)}  ·  In-progress: {len(in_prog)}",
        ]
        # list any in-progress tasks
        if in_prog:
            lines.append("\n**In-progress tasks:**")
            for t in in_prog[:5]:
                lines.append(f"- [{t.get('id','?')}] {t.get('title', t.get('subject','?'))[:80]}")
        return "\n".join(lines) + "\n"
    except Exception as e:
        return f"## 📋 Sprint / KANBAN\n_KANBAN.json not readable: {e}_\n"


def build_rules_section() -> str:
    return """\
## 📏 Dispatch Rules (always apply)

1. **Never say agents are working without reading `agent_health.json` or `launchctl list`**.
2. **Never say GoLive is ready without reading `golive_status.json`**.
3. **Never say "all agents installed" based on plist files existing** — loaded ≠ installed.
4. This file is auto-updated every 30 min. Its data is more reliable than Dispatch memory.
5. When Юрий asks "как дела" / "что работает" / "агенты установлены?" → read this file first.
6. LLM is FORBIDDEN in risk/execution/monitoring components — never generate code that calls LLM there.
7. Atomic writes only: `tmp + os.replace` on all data/*.json state files.
"""


def build_commands_section() -> str:
    return """\
## 🔧 Quick Diagnostic Commands

```bash
# Real agent status (run on macOS host):
bash ~/Documents/SPA_Claude/scripts/agent_status.sh

# GoLive check:
python3 -m spa_core.paper_trading.golive_checker

# Daily cycle (manual):
python3 -m spa_core.paper_trading.cycle_runner --verbose

# System health:
python3 -m spa_core.monitoring.system_health_monitor

# Refresh this briefing now:
python3 ~/Documents/SPA_Claude/scripts/update_system_briefing.py
```
"""


# ── Main ───────────────────────────────────────────────────────────────────────
def main() -> None:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    ts_iso = datetime.now(timezone.utc).isoformat()

    # Read fast summary values for the header
    golive = read_json("golive_status.json")
    agent_h = read_json("agent_health.json")
    eq = read_json("equity_curve_daily.json")
    resil = read_json("resilience_status.json")

    golive_ready = golive.get("ready", False)
    golive_pass = golive.get("pass_count") or golive.get("passed") or "?"
    golive_total = golive.get("total", 29)
    # Agent fleet header cell — driven by the SAME staleness guard as the
    # detailed section so the two surfaces can never disagree. When the snapshot
    # is missing/stale the header says so (fail-honest) rather than printing a
    # possibly-contradictory count.
    agent_state, agent_age_min = agent_snapshot_state(agent_h)
    agent_status = agent_h.get("overall_status", "UNKNOWN")
    agent_total = agent_h.get("total_agents", "?")
    agent_ok = agent_h.get("healthy_count", "?")
    eq_end = eq.get("summary", {}).get("end_equity", 100000)
    eq_ret = eq.get("summary", {}).get("total_return_pct", 0.0)
    # CANONICAL track length = evidenced count from golive_checker
    # (golive_status.real_track_days). This is the ONE honest number; every surface
    # reads it so they can't disagree (e.g. 17 days_running vs 5 evidenced). Fall
    # back to equity summary.real_days, then non-warmup bar count, only if the
    # canonical source is unavailable.
    eq_days = golive.get("real_track_days")
    if eq_days is None:
        eq_days = eq.get("summary", {}).get("real_days")
    if eq_days is None:
        _real_bars = [b for b in eq.get("daily", []) if not b.get("is_warmup", False)]
        eq_days = len(_real_bars) if _real_bars else eq.get("summary", {}).get("num_days", 0)

    # Honest anchor + go-live target, derived from golive_status (NOT hardcoded).
    # Canonical source = the top-level evidenced_anchor / target_date fields the
    # go-live checker now surfaces (one honest derived value). Fall back to the
    # equity summary / per-criterion detail only for older status files.
    track_anchor = (
        golive.get("evidenced_anchor")
        or eq.get("summary", {}).get("evidenced_anchor")
        or eq.get("summary", {}).get("first_real_date")
        or "2026-06-22"
    )
    golive_target = golive.get("target_date") or "?"
    if golive_target == "?":
        for crit in golive.get("criteria", []):
            if crit.get("name") in ("min_track_days_30", "gap_monitor_30d") and crit.get("target_date"):
                golive_target = crit["target_date"]
                break

    # Resilience header cell — fail-honest, mirrors the agent/snapshot style.
    if not resil:
        resil_cell = "❓ rollup unavailable (resilience_status.json missing)"
    else:
        r_overall = resil.get("overall", "UNKNOWN")
        r_icon = {"OK": "✅", "WARNING": "⚠️", "UNKNOWN": "❓"}.get(r_overall, "❓")
        n_notes = len(resil.get("notes", []))
        resil_cell = f"{r_icon} {r_overall}" + (f" ({n_notes} note{'s' if n_notes != 1 else ''})" if n_notes else "")

    golive_icon = "✅" if golive_ready else "⛔"
    if agent_state == "missing":
        agent_icon = "❓"
        agent_cell = "❓ snapshot unavailable (agent_health.json missing)"
    elif agent_state == "stale":
        agent_icon = "⚠️"
        age_txt = f"{agent_age_min:.0f}m" if agent_age_min is not None else "unknown age"
        agent_cell = (f"⚠️ SNAPSHOT STALE ({age_txt} > {AGENT_SNAPSHOT_STALE_MIN}m) — "
                      f"last-known {agent_ok}/{agent_total}")
    else:
        agent_icon = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🔴"}.get(agent_status, "❓")
        agent_cell = f"{agent_icon} {agent_status} ({agent_ok}/{agent_total} healthy)"

    header = f"""\
# SPA System Briefing
> Auto-updated: **{now_str}**  ·  Generated by `scripts/update_system_briefing.py`
> **⚠️ DISPATCH: Read this file at the start of every conversation before answering questions about system state.**

## 📊 Status Summary (at a glance)

| Metric | Value |
|--------|-------|
| GoLive | {golive_icon} {golive_pass}/{golive_total} pass — {"READY" if golive_ready else "NOT READY"} |
| Agents | {agent_cell} |
| Portfolio | ${eq_end:,.2f} ({eq_ret:+.2f}% over {eq_days}d evidenced) |
| Track days (evidenced) | {eq_days}/30 (anchor {track_anchor}) |
| Go-live target | {golive_target} (30 honest track days) |
| Resilience (DR) | {resil_cell} |
| Sprint | see KANBAN section |

"""

    sections = [
        header,
        build_golive_section() + "\n",
        build_agents_section() + "\n",
        build_launchd_section() + "\n",
        build_portfolio_section() + "\n",
        build_system_health_section() + "\n",
        build_resilience_section() + "\n",
        build_sprint_section() + "\n",
        build_rules_section() + "\n",
        build_commands_section() + "\n",
        f"---\n_Briefing generated at {ts_iso}_\n",
    ]

    content = "\n".join(sections)

    # Atomic write
    os.makedirs(DOCS_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DOCS_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(content)
        os.replace(tmp, OUTPUT)
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise

    print(f"[update_system_briefing] ✅ Written {OUTPUT}  ({len(content)} bytes)")


if __name__ == "__main__":
    main()
