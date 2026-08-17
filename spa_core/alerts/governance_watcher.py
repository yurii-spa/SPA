"""
Governance Watcher — FEAT-MON-002 (Sprint v3.18).

Monitors active governance proposals for the protocols that have a governance
source **configured below** (``SNAPSHOT_SPACES`` / ``TALLY_GOVERNORS``).

Watchlist = OUR protocols (ADR-070 п.14, owner decision 2026-08-07)
-------------------------------------------------------------------
The configured set used to contain six protocols we do not and cannot invest in
(``balancer``, ``curve``, ``lido``, ``maker``, ``uniswap-v3``, ``yearn``) while
the protocols we actually hold had no source at all: measured coverage was
**2 of 36** whitelisted protocols, and the held set was almost entirely
unchecked.  Every 30 minutes the watcher then reported eight healthy spaces —
a true statement about strangers.  The strangers are gone by name.

Protocols the owner named to ADD (``pendle``, ``maple``, ``morpho*``) are listed
in :data:`GOVERNANCE_SOURCE_UNCONFIRMED` instead of being wired in with a guessed
Snapshot slug.  A guessed slug is a fake source: it either 404s every scan (noise
that gets ignored) or silently resolves to a stranger's space and is published as
OUR coverage.  So the gap is **named with a verbatim reason and a candidate to
verify**, never filled by invention (invariant #2, `.claude/rules/adapters.md`
"никаких fake-fallback'ов").

.. warning::

   The configured set is **not** the SPA whitelist.  This docstring
   used to claim "monitors ... for SPA whitelist protocols", which was false:
   the configured spaces and ``ADAPTER_REGISTRY`` overlap only partly, so a
   whitelisted protocol can have **no governance source at all** and this
   module will still report a clean scan (``snapshot_spaces_ok=N``,
   ``snapshot_spaces_failed=0``, ``last_error=null``).

   Coverage is therefore accounted for explicitly and published in the output
   under ``coverage`` — see :func:`coverage_report`.  A protocol with no
   source is reported as **unchecked**, never as "no active proposals".
   Coverage is reported over two sets: the investable whitelist
   (``ADAPTER_REGISTRY``) and the protocols we are **holding right now**
   (``data/paper_trading_status.json`` → ``current_positions``).  An unchecked
   HELD protocol is the expensive kind of gap and is named separately.
   When coverage itself cannot be measured (registry unreadable), the report
   says so instead of claiming full coverage (fail-CLOSED, invariant #2).

Data sources:
  * **Snapshot** (free GraphQL API) — most DeFi governance proposals
  * **Tally** (free REST API) — on-chain governors (Compound, Uniswap, etc.)

Proposal categories
--------------------
* ``parameter_change``  — risk/interest-model parameters
* ``treasury``          — fund/grant disbursements
* ``upgrade``           — contract upgrades / proxy migrations
* ``emergency``         — emergency / pause actions
* ``risk_param``        — LTV, liquidation threshold, borrow-cap changes
* ``general``           — other proposals (low risk)
* ``unknown``           — unclassifiable

Severity
---------
* ``HIGH``   — upgrade / emergency / risk_param on active position
* ``MEDIUM`` — parameter_change / treasury on active position
* ``LOW``    — general proposals or non-active-position protocols

Design constraints
-------------------
* **Stdlib only** — urllib, json, dataclasses, datetime.  No new deps.
* **LLM forbidden** — keyword-matching classifier (deterministic).
* **Never raises** — scan_all() / export() catch all exceptions.
* **Offline-tolerant** — degrades to bootstrap seed data.

Output schema (``data/governance_proposals.json``)
----------------------------------------------------

::

    {
      "generated_at":  "<ISO-8601 UTC>",
      "watcher_version": "1.0",
      "sources": ["snapshot", "tally"],
      "fallback_used": false,
      "proposals": [
        {
          "id":           "snapshot:QmXyz123",
          "protocol":     "aave-v3",
          "title":        "Risk Parameter Update: USDC LTV to 88%",
          "category":     "risk_param",
          "severity":     "HIGH",
          "state":        "active",
          "source":       "snapshot",
          "start_at":     "2026-05-25T00:00:00Z",
          "end_at":       "2026-05-28T00:00:00Z",
          "url":          "https://snapshot.org/#/aave.eth/proposal/0x...",
          "votes_for":    1234567,
          "votes_against": 89012,
          "quorum_met":   true,
          "detected_at":  "2026-05-28T00:00:00Z"
        },
        ...
      ],
      "summary": {
        "total_proposals":    8,
        "by_category":        {"risk_param": 2, "upgrade": 1, ...},
        "by_severity":        {"HIGH": 3, "MEDIUM": 3, "LOW": 2},
        "by_protocol":        {"aave-v3": 2, ...},
        "high_severity_count": 3
      }
    }

CLI
---
::

    python -m spa_core.alerts.governance_watcher              # write file
    python -m spa_core.alerts.governance_watcher --offline    # bootstrap only
    python -m spa_core.alerts.governance_watcher --json       # print JSON
"""

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, Tuple

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[2] / "data" / "governance_proposals.json"
_REQUEST_TIMEOUT = 15  # seconds (was 8 — Snapshot can be slow under load)
_MAX_RETRIES = 3       # retry attempts per HTTP call
_BACKOFF_BASE = 2      # exponential backoff base (sleep = base ** attempt)

# Tally moved to an authenticated API (Api-Key header required).  Without a
# key Tally is skipped gracefully and only Snapshot is used.  Set via env.
TALLY_API_KEY = os.environ.get("TALLY_API_KEY", "").strip()

# Snapshot space slugs — ONLY for protocols in our own investable registry
# (ADR-070 п.14).  Key spelling is folded onto the registry by
# `_normalise_protocol_key`, so "aave-v3" and "aave_v3" are the same protocol.
SNAPSHOT_SPACES: dict[str, str] = {
    "aave-v3":      "aave.eth",
    "compound-v3":  "comp-vote.eth",
}

# Protocols removed from the watchlist by name, owner decision 2026-08-07
# (ADR-070 п.14): watched, answered every scan, and not investable for us.
# Kept as data — a test asserts they never creep back in, which a deleted
# comment could not do.
REMOVED_NOT_INVESTABLE: tuple[str, ...] = (
    "balancer",
    "curve",
    "lido",
    "maker",
    "uniswap-v3",
    "yearn",
)

