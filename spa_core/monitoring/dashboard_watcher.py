"""spa_core/monitoring/dashboard_watcher.py

Polls the live API every 5 min. Sends Telegram alerts on:
- Agent down / unhealthy (esp. critical agents)
- Portfolio anomaly (equity < $99K, equity > $110K, apy_today < -5%, is_demo flipped)
- System health CRITICAL (overall or any domain)
- API unreachable (Mac mini offline / FastAPI down)
- GoLive regression (passing count dropped)

Liveness pulse: once per 6 h, if everything is OK, send a short "all clear".
Otherwise — silent success (only alert on changes).

STDLIB ONLY. No LLM calls. Trusted source (our own JSON API on 127.0.0.1:8765).
Fail-safe: every network/IO call is wrapped; an exception never crashes the run.

Run via launchd every 5 min:
    python3 -m spa_core.monitoring.dashboard_watcher

Dedup / cooldown (same scheme as telegram_watcher.py):
    /tmp/spa_dw_seen_{hash}      seen alert  (TTL 2 h)
    /tmp/spa_dw_cooldown_{kind}  per-type cooldown (TTL 30 min)
    /tmp/spa_dw_pulse_last       last liveness pulse epoch
    /tmp/spa_dw_golive_last      last observed golive passing count
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
log = logging.getLogger("spa.monitoring.dashboard_watcher")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).resolve().parent.parent.parent  # repo root
DATA_DIR = BASE_DIR / "data"

API_BASE = os.environ.get("SPA_LIVE_API_BASE", "http://127.0.0.1:8765")
PING_PATH = "/api/live/ping"
AGENTS_PATH = "/api/live/agents"
PORTFOLIO_PATH = "/api/live/portfolio"
SYSTEM_PATH = "/api/live/system"

HTTP_TIMEOUT = 10        # seconds (normal endpoints)
PING_TIMEOUT = 5         # seconds (liveness)

# Telegram (Keychain, same services as telegram_watcher.py)
TOKEN_SERVICE = "TELEGRAM_BOT_TOKEN_SPA"
CHAT_ID_SERVICE = "TELEGRAM_CHAT_ID_SPA"

# Dedup / cooldown — module-level so tests can redirect to a temp dir.
TMP_PREFIX_SEEN = "/tmp/spa_dw_seen_"
TMP_PREFIX_COOLDOWN = "/tmp/spa_dw_cooldown_"
PULSE_FILE = "/tmp/spa_dw_pulse_last"
GOLIVE_FILE = "/tmp/spa_dw_golive_last"

DEDUP_TTL_SEC = 7_200    # 2 hours — same alert not repeated
COOLDOWN_TTL_SEC = 1_800  # 30 minutes — between alerts of the same type
PULSE_INTERVAL_SEC = 21_600  # 6 hours

# Portfolio thresholds
EQUITY_FLOOR = 99_000.0
EQUITY_CEIL = 110_000.0
APY_FLOOR = -5.0

# Critical launchd agents (short names, matched against label tail)
CRITICAL_AGENTS = {
    "daily_cycle", "autopush", "peg_monitor",
    "risk_monitor", "telegram_daily", "cycle_runner",
}

HEADER = "🖥️ <b>Dashboard Alert</b>\n━━━━━━━━━━━━━━━━━"


# ===========================================================================
# Keychain + Telegram (self-contained; HTML so underscores in labels survive)
# ===========================================================================

def _read_keychain(service: str) -> Optional[str]:
    """Read one generic-password from macOS Keychain. None on any failure."""
    try:
        proc = subprocess.run(
            ["security", "find-generic-password", "-s", service, "-w"],
            capture_output=True, text=True, timeout=5,
        )
        if proc.returncode == 0:
            val = proc.stdout.strip()
            if val:
                return val
    except Exception:
        pass
    return None


def get_bot_token() -> Optional[str]:
    return _read_keychain(TOKEN_SERVICE) or os.environ.get("TELEGRAM_BOT_TOKEN_SPA")


def get_chat_id() -> Optional[str]:
    return _read_keychain(CHAT_ID_SERVICE) or os.environ.get("TELEGRAM_CHAT_ID_SPA")


def send_telegram(text: str, token: Optional[str] = None,
                  chat_id: Optional[str] = None) -> bool:
    """Send an HTML message via the canonical telegram_client (single shared client
    with the 400→plain-text fallback). token/chat_id args kept for back-compat but
    ignored — the client reads creds from Keychain. Fail-safe → False on any error."""
    try:
        from spa_core.alerts.telegram_client import send_message
        return send_message(text, parse_mode="HTML")
    except Exception as exc:  # noqa: BLE001 — alerts must never crash the watcher
        log.warning("send_telegram error: %s", exc)
        return False


# ===========================================================================
# HTTP fetch (trusted own API)
# ===========================================================================

def fetch_json(path: str, timeout: int = HTTP_TIMEOUT) -> Optional[Any]:
    """GET a JSON endpoint from the live API. None on any failure (fail-safe)."""
    url = API_BASE + path
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode())
    except Exception as exc:
        log.warning("fetch %s failed: %s", path, exc)
        return None


# ===========================================================================
# Dedup / cooldown / pulse / golive state (file-based, /tmp)
# ===========================================================================

def _sha(text: str) -> str:
    return hashlib.sha1(text.encode()).hexdigest()[:16]


def _ttl_expired(path: str, ttl: int) -> bool:
    """True (and unlinks) if file is older than ttl; False if fresh."""
    try:
        age = time.time() - os.path.getmtime(path)
    except OSError:
        return True
    if age > ttl:
        try:
            os.unlink(path)
        except OSError:
            pass
        return True
    return False


def _is_seen(key: str) -> bool:
    path = TMP_PREFIX_SEEN + _sha(key)
    if not os.path.exists(path):
        return False
    return not _ttl_expired(path, DEDUP_TTL_SEC)


def _mark_seen(key: str) -> None:
    try:
        with open(TMP_PREFIX_SEEN + _sha(key), "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def _is_in_cooldown(kind: str) -> bool:
    path = TMP_PREFIX_COOLDOWN + _sha(kind)
    if not os.path.exists(path):
        return False
    return not _ttl_expired(path, COOLDOWN_TTL_SEC)


def _start_cooldown(kind: str) -> None:
    try:
        with open(TMP_PREFIX_COOLDOWN + _sha(kind), "w") as f:
            f.write(str(time.time()))
    except OSError:
        pass


def should_send_pulse(now: Optional[float] = None) -> bool:
    """True if no pulse was sent within PULSE_INTERVAL_SEC."""
    now = time.time() if now is None else now
    try:
        last = float(Path(PULSE_FILE).read_text().strip())
    except Exception:
        return True
    return (now - last) >= PULSE_INTERVAL_SEC


def mark_pulse(now: Optional[float] = None) -> None:
    now = time.time() if now is None else now
    try:
        Path(PULSE_FILE).write_text(str(now))
    except OSError:
        pass


def _read_golive_last() -> Optional[int]:
    try:
        return int(Path(GOLIVE_FILE).read_text().strip())
    except Exception:
        return None


def _write_golive_last(val: int) -> None:
    try:
        Path(GOLIVE_FILE).write_text(str(val))
    except OSError:
        pass


# ===========================================================================
# Normalization — accept BOTH the live-API verbatim shape (overall_status /
# status / issue) and the documented shape (overall / healthy / issues).
# ===========================================================================

def _short_label(label: str) -> str:
    return label.split(".")[-1] if label else label


def _norm_agents(data: Dict[str, Any]) -> Tuple[str, List[Dict[str, Any]]]:
    """Return (overall_upper, [{label, healthy, issues, log_age_min}])."""
    overall = str(data.get("overall") or data.get("overall_status") or "").upper()
    out: List[Dict[str, Any]] = []
    for ag in data.get("agents") or []:
        if not isinstance(ag, dict):
            continue
        label = ag.get("label", "")
        if "healthy" in ag:
            healthy = bool(ag["healthy"])
        else:
            healthy = str(ag.get("status") or "").upper() == "OK"
        if ag.get("issues"):
            issues = list(ag["issues"])
        elif ag.get("issue"):
            issues = [ag["issue"]]
        else:
            issues = []
        out.append({
            "label": label,
            "healthy": healthy,
            "issues": issues,
            "log_age_min": ag.get("log_age_min"),
        })
    return overall, out


def agents_summary(data: Dict[str, Any]) -> Tuple[int, int]:
    """(healthy_count, total) — prefers the API's own counters, else derives."""
    _, agents = _norm_agents(data)
    total = data.get("total_agents") or data.get("total") or len(agents)
    healthy = data.get("healthy_count")
    if healthy is None:
        healthy = sum(1 for a in agents if a["healthy"])
    return int(healthy), int(total)


