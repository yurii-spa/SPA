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
# while agents migrated to /tmp/spa_<name>.*). If the snapshot is older than its
# freshness budget the briefing marks it STALE (fail-honest) rather than presenting
# a possibly-contradictory number.
#
# The budget belongs to the PRODUCER, not to us: agent_health.json declares its own
# `stale_after_minutes` (90) next to its `cadence_minutes` (60), and
# snapshot_budget_min() reads it. The literal below is ONLY the fallback for a
# snapshot that declares nothing — and a fallback is NAMED out loud, never
# silently substituted (a budget the producer never agreed to is a guess).
#
# Cycle #242: this literal used to be the whole rule, and 35 < 60 = the writer's
# own cadence, so a fully healthy fleet flew "SNAPSHOT STALE" for ~25 minutes of
# every hour BY CONSTRUCTION. Same class as #235 (one artifact, two budgets,
# decided by the side that does not produce it) with the sign flipped: there the
# budget could never fire, here it fired almost always. Either way the guard
# teaches its readers to ignore it, and the real lag it exists to catch goes with it.
AGENT_SNAPSHOT_STALE_MIN = 35

# data/cycle_health.json is written by com.spa.cycle_health every 300 s (MEASURED
# #242: com.spa.cycle_health.plist StartInterval=300). The briefing CONSUMES its
# evidence-vs-curve number (see build_track_integrity_section); it must NOT re-derive
# the comparison itself — a second implementation of "do the two money records
# agree?" would be a second answer to the same question, and the rule from cycle
# #146 onwards is one question → one source. A snapshot older than this means the
# 5-minute producer has missed ~6 runs, so its numbers describe a past the briefing
# must not present as the present.
#
# 30 min ≫ 5 min cadence, so unlike the agent budget above this one is NOT red by
# construction — measured, not assumed (card item 3). cycle_health.json declares no
# budget of its own today, so this literal is the fallback and the briefing says so;
# if the producer ever starts declaring one, snapshot_budget_min() will prefer it.
TRACK_SNAPSHOT_STALE_MIN = 30

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


def snapshot_budget_min(d: dict, fallback: float):
    """Freshness budget for someone else's artifact — ASK THE PRODUCER.

    Returns ``(budget_minutes, source)`` where ``source`` is:
      * ``"declared"`` — the snapshot carries its own ``stale_after_minutes``
        and that number decides;
      * ``"fallback"`` — it declares nothing, so the consumer's literal is used
        and the caller is OBLIGED to name it out loud (see budget_txt).

    Why this exists (#242): the briefing judged the hourly agent_health.json by a
    35-minute literal of its own invention, below the writer's own 60-minute
    cadence, so "SNAPSHOT STALE" was the normal state of a healthy fleet. A
    consumer that invents a budget for a producer is measuring its own guess.
    """
    if isinstance(d, dict):
        raw = d.get("stale_after_minutes")
        if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0:
            return (float(raw), "declared")
    return (float(fallback), "fallback")


def budget_txt(budget_min: float, source: str, lang: str = "en") -> str:
    """Render a budget so the reader can tell WHOSE number it is.

    A silent fallback reads exactly like a producer-declared budget, which is how
    an invented threshold survives review. Naming it costs one word.
    """
    if lang == "ru":
        return (f"{budget_min:.0f}m объявленных писателем" if source == "declared"
                else f"{budget_min:.0f}m — запасной бюджет брифинга, снимок своего не объявляет")
    return (f"{budget_min:.0f} min declared by the writer" if source == "declared"
            else f"{budget_min:.0f} min — briefing fallback, snapshot declares no budget")