# Protocols we HOLD or whitelist whose governance channel is NOT configured, with
# the verbatim reason.  This is the "далее вайтлист по мере наличия каналов" half
# of ADR-070 п.14: the candidate slug is written down so verifying it is a
# one-line curl, and it is deliberately NOT used for fetching until verified.
#
# Why not just wire the candidates in: this session could not reach
# hub.snapshot.org (egress proxy answered 403 to the space-existence query), so
# every slug below is UNVERIFIED.  A wrong slug fails silently into
# `snapshot_spaces_failed` noise; a slug that happens to resolve to somebody
# else's space gets published as OUR coverage.  Either way the report would stop
# being true, which is the exact defect ADR-070 п.14 closes.
GOVERNANCE_SOURCE_UNCONFIRMED: dict[str, dict[str, str]] = {
    "pendle": {
        "candidate_space": "pendle.eth",
        "reason": (
            "held/whitelisted; Snapshot space UNVERIFIED — vePENDLE voting runs on "
            "Pendle's own app, so a Snapshot space may not exist at all"
        ),
    },
    "maple": {
        "candidate_space": "maplefinance.eth",
        "reason": "held/whitelisted; Snapshot space UNVERIFIED (slug not confirmed against hub.snapshot.org)",
    },
    "morpho_blue": {
        "candidate_space": "morpho.eth",
        "reason": "held/whitelisted; Snapshot space UNVERIFIED (slug not confirmed against hub.snapshot.org)",
    },
    "morpho_steakhouse": {
        "candidate_space": "morpho.eth",
        "reason": (
            "held via a MetaMorpho vault; vault-curator decisions are not DAO proposals — "
            "the channel to watch is UNDECIDED, not merely unverified"
        ),
    },
    "spark_susds": {
        "candidate_space": "",
        "reason": (
            "held; Sky/Spark governance channel deliberately NOT configured — "
            "sUSDS stays at 0% until GSM Pause Delay >= 48h is confirmed on-chain (invariant #10)"
        ),
    },
}

# Tally governor addresses for on-chain voters (our protocols only).
TALLY_GOVERNORS: dict[str, str] = {
    "compound-v3":  "0xc0Da02939E1441F497fd74F78cE7Decb17B66529",  # Compound Governor Bravo
}

# Keywords for category classification
_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "emergency":        ["emergency", "pause", "freeze", "halt", "exploit", "hack"],
    "upgrade":          ["upgrade", "migration", "proxy", "implementation", "deploy", "v2", "v3"],
    "risk_param":       ["ltv", "liquidation threshold", "collateral factor", "borrow cap",
                         "supply cap", "reserve factor", "loan-to-value", "health factor",
                         "liquidation bonus", "debt ceiling", "risk parameter"],
    "parameter_change": ["interest rate", "fee", "spread", "oracle", "price feed",
                         "incentive", "reward", "emission", "slope"],
    "treasury":         ["grant", "treasury", "fund", "budget", "spending", "allocation",
                         "compensation", "payment", "investment"],
}

# Risk-trigger categories that warrant score recalculation
RISK_TRIGGER_CATEGORIES = frozenset({"risk_param", "upgrade", "emergency"})


# ---------------------------------------------------------------------------
# Coverage accounting — "what did we NOT look at?"
# ---------------------------------------------------------------------------
#
# The counters above (snapshot_spaces_ok / _failed) describe the *transport*:
# did the configured spaces answer?  They say nothing about whether the
# configured spaces are the protocols we actually care about.  Measured on
# live production data 2026-08-01: 8 spaces answered, 0 failed, last_error
# null — and the intersection with the live portfolio was EMPTY.  The three
# sets below keep those two questions apart.

UNCHECKED = "unchecked"
_STATE_ACTIVE_HIGH = "active_high"
_STATE_NONE = "none"


def _normalise_protocol_key(key: str) -> str:
    """Fold ``aave-v3`` / ``aave_v3`` / ``Aave V3`` onto one comparable form."""
    return "".join(ch for ch in str(key).strip().lower() if ch.isalnum())


def monitored_protocol_keys() -> set[str]:
    """Protocol keys that have a governance source configured in this module."""
    return set(SNAPSHOT_SPACES) | set(TALLY_GOVERNORS)


def whitelisted_protocol_keys() -> Optional[list[str]]:
    """
    Investable-protocol keys, read from the single registry
    (``spa_core.adapters.ADAPTER_REGISTRY``) rather than duplicated here — a
    second hand-maintained list is exactly the drift that produced this bug.

    Returns ``None`` when the registry cannot be read or yields nothing.  The
    caller MUST treat ``None`` as *not measured*, never as "fully covered"
    (fail-CLOSED, invariant #2).  NEVER raises.
    """
    try:
        from spa_core.adapters import ADAPTER_REGISTRY  # local: avoid import cost/cycles
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch
        log.warning("whitelist unreadable (ADAPTER_REGISTRY import failed): %s", exc)
        return None
    try:
        keys: list[str] = []
        entries = (
            ADAPTER_REGISTRY.keys()
            if isinstance(ADAPTER_REGISTRY, dict)
            else ADAPTER_REGISTRY
        )
        for entry in entries:
            if isinstance(entry, str):
                keys.append(entry)
            elif isinstance(entry, (tuple, list)) and entry:
                keys.append(str(entry[0]))
        keys = sorted({k for k in keys if k})
        return keys or None
    except Exception as exc:
        log.warning("whitelist unreadable (ADAPTER_REGISTRY malformed): %s", exc)
        return None


PORTFOLIO_STATUS_PATH = (
    Path(__file__).resolve().parents[2] / "data" / "paper_trading_status.json"
)
HELD_POSITIONS_KEY = "current_positions"


