"""ARB continuity read model (ADR-610, ARB-CONTINUITY-01).

Builds the GENERATED half of the fresh-session entry point — ``docs/continuity/CURRENT_STATE.md``,
``ARCHITECT_DECISION_INDEX.md`` and their machine twin ``state.json`` — from canonical sources only,
and answers one question: is a recorded context still fresh enough to decide architecture on?

    python -m spa_core.studio_os.memory continuity build [--root R] [--out O] [--at ISO] [--receipt F] [--mission F]
    python -m spa_core.studio_os.memory continuity check [same options]   # exit 0 FRESH · 1 PARTIAL · 2 STALE

What it reads (and nothing else — no data/ crawl, no secrets, no network, no model):
  * CANONICAL inputs under ``--root`` (a clean origin checkout — the mirror on the Mac): CLAUDE.md,
    docs/ROADMAP.md, architecture/{memory_truth,roles}.json, the curated docs/continuity/* contract,
    this generator, every ADR cited by a decision topic or an intent, plus a digest of who supersedes
    them (a new ADR that supersedes a cited one makes the context stale; an unrelated one does not);
  * RUNTIME, two explicit single files: the production code-sync receipt (``code_sync_status.json`` →
    production code identity) and the published Mission Control bundle (``mission.json`` → its
    Company Truth section). Company Truth is computed on read inside Mission Control and NOT
    recomputed here (ADR-592, import ratchet): this module only projects cells the cockpit shows.

Freshness verdicts (``check``):
  CONTEXT_STALE   a canonical input changed / appeared / vanished; the contract or generator changed;
                  the production release moved by a change outside the generated outputs; the
                  production identity can no longer be verified; the runtime truth is older than
                  RUNTIME_MAX_AGE_H; the outputs were tampered with or are missing; malformed metadata.
  CONTEXT_PARTIAL bytes and identities hold, but UNKNOWN facts remain (or runtime was absent).
  CONTEXT_FRESH   everything recorded still holds.
A moved repo/origin commit whose canonical inputs are byte-identical is NOT stale (the committed
CURRENT_STATE can never name the commit that contains it); it is reported as a note.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.studio_os.memory.sources import sanitize
from spa_core.studio_os.memory.truth import Truth, adr_id

VERSION = "arb-continuity/2"
UNKNOWN = "UNKNOWN"
RUNTIME_MAX_AGE_H = 24.0
HEX40 = re.compile(r"^[0-9a-f]{40}$")
CODE_REPO = Path(__file__).resolve().parents[3]

CONTRACT_DIR = "docs/continuity"
CONTEXT_FILE = f"{CONTRACT_DIR}/ARCHITECT_CONTEXT.md"
LEDGER_FILE = f"{CONTRACT_DIR}/OWNER_INTENT_LEDGER.md"
BOOTSTRAP_FILE = f"{CONTRACT_DIR}/BOOTSTRAP.md"
SCHEMA_FILE = f"{CONTRACT_DIR}/CURRENT_STATE.schema.json"
GENERATOR_FILE = "spa_core/studio_os/memory/continuity.py"
#: Generated outputs — never inputs (a feedback loop would make every rebuild "change a source").
OUTPUTS = ("CURRENT_STATE.md", "ARCHITECT_DECISION_INDEX.md", "state.json")
OUTPUT_PATHS = tuple(f"{CONTRACT_DIR}/{n}" for n in OUTPUTS)
REQUIRED_INPUTS = ("CLAUDE.md", "docs/ROADMAP.md", "docs/STATE.md", "docs/decisions/INDEX.md",
                   "architecture/memory_truth.json", "architecture/roles.json",
                   CONTEXT_FILE, LEDGER_FILE, BOOTSTRAP_FILE, SCHEMA_FILE, GENERATOR_FILE)

#: The decision map. Class is DECLARED here with its reason; the cited ADR's own status is RESOLVED
#: from canon at build time and overrides the declaration when the canon says otherwise
#: (superseded / not accepted / missing ⇒ the row cannot stay CURRENT).
DECISION_TOPICS: Tuple[Dict[str, Any], ...] = (
    dict(topic="three-world-model", cls="CURRENT", adrs=("ADR-592", "ADR-580"),
         title="Three worlds: CAPITAL / STUDIO OS / EARN DEFI PRODUCT",
         note="ADR-592 §6 information architecture; ADR-580 contracts C1–C12 per domain."),
    dict(topic="owner-boundary", cls="CURRENT", adrs=("ADR-285",),
         title="The owner decides exactly three subjects: real money, public numbers/naming/legal, irreversible actions",
         note="Everything else the agent decides and records in the journal."),
    dict(topic="rm-truth-contracts", cls="CURRENT", adrs=("ADR-580",),
         title="RM-TRUTH-01 contracts C1–C12 (one writer, typed numbers, scoped readiness, one owner queue, Problem store, DR coverage)",
         note="Frozen after independent review; map in docs/rm_truth/."),
    dict(topic="director-os-read-model", cls="CURRENT", adrs=("ADR-592",),
         title="Director OS v2 = Mission Control; Company Truth computed on read — a read model, not an authority",
         note="No agent or gate reads Company Truth (import ratchet)."),
    dict(topic="director-os-v1-cockpits", cls="SUPERSEDED", adrs=("ADR-592",),
         title="Director OS :8788, Studio Shell :8778, repo dashboard :8767 as owner cockpits",
         note="Presentation superseded by ADR-592; unloading their agents is an owner action."),
    dict(topic="mission-control-v1", cls="CURRENT", adrs=("ADR-552",),
         title="Owner Remote / Mission Control v1 — read-only, loopback :8790, phone via Cloudflare Access",
         note="Evolved in place into Director OS v2 (ADR-592)."),
    dict(topic="trading-lab-canonical", cls="CURRENT", adrs=("ADR-590", "ADR-525"),
         title="Trading Research Engine v0 is the ONLY active Trading Lab line",
         note="Research/paper only; forward clocks immutable."),
    dict(topic="older-btc-engines", cls="SUPERSEDED", adrs=("ADR-590",),
         title="research/btc_cycle and btc_nav (older SPA BTC systems)",
         note="SUPERSEDED_HISTORY; the earn-defi BTC Signal Engine is a SEPARATE_PRODUCT, not superseded."),
    dict(topic="oracle-cio", cls="CURRENT", adrs=("ADR-554",),
         title="Oracle = Chief Investment Officer: advisory/paper cross-sleeve recommendation; executes nothing",
         note="Display name Oracle since 2026-10-04 («Штирлиц» before)."),
    dict(topic="sherlock-research", cls="CURRENT", adrs=("ADR-564",),
         title="Sherlock = Head of Research: deterministic evidence and paper admission; no capital authority",
         note="Curated facts count only after content-hash-bound review."),
    dict(topic="research-factory", cls="CURRENT", adrs=("ADR-560",),
         title="Research Factory v1: capital universe by economic mechanism, RESEARCH → PAPER → CIO_ELIGIBLE",
         note="No candidate is live-authorized."),
    dict(topic="shadow-execution", cls="CURRENT", adrs=("ADR-556",),
         title="Shadow execution; automated live execution PROHIBITED; a real-capital pilot is owner-gated",
         note="Unsigned intents, keyless quorum simulation."),
    dict(topic="three-paper-portfolios", cls="CURRENT", adrs=("ADR-533", "ADR-548"),
         title="Conservative / Balanced / Aggressive = three PAPER portfolios with different mechanics",
         note="docs/ROADMAP.md item 3 cites ADR-537 for the owner gate; the gate decision itself is ADR-548."),
    dict(topic="aggressive-simulated-loop", cls="EXPERIMENTAL", adrs=("ADR-533",),
         title="Aggressive = SIMULATED sUSDe/PYUSD loop (paper experiment, refused for live)",
         note="Evidence level L2 until a 30-period paper record exists."),
    dict(topic="public-internal-naming", cls="CURRENT", adrs=("ADR-593", "ADR-285"),
         title="Public tiers Conservative/Balanced/Aggressive; Conservative = the evidenced book; naming is owner subject №2",
         note="Alt names Preserve/Core/Max Yield are «owner choice #6» (landing/src/lib/tier_bands.json); Core is ambiguous."),
    dict(topic="published-rate-rounds-down", cls="CURRENT", adrs=("ADR-563",),
         title="The published yield rate rounds DOWN", note="Owner option 1, 2026-10-04."),
    dict(topic="single-roadmap-and-memory-v1", cls="CURRENT", adrs=("ADR-527",),
         title="Memory & Context Architecture v1; docs/ROADMAP.md is the single roadmap",
         note="Five memory layers; chat is never canonical."),
    dict(topic="memory-hybrid", cls="CURRENT", adrs=("ADR-591", "ADR-527"),
         title="Memory = HYBRID_BORROW_COMPONENTS (stdlib FTS5 + two borrowed ideas)", note=""),
    dict(topic="mempalace-dependency", cls="REJECTED", adrs=("ADR-591", "ADR-527"),
         title="MemPalace as a runtime dependency",
         note="Rejected on measurement (top-5 12/51 vs 31/51, 81 dependencies, stdlib invariant #4)."),
    dict(topic="openclaw", cls="SUPERSEDED", adrs=("ADR-599",), disposition="REMOVED_RETIRED",
         title="OpenClaw third-party AI gateway (Telegram + local model, shell access)",
         note="Removed by explicit owner decision 2026-10-07; no SPA component depended on it."),
    dict(topic="backup-offsite", cls="CURRENT", adrs=("ADR-580", "ADR-611"),
         title="DR: typed archive classes FULL / CRITICAL (never chosen by age across classes) + verified off-device copy to iCloud Drive",
         note="C10 DR coverage; ADR-611 archive classes; commits 1c5445d3 (iCloud default) and fe0534b5 (CIO *.json.gz). Upload to Apple servers is NOT_MEASURED from the Mac."),
    dict(topic="telegram-capital-readonly", cls="CURRENT", adrs=("ADR-612", "ADR-521"),
         title="Telegram Capital surface /capital /btc /lab /oracle /sherlock — read-only, same readers as Mission Control; Director OS reasons in plain Russian",
         note="Delivered 2026-10-07 (2b8887cb). nav-only buttons, no act: verb; free-text money orders refused before the classifier; REAL CAPITAL $0, no execution."),
    dict(topic="strict-promotion-guard", cls="CURRENT", adrs=("ADR-610",),
         title="Guarded promotion only: push_to_github.py --expected-base <sha>, STOP on drift, no --allow-overwrite, no force",
         note="Owner decisions 2026-10-06 (no --allow-overwrite; fix the guard); review trail docs/rm_truth/REVIEW_PUSHER_FIX_*.md."),
    dict(topic="arb-continuity", cls="CURRENT", adrs=("ADR-610",),
         title="ARB continuity: curated context + intent ledger + generated, freshness-checked CURRENT_STATE",
         note="Generated files are DERIVED (authority 0), never a second state store."),
)

#: Public profile ↔ internal book ↔ decision ↔ track source ↔ metric type (ADR-610 §10, ARB §10).
#: The runtime cell's metric type must equal the declared one — a crossing refuses the build.
PROFILE_MAP: Tuple[Dict[str, Any], ...] = (
    dict(profile="Conservative", alt_name="Preserve", internal_book="main cycle_runner book (RiskPolicy v1.0)",
         track_source="data/equity_curve_daily.json", decision="ADR-593",
         runtime="product.profiles.conservative", metric="REALIZED_PAPER_RETURN"),
    dict(profile="Balanced", alt_name="Core (ambiguous)", internal_book="fixed-rate PT sleeve (balanced-fixed-carry-v1)",
         track_source="data/hy_paper_trading.json", decision="ADR-533",
         runtime="product.profiles.balanced", metric="REALIZED_PAPER_RETURN"),
    dict(profile="Aggressive", alt_name="Max Yield", internal_book="SIMULATED sUSDe/PYUSD loop sleeve",
         track_source="data/lp_paper_trading.json", decision="ADR-533",
         runtime="product.profiles.aggressive", metric="REALIZED_PAPER_RETURN"),
    dict(profile="All three (target bands)", alt_name="—", internal_book="research targets, not results",
         track_source="landing/src/lib/tier_bands.json", decision="ADR-548",
         runtime="capital.defi.targets", metric="TARGET_RETURN"),
)
#: Company Truth metric_type → the five return kinds the owner named (ADR-580 C2). Never collapsed.
RETURN_KIND = {"TARGET": "TARGET_RETURN", "OBSERVED": "OBSERVED_RETURN", "REALIZED_PAPER": "REALIZED_PAPER_RETURN",
               "MODELLED": "MODELLED_RETURN", "BACKTEST": "BACKTEST_RETURN"}

INTENT_FIELDS = ("owner_intent", "why_it_matters", "first_known_evidence", "current_implementation",
                 "current_status", "known_gaps", "relevant_decisions", "superseded_implementations", "last_verified")

SECTION_ORDER = ("active_epic", "latest_accepted_epic", "current_origin", "production_code", "real_capital",
                 "live_execution", "capital_summary", "trading_lab", "btc", "defi_paper", "oracle", "sherlock",
                 "studio_os", "director_os", "memory", "product_publication", "active_problems", "test_health", "owner_gates",
                 "technical_debt", "next_safe_action", "last_verification")


class ContinuityError(Exception):
    """A refusal: the context cannot be built from verified canonical sources (fail-CLOSED)."""


# ── small helpers ─────────────────────────────────────────────────────────────────────────────

def _digest(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _stamp(s: str) -> datetime:
    d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    if d.tzinfo is None:
        raise ValueError("timestamp without timezone")
    return d.astimezone(timezone.utc)


def _stamp_or_none(s: Any) -> Optional[datetime]:
    try:
        return _stamp(s) if isinstance(s, str) and s.strip() else None
    except ValueError:
        return None


def _iso(d: datetime) -> str:
    return d.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_ABS = re.compile(r"(?:/Users|/private|/var|/tmp|/Library|/opt|/home|~)/[^\s'\"`)|]+")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def clean(s: Any, limit: int = 400) -> str:
    """Memory's credential sanitizer first, then no absolute paths/e-mails, one line, bounded."""
    t = sanitize(str(s))[0]
    t = _EMAIL.sub("<email>", _ABS.sub("<path>", t))
    t = re.sub(r"\s+", " ", t).replace("|", "/").strip()
    return (t[:limit].rstrip() + "…") if len(t) > limit else (t or UNKNOWN)