def agent_snapshot_state(d: dict):
    """Classify the agent_health.json snapshot for the briefing.

    Returns one of:
      * ("missing", None)  — file absent/empty/unreadable → fail-honest
      * ("stale", age_min) — present but older than its freshness budget
        (``stale_after_minutes`` from the snapshot itself; AGENT_SNAPSHOT_STALE_MIN
        only when it declares none — see snapshot_budget_min)
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
    budget, _src = snapshot_budget_min(d, AGENT_SNAPSHOT_STALE_MIN)
    if age > budget:
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

    Fail-honest: if the snapshot is missing or stale (older than the budget the
    snapshot itself declares — see snapshot_budget_min),
    the briefing SAYS SO instead of presenting a number that may no longer reflect
    the live fleet.

    Reason contract (cycle #75): the section renders BOTH kinds of reason the
    snapshot carries — per-agent problems AND ``system_issues`` (fleet parity,
    capital efficiency, …), each verbatim. The nominal reassurance
    "_All agents nominal_" is reachable ONLY when overall == OK; any non-OK
    verdict with nothing to quote is published as "cause NOT STATED". Before this,
    the section read d["agents"] alone, so a fleet of all-OK agents under a
    system-driven WARNING printed "_All agents nominal_" directly beneath the
    WARNING and named no cause — which is how "fleet parity stale 507.9h"
    (~21 days) stayed invisible in the one file every session is obliged to read.
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
        budget, src = snapshot_budget_min(d, AGENT_SNAPSHOT_STALE_MIN)
        return ("## 🤖 Agent Health\n"
                f"⚠️ **SNAPSHOT STALE** — `agent_health.json` is {age_txt} old "
                f"(> {budget_txt(budget, src)}); the com.spa.agent_health writer may be lagging. "
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

    # System-level reasons. agent_health_monitor.build_report derives
    # overall = _worst(system_status, *[per-agent statuses]), and system_status is
    # raised BY system_issues — so a fleet where every agent is OK can still be
    # WARNING. Rendering only d["agents"] made those verdicts unexplainable: the
    # live briefing showed "WARNING — 70 OK / 0 WARN / 0 CRIT" above
    # "_All agents nominal_" while the snapshot named "fleet parity stale 507.9h"
    # (~21 days) right there in system_issues. Quote them VERBATIM — a paraphrase
    # drops the number that makes the issue actionable.
    raw_issues = d.get("system_issues", [])
    if not isinstance(raw_issues, list):  # fail-honest: never take the briefing down
        raw_issues = []
    sys_issues = [str(s).strip() for s in raw_issues if str(s).strip()]
    if sys_issues:
        lines.append("\n**System-level issues (verbatim from agent_health.json):**")
        for s in sys_issues:
            lines.append(f"- ⚠️ {s}")

    if not problems and not sys_issues:
        # fail-CLOSED: the nominal reassurance is reachable ONLY under an OK
        # verdict. A non-OK verdict with nothing to quote is reported as exactly
        # that — an unexplained verdict is still not a healthy fleet.
        if overall == "OK":
            lines.append("_All agents nominal_")
        else:
            lines.append(
                f"_Verdict **{overall}**, but the snapshot names no reason "
                "(no per-agent problem and no `system_issues`) — cause NOT STATED, "
                "not 'nominal'. Run "
                "`python3 -m spa_core.monitoring.agent_health_monitor --check`._"
            )
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
            # "unchecked" (no check in the domain produced a real status — e.g. the
            # domain blew its time budget) must never read like a measured verdict.
            suffix = " — **NOT CHECKED** (no check ran)" if info.get("unchecked") else ""
            lines.append(f"- ⚠️ `{domain}`: {info.get('status')}{suffix}")
    return "\n".join(lines) + "\n"


def track_integrity_state(d: dict, *, now: datetime | None = None) -> dict:
    """Classify the evidence-vs-curve number from a ``data/cycle_health.json`` snapshot.

    ``cycle_health_monitor.check_evidence_matches_curve`` answers a question no
    other guard asks: do the two records of the SAME money — ``paper_evidence.json``
    (what the go-live checks read) and ``equity_curve_daily.json`` (the curve) —
    say the same number? Measured 2026-08-12: **18 of 54 dates disagree, worst
    $215.99, latest one today** — and 16 of 51 three days earlier, so the defect
    (own-32, two writers of the curve) is live and growing.

    That number had no reader. It was written into monitor state every 300 s and
    consumed by nothing but its own unit tests — the exact class the card that
    produced it warned against ("иначе повторим дефект правила честности, где
    вывод записывался, но никем не читался"). This function is the reader; the
    briefing is the one file CLAUDE.md obliges every session to open.

    Returns ``{"state": …, …}`` where state is one of:

      * ``missing``   — no snapshot at all
      * ``no_check``  — snapshot present but has no ``evidence_vs_curve`` key.
        This is NOT the same as "agrees": prod running a pre-2026-08-10 monitor
        produces exactly this shape, and omitting the line would let an absent
        check read as a clean one.
      * ``unchecked`` — the monitor itself could not compare (files absent, no
        common dates); its ``detail`` is carried through verbatim
      * ``stale``     — numbers are real but older than the freshness budget
        (declared by the snapshot if it carries one, else TRACK_SNAPSHOT_STALE_MIN,
        and ``budget_source`` in the result says which)
      * ``fresh``     — measured, recent, usable

    ``now`` is an input, not the environment, so tests pin both sides of the
    freshness question (rule `.claude/rules/deployment.md`, "время — вход").
    """
    if not d:
        return {"state": "missing", "detail": "data/cycle_health.json отсутствует или не читается"}

    checks = d.get("checks")
    if not isinstance(checks, dict) or "evidence_vs_curve" not in checks:
        return {"state": "no_check",
                "detail": "в снимке нет проверки evidence_vs_curve — монитор старой версии"}

    chk = checks.get("evidence_vs_curve") or {}
    age_min = _age_minutes(d.get("checked_at", ""))
    budget_min, budget_src = snapshot_budget_min(d, TRACK_SNAPSHOT_STALE_MIN)
    out = {
        "budget_min": budget_min,
        "budget_source": budget_src,
        "divergent_days": chk.get("divergent_days"),
        "compared_days": chk.get("compared_days"),
        "max_delta_usd": chk.get("max_delta_usd"),
        "latest_divergent": chk.get("latest_divergent"),
        "detail": str(chk.get("detail") or ""),
        "age_min": age_min,
    }

    if chk.get("status") == "UNCHECKED" or out["divergent_days"] is None:
        out["state"] = "unchecked"
        out["detail"] = out["detail"] or "монитор не смог сравнить записи"
        return out

    # Unparseable/absent checked_at cannot prove freshness → stale, never fresh.
    if age_min is None or age_min > budget_min:
        out["state"] = "stale"
        return out

    out["state"] = "fresh"
    ref = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
    out["live_today"] = bool(out["latest_divergent"]) and str(out["latest_divergent"]) == ref
    return out


def track_integrity_cell(st: dict) -> str:
    """One-line at-a-glance cell. Never claims agreement it did not measure."""
    state = st.get("state")
    if state in ("missing", "no_check"):
        return f"❓ НЕ ИЗМЕРЕНО — {st.get('detail', '')}"
    if state == "unchecked":
        return f"❓ НЕ ИЗМЕРЕНО — {st.get('detail', '')}"

    div, cmp_ = st.get("divergent_days"), st.get("compared_days")
    if state == "stale":
        age = st.get("age_min")
        age_txt = f"{age:.0f}m" if age is not None else "unknown age"
        b_txt = budget_txt(st.get("budget_min", TRACK_SNAPSHOT_STALE_MIN),
                           st.get("budget_source", "fallback"), lang="ru")
        return (f"⚠️ СНИМОК ПРОТУХ ({age_txt} > {b_txt}) — "
                f"last-known {div}/{cmp_} дат расходятся")
    if not div:
        return f"✅ доказательная база = кривая ({cmp_} дат сходятся)"
    worst = st.get("max_delta_usd")
    worst_txt = f", максимум ${worst:,.2f}" if isinstance(worst, (int, float)) else ""
    live = "  ·  🔴 ЖИВОЕ (разошёлся и сегодняшний день)" if st.get("live_today") else ""
    return f"⚠️ {div}/{cmp_} дат расходятся{worst_txt}{live}"



def source_discovery_state(d: dict, *, now: datetime | None = None,
                           max_age_days: float = 8.0) -> dict:
    """Состояние поиска новых источников доходности (ADR-142).

    Инструмент `scripts/find_defillama_sources.py` был рабочим, покрыт 30
    тестами — и **его результат не читал НИКТО**. Файл без читателя ловит наш же
    сторож соответствия (ADR-066), и это ровно тот случай. Решение владельца
    2026-08-25 (вариант A): поставить поиск на расписание И завести НАСТОЯЩЕГО
    читателя находок в сводке. Эта функция — читатель.

    Три исхода, а не два (инв. #17):

    * ``fresh``   — файл есть и моложе ``max_age_days``;
    * ``stale``   — файл есть и старше: сколько именно суток, названо числом;
    * ``missing`` — файла нет. Это НЕ «кандидатов не нашлось».

    Порог 8 суток при недельном расписании: один пропуск не звенит, замолчавший
    агент звенит. Время — ВХОД, а не окружение.
    """
    now = now or datetime.now(timezone.utc)
    if not isinstance(d, dict) or not d:
        return {"state": "missing", "age_days": None, "found_total": None,
                "protocols": [], "max_age_days": max_age_days}
    summary = d.get("summary") if isinstance(d.get("summary"), dict) else {}
    protocols = []
    total = 0
    for name, row in sorted(summary.items()):
        if not isinstance(row, dict):
            continue
        found = row.get("found")
        found = int(found) if isinstance(found, int) else 0
        total += found
        protocols.append({"name": str(name), "found": found,
                          "top_pool_id": row.get("top_pool_id")})
    age_days = None
    gen = d.get("generated_at")
    if isinstance(gen, str):
        try:
            ts = datetime.fromisoformat(gen.replace("Z", "+00:00"))
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            age_days = (now - ts).total_seconds() / 86400.0
        except ValueError:
            age_days = None
    state = "fresh"
    if age_days is None:
        state = "unchecked"        # файл есть, но когда снят — не сказано
    elif age_days > max_age_days:
        state = "stale"
    return {"state": state, "age_days": None if age_days is None else round(age_days, 2),
            "found_total": total, "protocols": protocols, "max_age_days": max_age_days}


def build_source_discovery_section() -> str:
    """Кандидаты в новые источники доходности — читатель `source_discovery.json`.

    Раздел существует, чтобы у файла БЫЛ читатель: инструмент годами складывал
    находки, которые никто не открывал, и о новых источниках мы узнавали
    случайно — «если кто-нибудь вспомнит запустить скрипт».
    """
    st = source_discovery_state(read_json("source_discovery.json"))
    lines = ["## 🔎 Кандидаты в источники доходности (advisory)"]
    state = st["state"]
    if state == "missing":
        lines.append(
            "- `data/source_discovery.json` **отсутствует** — поиск ни разу не "
            "отработал в этом дереве. Это НЕ «кандидатов нет» (инв. #17). "
            "Агент `com.spa.source_discovery` подготовлен, установка — за владельцем "
            "(ADR-142)."
        )
        return "\n".join(lines)
    if state == "unchecked":
        lines.append("- файл есть, но **без отметки времени** — свежесть НЕ измерена.")
    elif state == "stale":
        lines.append(
            f"- ⚠️ находки **протухли**: {st['age_days']} сут при пороге "
            f"{st['max_age_days']:.0f} — поиск замолчал."
        )
    else:
        lines.append(f"- свежесть: {st['age_days']} сут (порог {st['max_age_days']:.0f}).")
    lines.append(f"- всего найдено пулов: **{st['found_total']}** "
                 f"по {len(st['protocols'])} протоколам.")
    if st["protocols"]:
        lines.append("")
        lines.append("| протокол | найдено | лучший пул |")
        lines.append("|---|---:|---|")
        for row in st["protocols"][:12]:
            lines.append(f"| {row['name']} | {row['found']} | "
                         f"{row['top_pool_id'] or '—'} |")
    lines.append("")
    lines.append("_Advisory: кандидаты НЕ становятся адаптерами сами — это список для "
                 "человека. Источник: `data/source_discovery.json` (ADR-142)._")
    return "\n".join(lines)

def build_knowledge_graph_section() -> str:
    """Связность базы знаний (ADR-154).

    27.08 сессия трижды не нашла существующее и трижды сказала «этого нет» вместо
    «не знаю, где смотреть». Причина: к этим файлам не ведёт ни одной ссылки.
    Замер при введении: 17.9 % связности при 903 сиротах.
    """
    d = read_json("knowledge_graph.json")
    if not d:
        return ("## 🕸 Связность знаний\n- **НЕ ИЗМЕРЕНО** — нет "
                "`data/knowledge_graph.json` (`scripts/build_knowledge_graph.py`)\n")
    lines = ["## 🕸 Связность знаний",
             f"- связность: **{d.get('connectivity_pct')}%** "
             f"({d.get('linked')} из {d.get('notes')} заметок достижимы по ссылкам)",
             f"- сирот: **{d.get('orphans')}** — находятся только угадыванием имени"]
    hubs = d.get("hubs") or []
    if hubs:
        lines.append(f"- главный концентратор: `{hubs[0].get('note')}` "
                     f"({hubs[0].get('out')} исходящих) — его устаревание рвёт доступ")
    return "\n".join(lines) + "\n"


def build_git_index_lag_section() -> str:
    """Отставание git-индекса рабочего дерева от origin (ADR-152).

    Замерено 27.08: сессия честно доложила «последний ADR — 078», тогда как на origin
    их 129 — включая ADR-125 о старте трёх пакетов. Сессия не проглядела: у неё
    физически не было файла. Индекс отставал на 1139 коммитов.

    Отставание — ШТАТНОЕ свойство, а не поломка: пуши уходят в origin напрямую через
    API и локального индекса не касаются, а синхронизация возит только spa_core/,
    scripts/, tests/, architecture/. Поэтому строка не тревога, а указатель: читать
    ADR/STATE/карточки надо из зеркала.
    """
    def _git(*args, cwd=PROJECT_ROOT):
        try:
            r = subprocess.run(["git", *args], cwd=cwd, capture_output=True,
                               text=True, timeout=20)
            return r.stdout.strip() if r.returncode == 0 else None
        except Exception:  # noqa: BLE001
            return None

    lines = ["## 🪞 Git index vs origin"]
    behind = _git("rev-list", "--count", "HEAD..origin/main")
    if behind is None:
        # «Не смогли посмотреть» ≠ «отставания нет» (инвариант #17).
        lines.append("- отставание: **НЕ ИЗМЕРЕНО** (git недоступен или нет origin/main)")
        return "\n".join(lines) + "\n"

    mirror = os.path.join(os.path.expanduser("~"), "Documents", "SPA_mirror")
    m_head = (_git("rev-parse", "--short", "HEAD", cwd=mirror)
              if os.path.isdir(os.path.join(mirror, ".git")) else None)
    lines.append(f"- рабочее дерево отстаёт от origin/main на **{behind}** коммит(ов) — "
                 f"это штатно (пуши идут в origin через API, минуя локальный индекс)")
    if m_head:
        lines.append(f"- зеркало `~/Documents/SPA_mirror` @ `{m_head}` — "
                     f"**ADR / STATE / карточки читать оттуда**")
    else:
        lines.append("- зеркало `~/Documents/SPA_mirror` **отсутствует** — "
                     "локальные `docs/` могут быть устаревшими, сверяться не с чем")
    return "\n".join(lines) + "\n"


def build_track_integrity_section() -> str:
    """Do the two records of the same money agree? (own-32)

    Renders the monitor's numbers — it does not recompute them. The section
    exists so the count cannot keep growing unread: between 2026-08-09 and
    2026-08-12 it went 16 → 18 with nobody looking.
    """
    st = track_integrity_state(read_json("cycle_health.json"))
    state = st.get("state")
    lines = ["## 🧾 Track integrity (доказательная база vs кривая)",
             track_integrity_cell(st)]

    if state in ("missing", "no_check", "unchecked"):
        lines.append(
            "\n_Источник — `data/cycle_health.json` → `checks.evidence_vs_curve` "
            "(пишет `com.spa.cycle_health`, каждые 300 с). Пустая строка здесь означала бы "
            "«сходится», поэтому её тут нет._")
        return "\n".join(lines) + "\n"

    div = st.get("divergent_days")
    if div:
        lines.append("")
        lines.append(f"- расходящихся дат: **{div}** из {st.get('compared_days')}")
        worst = st.get("max_delta_usd")
        if isinstance(worst, (int, float)):
            lines.append(f"- худшее расхождение: **${worst:,.2f}**")
        if st.get("latest_divergent"):
            lines.append(f"- последняя расходящаяся дата: **{st['latest_divergent']}**")
        lines.append(
            "- механизм — `own-32`: кривую пишут ДВА пути, и в день остановки они берут "
            "«вчера» из разных источников. Починка — money-path, ждёт владельца.")
    if state == "stale":
        lines.append(
            "- ⚠️ числа выше — ПОСЛЕДНИЕ ИЗВЕСТНЫЕ, а не текущие: снимок протух "
            "(проверь `com.spa.cycle_health`).")
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

    # Track-integrity header cell — same snapshot the detailed section renders, so
    # the two surfaces cannot disagree (the failure mode of #197: a guard narrower
    # than its ward is its echo, and two surfaces with two sources are worse still).
    track_cell = track_integrity_cell(track_integrity_state(read_json("cycle_health.json")))

    golive_icon = "✅" if golive_ready else "⛔"
    if agent_state == "missing":
        agent_icon = "❓"
        agent_cell = "❓ snapshot unavailable (agent_health.json missing)"
    elif agent_state == "stale":
        agent_icon = "⚠️"
        age_txt = f"{agent_age_min:.0f}m" if agent_age_min is not None else "unknown age"
        a_budget, a_src = snapshot_budget_min(agent_h, AGENT_SNAPSHOT_STALE_MIN)
        a_budget_txt = (f"{a_budget:.0f}m declared" if a_src == "declared"
                        else f"{a_budget:.0f}m fallback")
        agent_cell = (f"⚠️ SNAPSHOT STALE ({age_txt} > {a_budget_txt}) — "
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
| Track integrity | {track_cell} |
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
        build_track_integrity_section() + "\n",
        build_git_index_lag_section() + "\n",
        build_knowledge_graph_section() + "\n",
        build_source_discovery_section() + "\n",
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