def read_held_protocol_keys(status_payload: object) -> Tuple[Optional[list[str]], Optional[str]]:
    """Protocols we are holding RIGHT NOW, from a loaded paper-trading status payload.

    Returns ``(keys, unchecked_reason)``.  ``keys`` is ``None`` whenever the held set
    could not be read — the caller MUST NOT read that as "we hold nothing" (that would
    publish full held-coverage on an unreadable file, fail-CLOSED, invariant #2).

    A position map that is PRESENT but empty is a measurement (all cash) and comes back
    as ``([], None)``.  NEVER raises.
    """
    if not isinstance(status_payload, dict):
        return None, (
            f"portfolio status payload is {type(status_payload).__name__}, not a mapping"
        )
    if HELD_POSITIONS_KEY not in status_payload:
        return None, (
            f"portfolio status has no {HELD_POSITIONS_KEY!r} key; top-level keys: "
            f"{sorted(str(k) for k in status_payload.keys())!r}"
        )
    positions = status_payload[HELD_POSITIONS_KEY]
    if isinstance(positions, dict):
        keys = sorted({str(k) for k in positions.keys() if str(k)})
        return keys, None
    if isinstance(positions, list):
        keys = []
        for entry in positions:
            if isinstance(entry, dict):
                name = entry.get("protocol") or entry.get("adapter") or entry.get("name")
                if name:
                    keys.append(str(name))
            elif isinstance(entry, str) and entry:
                keys.append(entry)
        return sorted(set(keys)), None
    return None, (
        f"portfolio status key {HELD_POSITIONS_KEY!r} is {type(positions).__name__}, "
        "neither mapping nor list"
    )


def load_held_protocol_keys(
    path: Optional[Path] = None,
) -> Tuple[Optional[list[str]], Optional[str]]:
    """Read the held set from disk.  ``(None, reason)`` on any failure.  NEVER raises."""
    target = Path(path) if path else PORTFOLIO_STATUS_PATH
    try:
        from spa_core.utils.atomic import atomic_load
        payload = atomic_load(str(target), default=None)
    except Exception as exc:  # pragma: no cover - exercised via monkeypatch
        return None, f"portfolio status unreadable ({target.name}): {exc}"
    if payload is None:
        return None, f"portfolio status missing or unreadable at {target.name}"
    return read_held_protocol_keys(payload)


def unconfirmed_source_report() -> list[dict[str, str]]:
    """The named half of the gap: protocols with NO configured channel, and why.

    Published in the output so "unchecked" carries a cause the owner can act on
    instead of being an anonymous absence.
    """
    return [
        {
            "protocol": key,
            "candidate_space": str(entry.get("candidate_space", "")),
            "reason": str(entry.get("reason", "")),
            "verified": "no",
        }
        for key, entry in sorted(GOVERNANCE_SOURCE_UNCONFIRMED.items())
    ]


def coverage_report(
    *,
    scan_status: Optional[dict[str, str]] = None,
    held: Optional[list[str]] = None,
    held_unchecked: Optional[str] = None,
) -> dict:
    """
    Answer "which investable protocols does this watcher not look at?".

    ``scan_status`` — optional per-protocol outcome of the most recent scan
    (``{protocol_key: "ok" | "failed"}``).  A configured protocol whose source
    ERRORED this run is reported as unchecked too: it was not measured, and the
    aggregate ``snapshot_spaces_failed`` counter cannot say which one it was.

    Keys
    ----
    ``measured``                  — False when the whitelist could not be read
    ``reason``                    — verbatim cause when ``measured`` is False
    ``monitored_protocols``       — have a governance source configured
    ``covered_protocols``         — whitelisted AND monitored AND not failed
    ``unchecked_protocols``       — whitelisted with NO usable source this run
    ``monitored_not_whitelisted`` — a source exists, but it is not investable
    ``failed_this_scan``          — configured, but the source errored this run
    ``held_measured``             — False when the held set could not be read
    ``held_reason``               — verbatim cause when ``held_measured`` is False
    ``held_protocols``            — protocols we are holding right now
    ``held_covered`` / ``held_unchecked``
                                  — the same split restricted to what we HOLD
    ``unconfirmed_sources``       — held/whitelisted protocols with NO channel, and why

    ``held`` / ``held_unchecked`` are inputs on purpose: the held set is a
    different file's business, and a function that goes and reads it cannot be
    tested hermetically.  Omitting both means the held set was not supplied —
    reported as ``held_measured: False``, never as "we hold nothing".

    Matching is **normalised key equality**, nothing cleverer.  Where the two
    sides spell a protocol differently (space ``yearn`` vs registry
    ``yearn_v3``) the keys do not match and the registry entry is reported as
    unchecked.  That errs toward *under*-claiming coverage, which is the safe
    direction; inventing an alias table here would be a second hand-maintained
    mapping — the exact drift that produced this bug.  Aligning the keys is a
    configuration decision, not something to guess at silently.

    NEVER raises.
    """
    monitored = monitored_protocol_keys()
    failed = sorted(k for k, v in (scan_status or {}).items() if v != "ok")
    mon_norm_all = {_normalise_protocol_key(k): k for k in monitored}
    failed_norm_all = {_normalise_protocol_key(k) for k in failed}

    # ── held accounting (independent of whether the registry reads) ──
    held_reason = held_unchecked
    held_keys: Optional[list[str]] = None
    if held is not None:
        held_keys = sorted({str(k) for k in held if str(k)})
    elif held_reason is None:
        held_reason = "held set NOT SUPPLIED — held coverage NOT MEASURED"
    held_block: dict = {
        "held_measured": held_keys is not None,
        "held_reason": held_reason if held_keys is None else None,
        "held_protocols": held_keys or [],
        "held_covered": [],
        "held_unchecked": [],
        "unconfirmed_sources": unconfirmed_source_report(),
    }
    if held_keys is not None:
        for key in held_keys:
            n = _normalise_protocol_key(key)
            if n in mon_norm_all and n not in failed_norm_all:
                held_block["held_covered"].append(key)
            else:
                held_block["held_unchecked"].append(key)

    base = {
        "monitored_protocols": sorted(monitored),
        "failed_this_scan": failed,
        **held_block,
    }
    try:
        whitelist = whitelisted_protocol_keys()
        if whitelist is None:
            return {
                **base,
                "measured": False,
                "reason": "ADAPTER_REGISTRY unreadable — coverage NOT MEASURED",
                "whitelist_size": None,
                "covered_protocols": [],
                "unchecked_protocols": [],
                "monitored_not_whitelisted": [],
            }

        mon_norm = {_normalise_protocol_key(k): k for k in monitored}
        failed_norm = {_normalise_protocol_key(k) for k in failed}
        wl_norm = {_normalise_protocol_key(k) for k in whitelist}

        covered, unchecked = [], []
        for key in whitelist:
            n = _normalise_protocol_key(key)
            if n in mon_norm and n not in failed_norm:
                covered.append(key)
            else:
                unchecked.append(key)
        not_whitelisted = sorted(
            orig for n, orig in mon_norm.items() if n not in wl_norm
        )
        return {
            **base,
            "measured": True,
            "reason": None,
            "whitelist_size": len(whitelist),
            "covered_protocols": sorted(covered),
            "unchecked_protocols": sorted(unchecked),
            "monitored_not_whitelisted": not_whitelisted,
        }
    except Exception as exc:
        log.error("coverage_report failed: %s", exc)
        return {
            **base,
            "measured": False,
            "reason": f"coverage computation failed: {exc}",
            "whitelist_size": None,
            "covered_protocols": [],
            "unchecked_protocols": [],
            "monitored_not_whitelisted": [],
        }


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class GovernanceProposal:
    """
    A single governance proposal record.
    """
    id:            str
    protocol:      str
    title:         str
    category:      str
    severity:      str
    state:         str          # "active" | "closed" | "pending" | "queued"
    source:        str          # "snapshot" | "tally" | "bootstrap"
    start_at:      str          # ISO-8601
    end_at:        str          # ISO-8601
    url:           str
    votes_for:     float = 0.0
    votes_against: float = 0.0
    quorum_met:    bool = False
    detected_at:   str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def to_dict(self) -> dict:
        return {
            "id":           self.id,
            "protocol":     self.protocol,
            "title":        self.title,
            "category":     self.category,
            "severity":     self.severity,
            "state":        self.state,
            "source":       self.source,
            "start_at":     self.start_at,
            "end_at":       self.end_at,
            "url":          self.url,
            "votes_for":    self.votes_for,
            "votes_against": self.votes_against,
            "quorum_met":   self.quorum_met,
            "detected_at":  self.detected_at,
        }