def _normalize_portfolio(state: Dict[str, Any]) -> Dict[str, Any]:
    """Add canonical equity/apy_today aliases.

    The live cycle_runner writes ``current_equity`` / ``apy_today_pct``; the
    documented contract uses ``equity`` / ``apy_today``. Accept both.
    """
    out = dict(state)
    if out.get("equity") is None and state.get("current_equity") is not None:
        out["equity"] = state["current_equity"]
    if out.get("apy_today") is None and state.get("apy_today_pct") is not None:
        out["apy_today"] = state["apy_today_pct"]
    return out


def extract_portfolio(bundle: Any) -> Dict[str, Any]:
    """Pull the portfolio_state dict out of the /api/live/portfolio bundle.

    Accepts the bundle (keyed by filename) or a bare portfolio_state dict.
    Returns a normalized dict (canonical equity/apy_today aliases added).
    """
    if not isinstance(bundle, dict):
        return {}
    if isinstance(bundle.get("portfolio_state"), dict):
        return _normalize_portfolio(bundle["portfolio_state"])
    # Fallback: paper_trading_status may carry equity/is_demo too.
    if isinstance(bundle.get("paper_trading_status"), dict):
        return _normalize_portfolio(bundle["paper_trading_status"])
    # Already a bare state dict (test convenience).
    if any(k in bundle for k in ("equity", "current_equity", "is_demo",
                                 "apy_today", "apy_today_pct")):
        return _normalize_portfolio(bundle)
    return {}


