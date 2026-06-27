"""
Governance Watcher — FEAT-MON-002 (Sprint v3.18).

Monitors active governance proposals for SPA whitelist protocols.
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

# Snapshot space slugs for whitelisted protocols
SNAPSHOT_SPACES: dict[str, str] = {
    "aave-v3":      "aave.eth",
    "compound-v3":  "comp-vote.eth",
    "uniswap-v3":   "uniswap",
    "curve":        "curve.eth",
    "lido":         "lido-snapshot.eth",
    "maker":        "makerdao.eth",
    "balancer":     "balancer.eth",
    "yearn":        "ybaby.eth",
}

# Tally governor addresses for on-chain voters
TALLY_GOVERNORS: dict[str, str] = {
    "compound-v3":  "0xc0Da02939E1441F497fd74F78cE7Decb17B66529",  # Compound Governor Bravo
    "uniswap-v3":   "0x408ED6354d4973f66138C91495F2f2FCbd8724C3",  # Uniswap Governor
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
    GovernanceProposal(
        id="snapshot:bootstrap-003",
        protocol="curve",
        title="Curve Fee Switch: Increase admin fee to 50%",
        category="treasury",
        severity="MEDIUM",
        state="active",
        source="bootstrap",
        start_at="2026-05-26T00:00:00Z",
        end_at="2026-05-30T00:00:00Z",
        url="https://snapshot.org/#/curve.eth/proposal/bootstrap-003",
        votes_for=3_100_000,
        votes_against=220_000,
        quorum_met=True,
    ),
    GovernanceProposal(
        id="snapshot:bootstrap-004",
        protocol="lido",
        title="Emergency: Pause stETH withdrawals pending security review",
        category="emergency",
        severity="HIGH",
        state="closed",
        source="bootstrap",
        start_at="2026-05-15T00:00:00Z",
        end_at="2026-05-15T12:00:00Z",
        url="https://snapshot.org/#/lido-snapshot.eth/proposal/bootstrap-004",
        votes_for=5_500_000,
        votes_against=0,
        quorum_met=True,
    ),
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
    GovernanceProposal(
        id="snapshot:bootstrap-006",
        protocol="uniswap-v3",
        title="Deploy Uniswap V3 on zkSync Era",
        category="upgrade",
        severity="MEDIUM",
        state="closed",
        source="bootstrap",
        start_at="2026-05-10T00:00:00Z",
        end_at="2026-05-14T00:00:00Z",
        url="https://snapshot.org/#/uniswap/proposal/bootstrap-006",
        votes_for=42_000_000,
        votes_against=1_200_000,
        quorum_met=True,
    ),
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
    ) -> None:
        self.output_file = Path(output_file)
        self._risk_scores_file = Path(risk_scores_file) if risk_scores_file else None
        self._fallback_used: bool = False
        # ── health-check state (populated by scan_all) ──
        self._snapshot_ok: bool = False
        self._tally_ok: bool = False
        self._snapshot_spaces_ok: int = 0
        self._snapshot_spaces_failed: int = 0
        self._last_live_fetch: Optional[str] = None
        self._last_error: Optional[str] = None

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
                        proposals.extend(active)
                        log.debug("Snapshot %s: ok, %d active proposals",
                                  protocol_key, len(active))
                    else:
                        self._snapshot_spaces_failed += 1
                except Exception as exc:
                    self._snapshot_spaces_failed += 1
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
                        proposals.extend(tally_props)
                        log.debug("Tally %s: ok, %d proposals", protocol_key, len(tally_props))
                except Exception as exc:
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
                "proposals": [p.to_dict() for p in proposals],
                "summary": {
                    "total_proposals": len(proposals),
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
        """
        try:
            return any(
                p.protocol == protocol_key and p.severity == "HIGH" and p.state == "active"
                for p in self.scan_all(offline=offline)
            )
        except Exception:
            return False


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

    proposals = result.get("proposals", [])
    summary   = result.get("summary", {})
    print(f"\n=== SPA Governance Watcher ===")
    print(f"Total proposals:  {summary.get('total_proposals', 0)}")
    print(f"Active:           {summary.get('active_count', 0)}")
    print(f"HIGH severity:    {summary.get('high_severity_count', 0)}")
    print(f"Risk triggers:    {len(summary.get('risk_triggers', []))}")
    print(f"Fetch method:     {result.get('fetch_method', '?')}")
    print(f"Snapshot OK:      {result.get('snapshot_ok', False)} "
          f"({result.get('snapshot_spaces_ok', 0)} ok / "
          f"{result.get('snapshot_spaces_failed', 0)} failed)")
    print(f"Tally OK:         {result.get('tally_ok', False)}")
    print(f"Fallback used:    {result.get('fallback_used', False)}")
    if result.get("last_error"):
        print(f"Last error:       {result.get('last_error')}")
    print()
    print(f"{'Sev':<7} {'State':<8} {'Protocol':<16} {'Category':<18} Title")
    print("-" * 100)
    for p in proposals:
        print(f"{p['severity']:<7} {p['state']:<8} {p['protocol']:<16} {p['category']:<18} {p['title'][:50]}")