def _git(root: Path, *args: str) -> Optional[str]:
    try:
        p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        return None
    return p.stdout.strip() if p.returncode == 0 else None


def origin_head(root: Path) -> Optional[str]:
    """The origin head as the SERVER reports it (`git ls-remote`, read-only — no ref is written).

    The local `refs/remotes/origin/main` is a cache of somebody's last fetch with no age and no
    provenance (ADR-361/362, `scripts/python_git_ref_provenance.py`); a freshness gate must not take
    it for the origin. No network ⇒ None ⇒ UNKNOWN, never the cached value.
    """
    out = _git(root, "ls-remote", "origin", "refs/heads/main")
    if not out:
        return None
    sha = out.split()[0]
    return sha if HEX40.match(sha) else None


def _sha_or_unknown(v: Optional[str]) -> str:
    return v if v and HEX40.match(v) else UNKNOWN


def _safe_read(root: Path, rel: str) -> Optional[bytes]:
    p = root / rel
    if p.is_symlink():
        raise ContinuityError(f"REFUSED: source is a symlink: {rel}")
    try:
        if not p.resolve().is_relative_to(root.resolve()):
            raise ContinuityError(f"REFUSED: source escapes the root: {rel}")
    except OSError as exc:
        raise ContinuityError(f"REFUSED: cannot resolve {rel}: {exc}")
    return p.read_bytes() if p.is_file() else None


def _read_runtime(path: Optional[Path]) -> Tuple[Optional[bytes], str]:
    if path is None:
        return None, "not supplied"
    if path.is_symlink():
        raise ContinuityError(f"REFUSED: runtime file is a symlink: {path.name}")
    if not path.is_file():
        return None, "absent"
    return path.read_bytes(), "read"


# ── canonical inputs ──────────────────────────────────────────────────────────────────────────

ADR_DIRS = ("docs/decisions", "docs/adr")


def _adr_files(root: Path, registry: str = "docs/decisions") -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {}
    d = root / registry
    for p in sorted(d.glob("ADR-*.md")) if d.is_dir() else []:
        aid = adr_id(p.name)
        if aid:
            out.setdefault(aid, []).append(f"{registry}/{p.name}")
    return out


def adr_max_considered(listing: List[str]) -> Optional[int]:
    """Highest ADR number present in either registry at generation — the line a no-machine reader
    compares the current registry against (BOOTSTRAP step 3); ``None`` when no ADR was listed."""
    nums = [int(m.group(1)) for x in listing for m in [re.match(r"ADR-(\d+)", x.rsplit("/", 1)[-1])] if m]
    return max(nums) if nums else None


def _adr_listing(root: Path) -> List[str]:
    """Every ADR file NAME in both registries. A new ADR anywhere may be a decision the index lacks."""
    return sorted(f"{reg}/{p.name}" for reg in ADR_DIRS for p in (root / reg).glob("*.md")
                  if (root / reg).is_dir() and p.name.startswith("ADR-"))


_EFFECTIVE = (r"(?im)^[\s>*\-]*\**(?:date of decision|дата решения)\**\s*[:：]\**\s*\**\s*(20\d\d-\d\d-\d\d)",
              r"(?im)^[\s>*\-]*\**(?:date|дата)\**\s*[:：]\**\s*\**\s*(20\d\d-\d\d-\d\d)",
              r"(?im)^[\s>*\-]*\**(?:status|статус)\**\s*[:：][^\n]*?(20\d\d-\d\d-\d\d)")


def adr_effective(text: str) -> str:
    """Decision date: «Date of decision» → «Date» → the status line → UNKNOWN. Never the first date in
    the file (ADR-593's first date is the BACKFILL day, not the decision day)."""
    head = text[:4000]
    for rx in _EFFECTIVE:
        m = re.search(rx, head)
        if m:
            return m.group(1)
    return UNKNOWN