def extract_system(bundle: Any) -> Dict[str, Any]:
    if isinstance(bundle, dict) and isinstance(bundle.get("system_health"), dict):
        return bundle["system_health"]
    return bundle if isinstance(bundle, dict) else {}


def extract_golive(bundle: Any) -> Dict[str, Any]:
    if isinstance(bundle, dict) and isinstance(bundle.get("golive_status"), dict):
        return bundle["golive_status"]
    return bundle if isinstance(bundle, dict) else {}


# ===========================================================================
# Checks — each returns a list of finding dicts (empty == OK).
# A finding: {"kind", "subtype", "key", ...payload}
# ===========================================================================

def check_agent_health(data: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(data, dict):
        return []
    overall, agents = _norm_agents(data)
    findings: List[Dict[str, Any]] = []

    if overall == "CRITICAL":
        crit = data.get("critical_count")
        warn = data.get("warning_count")
        findings.append({
            "kind": "agent", "subtype": "overall_critical",
            "key": "agent:overall_critical",
            "critical_count": crit, "warning_count": warn,
        })

    for ag in agents:
        if ag["healthy"]:
            continue
        is_critical = _short_label(ag["label"]) in CRITICAL_AGENTS
        findings.append({
            "kind": "agent", "subtype": "down",
            "key": f"agent:down:{ag['label']}",
            "label": ag["label"],
            "issues": ag["issues"],
            "log_age_min": ag["log_age_min"],
            "critical": is_critical,
        })
    return findings


def check_portfolio(pstate: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(pstate, dict) or not pstate:
        return []
    findings: List[Dict[str, Any]] = []

    if pstate.get("is_demo") is True:
        findings.append({
            "kind": "portfolio", "subtype": "is_demo",
            "key": "portfolio:is_demo",
        })

    equity = pstate.get("equity")
    if isinstance(equity, (int, float)):
        if equity < EQUITY_FLOOR:
            findings.append({
                "kind": "portfolio", "subtype": "equity_low",
                "key": "portfolio:equity_low", "equity": equity,
            })
        elif equity > EQUITY_CEIL:
            findings.append({
                "kind": "portfolio", "subtype": "equity_high",
                "key": "portfolio:equity_high", "equity": equity,
            })

    apy = pstate.get("apy_today")
    if isinstance(apy, (int, float)) and apy < APY_FLOOR:
        findings.append({
            "kind": "portfolio", "subtype": "apy_low",
            "key": "portfolio:apy_low", "apy": apy,
        })
    return findings


def check_system_health(sh: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not isinstance(sh, dict):
        return []
    overall = str(sh.get("overall") or sh.get("overall_status") or "").upper()
    findings: List[Dict[str, Any]] = []

    if overall == "CRITICAL":
        findings.append({
            "kind": "system", "subtype": "overall_critical",
            "key": "system:overall_critical",
        })

    for name, dom in (sh.get("domains") or {}).items():
        status = dom.get("status") if isinstance(dom, dict) else dom
        if str(status).upper() == "CRITICAL":
            findings.append({
                "kind": "system", "subtype": "domain_critical",
                "key": f"system:domain_critical:{name}", "domain": name,
            })
    return findings


def check_api_availability(ping: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if isinstance(ping, dict) and ping.get("ok"):
        return []
    return [{
        "kind": "api", "subtype": "unreachable", "key": "api:unreachable",
    }]


def check_golive(golive: Optional[Dict[str, Any]],
                 last_passing: Optional[int]) -> List[Dict[str, Any]]:
    if not isinstance(golive, dict):
        return []
    now = golive.get("passed", golive.get("passing_count"))
    if not isinstance(now, int):
        return []
    if last_passing is not None and now < last_passing:
        return [{
            "kind": "golive", "subtype": "regression", "key": "golive:regression",
            "prev": last_passing, "now": now,
            "total": golive.get("total"),
        }]
    return []


# ===========================================================================
# Formatting
# ===========================================================================

def _money(x: Any) -> str:
    try:
        return f"${float(x):,.0f}"
    except (TypeError, ValueError):
        return "$?"


def _footer(ctx: Dict[str, Any]) -> str:
    lines: List[str] = []
    p = ctx.get("portfolio") or {}
    parts: List[str] = []
    if isinstance(p.get("equity"), (int, float)):
        parts.append(_money(p["equity"]))
    if isinstance(p.get("apy_today"), (int, float)):
        parts.append(f"APY {p['apy_today']:.2f}%")
    if parts:
        lines.append("📊 Portfolio: " + " · ".join(parts))
    h, t = ctx.get("healthy"), ctx.get("total")
    if h is not None and t is not None:
        lines.append(f"🤖 Agents: {h}/{t} OK")
    return ("\n\n" + "\n".join(lines)) if lines else ""


def format_agent_alert(finding: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    if finding["subtype"] == "overall_critical":
        crit = finding.get("critical_count")
        warn = finding.get("warning_count")
        body = "🔴 Agent health CRITICAL"
        tail = []
        if crit is not None:
            tail.append(f"{crit} critical")
        if warn is not None:
            tail.append(f"{warn} warning")
        if tail:
            body += " — " + ", ".join(tail)
    else:
        icon = "🔴" if finding.get("critical") else "⚠️"
        suffix = " (CRITICAL agent)" if finding.get("critical") else ""
        body = f"{icon} Agent DOWN: {finding['label']}{suffix}"
        age = finding.get("log_age_min")
        if isinstance(age, (int, float)):
            body += f"\nLast seen: {age:.1f} мин назад"
        if finding.get("issues"):
            body += "\nIssues: " + "; ".join(str(i) for i in finding["issues"])
    return f"{HEADER}\n{body}{_footer(ctx)}"


def format_portfolio_alert(finding: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    st = finding["subtype"]
    if st == "is_demo":
        body = "🚨 is_demo flipped to TRUE — paper mode regression! (someone switched back to test mode)"
    elif st == "equity_low":
        body = f"💰 Equity below floor: {_money(finding['equity'])} (< {_money(EQUITY_FLOOR)}, loss > 1%)"
    elif st == "equity_high":
        body = f"📈 Equity anomalously high: {_money(finding['equity'])} (> {_money(EQUITY_CEIL)} — possible bug)"
    elif st == "apy_low":
        body = f"📉 Daily APY {finding['apy']:.2f}% (< {APY_FLOOR}% — daily loss > 5%)"
    else:
        body = "💰 Portfolio anomaly"
    return f"{HEADER}\n{body}{_footer(ctx)}"


def format_system_alert(finding: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    if finding["subtype"] == "domain_critical":
        body = f"🔴 System domain CRITICAL: {finding['domain']}"
    else:
        body = "🔴 System health CRITICAL (overall)"
    return f"{HEADER}\n{body}{_footer(ctx)}"


def format_api_alert(finding: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    return (f"{HEADER}\n⚠️ Live API недоступен — Mac mini офлайн или FastAPI упал\n"
            f"({API_BASE}{PING_PATH} не ответил за {PING_TIMEOUT}s)")


def format_golive_alert(finding: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    total = finding.get("total")
    now = finding["now"]
    now_str = f"{now}/{total}" if total else str(now)
    body = (f"📉 GoLive regression: passing dropped "
            f"{finding['prev']} → {now_str}")
    return f"{HEADER}\n{body}{_footer(ctx)}"


def format_pulse(ctx: Dict[str, Any]) -> str:
    p = ctx.get("portfolio") or {}
    h, t = ctx.get("healthy"), ctx.get("total")
    parts: List[str] = []
    if h is not None and t is not None:
        parts.append(f"{h}/{t} agents")
    if isinstance(p.get("equity"), (int, float)):
        parts.append(f"equity {_money(p['equity'])}")
    if isinstance(p.get("apy_today"), (int, float)):
        parts.append(f"APY {p['apy_today']:.2f}%")
    tail = (" — " + ", ".join(parts)) if parts else ""
    return f"✅ Dashboard check OK{tail}"


_FORMATTERS = {
    "agent": format_agent_alert,
    "portfolio": format_portfolio_alert,
    "system": format_system_alert,
    "api": format_api_alert,
    "golive": format_golive_alert,
}


def format_finding(finding: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    return _FORMATTERS[finding["kind"]](finding, ctx)


# ===========================================================================
# Orchestration
# ===========================================================================

def maybe_send(finding: Dict[str, Any], ctx: Dict[str, Any]) -> bool:
    """Send the alert unless deduped or in cooldown. Returns True if sent."""
    key = finding["key"]
    kind = finding["kind"]
    if _is_seen(key):
        log.info("Duplicate alert skipped: %s", key)
        return False
    if _is_in_cooldown(kind):
        log.info("Cooldown active for kind=%s — skipping %s", kind, key)
        return False
    _mark_seen(key)  # mark immediately to avoid parallel double-send
    text = format_finding(finding, ctx)
    if send_telegram(text):
        _start_cooldown(kind)
        log.info("Alert sent: %s", key)
        return True
    log.warning("Alert send failed: %s", key)
    return False


def run_once() -> None:
    """Single pass: poll the live API, run checks, alert or pulse."""
    # 1. Liveness first — if the API is down, that IS the alert; bail out.
    ping = fetch_json(PING_PATH, timeout=PING_TIMEOUT)
    api_findings = check_api_availability(ping)
    if api_findings:
        log.warning("Live API unreachable")
        maybe_send(api_findings[0], {})
        return

    # 2. Fetch the three bundles (fail-safe).
    agents_data = fetch_json(AGENTS_PATH)
    portfolio_bundle = fetch_json(PORTFOLIO_PATH)
    system_bundle = fetch_json(SYSTEM_PATH)

    pstate = extract_portfolio(portfolio_bundle)
    sh = extract_system(system_bundle)
    golive = extract_golive(system_bundle)

    # 3. Context for footers/pulse.
    if isinstance(agents_data, dict) and agents_data.get("agents") is not None:
        healthy, total = agents_summary(agents_data)
    else:
        healthy = total = None
    ctx = {"portfolio": pstate, "healthy": healthy, "total": total}

    # 4. Run checks.
    findings: List[Dict[str, Any]] = []
    findings += check_agent_health(agents_data)
    findings += check_portfolio(pstate)
    findings += check_system_health(sh)

    last_golive = _read_golive_last()
    gl_findings = check_golive(golive, last_golive)
    findings += gl_findings
    now_passing = golive.get("passed", golive.get("passing_count")) if isinstance(golive, dict) else None
    if isinstance(now_passing, int):
        _write_golive_last(now_passing)

    # 5. Emit alerts or (if nothing wrong) a 6-hourly liveness pulse.
    sent = 0
    for f in findings:
        if maybe_send(f, ctx):
            sent += 1

    if not findings:
        if should_send_pulse():
            if send_telegram(format_pulse(ctx)):
                mark_pulse()
                log.info("Liveness pulse sent")
        else:
            log.info("All OK — silent success (pulse not due)")
    else:
        log.info("Done. %d/%d alert(s) sent", sent, len(findings))


def main() -> None:
    log.info("=== SPA Dashboard Watcher starting ===")
    try:
        run_once()
    except Exception as exc:  # fail-safe: never crash the launchd job
        log.critical("Unhandled error in run_once: %s", exc, exc_info=True)
    log.info("=== SPA Dashboard Watcher done ===")


if __name__ == "__main__":
    main()
