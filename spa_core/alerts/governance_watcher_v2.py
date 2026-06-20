"""
Governance Watcher v2 — Yield Parameter Tracker (Sprint v12.59).

Builds on :mod:`spa_core.alerts.governance_watcher` (v3.18, Snapshot/Tally
scanner).  Where the v1 watcher classifies *all* governance proposals into
broad categories, this module adds a **targeted tracker** for the specific
governance actions that directly move SPA's virtual yields: interest-rate
model / reserve-factor / supply-cap / DSR changes on the protocols SPA holds.

Tracked protocols & parameters
------------------------------
* **Aave**      — "interest rate", "base rate", "slope", "reserve factor"
* **Compound**  — "supply cap", "borrow cap", "interest rate model"
* **Morpho**    — "supply cap", "curve", "apr"
* **Sky/Maker** — "dsr", "savings rate", "dai savings rate"  (DSR changes)

When a matching proposal is detected the tracker:
1. Logs it to ``data/governance_alerts.json`` (atomic write, ring-buffer,
   de-duplicated by proposal id).
2. Sends a Telegram alert
   ``⚠️ GOVERNANCE: [Protocol] proposal may affect yield parameters``
   carrying the title, vote deadline and an estimated APY-impact direction.

APY-impact heuristics (deterministic — no LLM)
----------------------------------------------
* increase reserve factor   → APY likely **DOWN** (protocol takes more)
* decrease reserve factor   → APY likely **UP**
* increase supply cap       → APY likely **DOWN** (more competition)
* decrease supply cap       → APY likely **UP**
* increase DSR/savings rate → APY likely **UP**
* decrease DSR/savings rate → APY likely **DOWN**
* anything else             → **unknown**

Design constraints (inherited from v1)
--------------------------------------
* **Stdlib only** — urllib/json/dataclasses/datetime + the project's
  ``atomic_save`` helper and the Keychain-backed Telegram client.
* **LLM forbidden** — keyword / direction matching only (this is a monitoring
  component; see ``LLM_FORBIDDEN_AGENTS``).
* **Never raises** — ``scan()`` / ``export()`` / ``run()`` catch everything.
* **Atomic writes** — ``data/governance_alerts.json`` via ``atomic_save``.

CLI
---
::

    python -m spa_core.alerts.governance_watcher_v2            # scan + print
    python -m spa_core.alerts.governance_watcher_v2 --write    # + write file
    python -m spa_core.alerts.governance_watcher_v2 --notify   # + Telegram
    python -m spa_core.alerts.governance_watcher_v2 --offline  # bootstrap data
    python -m spa_core.alerts.governance_watcher_v2 --json
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional

from spa_core.alerts.governance_watcher import (
    GovernanceProposal,
    GovernanceWatcher,
    _fetch_snapshot_proposals,
)
from spa_core.utils.atomic import atomic_load, atomic_save

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ALERTS_PATH = _REPO_ROOT / "data" / "governance_alerts.json"

TRACKER_VERSION = "2.0"
_ALERTS_RING_CAP = 200  # keep the last N yield-parameter alerts

# Yield-affecting keyword sets keyed by normalised protocol *family*.
# Matching is case-insensitive substring over (title + body).
YIELD_PARAM_KEYWORDS: dict[str, list[str]] = {
    "aave":     ["interest rate", "base rate", "slope", "reserve factor"],
    "compound": ["supply cap", "borrow cap", "interest rate model"],
    "morpho":   ["supply cap", "curve", "apr"],
    "sky":      ["dsr", "dai savings rate", "savings rate"],
}

# Map the v1 watcher's per-protocol keys (and common aliases) to a family above.
_PROTOCOL_FAMILY: dict[str, str] = {
    "aave-v3":            "aave",
    "aave-v3-arbitrum":   "aave",
    "aave":               "aave",
    "compound-v3":        "compound",
    "compound":           "compound",
    "morpho":             "morpho",
    "morpho-blue":        "morpho",
    "morpho-steakhouse":  "morpho",
    "maker":              "sky",
    "makerdao":           "sky",
    "sky":                "sky",
    "susds":              "sky",
}

# Extra Snapshot spaces (not in the v1 SNAPSHOT_SPACES) needed for full
# yield-parameter coverage.  Morpho + Sky governance live on Snapshot.
YIELD_EXTRA_SPACES: dict[str, str] = {
    "morpho": "morpho.eth",
    "sky":    "sky.eth",
}

# Human-readable protocol labels for the alert text.
_PROTOCOL_LABEL: dict[str, str] = {
    "aave":     "Aave",
    "compound": "Compound",
    "morpho":   "Morpho",
    "sky":      "Sky/MakerDAO",
}

# Direction tokens for the APY-impact heuristic.
_INCREASE_TOKENS = ("increase", "raise", "hike", "bump", "higher", "up to", "increasing")
_DECREASE_TOKENS = ("decrease", "reduce", "lower", "cut", "reducing", "decreasing", "down to")

# (parameter, direction) → APY impact.  Direction is "increase" / "decrease".
_IMPACT_RULES: dict[tuple[str, str], str] = {
    ("reserve factor", "increase"): "down",
    ("reserve factor", "decrease"): "up",
    ("supply cap", "increase"):     "down",
    ("supply cap", "decrease"):     "up",
    ("dsr", "increase"):            "up",
    ("dsr", "decrease"):            "down",
    ("savings rate", "increase"):   "up",
    ("savings rate", "decrease"):   "down",
}


# ---------------------------------------------------------------------------
# Pure helpers (deterministic, no I/O — easy to unit-test)
# ---------------------------------------------------------------------------

def normalize_protocol_family(protocol: str) -> Optional[str]:
    """
    Map a v1 watcher protocol key (or alias) to a tracked yield *family*.

    Returns one of ``aave`` / ``compound`` / ``morpho`` / ``sky``, or
    ``None`` if the protocol is not yield-tracked.
    """
    if not protocol:
        return None
    return _PROTOCOL_FAMILY.get(protocol.strip().lower())


def detect_yield_keywords(family: str, text: str) -> list[str]:
    """
    Return the yield-parameter keywords for *family* that appear in *text*
    (case-insensitive).  Empty list if none / unknown family.
    """
    keywords = YIELD_PARAM_KEYWORDS.get(family, [])
    low = (text or "").lower()
    return [kw for kw in keywords if kw in low]


def _direction(text: str) -> Optional[str]:
    """Infer "increase" / "decrease" from *text*, or ``None`` if ambiguous."""
    low = (text or "").lower()
    inc = any(tok in low for tok in _INCREASE_TOKENS)
    dec = any(tok in low for tok in _DECREASE_TOKENS)
    if inc and not dec:
        return "increase"
    if dec and not inc:
        return "decrease"
    return None  # neither, or both (ambiguous)


def estimate_apy_impact(title: str, body: str = "") -> str:
    """
    Estimate the APY-impact direction of a proposal: ``"up"`` / ``"down"`` /
    ``"unknown"``.

    Deterministic heuristic over the (parameter, direction) rules table.
    The first parameter that both appears in the text *and* has an
    unambiguous direction wins; otherwise ``"unknown"``.
    """
    text = (title + " " + body).lower()
    direction = _direction(text)
    if direction is None:
        return "unknown"
    # Check parameters in a stable priority order.
    for param in ("reserve factor", "supply cap", "dsr", "savings rate"):
        if param in text:
            impact = _IMPACT_RULES.get((param, direction))
            if impact:
                return impact
    return "unknown"


# ---------------------------------------------------------------------------
# Alert data class
# ---------------------------------------------------------------------------

@dataclass
class YieldParameterAlert:
    """A governance proposal flagged as affecting SPA yield parameters."""
    id:               str
    protocol:         str          # original v1 protocol key (e.g. "aave-v3")
    family:           str          # normalised family ("aave"/"compound"/...)
    protocol_label:   str          # human label ("Aave")
    title:            str
    category:         str
    severity:         str
    state:            str
    matched_keywords: list[str]
    apy_impact:       str          # "up" | "down" | "unknown"
    vote_deadline:    str          # ISO-8601 (proposal end_at)
    url:              str
    source:           str
    detected_at:      str = field(
        default_factory=lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    )

    def to_dict(self) -> dict:
        return {
            "id":               self.id,
            "protocol":         self.protocol,
            "family":           self.family,
            "protocol_label":   self.protocol_label,
            "title":            self.title,
            "category":         self.category,
            "severity":         self.severity,
            "state":            self.state,
            "matched_keywords": self.matched_keywords,
            "apy_impact":       self.apy_impact,
            "vote_deadline":    self.vote_deadline,
            "url":              self.url,
            "source":           self.source,
            "detected_at":      self.detected_at,
        }


def proposal_to_alert(proposal: GovernanceProposal) -> Optional[YieldParameterAlert]:
    """
    Convert a v1 ``GovernanceProposal`` to a ``YieldParameterAlert`` if it
    touches a tracked yield parameter, else ``None``.
    """
    family = normalize_protocol_family(getattr(proposal, "protocol", ""))
    if family is None:
        return None
    matched = detect_yield_keywords(family, getattr(proposal, "title", ""))
    if not matched:
        return None
    impact = estimate_apy_impact(getattr(proposal, "title", ""))
    return YieldParameterAlert(
        id=proposal.id,
        protocol=proposal.protocol,
        family=family,
        protocol_label=_PROTOCOL_LABEL.get(family, family.title()),
        title=proposal.title,
        category=getattr(proposal, "category", "unknown"),
        severity=getattr(proposal, "severity", "LOW"),
        state=getattr(proposal, "state", "active"),
        matched_keywords=matched,
        apy_impact=impact,
        vote_deadline=getattr(proposal, "end_at", ""),
        url=getattr(proposal, "url", ""),
        source=getattr(proposal, "source", "unknown"),
    )


def detect_yield_proposals(
    proposals: List[GovernanceProposal],
) -> list[YieldParameterAlert]:
    """
    Filter a list of v1 proposals down to yield-parameter alerts.
    Never raises — bad entries are skipped.
    """
    out: list[YieldParameterAlert] = []
    for p in proposals or []:
        try:
            alert = proposal_to_alert(p)
        except Exception as exc:  # noqa: BLE001 — monitoring must not crash
            log.debug("proposal_to_alert failed: %s", exc)
            alert = None
        if alert is not None:
            out.append(alert)
    return out


def build_telegram_message(alert: YieldParameterAlert) -> str:
    """
    Render the Telegram alert text for a yield-parameter proposal.

    HTML parse_mode (protocol keys contain ``-``/``_`` which break Telegram's
    legacy Markdown; see telegram_client docstring).
    """
    impact_emoji = {"up": "📈 UP", "down": "📉 DOWN", "unknown": "❔ unknown"}
    impact = impact_emoji.get(alert.apy_impact, "❔ unknown")
    kws = ", ".join(alert.matched_keywords) or "—"
    lines = [
        f"⚠️ GOVERNANCE: {alert.protocol_label} proposal may affect yield parameters",
        "",
        f"<b>Title:</b> {alert.title}",
        f"<b>Vote deadline:</b> {alert.vote_deadline}",
        f"<b>Est. APY impact:</b> {impact}",
        f"<b>Matched:</b> {kws}",
        f"<b>State:</b> {alert.state}",
    ]
    if alert.url:
        lines.append(f"<b>Link:</b> {alert.url}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Default Telegram notifier (lazy import keeps tests/offline decoupled)
# ---------------------------------------------------------------------------

def _default_notifier(text: str) -> bool:
    """Send via the Keychain-backed Telegram client. Fail-safe → False."""
    try:
        from spa_core.alerts.telegram_client import send_message
        return bool(send_message(text, parse_mode="HTML"))
    except Exception as exc:  # noqa: BLE001 — alerts must never crash callers
        log.warning("Telegram notify failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# YieldParameterTracker — main class
# ---------------------------------------------------------------------------

class YieldParameterTracker:
    """
    Tracks governance proposals that change protocol parameters directly
    affecting SPA yields (interest-rate models, reserve factors, supply caps,
    DSR).  Persists alerts to ``data/governance_alerts.json`` and pushes a
    Telegram notification per newly-seen proposal.

    All public methods are **guaranteed never to raise**.
    """

    def __init__(
        self,
        alerts_file: str | Path = DEFAULT_ALERTS_PATH,
        *,
        watcher: Optional[GovernanceWatcher] = None,
        notifier: Optional[Callable[[str], bool]] = None,
    ) -> None:
        self.alerts_file = Path(alerts_file)
        self._watcher = watcher or GovernanceWatcher()
        self._notifier = notifier or _default_notifier

    # ------------------------------------------------------------------ #
    # Scanning                                                            #
    # ------------------------------------------------------------------ #

    def _gather_proposals(self, *, offline: bool) -> list[GovernanceProposal]:
        """
        Collect proposals from the v1 watcher plus the extra Morpho/Sky
        Snapshot spaces.  Never raises.
        """
        proposals: list[GovernanceProposal] = []
        try:
            proposals.extend(self._watcher.scan_all(offline=offline))
        except Exception as exc:  # noqa: BLE001
            log.warning("v1 scan_all failed: %s", exc)

        if not offline:
            for family, space in YIELD_EXTRA_SPACES.items():
                try:
                    ok, extra = _fetch_snapshot_proposals(family, space, state="active")
                    if ok:
                        proposals.extend(extra)
                except Exception as exc:  # noqa: BLE001
                    log.debug("extra space %s/%s failed: %s", family, space, exc)
        return proposals

    def scan(
        self,
        *,
        offline: bool = False,
        proposals: Optional[List[GovernanceProposal]] = None,
    ) -> list[YieldParameterAlert]:
        """
        Return yield-parameter alerts.  If *proposals* is given it is used
        directly (no network); otherwise proposals are gathered live/offline.
        NEVER raises.
        """
        try:
            if proposals is None:
                proposals = self._gather_proposals(offline=offline)
            alerts = detect_yield_proposals(proposals)
            # De-duplicate by id, keep first occurrence.
            seen: set[str] = set()
            unique: list[YieldParameterAlert] = []
            for a in alerts:
                if a.id not in seen:
                    seen.add(a.id)
                    unique.append(a)
            return unique
        except Exception as exc:  # noqa: BLE001
            log.error("YieldParameterTracker.scan failed: %s", exc)
            return []

    # ------------------------------------------------------------------ #
    # Persistence + notification                                          #
    # ------------------------------------------------------------------ #

    def _load_existing(self) -> dict:
        """Load the current alerts file, tolerating missing/corrupt files."""
        try:
            data = atomic_load(str(self.alerts_file), {})
            return data if isinstance(data, dict) else {}
        except Exception as exc:  # noqa: BLE001
            log.debug("load governance_alerts.json failed (expected first run): %s", exc)
            return {}

    def export(
        self,
        *,
        dry_run: bool = True,
        offline: bool = False,
        notify: bool = False,
        proposals: Optional[List[GovernanceProposal]] = None,
    ) -> dict:
        """
        Scan, merge with the existing alert log (de-dup by id), optionally
        write the file and/or send Telegram alerts for *new* proposals.

        Returns the full alerts dict.  NEVER raises.
        """
        try:
            alerts = self.scan(offline=offline, proposals=proposals)

            existing = self._load_existing()
            prior = existing.get("alerts", [])
            if not isinstance(prior, list):
                prior = []
            known_ids = {a.get("id") for a in prior if isinstance(a, dict)}

            new_alerts = [a for a in alerts if a.id not in known_ids]

            # Send Telegram for new proposals (only when asked).
            notified = 0
            if notify:
                for a in new_alerts:
                    try:
                        if self._notifier(build_telegram_message(a)):
                            notified += 1
                    except Exception as exc:  # noqa: BLE001
                        log.warning("notify failed for %s: %s", a.id, exc)

            # Merge: prior records + new alert dicts, ring-buffer capped.
            merged = prior + [a.to_dict() for a in new_alerts]
            if len(merged) > _ALERTS_RING_CAP:
                merged = merged[-_ALERTS_RING_CAP:]

            by_impact: dict[str, int] = {}
            by_protocol: dict[str, int] = {}
            for a in alerts:
                by_impact[a.apy_impact] = by_impact.get(a.apy_impact, 0) + 1
                by_protocol[a.family] = by_protocol.get(a.family, 0) + 1

            result = {
                "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "tracker_version": TRACKER_VERSION,
                "alerts": merged,
                "summary": {
                    "current_scan_alerts": len(alerts),
                    "new_alerts":          len(new_alerts),
                    "notified":            notified,
                    "total_logged":        len(merged),
                    "by_impact":           by_impact,
                    "by_protocol":         by_protocol,
                },
            }

            if not dry_run:
                atomic_save(result, str(self.alerts_file))
                log.info("Yield-parameter alerts written to %s (%d new)",
                         self.alerts_file, len(new_alerts))
            return result
        except Exception as exc:  # noqa: BLE001
            log.error("YieldParameterTracker.export failed: %s", exc)
            return {"error": str(exc), "alerts": []}

    def run(self, *, offline: bool = False) -> dict:
        """Convenience: scan, write the file, and send Telegram alerts."""
        return self.export(dry_run=False, offline=offline, notify=True)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_default_tracker: Optional[YieldParameterTracker] = None


def get_tracker() -> YieldParameterTracker:
    """Return (and lazily create) the module-level singleton tracker."""
    global _default_tracker
    if _default_tracker is None:
        _default_tracker = YieldParameterTracker()
    return _default_tracker


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    parser = argparse.ArgumentParser(description="SPA Governance Watcher v2 — Yield Parameter Tracker")
    parser.add_argument("--offline", action="store_true", help="Use bootstrap data only")
    parser.add_argument("--json",    action="store_true", help="Print JSON output")
    parser.add_argument("--write",   action="store_true", help="Write governance_alerts.json")
    parser.add_argument("--notify",  action="store_true", help="Send Telegram alerts for new proposals")
    args = parser.parse_args()

    tracker = YieldParameterTracker()
    result = tracker.export(dry_run=not args.write, offline=args.offline, notify=args.notify)

    if args.json:
        print(json.dumps(result, indent=2))
        sys.exit(0)

    summary = result.get("summary", {})
    alerts = result.get("alerts", [])
    print("\n=== SPA Governance Watcher v2 — Yield Parameter Tracker ===")
    print(f"Current-scan alerts: {summary.get('current_scan_alerts', 0)}")
    print(f"New this run:        {summary.get('new_alerts', 0)}")
    print(f"Notified:            {summary.get('notified', 0)}")
    print(f"Total logged:        {summary.get('total_logged', 0)}")
    print(f"By impact:           {summary.get('by_impact', {})}")
    print(f"By protocol:         {summary.get('by_protocol', {})}")
    print()
    print(f"{'Impact':<9} {'Protocol':<14} {'State':<8} Title")
    print("-" * 90)
    for a in alerts[-20:]:
        print(f"{a.get('apy_impact',''):<9} {a.get('family',''):<14} "
              f"{a.get('state',''):<8} {a.get('title','')[:50]}")