def parse_ledger(text: str) -> List[Dict[str, str]]:
    """Curated intent ledger → entries. Refuses a duplicate id or a missing field (fail-CLOSED)."""
    entries: List[Dict[str, str]] = []
    seen = set()
    for m in re.finditer(r"(?ms)^## (INT-\d+) · ([^\n]+)\n(.*?)(?=^## |\Z)", text):
        iid, title, body = m.group(1), m.group(2).strip(), m.group(3)
        if iid in seen:
            raise ContinuityError(f"REFUSED: duplicate intent id {iid} in {LEDGER_FILE}")
        seen.add(iid)
        fields = dict(re.findall(r"(?m)^- \*\*(\w+):\*\* (.+)$", body))
        missing = [f for f in INTENT_FIELDS if not fields.get(f, "").strip()]
        if missing:
            raise ContinuityError(f"REFUSED: intent {iid} is missing field(s) {missing}")
        entries.append(dict(intent_id=iid, title=title, **{f: fields[f].strip() for f in INTENT_FIELDS}))
    if not entries:
        raise ContinuityError(f"REFUSED: {LEDGER_FILE} carries no intent sections")
    return entries


def _latest_done_adr(roadmap: str) -> Optional[str]:
    found = [m.group(2) for _, body in _roadmap_items(roadmap)
             for m in [re.match(r"~~(.+?)~~\s*—\s*DONE\b.*?\((ADR-\d+)\)", body)] if m]
    return found[-1] if found else None


def _cited_adrs(intents: List[Dict[str, str]], roadmap: str = "") -> List[str]:
    ids = {a for t in DECISION_TOPICS for a in t["adrs"]}
    for i in intents:
        ids.update(re.findall(r"ADR-\d+", i["relevant_decisions"]))
    latest = _latest_done_adr(roadmap)
    if latest:
        ids.add(latest)
    return sorted(ids)


def inventory(root: Path) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, Any]]:
    """(input hashes, texts, aux). Refuses a missing required input or an unreadable/ambiguous ADR."""
    root = root.resolve()
    texts: Dict[str, str] = {}
    hashes: Dict[str, str] = {}
    for rel in REQUIRED_INPUTS:
        b = _safe_read(root, rel)
        if b is None:
            raise ContinuityError(f"REFUSED: required canonical source missing: {rel}")
        texts[rel], hashes[rel] = b.decode("utf-8"), _digest(b)
    intents = parse_ledger(texts[LEDGER_FILE])
    adr_map = _adr_files(root)
    adr_b = _adr_files(root, "docs/adr")
    all_adrs = {}
    for aid, paths in adr_map.items():
        for rel in paths:
            all_adrs[rel] = (_safe_read(root, rel) or b"").decode("utf-8", "replace")
    registry = json.loads(texts["architecture/memory_truth.json"])
    truth = Truth(registry, [("spa:" + rel, "CANONICAL", "adr", t) for rel, t in all_adrs.items()])
    cited = _cited_adrs(intents, texts["docs/ROADMAP.md"])
    resolved: Dict[str, Dict[str, Any]] = {}
    for aid in cited:
        paths = adr_map.get(aid, [])
        if len(paths) != 1:
            resolved[aid] = dict(path=UNKNOWN, status=UNKNOWN, basis=f"{len(paths)} files carry this number",
                                 superseded_by=None, effective=UNKNOWN, title=UNKNOWN, number_collision=None)
            continue
        rel = paths[0]
        t = all_adrs[rel]
        texts[rel], hashes[rel] = t, _digest(t.encode("utf-8"))
        r = truth.resolve("spa:" + rel, "CANONICAL", t)
        resolved[aid] = dict(path=rel, status=r["status"], basis=r["basis"],
                             superseded_by=r.get("superseded_by"), effective=adr_effective(t),
                             title=clean(t.splitlines()[0].lstrip("# ") if t else aid, 200),
                             # docs/decisions is canonical (ADR-527); the historical docs/adr registry reuses
                             # some numbers — the number is AMBIGUOUS when cited without a path.
                             number_collision=adr_b.get(aid) or None)
    # A NEW ADR that supersedes a cited one is material; an unrelated new ADR is not.
    sup = {aid: resolved[aid]["superseded_by"] for aid in cited}
    hashes["derived:supersession_of_cited_adrs"] = _digest(json.dumps(sup, sort_keys=True).encode())
    # Any ADR added or removed in either registry is material: the decision index may lack it (review P1-2).
    hashes["derived:adr_registry_listing"] = _digest("\n".join(_adr_listing(root)).encode())
    return hashes, texts, dict(intents=intents, resolved=resolved, registry=registry, adr_map=adr_map)


# ── runtime projections (Company Truth via the published Mission Control bundle) ──────────────

def load_mission(path: Optional[Path]) -> Tuple[Optional[dict], Dict[str, Any]]:
    """A ``current.json`` pointer or a ``mission.json`` file. Returns (truth section, meta)."""
    raw, how = _read_runtime(path)
    if raw is None:
        return None, dict(state=UNKNOWN, reason=f"mission bundle {how}", sha256=None, bundle=None, computed_at=None)
    try:
        doc = json.loads(raw)
        bundle = None
        if "bundle" in doc and "truth" not in doc:          # the current.json pointer
            bundle = str(doc["bundle"])
            if not re.fullmatch(r"b-[0-9TZ]+-[0-9a-f]{8}", bundle):
                raise ValueError("bundle name has an unexpected shape")
            raw, how = _read_runtime(path.parent / bundle / "mission.json")
            if raw is None:
                return None, dict(state=UNKNOWN, reason=f"bundle mission.json {how}", sha256=None, bundle=bundle,
                                  computed_at=None)
            doc = json.loads(raw)
        truth = doc.get("truth")
        if not isinstance(truth, dict) or truth.get("schema") != "company-truth/1":
            return None, dict(state=UNKNOWN, reason="no company-truth/1 section", sha256=_digest(raw), bundle=bundle,
                              computed_at=None)
        computed = truth.get("computed_at")
        _stamp(computed)
        return truth, dict(state="READ", reason="read", sha256=_digest(raw), bundle=bundle, computed_at=computed)
    except (ValueError, TypeError, KeyError) as exc:
        return None, dict(state=UNKNOWN, reason=f"unreadable: {type(exc).__name__}", sha256=None, bundle=None,
                          computed_at=None)


def load_receipt(path: Optional[Path]) -> Dict[str, Any]:
    raw, how = _read_runtime(path)
    if raw is None:
        return dict(production_release=UNKNOWN, verified_at=None, sha256=None, reason=f"receipt {how}")
    try:
        d = json.loads(raw)
        sha, res = str(d.get("origin_main", "")), d.get("result")
        ts = _iso(_stamp(d["timestamp"]))
        if res in ("IN_SYNC", "SYNCED") and HEX40.match(sha):
            return dict(production_release=sha, verified_at=ts, sha256=_digest(raw), reason=f"code sync {res}")
        return dict(production_release=UNKNOWN, verified_at=ts, sha256=_digest(raw),
                    reason=f"code sync result {res!r} does not prove a production commit")
    except (ValueError, TypeError, KeyError) as exc:
        return dict(production_release=UNKNOWN, verified_at=None, sha256=_digest(raw),
                    reason=f"receipt unreadable: {type(exc).__name__}")


def _get(truth: Optional[dict], path: str) -> Optional[dict]:
    cur: Any = truth
    for k in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(k)
    return cur if isinstance(cur, dict) else None


def _section(display: Any, source: str, status: str, as_of: Optional[str] = None, value: Any = None,
             authority: str = "RUNTIME") -> Dict[str, Any]:
    return dict(display=clean(display, 600) if display not in (None, "") else UNKNOWN, source=clean(source, 300),
                status=status, as_of=as_of, value=value, authority=authority)


def _cell_section(truth: Optional[dict], path: str, display: Any = None, value: Any = None) -> Dict[str, Any]:
    c = _get(truth, path)
    if c is None:
        return _section(None, f"runtime: mission.json truth.{path}", UNKNOWN)
    state = str(c.get("state") or UNKNOWN)
    measured = state.startswith("MEASURED")
    shown = display if display is not None else (c.get("display_ru") if measured else c.get("unknown_ru"))
    return _section(shown, f"runtime: mission.json truth.{path} (canon: {c.get('canon') or UNKNOWN})",
                    state if measured else (state if state != "MEASURED" else UNKNOWN),
                    c.get("as_of"), value if value is not None else (c.get("value") if measured else None))


def _unknown_if_none(v: Any) -> Any:
    return UNKNOWN if v is None else v


# ── roadmap (canonical) ───────────────────────────────────────────────────────────────────────

def _roadmap_items(text: str) -> List[Tuple[int, str]]:
    sect = text.split("## Order of the next epics", 1)[-1].split("\n## ", 1)[0]
    items = []
    for m in re.finditer(r"(?ms)^(\d+)\. (.*?)(?=^\d+\. |\Z)", sect):
        items.append((int(m.group(1)), re.sub(r"\s+", " ", m.group(2)).strip()))
    return items


def _clause(item: str, label: str) -> Optional[str]:
    m = re.search(label + r":\s*(.+?)(?=\s(?:Owner gates|Remaining debt|Next safe action):|$)", item)
    return m.group(1).strip().rstrip(".") if m else None


