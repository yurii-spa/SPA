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
DATA_DIR = os.path.join(PROJECT_ROOT, "data")
DOCS_DIR = os.path.join(PROJECT_ROOT, "docs")
OUTPUT = os.path.join(DOCS_DIR, "SYSTEM_BRIEFING.md")


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
    d = read_json("agent_health.json")
    if not d:
        return "## 🤖 Agent Health\n_agent_health.json not found — run scripts/agent_status.sh to check_\n"

    overall = d.get("overall_status", "UNKNOWN")
    total = d.get("total_agents", 0)
    ok = d.get("healthy_count", 0)
    warn = d.get("warning_count", 0)
    crit = d.get("critical_count", 0)
    ts = d.get("timestamp", "")

    icon_map = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🔴", "UNKNOWN": "❓"}
    icon = icon_map.get(overall, "❓")

    lines = [
        "## 🤖 Agent Health",
        f"{icon} **{overall}** — {ok} OK / {warn} WARN / {crit} CRIT  (of {total})  ·  updated {_age_str(ts)}",
    ]

    agents = d.get("agents", [])
    problems = [a for a in agents if a.get("status") in ("CRITICAL", "WARNING")]
    if problems:
        lines.append("\n**Problems:**")
        for a in problems:
            icon2 = "🔴" if a.get("status") == "CRITICAL" else "⚠️"
            issue = a.get("issue", "")
            lines.append(f"- {icon2} `{a['label']}` — {issue}")
    else:
        lines.append("_All agents nominal_")
    return "\n".join(lines) + "\n"


def build_launchd_section() -> str:
    """Check launchctl directly — only works on real macOS host."""
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
            # Skip non-zero exit for currently-RUNNING agents (numeric PID):
            # launchctl retains the previous run's exit code, so a live server that
            # was cleanly restarted shows e.g. -15 (SIGTERM) — a false alarm.
            _running = pid not in ("-", "0") and pid.lstrip("-").isdigit()
            if exit_code not in ("0", "-") and not _running:
                errored.append(f"`{label}` (exit {exit_code})")

    # Expected agents from agent_status.sh
    expected = [
        "com.spa.httpserver", "com.spa.cloudflared", "com.spa.familyfund",
        "com.spa.uptime_monitor", "com.spa.cycle_health", "com.spa.cycle_gap_monitor",
        "com.spa.portfolio_monitor", "com.spa.peg_monitor", "com.spa.red_flag_monitor",
        "com.spa.governance_watcher", "com.spa.autopush", "com.spa.daily_cycle",
        "com.spa.base_gas_monitor", "com.spa.sky_monitor", "com.spa.daily-paper-report",
        "com.spa.checkpoint-7day", "com.spa.weekly_backup", "com.spa.analytics_tier_c",
        "com.spa.analytics_tier_b", "com.spa.bts-feed", "com.spa.bts-monitor",
    ]
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
        lines.append("_All expected agents loaded and healthy_")
    return "\n".join(lines) + "\n"


def build_portfolio_section() -> str:
    pos = read_json("current_positions.json")
    eq = read_json("equity_curve_daily.json")

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
    # Honest track length: real (non-warmup) days, not the raw bar count which
    # includes pre-2026-06-10 warmup/demo bars. Prefer summary.real_days; fall back
    # to counting non-warmup bars directly so it's honest even before the next cycle.
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

    golive_ready = golive.get("ready", False)
    golive_pass = golive.get("pass_count") or golive.get("passed") or "?"
    golive_total = golive.get("total", 29)
    agent_status = agent_h.get("overall_status", "UNKNOWN")
    agent_total = agent_h.get("total_agents", "?")
    agent_ok = agent_h.get("healthy_count", "?")
    eq_end = eq.get("summary", {}).get("end_equity", 100000)
    eq_ret = eq.get("summary", {}).get("total_return_pct", 0.0)
    # Honest track length: real (non-warmup) days, NOT the raw bar count which
    # includes pre-2026-06-10 warmup/demo bars. Mirror build_portfolio_section so
    # the header table and the Portfolio section never disagree (e.g. 35d vs 15d).
    eq_days = eq.get("summary", {}).get("real_days")
    if eq_days is None:
        _real_bars = [b for b in eq.get("daily", []) if not b.get("is_warmup", False)]
        eq_days = len(_real_bars) if _real_bars else eq.get("summary", {}).get("num_days", 0)

    golive_icon = "✅" if golive_ready else "⛔"
    agent_icon = {"OK": "✅", "WARNING": "⚠️", "CRITICAL": "🔴"}.get(agent_status, "❓")

    header = f"""\
# SPA System Briefing
> Auto-updated: **{now_str}**  ·  Generated by `scripts/update_system_briefing.py`
> **⚠️ DISPATCH: Read this file at the start of every conversation before answering questions about system state.**

## 📊 Status Summary (at a glance)

| Metric | Value |
|--------|-------|
| GoLive | {golive_icon} {golive_pass}/{golive_total} pass — {"READY" if golive_ready else "NOT READY"} |
| Agents | {agent_icon} {agent_status} ({agent_ok}/{agent_total} healthy) |
| Portfolio | ${eq_end:,.2f} ({eq_ret:+.2f}% over {eq_days}d) |
| Track started | 2026-06-10 (real, non-demo) |
| Go-live target | 2026-07-09 (30 honest track days) |
| Sprint | see KANBAN section |

"""

    sections = [
        header,
        build_golive_section() + "\n",
        build_agents_section() + "\n",
        build_launchd_section() + "\n",
        build_portfolio_section() + "\n",
        build_system_health_section() + "\n",
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