# ---------------------------------------------------------------------------
# Bootstrap seed data (offline fallback)
# ---------------------------------------------------------------------------

BOOTSTRAP_PROPOSALS: list[GovernanceProposal] = [
    GovernanceProposal(
        id="snapshot:bootstrap-001",
        protocol="aave-v3",
        title="[ARFC] Risk Parameter Updates for Aave V3 — USDC LTV Increase",
        category="risk_param",
        severity="HIGH",
        state="closed",
        source="bootstrap",
        start_at="2026-05-20T00:00:00Z",
        end_at="2026-05-23T00:00:00Z",
        url="https://snapshot.org/#/aave.eth/proposal/bootstrap-001",
        votes_for=1_250_000,
        votes_against=45_000,
        quorum_met=True,
    ),
    GovernanceProposal(
        id="snapshot:bootstrap-002",
        protocol="compound-v3",
        title="Add LINK as collateral in cUSDCv3",
        category="parameter_change",
        severity="MEDIUM",
        state="closed",
        source="bootstrap",
        start_at="2026-05-18T00:00:00Z",
        end_at="2026-05-21T00:00:00Z",
        url="https://snapshot.org/#/comp-vote.eth/proposal/bootstrap-002",
        votes_for=890_000,
        votes_against=12_000,
        quorum_met=True,
    ),
    # bootstrap-003 (curve) and bootstrap-004 (lido) removed with their spaces —
    # ADR-070 п.14.  `test_protocols_are_whitelisted` in
    # spa_core/tests/test_governance_watcher.py enforces exactly this: seed data may
    # only name protocols the watcher is configured for, so a stranger cannot survive
    # in the fallback payload after its space is gone.
    GovernanceProposal(
        id="snapshot:bootstrap-005",
        protocol="aave-v3",
        title="Aave V3 Upgrade: New risk model for volatile collateral",
        category="upgrade",
        severity="HIGH",
        state="active",
        source="bootstrap",
        start_at="2026-05-27T00:00:00Z",
        end_at="2026-06-02T00:00:00Z",
        url="https://snapshot.org/#/aave.eth/proposal/bootstrap-005",
        votes_for=780_000,
        votes_against=95_000,
        quorum_met=False,
    ),
    # bootstrap-006 (uniswap-v3) removed with its space — ADR-070 п.14.
]


# ---------------------------------------------------------------------------
# Category classification
# ---------------------------------------------------------------------------

def classify_category(title: str, body: str = "") -> str:
    """
    Classify a governance proposal into a category using keyword matching.

    Applies category keywords in priority order:
    emergency > upgrade > risk_param > parameter_change > treasury > general

    Returns the first matching category or ``"general"`` if none match.
    Deterministic — no LLM.
    """
    text = (title + " " + body).lower()
    for category in ["emergency", "upgrade", "risk_param", "parameter_change", "treasury"]:
        for kw in _CATEGORY_KEYWORDS[category]:
            if kw in text:
                return category
    return "general"


def classify_severity(category: str, state: str) -> str:
    """
    Map proposal category + state to a severity level.

    Rules:
    * emergency / upgrade                        → HIGH
    * risk_param on active proposal              → HIGH
    * risk_param on closed proposal              → MEDIUM
    * parameter_change / treasury                → MEDIUM
    * general / unknown                          → LOW
    """
    if category in ("emergency", "upgrade"):
        return "HIGH"
    if category == "risk_param":
        return "HIGH" if state == "active" else "MEDIUM"
    if category in ("parameter_change", "treasury"):
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# HTTP helper
# ---------------------------------------------------------------------------

