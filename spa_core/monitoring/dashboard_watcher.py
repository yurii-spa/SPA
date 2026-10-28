"""spa_core/monitoring/dashboard_watcher.py

Polls the live API every 5 min. Sends Telegram alerts on:
- Agent down / unhealthy (esp. critical agents)
- Portfolio anomaly (equity < $99K, equity > $110K, apy_today < -5%, is_demo flipped)
- System health CRITICAL (overall or any domain)
- API unreachable (Mac mini offline / FastAPI down)
- GoLive regression (passing count dropped)

Liveness pulse: once per 6 h, if everything is OK, send a short "all clear".
Otherwise — silent success (only alert on changes).

HONESTY (invariant #2, fail-CLOSED): an empty finding list means "nothing is
wrong", NOT "nothing was measured". Every input that could not be evaluated
(endpoint unreachable, unexpected shape, missing field, unrecognized status,
absent go-live baseline) is collected by ``collect_unchecked`` and:
  - blocks the green "✅ Dashboard check OK" pulse — it says INCOMPLETE and
    names what was not measured;
  - is appended to any alert that goes out anyway (same volume, more truth).
UNCHECKED is deliberately NOT escalated into an alert of its own: this agent
runs every 5 min and a new alert kind would be pure noise. Thresholds
(EQUITY_FLOOR / EQUITY_CEIL / APY_FLOOR / CRITICAL_AGENTS) are untouched.

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

#: Контракт агента (ADR-154/158): что этот агент ПРОИЗВОДИТ.
#: ПУСТО — это ОТВЕТ «артефактов не произвожу», а не незаполненное поле.
#: Проверено чтением модуля и его пакета 28.08: пишет только в /tmp (пульс, кулдауны дедупа) — это эфемерное состояние процесса, а не артефакт флота; результат уезжает ВЛАДЕЛЬЦУ тревогой.
#: Следствие (ADR-154): раз свежесть файла тут ни при чём, метрикой качества
#: должен стать другой признак — доступность/факт отправки. Открыто карточкой.
PRODUCES = ()

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

# TELEGRAM-OWNER-UX-01 (ADR-OWN-2026-10-28): «не OK» у агента — это НЕ одно состояние.
# До правки каждая запись healthy=False становилась subtype=down → «Agent DOWN», и
# измеренное предупреждение resource_guard (код 1 по его договору) владелец читал как
# «упал сторож ×12». Теперь состояние называется тем, чем оно измерено:
#   stopped   — процесс точно не работает (не загружен / сервер с PID=0);
#   critical  — агент в критическом состоянии по замеру agent_health (не обязательно остановлен);
#   warning   — предупреждение агента (процесс может работать);
#   measured  — агент-ЗАМЕР штатно сообщил плохой результат замера кодом выхода по договору;
#   stale     — снимок о нём устарел;  unchecked — состояние не измерено (третий исход, инв. #17).
# Отключённый владельцем агент приходит со статусом OK и пометкой — находкой он не является.
AGENT_STOPPED = "stopped"
AGENT_CRITICAL = "critical"
AGENT_WARNING = "warning"
AGENT_MEASURED = "measured"
AGENT_STALE = "stale"
AGENT_UNCHECKED = "unchecked"
#: Документированная форма ``{"healthy": false}`` без статуса — прежний контракт «down».
AGENT_DOWN_LEGACY = "down"

#: Агенты, у которых код выхода — ВЕРДИКТ замера, а не исход процесса. Договор
#: resource_guard: 0 OK · 1 WARN · 2 CRITICAL или «не измерено». Замером здесь читается
#: ровно то, что так прочитал agent_health (ARB 27.10): код 1. Код 2 ARB оставил прежней
#: веткой («как прежде» — он же и аварийный выход процесса), поэтому и здесь он остаётся
#: предупреждением агента, а не «штатным замером» (fail-CLOSED).
MEASUREMENT_VERDICT_AGENTS: Dict[str, Dict[int, str]] = {
    "com.spa.resource_guard": {
        1: "контроль ресурсов Mac сообщает о нехватке ресурсов (замер: предупреждение)",
    },
}

_AGENT_STATE_RU: Dict[str, str] = {
    AGENT_STOPPED: "не работает",
    AGENT_CRITICAL: "критическое состояние (процесс может работать — см. причину)",
    AGENT_WARNING: "предупреждение (это не остановка агента)",
    AGENT_STALE: "сведения о нём устарели",
    AGENT_UNCHECKED: "состояние не измерено",
    AGENT_DOWN_LEGACY: "отмечен как неисправный (вид неисправности источник не указал)",
}

# Status vocabularies actually emitted by the producers we read (agent_health_
# monitor / system_health_monitor). Anything outside these is reported as
# "not measured" with the value quoted verbatim, never silently read as healthy.
KNOWN_OVERALL_STATUSES = frozenset({
    "OK", "HEALTHY", "WARNING", "STALE", "DEGRADED", "CRITICAL", "UNCHECKED",
})
KNOWN_DOMAIN_STATUSES = KNOWN_OVERALL_STATUSES


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


def route_to_digest(text: str, *, title: str = "Dashboard watcher finding",
                    severity: str = "INFO", incident: Optional[str] = None,
                    summary: Optional[str] = None) -> bool:
    """Append one finding to the digest queue. True iff it was enqueued.

    This is the watcher's ONLY outbound path (the Telegram push is retired, see
    ``send_telegram``). It returns the *routing* result — callers that keep
    cadence state (``mark_pulse``) need to know whether the item actually
    landed, and ``send_telegram``'s "always False" contract cannot tell them.
    Never raises.
    """
    try:
        from spa_core.telegram import push_policy
        push_policy._enqueue_digest(
            push_policy._tg_dir(),
            {
                "ts": push_policy._now_iso(),
                "event_key": "dashboard_watch",
                "severity": severity,
                "title": title,
                "body": text[:500],
                "reason": "dashboard_watcher_retired_push",
                # Идентичность инцидента и смысловая строка (TELEGRAM-OWNER-UX-01):
                # сводка объединяет по ним, а не по первым 120 символам текста.
                **({"incident": incident} if incident else {}),
                **({"summary": summary} if summary else {}),
            },
        )
        return True
    except Exception as exc:  # noqa: BLE001 — never crash the watcher
        log.warning("route_to_digest error: %s", exc)
        return False


def send_telegram(text: str, token: Optional[str] = None,
                  chat_id: Optional[str] = None, *, incident: Optional[str] = None,
                  summary: Optional[str] = None, severity: str = "INFO") -> bool:
    """RETIRED as a Telegram push (Phase-1 Telegram rebuild).

    dashboard_watcher used to push ~26 alerts/day every 5 min. Everything it
    reports (agent/portfolio/system/api/golive) is now answered on demand by the
    interactive bot's ``/status`` ``/agents`` ``/alerts`` views, so it MUST NOT
    interrupt the owner. The watcher keeps RUNNING and DETECTING, but its
    findings are routed to the digest queue (folded into the one daily digest)
    instead of pushed. token/chat_id args kept for back-compat (ignored).
    Always returns False (nothing was PUSHED) — kept deliberately, since that is
    the published contract; internal callers that need the routing result use
    ``route_to_digest`` instead. Never raises.
    """
    route_to_digest(text, incident=incident, summary=summary, severity=severity)
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
            # Сырые поля состояния — чтобы классификация говорила то, что измерено,
            # а не сводила любое «не OK» к остановке.
            "status": (str(ag["status"]).upper() if ag.get("status") is not None else None),
            "pid": ag.get("pid"),
            "last_exit": ag.get("last_exit"),
            "loaded": ag.get("loaded"),
            "category": ag.get("category"),
        })
    return overall, out


def classify_agent(ag: Dict[str, Any]) -> str:
    """Вид неисправности агента — по ИЗМЕРЕННОМУ состоянию, а не по «не OK».

    Порядок важен: замер по договору проверяется первым только для объявленных меток и
    объявленных кодов; «остановлен» — только при прямом признаке (не загружен / сервер
    с PID=0); прочий CRITICAL остаётся критическим, но не называется остановкой.
    """
    label = ag.get("label") or ""
    status = ag.get("status")
    last_exit = ag.get("last_exit")
    contract = MEASUREMENT_VERDICT_AGENTS.get(label)
    if (contract and isinstance(last_exit, int) and not isinstance(last_exit, bool)
            and last_exit in contract and not ag.get("pid")
            and status == "WARNING" and ag.get("loaded") is not False):
        # Только WARNING: agent_health ставит по коду 1 ровно WARNING; CRITICAL у той же метки
        # пришёл бы из ДРУГОЙ причины (лог, загрузка) и «штатным замером» не является.
        return AGENT_MEASURED
    # Остановка — только по ИЗМЕРЕННОМУ признаку agent_health. Одно `loaded: false` им не является:
    # календарный агент между запусками штатно не загружен и судится свежестью лога.
    issues = " ".join(str(i) for i in ag.get("issues") or [])
    if "PID=0 (server down)" in issues or "not loaded in launchctl" in issues:
        return AGENT_STOPPED
    if status == "CRITICAL":
        return AGENT_CRITICAL
    if status == "WARNING":
        return AGENT_WARNING
    if status == "STALE":
        return AGENT_STALE
    if status is None:
        return AGENT_DOWN_LEGACY
    # UNCHECKED и любой неизвестный статус — «не измерено», значение сохраняется в причинах.
    return AGENT_UNCHECKED


def _as_int(value: Any) -> Optional[int]:
    """int(value) or None — bools and un-coercible values are NOT numbers."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _is_number(value: Any) -> bool:
    """True for a real int/float (bool is not a measurement)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def agents_summary(data: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    """(healthy_count, total) — prefers the API's own counters, else derives.

    Returns ``None`` for a counter that cannot be read as an integer instead of
    raising: a ``TypeError`` here used to escape into ``main()``'s catch-all and
    void the whole tick silently (launchd still saw exit 0).
    """
    if not isinstance(data, dict):
        return None, None
    _, agents = _norm_agents(data)
    total = _as_int(data.get("total_agents") or data.get("total"))
    if total is None:
        total = len(agents)
    healthy = _as_int(data.get("healthy_count"))
    if healthy is None and data.get("healthy_count") is None:
        healthy = sum(1 for a in agents if a["healthy"])
    return healthy, total


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
# UNCHECKED accounting — what could NOT be evaluated this run.
#
# An empty finding list from the check_* functions below means "no problem
# found"; it does NOT mean "the input was readable". These functions answer the
# second question, so the pulse can tell "all clear" from "never looked".
# Each entry: {"check": <agents|portfolio|system|golive>, "reason": <text>}.
# Unknown values are quoted VERBATIM — never normalized into a healthy status.
# ===========================================================================

def _u(check: str, reason: str) -> Dict[str, str]:
    return {"check": check, "reason": reason}


def unchecked_agents(data: Any) -> List[Dict[str, str]]:
    """Report what the /api/live/agents payload did not let us measure."""
    if data is None:
        return [_u("agents", "live API /api/live/agents returned nothing "
                             "(unreachable or non-JSON)")]
    if not isinstance(data, dict):
        return [_u("agents", f"unexpected response type: {type(data).__name__}")]

    out: List[Dict[str, str]] = []
    agents = data.get("agents")
    if not isinstance(agents, list):
        out.append(_u("agents", "response carries no agents list "
                                f"(keys: {sorted(data.keys())[:8]})"))
    elif not agents:
        out.append(_u("agents", "agents list is empty — no agent was evaluated"))

    raw_overall = data.get("overall") or data.get("overall_status")
    if raw_overall is None or str(raw_overall).strip() == "":
        out.append(_u("agents", "fleet overall status absent — "
                                "'overall CRITICAL' not measurable"))
    elif str(raw_overall).upper() not in KNOWN_OVERALL_STATUSES:
        out.append(_u("agents", f"unrecognized overall status: {raw_overall!r}"))
    return out


def unchecked_portfolio(pstate: Any) -> List[Dict[str, str]]:
    """Report which portfolio thresholds could not be evaluated."""
    if not isinstance(pstate, dict) or not pstate:
        return [_u("portfolio", "bundle carries neither portfolio_state nor "
                                "paper_trading_status — no threshold evaluated")]

    out: List[Dict[str, str]] = []
    if pstate.get("is_demo") is None:
        out.append(_u("portfolio", "is_demo absent — paper-mode regression "
                                   "not measurable"))
    equity = pstate.get("equity")
    if not _is_number(equity):
        out.append(_u("portfolio", f"equity absent or non-numeric: {equity!r} — "
                                   "floor/ceiling not measurable"))
    apy = pstate.get("apy_today")
    if not _is_number(apy):
        out.append(_u("portfolio", f"apy_today absent or non-numeric: {apy!r} — "
                                   "daily-loss floor not measurable"))
    return out


def unchecked_system(sh: Any) -> List[Dict[str, str]]:
    """Report which system-health verdicts could not be evaluated."""
    if not isinstance(sh, dict) or not sh:
        return [_u("system", "bundle carries no system_health block")]

    out: List[Dict[str, str]] = []
    raw_overall = sh.get("overall") or sh.get("overall_status")
    if raw_overall is None or str(raw_overall).strip() == "":
        out.append(_u("system", "overall status absent — "
                                "'overall CRITICAL' not measurable"))
    elif str(raw_overall).upper() not in KNOWN_OVERALL_STATUSES:
        out.append(_u("system", f"unrecognized overall status: {raw_overall!r}"))

    domains = sh.get("domains")
    if not isinstance(domains, dict):
        out.append(_u("system", "no domains block — per-domain CRITICAL "
                                "not measurable"))
    elif not domains:
        out.append(_u("system", "domains block is empty — no domain evaluated"))
    else:
        for name, dom in domains.items():
            status = dom.get("status") if isinstance(dom, dict) else dom
            if status is None or str(status).upper() not in KNOWN_DOMAIN_STATUSES:
                out.append(_u("system", f"domain {name!r}: unrecognized status "
                                        f"{status!r}"))
    return out


def unchecked_golive(golive: Any,
                     last_passing: Optional[int]) -> List[Dict[str, str]]:
    """Report whether a go-live regression could be detected at all."""
    if not isinstance(golive, dict) or not golive:
        return [_u("golive", "bundle carries no golive_status block")]

    now = golive.get("passed", golive.get("passing_count"))
    if not isinstance(now, int) or isinstance(now, bool):
        return [_u("golive", f"passing count absent or non-integer: {now!r}")]
    if last_passing is None:
        return [_u("golive", "no previous passing count on record (first run or "
                             "/tmp cleared) — regression not measurable, "
                             f"baseline set to {now}")]
    return []


def collect_unchecked(agents_data: Any, pstate: Any, sh: Any, golive: Any,
                      last_passing: Any) -> List[Dict[str, str]]:
    """All four accounts in a stable order. Never raises."""
    out: List[Dict[str, str]] = []
    for fn, args in (
        (unchecked_agents, (agents_data,)),
        (unchecked_portfolio, (pstate,)),
        (unchecked_system, (sh,)),
        (unchecked_golive, (golive, last_passing if isinstance(last_passing, int)
                            and not isinstance(last_passing, bool) else None)),
    ):
        try:
            out.extend(fn(*args))
        except Exception as exc:  # noqa: BLE001 — an accounting bug must not
            # blind the watcher, but it must not pass for "measured" either.
            out.append(_u(getattr(fn, "__name__", "unknown").replace(
                "unchecked_", ""), f"accounting failed: {exc}"))
    return out


# ===========================================================================
# Checks — each returns a list of finding dicts (empty == OK, NOT "measured").
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
        subtype = classify_agent(ag)
        if subtype == AGENT_UNCHECKED and ag.get("status") not in (None, "UNCHECKED"):
            # Неизвестный статус не выдаётся за «здоров» и не теряется — назван дословно.
            ag["issues"] = list(ag["issues"]) + [f"статус источника: {ag['status']}"]
        findings.append({
            "kind": "agent", "subtype": subtype,
            "key": f"agent:{subtype}:{ag['label']}",
            "label": ag["label"],
            "issues": ag["issues"],
            "log_age_min": ag["log_age_min"],
            "last_exit": ag.get("last_exit"),
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


def _unchecked_names(unchecked: Any) -> List[str]:
    """Distinct check names, first-seen order. Tolerates a malformed list."""
    names: List[str] = []
    if not isinstance(unchecked, list):
        return names
    for u in unchecked:
        name = u.get("check") if isinstance(u, dict) else None
        if name and name not in names:
            names.append(str(name))
    return names


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
    # An alert that goes out anyway must disclose what was NOT measured —
    # otherwise the numbers above read as a complete picture. Names only (the
    # reasons are in the log); this adds no new item, only truth to an existing.
    names = _unchecked_names(ctx.get("unchecked"))
    if names:
        lines.append("⚠️ Not measured: " + ", ".join(names))
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
        body = agent_summary(finding)
        age = finding.get("log_age_min")
        if isinstance(age, (int, float)):
            body += f"\nПоследняя запись в журнале агента: {age:.1f} мин назад"
        if finding.get("issues"):
            body += "\nПричина: " + "; ".join(_issue_ru(i) for i in finding["issues"])
    return f"{HEADER}\n{body}{_footer(ctx)}"


def _finding_severity(finding: Dict[str, Any]) -> str:
    """Степень находки для очереди сводки: остановка/критика ключевого — CRITICAL.

    До 28.10 всё уходило как INFO, и сводка считала критичным только тело со словом
    «CRITICAL»; остановленный ключевой агент терялся среди предупреждений.
    """
    sub = finding.get("subtype")
    if sub == "overall_critical" or (sub in (AGENT_STOPPED, AGENT_CRITICAL) and finding.get("critical")):
        return "CRITICAL"
    if sub in (AGENT_STOPPED, AGENT_CRITICAL, AGENT_WARNING, AGENT_MEASURED, AGENT_DOWN_LEGACY):
        return "WARNING"
    return "INFO"


def _issue_ru(issue: Any) -> str:
    """Причина простым языком через общий словарь humanize; нераспознанное — дословно."""
    text = str(issue)
    try:
        from spa_core.telegram import humanize
        return humanize.humanize_body(text)
    except Exception:  # noqa: BLE001 — причина обязана дойти, хоть и технической строкой
        return text


def agent_summary(finding: Dict[str, Any]) -> str:
    """Одна строка: ЧТО с агентом — тем видом состояния, который измерен.

    Её же кладём в очередь сводки как ``summary``: дневная сводка и отдельная тревога
    говорят одно и то же (TELEGRAM-OWNER-UX-01, п. 2).
    """
    label = finding.get("label") or "?"
    subtype = finding.get("subtype")
    if subtype == AGENT_MEASURED:
        words = MEASUREMENT_VERDICT_AGENTS.get(label, {}).get(finding.get("last_exit"))
        if words:
            return f"⚠️ {words[0].upper()}{words[1:]}; агент отработал штатно ({label})"
    crit = finding.get("critical")
    icon = "🔴" if subtype in (AGENT_STOPPED, AGENT_CRITICAL) or crit else "⚠️"
    state = _AGENT_STATE_RU.get(subtype, "неизвестное состояние")
    who = "ключевой агент" if crit else "агент"
    return f"{icon} {who[0].upper()}{who[1:]} {label}: {state}"


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


def format_pulse(ctx: Dict[str, Any],
                 unchecked: Optional[List[Dict[str, str]]] = None) -> str:
    """The 6-hourly liveness line.

    "✅ OK" is claimed ONLY when every check actually ran. If anything was
    unmeasured the pulse says INCOMPLETE and names each unmeasured check with
    its reason — an empty finding list is not evidence of health.
    """
    p = ctx.get("portfolio") or {}
    h, t = ctx.get("healthy"), ctx.get("total")
    parts: List[str] = []
    if h is not None and t is not None:
        parts.append(f"{h}/{t} agents")
    if _is_number(p.get("equity")):
        parts.append(f"equity {_money(p['equity'])}")
    if _is_number(p.get("apy_today")):
        parts.append(f"APY {p['apy_today']:.2f}%")
    tail = (" — " + ", ".join(parts)) if parts else ""

    if unchecked is None:
        unchecked = ctx.get("unchecked")  # type: ignore[assignment]
    if unchecked:
        detail = "\n".join(f"• {u.get('check', '?')}: {u.get('reason', '?')}"
                           for u in unchecked if isinstance(u, dict))
        measured = f"\nMeasured{tail}" if tail else ""
        return ("⚠️ Dashboard check INCOMPLETE — not measured:\n"
                f"{detail}{measured}")
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
    """Publish the finding unless deduped or in cooldown. True iff PUSHED.

    Unchanged on purpose. ``send_telegram`` routes the text to the digest queue
    and returns False (the push is retired), so:
      - dedup (per key, 2 h) is what actually limits volume today;
      - the per-kind cooldown stays inert, exactly as it has been since the push
        was retired. Arming it here would suppress a *second, distinct* finding
        of the same kind within 30 min — i.e. silently drop information from the
        daily digest — so the cooldown is left as the author wrote it, for
        whoever revives pushes later.
    """
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
    # Push retired: the finding goes to the digest queue WITH its incident identity and
    # one-line meaning, so the digest folds repeats of the same incident (and only them).
    summary = agent_summary(finding) if kind == "agent" and finding.get("subtype") != "overall_critical" else None
    if send_telegram(text, incident=key, summary=summary, severity=_finding_severity(finding)):  # retired push: routes to digest, returns False
        _start_cooldown(kind)
        log.info("Alert pushed: %s", key)
        return True
    log.info("Finding routed to digest, not pushed (push retired): %s", key)
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

    last_golive = _read_golive_last()

    # 3a. What could NOT be measured this run (before any verdict is published).
    unchecked = collect_unchecked(agents_data, pstate, sh, golive, last_golive)
    ctx = {"portfolio": pstate, "healthy": healthy, "total": total,
           "unchecked": unchecked}

    # 4. Run checks.
    findings: List[Dict[str, Any]] = []
    findings += check_agent_health(agents_data)
    findings += check_portfolio(pstate)
    findings += check_system_health(sh)

    gl_findings = check_golive(golive, last_golive)
    findings += gl_findings
    now_passing = golive.get("passed", golive.get("passing_count")) if isinstance(golive, dict) else None
    if isinstance(now_passing, int) and not isinstance(now_passing, bool):
        _write_golive_last(now_passing)

    if unchecked:
        log.warning("Not measured this run: %s",
                    "; ".join(f"{u['check']}: {u['reason']}" for u in unchecked))

    # 5. Publish alerts or (if nothing wrong) a 6-hourly liveness pulse.
    pushed = 0
    for f in findings:
        if maybe_send(f, ctx):
            pushed += 1

    if not findings:
        # No finding is NOT the same as "everything checked out" — the pulse
        # text distinguishes the two (see format_pulse).
        if should_send_pulse():
            send_telegram(format_pulse(ctx, unchecked))
            # Advance the cadence on PUBLICATION, not on push-delivery. The push
            # is retired: send_telegram routes the text to the digest queue and
            # always reports False, so gating mark_pulse() on its return value
            # left should_send_pulse() permanently True — the pulse was enqueued
            # on every 5-minute run (≈288/day) instead of once per 6 h, and the
            # queue's 500-item cap then evicted real demoted events.
            mark_pulse()
            log.info("Liveness pulse published (%s)",
                     "INCOMPLETE" if unchecked else "OK")
        else:
            log.info("Nothing to report (pulse not due)")
    else:
        log.info("Done. %d finding(s); %d pushed, the rest routed to the digest "
                 "(push retired)", len(findings), pushed)


def main() -> None:
    log.info("=== SPA Dashboard Watcher starting ===")
    try:
        run_once()
    except Exception as exc:  # fail-safe: never crash the launchd job
        log.critical("Unhandled error in run_once: %s", exc, exc_info=True)
    log.info("=== SPA Dashboard Watcher done ===")


if __name__ == "__main__":
    main()