def roadmap_view(text: str, resolved_status) -> Dict[str, Any]:
    items = _roadmap_items(text)
    latest = None
    for n, body in items:
        m = re.match(r"~~(.+?)~~\s*—\s*DONE\b.*?\((ADR-\d+)\)", body)
        if m:
            latest = (n, m.group(1).strip(), m.group(2), body)
    active = next(((n, b) for n, b in items if not b.startswith("~~") and re.search(r"\bin progress\b", b)), None)
    out: Dict[str, Any] = dict(latest=None, active=None)
    if latest:
        n, name, aid, body = latest
        st = resolved_status(aid)
        out["latest"] = dict(n=n, name=clean(name, 160), adr=aid, adr_status=st,
                             accepted=st in ("ACCEPTED", "ACTIVE"), owner_gates=_clause(body, "Owner gates"),
                             remaining_debt=_clause(body, "Remaining debt"))
    if active:
        n, body = active
        name = re.match(r"\*\*(.+?)\*\*", body)
        out["active"] = dict(n=n, name=clean(name.group(1) if name else body[:120], 160),
                             owner_gates=_clause(body, "Owner gates"), next_safe_action=_clause(body, "Next safe action"))
    return out


# ── build ─────────────────────────────────────────────────────────────────────────────────────

def _decision_rows(resolved: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for t in DECISION_TOPICS:
        refs = [dict(adr=a, **resolved[a]) for a in t["adrs"]]
        cls, why = t["cls"], "declared"
        if any(r["status"] == UNKNOWN or r["path"] == UNKNOWN for r in refs):
            cls, why = UNKNOWN, "a cited ADR is missing, ambiguous or carries no status"
        elif any(r["status"] == "SUPERSEDED" for r in refs) and t["cls"] != "SUPERSEDED":
            cls, why = "SUPERSEDED", "a cited ADR is superseded in canon"
        elif any(r["status"] in ("PROPOSED", "REJECTED") for r in refs) and t["cls"] == "CURRENT":
            cls, why = UNKNOWN, "declared CURRENT but a cited ADR is not accepted"
        rows.append(dict(topic=t["topic"], title=t["title"], cls=cls, declared=t["cls"], basis=why,
                         disposition=t.get("disposition"), note=t["note"],
                         refs=[dict(adr=r["adr"], path=r["path"], status=r["status"], effective=r["effective"],
                                    superseded_by=r["superseded_by"], number_collision=r.get("number_collision"))
                               for r in refs]))
    return rows


def _intent_rows(intents: List[Dict[str, str]], resolved: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for i in intents:
        ids = sorted(set(re.findall(r"ADR-\d+", i["relevant_decisions"])))
        sts = {a: resolved[a]["status"] for a in ids}
        flags = [f"{a} is SUPERSEDED by {resolved[a]['superseded_by']}" for a in ids if sts[a] == "SUPERSEDED"]
        flags += [f"{a} not found or ambiguous in docs/decisions" for a in ids if resolved[a]["path"] == UNKNOWN]
        derived = "SUPERSEDED_DECISION" if any(s == "SUPERSEDED" for s in sts.values()) else (
            UNKNOWN if any(s == UNKNOWN for s in sts.values()) or not ids else "DECISIONS_CURRENT")
        rows.append(dict(intent_id=i["intent_id"], title=clean(i["title"], 120), decisions=ids,
                         decision_status=derived, flags=flags, curated_status=clean(i["current_status"], 200),
                         last_verified=i["last_verified"]))
    return rows


def _profile_rows(truth: Optional[dict], resolved: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for p in PROFILE_MAP:
        c = _get(truth, p["runtime"])
        mt = RETURN_KIND.get(str(c.get("metric_type"))) if c else None
        if c is not None and mt != p["metric"]:
            raise ContinuityError(f"REFUSED: metric type crossing for {p['profile']}: runtime "
                                  f"{c.get('metric_type')!r} vs declared {p['metric']} — typed numbers are never collapsed")
        state = str(c.get("state")) if c else UNKNOWN
        rate = None
        if c and state == "MEASURED":
            rate = c.get("rate_ru") or c.get("display_ru")
        reportable = None
        if c and isinstance(c.get("value"), dict):
            v = c["value"]
            reportable = v.get("reportable") if "reportable" in v else (True if v.get("evidence") == "REPORTABLE" else None)
        rows.append(dict(profile=p["profile"], alt_name=p["alt_name"], internal_book=p["internal_book"],
                         track_source=p["track_source"], decision=p["decision"],
                         effective=(resolved.get(p["decision"]) or {}).get("effective", UNKNOWN),
                         metric_type=p["metric"], runtime_state=state, value=clean(rate, 120) if rate else UNKNOWN,
                         reportable=("n/a (target, not a result)" if p["metric"] == "TARGET_RETURN"
                                     else _unknown_if_none(reportable)),
                         accumulating_days=_unknown_if_none(c.get("accumulating_days") if c else None),
                         evidenced_days=_unknown_if_none(c.get("evidenced_days") if c else None)))
    return rows


COPY_ROLES = ("PRODUCTION", "COMMITTED_SNAPSHOT")

#: A machine record of a FULL test run on origin/main: ``junit.xml`` written by pytest itself plus
#: ``meta.json`` {"commit": <40-hex>, "as_of": <ISO>}. Read through the existing three-outcome reader
#: ``scripts/ci_verdict.py`` (ADR-474) — never ADR prose, never a hand-typed count.
TEST_RECORD_DEFAULT = CODE_REPO / "data" / "ci" / "origin_main"
TEST_HEALTH_POINTER = "see ADR-613 (a pointer to where the measurement is discussed — not a measurement)"


def _ci_verdict_module():
    import importlib.util
    path = CODE_REPO / "scripts" / "ci_verdict.py"
    spec = importlib.util.spec_from_file_location("spa_ci_verdict_for_continuity", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _failed_names(junit: Path, limit: int = 20) -> List[str]:
    import xml.etree.ElementTree as ET
    names: List[str] = []
    for tc in ET.parse(junit).getroot().iter("testcase"):
        if any(ch.tag in ("failure", "error") for ch in tc):
            names.append(clean(f"{tc.get('classname') or ''}::{tc.get('name') or ''}", 200))
    return sorted(names)[:limit]


def test_health_section(record: Optional[Path]) -> Dict[str, Any]:
    """origin/main test health — three outcomes (inv. #17): MEASURED (N failed + names) ·
    MEASURED_ZERO · NOT_MEASURED (with the reason). Absence of the record is NOT «green»."""
    src = "runtime: machine record of a full origin/main run (junit.xml + meta.json, read by scripts/ci_verdict.py)"
    if record is None:
        return _section(f"not measured: no test record was given to this build — {TEST_HEALTH_POINTER}",
                        src, "NOT_MEASURED", None, None)
    rec = Path(record)
    junit, meta_p = rec / "junit.xml", rec / "meta.json"
    if not junit.is_file() or not meta_p.is_file():
        return _section(f"not measured: no machine record of a full origin/main test run at {rec.name}/ — "
                        f"{TEST_HEALTH_POINTER}", src, "NOT_MEASURED", None, None)
    try:
        meta = json.loads(meta_p.read_text(encoding="utf-8"))
        commit, as_of = meta.get("commit"), meta.get("as_of")
        if not (isinstance(commit, str) and re.fullmatch(r"[0-9a-f]{40}", commit)) or _stamp_or_none(as_of) is None:
            raise ValueError("meta.json lacks a 40-hex commit or an ISO as_of")
        v = _ci_verdict_module().read_verdict(junit)
    except Exception as exc:  # noqa: BLE001 — an unreadable record is NOT_MEASURED with its reason
        return _section(f"not measured: test record unreadable ({type(exc).__name__}: {clean(str(exc), 160)})",
                        src, "NOT_MEASURED", None, None)
    if not v.measured:
        return _section(f"not measured: {clean(v.reason, 300)}", src, "NOT_MEASURED", None,
                        dict(commit=commit))
    bad = (v.failures or 0) + (v.errors or 0)
    if bad == 0:
        return _section(f"0 failed of {v.tests} on origin {commit[:12]}", src, "MEASURED_ZERO", _iso(_stamp(as_of)),
                        dict(commit=commit, tests=v.tests, failed=0, names=[]))
    names = _failed_names(junit)
    return _section(f"{bad} failed of {v.tests} on origin {commit[:12]}: " + "; ".join(names[:5])
                    + (" …" if bad > 5 else ""), src, "MEASURED", _iso(_stamp(as_of)),
                    dict(commit=commit, tests=v.tests, failed=bad, names=names))


def _dirty_inputs(root: Path, paths: List[str]) -> Optional[List[str]]:
    """Inputs whose working-tree bytes differ from the root's HEAD (None = not a git root)."""
    out = _git(root, "status", "--porcelain", "--untracked-files=all")   # literal argv; filtered below
    if out is None:
        return None
    # `_git` strips the output, so the first line may have lost its leading status column: split instead
    changed = [ln.split(None, 1)[1].split(" -> ")[-1] for ln in out.splitlines() if ln.strip()]
    wanted = set(paths)
    return sorted(p for p in changed if p not in OUTPUT_PATHS
                  and (p in wanted or any(p.startswith(d + "/") for d in ADR_DIRS)))


def build(root: Path, generated_at: str, receipt: Optional[Path] = None, mission: Optional[Path] = None,
          copy_role: str = "PRODUCTION", test_record: Optional[Path] = None) -> Dict[str, Any]:
    if copy_role not in COPY_ROLES:
        raise ContinuityError(f"REFUSED: unknown copy role {copy_role!r}")
    gen_at = _stamp(generated_at)
    root = root.resolve()
    refs0 = (_git(root, "rev-parse", "HEAD"), origin_head(root))
    hashes, texts, aux = inventory(root)
    resolved = aux["resolved"]
    rec = load_receipt(receipt)
    truth, mmeta = load_mission(mission)
    runtime_age_h = None
    if mmeta.get("computed_at"):
        runtime_age_h = round((gen_at - _stamp(mmeta["computed_at"])).total_seconds() / 3600, 2)

    def st(aid: str) -> str:
        return resolved[aid]["status"] if aid in resolved else UNKNOWN
    rv = roadmap_view(texts["docs/ROADMAP.md"], st)
    latest = rv["latest"]
    latest_name = latest["name"] if latest and latest["accepted"] else UNKNOWN

    S: Dict[str, Dict[str, Any]] = {}
    act = rv["active"]
    cw = _get(truth, "studio.claude_work")
    done_names = [re.sub(r"[~*`]", "", b.split("—")[0]).strip() for _, b in _roadmap_items(texts["docs/ROADMAP.md"])
                  if b.startswith("~~")]
    announced = (cw or {}).get("epic") if cw and str(cw.get("state", "")).startswith("MEASURED") else None
    if announced and any(n and (n in announced or announced in n) for n in done_names):
        announced = None        # an announcement naming a DONE epic is a stale announcement, not current work
    S["active_epic"] = _section(
        (act["name"] if act else "no epic marked «in progress» in docs/ROADMAP.md")
        + (f" · Claude announced (as of {cw.get('as_of')}): {announced}" if announced else ""),
        "docs/ROADMAP.md «Order of the next epics» (+ runtime truth.studio.claude_work, DONE epics dropped)",
        "MEASURED" if act else UNKNOWN, None, act["name"] if act else None, "CANONICAL")
    S["latest_accepted_epic"] = _section(
        f"{latest['name']} ({latest['adr']}, {latest['adr_status']})" if latest else None,
        "docs/ROADMAP.md (struck item marked DONE with its ADR, ADR status resolved from canon)",
        "MEASURED" if latest and latest["accepted"] else UNKNOWN, None, latest_name, "CANONICAL")
    head, origin = _sha_or_unknown(refs0[0]), _sha_or_unknown(refs0[1])
    behind = head != UNKNOWN and origin != UNKNOWN and head != origin
    S["current_origin"] = _section(
        f"canonical root HEAD {head[:12]} · origin main on the server {origin[:12]}"
        + (" — the root is NOT at the origin head" if behind else ""),
        "git rev-parse HEAD in the canonical root + git ls-remote origin (asked at generation)",
        "MEASURED" if origin != UNKNOWN and head != UNKNOWN else UNKNOWN, _iso(gen_at), origin, "CANONICAL")
    S["production_code"] = _section(
        f"production code = origin {rec['production_release'][:12]} ({rec['reason']}, at {rec['verified_at']})"
        if rec["production_release"] != UNKNOWN else f"not proven: {rec['reason']}",
        "runtime: data/code_sync_status.json (code-sync scope only, not every service's live memory)",
        "MEASURED" if rec["production_release"] != UNKNOWN else UNKNOWN, rec["verified_at"], rec["production_release"])
    mc = _get(truth, "home.money_chip")
    usd = mc.get("usd") if mc else None
    S["real_capital"] = _section(
        f"real capital ${usd:,.0f} (policy baseline $0; owner subject №1)" if isinstance(usd, (int, float)) and
        mc.get("state") == "MEASURED" else (mc.get("unknown_ru") if mc else None),
        f"runtime: mission.json truth.home.money_chip (canon: {mc.get('canon') if mc else UNKNOWN})",
        "MEASURED" if mc and mc.get("state") == "MEASURED" else UNKNOWN, mc.get("as_of") if mc else None, usd)
    rd = _get(truth, "capital.readiness")
    ready = rd.get("ready") if rd else None
    S["live_execution"] = _section(
        ("NOT ENABLED — paper only; investment-engine readiness "
         f"{(rd.get('value') or {}).get('status')}, open go-live conditions {rd.get('conditions_open')}")
        if rd and rd.get("state") == "MEASURED" and ready is False else (
            "readiness reports READY — live execution still needs an explicit owner decision (ADR-556)"
            if ready is True else None),
        f"runtime: mission.json truth.capital.readiness (canon: {rd.get('canon') if rd else UNKNOWN}); policy ADR-556",
        "MEASURED" if rd and rd.get("state") == "MEASURED" and ready is not None else UNKNOWN,
        rd.get("as_of") if rd else None,
        None if ready is None else ("LIVE_DISABLED" if not ready else "READY_NOT_APPROVED"))
    strip = {c.get("key"): c for c in ((_get(truth, "home") or {}).get("strip") or []) if isinstance(c, dict)}
    y = strip.get("yield")
    S["capital_summary"] = _section(y.get("display_ru") if y and y.get("state") == "MEASURED" else None,
                                    f"runtime: mission.json truth.home.strip[yield] (canon: {y.get('canon') if y else UNKNOWN})",
                                    "MEASURED" if y and y.get("state") == "MEASURED" else UNKNOWN, y.get("as_of") if y else None)
    tl = _get(truth, "capital.trading_lab")
    if tl and tl.get("state") == "MEASURED":
        fr = tl.get("freshness") or {}
        S["trading_lab"] = _section(
            f"candidates researched {tl.get('candidates')} · in forward paper {tl.get('forward')} · champions "
            f"{tl.get('champions')} · evidence chain {'intact' if tl.get('chain_ok') else 'NOT intact'} · data age "
            f"{fr.get('age_min')} min", f"runtime: mission.json truth.capital.trading_lab (canon: {tl.get('canon')})",
            "MEASURED", tl.get("as_of"), dict(candidates=tl.get("candidates"), forward=tl.get("forward"),
                                              champions=tl.get("champions"), chain_ok=tl.get("chain_ok")))
    else:
        S["trading_lab"] = _cell_section(truth, "capital.trading_lab")
    S["btc"] = _cell_section(truth, "capital.btc")
    S["btc"]["display"] = clean(f"research signal only, not an order: {S['btc']['display']}", 600) \
        if S["btc"]["status"].startswith("MEASURED") else S["btc"]["display"]
    profs = _profile_rows(truth, resolved)
    S["defi_paper"] = _section(
        " · ".join(f"{p['profile']}: {p['value'] if p['value'] != UNKNOWN else 'rate not reportable'}"
                   f" ({p['runtime_state']}, evidenced {p['evidenced_days']} d, accumulating {p['accumulating_days']} d)"
                   for p in profs[:3]),
        "runtime: mission.json truth.product.profiles.* (canon per row in «Public profile mapping»)",
        "MEASURED" if any(p["runtime_state"] == "MEASURED" for p in profs[:3]) else UNKNOWN,
        (_get(truth, "product.profiles.conservative") or {}).get("as_of"))
    orc = _get(truth, "capital.oracle")
    S["oracle"] = _section(
        f"stance {orc.get('stance')} · {json.dumps(orc.get('value'), ensure_ascii=False, sort_keys=True)} · advisory/paper, "
        "no execution authority (ADR-554)" if orc and orc.get("state") == "MEASURED" else (orc or {}).get("unknown_ru"),
        f"runtime: mission.json truth.capital.oracle (canon: {(orc or {}).get('canon', UNKNOWN)})",
        "MEASURED" if orc and orc.get("state") == "MEASURED" else UNKNOWN, (orc or {}).get("as_of"),
        (orc or {}).get("stance"))
    sh = _get(truth, "capital.sherlock")
    if sh and sh.get("state") == "MEASURED":
        v = sh.get("value") if isinstance(sh.get("value"), dict) else {}
        total = sh.get("total")
        S["sherlock"] = _section(
            f"usable curated facts {sh.get('usable')} · total facts {total if isinstance(total, int) and not isinstance(total, bool) else 'не измерено'}"
            f" · evidence-ready {v.get('evidence_ready', UNKNOWN)} · paper-active {v.get('paper_active', UNKNOWN)} · "
            f"CIO-eligible {v.get('cio_eligible', UNKNOWN)} · no capital authority (ADR-564)",
            f"runtime: mission.json truth.capital.sherlock (canon: {sh.get('canon')})", "MEASURED", sh.get("as_of"))
    else:
        S["sherlock"] = _cell_section(truth, "capital.sherlock")
    fl, tk, shl = _get(truth, "studio.fleet"), _get(truth, "studio.tasks"), _get(truth, "studio.self_heal")
    S["studio_os"] = _section(
        " · ".join(x for x in (fl and fl.get("display_ru"), tk and tk.get("display_ru"),
                               shl and f"self-heal: {shl.get('display_ru')}") if x) or None,
        "runtime: mission.json truth.studio.{fleet,tasks,self_heal}",
        "MEASURED" if fl and fl.get("state") == "MEASURED" else UNKNOWN, (fl or {}).get("as_of"))
    S["director_os"] = _section(
        f"Mission Control bundle {mmeta.get('bundle') or UNKNOWN}, Company Truth computed {mmeta.get('computed_at')}"
        f" (age {runtime_age_h} h at generation); read model only (ADR-592)" if truth else f"not read: {mmeta['reason']}",
        "runtime: published Mission Control bundle (current.json → mission.json)", "MEASURED" if truth else UNKNOWN,
        mmeta.get("computed_at"), mmeta.get("bundle"))
    S["memory"] = _cell_section(truth, "studio.memory",
                                display=(lambda c: f"index lag {c.get('lag')} ADRs · newest indexed "
                                         f"{(c.get('value') or {}).get('newest_indexed')} · truth overrides "
                                         f"{(c.get('value') or {}).get('truth_overrides')}" if c else None)(
                                    _get(truth, "studio.memory")))
    pr, wh = _get(truth, "product.public_release"), _get(truth, "product.website_health")
    gate_note = "publication candidate is an Owner Gate (see owner_gates)"
    S["product_publication"] = _section(
        (f"published {(pr.get('value') or {}).get('published_at')} (measured {(pr.get('value') or {}).get('measured_at')}),"
         f" next {(pr.get('value') or {}).get('next_publication')} · site health {(wh or {}).get('display_ru')} · {gate_note}")
        if pr and pr.get("state") == "MEASURED" else None,
        "runtime: mission.json truth.product.{public_release,website_health}",
        "MEASURED" if pr and pr.get("state") == "MEASURED" else UNKNOWN, (wh or {}).get("as_of"))
    pb = _get(truth, "studio.problems")
    S["active_problems"] = _section(
        (pb.get("display_ru") + " · open: " + ", ".join(map(str, (pb.get("value") or {}).get("open") or [])))
        if pb and pb.get("state", "").startswith("MEASURED") else (pb or {}).get("unknown_ru"),
        f"runtime: mission.json truth.studio.problems (canon: {(pb or {}).get('canon', UNKNOWN)})",
        pb.get("state") if pb and pb.get("state", "").startswith("MEASURED") else UNKNOWN, (pb or {}).get("as_of"),
        (pb or {}).get("value"))
    dc = _get(truth, "decisions") or {}
    counts = dc.get("counts") if dc.get("state") == "MEASURED" else None
    titles = [clean(g.get("title_ru"), 140) for g in ((dc.get("groups") or {}).get("owner") or [])[:8]
              if isinstance(g, dict)] if counts else []
    epic_gates = [g for g in ((latest or {}).get("owner_gates"), (act or {}).get("owner_gates")) if g]
    S["owner_gates"] = _section(
        ("epic gates: " + " | ".join(epic_gates) if epic_gates else "epic gates: none recorded in docs/ROADMAP.md")
        + (f" · owner queue: {json.dumps(counts, sort_keys=True)}" if counts else " · owner queue: не измерено")
        + (" · owner cards: " + "; ".join(titles) if titles else ""),
        "docs/ROADMAP.md «Owner gates:» of the latest/active epic + runtime truth.decisions (one owner queue, ADR-580 C5)",
        "MEASURED" if counts is not None else "PARTIAL", None, dict(epic=epic_gates, queue=counts), "CANONICAL")
    debt = (latest or {}).get("remaining_debt")
    S["technical_debt"] = _section(debt, "docs/ROADMAP.md «Remaining debt:» of the latest accepted epic",
                                   "MEASURED" if debt else UNKNOWN, None, None, "CANONICAL")
    nsa = (act or {}).get("next_safe_action")
    S["next_safe_action"] = _section(nsa, "docs/ROADMAP.md «Next safe action:» of the active epic",
                                     "MEASURED" if nsa else UNKNOWN, None, None, "CANONICAL")
    S["test_health"] = test_health_section(test_record)
    S["last_verification"] = _section(
        f"generated {_iso(gen_at)} · code-sync receipt {rec['verified_at']} · Company Truth {mmeta.get('computed_at')}",
        "this generator (freshness: `python -m spa_core.studio_os.memory continuity check`)", "MEASURED",
        _iso(gen_at), None, "DERIVED")

    for k, sec in S.items():
        # review P1-5: a runtime value without an observation time is not a measurement we can age
        if sec["authority"] == "RUNTIME" and sec["status"].startswith("MEASURED") and not sec["as_of"]:
            sec["status"] = "PARTIAL"
            sec["display"] = clean(f"{sec['display']} (the source records no observation time)", 600)
    dirty = _dirty_inputs(root, sorted(p for p in hashes if not p.startswith("derived:")))
    if copy_role == "COMMITTED_SNAPSHOT" and (dirty is None or dirty):
        # off the machine nobody can prove which bytes an uncommitted input had — commit the sources
        # first, then build the snapshot from a clean tree (ADR-610 delivery order)
        raise ContinuityError("REFUSED: a COMMITTED_SNAPSHOT needs a clean canonical root; uncommitted "
                              f"inputs: {dirty if dirty is not None else 'NOT MEASURED'}")
    behind = refs0[1] is None or refs0[0] != refs0[1]
    partial = [k for k, x in S.items() if x["status"] in (UNKNOWN, "PARTIAL")]
    verdict_at_gen = "CONTEXT_PARTIAL" if (partial or behind or dirty or dirty is None or truth is None) \
        else "CONTEXT_FRESH"
    inputs_digest = _digest(json.dumps(hashes, sort_keys=True).encode())
    gen_version = f"{VERSION}+{_digest(Path(__file__).read_bytes())[:12]}"
    header = dict(
        context_version=VERSION, generated_at=_iso(gen_at), repo_commit=head, origin_commit=origin,
        production_release=rec["production_release"], latest_accepted_epic=latest_name,
        source_snapshot_ids=sorted(x for x in (f"inputs:{inputs_digest}",
                                               f"receipt:{rec['sha256']}" if rec["sha256"] else None,
                                               f"mission:{mmeta['sha256']}" if mmeta.get("sha256") else None) if x),
        generator_version=gen_version, authority="DERIVED", runtime_truth_computed_at=mmeta.get("computed_at"),
        production_release_verified_at=rec["verified_at"], copy_role=copy_role,
        verdict_at_generation=verdict_at_gen, root_dirty_inputs=dirty if dirty is not None else [UNKNOWN],
        adr_max_considered=adr_max_considered(_adr_listing(root)),
        adr_listing_sha256=hashes["derived:adr_registry_listing"])
    state = dict(header=header, inputs=dict(sorted(hashes.items())),
                 runtime=dict(receipt=dict(reason=rec["reason"], sha256=rec["sha256"]),
                              mission=dict(bundle=mmeta.get("bundle"), computed_at=mmeta.get("computed_at"),
                                           sha256=mmeta.get("sha256"), reason=mmeta.get("reason"),
                                           age_h_at_generation=runtime_age_h)),
                 sections={k: S[k] for k in SECTION_ORDER},
                 decisions=_decision_rows(resolved), intents=_intent_rows(aux["intents"], resolved), profiles=profs)
    validate(state, json.loads(texts[SCHEMA_FILE]))
    # sources must not move under us: a mixed snapshot is refused, not published as "fresh"
    if inventory(root)[0] != hashes or _git(root, "rev-parse", "HEAD") != refs0[0]:
        raise ContinuityError("REFUSED: canonical sources changed during generation (CONTEXT_STALE)")
    return state


# ── schema (a strict subset of JSON Schema, enough for the declared contract) ─────────────────

def _check(node: Any, schema: Dict[str, Any], where: str) -> None:
    t = schema.get("type")
    types = t if isinstance(t, list) else ([t] if t else [])
    py = {"object": dict, "array": list, "string": str, "integer": int, "number": (int, float), "boolean": bool,
          "null": type(None)}
    if types and not any(isinstance(node, py[x]) and not (x in ("integer", "number") and isinstance(node, bool))
                         for x in types):
        raise ValueError(f"{where}: expected {types}, got {type(node).__name__}")
    if "enum" in schema and node not in schema["enum"]:
        raise ValueError(f"{where}: {node!r} not in {schema['enum']}")
    if "pattern" in schema and isinstance(node, str) and not re.search(schema["pattern"], node):
        raise ValueError(f"{where}: {node!r} does not match {schema['pattern']}")
    if isinstance(node, dict):
        for k in schema.get("required", []):
            if k not in node:
                raise ValueError(f"{where}: missing required {k!r}")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = sorted(set(node) - set(props))
            if extra:
                raise ValueError(f"{where}: unexpected {extra}")
        for k, v in node.items():
            if k in props:
                _check(v, props[k], f"{where}.{k}")
            elif isinstance(schema.get("additionalProperties"), dict):
                _check(v, schema["additionalProperties"], f"{where}.{k}")
    if isinstance(node, list):
        if len(node) < schema.get("minItems", 0):
            raise ValueError(f"{where}: fewer than {schema['minItems']} items")
        if "items" in schema:
            for i, v in enumerate(node):
                _check(v, schema["items"], f"{where}[{i}]")


def validate(state: Dict[str, Any], schema: Dict[str, Any]) -> None:
    try:
        _check(state, schema, "state")
    except ValueError as exc:
        raise ContinuityError(f"REFUSED: schema violation — {exc}")
    secs = state["sections"]
    if sorted(secs) != sorted(SECTION_ORDER):
        raise ContinuityError("REFUSED: sections differ from the declared set")
    for k, s in secs.items():
        if s["status"] != UNKNOWN and (not s["source"] or s["source"] == UNKNOWN):
            raise ContinuityError(f"REFUSED: section {k} carries a value without provenance")
        if s["authority"] == "RUNTIME" and s["status"].startswith("MEASURED") and not s["as_of"]:
            raise ContinuityError(f"REFUSED: runtime section {k} is MEASURED without an observation time")
    ids = [i["intent_id"] for i in state["intents"]]
    if len(ids) != len(set(ids)):
        raise ContinuityError("REFUSED: duplicate intent id")
    for p in state["profiles"]:
        if p["metric_type"] not in RETURN_KIND.values():
            raise ContinuityError(f"REFUSED: unknown metric type {p['metric_type']!r}")


# ── render ────────────────────────────────────────────────────────────────────────────────────

_TITLES = dict(active_epic="Active epic / current wave", latest_accepted_epic="Latest accepted epic",
               current_origin="Current origin", production_code="Production code identity",
               real_capital="Real capital", live_execution="Live execution", capital_summary="Capital summary",
               trading_lab="Trading Lab", btc="BTC (directional research)", defi_paper="DeFi paper",
               oracle="Oracle (CIO)", sherlock="Sherlock (Head of Research)", studio_os="Studio OS",
               director_os="Director OS / Mission Control", memory="Memory", product_publication="Product / publication",
               active_problems="Active problems", test_health="origin/main test health", owner_gates="Pending Owner Gates", technical_debt="Known technical debt",
               next_safe_action="Next safe architectural action", last_verification="Last verification evidence")


def render(state: Dict[str, Any]) -> Dict[str, str]:
    h = state["header"]
    cs = ["---", json.dumps(h, ensure_ascii=False, sort_keys=True, indent=1), "---",
          "# CURRENT_STATE — generated read model (authority: DERIVED, never canonical)", "",
          "> Generated by `spa_core/studio_os/memory/continuity.py` (ADR-610). Do not edit: a hand edit is detected "
          "as tampering. Before deciding architecture run `python -m spa_core.studio_os.memory continuity check`; "
          "without a machine, judge freshness by the four-step no-machine rule in `docs/continuity/BOOTSTRAP.md` "
          "(«Freshness gate»; ADRs above `adr_max_considered` must be read). UNKNOWN is an answer, not a gap to "
          "fill.", "",
          f"**Copy:** {h['copy_role']} · **verdict at generation:** {h['verdict_at_generation']}"
          + (f" · inputs not committed at generation: {', '.join(h['root_dirty_inputs'])}"
             if h["root_dirty_inputs"] else "")
          + (" — on the Mac the authoritative copy is `data/continuity/` (rebuilt every 30 min); this committed "
             "snapshot is for readers off the machine." if h["copy_role"] == "COMMITTED_SNAPSHOT" else ""), ""]
    for k in SECTION_ORDER:
        s = state["sections"][k]
        cs += [f"## {_TITLES[k]}", f"- **status:** {s['status']} · **as of:** {s['as_of'] or '—'} · "
               f"**authority:** {s['authority']}", f"- **source:** {s['source']}", f"- {s['display']}", ""]
    cs += ["## Public profile mapping (public ↔ internal ↔ decision ↔ track ↔ metric type)", "",
           "| Public profile | Alt name | Internal book | Track source | Decision | Effective | Metric type | Runtime state | Value | Reportable |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for p in state["profiles"]:
        cs.append(f"| {p['profile']} | {p['alt_name']} | {p['internal_book']} | `{p['track_source']}` | {p['decision']} | "
                  f"{p['effective']} | {p['metric_type']} | {p['runtime_state']} | {p['value']} | {p['reportable']} |")
    cs += ["", "Metric types are never collapsed into a generic «APY» (ADR-580 C2): TARGET_RETURN · OBSERVED_RETURN · "
           "REALIZED_PAPER_RETURN · MODELLED_RETURN · BACKTEST_RETURN. Changing the public↔internal mapping is owner subject №2.",
           "", "## Intents (live status of OWNER_INTENT_LEDGER.md entries)", "",
           "| Intent | Decisions | Decision status | Flags | Curated status |", "|---|---|---|---|---|"]
    for i in state["intents"]:
        cs.append(f"| {i['intent_id']} {i['title']} | {', '.join(i['decisions']) or '—'} | {i['decision_status']} | "
                  f"{'; '.join(i['flags']) or '—'} | {i['curated_status']} |")
    cs += ["", "## Freshness inputs", "", f"{len(state['inputs'])} canonical inputs hashed (`state.json` → `inputs`); "
           f"runtime: receipt ({state['runtime']['receipt']['reason']}), Mission Control bundle "
           f"({state['runtime']['mission']['reason']}).", ""]
    idx = ["# ARCHITECT_DECISION_INDEX — generated index over canonical decisions (not a decision store)", "",
           f"> Generated {h['generated_at']} by ADR-610's generator from `docs/decisions/`. The class is declared per topic "
           "and OVERRIDDEN by the canon: a cited ADR that is superseded, not accepted, missing or ambiguous cannot "
           "stay CURRENT. Read the cited ADR in full before acting; this table is navigation.", ""]
    for cls in ("CURRENT", "EXPERIMENTAL", "SUPERSEDED", "REJECTED", UNKNOWN):
        rows = [r for r in state["decisions"] if r["cls"] == cls]
        if not rows:
            continue
        idx += [f"## {cls}", "", "| Topic | Decision | Cited ADR (status · effective) | Note |", "|---|---|---|---|"]
        for r in rows:
            refs = "<br>".join(f"[{x['adr']}](../../{x['path']}) {x['status']} · {x['effective']}"
                               + (f" · superseded by {x['superseded_by']}" if x["superseded_by"] else "")
                               + (f" · AMBIGUOUS NUMBER (also {', '.join(x['number_collision'])}; "
                                  "docs/decisions is canonical)" if x.get("number_collision") else "")
                               if x["path"] != UNKNOWN else f"{x['adr']} — NOT FOUND/AMBIGUOUS" for x in r["refs"])
            extra = f" ({r['disposition']})" if r["disposition"] else ""
            why = "" if r["basis"] == "declared" else f" **[{r['basis']}; declared {r['declared']}]**"
            idx.append(f"| {r['topic']} | {r['title']}{extra}{why} | {refs} | {r['note'] or '—'} |")
        idx.append("")
    return {"CURRENT_STATE.md": "\n".join(cs) + "\n", "ARCHITECT_DECISION_INDEX.md": "\n".join(idx) + "\n",
            "state.json": json.dumps(state, ensure_ascii=False, sort_keys=True, indent=1) + "\n"}


def _mirror_root() -> Optional[Path]:
    try:
        from spa_core.studio_os.memory.sources import DEFAULT_ROOTS
        return DEFAULT_ROOTS["spa"].resolve()
    except Exception:  # pragma: no cover
        return None


def write(state: Dict[str, Any], out: Path, root: Optional[Path] = None) -> None:
    out = out.resolve()
    mirror = _mirror_root()
    if mirror is not None and out.is_relative_to(mirror):
        raise ContinuityError("REFUSED: never write into the read-only origin mirror")
    if root is not None and out.is_relative_to(root.resolve()) and out != (root.resolve() / CONTRACT_DIR):
        raise ContinuityError(f"REFUSED: inside the canonical root the only output place is {CONTRACT_DIR}/")
    if root is not None and out == (root.resolve() / CONTRACT_DIR) and \
            state["header"].get("copy_role") != "COMMITTED_SNAPSHOT":
        raise ContinuityError("REFUSED: the committed copy must be built with copy_role=COMMITTED_SNAPSHOT")
    out.mkdir(parents=True, exist_ok=True)
    rendered = render(state)
    for name in OUTPUTS:                     # state.json last: readers verify the Markdown against it
        p = out / name
        if p.is_symlink():
            raise ContinuityError(f"REFUSED: output is a symlink: {name}")
        fd, tmp = tempfile.mkstemp(dir=out, prefix=".continuity-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(rendered[name])
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, p)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)


# ── freshness ─────────────────────────────────────────────────────────────────────────────────

def _material(path: str, hashes: Dict[str, str]) -> bool:
    """A path whose change can alter the architecture context: a hashed input, or ANY ADR in either
    registry (added, changed or removed — the index may lack it). Review P1-2."""
    return path in hashes or bool(re.match(r"^docs/(decisions|adr)/ADR-[^/]+\.md$", path))


def check(root: Path, out: Path, now: str, receipt: Optional[Path] = None,
          mission: Optional[Path] = None) -> Dict[str, Any]:
    reasons: List[str] = []
    notes: List[str] = []
    root = root.resolve()
    try:
        state = json.loads((out / "state.json").read_text(encoding="utf-8"))
        schema = json.loads((root / SCHEMA_FILE).read_text(encoding="utf-8"))
        validate(state, schema)
    except (OSError, ValueError, ContinuityError) as exc:
        return dict(verdict="CONTEXT_STALE", reasons=[f"recorded context unreadable or malformed: {exc}"], notes=[],
                    judged=dict(file=str(out / "state.json"), copy_role=None, verdict_at_generation=None))
    h = state["header"]
    try:
        rendered = render(state)
        for name in ("CURRENT_STATE.md", "ARCHITECT_DECISION_INDEX.md"):
            if (out / name).read_text(encoding="utf-8") != rendered[name]:
                reasons.append(f"{name} does not match state.json (edited by hand or partially written)")
    except OSError as exc:
        reasons.append(f"generated output missing: {exc}")
    try:
        cur_hashes, cur_texts, cur_aux = inventory(root)
    except ContinuityError as exc:
        return dict(verdict="CONTEXT_STALE", reasons=reasons + [str(exc)], notes=notes,
                    judged=dict(file=str(out / "state.json"), copy_role=h.get("copy_role"),
                                verdict_at_generation=h.get("verdict_at_generation")))
    rec_hashes = state["inputs"]
    for k in sorted(set(rec_hashes) | set(cur_hashes)):
        if rec_hashes.get(k) != cur_hashes.get(k):
            what = "appeared" if k not in rec_hashes else ("vanished" if k not in cur_hashes else "changed")
            reasons.append(f"canonical input {what}: {k}")
    if h["generator_version"] != f"{VERSION}+{_digest(Path(__file__).read_bytes())[:12]}":
        reasons.append("the running generator differs from the one that built this context")
    head = _sha_or_unknown(_git(root, "rev-parse", "HEAD"))
    origin = _sha_or_unknown(origin_head(root))
    partial_extra: List[str] = []
    if h["repo_commit"] != head:
        notes.append(f"repo_commit moved {h['repo_commit'][:12]} → {head[:12]}; canonical inputs compared byte-for-byte above")
    if origin == UNKNOWN:
        notes.append("origin head not asked of the server (no network or no remote) — origin freshness NOT MEASURED")
    elif origin != head:
        # the canonical root itself lags the server: its inputs may be old although they hash the same
        if _git(root, "cat-file", "-e", f"{origin}^{{commit}}") is None:
            reasons.append(f"canonical root {head[:12]} is behind origin {origin[:12]} and that commit is not "
                           "present locally — update the root, then rebuild")
        elif _git(root, "merge-base", "--is-ancestor", origin, head) is not None:
            # the root is AHEAD of the server (unpublished commits): a candidate context, not a delivered one
            partial_extra.append(f"canonical root {head[:12]} is ahead of origin {origin[:12]} — unpublished "
                                 "commits; this context describes a candidate, not the delivered state")
        else:
            # only what the SERVER side changed since the common ancestor — never our own unpublished edits
            base = _git(root, "merge-base", head, origin) or head
            changed = _git(root, "diff", "--name-only", base, origin) or ""
            touched = sorted(p for p in changed.splitlines() if _material(p, cur_hashes))
            if touched:
                reasons.append(f"origin moved ahead of the canonical root with input change(s): {touched[:3]}")
            else:
                notes.append(f"origin {origin[:12]} is ahead of the root {head[:12]} without canonical-input changes")
    elif h["origin_commit"] != origin:
        notes.append(f"origin_commit moved {h['origin_commit'][:12]} → {origin[:12]}; canonical inputs compared byte-for-byte above")
    rc = load_receipt(receipt)
    rec_prod, cur_prod = h["production_release"], rc["production_release"]
    if rec_prod != UNKNOWN and cur_prod == UNKNOWN:
        reasons.append(f"production identity can no longer be verified ({rc['reason']})")
    elif rec_prod != cur_prod and cur_prod != UNKNOWN:
        changed = _git(root, "diff", "--name-only", f"{rec_prod}..{cur_prod}") if rec_prod != UNKNOWN else None
        if changed is None:
            reasons.append(f"production release moved {rec_prod[:12]} → {cur_prod[:12]} and the change cannot be "
                           "proven immaterial (commit unknown to this root)")
        else:
            material = [p for p in changed.splitlines() if p and p not in OUTPUT_PATHS]
            if material:
                reasons.append(f"production release moved {rec_prod[:12]} → {cur_prod[:12]} ({len(material)} changed "
                               f"file(s), e.g. {material[0]})")
            else:
                notes.append(f"production release moved {rec_prod[:12]} → {cur_prod[:12]} by generated outputs only")
    truth, mmeta = load_mission(mission)
    computed = h.get("runtime_truth_computed_at")
    if computed:
        age = (_stamp(now) - _stamp(computed)).total_seconds() / 3600
        if age < -0.1:
            reasons.append("runtime truth is dated in the future relative to the check time")
        elif age > RUNTIME_MAX_AGE_H:
            reasons.append(f"runtime facts are {age:.1f} h old (> {RUNTIME_MAX_AGE_H:.0f} h)")
    if mmeta.get("computed_at") and mmeta.get("computed_at") != computed:
        notes.append(f"Mission Control truth moved {computed} → {mmeta['computed_at']} (numbers in CURRENT_STATE are as of {computed})")
    if (_stamp(now) - _stamp(h["generated_at"])).total_seconds() < -60:
        reasons.append("generated_at is in the future relative to the check time")
    rv = roadmap_view(cur_texts["docs/ROADMAP.md"], lambda a: (cur_aux["resolved"].get(a) or {}).get("status", UNKNOWN))
    latest_now = rv["latest"]["name"] if rv["latest"] and rv["latest"]["accepted"] else UNKNOWN
    if latest_now != h["latest_accepted_epic"]:
        reasons.append(f"latest accepted epic changed: {h['latest_accepted_epic']} → {latest_now}")
    judged = dict(file=str(out / "state.json"), copy_role=h.get("copy_role"),
                  verdict_at_generation=h.get("verdict_at_generation"))
    if reasons:
        return dict(verdict="CONTEXT_STALE", reasons=reasons, notes=notes, judged=judged)
    partial: List[str] = list(partial_extra)
    unknown = [k for k, s in state["sections"].items() if s["status"] in (UNKNOWN, "PARTIAL")]
    if unknown:
        partial.append(f"UNKNOWN/PARTIAL sections: {unknown}")
    if computed is None:
        partial.append("runtime truth was not available at generation")
    if origin == UNKNOWN:
        # review P1-3: without the server's answer origin freshness is NOT MEASURED — never FRESH
        partial.append("origin head not measured at check time")
    if partial:
        return dict(verdict="CONTEXT_PARTIAL", reasons=partial, notes=notes, judged=judged)
    return dict(verdict="CONTEXT_FRESH", reasons=[], notes=notes, judged=judged)


# ── CLI ───────────────────────────────────────────────────────────────────────────────────────

def _defaults() -> Dict[str, Path]:
    from spa_core.studio_os.memory.sources import roots
    return dict(root=roots()["spa"], out=CODE_REPO / "data" / "continuity",
                receipt=CODE_REPO / "data" / "code_sync_status.json",
                mission=Path.home() / "studio-os-serve" / "mission" / "current.json")


def main(argv: Optional[List[str]] = None) -> int:
    d = _defaults()
    ap = argparse.ArgumentParser(prog="spa_core.studio_os.memory continuity")
    ap.add_argument("command", choices=("build", "check"))
    ap.add_argument("--root", type=Path, default=d["root"], help="canonical origin checkout (default: the mirror)")
    ap.add_argument("--out", type=Path, default=d["out"], help="output directory (default: data/continuity)")
    ap.add_argument("--at", default=None, help="UTC ISO time (default: now)")
    ap.add_argument("--receipt", type=Path, default=d["receipt"])
    ap.add_argument("--mission", type=Path, default=d["mission"])
    ap.add_argument("--test-record", type=Path, default=TEST_RECORD_DEFAULT,
                    help="machine record of a full origin/main run (junit.xml + meta.json)")
    a = ap.parse_args(argv)
    at = a.at or _iso(datetime.now(timezone.utc))
    try:
        if a.command == "build":
            committed = a.out.resolve() == (a.root.resolve() / CONTRACT_DIR)
            st = build(a.root, at, a.receipt, a.mission, "COMMITTED_SNAPSHOT" if committed else "PRODUCTION",
                       a.test_record)
            write(st, a.out, a.root)
            print(json.dumps({"built": True, "out": a.out.name, "header": st["header"]}, ensure_ascii=False, indent=1))
            return 0
        res = check(a.root, a.out, at, a.receipt, a.mission)
    except ContinuityError as exc:
        print(str(exc))
        return 2
    print(res["verdict"])
    j = res.get("judged") or {}
    print(f"  judged: {j.get('file')} (copy role {j.get('copy_role')}, verdict at generation "
          f"{j.get('verdict_at_generation')})")
    for r in res["reasons"]:
        print(f"  reason: {r}")
    for n in res["notes"]:
        print(f"  note: {n}")
    return {"CONTEXT_FRESH": 0, "CONTEXT_PARTIAL": 1}.get(res["verdict"], 2)


if __name__ == "__main__":
    sys.exit(main())
