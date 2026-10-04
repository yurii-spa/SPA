"""spa_core/studio_os/mission_control.py — Mission Control v1 read model (ADR-552).

ONE read model for the Owner Remote / Mission Control UI. It owns no state: every value is READ from a
canonical source named in ``CONTRACT`` and re-projected with the shared status vocabulary. The UI reads
only the JSON this module produces (``python -m spa_core.studio_os.mission_control --out <file>``); it
never scrapes data files itself.

Rules (frozen by the architecture gate, tested by ``test_mission_control_contract.py``):

* **One truth.** Studio OS state (tasks, agents, evidence, releases, system) comes from the build loop /
  tracker / Director collector / resource guard; Capital state (strategies, positions, research) from
  ``package_status.public_view`` and the Trading Research status file. The two are separate top-level
  areas — the boundary is visible in the UI and in this file (``AREAS``).
* **No data ⇒ NOT_MEASURED / UNKNOWN, never healthy, zero or empty.** A source that cannot be read
  makes its section ``NOT_MEASURED`` with a reason. A source older than its contract's ``stale_after``
  makes it ``STALE``.
* **Status colour is not a risk grade** (ADR-537). ``state`` says whether a part WORKS and is FRESH; risk
  and «approved for real money» are separate fields, and real money is always ``LIVE_NOT_APPROVED``.
* **Redaction.** Nothing here carries a command line, environment value, token, local path, chat id or
  e-mail. Free text passes ``safe_text`` (paths, secrets and identifiers removed, length capped).
* **Read-only.** Building the model writes nothing except its own output file; leases are read without
  pruning, the Director's «seen» mark is never set.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Optional

from spa_core.utils.observation import observed

REPO = Path(__file__).resolve().parents[2]
SCHEMA = "mission-control/1"
#: The SPA bot's public username (not a secret: it is the t.me address). Owner answers are given there.
TELEGRAM_BOT = "SPA_Monitor_bot"
#: The Studio Bridge bot: confirm-first text/voice intake (task · idea · decision proposal) and /report.
BRIDGE_BOT = "Bridge_studio_os_bot"

# ── the shared status vocabulary (WP-A03) ───────────────────────────────────────────────────────
OPERATIONAL = ("RUNNING", "PAUSED", "FAILED", "UNKNOWN")
HEALTH = ("HEALTHY", "DEGRADED", "STALE", "NOT_MEASURED", "CRITICAL")
WORK = ("QUEUED", "IN_PROGRESS", "BLOCKED", "REVIEW", "DONE")
DECISION = ("NEEDS_OWNER", "ACCEPTED", "ANSWERED", "INGESTED", "REJECTED", "EXPIRED", "UNKNOWN")
CAPITAL_MODE = ("PAPER", "SHADOW", "LIVE_NOT_APPROVED")
EVIDENCE = ("WARMUP", "ACCUMULATING", "REPORTABLE")
#: Colour is derived from HEALTH only, never from performance or risk (ADR-537).
#: production-tree statuses that mean «the owner already answered» — shared with director_report
ANSWERED_STATUSES = ("owner-done", "owner-accepted", "ingested")

COLOUR = {"HEALTHY": "neutral-ok", "DEGRADED": "warn", "STALE": "warn", "NOT_MEASURED": "unknown",
          "CRITICAL": "alert"}

AREAS = {
    "overview": "Studio OS + Capital summary — the 30-second answer",
    "capital": "SPA / Capital — paper strategies and research (no execution path, real capital 0)",
    "studio": "Studio OS — tasks, agents, epics, releases, outcomes, orphans",
    "decisions": "Owner decisions — the canonical owner queue (answers are given in Telegram)",
    "system": "Studio OS — machine, services, resources, backups, code identity, incidents",
}

#: WP-A02 field contract. One row per section path; every emitted value lives under exactly one row.
#: source = canonical source · stale_after_min = freshness · unknown = behaviour without data ·
#: redaction = what is stripped · mobile = shown on the phone · alert = may raise an owner alert.
CONTRACT: list[dict] = [
    {"path": "overview.system", "source": "director_report.collect (agent_health + launchctl + resource_health + kill switch)",
     "stale_after_min": 90, "unknown": "NOT_MEASURED", "redaction": "safe_text on alerts", "mobile": True, "alert": True},
    {"path": "overview.needs_owner", "source": "tracker cards on origin (mirror) + production-tree owner answers",
     "stale_after_min": None, "unknown": "count null", "redaction": "safe_text on titles", "mobile": True, "alert": True},
    {"path": "overview.now", "source": "docs/ROADMAP.md + build_loop.board (origin tracker)",
     "stale_after_min": None, "unknown": "UNKNOWN epic", "redaction": "safe_text", "mobile": True, "alert": False},
    {"path": "overview.capital", "source": "package_status.public_view + data/trading_research/status.json + paper_trading_status.execution_mode",
     "stale_after_min": 120, "unknown": "NOT_MEASURED per package", "redaction": "public_view scrub", "mobile": True, "alert": False},
    {"path": "overview.today", "source": "git origin/main (mirror) + code_sync_status + push_state (Telegram policy)",
     "stale_after_min": None, "unknown": "null list", "redaction": "commit subjects safe_text", "mobile": True, "alert": False},
    {"path": "overview.resources", "source": "data/resource_health.json (resource_guard, ADR-551)",
     "stale_after_min": 20, "unknown": "NOT_MEASURED", "redaction": "numbers only", "mobile": True, "alert": True},
    {"path": "capital.packages", "source": "spa_core.defi_engine.package_status.public_view",
     "stale_after_min": 120, "unknown": "NOT_MEASURED", "redaction": "public_view scrub", "mobile": True, "alert": False},
    {"path": "capital.trading_research", "source": "data/trading_research/status.json",
     "stale_after_min": 60, "unknown": "NOT_MEASURED", "redaction": "no shortlist free text", "mobile": True, "alert": True},
    {"path": "capital.live_readiness", "source": "spa_core.capital_shadow.read.latest — the separate read-only verifier (ADR-556)",
     "stale_after_min": 1800, "unknown": "NOT_MEASURED (no shadow run yet); BROKEN ledger ⇒ CRITICAL", "redaction": "safe_text on every string",
     "mobile": True, "alert": True},
    {"path": "capital.investment_cio", "source": "spa_core.investment_cio.read.latest (ledger.jsonl + latest.json, ADR-554)",
     "stale_after_min": 1800, "unknown": "NOT_MEASURED (no recommendation yet)", "redaction": "safe_text on every string",
     "mobile": True, "alert": False},
    {"path": "capital.research_universe", "source": "spa_core.research_factory.read.latest (ADR-560, RESEARCH/PAPER only)",
     "stale_after_min": 1560, "unknown": "NOT_MEASURED (no research_factory run yet); BROKEN ledger ⇒ CRITICAL; "
     "STALE when the last run's generated_at is older than ~26h (contract.CIO_READ_MODEL_MAX_AGE_H)",
     "redaction": "safe_text on every string", "mobile": True, "alert": True},
    {"path": "capital.real_capital", "source": "paper_trading_status.execution_mode + package live_capital_usd + trading live_capital_usd",
     "stale_after_min": None, "unknown": "UNKNOWN (never 0 by default)", "redaction": "-", "mobile": True, "alert": True},
    {"path": "studio.epics", "source": "docs/ROADMAP.md (owner-confirmed order; ~~struck~~ = done)",
     "stale_after_min": None, "unknown": "UNKNOWN", "redaction": "safe_text", "mobile": True, "alert": False},
    {"path": "studio.board", "source": "spa_core.studio_os.build_loop.board (origin tracker)",
     "stale_after_min": None, "unknown": "NOT_MEASURED", "redaction": "safe_text on titles", "mobile": True, "alert": False},
    {"path": "studio.lineage", "source": "spa_core.studio_os.build_loop.lineage",
     "stale_after_min": None, "unknown": "stage UNKNOWN", "redaction": "safe_text on evidence", "mobile": False, "alert": False},
    {"path": "studio.agents", "source": "data/agent_health.json (stale-aware load_report)",
     "stale_after_min": 90, "unknown": "NOT_MEASURED", "redaction": "labels only", "mobile": True, "alert": True},
    {"path": "studio.orphans", "source": "data/orphan_report.json (com.spa.resource_cleanup)",
     "stale_after_min": 2880, "unknown": "NOT_MEASURED", "redaction": "counts only", "mobile": True, "alert": False},
    {"path": "decisions", "source": "tracker owner-decision cards (origin) + production-tree owner answers (owner_answer.py fields)",
     "stale_after_min": None, "unknown": "UNKNOWN fields named", "redaction": "safe_text; no chat ids", "mobile": True, "alert": True},
    {"path": "system.resources", "source": "data/resource_health.json (com.spa.resource_guard)",
     "stale_after_min": 20, "unknown": "NOT_MEASURED", "redaction": "process NAME only, never the command line", "mobile": True, "alert": True},
    {"path": "system.agents", "source": "director_report.collect → data/agent_health.json",
     "stale_after_min": 90, "unknown": "NOT_MEASURED", "redaction": "agent labels only", "mobile": True, "alert": True},
    {"path": "system.kill_switch", "source": "director_report: kill_switch_active.json + kill_switch_status.json (fresh ≤26 h) + derisk",
     "stale_after_min": 1560, "unknown": "null = not measured (unreadable / UNMEASURED / stale)", "redaction": "-", "mobile": True, "alert": True},
    {"path": "system.derisk", "source": "director_report: data/derisk_status.json (fresh ≤26 h)",
     "stale_after_min": 1560, "unknown": "null = not measured", "redaction": "-", "mobile": True, "alert": True},
    {"path": "system.heavy_jobs", "source": "~/.spa_heavy_jobs leases (read without pruning)",
     "stale_after_min": None, "unknown": "null (not measured) vs [] (measured none)", "redaction": "tree basename only", "mobile": True, "alert": False},
    {"path": "system.cleanup", "source": "data/resource_cleanup_log.jsonl",
     "stale_after_min": 2880, "unknown": "NOT_MEASURED", "redaction": "counts only", "mobile": False, "alert": False},
    {"path": "system.backups", "source": "data/dr_offsite_status.json + data/backups/*.tar.gz + data/resilience_status.json",
     "stale_after_min": 1800, "unknown": "NOT_MEASURED", "redaction": "no paths", "mobile": True, "alert": True},
    {"path": "system.code", "source": "data/code_sync_status.json + data/deployment_acceptance.json + trusted approved_release.json",
     "stale_after_min": 120, "unknown": "NOT_MEASURED", "redaction": "short shas only", "mobile": True, "alert": True},
    {"path": "system.services", "source": "launchctl list (KEY_SERVICES of director_report)",
     "stale_after_min": None, "unknown": "NOT_MEASURED", "redaction": "-", "mobile": True, "alert": True},
    {"path": "system.incidents", "source": "data/telegram/push_state.json (events in bad state)",
     "stale_after_min": None, "unknown": "NOT_MEASURED", "redaction": "event keys only", "mobile": True, "alert": False},
    {"path": "intake", "source": "constants: the two Telegram bots (public usernames) — no state",
     "stale_after_min": None, "unknown": "-", "redaction": "-", "mobile": True, "alert": False},
    {"path": "release_feed", "source": "git origin/main (mirror): subject, ADR/cycle/card refs; production containment via code_sync_status",
     "stale_after_min": None, "unknown": "null", "redaction": "safe_text on subjects", "mobile": True, "alert": False},
]

# ── redaction ───────────────────────────────────────────────────────────────────────────────────
_PATH = re.compile(r"(?:/Users|/private|/var|/tmp|/Library|/opt|/home|~)/[^\s'\"`)]+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_LONGNUM = re.compile(r"(?<![\w.])-?\d{8,}(?![\w.])")
# WP-A05 #4: shapes redact_cmd does not see — Telegram bot tokens (bare and inside api URLs), JWTs,
# Authorization/API-key headers, and 40-char key material that contains «/» or «+» (AWS-style).
_TG_TOKEN = re.compile(r"(?:bot)?\d{6,}:[A-Za-z0-9_-]{30,}")
_JWT = re.compile(r"eyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]*")
_AUTH_SCHEME = re.compile(r"(?i)\b(bearer|basic)\s+(?!<redacted>)\S+")
_AUTH = re.compile(r"(?i)\b(x-api-key:?|api-key:?|authorization:?)\s+(?!(?:bearer|basic)\b)(?!<redacted>)\S+")
_KEYISH = re.compile(r"(?<![\w/+])(?=[A-Za-z0-9/+]*[/+])(?=[A-Za-z0-9/+]*\d)[A-Za-z0-9/+]{40,}={0,2}(?![\w/+])")
# a card / branch slug (lower-case words joined by hyphens) is an identifier the owner needs, not key
# material: it is shielded from the long-blob rule (the over-redaction WP-A05 found in lineage evidence)
_SLUG = re.compile(r"\b[a-z0-9]{1,24}(?:-[a-z0-9]{1,24}){3,}\b")


def safe_text(s: Any, limit: int = 160) -> Optional[str]:
    """Owner-readable text with secrets, local paths, e-mails and long identifiers removed."""
    if s is None:
        return None
    from spa_core.monitoring.resource_guard import redact_cmd
    t = " ".join(str(s).split())
    t = _TG_TOKEN.sub("<redacted>", t)
    t = _JWT.sub("<redacted>", t)
    t = _AUTH_SCHEME.sub(lambda m: m.group(1) + " <redacted>", t)
    t = _AUTH.sub(lambda m: m.group(1) + " <redacted>", t)
    slugs: list = []

    def _keep(m):
        slugs.append(m.group(0))
        return f"\x00{len(slugs) - 1}\x00"
    t = _SLUG.sub(_keep, t)
    t = redact_cmd(t)
    t = _PATH.sub("<path>", t)
    t = _KEYISH.sub("<redacted>", t)
    t = _EMAIL.sub("<email>", t)
    t = _LONGNUM.sub("<id>", t)
    t = re.sub("\x00(\\d+)\x00", lambda m: slugs[int(m.group(1))], t)
    return t if len(t) <= limit else t[: limit - 1] + "…"


def proc_name(cmd: Any) -> str:
    """A process NAME for display — the executable or module, never its arguments."""
    c = str(cmd or "")
    m = re.search(r"-m\s+([\w.]+)", c)
    if m:
        return m.group(1).split(".")[-1]
    m2 = re.search(r"/([^/]+)\.app/", c)          # a macOS bundle name may contain spaces
    if m2:
        return m2.group(1)[:40]
    first = c.split()[0] if c.split() else "?"
    return first.rsplit("/", 1)[-1][:40]


# ── inputs ──────────────────────────────────────────────────────────────────────────────────────
def _default_mirror() -> Path:
    m = Path.home() / "Documents" / "SPA_mirror"
    return m if (m / ".git").exists() else REPO


@dataclass
class MCInputs:
    repo: Path = REPO                       # production tree (live data/)
    mirror: Path = field(default_factory=_default_mirror)
    trusted_root: Optional[Path] = None
    now: Optional[datetime] = None
    measure_host: bool = True
    collect: Optional[Callable[..., dict]] = None        # injectable Director collector (tests)
    packages: Optional[Callable[[], Optional[dict]]] = None
    git_log: Optional[Callable[[int], Optional[list]]] = None
    leases: Optional[Callable[[], Optional[list]]] = None
    mirror_synced_at: Optional[datetime] = None          # injectable (tests); default: the mirror's last fetch


#: the origin mirror re-fetches every 30 min; older than this, its cards/board/history are STALE
MIRROR_STALE_MIN = 90
#: paths code-sync delivers into the production tree (ADR-152/214); other commits never «reach production» by it
SYNCED_PREFIXES = ("spa_core/", "scripts/", "tests/", "architecture/", "CLAUDE.md", ".claude/")
#: the SPA bot's deep-link payload grammar (bot.py _DEEPLINK)
_LINK_SLUG = re.compile(r"^[a-z0-9-]{3,61}$")


def _mirror_synced_at(inp: "MCInputs") -> Optional[datetime]:
    if inp.mirror_synced_at is not None:
        return inp.mirror_synced_at
    for f in (Path(inp.mirror) / ".git" / "FETCH_HEAD", Path(inp.mirror) / ".git" / "refs" / "remotes" / "origin" / "main"):
        try:
            return datetime.fromtimestamp(f.stat().st_mtime, timezone.utc)
        except OSError:
            continue
    return None


def _read_json(p: Path) -> Optional[Any]:
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _ts(v) -> Optional[datetime]:
    if v is None:
        return None
    try:
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / 1000 if v > 1e11 else v, timezone.utc)
        d = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def _age_min(now: datetime, at: Optional[datetime]) -> Optional[float]:
    return round((now - at).total_seconds() / 60, 1) if at else None


def _meta(state: str, sources: list, observed_at: Optional[datetime], now: datetime,
          stale_after_min: Optional[float] = None, reason: Optional[str] = None) -> dict:
    """Section envelope: the state is downgraded to STALE when the observation is older than its contract."""
    age = _age_min(now, observed_at)
    if state not in ("NOT_MEASURED", "CRITICAL") and stale_after_min is not None and (age is None or age > stale_after_min):
        state, reason = "STALE", reason or (f"last observation {age} min ago (contract: {stale_after_min} min)"
                                            if age is not None else "no observation time")
    return {"state": state, "colour": COLOUR.get(state, "unknown"), "sources": sources,
            "observed_at": observed_at.strftime("%Y-%m-%dT%H:%M:%SZ") if observed_at else None,
            "age_min": age, "stale_after_min": stale_after_min, "reason": safe_text(reason)}


def _nm(sources: list, now: datetime, reason: str) -> dict:
    return {"_meta": _meta("NOT_MEASURED", sources, None, now, reason=reason)}


# ── tracker (origin cards + production-tree owner answers) ─────────────────────────────────────
def _cards(tdir: Path) -> Optional[dict]:
    from spa_core.studio_os import build_loop as bl
    if not tdir.is_dir():
        return None
    out = {}
    for p in tdir.glob("*.md"):
        if p.name.startswith("_"):
            continue
        try:
            fm, trail, body = bl._frontmatter(p.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
        out[p.name] = {"fm": fm, "trail": trail, "body": body, "path": p}
    return out


_SUBJECT_HINT = (
    (re.compile(r"капитал|деньг|money|live|ключ|кошел|wallet|execution|исполнен", re.I), "1 · real money"),
    (re.compile(r"сайт|site|landing|формулир|wording|цифр|доходн|yield|tier|тир|legal|юрид|fee|комисс", re.I),
     "2 · public numbers / naming / legal"),
    (re.compile(r"удал|delete|необратим|irreversible|публикац|publish|внешн", re.I), "3 · irreversible / external"),
)


def risk_class(title: str, body: str) -> str:
    """ADR-285 subject of an owner card. Deterministic keyword hint; no match ⇒ UNKNOWN (a queue defect
    candidate per ADR-285, never silently «low risk»)."""
    text = f"{title}\n{body[:1500]}"
    for rx, label in _SUBJECT_HINT:
        if rx.search(text):
            return label
    return "UNKNOWN"


def _section(body: str, heading: str) -> Optional[str]:
    m = re.search(r"^##\s*" + re.escape(heading) + r"[^\n]*\n(.*?)(?=^##\s|\Z)", body, re.M | re.S)
    return m.group(1).strip() if m else None


def _link_slug(name: str, prod_names: Optional[set]) -> tuple[Optional[str], Optional[str]]:
    """The deep-link payload the bot will resolve to EXACTLY this card, or (None, why) — WP-A05 #10.
    The bot reads the production tracker: exact file name first, else a unique prefix."""
    stem = name[:-3] if name.endswith(".md") else name
    slug = stem[:58]
    if not _LINK_SLUG.match(slug):
        return None, "card name outside the bot's link grammar — open the SPA bot menu"
    if prod_names is None:
        return None, "production tracker not readable"
    if f"{stem}.md" not in prod_names:
        return None, "card not in the production tracker yet (origin is ahead) — the bot cannot open it"
    if f"{slug}.md" in prod_names and slug != stem:
        return None, "another card's name equals this link — would open the wrong card"
    if slug != stem and sum(1 for n in prod_names if n.startswith(slug)) != 1:
        return None, "link prefix is ambiguous in the production tracker"
    return slug, None


def decision_item(name: str, card: dict, prod: Optional[dict], bot: Optional[str],
                  prod_names: Optional[set] = None) -> dict:
    fm, body, trail = card["fm"], card["body"], card["trail"]
    pfm = (prod or {}).get("fm") or {}
    # ONE rule with the Director's owner section: record_owner_answer always moves the status, so an
    # answered status in the production tree counts even before the trace reaches origin
    answered_here = pfm.get("status") in ANSWERED_STATUSES
    status = fm.get("status", "")
    state = {"needs-owner": "NEEDS_OWNER", "owner-accepted": "ACCEPTED", "owner-done": "ANSWERED",
             "ingested": "INGESTED", "done": "INGESTED"}.get(status, "UNKNOWN")
    if state == "NEEDS_OWNER" and answered_here:
        state = "ANSWERED"                     # answered in Telegram; the trace is on its way to origin
    approves = fm.get("approves", "")
    slug, why = _link_slug(name, prod_names)
    missing = [k for k, v in (("reason", _section(body, "Что случилось")), ("requested_action", _section(body, "Что от тебя нужно")))
               if not v]
    return {
        "id": name[:-3] if name.endswith(".md") else name,
        "title": safe_text(fm.get("title") or name, 200),
        "state": state,
        "reason": safe_text(_section(body, "Что случилось"), 400) or "UNKNOWN",
        "requested_action": safe_text(_section(body, "Что от тебя нужно"), 400) or "UNKNOWN",
        "done_when": safe_text(_section(body, "Как понять"), 200) or "UNKNOWN",
        "risk_class": risk_class(fm.get("title", ""), body),
        "created_at": safe_text(fm.get("created"), 40) or "UNKNOWN",
        "source": safe_text(fm.get("source"), 60) or "UNKNOWN",
        "evidence": safe_text(fm.get("package") or fm.get("adr") or fm.get("finding_key"), 160) or "UNKNOWN",
        "affected_artifacts": [safe_text(a.strip(" []'\""), 120) for a in str(approves).split(",") if a.strip(" []")] or [],
        "scope": "approves: " + (safe_text(approves, 300) or "—") if approves else "UNKNOWN",
        "owner_answer": safe_text(pfm.get("owner_choice") or fm.get("owner_choice"), 200),
        "answered_at": safe_text(pfm.get("owner_answered_at") or fm.get("owner_answered_at"), 40),
        "missing_fields": missing,
        "answer_in": "telegram",
        "telegram_link": f"https://t.me/{bot}?start=od_{slug}" if (bot and slug) else None,
        "telegram_link_note": None if (bot and slug) else (why or "SPA bot username unknown"),
        "last_transition": safe_text(trail[-1], 160) if trail else None,
    }


# ── sections ───────────────────────────────────────────────────────────────────────────────────
def _roadmap(mirror: Path) -> dict:
    p = mirror / "docs" / "ROADMAP.md"
    try:
        text = p.read_text(encoding="utf-8")
    except OSError:
        return {"items": None, "current": None, "confirmed": None}
    m = re.search(r"Last confirmed by the owner:\s*\*\*([\d-]+)\*\*", text)
    items = []
    sect = text.split("## Order of the next epics", 1)[-1].split("\n## ", 1)[0]
    for ln in sect.splitlines():
        mm = re.match(r"\s*(\d+)\.\s+(.*)", ln)
        if not mm:
            continue
        raw = mm.group(2)
        done = raw.strip().startswith("~~")
        name = re.sub(r"[~*`]", "", raw.split("—")[0]).strip()
        note = raw.split("—", 1)[1].strip() if "—" in raw else ""
        state = "DONE" if done else ("IN_PROGRESS" if re.search(r"in progress|в работе", note, re.I) else "QUEUED")
        items.append({"n": int(mm.group(1)), "epic": safe_text(name, 120), "state": state, "note": safe_text(note, 200)})
    cur = next((i for i in items if i["state"] == "IN_PROGRESS"), None) or next((i for i in items if i["state"] == "QUEUED"), None)
    return {"items": items, "current": cur, "confirmed": m.group(1) if m else None}


def _git_feed(inp: MCInputs, hours: int = 48, limit: int = 25) -> Optional[list]:
    if inp.git_log is not None:
        return inp.git_log(hours)
    if not inp.measure_host:
        return None
    try:
        r = subprocess.run(["git", "-C", str(inp.mirror), "log", "origin/main", f"--since={hours} hours ago",
                            "-n", str(limit), "--name-only",
                            "--format=%x1e%H%x1f%cI%x1f%s%x1f%(trailers:key=Co-Authored-By,valueonly,separator=;)%x1f"],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    if r.returncode != 0:
        return None
    out = []
    for rec in r.stdout.split("\x1e"):
        p = rec.strip("\n").split("\x1f")
        if len(p) >= 5:
            out.append({"sha": p[0][:9], "full": p[0], "at": p[1], "subject": p[2], "co_author": p[3].strip(),
                        "files": [f for f in p[4].splitlines() if f.strip()]})
    return out


def _is_ancestor(root: Path, sha: str, of: str) -> Optional[bool]:
    try:
        r = subprocess.run(["git", "-C", str(root), "merge-base", "--is-ancestor", sha, of],
                           capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return None
    return True if r.returncode == 0 else False if r.returncode == 1 else None


def _kind(subject: str) -> str:
    s = subject.lower()
    if s.startswith(("security", "fix(security", "sec(")) or "security" in s[:30]:
        return "security"
    if s.startswith(("cards(", "board(", "chore(queue")):
        return "housekeeping"
    if "adr-" in s[:12] or s.startswith(("feat", "adr")):
        return "decision"
    if s.startswith(("fix", "hotfix")):
        return "fix"
    if s.startswith("docs"):
        return "docs"
    return "change"


def release_feed(inp: MCInputs, now: datetime, cs: Optional[dict]) -> dict:
    """«IN_PROD_TREE» = the commit is in the production working tree AND touches paths code-sync delivers.
    It is not «running»: a long-lived service runs new code only after a restart (agent_code_freshness).
    docs/, landing/ (Cloudflare Pages) and tracker commits are NOT_APPLICABLE to code-sync (WP-A05 #6)."""
    feed = _git_feed(inp)
    if feed is None:
        return _nm(["git origin/main (mirror)"], now, "git history not readable")
    prod = (cs or {}).get("origin_main") if str((cs or {}).get("result", "")).upper() in ("IN_SYNC", "SYNCED") else None
    items = []
    for c in feed:
        subj = c["subject"]
        contains = None
        files = c.get("files")
        synced = None if files is None else any(f.startswith(SYNCED_PREFIXES) for f in files)
        if prod and inp.measure_host and synced:
            # the production clone has fetched the commit code-sync delivered; the mirror may lag it
            for root in (Path(inp.repo), Path(inp.mirror)):
                contains = _is_ancestor(root, c["full"], prod)
                if contains is not None:
                    break
        items.append({
            "at": c["at"], "commit": c["sha"], "kind": _kind(subj),
            "summary": safe_text(re.sub(r"^\w+(\([^)]*\))?:\s*", "", subj), 180),
            "adrs": sorted(set(re.findall(r"ADR-\d{3}", subj))),
            "cycle": (re.findall(r"(?:цикл|cycle)\s*#(\d+)", subj, re.I) or [None])[0],
            "producer": ("autonomous cycle" if re.search(r"(?:цикл|cycle)\s*#\d+", subj, re.I) else
                         f"agent session ({c['co_author'].split('<')[0].strip()[:40]})" if c["co_author"] else "UNKNOWN"),
            "release": ("NOT_APPLICABLE" if synced is False else "IN_PROD_TREE" if contains else
                        "ON_MAIN" if contains is False else "PRODUCTION_UNKNOWN"),
        })
    return {"_meta": _meta("HEALTHY", ["git origin/main (mirror)", "data/code_sync_status.json"], _mirror_synced_at(inp), now,
                           MIRROR_STALE_MIN),
            "production_commit": prod[:9] if prod else None, "items": items,
            "release_note": ("IN_PROD_TREE: in the production tree via code-sync; long-lived services run it after a restart. "
                             "NOT_APPLICABLE: docs/site/tracker commits are not delivered by code-sync.")}


def _live_readiness_section(data: Path, now: datetime) -> dict:
    """RM-LIVE-01 shadow execution + pilot readiness (ADR-556), read ONLY through the separate verifier — the writer
    never certifies itself. Colour = health of the shadow feed and ledger, never «permission»: nothing here is
    green past SHADOW_READY and there is no action control."""
    src = ["data/capital_shadow/ledger.jsonl", "data/capital_shadow_anchors/anchors.jsonl"]
    fixed = {"automated_live_execution": "PROHIBITED", "real_capital_usd": 0,
             "banner": "Readiness is not authorization · real capital $0 · automated live execution PROHIBITED"}
    try:
        from spa_core.capital_shadow import read as shadow_read
        doc = shadow_read.latest(data, now=now)
    except Exception as exc:  # noqa: BLE001 — an unreadable shadow feed is NOT_MEASURED, never a crash
        return {**_nm(src, now, f"shadow read failed: {type(exc).__name__}"), **fixed}
    if doc.get("integrity") == "BROKEN":
        return {"_meta": _meta("CRITICAL", src, now, now, reason=safe_text(doc.get("reason"), 300)),
                "integrity": "BROKEN", **fixed}
    if doc.get("state") != "MEASURED" or not (doc.get("ledger") or {}).get("entries"):
        return {**_nm(src, now, doc.get("reason") or "no shadow run yet"), **fixed}
    summ = doc.get("summary") or {}
    sleeves = {}
    for sid, rep in (doc.get("readiness") or {}).items():
        if not isinstance(rep, dict) or "readiness_state" not in rep:
            continue                                   # e.g. venue_canary: diagnostic, never a sleeve
        checks = rep.get("system_checks") or {}
        sleeves[sid] = {"state": rep.get("readiness_state"),
                        "display": safe_text(rep.get("readiness_display") or rep.get("readiness_state"), 80),
                        "passed": sum(1 for c in checks.values() if (c or {}).get("state") == "PASS"),
                        "gates": len(checks),
                        "blockers": [safe_text(f"{b.get('gate')}: {b.get('reason')}", 160)
                                     for b in (rep.get("blocking_conditions") or [])][:6],
                        "owner_pending": [k for k, v in (rep.get("owner_preconditions") or {}).items()
                                          if (v or {}).get("state") == "PENDING"]}
    def _brief(x):
        return ({k: (safe_text(v, 80) if isinstance(v, str) else v) for k, v in x.items()} if isinstance(x, dict) else None)
    inc = summ.get("open_incidents")
    if not isinstance(inc, dict) or inc.get("state") == "BROKEN" or not isinstance(inc.get("count"), int):
        # an unreadable / tampered incident store is never «0 incidents» (second re-review N4)
        st, why = "CRITICAL", f"incident store not readable: {(inc or {}).get('reason') if isinstance(inc, dict) else 'absent'}"
        inc = inc if isinstance(inc, dict) else {}
    elif inc["count"] > 0:
        st, why = "CRITICAL", f"open incidents: {inc.get('kinds')}"
    else:
        st, why = "HEALTHY", None
    return {"_meta": _meta(st, src, _ts(summ.get("generated_at")), now, 1800, reason=safe_text(why, 300)),
            "execution_mode": summ.get("current_execution_mode"), **fixed,
            "sleeves": sleeves,
            "top_blockers": [{"gate": b.get("gate") if isinstance(b, dict) else b,
                              "count": b.get("count") if isinstance(b, dict) else None}
                             for b in (summ.get("top_blockers") or [])][:5],
            "last_simulation": _brief(summ.get("last_simulation")),
            "last_shadow_execution": _brief(summ.get("last_shadow_execution")),
            "last_reconciliation": _brief(summ.get("last_reconciliation")),
            "open_incidents": {"count": inc.get("count"), "kinds": inc.get("kinds")},
            "owner_decisions_pending": summ.get("owner_decisions_pending"),
            "ledger": doc.get("ledger")}


def _cio_display_name() -> Optional[str]:
    try:
        from spa_core.investment_cio import contract as cio_contract
        return cio_contract.ROLE_DISPLAY_NAME
    except Exception:  # noqa: BLE001 — a missing name is shown as absent, never invented
        return None


def _cio_research_universe_counts(view: Any) -> dict:
    """The CIO's OWN ``research_universe`` view (ADR-560 WP-S07), shown as counts only on the
    Oracle card — never the full candidate list, that lives in the separate Research Universe
    section below. Absence is its own value: a view that is missing/NOT_MEASURED is never shown
    as zero candidates."""
    if not isinstance(view, dict):
        return {"state": "NOT_MEASURED", "observe_only": None, "paper_active": None, "cio_eligible": None}
    state = view.get("state") or "NOT_MEASURED"
    counts = {k: (len(view[k]) if isinstance(view.get(k), list) else None)
              for k in ("observe_only", "paper_active", "cio_eligible")}
    return {"state": state, **counts}


def _investment_cio_section(data: Path, now: datetime) -> dict:
    """Oracle — Chief Investment Officer (ADR-554): read through the CIO package's single read function — no
    second truth. Colour = health of the CIO feed (fresh, chain intact), never the quality of the portfolio."""
    src = ["data/investment_cio/ledger.jsonl", "data/investment_cio/latest.json"]
    try:
        from spa_core.investment_cio import read as cio_read
        doc = cio_read.latest(data, now=now)
    except Exception as exc:  # noqa: BLE001 — an unreadable CIO feed is NOT_MEASURED, never a crash
        return {**_nm(src, now, f"CIO read failed: {type(exc).__name__}"),
                "research_universe": _cio_research_universe_counts(None)}
    research_universe_counts = _cio_research_universe_counts(doc.get("research_universe"))
    if doc.get("integrity") == "BROKEN":
        # the decision history cannot be trusted: the recommendation is withheld and this is CRITICAL, not quiet
        return {"_meta": _meta("CRITICAL", src, now, now, reason=safe_text(doc.get("reason"), 300)),
                "integrity": "BROKEN", "research_universe": research_universe_counts,
                "boundary": "paper recommendation — nothing executes it; real capital stays $0"}
    if doc.get("state") != "MEASURED":
        return {**_nm(src, now, doc.get("reason") or "no CIO recommendation yet"),
                "research_universe": research_universe_counts}
    rec = doc.get("recommendation") or {}
    chain_ok = (doc.get("ledger") or {}).get("chain_ok")
    st = "HEALTHY" if chain_ok else "CRITICAL"
    # ADR-554 finding #14: major_risks now carries a named `basis` ("recommended" when there is a
    # recommendation, else "seed_split") and the per-factor weight is `sleeve_weight_touching`
    # (the sleeve weight that touches the factor, not a portfolio-level weighted risk score).
    major_risks_doc = rec.get("major_risks") or {}
    major_risks_factors = major_risks_doc.get("factors") or {}
    out = {"_meta": _meta(st, src, _ts(rec.get("generated_at")), now, 1800,
                          reason=None if chain_ok else "decision ledger hash chain is broken"),
           "role": {"role_id": rec.get("role_id"), "title": "Chief Investment Officer",
                    # one source for the display name: the CIO contract (= architecture/roles.json, tested)
                    "display_name": _cio_display_name()},
           "stance": rec.get("stance"), "confidence": rec.get("confidence"),
           "confidence_reasons": [safe_text(x, 240) for x in (rec.get("confidence_reasons") or [])],
           "date": rec.get("date"), "evidence_cutoff": rec.get("evidence_cutoff"),
           # review N9: the cutoff covers only the inputs that were readable — say so when some were not
           "evidence_cutoff_complete": rec.get("evidence_cutoff_complete"),
           "evidence_incomplete_inputs": [safe_text(x if isinstance(x, str) else (x or {}).get("name"), 80)
                                          for x in (rec.get("evidence_cutoff_incomplete_inputs") or [])][:12],
           "recommended_weights": rec.get("recommended_weights") or {},
           "seed_split_weights": rec.get("seed_split_weights") or {},
           "alternatives": {k: {"weights": (v or {}).get("weights"), "note": safe_text((v or {}).get("note"), 200)}
                            for k, v in (rec.get("alternatives_considered") or {}).items()},
           "abstentions": {k: safe_text(v, 240) for k, v in (rec.get("abstentions") or {}).items()},
           "binding_constraints": [{"constraint": c.get("constraint"), "state": c.get("state"),
                                    "detail": safe_text(c.get("detail") or c.get("reason"), 240)}
                                   for c in (rec.get("binding_constraints") or [])],
           "major_risks_basis": major_risks_doc.get("basis"),
           "major_risks": [{"factor": f, "sleeves": v.get("contributors"),
                            "sleeve_weight_touching": v.get("sleeve_weight_touching")}
                           for f, v in sorted(major_risks_factors.items(),
                                              key=lambda kv: -(kv[1].get("sleeve_weight_touching") or 0))][:8],
           "unknowns": [safe_text(u, 200) for u in (rec.get("unknowns") or [])][:10],
           # a recommendation without its rule trace is unexplained — None («not measured»), never an empty list
           "rationale": ([safe_text(x, 260) for x in rec["rationale"]][:14]
                         if isinstance(rec.get("rationale"), list) else None),
           "ledger": doc.get("ledger"), "outcomes": doc.get("outcomes"),
           "policy_version": rec.get("policy_version"), "recommendation_id": (str(rec["recommendation_id"])[:12] if rec.get("recommendation_id") else None),
           "mode": rec.get("mode"), "executes": rec.get("executes"), "real_capital_usd": rec.get("real_capital_usd"),
           "research_universe": research_universe_counts,
           "boundary": "paper recommendation — nothing executes it; real capital stays $0"}
    return out


#: ADR-560 WP-S08: shown always, whatever the section's own state — a boundary notice, not a
#: measured fact, so it must not disappear just because the factory has not run yet.
RESEARCH_UNIVERSE_BANNER = ("RESEARCH ≠ APPROVED · PAPER ≠ LIVE · CIO_ELIGIBLE ≠ REAL-MONEY APPROVED · "
                           "real capital $0")


def _research_candidate_sort_key(c: dict) -> tuple:
    """Rank by EVIDENCE, never by advertised APY (ADR-560 WP-S08's own explicit instruction):
    forward periods first (more days of real observation beats everything), then whether the net
    figure is MEASURED/ESTIMATED (never an advertised-only number), then the net value itself."""
    maturity = (c.get("evidence_maturity") or {}).get("forward_periods") if isinstance(c.get("evidence_maturity"),
                                                                                       dict) else None
    maturity = maturity or 0
    net = c.get("net_expected_return") or {}
    state_rank = {"MEASURED": 0, "ESTIMATED_WITH_METHOD": 1}.get(net.get("state"), 2)
    value = net.get("value")
    return (-maturity, state_rank, -(value if isinstance(value, (int, float)) else 0))


def _research_universe_section(data: Path, now: datetime) -> dict:
    """ADR-560 WP-S08: the research factory's own universe, read ONLY through
    spa_core.research_factory.read.latest — no second truth. OBSERVE_ONLY / PAPER_ACTIVE /
    CIO_ELIGIBLE are the factory's own vocabulary and are never approval, which is exactly why the
    banner is shown unconditionally: this section is one an owner glancing at Mission Control could
    otherwise misread as a buy list. BROKEN ⇒ CRITICAL; no status at all ⇒ NOT_MEASURED (the agent
    has not run yet, or packages A/B are not deployed on this tree)."""
    src = ["data/research_factory/ledger.jsonl", "data/research_factory/status.json"]
    try:
        from spa_core.research_factory import read as rf_read
        doc = rf_read.latest(data)
    except ImportError as exc:
        return {**_nm(src, now, f"research_factory not available ({exc})"), "banner": RESEARCH_UNIVERSE_BANNER}
    except Exception as exc:  # noqa: BLE001 — an unreadable factory feed is NOT_MEASURED, never a crash
        return {**_nm(src, now, f"research_factory read failed: {type(exc).__name__}"),
                "banner": RESEARCH_UNIVERSE_BANNER}
    if not isinstance(doc, dict) or not doc.get("schema"):
        return {**_nm(src, now, "no research factory status yet"), "banner": RESEARCH_UNIVERSE_BANNER}
    if doc.get("integrity") == "BROKEN":
        return {"_meta": _meta("CRITICAL", src, now, now, reason=safe_text(doc.get("reason"), 300)),
                "integrity": "BROKEN", "banner": RESEARCH_UNIVERSE_BANNER}
    denom = doc.get("denominators") or {}
    candidates = [c for c in (doc.get("candidates") or []) if isinstance(c, dict)]
    top = sorted(candidates, key=_research_candidate_sort_key)[:10]
    return {
        # REWORK M5: Package A is moving `generated_at` from "when I was queried" (always ~0 age,
        # so a 4-day-dead agent still looked HEALTHY) to the LAST RUN ROW's time — the one honest
        # signal of whether the factory is actually still running. 1560 min == 26h, matching
        # contract.CIO_READ_MODEL_MAX_AGE_H (the same convention this file already uses for
        # system.kill_switch / system.derisk); _meta() downgrades to STALE on its own once the age
        # exceeds this, no extra branch needed here.
        "_meta": _meta("HEALTHY", src, _ts(doc.get("generated_at")), now, 1560),
        "real_capital_usd": doc.get("real_capital_usd"), "live_authorized": doc.get("live_authorized"),
        "counts": {k: denom.get(k) for k in ("discovered", "paper_active", "cio_eligible", "observe_only",
                                             "rejected", "scanned", "truncated", "disappeared")},
        "by_domain": doc.get("by_domain") or {}, "by_mechanism": doc.get("by_mechanism") or {},
        "top_candidates": [{"candidate_id": c.get("candidate_id"), "domain": c.get("domain"),
                            "mechanism_id": c.get("mechanism_id"), "instrument": safe_text(c.get("instrument"), 80),
                            "venue_or_protocol": safe_text(c.get("venue_or_protocol"), 80),
                            "admission_state": c.get("admission_state"),
                            "forward_periods": (c.get("evidence_maturity") or {}).get("forward_periods"),
                            "net_expected_return": c.get("net_expected_return")} for c in top],
        "rejected": [{"candidate_id": r.get("candidate_id"), "state": r.get("state"),
                      "reasons": [safe_text(x, 160) for x in (r.get("reasons") or [])][:5]}
                     for r in (doc.get("rejections") or [])][:20],
        "stale_feeds": [{"source_root": f.get("source_root"), "age_h": f.get("age_h")}
                        for f in (doc.get("stale_feeds") or [])][:20],
        "counterparty_unknown_count": doc.get("counterparty_unknown_count"),
        "domain_decisions": doc.get("domain_decisions") or {},
        "basis_track": doc.get("basis_track"),
        "banner": RESEARCH_UNIVERSE_BANNER,
    }


def build(inp: Optional[MCInputs] = None) -> dict:
    inp = inp or MCInputs()
    now = inp.now or datetime.now(timezone.utc)
    data = Path(inp.repo) / "data"

    # The Director collector — the same projection Telegram renders (one meaning per value).
    from spa_core.studio_os import director_report as dr
    try:
        if inp.collect is not None:
            rep = inp.collect()
        else:
            kw = {"repo": Path(inp.repo), "mirror": Path(inp.mirror), "now": now, "measure_host": inp.measure_host}
            if inp.trusted_root is not None:
                kw["trusted_root"] = Path(inp.trusted_root)
            rep = dr.collect(dr.Inputs(**kw))
    except Exception as exc:  # noqa: BLE001 — a broken collector is NOT_MEASURED, never a crash
        rep = {"_error": safe_text(f"{type(exc).__name__}: {exc}")}

    # ── SYSTEM ─────────────────────────────────────────────────────────────────────────────────
    rh = _read_json(data / "resource_health.json")
    if isinstance(rh, dict):
        st = {"OK": "HEALTHY", "WARN": "DEGRADED", "CRITICAL": "CRITICAL"}.get(rh.get("overall"), "NOT_MEASURED")
        procs = rh.get("processes") or {}
        resources = {
            "_meta": _meta(st, ["data/resource_health.json"], _ts(rh.get("generated_at")), now, 20,
                           reason=None if st != "NOT_MEASURED" else "the guard could not measure"),
            "disk": {"state": (rh.get("disk") or {}).get("state"), "free_gb": (rh.get("disk") or {}).get("free_gb"),
                     "warn_below_gb": (rh.get("disk") or {}).get("warn_free_gb"),
                     "critical_below_gb": (rh.get("disk") or {}).get("critical_free_gb")},
            "memory": {"state": (rh.get("memory") or {}).get("state"),
                       "pressure_level": (rh.get("memory") or {}).get("pressure_level"),
                       "swap_used_pct": ((rh.get("memory") or {}).get("swap") or {}).get("used_pct")},
            "rss_mb_by_class": procs.get("rss_mb_by_class"),
            "top": [{"name": proc_name(r.get("cmd")), "class": r.get("class"), "rss_mb": r.get("rss_mb"),
                     "agent": r.get("label") if str(r.get("label") or "").startswith(("com.spa.", "com.studiobridge.")) else None}
                    for r in (procs.get("top") or [])[:8]],
            "reserve": ((rh.get("protection") or {}).get("reserve") or {}).get("action"),
        }
    else:
        resources = _nm(["data/resource_health.json"], now, "no resource reading (guard not installed or file unreadable)")

    if inp.leases is not None:
        leases = inp.leases()
    elif inp.measure_host:
        try:
            from spa_core.utils import heavy_job as hj
            leases = [{"kind": safe_text(l.get("kind"), 40), "tree": safe_text(Path(str(l.get("tree"))).name, 60),
                       "since": safe_text(l.get("started_at"), 40)}
                      for l in hj.live_leases(hj._policy(), prune=False)]
        except Exception:  # noqa: BLE001
            leases = None
    else:
        leases = None

    cl_path = data / "resource_cleanup_log.jsonl"
    try:
        lines = cl_path.read_text(encoding="utf-8").splitlines()[-2000:]
        rows = [json.loads(x) for x in lines if x.strip()]
        last = _ts(rows[-1].get("ts")) if rows else None
        cleanup = {"_meta": _meta("HEALTHY", [str(cl_path.relative_to(Path(inp.repo)))], last, now, 2880),
                   "last_run": last.strftime("%Y-%m-%dT%H:%M:%SZ") if last else None,
                   "removed_logged": sum(1 for r in rows if r.get("removed")),
                   "gb_logged": round(sum((r.get("bytes") or 0) for r in rows) / 2 ** 30, 3)}
    except (OSError, ValueError):
        cleanup = _nm(["data/resource_cleanup_log.jsonl"], now, "no cleanup log yet")

    dro = _read_json(data / "dr_offsite_status.json")
    res = _read_json(data / "resilience_status.json")
    arch = sorted((data / "backups").glob("spa_state_*.tar.gz"), key=lambda p: p.stat().st_mtime) if (data / "backups").is_dir() else []
    last_arch = datetime.fromtimestamp(arch[-1].stat().st_mtime, timezone.utc) if arch else None
    if isinstance(dro, dict) or arch:
        rd = (res or {}).get("restore_drill") if isinstance(res, dict) else None
        drill = (None if not isinstance(rd, dict) else "NEVER_RUN" if rd.get("never_run") else
                 "STALE" if rd.get("stale") else "OK" if rd.get("all_ok") is True else
                 "FAILED" if rd.get("all_ok") is False else None)
        bad = [why for ok, why in ((isinstance(dro, dict) and dro.get("verified"), "offsite copy not verified"),
                                   (bool(arch), "no local archive"),
                                   (drill == "OK", f"restore drill {drill or 'not measured'}")) if not ok]
        bstate = "HEALTHY" if not bad else "DEGRADED"
        backups = {"_meta": _meta(bstate, ["data/backups/spa_state_*.tar.gz", "data/dr_offsite_status.json",
                                           "data/resilience_status.json"], last_arch, now, 1800,
                                  reason="; ".join(bad) or None),
                   "last_local_archive": last_arch.strftime("%Y-%m-%dT%H:%M:%SZ") if last_arch else None,
                   "offsite_verified": (dro or {}).get("verified"),
                   "offsite_is_real_remote": (dro or {}).get("is_real_remote"),
                   "offsite_at": (dro or {}).get("last_offsite_ts"),
                   "restore_drill": drill, "restore_drill_at": safe_text((rd or {}).get("last_ts"), 40) if isinstance(rd, dict) else None,
                   "note": ("the 'offsite' copy is on the same disk (is_real_remote=false); the only copy that leaves "
                            "the Mac is iCloud SPA_backups" if (dro or {}).get("is_real_remote") is False else None)}
    else:
        backups = _nm(["data/backups", "data/dr_offsite_status.json"], now, "no backup evidence readable")

    cs = _read_json(data / "code_sync_status.json")
    da = _read_json(data / "deployment_acceptance.json")
    if isinstance(cs, dict):
        cst = "HEALTHY" if str(cs.get("result", "")).upper() in ("IN_SYNC", "SYNCED") else "DEGRADED"
        code = {"_meta": _meta(cst, ["data/code_sync_status.json", "data/deployment_acceptance.json",
                                     "trusted approved_release.json"], _ts(cs.get("timestamp")), now, 120,
                               reason=None if cst == "HEALTHY" else f"code-sync result {cs.get('result')}"),
                "production_commit": str(cs.get("origin_main") or "")[:9] or None, "sync_result": cs.get("result"),
                "deployment_acceptance": (da or {}).get("status") if isinstance(da, dict) else None,
                "approved_release": (str(rep.get("approved_release"))[:8] if rep.get("approved_release") else None)}
    else:
        code = _nm(["data/code_sync_status.json"], now, "no code-sync receipt")

    svcs = rep.get("services")
    services = (_nm(["launchctl list"], now, "launchctl not readable" if svcs is None else "no service rows read")
                if not svcs else
                {"_meta": _meta("HEALTHY" if all(s["running"] for s in svcs) else "DEGRADED", ["launchctl list"], now, now),
                 "items": [{"name": safe_text(s["name"], 60), "running": s["running"], "loaded": s["loaded"]} for s in svcs]})

    ps = _read_json(data / "telegram" / "push_state.json")
    if isinstance(ps, dict):
        ev = ps.get("events") or {}
        bad = [{"event": safe_text(k, 80), "since": safe_text((v or {}).get("last_ts") or (v or {}).get("since"), 40)}
               for k, v in sorted(ev.items()) if isinstance(v, dict) and v.get("state") == "bad"]
        incidents = {"_meta": _meta("DEGRADED" if bad else "HEALTHY", ["data/telegram/push_state.json"],
                                    _ts(ps.get("updated_at")), now, None), "open": bad}
    else:
        incidents = _nm(["data/telegram/push_state.json"], now, "alert state not readable")

    fleet = rep.get("fleet")
    if isinstance(fleet, dict):
        fst = {"OK": "HEALTHY", "WARNING": "DEGRADED", "CRITICAL": "CRITICAL"}.get(fleet.get("overall"), "NOT_MEASURED")
        if fleet.get("overall") in ("STALE", "UNCHECKED"):
            fst = "STALE"
        why = (None if fst == "HEALTHY" else
               f"fleet {fleet.get('overall')}: warning {fleet.get('warning')}, critical {fleet.get('critical')} of {fleet.get('total')}")
        agents = {"_meta": _meta(fst, ["data/agent_health.json"], _ts(fleet.get("snapshot_at")), now, 90, reason=why),
                  "ok": fleet.get("ok"), "warning": fleet.get("warning"), "critical": fleet.get("critical"),
                  "total": fleet.get("total"),
                  "critical_agents": [safe_text(x, 80) for x in fleet.get("critical_labels") or []],
                  "warning_agents": [safe_text(x, 80) for x in fleet.get("warning_labels") or []],
                  "paused_intentionally": [safe_text(x, 80) for x in fleet.get("disabled_labels") or []]}
    else:
        agents = _nm(["data/agent_health.json"], now, "agent health not readable or stale")

    system = {"_meta": None, "resources": resources, "heavy_jobs": leases, "cleanup": cleanup, "backups": backups,
              "code": code, "services": services, "incidents": incidents, "agents": agents,
              "kill_switch": rep.get("kill_switch_active"), "derisk": rep.get("derisk_active")}
    parts = [resources, backups, code, services, agents]
    states = [p["_meta"]["state"] for p in parts]
    if rep.get("kill_switch_active") is True:
        states.append("CRITICAL")              # an armed kill switch is never a quiet system
    elif rep.get("kill_switch_active") is None:
        states.append("NOT_MEASURED")          # unreadable / UNMEASURED / stale reading (WP-A05 #5)
    if rep.get("derisk_active") is True:
        states.append("DEGRADED")              # SOFT tier: new entries halted
    sys_state = ("CRITICAL" if "CRITICAL" in states else "NOT_MEASURED" if "NOT_MEASURED" in states else
                 "DEGRADED" if any(s in ("DEGRADED", "STALE") for s in states) else "HEALTHY")
    named = {"resources": resources, "backups": backups, "code": code, "services": services, "agents": agents}
    off = [f"{k} {v['_meta']['state']}" for k, v in named.items() if v["_meta"]["state"] != "HEALTHY"]
    if rep.get("kill_switch_active") is True:
        off.append("kill switch armed")
    elif rep.get("kill_switch_active") is None:
        off.append("kill switch not measured")
    if rep.get("derisk_active") is True:
        off.append("soft de-risk active")
    system["_meta"] = _meta(sys_state, ["system.*"], now, now, reason="; ".join(off) or None)
    pstates = [p["_meta"]["state"] for p in parts]
    system["_meta"]["counts"] = {s: pstates.count(s) for s in sorted(set(pstates))}

    # ── CAPITAL ────────────────────────────────────────────────────────────────────────────────
    try:
        if inp.packages is not None:
            pv = inp.packages()
        else:
            from spa_core.defi_engine import package_status as PS
            pv = PS.public_view(PS.build_all(data, now))
    except Exception as exc:  # noqa: BLE001
        pv = None
        pkg_err = safe_text(f"{type(exc).__name__}")
    else:
        pkg_err = None
    if isinstance(pv, dict) and observed(pv, "packages", kind=dict) is not None:
        pk = {}
        for key, p in observed(pv, "packages", kind=dict).items():
            work = (p.get("work") or {}).get("state")
            data_st = (p.get("data") or {}).get("state")
            health = ("HEALTHY" if work == "RUNNING" and data_st == "HEALTHY" else
                      "NOT_MEASURED" if work in (None, "UNKNOWN") else
                      "CRITICAL" if work == "FAILED" else "DEGRADED")
            pk[key] = {"state": health, "work": work, "data": data_st,
                       "decision": (p.get("decision") or {}).get("state"),
                       "position": safe_text((p.get("decision") or {}).get("position_en"), 200),
                       "position_ru": safe_text((p.get("decision") or {}).get("position_ru"), 200),
                       "evidence": observed(observed(p, "history", kind=dict), "state"),
                       "valid_periods": observed(observed(p, "history", kind=dict), "valid_periods"),
                       "mechanism": safe_text(p.get("mechanic_short_en"), 200),
                       "mechanism_ru": safe_text(p.get("mechanic_short_ru"), 200),
                       "version": p.get("running_version"),
                       "live": (p.get("mode") or {}).get("live"), "mode": (p.get("mode") or {}).get("state"),
                       "live_reason": safe_text((p.get("mode") or {}).get("live_reason_en"), 240),
                       "live_reason_ru": safe_text((p.get("mode") or {}).get("live_reason_ru"), 240),
                       "composition": safe_text((p.get("composition") or {}).get("summary_en"), 300) if isinstance(p.get("composition"), dict) else None,
                       "last_run_at": (p.get("work") or {}).get("last_run_at")}
        _r = {"HEALTHY": 0, "DEGRADED": 1, "STALE": 1, "NOT_MEASURED": 2, "CRITICAL": 3}
        worst = max([v["state"] for v in pk.values()] or ["NOT_MEASURED"], key=lambda x: _r.get(x, 2))
        packages = {"_meta": _meta(worst, ["package_status.public_view"], _ts(pv.get("generated_at")), now, 120,
                                   reason=None if worst == "HEALTHY" else
                                   "; ".join(f"{k} {v['state']} (work {v['work']}, data {v['data']})" for k, v in pk.items()
                                             if v["state"] != "HEALTHY") or "no packages in the read model"),
                    "items": pk, "status_colour_is_not_a_risk_grade": True}
    else:
        packages = _nm(["package_status.public_view"], now, f"package read model failed {pkg_err or ''}".strip())

    tr = rep.get("trading")
    if isinstance(tr, dict):
        trs_state = "HEALTHY" if tr.get("ok") else "DEGRADED"
        trading = {"_meta": _meta(trs_state, ["data/trading_research/status.json"],
                                  now - timedelta(hours=tr["age_h"]) if tr.get("age_h") is not None else None, now, 60),
                   "candidates": tr.get("candidates"), "qualified": tr.get("backtest_qualified"),
                   "forward_paper": tr.get("forward_paper"), "observations": tr.get("observations"),
                   "evidence_chain": ("VERIFIED" if tr.get("evidence_verified") is True else
                                      "BROKEN" if tr.get("evidence_verified") is False else "NOT_MEASURED"),
                   "mode": "PAPER", "live_capital_usd": tr.get("live_capital_usd")}
    else:
        trading = _nm(["data/trading_research/status.json"], now, "trading research status not readable")

    pts = _read_json(data / "paper_trading_status.json")
    mode = (pts or {}).get("execution_mode")
    live_vals = [v for v in ((pv or {}).get("live_capital_usd") if isinstance(pv, dict) else None,
                             (tr or {}).get("live_capital_usd") if isinstance(tr, dict) else None) if v is not None]
    if mode is None and not live_vals:
        real = {"state": "UNKNOWN", "usd": None, "basis": "execution mode and live capital not readable"}
    else:
        # WP-A05 #8: $0 needs a READABLE paper execution mode — the engines' live_capital_usd are constants
        ok = mode in ("read_only_simulation", "paper") and all(v == 0 for v in live_vals)
        real = {"state": "LIVE_NOT_APPROVED" if ok else "UNKNOWN",
                "usd": 0 if ok else None,
                "basis": f"execution_mode={mode}; live_capital_usd reported by the paper engines={live_vals}"}
    _rank = {"HEALTHY": 0, "DEGRADED": 1, "STALE": 1, "NOT_MEASURED": 2, "CRITICAL": 3}
    cap_state = max((packages["_meta"]["state"], trading["_meta"]["state"]), key=lambda s: _rank.get(s, 2))
    investment_cio = _investment_cio_section(data, now)
    live_readiness = _live_readiness_section(data, now)
    research_universe = _research_universe_section(data, now)
    capital = {"_meta": _meta(cap_state,
                              ["package_status.public_view", "data/trading_research/status.json",
                               "data/paper_trading_status.json"], now, now),
               "packages": packages, "trading_research": trading, "real_capital": real,
               "investment_cio": investment_cio,
               "live_readiness": live_readiness,
               "research_universe": research_universe,
               "boundary": "SPA / Capital — research and paper only; no execution path is exposed here"}

    # ── STUDIO ─────────────────────────────────────────────────────────────────────────────────
    from spa_core.studio_os import build_loop as bl
    tdir = Path(inp.mirror) / "nimbalyst-local" / "tracker"
    msync = _mirror_synced_at(inp)
    cards = _cards(tdir)
    prod_cards = _cards(Path(inp.repo) / "nimbalyst-local" / "tracker") if Path(inp.repo) != Path(inp.mirror) else None
    roadmap = _roadmap(Path(inp.mirror))
    if cards is None:
        board = _nm(["origin tracker"], now, "tracker not readable")
        lineage = {}
    else:
        try:
            b = bl.board(tdir)
        except Exception as exc:  # noqa: BLE001
            b = None
        if b is None:
            board = _nm(["build_loop.board"], now, "board failed")
            lineage = {}
        else:
            def _row(r):
                return {"id": r["card"], "title": safe_text(r["title"], 140), "type": r.get("type"),
                        "last_transition": (r.get("last_transition") or "")[:20] or None}
            board = {"_meta": _meta("HEALTHY", ["build_loop.board (origin tracker)"], msync, now, MIRROR_STALE_MIN),
                     "counts": b["counts"], "in_progress": [_row(r) for r in b["active"][:30]],
                     "blocked": [_row(r) for r in b["blocked"][:30]],
                     "review": None, "review_note": "the card lifecycle has no REVIEW status; review evidence is a lineage stage",
                     "recently_done": [_row(r) for r in b["recently_closed"][:15]],
                     "queued": b["counts"].get("new", 0) + b["counts"].get("backlog", 0)}
            lineage = {}
            for r in (b["recently_closed"][:8] + b["active"][:8]):
                try:
                    x = bl.lineage(r["card"], tdir=tdir, root=Path(inp.mirror), data_dir=data, memory=inp.measure_host)
                except Exception:  # noqa: BLE001
                    continue
                if x.get("state") == "NOT_FOUND":
                    continue
                lineage[r["card"]] = {s: {"state": v["state"],
                                          "evidence": safe_text(json.dumps(v["evidence"], ensure_ascii=False)
                                                                if not isinstance(v["evidence"], str) else v["evidence"], 220)}
                                      for s, v in x["stages"].items()}
    orr = _read_json(data / "orphan_report.json")
    orphans = ({"_meta": _meta("HEALTHY", ["data/orphan_report.json"], _ts(orr.get("generated_at")), now, 2880),
                "total": orr.get("total"), "counts": orr.get("counts")}
               if isinstance(orr, dict) else _nm(["data/orphan_report.json"], now, "no orphan report yet"))
    studio = {"_meta": _meta("HEALTHY", ["origin tracker", "docs/ROADMAP.md", "data/agent_health.json"], msync, now,
                             MIRROR_STALE_MIN),
              "epics": {"items": roadmap["items"], "current": roadmap["current"], "roadmap_confirmed": roadmap["confirmed"]},
              "board": board, "lineage": lineage, "agents": agents, "orphans": orphans,
              "sessions": {"claude_workers": rep.get("claude_sessions")}}

    # ── DECISIONS ──────────────────────────────────────────────────────────────────────────────
    bot = os.environ.get("SPA_TELEGRAM_BOT_USERNAME") or TELEGRAM_BOT
    if cards is None:
        decisions = _nm(["origin tracker"], now, "tracker not readable")
    else:
        items, resolved = [], []
        prod_names = set(prod_cards) if prod_cards is not None else (set(cards) if Path(inp.repo) == Path(inp.mirror) else None)
        for name, c in sorted(cards.items()):
            t = (c["fm"].get("type") or "")
            is_owner = t == "owner-decision" or name.startswith(("owner-decision-", "own-"))
            st = c["fm"].get("status")
            if not is_owner and st not in ("needs-owner", "owner-accepted"):
                continue
            d = decision_item(name, c, (prod_cards or {}).get(name), bot, prod_names)
            if st in ("needs-owner", "owner-accepted"):
                items.append(d)
            elif d["answered_at"] and _ts(d["answered_at"]) and (now - _ts(d["answered_at"])) < timedelta(days=7):
                resolved.append(d)
        items.sort(key=lambda d: d["created_at"])
        decisions = {"_meta": _meta("HEALTHY", ["origin tracker owner cards", "production-tree owner answers"], msync, now,
                                    MIRROR_STALE_MIN),
                     "pending": items, "recently_resolved": resolved[:10],
                     "counts": {"needs_owner": sum(1 for d in items if d["state"] == "NEEDS_OWNER"),
                                "accepted_in_work": sum(1 for d in items if d["state"] == "ACCEPTED"),
                                "answered_awaiting_delivery": sum(1 for d in items if d["state"] == "ANSWERED")},
                     "how_to_answer": "Telegram (SPA bot): the same canonical path as every other answer — this UI is read-only"}

    feed = release_feed(inp, now, cs)

    # ── OVERVIEW (composition only — no new numbers) ───────────────────────────────────────────
    bcounts = observed(board, "counts", kind=dict)
    alerts = [safe_text(a, 200) for a in (rep.get("alerts") or [])]
    crit = [a for a in alerts if a and (a.startswith("🔴") or a.startswith("🛑"))]
    today = [i for i in (feed.get("items") or []) if _ts(i["at"]) and (now - _ts(i["at"])) < timedelta(hours=24)]
    overview = {
        "system": {"state": system["_meta"]["state"], "reason": system["_meta"]["reason"],
                   "counts": system["_meta"]["counts"], "critical_alerts": crit,
                   "alerts": alerts[:8], "kill_switch": rep.get("kill_switch_active"), "derisk": rep.get("derisk_active")},
        "needs_owner": ({"count": decisions["counts"]["needs_owner"], "accepted_in_work": decisions["counts"]["accepted_in_work"],
                         "top": [{"id": d["id"], "title": d["title"], "created_at": d["created_at"]} for d in decisions["pending"][:3]]}
                        if "pending" in decisions else {"count": None}),
        # a status absent from measured board counts is a measured zero; no counts at all is «not measured»
        "now": {"current_epic": roadmap["current"],
                "in_progress": (bcounts.get("in-progress", 0) if bcounts is not None else None),
                "blocked": (bcounts.get("blocked", 0) if bcounts is not None else None),
                "claude_workers": rep.get("claude_sessions"),
                "heavy_jobs": len(leases) if isinstance(leases, list) else None},
        "capital": {"real_capital": real,
                    "investment_cio": ({"stance": investment_cio.get("stance"), "confidence": investment_cio.get("confidence"),
                                        "date": investment_cio.get("date"), "state": investment_cio["_meta"]["state"]}),
                    "packages": {k: {"state": v["state"], "work": v["work"], "decision": v["decision"], "evidence": v["evidence"],
                                     "live": v["live"]} for k, v in (packages.get("items") or {}).items()},
                    "trading_research": {"state": trading["_meta"]["state"], "forward_paper": trading.get("forward_paper"),
                                         "candidates": trading.get("candidates")}},
        "today": {"releases": len([i for i in today if i["kind"] not in ("housekeeping",)]),
                  "release_items": today[:6], "incidents": (incidents.get("open") if "open" in incidents else None)},
        "resources": {"state": resources["_meta"]["state"], "disk_free_gb": (resources.get("disk") or {}).get("free_gb"),
                      "pressure_level": (resources.get("memory") or {}).get("pressure_level"),
                      "swap_used_pct": (resources.get("memory") or {}).get("swap_used_pct")},
    }
    intake = {
        "ask": f"https://t.me/{BRIDGE_BOT}", "idea": f"https://t.me/{BRIDGE_BOT}",
        "voice": f"https://t.me/{BRIDGE_BOT}", "report": f"https://t.me/{BRIDGE_BOT}",
        "decisions": f"https://t.me/{bot}",
        "how": ("Ask / Idea / Voice go to the Studio Bridge bot: text or a voice note, classified, then CONFIRMED by "
                "you before anything is written (ADR-521). Decisions are answered in the SPA bot with its buttons. "
                "This page writes nothing."),
    }
    return {"schema": SCHEMA, "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "areas": AREAS, "intake": intake,
            "vocabulary": {"operational": OPERATIONAL, "health": HEALTH, "work": WORK, "decision": DECISION,
                           "capital_mode": CAPITAL_MODE, "evidence": EVIDENCE,
                           "colour_rule": "colour follows HEALTH only — never profit, risk or approval for real money"},
            "contract": CONTRACT, "overview": overview, "capital": capital, "studio": studio,
            "decisions": decisions, "system": system, "release_feed": feed}


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(description="Mission Control v1 read model (ADR-552)")
    ap.add_argument("--out", default=None, help="write the model here (atomic); default: stdout")
    a = ap.parse_args(argv)
    model = build()
    if a.out:
        from spa_core.utils.atomic import atomic_save
        atomic_save(model, a.out)
        print(f"written {a.out}: system={model['system']['_meta']['state']} decisions={model['overview']['needs_owner'].get('count')}")
    else:
        print(json.dumps(model, ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
