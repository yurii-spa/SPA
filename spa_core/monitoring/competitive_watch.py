"""
competitive_watch.py — SPA Competitive Early-Warning Monitor (Proof-of-Risk WS-E).

The moat-defense radar for the competitive report's Section-7 watch-thresholds.
It encodes each Section-7 trigger as a tracked SIGNAL with a deterministic state
(SAFE / WATCH / BREACHED), an ``as_of`` date, and traceable ``evidence``.

WHY THIS MODULE EXISTS
  A competitive report identified the strongest 12-24mo threat to SPA's white
  space (a transparent personal-capital DeFi risk desk with a public refusal log,
  Liquidation-NAV-by-size, and deterministic anti-AI). It named three encroachment
  vectors and the early-warning thresholds that would mean SPA's moat is closing:

    (a) Exponential.fi / YO (Paradigm-backed) adds a public refusal-log OR an
        exit-NAV-by-size product           → DIRECT competition.
    (b) Chaos Labs / Gauntlet / Credora ships an INVESTOR-FACING exit-NAV product
                                            → category commoditization.
    (c) Kraken / Coinbase / Binance adds risk-rationale transparency to retail
                                            → mass-retail encroachment.

DESIGN RULES (per CLAUDE.md + the WS-E quality bar)
  * stdlib only — no third-party imports.
  * deterministic — same inputs → byte-identical output (sorted keys, no clocks
    inside the state computation; ``as_of``/``generated_at`` are explicit inputs).
  * atomic writes — via spa_core.utils.atomic.atomic_save (tmp + os.replace).
  * fail-CLOSED — an unknown / unsourced / ambiguous / spoofed signal degrades to
    WATCH, NEVER to a silent SAFE. We never fabricate a competitor's state.
  * monitoring component → LLM FORBIDDEN.
  * HONEST inputs — auto-sourceable signals carry a dated, sourced ``evidence``;
    everything we cannot honestly auto-source is ``manual_pending`` (explicit),
    NOT an invented competitor feature.

STATE VOCABULARY (mirrors the existing monitors' SAFE/WARNING/CRITICAL spirit,
specialized for a watch-threshold):
  * SAFE     — sourced, dated evidence shows the threshold is NOT breached.
  * WATCH    — fail-closed default: unknown / unsourced / manual-pending / spoofed
               / ambiguous input. "We cannot prove SAFE, so we watch."
  * BREACHED — sourced, dated evidence shows the threshold IS breached
               (the competitor shipped the watched capability).

MONOTONIC-HONEST INVARIANT
  A signal that was BREACHED with sourced evidence may only return to a lower
  state via a *sourced* change (an explicit retraction with its own evidence).
  Absence of new input never silently downgrades a sourced BREACHED back to SAFE —
  see ``reconcile_with_previous``.

CLI:
    python3 -m spa_core.monitoring.competitive_watch --check   # compute+write+print
    python3 -m spa_core.monitoring.competitive_watch --run     # +alert on new BREACH
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

log = logging.getLogger("spa.monitoring.competitive_watch")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
# Honor SPA_DATA_DIR so the pre-deploy gate (which exports a sandbox SPA_DATA_DIR)
# redirects this monitor's writes into the sandbox — never the canonical data/.
_DEFAULT_DATA_DIR = Path(os.environ.get("SPA_DATA_DIR", _PROJECT_ROOT / "data"))
_OUTPUT_FILENAME = "competitive_watch.json"
# Optional honest signal-input file. Owner / a future auto-sourcer drops sourced,
# dated observations here; absent → every signal is its fail-closed default.
_SIGNAL_INPUT_FILENAME = "competitive_signals_input.json"

# ---------------------------------------------------------------------------
# State constants (ordered by escalation severity)
# ---------------------------------------------------------------------------
SAFE = "SAFE"
WATCH = "WATCH"
BREACHED = "BREACHED"
_SEVERITY = {SAFE: 0, WATCH: 1, BREACHED: 2}

# How a raw observation's discrete verdict maps onto a signal state. Anything we
# do not recognise as an explicit, sourced SAFE/BREACHED is fail-closed to WATCH.
_VERDICT_TO_STATE = {
    "safe": SAFE,
    "not_breached": SAFE,
    "clear": SAFE,
    "breached": BREACHED,
    "shipped": BREACHED,
    "launched": BREACHED,
    "live": BREACHED,
}


def _worst(*states: str) -> str:
    """Highest-severity state among args (BREACHED > WATCH > SAFE)."""
    return max(states, key=lambda s: _SEVERITY.get(s, 1)) if states else SAFE


# ===========================================================================
# Section-7 watch-threshold catalogue (the coded triggers).
# Each is a stable, coded check id. ``auto_sourceable=False`` means we cannot
# honestly machine-source it without a live competitor-product scraper → it is
# manual_pending until a sourced observation is supplied. We deliberately do NOT
# build a fake scraper: an unsourced signal is honestly WATCH, never SAFE.
# ===========================================================================
@dataclass(frozen=True)
class Threshold:
    signal_id: str
    category: str                # the report's encroachment vector (a/b/c)
    competitors: Tuple[str, ...]
    description: str
    breach_meaning: str          # what a BREACH would mean for SPA's moat
    auto_sourceable: bool = False


# Section-7 triggers, in stable report order. Tuple → deterministic iteration.
SECTION7_THRESHOLDS: Tuple[Threshold, ...] = (
    Threshold(
        signal_id="exponential_yo_refusal_log",
        category="a_direct_competition",
        competitors=("Exponential.fi", "YO"),
        description=(
            "Exponential.fi / YO (Paradigm-backed) publishes a public REFUSAL LOG "
            "of declined yield opportunities with rationale."
        ),
        breach_meaning=(
            "DIRECT competition: SPA's public refusal log stops being unique."
        ),
        auto_sourceable=False,
    ),
    Threshold(
        signal_id="exponential_yo_exit_nav",
        category="a_direct_competition",
        competitors=("Exponential.fi", "YO"),
        description=(
            "Exponential.fi / YO adds a Liquidation/exit-NAV-BY-SIZE surface "
            "(size-tiered conservative unwind proceeds)."
        ),
        breach_meaning=(
            "DIRECT competition: SPA's exit-NAV-by-size stops being unique."
        ),
        auto_sourceable=False,
    ),
    Threshold(
        signal_id="chaos_gauntlet_investor_exit_nav",
        category="b_category_commoditization",
        competitors=("Chaos Labs", "Gauntlet", "Credora"),
        description=(
            "A risk-engine vendor (Chaos Labs / Gauntlet / Credora) ships an "
            "INVESTOR-FACING exit-NAV product (not just protocol-facing risk params)."
        ),
        breach_meaning=(
            "Category commoditization: exit-NAV-by-size becomes a buyable vendor "
            "feature rather than a differentiator."
        ),
        auto_sourceable=False,
    ),
    Threshold(
        signal_id="kraken_coinbase_risk_rationale",
        category="c_mass_retail_encroachment",
        competitors=("Kraken", "Coinbase", "Binance"),
        description=(
            "A mass-retail venue (Kraken / Coinbase / Binance) adds per-asset "
            "RISK-RATIONALE transparency to its retail yield/earn product."
        ),
        breach_meaning=(
            "Mass-retail encroachment: transparent risk rationale reaches retail "
            "at scale, eroding SPA's transparency edge for the $100K-$5M segment."
        ),
        auto_sourceable=False,
    ),
)

_THRESHOLDS_BY_ID: Dict[str, Threshold] = {t.signal_id: t for t in SECTION7_THRESHOLDS}


# ===========================================================================
# Signal (the evaluated state of one threshold)
# ===========================================================================
@dataclass
class Signal:
    signal_id: str
    category: str
    competitors: List[str]
    description: str
    breach_meaning: str
    state: str = WATCH
    as_of: Optional[str] = None          # date of the sourced observation (ISO)
    evidence: Optional[str] = None       # human-traceable source / note
    source_url: Optional[str] = None
    manual_pending: bool = True          # True ⟺ no sourced observation yet
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "signal_id": self.signal_id,
            "category": self.category,
            "competitors": list(self.competitors),
            "description": self.description,
            "breach_meaning": self.breach_meaning,
            "state": self.state,
            "as_of": self.as_of,
            "evidence": self.evidence,
            "source_url": self.source_url,
            "manual_pending": bool(self.manual_pending),
            "note": self.note,
        }


# ===========================================================================
# Observation normalization — the fail-CLOSED heart of E2.
# Turns a raw input record into a (state, fields) verdict, degrading anything
# unknown / ambiguous / spoofed to WATCH and NEVER fabricating a SAFE.
# ===========================================================================
def normalize_observation(obs: Optional[dict]) -> Tuple[str, dict]:
    """Map a raw observation dict → (state, evidence_fields). Fail-CLOSED.

    A valid observation is a dict carrying a recognised ``verdict`` AND, when it
    claims SAFE or BREACHED, a sourced (``as_of`` + ``evidence``) basis. Anything
    missing / malformed / unrecognised / internally-contradictory degrades to
    WATCH with a reason — we never let an under-specified or spoofed record assert
    SAFE (the adversarial requirement).

    Returns (state, {as_of, evidence, source_url, manual_pending, note}).
    """
    base = {
        "as_of": None,
        "evidence": None,
        "source_url": None,
        "manual_pending": True,
        "note": "",
    }

    if obs is None:
        base["note"] = "no observation supplied — fail-closed to WATCH"
        return WATCH, base
    if not isinstance(obs, dict):
        base["note"] = "malformed observation (not an object) — fail-closed to WATCH"
        return WATCH, base

    raw_verdict = obs.get("verdict")
    verdict = str(raw_verdict).strip().lower() if raw_verdict is not None else ""
    as_of = obs.get("as_of")
    evidence = obs.get("evidence")
    source_url = obs.get("source_url")

    # An explicitly manual-pending record stays WATCH and is honestly labeled —
    # never coerced to SAFE.
    if obs.get("manual_pending") is True or verdict in ("", "manual_pending", "pending", "unknown"):
        base["note"] = "manual_pending: no sourced observation yet — WATCH (not SAFE)"
        return WATCH, base

    mapped = _VERDICT_TO_STATE.get(verdict)
    if mapped is None:
        # Unrecognised / spoofed verdict string → fail-closed.
        base["note"] = f"unrecognised verdict {raw_verdict!r} — fail-closed to WATCH"
        return WATCH, base

    # A SAFE or BREACHED claim MUST be sourced: both a date and evidence. An
    # unsourced positive claim is exactly the spoof we degrade to WATCH.
    sourced = bool(_valid_date(as_of)) and bool(evidence and str(evidence).strip())
    if not sourced:
        base["note"] = (
            f"verdict {verdict!r} lacks sourced as_of+evidence — fail-closed to WATCH "
            "(never assert a competitor state without a source)"
        )
        return WATCH, base

    fields = {
        "as_of": str(as_of),
        "evidence": str(evidence).strip(),
        "source_url": (str(source_url).strip() if source_url else None),
        "manual_pending": False,
        "note": obs.get("note", "") or "",
    }
    return mapped, fields


def _valid_date(value) -> bool:
    """True iff value is an ISO date/datetime string we can parse. Fail-closed."""
    if not value or not isinstance(value, str):
        return False
    s = value.strip().replace("Z", "+00:00")
    try:
        datetime.fromisoformat(s)
        return True
    except ValueError:
        # Accept bare YYYY-MM-DD too (fromisoformat handles it on 3.11+, but be safe).
        try:
            datetime.strptime(value.strip()[:10], "%Y-%m-%d")
            return True
        except ValueError:
            return False


# ===========================================================================
# Build one signal from the threshold + (optional) sourced observation.
# ===========================================================================
def evaluate_signal(threshold: Threshold, observation: Optional[dict]) -> Signal:
    """Evaluate a single Section-7 threshold against its observation. Fail-CLOSED."""
    state, fields = normalize_observation(observation)
    return Signal(
        signal_id=threshold.signal_id,
        category=threshold.category,
        competitors=list(threshold.competitors),
        description=threshold.description,
        breach_meaning=threshold.breach_meaning,
        state=state,
        as_of=fields["as_of"],
        evidence=fields["evidence"],
        source_url=fields["source_url"],
        manual_pending=fields["manual_pending"],
        note=fields["note"],
    )


# ===========================================================================
# Monotonic-honest reconciliation against the previous published report.
# A sourced BREACHED must not silently revert to SAFE/WATCH without a *sourced*
# change. If the new input is unsourced (→WATCH) but we previously had a sourced
# BREACHED for that signal, we KEEP the BREACHED (carry the prior sourced
# evidence) and annotate that no sourced retraction was seen.
# ===========================================================================
def reconcile_with_previous(current: List[Signal],
                            previous: Optional[dict]) -> List[Signal]:
    """Enforce monotonic-honesty against the prior report. Returns adjusted signals."""
    if not previous or not isinstance(previous, dict):
        return current
    prev_by_id: Dict[str, dict] = {}
    for s in previous.get("signals", []):
        if isinstance(s, dict) and s.get("signal_id"):
            prev_by_id[s["signal_id"]] = s

    out: List[Signal] = []
    for sig in current:
        prev = prev_by_id.get(sig.signal_id)
        if (
            prev
            and prev.get("state") == BREACHED
            and not prev.get("manual_pending", True)   # prior breach was SOURCED
            and sig.state != BREACHED
        ):
            # A non-sourced downgrade is suspicious. Only a SOURCED retraction may
            # lower a sourced breach. The current signal is sourced only when it
            # is itself not manual_pending. If the new input is unsourced, hold.
            if sig.manual_pending or sig.state == WATCH:
                sig.state = BREACHED
                sig.as_of = prev.get("as_of")
                sig.evidence = prev.get("evidence")
                sig.source_url = prev.get("source_url")
                sig.manual_pending = False
                sig.note = (
                    "HELD at sourced BREACHED (no sourced retraction seen; "
                    "monotonic-honest — a breach cannot silently revert to SAFE)"
                )
        out.append(sig)
    return out


# ===========================================================================
# Honest signal feed (E2): load sourced observations, never invent them.
# ===========================================================================
def load_signal_inputs(data_dir: Path) -> Dict[str, dict]:
    """Load sourced observations keyed by signal_id from the optional input file.

    The file is owner/auto-sourcer-supplied. Its absence is the NORMAL state →
    every signal is its fail-closed manual_pending WATCH. We never synthesize an
    observation here. Malformed file → empty (fail-closed: nothing becomes SAFE).
    """
    path = Path(data_dir) / _SIGNAL_INPUT_FILENAME
    if not path.exists():
        return {}
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("competitive signal input unreadable (%s) — fail-closed to none", exc)
        return {}
    obs = doc.get("observations") if isinstance(doc, dict) else None
    if not isinstance(obs, dict):
        return {}
    # Keep only entries for known threshold ids; ignore unknown ids (don't trust
    # an input file to introduce signals the code doesn't define).
    return {k: v for k, v in obs.items() if k in _THRESHOLDS_BY_ID and isinstance(v, dict)}


# ===========================================================================
# Report assembly
# ===========================================================================
def build_report(signals: List[Signal], generated_at: str) -> dict:
    counts = {SAFE: 0, WATCH: 0, BREACHED: 0}
    for s in signals:
        counts[s.state] = counts.get(s.state, 0) + 1
    overall = _worst(*[s.state for s in signals]) if signals else SAFE
    manual_pending = sorted(s.signal_id for s in signals if s.manual_pending)
    breached = sorted(s.signal_id for s in signals if s.state == BREACHED)
    # Deterministic: signals sorted by stable signal_id.
    ordered = sorted(signals, key=lambda s: s.signal_id)
    return {
        "schema": "spa.competitive_watch.v1",
        "model": "section7_watch_thresholds",
        "generated_at": generated_at,
        "overall_state": overall,
        "counts": counts,
        "n_signals": len(signals),
        "n_breached": len(breached),
        "breached_ids": breached,
        "manual_pending_ids": manual_pending,
        "white_space": (
            "transparent personal-capital ($100K-$5M) DeFi risk desk: public "
            "refusal log + Liquidation-NAV-by-size + deterministic anti-AI"
        ),
        "fail_closed_note": (
            "Unknown/unsourced/ambiguous/spoofed input degrades to WATCH, never a "
            "silent SAFE. Competitor states are never fabricated. manual_pending "
            "signals have no auto-source and await a sourced observation."
        ),
        "public_naming_owner_gated": True,
        "is_internal_surface": True,
        "signals": [s.to_dict() for s in ordered],
    }


# ===========================================================================
# Alert decision — fire ONLY on a NEW transition to BREACHED.
# ===========================================================================
def newly_breached(current: dict, previous: Optional[dict]) -> List[str]:
    """Signal ids that are BREACHED now but were NOT BREACHED in the prior report."""
    prev_state: Dict[str, str] = {}
    for s in (previous or {}).get("signals", []):
        if isinstance(s, dict) and s.get("signal_id"):
            prev_state[s["signal_id"]] = s.get("state", WATCH)
    out = []
    for s in current.get("signals", []):
        if s.get("state") == BREACHED and prev_state.get(s["signal_id"]) != BREACHED:
            out.append(s["signal_id"])
    return sorted(out)


def format_alert(report: dict, new_ids: List[str]) -> str:
    """HTML Telegram alert for newly-breached watch thresholds (internal-only)."""
    by_id = {s["signal_id"]: s for s in report.get("signals", [])}
    lines = [
        "🛰️ <b>SPA Competitive Watch — BREACH</b>",
        f"{len(new_ids)} Section-7 threshold(s) newly BREACHED:",
        "",
    ]
    for sid in new_ids:
        s = by_id.get(sid, {})
        comps = ", ".join(s.get("competitors", []))
        lines.append(f"❗ <b>{sid}</b> ({comps})")
        lines.append(f"   {s.get('breach_meaning', '')}")
        if s.get("evidence"):
            lines.append(f"   source: {s.get('evidence')} ({s.get('as_of')})")
        lines.append("")
    lines.append("<i>internal surface — public competitor naming is owner-gated</i>")
    return "\n".join(lines)


def _push_breach(report: dict, new_ids: List[str]) -> bool:
    """Route a NEW breach through the single push authority. Fail-safe."""
    if not new_ids:
        return False
    try:
        from spa_core.telegram import push_policy
    except Exception as exc:  # noqa: BLE001
        log.warning("push_policy import failed: %s", exc)
        return False
    try:
        return bool(
            push_policy.push_critical(
                "competitive_watch_breach",
                "CRITICAL",
                "SPA Competitive Watch — BREACH",
                format_alert(report, new_ids),
            )
        )
    except Exception as exc:  # noqa: BLE001 — never raise out of the monitor
        log.warning("competitive watch push failed: %s", exc)
        return False


# ===========================================================================
# Orchestration
# ===========================================================================
def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class CompetitiveWatchMonitor:
    """Deterministic Section-7 watch-threshold monitor. Fail-closed, atomic."""

    def __init__(self,
                 data_dir: Path = _DEFAULT_DATA_DIR,
                 generated_at: Optional[str] = None):
        self.data_dir = Path(data_dir)
        # generated_at is injectable so a re-run with the same stamp is
        # byte-identical (the determinism contract). Default = now (UTC).
        self.generated_at = generated_at or _utcnow_iso()

    def _previous(self) -> Optional[dict]:
        p = self.data_dir / _OUTPUT_FILENAME
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def collect(self, previous: Optional[dict] = None) -> dict:
        """Build the report (read-only). Deterministic for fixed inputs+stamp."""
        observations = load_signal_inputs(self.data_dir)
        signals = [
            evaluate_signal(t, observations.get(t.signal_id))
            for t in SECTION7_THRESHOLDS
        ]
        signals = reconcile_with_previous(signals, previous)
        return build_report(signals, self.generated_at)

    def run(self, send: bool = True) -> dict:
        """Full cycle: collect → reconcile → (alert on new breach) → atomic write."""
        try:
            previous = self._previous()
            report = self.collect(previous=previous)
            new_ids = newly_breached(report, previous)
            report["new_breaches"] = new_ids
            report["alert_sent"] = False
            if send and new_ids:
                report["alert_sent"] = bool(_push_breach(report, new_ids))
            self._write(report)
            return report
        except Exception as exc:  # noqa: BLE001 — never raise out of run()
            log.exception("competitive_watch run failed: %s", exc)
            return {
                "schema": "spa.competitive_watch.v1",
                "generated_at": self.generated_at,
                "overall_state": WATCH,   # fail-closed: error → WATCH, not SAFE
                "error": str(exc),
            }

    def _write(self, report: dict) -> None:
        from spa_core.utils.atomic import atomic_save
        # sort_keys for byte-stable output is handled by ordering signals + the
        # fixed key insertion order; atomic_save uses indent=2.
        atomic_save(report, str(self.data_dir / _OUTPUT_FILENAME))


# ===========================================================================
# CLI
# ===========================================================================
def _print_summary(report: dict) -> None:
    print(f"Overall: {report.get('overall_state')}  "
          f"(SAFE={report.get('counts', {}).get(SAFE)} "
          f"WATCH={report.get('counts', {}).get(WATCH)} "
          f"BREACHED={report.get('counts', {}).get(BREACHED)} "
          f"/ {report.get('n_signals')} signals)")
    for s in report.get("signals", []):
        tag = "manual_pending" if s.get("manual_pending") else "sourced"
        line = f"  [{s.get('state')}] {s.get('signal_id')} ({tag})"
        if s.get("as_of"):
            line += f" as_of={s.get('as_of')}"
        print(line)
    if report.get("new_breaches"):
        print(f"  NEW BREACHES: {report['new_breaches']}")
    if report.get("alert_sent"):
        print("  telegram alert: SENT")


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(
        description="SPA competitive early-warning monitor (Section-7 watch thresholds)")
    g = parser.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true",
                   help="compute + write competitive_watch.json + print, NO telegram")
    g.add_argument("--run", action="store_true",
                   help="compute + write + alert on NEW breach")
    parser.add_argument("--data-dir", default=str(_DEFAULT_DATA_DIR))
    parser.add_argument("--generated-at", default=None,
                        help="ISO timestamp override (for deterministic re-runs)")
    args = parser.parse_args(argv)

    send = bool(args.run)
    monitor = CompetitiveWatchMonitor(
        data_dir=Path(args.data_dir),
        generated_at=args.generated_at,
    )
    report = monitor.run(send=send)
    _print_summary(report)
    return 0  # always exit 0 (fail-safe daemon)


if __name__ == "__main__":
    sys.exit(main())
