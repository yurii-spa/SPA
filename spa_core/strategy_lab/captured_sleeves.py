"""
spa_core/strategy_lab/captured_sleeves.py — promote VALIDATED Strategy-Lab sleeves to
CAPTURED-PAPER books (WS-4.1, "deepen the edge").

WHY THIS EXISTS
═══════════════
The rates-desk FixedCarry sleeve is already a CAPTURED-PAPER book: a bounded, SEPARATE paper
book whose forward record (data/rates_desk/paper/*_series.json) accrues a real, hash-anchored
carry track that becomes fundability evidence. The Strategy-Lab sleeves (eth_lst_neutral, rwa_sleeve)
are validated/advisory but NOT captured — their forward records (data/strategy_lab_paper/*_series.json)
accrue, but nothing PROMOTES them into a bounded captured book the combined-attribution + capacity
model can treat the way it treats FixedCarry.

This module is that promotion gate. It is HONEST by construction — it captures a sleeve ONLY when
the sleeve genuinely passes validation AND has a real accruing forward record, and it reports an
explicit NO-GO (with the reason) for every sleeve that does not. It NEVER fabricates a track and it
NEVER flips a sleeve live.

THE GATE (deterministic, fail-CLOSED, every condition must hold to CAPTURE)
══════════════════════════════════════════════════════════════════════════
  (1) PROMOTION  — the sleeve is a PAPER_CANDIDATE in the Strategy-Lab promotion engine
                   (promotion.py: it cleared the RWA floor + every risk criterion in the backtest
                   AND is walk-forward-robust + capacity-sufficient). A REJECT / BACKTEST_PASS
                   sleeve is NOT captured (honest NO-GO with the promotion reason).
  (2) ADVISORY   — the sleeve is_advisory=True (repo rule #10). A live-capable sleeve is REFUSED
                   here (fail-CLOSED) — the captured book is advisory paper, never live capital.
  (3) REAL TRACK — the sleeve's forward series exists, passes track_integrity (no gap / dup /
                   out-of-order / FUTURE / malformed) AND carries >= MIN_CAPTURE_POINTS real,
                   non-flat accruing points. An empty / fail-closed / single-point series is NOT
                   a captured book — it is INSUFFICIENT_DATA (the honest NO-GO for a sleeve whose
                   live feed did not let it trade, e.g. eth_lst_neutral offline).

A captured book is a BOUNDED, SEPARATE paper book: its initial capital + current NAV come from the
sleeve's OWN forward series (never the $100k go-live track), and it is tagged is_advisory + research_only
so no downstream consumer can mistake it for live capital. The go-live track is byte-untouched.

CASH-FLOOR HONESTY (the rwa_sleeve case)
════════════════════════════════════════
rwa_sleeve is the REALIZED tokenized-T-bill cash floor: it banks the floor (~3.4%), it does NOT beat
it. It passes the gate (real, zero-drawdown, accruing) and IS captured — but flagged `at_floor=True`
so the combined attribution credits it as a BASE-yield (floor-banking) book, never as an above-floor
edge. Capturing the realized floor is honest and useful (it is the deep base the carry sits on); it is
NOT dressed up as alpha.

stdlib only, deterministic, fail-CLOSED, atomic writes (spa_core.utils.atomic). LLM FORBIDDEN.
Advisory / research — never moves capital, never touches execution/*, never touches the go-live track.

Run (offline, on the accrued forward series):
    python3 -m spa_core.strategy_lab.captured_sleeves
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.utils.atomic import atomic_load, atomic_save
from spa_core.strategy_lab import metrics
from spa_core.strategy_lab import track_integrity as ti
from spa_core.strategy_lab import promotion as lab_promotion

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
LAB_PAPER_DIR = DATA_DIR / "strategy_lab_paper"
CAPTURED_DIR = DATA_DIR / "strategy_lab" / "captured"
CAPTURED_INDEX = DATA_DIR / "strategy_lab" / "captured_sleeves.json"

# The Strategy-Lab sleeves eligible for capture (the validated forward-tracked sleeves). The stable
# ENGINES (engine_a/b/c) are production paper books with their own accrual path and are NOT promoted
# here (they are credited separately by the capacity model). rwa_sleeve = the realized floor;
# eth_lst_neutral = the SAFE hedged-ETH sleeve. Pinned + documented (never a wildcard).
CAPTURE_CANDIDATES: Tuple[str, ...] = ("rwa_sleeve", "eth_lst_neutral")

# The stage a sleeve must reach in the Strategy-Lab promotion engine before it can be captured. Only a
# PAPER_CANDIDATE (cleared the floor + risk + walk-forward + capacity) is captured; BACKTEST_PASS /
# REJECT are honest NO-GOs.
CAPTURABLE_STAGE = lab_promotion.STAGE_PAPER_CANDIDATE

# A captured book must carry at least this many real accruing points before it is a track (not a
# fabricated 1-point book). Mirrors forward_analytics MIN_POINTS intent at the capture boundary: a
# handful of days is enough to be a REAL captured book, but a 0/1-point series is INSUFFICIENT_DATA.
MIN_CAPTURE_POINTS = 2

# Verdict labels (single source of truth).
CAPTURED = "CAPTURED"                 # passed the gate → a bounded captured paper book exists
NO_GO_PROMOTION = "NO_GO_PROMOTION"   # did not reach PAPER_CANDIDATE (the gate's promotion leg)
NO_GO_INSUFFICIENT = "NO_GO_INSUFFICIENT_DATA"  # no real accruing track (empty / fail-closed / thin)
NO_GO_INTEGRITY = "NO_GO_TRACK_INTEGRITY"       # the forward series failed track_integrity
NO_GO_NOT_ADVISORY = "NO_GO_NOT_ADVISORY"       # is_advisory=False — refused (never capture a live sleeve)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# series → equity path (fail-CLOSED, no fabrication)
# ──────────────────────────────────────────────────────────────────────────────
def _equity_path(points: List[dict]) -> Optional[List[float]]:
    """Pull the equity_usd path from an in-order point list. None (fail-CLOSED) on a missing /
    non-numeric / non-finite equity — a malformed point is never a captured book."""
    import math
    eq: List[float] = []
    for p in points:
        v = p.get("equity_usd")
        if not isinstance(v, (int, float)) or isinstance(v, bool):
            return None
        if not math.isfinite(float(v)):
            return None
        eq.append(float(v))
    return eq


def _is_real_track(equity: List[float]) -> bool:
    """A captured book is REAL when it has >= MIN_CAPTURE_POINTS points AND actually MOVED off its
    start (a flat fail-closed hold that never accrued is not a captured book — it is INSUFFICIENT
    data). Deterministic; conservative."""
    if len(equity) < MIN_CAPTURE_POINTS:
        return False
    # require some movement off the start (an accrual happened); a perfectly flat series is a hold.
    return any(abs(e - equity[0]) > 1e-9 for e in equity[1:])


# ──────────────────────────────────────────────────────────────────────────────
# promotion stage lookup (reuse the validated Strategy-Lab promotion engine)
# ──────────────────────────────────────────────────────────────────────────────
def _promotion_index(promotion_report: Optional[dict]) -> Dict[str, dict]:
    """Map sleeve id → its promotion record from a promotion.build_report() result. Empty on a
    missing/!malformed report (fail-CLOSED: absent promotion evidence → no sleeve is capturable)."""
    if not isinstance(promotion_report, dict):
        return {}
    out: Dict[str, dict] = {}
    for s in promotion_report.get("sleeves") or []:
        if isinstance(s, dict) and s.get("id"):
            out[s["id"]] = s
    return out


# ──────────────────────────────────────────────────────────────────────────────
# evaluate ONE candidate
# ──────────────────────────────────────────────────────────────────────────────
def evaluate_candidate(
    sleeve_id: str,
    *,
    series_doc: Any,
    promotion_record: Optional[dict],
    floor_apy_pct: float,
) -> dict:
    """Honest capture verdict for ONE candidate sleeve. PURE / fail-CLOSED / deterministic.

    Returns a record carrying the verdict (CAPTURED / a NO_GO_* reason), the promotion stage, the
    advisory flag, the integrity result, and — when CAPTURED — the bounded captured book
    (initial_capital_usd, nav_usd, realized_pnl_usd, n_points, dates, at_floor). NEVER fabricates a
    track: a NO_GO carries the reason, never an invented number.
    """
    rec: dict = {
        "id": sleeve_id,
        "verdict": NO_GO_INSUFFICIENT,
        "captured": False,
        "is_advisory": None,
        "promotion_stage": None,
        "promotion_reason": None,
        "integrity_ok": False,
        "integrity_reason": "malformed",
        "n_points": 0,
        "first_date": None,
        "last_date": None,
        "initial_capital_usd": None,
        "nav_usd": None,
        "realized_pnl_usd": None,
        "net_apy_pct": None,
        "max_drawdown_pct": None,
        "at_floor": None,
        "beats_floor": None,
        "floor_apy_pct": round(float(floor_apy_pct), 4),
        "reason": "",
    }

    # ── (1) PROMOTION leg — must be a PAPER_CANDIDATE ──────────────────────────────────────────
    pr = promotion_record or {}
    stage = pr.get("stage")
    rec["promotion_stage"] = stage
    rec["promotion_reason"] = pr.get("reason")
    rec["is_advisory"] = None  # filled from the series/status below if available
    promotion_ok = (stage == CAPTURABLE_STAGE)

    # ── (3a) integrity gate on the forward series (fail-CLOSED) ────────────────────────────────
    integ = ti.check_track_integrity(series_doc)
    rec["integrity_ok"] = bool(integ["ok"])
    rec["integrity_reason"] = integ["reason"]
    rec["n_points"] = integ["n_points"]
    rec["first_date"] = integ["first_date"]
    rec["last_date"] = integ["last_date"]

    points = ti._coerce_series(series_doc) or []

    # advisory flag: read from the sleeve's series doc / first point if present, else default True
    # (advisory is the documented mandate; a non-advisory sleeve in this surface is a contract bug).
    rec["is_advisory"] = _advisory_of(series_doc, points)

    # ── ADVISORY enforcement (fail-CLOSED): never capture a live-capable sleeve ─────────────────
    if rec["is_advisory"] is False:
        rec["verdict"] = NO_GO_NOT_ADVISORY
        rec["reason"] = ("is_advisory=False — a live-capable sleeve must NOT be captured in the "
                         "advisory research surface (fail-closed; capture refused).")
        return rec

    if not integ["ok"]:
        rec["verdict"] = NO_GO_INTEGRITY
        rec["reason"] = (f"forward series failed track_integrity ({integ['reason']}) — a broken "
                         "track is never a captured book.")
        return rec

    equity = _equity_path(points) if points else None
    if equity is None or not _is_real_track(equity):
        rec["verdict"] = NO_GO_INSUFFICIENT
        rec["reason"] = (
            "no real accruing forward track yet (empty / fail-closed / flat / < "
            f"{MIN_CAPTURE_POINTS} accruing points) — INSUFFICIENT_DATA, NOT a strategy loss. "
            "The live feed did not let this sleeve trade a record offline.")
        # still record what little is honestly defined
        if equity:
            rec["initial_capital_usd"] = round(equity[0], 2)
            rec["nav_usd"] = round(equity[-1], 2)
        return rec

    # ── all data legs hold; now the PROMOTION leg decides CAPTURED vs NO_GO_PROMOTION ───────────
    initial = equity[0]
    nav = equity[-1]
    realized = nav - initial
    napy = metrics.net_apy_from_equity(equity)
    mdd = metrics.max_drawdown_pct(equity)
    # at_floor: realized APY sits at-or-below the floor (banks the floor, does not beat it). The
    # realized-floor sleeve (rwa_sleeve) lands here by construction — captured as BASE yield.
    at_floor = bool(napy <= floor_apy_pct + 1e-9)
    beats_floor = bool(metrics.beats_rwa_floor(napy, mdd, floor_apy_pct))

    rec.update({
        "initial_capital_usd": round(initial, 2),
        "nav_usd": round(nav, 2),
        "realized_pnl_usd": round(realized, 4),
        "net_apy_pct": napy,
        "max_drawdown_pct": mdd,
        "at_floor": at_floor,
        "beats_floor": beats_floor,
    })

    if not promotion_ok:
        rec["verdict"] = NO_GO_PROMOTION
        rec["reason"] = (
            f"promotion stage {stage!r} != {CAPTURABLE_STAGE} — the sleeve has a real track but "
            "has NOT cleared the Strategy-Lab promotion gate (floor + risk + walk-forward + "
            f"capacity). Honest NO-GO: {pr.get('reason')}")
        return rec

    rec["verdict"] = CAPTURED
    rec["captured"] = True
    rec["reason"] = (
        "PAPER_CANDIDATE in the promotion gate, is_advisory, real accruing forward track, integrity "
        "OK → captured as a bounded SEPARATE advisory paper book."
        + (" Banks the RWA floor (at_floor) → credited as BASE yield, not an above-floor edge."
           if at_floor else " Accrues ABOVE the RWA floor.")
    )
    return rec


def _advisory_of(series_doc: Any, points: List[dict]) -> Optional[bool]:
    """Best-effort read of the sleeve's is_advisory flag. The forward series points don't carry it,
    so we resolve it from the live config block (the SSOT mandate). Fail-CLOSED to True (advisory)
    only when the config can't be read — a real is_advisory=False in config is honored and REFUSES
    capture. Returns True/False, or True as the documented default."""
    # the doc may carry an explicit flag (some status files do); honor it first.
    if isinstance(series_doc, dict) and isinstance(series_doc.get("is_advisory"), bool):
        return series_doc["is_advisory"]
    sid = series_doc.get("id") if isinstance(series_doc, dict) else None
    if not sid:
        return True
    try:
        from spa_core.strategy_lab import config as lab_config
        block = (lab_config.load_config().get("strategies") or {}).get(sid) or {}
        v = block.get("is_advisory")
        if isinstance(v, bool):
            return v
    except Exception:  # noqa: BLE001 — config read failure → advisory default (never capture-live)
        return True
    return True


# ──────────────────────────────────────────────────────────────────────────────
# captured book materialization (the bounded SEPARATE book artifact)
# ──────────────────────────────────────────────────────────────────────────────
def _write_captured_book(rec: dict, *, captured_dir: Path, now_iso: str) -> None:
    """Write the bounded captured-book artifact for a CAPTURED sleeve, atomically. The book mirrors
    the FixedCarry captured-book shape: a SEPARATE advisory paper book keyed by the sleeve id, tagged
    is_advisory + research_only so no consumer mistakes it for live capital."""
    book = {
        "id": rec["id"],
        "model": "captured_sleeve_book",
        "generated_at": now_iso,
        "llm_forbidden": True,
        "is_advisory": True,
        "research_only": True,
        "separate_from_golive_track": True,
        "initial_capital_usd": rec["initial_capital_usd"],
        "nav_usd": rec["nav_usd"],
        "realized_pnl_usd": rec["realized_pnl_usd"],
        "net_apy_pct": rec["net_apy_pct"],
        "max_drawdown_pct": rec["max_drawdown_pct"],
        "n_points": rec["n_points"],
        "first_date": rec["first_date"],
        "last_date": rec["last_date"],
        "at_floor": rec["at_floor"],
        "beats_floor": rec["beats_floor"],
        "floor_apy_pct": rec["floor_apy_pct"],
        "note": rec["reason"],
    }
    captured_dir.mkdir(parents=True, exist_ok=True)
    atomic_save(book, str(captured_dir / f"{rec['id']}_captured.json"))


# ──────────────────────────────────────────────────────────────────────────────
# build the captured-sleeve index over all candidates
# ──────────────────────────────────────────────────────────────────────────────
def build_captured_sleeves(
    *,
    data_dir: Optional[Path] = None,
    promotion_report: Optional[dict] = None,
    floor_apy_pct: Optional[float] = None,
    write: bool = True,
    now_iso: Optional[str] = None,
) -> dict:
    """Evaluate every CAPTURE_CANDIDATE, write a bounded captured book for each that PASSES, and
    return the captured-sleeve index. Writes data/strategy_lab/captured_sleeves.json + per-sleeve
    captured books atomically (unless write=False).

    Args:
        data_dir:         override the data root (tests/hermetic). None → live DATA_DIR.
        promotion_report: inject a promotion.build_report() result (tests/hermetic). None → build it
                          live from the on-disk backtest/walk-forward evidence (fail-CLOSED: a missing
                          backtest yields an empty sleeves list → every candidate NO_GO_PROMOTION).
        floor_apy_pct:    override the RWA floor % (tests). None → live metrics.rwa_floor_apy_pct().
        write:            persist the index + books atomically when True.
        now_iso:          inject the generated_at stamp (byte-stable tests). None → live UTC.

    Honest by construction: only genuinely-passing sleeves are CAPTURED; every other candidate carries
    an explicit NO_GO_* verdict + reason. The go-live track is never read or written.
    """
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    lab_paper = root / "strategy_lab_paper"
    captured_dir = root / "strategy_lab" / "captured"
    floor = metrics.rwa_floor_apy_pct() if floor_apy_pct is None else float(floor_apy_pct)
    now = now_iso if now_iso is not None else _utc_now_iso()

    # promotion evidence: reuse the validated Strategy-Lab promotion engine (fail-CLOSED: if no
    # report is injected we build it live; a missing backtest → empty → every candidate NO_GO).
    if promotion_report is None:
        try:
            promotion_report = lab_promotion.build_report(write=False)
        except Exception:  # noqa: BLE001 — promotion evidence unavailable → fail-closed empty
            promotion_report = {"sleeves": []}
    prom_idx = _promotion_index(promotion_report)

    records: List[dict] = []
    for sid in CAPTURE_CANDIDATES:
        series_path = lab_paper / f"{sid}_series.json"
        try:
            doc = atomic_load(str(series_path), default=None)
        except Exception:  # noqa: BLE001 — an unreadable series is INSUFFICIENT, never a crash
            doc = None
        if doc is None:
            doc = {"id": sid, "series": []}  # absent series → honest INSUFFICIENT_DATA, no fabrication
        rec = evaluate_candidate(
            sid, series_doc=doc, promotion_record=prom_idx.get(sid), floor_apy_pct=floor)
        records.append(rec)
        if write and rec["captured"]:
            _write_captured_book(rec, captured_dir=captured_dir, now_iso=now)

    captured = [r for r in records if r["captured"]]
    index = {
        "generated_at": now,
        "model": "captured_sleeves",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "research_only": True,
        "separate_from_golive_track": True,
        "rwa_floor_apy_pct": round(floor, 4),
        "capturable_stage": CAPTURABLE_STAGE,
        "min_capture_points": MIN_CAPTURE_POINTS,
        "n_candidates": len(records),
        "n_captured": len(captured),
        "captured_ids": sorted(r["id"] for r in captured),
        "advisory_all_true": all(r["is_advisory"] is True for r in records),
        "sleeves": records,
        "note": (
            "WS-4.1 captured-paper promotion. A sleeve is CAPTURED only when it is a PAPER_CANDIDATE "
            "in the promotion gate, is_advisory, and has a real accruing forward track that passes "
            "track_integrity. rwa_sleeve banks the floor (at_floor → BASE yield, not an above-floor "
            "edge). NO_GO sleeves carry an explicit reason — never a fabricated track. Advisory: "
            "these are bounded SEPARATE paper books, NEVER live capital; the go-live track is "
            "byte-untouched."),
    }
    if write:
        (root / "strategy_lab").mkdir(parents=True, exist_ok=True)
        atomic_save(index, str(root / "strategy_lab" / CAPTURED_INDEX.name))
    return index


def captured_series_paths(data_dir: Optional[Path] = None) -> List[Path]:
    """The forward-series file paths of the CURRENTLY-captured sleeves (for the combined attribution
    + decorrelation to ingest the same real series the gate captured). Reads the captured index;
    returns [] when no sleeve is captured. Fail-safe (never raises)."""
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    idx = atomic_load(str(root / "strategy_lab" / CAPTURED_INDEX.name), default=None)
    if not isinstance(idx, dict):
        return []
    out: List[Path] = []
    for sid in idx.get("captured_ids") or []:
        p = root / "strategy_lab_paper" / f"{sid}_series.json"
        if p.exists():
            out.append(p)
    return out


def main() -> int:
    import json
    import socket
    socket.setdefaulttimeout(20)
    idx = build_captured_sleeves(write=True)
    # honest table
    print(f"Captured-paper sleeves   RWA floor {idx['rwa_floor_apy_pct']}%/yr   "
          f"captured {idx['n_captured']}/{idx['n_candidates']}")
    print(f"{'sleeve':18s} {'verdict':26s} {'stage':16s} {'napy%':>8s}  reason")
    print("-" * 100)
    for r in idx["sleeves"]:
        napy = r["net_apy_pct"]
        napy_s = f"{napy:8.3f}" if isinstance(napy, (int, float)) else f"{'—':>8s}"
        print(f"{r['id']:18s} {r['verdict']:26s} {str(r['promotion_stage']):16s} {napy_s}  "
              f"{r['reason'][:60]}")
    print(json.dumps(idx, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