def _http_get(url: str, *, headers: dict | None = None, timeout: int = _REQUEST_TIMEOUT) -> dict:
    """
    Perform a GET request and return the JSON response as a dict.
    Raises urllib.error.URLError / ValueError on failure.
    """
    req_headers = {"Accept": "application/json", "User-Agent": "SPA-GovernanceWatcher/1.0"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _http_post(
    url: str,
    payload: dict,
    *,
    timeout: int = _REQUEST_TIMEOUT,
    extra_headers: dict | None = None,
) -> dict:
    """
    Perform a single POST request with a JSON payload and return the JSON
    response.  Raises on failure (use :func:`_http_post_retry` for resilience).
    """
    data = json.dumps(payload).encode()
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "SPA-GovernanceWatcher/1.0",
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def _sleep(seconds: float) -> None:
    """Indirection over :func:`time.sleep` so tests can patch out backoff delays."""
    time.sleep(seconds)


def _http_post_retry(
    url: str,
    payload: dict,
    *,
    timeout: int = _REQUEST_TIMEOUT,
    retries: int = _MAX_RETRIES,
    extra_headers: dict | None = None,
) -> dict:
    """
    POST with retry + exponential backoff.

    Retries on any exception (timeout, transient 5xx, connection reset).
    Sleeps ``_BACKOFF_BASE ** attempt`` seconds between attempts
    (1s, 2s, 4s, ...).  Raises the last exception if all attempts fail.
    """
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            return _http_post(url, payload, timeout=timeout, extra_headers=extra_headers)
        except Exception as exc:  # noqa: BLE001 — deliberately broad, we retry all
            last_exc = exc
            if attempt < retries - 1:
                sleep_s = _BACKOFF_BASE ** attempt
                log.debug("HTTP POST %s failed (attempt %d/%d): %s — retry in %ds",
                          url, attempt + 1, retries, exc, sleep_s)
                _sleep(sleep_s)
    # All attempts exhausted
    raise last_exc if last_exc else RuntimeError("HTTP POST failed with no exception")


# ---------------------------------------------------------------------------
# Snapshot fetcher
# ---------------------------------------------------------------------------

SNAPSHOT_GQL_URL = "https://hub.snapshot.org/graphql"

_SNAPSHOT_QUERY = """
query Proposals($space: String!, $state: String!) {
  proposals(
    first: 10
    skip: 0
    where: { space: $space, state: $state }
    orderBy: "created"
    orderDirection: desc
  ) {
    id
    title
    body
    state
    start
    end
    scores
    scores_total
    quorum
    link
  }
}
"""


def _fetch_snapshot_proposals(
    protocol_key: str,
    space: str,
    *,
    state: str = "active",
) -> Tuple[bool, list[GovernanceProposal]]:
    """
    Fetch governance proposals from Snapshot GraphQL API for *space*.

    Returns a ``(ok, proposals)`` tuple:

    * ``ok``        — True if the API call succeeded (even with zero results),
                      False if the network/HTTP call failed.
    * ``proposals`` — list of parsed proposals (possibly empty).

    This distinction is critical: a space with **no active proposals** is a
    successful call that returns ``(True, [])`` — it must NOT be treated as a
    fallback condition.  Only a genuine network failure yields ``(False, [])``.
    """
    try:
        resp = _http_post_retry(SNAPSHOT_GQL_URL, {
            "query": _SNAPSHOT_QUERY,
            "variables": {"space": space, "state": state},
        })
        proposals_raw = resp.get("data", {}).get("proposals", [])
        results: list[GovernanceProposal] = []
        for p in proposals_raw:
            title = p.get("title", "")
            body  = p.get("body", "")
            pid   = p.get("id", "")
            pstate = p.get("state", "active")
            scores = p.get("scores", [0, 0])
            votes_for     = float(scores[0]) if len(scores) > 0 else 0.0
            votes_against = float(scores[1]) if len(scores) > 1 else 0.0
            quorum = float(p.get("quorum", 0) or 0)
            total  = float(p.get("scores_total", 0) or 0)
            quorum_met = (quorum == 0) or (total >= quorum)
            category = classify_category(title, body)
            severity = classify_severity(category, pstate)
            results.append(GovernanceProposal(
                id=f"snapshot:{pid}",
                protocol=protocol_key,
                title=title[:200],
                category=category,
                severity=severity,
                state=pstate,
                source="snapshot",
                start_at=_ts(p.get("start")),
                end_at=_ts(p.get("end")),
                url=p.get("link") or f"https://snapshot.org/#/{space}/proposal/{pid}",
                votes_for=votes_for,
                votes_against=votes_against,
                quorum_met=quorum_met,
            ))
        return True, results
    except Exception as exc:
        log.debug("Snapshot fetch failed for %s/%s: %s", protocol_key, space, exc)
        return False, []


# ---------------------------------------------------------------------------
# Tally fetcher
# ---------------------------------------------------------------------------

TALLY_API_URL = "https://api.tally.xyz/query"

_TALLY_QUERY = """
query Proposals($governorId: ID!, $afterId: ID) {
  proposals(
    governorId: $governorId
    pagination: { limit: 5 }
    sort: { field: START_BLOCK, order: DESC }
  ) {
    id
    title
    description
    status
    voteStats {
      votes
      type
      percent
    }
    quorum
    block {
      timestamp
    }
    end {
      timestamp
    }
  }
}
"""


def _fetch_tally_proposals(protocol_key: str, governor_id: str) -> Tuple[bool, list[GovernanceProposal]]:
    """
    Fetch proposals from Tally API for an on-chain governor.

    Tally now requires an ``Api-Key`` header.  If ``TALLY_API_KEY`` env var is
    not set, the call is skipped and ``(False, [])`` is returned — Snapshot then
    covers these protocols (comp-vote.eth / uniswap spaces exist on Snapshot).

    Returns a ``(ok, proposals)`` tuple, mirroring the Snapshot fetcher.
    """
    if not TALLY_API_KEY:
        log.debug("Tally skipped for %s — TALLY_API_KEY not set", protocol_key)
        return False, []
    try:
        resp = _http_post_retry(
            TALLY_API_URL,
            {"query": _TALLY_QUERY, "variables": {"governorId": governor_id}},
            extra_headers={"Api-Key": TALLY_API_KEY},
        )
        proposals_raw = resp.get("data", {}).get("proposals", [])
        results: list[GovernanceProposal] = []
        for p in proposals_raw:
            title = p.get("title", "") or p.get("description", "")[:100]
            pid   = str(p.get("id", ""))
            raw_state = str(p.get("status", "active")).lower()
            # Map Tally states to canonical
            state_map = {"active": "active", "succeeded": "closed", "executed": "closed",
                         "defeated": "closed", "queued": "queued", "pending": "pending",
                         "canceled": "closed"}
            pstate = state_map.get(raw_state, "active")
            vote_stats = p.get("voteStats", [])
            votes_for = votes_against = 0.0
            for vs in vote_stats:
                vtype = str(vs.get("type", "")).upper()
                count = float(vs.get("votes", 0) or 0)
                if vtype == "FOR":
                    votes_for = count
                elif vtype == "AGAINST":
                    votes_against = count
            quorum = float(p.get("quorum", 0) or 0)
            quorum_met = (quorum == 0) or (votes_for >= quorum)
            category = classify_category(title)
            severity = classify_severity(category, pstate)
            start_ts = (p.get("block") or {}).get("timestamp", "")
            end_ts   = (p.get("end")   or {}).get("timestamp", "")
            results.append(GovernanceProposal(
                id=f"tally:{pid}",
                protocol=protocol_key,
                title=title[:200],
                category=category,
                severity=severity,
                state=pstate,
                source="tally",
                start_at=_ts_str(start_ts),
                end_at=_ts_str(end_ts),
                url=f"https://www.tally.xyz/gov/{protocol_key}/proposal/{pid}",
                votes_for=votes_for,
                votes_against=votes_against,
                quorum_met=quorum_met,
            ))
        return True, results
    except Exception as exc:
        log.debug("Tally fetch failed for %s/%s: %s", protocol_key, governor_id, exc)
        return False, []


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _ts(unix: int | float | None) -> str:
    """Convert a Unix timestamp to ISO-8601 string, or return epoch on failure."""
    try:
        return datetime.fromtimestamp(float(unix), tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except Exception:
        return "1970-01-01T00:00:00Z"


def _ts_str(s: str | None) -> str:
    """Normalise an arbitrary timestamp string to ISO-8601, or epoch on failure."""
    if not s:
        return "1970-01-01T00:00:00Z"
    try:
        # Already ISO-like
        if "T" in s:
            return s[:19] + "Z"
        return _ts(float(s))
    except Exception:
        return "1970-01-01T00:00:00Z"


# ---------------------------------------------------------------------------
# GovernanceWatcher — main class
# ---------------------------------------------------------------------------

class GovernanceWatcher:
    """
    Governance proposal scanner for SPA whitelist protocols.

    Fetches active proposals from Snapshot GraphQL and Tally REST APIs,
    classifies them deterministically by keyword matching, and writes a
    summary to ``data/governance_proposals.json``.

    All public methods are **guaranteed never to raise**.
    """

    def __init__(
        self,
        output_file: str | Path = DEFAULT_OUTPUT_PATH,
        risk_scores_file: str | Path | None = None,
        portfolio_status_file: str | Path | None = None,
    ) -> None:
        self.output_file = Path(output_file)
        self._risk_scores_file = Path(risk_scores_file) if risk_scores_file else None
        # Injectable so held-coverage can be tested hermetically (no live data/).
        self._portfolio_status_file = (
            Path(portfolio_status_file) if portfolio_status_file else PORTFOLIO_STATUS_PATH
        )
        self._fallback_used: bool = False
        # ── health-check state (populated by scan_all) ──
        self._snapshot_ok: bool = False
        self._tally_ok: bool = False
        self._snapshot_spaces_ok: int = 0
        self._snapshot_spaces_failed: int = 0
        self._last_live_fetch: Optional[str] = None
        self._last_error: Optional[str] = None
        # Per-protocol scan outcome ({key: "ok" | "failed"}).  The aggregate
        # spaces_ok/spaces_failed counters cannot name WHICH protocol went
        # unscanned; coverage accounting needs the names.
        self._scan_status: dict[str, str] = {}

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def scan_all(self, *, offline: bool = False) -> list[GovernanceProposal]:
        """
        Scan all whitelisted protocols and return a flat list of proposals.
        NEVER raises.
        """
        try:
            proposals: list[GovernanceProposal] = []
            # Reset health-check state for this scan
            self._fallback_used = False
            self._snapshot_ok = False
            self._tally_ok = False
            self._snapshot_spaces_ok = 0
            self._snapshot_spaces_failed = 0
            self._last_error = None
            self._scan_status = {}

            if offline:
                log.info("Offline mode — returning bootstrap proposals")
                self._fallback_used = True
                proposals = list(BOOTSTRAP_PROPOSALS)
                # Apply same sort as live path
                sev_order_local = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
                state_order_local = {"active": 0, "pending": 1, "queued": 2, "closed": 3}
                proposals.sort(key=lambda p: (
                    state_order_local.get(p.state, 9),
                    sev_order_local.get(p.severity, 9),
                    p.start_at,
                ))
                return proposals

            # ── Snapshot ──
            # IMPORTANT: a space that returns zero ACTIVE proposals is a SUCCESS,
            # not a failure.  We only count genuine network/HTTP errors toward
            # the failure tally that triggers fallback.
            for protocol_key, space in SNAPSHOT_SPACES.items():
                try:
                    ok, active = _fetch_snapshot_proposals(protocol_key, space, state="active")
                    if ok:
                        self._snapshot_spaces_ok += 1
                        self._scan_status[protocol_key] = "ok"
                        proposals.extend(active)
                        log.debug("Snapshot %s: ok, %d active proposals",
                                  protocol_key, len(active))
                    else:
                        self._snapshot_spaces_failed += 1
                        self._scan_status[protocol_key] = "failed"
                except Exception as exc:
                    self._snapshot_spaces_failed += 1
                    self._scan_status[protocol_key] = "failed"
                    self._last_error = f"snapshot:{protocol_key}: {exc}"
                    log.warning("Snapshot scan error %s: %s", protocol_key, exc)

            # Snapshot is considered healthy if AT LEAST ONE space responded.
            self._snapshot_ok = self._snapshot_spaces_ok > 0

            # ── Tally (optional; skipped gracefully without API key) ──
            for protocol_key, gov_id in TALLY_GOVERNORS.items():
                try:
                    ok, tally_props = _fetch_tally_proposals(protocol_key, gov_id)
                    if ok:
                        self._tally_ok = True
                        self._scan_status[protocol_key] = "ok"
                        proposals.extend(tally_props)
                        log.debug("Tally %s: ok, %d proposals", protocol_key, len(tally_props))
                    else:
                        self._scan_status.setdefault(protocol_key, "failed")
                except Exception as exc:
                    self._scan_status.setdefault(protocol_key, "failed")
                    log.debug("Tally error %s: %s", protocol_key, exc)

            # ── Fallback decision ──
            # Fall back to bootstrap ONLY when no live source responded at all
            # (Snapshot down AND Tally unavailable).  An empty-but-healthy live
            # scan (no active proposals anywhere) is a valid, NON-fallback result.
            live_ok = self._snapshot_ok or self._tally_ok
            if not live_ok:
                log.info("No live governance source responded — using bootstrap "
                         "(snapshot_ok=%s, tally_ok=%s)", self._snapshot_ok, self._tally_ok)
                proposals = list(BOOTSTRAP_PROPOSALS)
                self._fallback_used = True
            else:
                self._last_live_fetch = datetime.now(timezone.utc).strftime(
                    "%Y-%m-%dT%H:%M:%SZ"
                )
                log.debug("Live governance scan ok: %d proposals "
                          "(snapshot_ok=%s, tally_ok=%s, spaces_ok=%d, spaces_failed=%d)",
                          len(proposals), self._snapshot_ok, self._tally_ok,
                          self._snapshot_spaces_ok, self._snapshot_spaces_failed)

            # De-duplicate by id
            seen: set[str] = set()
            unique: list[GovernanceProposal] = []
            for p in proposals:
                if p.id not in seen:
                    seen.add(p.id)
                    unique.append(p)

            # Sort: active first, then by severity (HIGH > MEDIUM > LOW), then by start_at desc
            sev_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
            state_order = {"active": 0, "pending": 1, "queued": 2, "closed": 3}
            unique.sort(key=lambda p: (
                state_order.get(p.state, 9),
                sev_order.get(p.severity, 9),
                p.start_at,
            ))
            return unique

        except Exception as exc:
            log.error("GovernanceWatcher.scan_all failed: %s", exc)
            return list(BOOTSTRAP_PROPOSALS)

    def _held_protocols(self) -> Tuple[Optional[list[str]], Optional[str]]:
        """The protocols we hold right now, or a verbatim reason we do not know."""
        return load_held_protocol_keys(self._portfolio_status_file)

    def export(self, *, dry_run: bool = True, offline: bool = False) -> dict:
        """
        Scan proposals, build the output dict, and optionally write it to
        ``data/governance_proposals.json``.

        Returns the dict regardless of ``dry_run``.
        NEVER raises.
        """
        try:
            proposals = self.scan_all(offline=offline)
            by_category: dict[str, int] = {}
            by_severity: dict[str, int] = {}
            by_protocol: dict[str, int] = {}
            for p in proposals:
                by_category[p.category] = by_category.get(p.category, 0) + 1
                by_severity[p.severity] = by_severity.get(p.severity, 0) + 1
                by_protocol[p.protocol] = by_protocol.get(p.protocol, 0) + 1

            # Build the source list from what actually responded
            if self._fallback_used:
                sources = ["bootstrap"]
            else:
                sources = []
                if self._snapshot_ok:
                    sources.append("snapshot")
                if self._tally_ok:
                    sources.append("tally")
                if not sources:  # offline path or edge case
                    sources = ["bootstrap"]

            # Coverage is about WHAT WE LOOKED AT, not whether the transport
            # answered.  In fallback/offline mode nothing live was measured at
            # all, so no protocol counts as covered.
            held_keys, held_reason = self._held_protocols()
            coverage = coverage_report(
                scan_status=None if self._fallback_used else self._scan_status,
                held=held_keys,
                held_unchecked=held_reason,
            )
            if self._fallback_used and coverage.get("measured"):
                coverage["covered_protocols"] = []
                coverage["unchecked_protocols"] = sorted(
                    whitelisted_protocol_keys() or []
                )
                coverage["reason"] = (
                    "bootstrap fallback — no live governance source responded; "
                    "nothing was measured this run"
                )
            if self._fallback_used and coverage.get("held_measured"):
                # Same rule for the held set: a fallback run measured nothing, so
                # nothing we hold may be published as covered.
                coverage["held_covered"] = []
                coverage["held_unchecked"] = list(coverage.get("held_protocols") or [])

            result = {
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "watcher_version": "1.1",
                "sources": sources,
                "fallback_used": self._fallback_used,
                # ── health-check fields ──
                "fetch_method": "fallback" if self._fallback_used else "live",
                "snapshot_ok": self._snapshot_ok,
                "tally_ok": self._tally_ok,
                "snapshot_spaces_ok": self._snapshot_spaces_ok,
                "snapshot_spaces_failed": self._snapshot_spaces_failed,
                "last_live_fetch": self._last_live_fetch,
                "last_error": self._last_error,
                # ── coverage: which investable protocols were NOT looked at ──
                "coverage": coverage,
                "proposals": [p.to_dict() for p in proposals],
                "summary": {
                    "total_proposals": len(proposals),
                    # None (not 0) when coverage itself is not measured — an
                    # unmeasured gap must never read as "no gap".
                    "unchecked_protocol_count": (
                        len(coverage["unchecked_protocols"])
                        if coverage.get("measured") else None
                    ),
                    # The expensive gap: a protocol holding real (paper) capital whose
                    # governance nobody watched. None (not 0) when the held set itself
                    # could not be read.
                    "unchecked_held_count": (
                        len(coverage["held_unchecked"])
                        if coverage.get("held_measured") else None
                    ),
                    "active_count":    sum(1 for p in proposals if p.state == "active"),
                    "by_category":     by_category,
                    "by_severity":     by_severity,
                    "by_protocol":     by_protocol,
                    "high_severity_count": by_severity.get("HIGH", 0),
                    "risk_triggers": [
                        p.to_dict() for p in proposals
                        if p.category in RISK_TRIGGER_CATEGORIES and p.state == "active"
                    ],
                },
            }
            if not dry_run:
                from spa_core.utils.atomic import atomic_save
                # Atomic write (tmp + os.replace) — never leave a partial
                # data/governance_proposals.json state file on crash.
                atomic_save(result, str(self.output_file), indent=2)
                log.info("Governance proposals written to %s", self.output_file)
            return result
        except Exception as exc:
            log.error("GovernanceWatcher.export failed: %s", exc)
            return {"error": str(exc), "proposals": []}

    def get_risk_triggers(self, *, offline: bool = False) -> list[GovernanceProposal]:
        """
        Return active proposals in RISK_TRIGGER_CATEGORIES (risk_param, upgrade, emergency).
        These should trigger risk score recalculation in scoring_engine.py.
        NEVER raises.
        """
        try:
            return [
                p for p in self.scan_all(offline=offline)
                if p.category in RISK_TRIGGER_CATEGORIES and p.state == "active"
            ]
        except Exception as exc:
            log.error("GovernanceWatcher.get_risk_triggers failed: %s", exc)
            return []

    def has_active_risk_proposals(self, protocol_key: str, *, offline: bool = False) -> bool:
        """
        Return True if *protocol_key* has any active HIGH-severity proposal.
        Useful for quick checks in the scheduler.
        NEVER raises.

        .. warning::

           ``False`` here does NOT mean "checked, nothing found".  A protocol
           with no configured governance source — most of the SPA whitelist —
           also returns ``False``.  Behaviour is kept as-is for existing
           callers; use :meth:`risk_proposal_state` when the difference between
           "clean" and "never looked" matters.
        """
        try:
            return any(
                p.protocol == protocol_key and p.severity == "HIGH" and p.state == "active"
                for p in self.scan_all(offline=offline)
            )
        except Exception:
            return False

    def risk_proposal_state(self, protocol_key: str, *, offline: bool = False) -> str:
        """
        Tri-state answer to "does *protocol_key* have an active HIGH proposal?".

        ``"active_high"`` · ``"none"`` · ``"unchecked"``

        :meth:`has_active_risk_proposals` returns a bool and therefore cannot
        tell "we checked and found nothing" apart from "we never look at this
        protocol" — for every protocol without a configured source it answers
        ``False``, which is a claim about a check that never ran.  This method
        exists so callers can refuse instead of guessing (fail-CLOSED).

        ``unchecked`` is returned when the protocol has no configured source,
        when its source errored during this scan, or when the scan fell back to
        bootstrap seed data (nothing live was measured).  NEVER raises.
        """
        try:
            proposals = self.scan_all(offline=offline)
            if self._fallback_used:
                return UNCHECKED
            norm = _normalise_protocol_key(protocol_key)
            monitored = {_normalise_protocol_key(k) for k in monitored_protocol_keys()}
            if norm not in monitored:
                return UNCHECKED
            if self._scan_status.get(protocol_key, "ok") != "ok":
                return UNCHECKED
            hit = any(
                _normalise_protocol_key(p.protocol) == norm
                and p.severity == "HIGH"
                and p.state == "active"
                for p in proposals
            )
            return _STATE_ACTIVE_HIGH if hit else _STATE_NONE
        except Exception as exc:
            log.error("risk_proposal_state failed for %s: %s", protocol_key, exc)
            return UNCHECKED


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_watcher: Optional[GovernanceWatcher] = None


def get_watcher() -> GovernanceWatcher:
    """Return (and lazily create) the module-level singleton GovernanceWatcher."""
    global _default_watcher
    if _default_watcher is None:
        _default_watcher = GovernanceWatcher()
    return _default_watcher


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_report(result: dict) -> None:
    """
    Render the human-readable report.  Extracted from the ``__main__`` block so
    the operator-facing text is testable — the coverage lines below are the
    whole point of the fix and must not be able to silently regress.
    """
    proposals = result.get("proposals", [])
    summary   = result.get("summary", {})
    print("\n=== SPA Governance Watcher ===")
    print(f"Total proposals:  {summary.get('total_proposals', 0)}")
    print(f"Active:           {summary.get('active_count', 0)}")
    print(f"HIGH severity:    {summary.get('high_severity_count', 0)}")
    print(f"Risk triggers:    {len(summary.get('risk_triggers', []))}")
    print(f"Fetch method:     {result.get('fetch_method', '?')}")
    print(f"Snapshot OK:      {result.get('snapshot_ok', False)} "
          f"({result.get('snapshot_spaces_ok', 0)} ok / "
          f"{result.get('snapshot_spaces_failed', 0)} failed)"
          "   [transport only — see Coverage]")
    print(f"Tally OK:         {result.get('tally_ok', False)}")
    print(f"Fallback used:    {result.get('fallback_used', False)}")
    if result.get("last_error"):
        print(f"Last error:       {result.get('last_error')}")

    # Coverage — the transport counters above say a source ANSWERED, not that
    # the protocols we hold were looked at.  Print the gap by name.
    cov = result.get("coverage") or {}
    if not cov.get("measured"):
        print(f"Coverage:         NOT MEASURED — {cov.get('reason', 'no reason recorded')}")
    else:
        total = cov.get("whitelist_size")
        unchecked = cov.get("unchecked_protocols") or []
        covered = cov.get("covered_protocols") or []
        print(f"Coverage:         {len(covered)}/{total} whitelisted protocols have a "
              f"governance source")
        if unchecked:
            print(f"NOT CHECKED ({len(unchecked)}): {', '.join(unchecked)}")
        stray = cov.get("monitored_not_whitelisted") or []
        if stray:
            print(f"Watched but not investable: {', '.join(stray)}")

    # Held coverage — the gap that costs money, printed separately from the
    # whitelist gap and never collapsed into it.
    if not cov.get("held_measured"):
        print(
            "Held coverage:    NOT MEASURED — "
            f"{cov.get('held_reason', 'no reason recorded')}"
        )
    else:
        held = cov.get("held_protocols") or []
        held_cov = cov.get("held_covered") or []
        held_gap = cov.get("held_unchecked") or []
        print(f"Held coverage:    {len(held_cov)}/{len(held)} HELD protocols watched")
        if held_gap:
            print(f"HELD, NOT CHECKED ({len(held_gap)}): {', '.join(held_gap)}")
    for entry in cov.get("unconfirmed_sources") or []:
        candidate = entry.get("candidate_space") or "(none)"
        print(
            f"  no channel: {entry.get('protocol')} — {entry.get('reason')} "
            f"[candidate: {candidate}, verified: {entry.get('verified')}]"
        )
    print()
    print(f"{'Sev':<7} {'State':<8} {'Protocol':<16} {'Category':<18} Title")
    print("-" * 100)
    for p in proposals:
        print(f"{p['severity']:<7} {p['state']:<8} {p['protocol']:<16} "
              f"{p['category']:<18} {p['title'][:50]}")


if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="SPA Governance Watcher")
    parser.add_argument("--offline", action="store_true", help="Use bootstrap data only")
    parser.add_argument("--json",    action="store_true", help="Print JSON output")
    parser.add_argument("--dry-run", action="store_true", help="Don't write output file",
                        default=True)
    parser.add_argument("--write",   action="store_true", help="Write governance_proposals.json")
    args = parser.parse_args()

    watcher = GovernanceWatcher()
    result = watcher.export(dry_run=not args.write, offline=args.offline)

    if args.json:
        print(json.dumps(result, indent=2))
        sys.exit(0)

    _print_report(result)
