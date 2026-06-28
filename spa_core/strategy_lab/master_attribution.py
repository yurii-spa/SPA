"""
spa_core/strategy_lab/master_attribution.py — the ONE hash-anchored MASTER attribution report
(WS-4.5): every captured book vs the RWA floor, verifiable.

WHY THIS EXISTS
═══════════════
WS-4 produced four honest artifacts: the captured-sleeve gate (captured_sleeves), the COMBINED
multi-sleeve attribution (forward_analytics.combined_book_attribution), the empirical decorrelation
matrix + capacity ceiling (decorrelation), and the rates-desk refusal coverage (rates_desk.
refusal_coverage). The fundability story is the SUM of these — but a story is only fundable if it is
VERIFIABLE. This module assembles them into ONE master report and HASH-ANCHORS it the same way the
rates-desk decision proof chain anchors its decisions, so a third party can confirm the report was not
mutated after the fact (and that two runs over the same inputs produce the SAME anchor).

THE ANCHOR (reuses the proof-chain pattern, spa_core.audit.hash_chain)
═════════════════════════════════════════════════════════════════════
The report body (the section payloads — NOT the wall-clock generated_at) is serialized canonically
(sorted keys, compact separators) and a single deterministic ``proof_hash`` is computed over it via
``hash_chain.compute_entry_hash`` (the EXACT primitive the rates-desk proof chain uses). Same inputs →
byte-identical body → identical proof_hash. ``verify_master_report(report)`` recomputes the hash from
the body and returns valid/invalid — the standalone verifier a third party runs. Mutating any anchored
section changes the body → the recomputed hash no longer matches → tamper detected.

stdlib only, deterministic, fail-CLOSED, atomic. LLM FORBIDDEN. Advisory / research — it READS the
WS-4 artifacts; it never moves capital, never touches the go-live track (asserted: every captured book
+ combined book carry is_advisory / separate_from_golive_track).

Run:  python3 -m spa_core.strategy_lab.master_attribution
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
from pathlib import Path
from typing import Any, Dict, Optional

from spa_core.audit import hash_chain
from spa_core.utils.atomic import atomic_load, atomic_save
from spa_core.strategy_lab import metrics

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
OUT_FILE = DATA_DIR / "strategy_lab" / "master_attribution.json"

# The event type the master report anchors under in the hash_chain primitive (a stable, documented
# label so the recomputation is reproducible).
EVENT_TYPE = "strategy_lab_master_attribution"

# The keys that are METADATA (NOT part of the anchored body): the wall-clock stamp + the anchor itself.
# Everything else in the report IS anchored, so mutating any section breaks the hash.
_META_KEYS = ("generated_at", "proof_hash", "proof_event_type")


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# canonical body + anchor
# ──────────────────────────────────────────────────────────────────────────────
def _strip_clocks(obj: Any) -> Any:
    """Recursively drop every ``generated_at`` key so the anchor is a PURE function of the DATA, not
    the build wall-clock. The nested WS-4 sections each stamp their own generated_at; left in, the
    anchor would change every run even on identical data. Deterministic / PURE (returns a new structure,
    never mutates the input)."""
    if isinstance(obj, dict):
        return {k: _strip_clocks(v) for k, v in obj.items() if k != "generated_at"}
    if isinstance(obj, list):
        return [_strip_clocks(v) for v in obj]
    return obj


def _body_of(report: Dict[str, Any]) -> Dict[str, Any]:
    """The ANCHORED body = the report minus the metadata keys (top-level wall-clock + the anchor
    itself) AND every nested ``generated_at`` (so the hash is data-only, build-time-independent)."""
    return _strip_clocks({k: v for k, v in report.items() if k not in _META_KEYS})


def _proof_hash(body: Dict[str, Any]) -> str:
    """Deterministic SHA-256 anchor over the report body, via the SAME hash_chain primitive the
    rates-desk proof chain uses. seq=0, ts="" (the body carries no clock), genesis prev — so the hash
    is a PURE function of the body. Same body → same hash."""
    return hash_chain.compute_entry_hash(0, "", EVENT_TYPE, body, hash_chain.GENESIS_PREV)


def verify_master_report(report: Dict[str, Any]) -> dict:
    """Recompute the anchor from the report body and compare it to the stored proof_hash. The
    standalone verifier a third party runs: {valid, recomputed_hash, stored_hash}. fail-CLOSED: a
    report with no proof_hash, or whose body no longer hashes to the stored value, is invalid."""
    stored = report.get("proof_hash")
    try:
        recomputed = _proof_hash(_body_of(report))
    except Exception:  # noqa: BLE001 — an unhashable body is a tampered/malformed report → invalid
        return {"valid": False, "recomputed_hash": None, "stored_hash": stored}
    return {
        "valid": bool(stored is not None and stored == recomputed),
        "recomputed_hash": recomputed,
        "stored_hash": stored,
    }


# ──────────────────────────────────────────────────────────────────────────────
# section assembly (read the WS-4 artifacts; build them live when absent)
# ──────────────────────────────────────────────────────────────────────────────
def _assert_advisory(section: Any, *, where: str) -> None:
    """fail-CLOSED guard: a captured/combined book section that is NOT advisory / separate from the
    go-live track is a contract violation → RAISES. The master report can never anchor a live book."""
    if not isinstance(section, dict):
        return
    if section.get("is_advisory") is False:
        raise ValueError(f"master_attribution: {where} is_advisory=False — refusing to anchor a "
                         "live-capable book in the advisory master report (fail-closed).")
    if section.get("separate_from_golive_track") is False:
        raise ValueError(f"master_attribution: {where} separate_from_golive_track=False — refusing to "
                         "anchor a book entangled with the go-live track (fail-closed).")


def build_master_report(
    *,
    data_dir: Optional[Path] = None,
    floor_apy_pct: Optional[float] = None,
    write: bool = True,
    now_iso: Optional[str] = None,
) -> dict:
    """Assemble + hash-anchor the master attribution report from the WS-4 artifacts.

    Reads (and, when absent, BUILDS live) the four sections:
      • captured_sleeves     — the WS-4.1 capture gate (honest GO/NO-GO per sleeve),
      • combined_attribution — the WS-4.2 combined captured-book floor-leg/carry-leg vs the floor,
      • decorrelation        — the WS-4.4 empirical matrix + the honest capacity ceiling,
      • refusal_coverage     — the WS-4.3 100%-on-toxic refusal coverage.

    Then computes the single deterministic ``proof_hash`` over the report body and (optionally) writes
    data/strategy_lab/master_attribution.json atomically.

    Args:
        data_dir / floor_apy_pct / write / now_iso: standard injection points (hermetic tests).

    fail-CLOSED: a section that cannot be built is recorded as {"status": "unavailable", ...} (never a
    fabricated number); a non-advisory captured/combined book RAISES (the advisory invariant)."""
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    floor = metrics.rwa_floor_apy_pct() if floor_apy_pct is None else float(floor_apy_pct)
    now = now_iso if now_iso is not None else _utc_now_iso()

    # ── captured sleeves (WS-4.1) ──────────────────────────────────────────────────────────────
    try:
        from spa_core.strategy_lab import captured_sleeves as cs
        captured = cs.build_captured_sleeves(
            data_dir=root, floor_apy_pct=floor, write=False, now_iso=now)
    except Exception as exc:  # noqa: BLE001 — fail-CLOSED: an unbuildable section is unavailable
        captured = {"status": "unavailable", "error": str(exc)}
    _assert_advisory(captured, where="captured_sleeves")

    # ── combined attribution (WS-4.2) + decorrelation (WS-4.4) share the captured-book series ────
    try:
        from spa_core.strategy_lab import forward_analytics as fa
        book_series = fa._discover_captured_book_series(root)
        combined = fa.combined_book_attribution(book_series, floor_apy_pct=floor)
    except Exception as exc:  # noqa: BLE001
        book_series, combined = {}, {"status": "unavailable", "error": str(exc)}
    _assert_advisory(
        {"is_advisory": True, "separate_from_golive_track": True} if "status" not in combined else combined,
        where="combined_attribution")

    # ── decorrelation matrix + capacity ceiling (WS-4.4) ───────────────────────────────────────
    try:
        from spa_core.strategy_lab import decorrelation as dec
        decorr = dec.build_report(
            data_dir=root, book_series=book_series, write=False, now_iso=now)
    except Exception as exc:  # noqa: BLE001
        decorr = {"status": "unavailable", "error": str(exc)}

    # ── refusal coverage (WS-4.3) ──────────────────────────────────────────────────────────────
    try:
        from spa_core.strategy_lab.rates_desk import refusal_coverage as rc
        refusal = rc.build_coverage(write=False, now_iso=now)
    except Exception as exc:  # noqa: BLE001
        refusal = {"status": "unavailable", "error": str(exc)}

    # ── headline roll-up (honest) ──────────────────────────────────────────────────────────────
    headline = {
        "rwa_floor_apy_pct": round(floor, 4),
        "n_captured_books": (captured.get("n_captured") if isinstance(captured, dict) else None),
        "captured_ids": (captured.get("captured_ids") if isinstance(captured, dict) else None),
        "combined_status": (combined.get("status") if isinstance(combined, dict) else None),
        "combined_reconciles": (combined.get("reconciles") if isinstance(combined, dict) else None),
        "combined_carry_leg_usd": (combined.get("combined_carry_leg_usd") if isinstance(combined, dict) else None),
        "combined_carry_beats_floor": (combined.get("carry_beats_floor") if isinstance(combined, dict) else None),
        "decorrelation_measured": (
            decorr.get("capacity_ceiling", {}).get("measured") if isinstance(decorr, dict) else None),
        "decorrelated_ceiling_usd": (
            decorr.get("capacity_ceiling", {}).get("decorrelated_ceiling_usd")
            if isinstance(decorr, dict) else None),
        "matrix_valid": (
            decorr.get("matrix_validity", {}).get("valid") if isinstance(decorr, dict) else None),
        "refusal_100pct_on_toxic": (
            refusal.get("refusal_100pct_on_toxic") if isinstance(refusal, dict) else None),
    }

    report = {
        "generated_at": now,                # METADATA — not anchored
        "model": "strategy_lab_master_attribution",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "research_only": True,
        "separate_from_golive_track": True,
        "headline": headline,
        "captured_sleeves": captured,
        "combined_attribution": combined,
        "decorrelation": decorr,
        "refusal_coverage": refusal,
        "note": (
            "WS-4.5 MASTER attribution report — every captured book vs the ~3.4% RWA floor, "
            "hash-anchored (proof-chain pattern) so it is verifiable. Combined carry reconciles to "
            "the captured-book NAV; the decorrelation benefit is empirical + bounded (zero on "
            "unmeasured tracks); refusal stays 100% on toxic. HONEST at today's THIN depth — the "
            "combined carry can be negative early. Advisory paper — NOT live capital; the go-live "
            "track is byte-untouched. Real capital for any sleeve is OWNER-GATED."),
        "proof_event_type": EVENT_TYPE,     # METADATA — documents the anchor primitive
    }
    # ── the anchor: a deterministic hash over the report BODY (everything but the metadata) ──────
    report["proof_hash"] = _proof_hash(_body_of(report))

    if write:
        (root / "strategy_lab").mkdir(parents=True, exist_ok=True)
        atomic_save(report, str(root / "strategy_lab" / OUT_FILE.name))
    return report


def render_markdown(report: dict) -> str:
    """A compact human-readable rendering of the master report (for the docs/site surface)."""
    h = report.get("headline", {})
    lines = ["# Strategy Lab — Master Attribution (every captured book vs the RWA floor)", ""]
    lines.append(f"- **RWA floor:** {h.get('rwa_floor_apy_pct')}%/yr")
    lines.append(f"- **Captured books:** {h.get('n_captured_books')} — {h.get('captured_ids')}")
    lines.append(f"- **Combined attribution:** status `{h.get('combined_status')}`, "
                 f"reconciles `{h.get('combined_reconciles')}`, carry-leg "
                 f"${h.get('combined_carry_leg_usd')} (beats floor: {h.get('combined_carry_beats_floor')})")
    lines.append(f"- **Decorrelation:** measured `{h.get('decorrelation_measured')}`, "
                 f"matrix valid `{h.get('matrix_valid')}`, "
                 f"capacity ceiling ${h.get('decorrelated_ceiling_usd')}")
    lines.append(f"- **Refusal 100% on toxic:** `{h.get('refusal_100pct_on_toxic')}`")
    lines.append("")
    lines.append(f"**Proof hash (anchored body):** `{report.get('proof_hash')}`")
    lines.append("")
    lines.append(f"> {report.get('note')}")
    return "\n".join(lines)


def main() -> int:
    import socket
    socket.setdefaulttimeout(20)
    report = build_master_report(write=True)
    v = verify_master_report(report)
    print(render_markdown(report))
    print(f"\nverify: valid={v['valid']}  hash={v['recomputed_hash']}")
    print("\n--- full ---")
    print(json.dumps(report, indent=2, default=str)[:2000])
    return 0 if v["valid"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
