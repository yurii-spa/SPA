"""
spa_core/strategy_lab/decorrelation.py — EMPIRICAL cross-sleeve decorrelation + an honest
decorrelation-aware combined capacity ceiling (WS-4.4, "toward the capacity ceiling").

THE QUESTION THIS ANSWERS
═════════════════════════
portfolio_capacity.py sums the THREE sleeve families and applies a STRUCTURAL correlation haircut
(rates carry + RWA both exit through stablecoin venues → not additive). That haircut is a documented,
pinned ASSUMPTION about shared exit rails. This module supplies the missing EMPIRICAL piece: the
realized cross-sleeve return CORRELATION measured from the actual captured forward series. The
diversification benefit of running multiple sleeves is real, but it is BOUNDED by how correlated the
sleeves' realized returns actually are — and that is a measurement, not an assumption.

WHAT IT COMPUTES
════════════════
  (1) EMPIRICAL DECORRELATION MATRIX over the captured sleeves' real return series:
        • align every captured book on the COMMON date axis (only days every book has a return),
        • Pearson correlation for each pair (REUSING metrics.correlation — never reinvented),
        • a valid matrix: symmetric, diagonal == 1.0, every |corr| <= 1.0.
      HONEST / fail-CLOSED: a pair with fewer than MIN_OVERLAP_RETURNS aligned returns yields
      correlation UNKNOWN (None) — a 2-point correlation is a degenerate artifact, never a number.
      At today's ~3-day track depth most pairs SHOULD read UNKNOWN, by design.

  (2) An honest DECORRELATION-AWARE combined capacity ceiling:
        • a diversification benefit is credited ONLY from pairs with a KNOWN, measured correlation,
        • the benefit is the classic 1/sqrt(N_eff) shrink, where N_eff is the effective number of
          INDEPENDENT books implied by the average pairwise correlation (rho_bar): fully-correlated
          books (rho_bar→1) → N_eff→1 (NO benefit); uncorrelated books (rho_bar→0) → N_eff→N (full
          benefit). The benefit is CAPPED (MAX_DECORR_BENEFIT_FRAC) so it can never inflate the book,
        • when correlation is UNKNOWN (thin tracks) the benefit is ZERO (fail-CLOSED: we do NOT credit
          a diversification benefit we have not measured). The combined capacity then == the structural
          portfolio_capacity number with no empirical uplift.

      The output is an HONEST cap: a SMALL, bounded uplift over the structural combined deployable,
      explicitly zero until the tracks are deep enough to measure decorrelation. No inflated number.

stdlib only, deterministic, fail-CLOSED, atomic writes (spa_core.utils.atomic). LLM FORBIDDEN.
Advisory / research — reads the captured series + the structural capacity; never moves capital,
never touches the go-live track.

Run (offline, on the captured series + cached capacity):
    python3 -m spa_core.strategy_lab.decorrelation
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from spa_core.utils.atomic import atomic_load, atomic_save
from spa_core.strategy_lab import metrics
from spa_core.strategy_lab import track_integrity as ti

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
OUT_FILE = DATA_DIR / "strategy_lab" / "decorrelation.json"

# A pair needs at least this many ALIGNED daily returns before its Pearson correlation is trusted; a
# 2-point correlation is a degenerate artifact (it is ±1 by construction). 3 aligned returns ≥ 4
# aligned equity points — a credible minimum. Below it → UNKNOWN (never a fabricated correlation).
MIN_OVERLAP_RETURNS = 3

# The decorrelation benefit is CAPPED: even perfectly-uncorrelated sleeves do not let an underwriter
# deploy unbounded extra depth (shared market-impact, operational limits). The empirical uplift over
# the structural combined deployable can never exceed this fraction — a hard ceiling on the credit so
# the number is never inflated by a lucky low-correlation read on a thin track.
MAX_DECORR_BENEFIT_FRAC = 0.25  # ≤ +25% over the structural combined deployable, ever


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# return-series extraction (dated, fail-CLOSED)
# ──────────────────────────────────────────────────────────────────────────────
def _dated_returns(series_doc: Any) -> Optional[Dict[str, float]]:
    """{date: daily_fractional_return} for ONE captured series, or None (fail-CLOSED) when the series
    fails track_integrity / has a malformed equity. The return on day d is e[d]/e[d-1]-1, KEYED BY d
    (the later date), so two books align on the days they share. Deterministic / PURE."""
    integ = ti.check_track_integrity(series_doc)
    if not integ["ok"]:
        return None
    points = ti._coerce_series(series_doc) or []
    if len(points) < 2:
        return {}  # a clean but single/empty track has no returns (honest empty, not malformed)
    dates: List[str] = []
    equity: List[float] = []
    for p in points:
        d = p.get("date")
        v = p.get("equity_usd")
        if not isinstance(d, str) or not d:
            return None
        if not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(float(v)):
            return None
        dates.append(d[:10])
        equity.append(float(v))
    out: Dict[str, float] = {}
    for i in range(1, len(equity)):
        prev = equity[i - 1]
        out[dates[i]] = (equity[i] / prev - 1.0) if prev > 0 else 0.0
    return out


def _aligned_pair(a: Dict[str, float], b: Dict[str, float]) -> Tuple[List[float], List[float]]:
    """Two dated-return dicts → two equal-length lists over their COMMON dates (sorted)."""
    common = sorted(set(a.keys()) & set(b.keys()))
    return [a[d] for d in common], [b[d] for d in common]


# ──────────────────────────────────────────────────────────────────────────────
# the decorrelation matrix
# ──────────────────────────────────────────────────────────────────────────────
def decorrelation_matrix(book_series: Dict[str, Any]) -> dict:
    """Empirical Pearson correlation matrix across the captured books' real return series.

    Returns:
      {
        "books": [sorted book names that produced a usable return series],
        "matrix": {name_i: {name_j: corr|None}},   # symmetric, diag=1.0, |corr|<=1, None=UNKNOWN
        "n_overlap": {name_i: {name_j: int}},        # aligned-return count per pair
        "avg_abs_offdiag_corr": float|None,          # mean |corr| over KNOWN off-diagonal pairs
        "n_known_pairs": int, "n_unknown_pairs": int,
      }
    fail-CLOSED: a book whose series fails integrity / is malformed is DROPPED (never a fabricated
    correlation row). A pair with < MIN_OVERLAP_RETURNS aligned returns → corr None (UNKNOWN). PURE."""
    rets: Dict[str, Dict[str, float]] = {}
    for name in sorted(book_series.keys()):
        dr = _dated_returns(book_series[name])
        if dr is None:
            continue  # malformed / integrity-failed book → excluded (fail-closed)
        rets[name] = dr
    names = sorted(rets.keys())

    matrix: Dict[str, Dict[str, Optional[float]]] = {}
    overlap: Dict[str, Dict[str, int]] = {}
    known_corrs: List[float] = []
    n_known = 0
    n_unknown = 0
    for i in names:
        matrix[i] = {}
        overlap[i] = {}
        for j in names:
            if i == j:
                matrix[i][j] = 1.0
                overlap[i][j] = len(rets[i])
                continue
            xs, ys = _aligned_pair(rets[i], rets[j])
            overlap[i][j] = len(xs)
            if len(xs) < MIN_OVERLAP_RETURNS:
                matrix[i][j] = None  # UNKNOWN — too few aligned returns for a real correlation
            else:
                c = metrics.correlation(xs, ys)  # None when undefined (zero-variance leg)
                matrix[i][j] = c
            # tally each unordered off-diagonal pair once (i<j)
            if i < j:
                if matrix[i][j] is None:
                    n_unknown += 1
                else:
                    n_known += 1
                    known_corrs.append(abs(float(matrix[i][j])))

    avg_abs = round(sum(known_corrs) / len(known_corrs), 6) if known_corrs else None
    return {
        "books": names,
        "matrix": matrix,
        "n_overlap": overlap,
        "avg_abs_offdiag_corr": avg_abs,
        "n_known_pairs": n_known,
        "n_unknown_pairs": n_unknown,
        "min_overlap_returns": MIN_OVERLAP_RETURNS,
    }


def validate_matrix(mat: dict) -> dict:
    """Assert the matrix is a VALID correlation matrix: symmetric, diagonal == 1.0, every KNOWN entry
    in [-1, 1]. Returns {valid, symmetric, diag_ok, in_range, reason}. PURE / deterministic."""
    m = mat.get("matrix", {})
    names = mat.get("books", [])
    symmetric = True
    diag_ok = True
    in_range = True
    reason = "ok"
    for i in names:
        if m.get(i, {}).get(i) != 1.0:
            diag_ok = False
            reason = "diag"
        for j in names:
            vij = m.get(i, {}).get(j)
            vji = m.get(j, {}).get(i)
            # symmetry holds for both KNOWN (equal values) and UNKNOWN (both None) entries.
            if vij != vji:
                symmetric = False
                reason = "asymmetric"
            if vij is not None and not (-1.0 - 1e-9 <= float(vij) <= 1.0 + 1e-9):
                in_range = False
                reason = "out_of_range"
    valid = bool(symmetric and diag_ok and in_range)
    return {"valid": valid, "symmetric": symmetric, "diag_ok": diag_ok,
            "in_range": in_range, "reason": reason if not valid else "ok"}


# ──────────────────────────────────────────────────────────────────────────────
# the honest decorrelation-aware combined capacity ceiling
# ──────────────────────────────────────────────────────────────────────────────
def _effective_n(n_books: int, rho_bar: float) -> float:
    """Effective number of INDEPENDENT books implied by the average pairwise correlation rho_bar.

    Classic equicorrelation result: the variance of an equal-weight average of N unit-variance books
    with average correlation rho is (1 + (N-1)·rho)/N, so the effective independent count is
    N_eff = N / (1 + (N-1)·rho). rho=1 → N_eff=1 (no diversification); rho=0 → N_eff=N (full).
    Clamped to [1, N]; rho clamped to [0, 1] (we never credit a NEGATIVE correlation as extra
    diversification beyond independence — conservative)."""
    if n_books <= 1:
        return float(max(1, n_books))
    rho = min(1.0, max(0.0, rho_bar))
    denom = 1.0 + (n_books - 1) * rho
    if denom <= 0:
        return float(n_books)
    return min(float(n_books), max(1.0, n_books / denom))


def capacity_ceiling(
    structural_deployable_usd: float,
    matrix: dict,
    *,
    max_benefit_frac: float = MAX_DECORR_BENEFIT_FRAC,
) -> dict:
    """An HONEST decorrelation-aware combined capacity ceiling over the STRUCTURAL combined deployable.

    The diversification benefit is credited ONLY from KNOWN (measured) pairwise correlations:
      • rho_bar = avg |off-diagonal correlation| over the KNOWN pairs (None → no benefit),
      • N_eff   = effective independent books from rho_bar (1/sqrt shrink),
      • benefit_frac = min(max_benefit_frac, (1 - 1/sqrt(N_eff)))  — bounded, ≥ 0,
      • decorrelated_ceiling = structural_deployable · (1 + benefit_frac).

    fail-CLOSED: rho_bar UNKNOWN (thin tracks, no known pair) → benefit_frac = 0 → the ceiling EQUALS
    the structural number (NO empirical uplift on unmeasured decorrelation). The uplift is capped by
    max_benefit_frac so a lucky low-correlation read on a thin track can never inflate the book.

    Returns the ceiling + the full honest derivation. Deterministic / PURE."""
    base = float(structural_deployable_usd)
    n_books = len(matrix.get("books", []))
    rho_bar = matrix.get("avg_abs_offdiag_corr")
    n_known = matrix.get("n_known_pairs", 0)

    if rho_bar is None or n_known == 0 or n_books <= 1:
        # honest: we have NOT measured decorrelation → zero benefit, ceiling == structural number.
        return {
            "structural_deployable_usd": round(base, 2),
            "rho_bar": None,
            "n_books": n_books,
            "n_known_pairs": n_known,
            "effective_independent_books": None,
            "benefit_frac": 0.0,
            "decorrelated_ceiling_usd": round(base, 2),
            "uplift_usd": 0.0,
            "max_benefit_frac": float(max_benefit_frac),
            "measured": False,
            "note": ("decorrelation UNMEASURED at this track depth (no pair has ≥ "
                     f"{MIN_OVERLAP_RETURNS} aligned returns) → ZERO empirical uplift (fail-closed). "
                     "The ceiling equals the structural combined deployable; the benefit ACTIVATES "
                     "only once the captured tracks are deep enough to measure cross-sleeve correlation."),
        }

    n_eff = _effective_n(n_books, float(rho_bar))
    raw_benefit = 1.0 - (1.0 / math.sqrt(n_eff)) if n_eff > 0 else 0.0
    benefit_frac = max(0.0, min(float(max_benefit_frac), raw_benefit))
    ceiling = base * (1.0 + benefit_frac)
    return {
        "structural_deployable_usd": round(base, 2),
        "rho_bar": round(float(rho_bar), 6),
        "n_books": n_books,
        "n_known_pairs": n_known,
        "effective_independent_books": round(n_eff, 4),
        "benefit_frac": round(benefit_frac, 6),
        "decorrelated_ceiling_usd": round(ceiling, 2),
        "uplift_usd": round(ceiling - base, 2),
        "max_benefit_frac": float(max_benefit_frac),
        "measured": True,
        "note": (
            f"MEASURED decorrelation: avg |pairwise corr| rho_bar={float(rho_bar):.4f} over "
            f"{n_known} known pair(s) → {n_eff:.2f} effective independent books → a BOUNDED "
            f"+{benefit_frac*100:.2f}% uplift (capped at {max_benefit_frac*100:.0f}%) over the "
            "structural combined deployable. The diversification benefit is real but bounded — and "
            "it is an empirical measurement, not an assumption."),
    }


# ──────────────────────────────────────────────────────────────────────────────
# build the full report
# ──────────────────────────────────────────────────────────────────────────────
def build_report(
    *,
    data_dir: Optional[Path] = None,
    book_series: Optional[Dict[str, Any]] = None,
    structural_deployable_usd: Optional[float] = None,
    write: bool = True,
    now_iso: Optional[str] = None,
) -> dict:
    """Build the cross-sleeve decorrelation matrix + the honest capacity ceiling and (optionally)
    write data/strategy_lab/decorrelation.json atomically.

    Args:
        data_dir:                  data root (None → live). Used to discover the captured series + the
                                   structural capacity number when those are not injected.
        book_series:               inject {name: series_doc} (tests/hermetic). None → discover the
                                   FixedCarry + captured-sleeve series via forward_analytics.
        structural_deployable_usd: inject the structural combined deployable (tests). None → read it
                                   live from data/strategy_lab/portfolio_capacity.json (the WS-4 model),
                                   fail-safe to 0.0 (→ a ceiling of 0, honest, never a crash).
        write / now_iso:           persist atomically / inject the stamp (byte-stable tests).

    Returns the full report. fail-CLOSED throughout: a malformed book is dropped, an unmeasured pair
    is UNKNOWN, an unmeasured rho_bar credits ZERO uplift."""
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    now = now_iso if now_iso is not None else _utc_now_iso()

    if book_series is None:
        from spa_core.strategy_lab import forward_analytics as fa
        book_series = fa._discover_captured_book_series(root)

    if structural_deployable_usd is None:
        cap_doc = atomic_load(str(root / "strategy_lab" / "portfolio_capacity.json"), default=None)
        structural_deployable_usd = 0.0
        if isinstance(cap_doc, dict):
            c = cap_doc.get("combined") or {}
            v = c.get("total_deployable_usd")
            if isinstance(v, (int, float)):
                structural_deployable_usd = float(v)

    mat = decorrelation_matrix(book_series or {})
    validity = validate_matrix(mat)
    ceiling = capacity_ceiling(structural_deployable_usd, mat)

    out = {
        "generated_at": now,
        "model": "strategy_lab_decorrelation",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "research_only": True,
        "separate_from_golive_track": True,
        "decorrelation_matrix": mat,
        "matrix_validity": validity,
        "capacity_ceiling": ceiling,
        "note": (
            "WS-4.4 EMPIRICAL cross-sleeve decorrelation + honest capacity ceiling. The matrix is the "
            "realized Pearson correlation across the captured books' real return series (symmetric, "
            "diag=1, |corr|<=1; UNKNOWN where the overlap is too thin). The ceiling credits a BOUNDED "
            "diversification benefit ONLY from MEASURED correlations — zero uplift on unmeasured "
            "decorrelation (fail-closed). No inflated number. Advisory — never moves capital."),
    }
    if write:
        (root / "strategy_lab").mkdir(parents=True, exist_ok=True)
        atomic_save(out, str(root / "strategy_lab" / OUT_FILE.name))
    return out


def main() -> int:
    import json
    import socket
    socket.setdefaulttimeout(20)
    rep = build_report(write=True)
    mat = rep["decorrelation_matrix"]
    print(f"Cross-sleeve decorrelation   books={mat['books']}   "
          f"known_pairs={mat['n_known_pairs']} unknown_pairs={mat['n_unknown_pairs']}   "
          f"valid={rep['matrix_validity']['valid']}")
    c = rep["capacity_ceiling"]
    print(f"Structural deployable: ${c['structural_deployable_usd']:,.0f}   "
          f"measured={c['measured']}   rho_bar={c['rho_bar']}   "
          f"ceiling: ${c['decorrelated_ceiling_usd']:,.0f} (uplift ${c['uplift_usd']:,.0f})")
    print(json.dumps(rep, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
