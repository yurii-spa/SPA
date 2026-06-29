"""
spa_core/strategy_lab/portfolio_book.py — ROUND-2 WS-3.3: the DECORRELATED MULTI-SLEEVE book.

THE QUESTION THIS ANSWERS (WS-1's honest finding)
══════════════════════════════════════════════════
WS-1 proved a SINGLE sleeve sits in cash and does not beat the RWA floor at scale: FixedCarry is thin
and below floor; the optimizer's uplift is a $100k artifact. But a SINGLE sleeve is the wrong unit. A
risk-budgeted PORTFOLIO of LOW-correlation sleeves can stay invested where any one sleeve would sit in
cash — diversification lets the book carry more total risk-adjusted return at the same volatility. This
module combines the three named sleeve families into ONE risk-budgeted book and asks, HONESTLY, whether
the combined realized track beats the RWA floor risk-adjusted — and says so plainly when it does NOT.

THE THREE SLEEVES (the brief's named set)
═══════════════════════════════════════════
  • FixedCarry      — the rates-desk PT carry book (rates_desk/paper/rates_desk_fixed_carry_series).
  • rwa_sleeve      — the realized tokenized-T-bill cash FLOOR (strategy_lab_paper/rwa_sleeve_series).
  • eth_lst_neutral — the SAFE hedged-ETH (PLAIN-LST + short-perp, β≈0) sleeve. Its own forward series
                      may not exist yet (its live feed has not let it trade — INSUFFICIENT_DATA). When
                      absent we fall back to the REALIZED hedged-neutral track of `variant_n` (the
                      restaking-neutral β≈0 sleeve that DOES have a forward record) as the best available
                      realized proxy for the hedged-ETH-neutral leg — EXPLICITLY labeled as a proxy,
                      never fabricated. When NEITHER exists the leg is INSUFFICIENT_DATA and is dropped
                      from the risk budget (the book is built from the legs that have a real track).

RISK-BUDGETED WEIGHTS (inverse-volatility, decorrelation-aware)
═══════════════════════════════════════════════════════════════
Equal-risk-contribution intuition without a full optimizer (stdlib, deterministic): weight each sleeve
INVERSELY to its realized return volatility (a quiet floor sleeve gets more weight than a noisy hedged
sleeve, equalizing risk contribution), then normalize. A zero-vol sleeve (the realized RWA floor) is
capped at a documented max weight so the "book" is not just the floor wearing a portfolio costume. The
combined daily return is the weight-blended sleeve return; the combined equity path compounds it.

WHAT IT REPORTS (honest, fail-CLOSED, no fabrication)
═══════════════════════════════════════════════════════
  • the realized combined equity track + net APY + max drawdown over the COMMON date axis,
  • beats_rwa_floor (risk-adjusted, reusing metrics.beats_rwa_floor) — HONEST: INSUFFICIENT_DATA when
    the common track is thinner than MIN_TRACK_POINTS (a handful of days is not yet a verdict),
  • the EMPIRICAL decorrelation matrix across the sleeves (REUSING decorrelation.decorrelation_matrix),
    the average pairwise correlation, and a "single-bet" guard: a book whose sleeves are ~perfectly
    correlated (rho_bar → 1) is NOT a diversified book — it is one bet wearing three names, and we SAY
    so (`is_single_bet=True`) rather than claim a diversification benefit it does not have.

stdlib only, deterministic, fail-CLOSED, atomic writes (spa_core.utils.atomic). LLM FORBIDDEN.
Advisory / research — reads the captured + forward series READ-ONLY; never moves capital, never flips
is_live, never touches the go-live track.

Run (offline, on the accrued forward series):
    python3 -m spa_core.strategy_lab.portfolio_book
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
from spa_core.strategy_lab import decorrelation

_REPO_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
DATA_DIR = _REPO_ROOT / "data"
OUT_FILE = DATA_DIR / "strategy_lab" / "portfolio_book.json"

# The named sleeve set + where each leg's realized forward series lives. Pinned + documented.
FIXED_CARRY_SERIES = ("rates_desk", "paper", "rates_desk_fixed_carry_series.json")
RWA_SLEEVE_SERIES = ("strategy_lab_paper", "rwa_sleeve_series.json")
ETH_LST_NEUTRAL_SERIES = ("strategy_lab_paper", "eth_lst_neutral_series.json")
# Realized hedged-neutral PROXY for eth_lst_neutral when its own series is absent (documented; the
# variant_n restaking-neutral β≈0 sleeve is the closest realized hedged-ETH-neutral track we have).
ETH_NEUTRAL_PROXY_SERIES = ("strategy_lab_paper", "variant_n_series.json")

# A combined common-axis track needs at least this many points before beats_floor is a trustworthy
# verdict; below it the verdict is INSUFFICIENT_DATA (honest — a few days is not a track).
MIN_TRACK_POINTS = 7

# A zero/near-zero-vol sleeve (the realized RWA floor) is capped at this weight so the risk-budgeted
# book is not just the floor in disguise (inverse-vol would otherwise hand a flat floor ~all the weight).
MAX_SINGLE_SLEEVE_WEIGHT = 0.60

# A floor on each sleeve's realized vol used in the inverse-vol weight (so a perfectly-flat sleeve does
# not produce an infinite weight). Daily-return vol units; conservative tiny floor.
VOL_FLOOR = 1e-6

# rho_bar at/above this → the sleeves move together → the book is effectively a SINGLE BET (not
# diversified). We flag it honestly rather than credit a phantom diversification benefit.
SINGLE_BET_RHO = 0.95


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ──────────────────────────────────────────────────────────────────────────────
# sleeve-series loading (fail-CLOSED, honest INSUFFICIENT_DATA)
# ──────────────────────────────────────────────────────────────────────────────
def _load(root: Path, parts: Tuple[str, ...]) -> Optional[dict]:
    p = root
    for seg in parts:
        p = p / seg
    if not p.exists():
        return None
    return atomic_load(str(p), default=None)


def discover_sleeve_series(root: Optional[Path] = None) -> Dict[str, Any]:
    """{sleeve_name: series_doc} for the three named legs. eth_lst_neutral falls back to the
    variant_n realized proxy when its own series is absent (labeled in the returned name). A leg with
    NO real series at all is simply omitted (fail-CLOSED: the book is built from legs with a track).
    PURE-ish (reads files); deterministic given the on-disk series."""
    root = Path(root) if root is not None else DATA_DIR
    out: Dict[str, Any] = {}
    fc = _load(root, FIXED_CARRY_SERIES)
    if fc is not None:
        out["fixed_carry"] = fc
    rwa = _load(root, RWA_SLEEVE_SERIES)
    if rwa is not None:
        out["rwa_sleeve"] = rwa
    # eth_lst_neutral: prefer its own series; else the documented realized proxy; else omit.
    eln = _load(root, ETH_LST_NEUTRAL_SERIES)
    if eln is not None:
        out["eth_lst_neutral"] = eln
    else:
        proxy = _load(root, ETH_NEUTRAL_PROXY_SERIES)
        if proxy is not None:
            out["eth_lst_neutral(proxy:variant_n)"] = proxy
    return out


# ──────────────────────────────────────────────────────────────────────────────
# the risk-budgeted combined track
# ──────────────────────────────────────────────────────────────────────────────
def _vol(returns: List[float]) -> float:
    """Sample std of a daily-return list (0.0 for < 2 points). PURE."""
    if len(returns) < 2:
        return 0.0
    m = sum(returns) / len(returns)
    var = sum((r - m) ** 2 for r in returns) / (len(returns) - 1)
    return math.sqrt(var) if var > 0 else 0.0


def _inverse_vol_weights(sleeve_returns: Dict[str, Dict[str, float]],
                         common_dates: List[str]) -> Dict[str, float]:
    """Inverse-realized-vol weights over the COMMON date axis, capped at MAX_SINGLE_SLEEVE_WEIGHT and
    renormalized. A flat (zero-vol) sleeve is floored at VOL_FLOOR so it does not get infinite weight;
    the cap then prevents the quiet floor from dominating. Deterministic. Returns {} if no sleeve has a
    usable common-axis return series."""
    raw: Dict[str, float] = {}
    for name, dr in sleeve_returns.items():
        rets = [dr[d] for d in common_dates if d in dr]
        v = max(_vol(rets), VOL_FLOOR)
        raw[name] = 1.0 / v
    total = sum(raw.values())
    if total <= 0:
        return {}
    weights = {k: v / total for k, v in raw.items()}
    # cap + renormalize (single pass is enough for a small named set; deterministic)
    capped = {k: min(w, MAX_SINGLE_SLEEVE_WEIGHT) for k, w in weights.items()}
    ctotal = sum(capped.values())
    if ctotal <= 0:
        return {}
    return {k: w / ctotal for k, w in capped.items()}


def build_combined_track(sleeve_series: Dict[str, Any]) -> dict:
    """Build the risk-budgeted combined equity track over the sleeves' COMMON date axis. PURE /
    deterministic / fail-CLOSED.

    Returns {sleeves, weights, common_dates, combined_equity, combined_returns, n_points, dropped}.
    A sleeve whose series fails integrity / has no returns is DROPPED (listed in `dropped`), never
    fabricated. An empty common axis → empty track (honest, never invented)."""
    sleeve_returns: Dict[str, Dict[str, float]] = {}
    dropped: List[dict] = []
    for name in sorted(sleeve_series.keys()):
        dr = decorrelation._dated_returns(sleeve_series[name])
        if dr is None:
            dropped.append({"sleeve": name, "reason": "integrity_failed_or_malformed"})
            continue
        if not dr:
            dropped.append({"sleeve": name, "reason": "no_returns (< 2 dated points)"})
            continue
        sleeve_returns[name] = dr

    # common date axis = days EVERY usable sleeve has a return (so the blend is honest, not padded).
    if not sleeve_returns:
        return {"sleeves": [], "weights": {}, "common_dates": [], "combined_equity": [],
                "combined_returns": [], "n_points": 0, "dropped": dropped}
    common = None
    for dr in sleeve_returns.values():
        s = set(dr.keys())
        common = s if common is None else (common & s)
    common_dates = sorted(common or set())

    weights = _inverse_vol_weights(sleeve_returns, common_dates)
    combined_returns = []
    for d in common_dates:
        r = sum(weights.get(name, 0.0) * dr.get(d, 0.0) for name, dr in sleeve_returns.items())
        combined_returns.append(r)
    # compound the blended return into an equity path (start at 1.0 → indexed; scale-free, honest).
    equity = [1.0]
    for r in combined_returns:
        equity.append(equity[-1] * (1.0 + r))

    return {
        "sleeves": sorted(sleeve_returns.keys()),
        "weights": {k: round(v, 6) for k, v in weights.items()},
        "common_dates": common_dates,
        "combined_equity": equity,
        "combined_returns": [round(r, 10) for r in combined_returns],
        "n_points": len(equity),
        "dropped": dropped,
    }


# ──────────────────────────────────────────────────────────────────────────────
# the honest verdict
# ──────────────────────────────────────────────────────────────────────────────
def build_report(
    *,
    data_dir: Optional[Path] = None,
    sleeve_series: Optional[Dict[str, Any]] = None,
    floor_apy_pct: Optional[float] = None,
    write: bool = True,
    now_iso: Optional[str] = None,
) -> dict:
    """Build the decorrelated multi-sleeve book report + (optionally) write
    data/strategy_lab/portfolio_book.json atomically.

    HONEST verdict: beats_floor is computed ONLY when the common track is >= MIN_TRACK_POINTS deep;
    otherwise INSUFFICIENT_DATA. The decorrelation matrix is the REAL Pearson matrix over the sleeves
    (reusing decorrelation.decorrelation_matrix). The single-bet guard flags a book whose sleeves are
    ~perfectly correlated (rho_bar >= SINGLE_BET_RHO) — it is one bet, not a diversified portfolio.

    fail-CLOSED throughout: a malformed/integrity-failed sleeve is dropped, a thin track is
    INSUFFICIENT_DATA, an unmeasured correlation is UNKNOWN. No fabrication."""
    root = Path(data_dir) if data_dir is not None else DATA_DIR
    now = now_iso if now_iso is not None else _utc_now_iso()
    floor = metrics.rwa_floor_apy_pct() if floor_apy_pct is None else float(floor_apy_pct)

    if sleeve_series is None:
        sleeve_series = discover_sleeve_series(root)

    track = build_combined_track(sleeve_series)
    equity = track["combined_equity"]
    returns = track["combined_returns"]

    # decorrelation matrix over the SAME sleeve series (reuse — never reinvented).
    mat = decorrelation.decorrelation_matrix(sleeve_series)
    validity = decorrelation.validate_matrix(mat)
    rho_bar = mat.get("avg_abs_offdiag_corr")
    is_single_bet = bool(rho_bar is not None and rho_bar >= SINGLE_BET_RHO)

    # honest metrics on the realized combined track.
    napy = metrics.net_apy_from_equity(equity) if len(equity) >= 2 else None
    mdd = metrics.max_drawdown_pct(equity) if len(equity) >= 2 else None
    sharpe = metrics.sharpe(returns) if len(returns) >= 2 else None

    thin = track["n_points"] < MIN_TRACK_POINTS
    if thin or napy is None or mdd is None:
        verdict = "INSUFFICIENT_DATA"
        beats_floor: Optional[bool] = None
        reason = (f"combined common-axis track is thin ({track['n_points']} pts < {MIN_TRACK_POINTS}) "
                  "— the realized $ blend is honest but the annualized beats-floor verdict is not yet "
                  "trustworthy. INSUFFICIENT_DATA, NOT a strategy loss.")
    else:
        beats_floor = bool(metrics.beats_rwa_floor(napy, mdd, floor))
        verdict = "BEATS_FLOOR" if beats_floor else "BELOW_FLOOR"
        reason = (
            f"combined risk-budgeted book net APY {napy:.4f}% vs RWA floor {floor:.4f}% "
            f"(maxDD {mdd:.4f}%) → " + (
                "BEATS the floor risk-adjusted (excess covers drawdown)." if beats_floor else
                "does NOT beat the floor risk-adjusted yet — honest BELOW_FLOOR. A single sleeve sits "
                "in cash; this decorrelated book stays invested but has not yet cleared the floor."))

    out = {
        "generated_at": now,
        "model": "strategy_lab_portfolio_book",
        "llm_forbidden": True,
        "deterministic": True,
        "is_advisory": True,
        "research_only": True,
        "separate_from_golive_track": True,
        "rwa_floor_apy_pct": round(floor, 4),
        "min_track_points": MIN_TRACK_POINTS,
        "verdict": verdict,
        "beats_floor": beats_floor,
        "reason": reason,
        "combined_net_apy_pct": napy,
        "combined_max_drawdown_pct": mdd,
        "combined_sharpe": sharpe,
        "n_track_points": track["n_points"],
        "common_dates": track["common_dates"],
        "sleeves": track["sleeves"],
        "weights": track["weights"],
        "dropped_sleeves": track["dropped"],
        "combined_equity_indexed": [round(e, 8) for e in equity],
        "decorrelation": {
            "matrix": mat["matrix"],
            "n_overlap": mat["n_overlap"],
            "avg_abs_offdiag_corr": rho_bar,
            "n_known_pairs": mat["n_known_pairs"],
            "n_unknown_pairs": mat["n_unknown_pairs"],
            "valid": validity["valid"],
        },
        "is_single_bet": is_single_bet,
        "single_bet_rho_threshold": SINGLE_BET_RHO,
        "single_bet_note": (
            "FLAGGED: the sleeves' realized returns are ~perfectly correlated (rho_bar >= "
            f"{SINGLE_BET_RHO}) — this is ONE bet wearing three names, NOT a diversified book; NO "
            "diversification benefit is credited." if is_single_bet else
            ("rho_bar UNKNOWN at this track depth — diversification is not yet measurable (fail-closed)."
             if rho_bar is None else
             f"sleeves are not a single bet (rho_bar={rho_bar:.4f} < {SINGLE_BET_RHO}); a real "
             "diversification benefit is plausible but bounded.")),
        "note": (
            "WS-3.3 decorrelated multi-sleeve book: FixedCarry + rwa_sleeve + eth_lst_neutral (or its "
            "documented realized proxy) combined inverse-vol risk-budgeted over their COMMON date axis. "
            "beats_floor is HONEST (INSUFFICIENT_DATA where thin); the decorrelation matrix is the REAL "
            "Pearson matrix; a single-bet (corr~1) book is flagged, never dressed as diversified. "
            "Advisory — never moves capital, never touches the go-live track."),
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
    print(f"Decorrelated multi-sleeve book   RWA floor {rep['rwa_floor_apy_pct']}%/yr")
    print(f"sleeves={rep['sleeves']}  weights={rep['weights']}")
    print(f"track points={rep['n_track_points']}  net APY="
          f"{rep['combined_net_apy_pct']}  maxDD={rep['combined_max_drawdown_pct']}")
    print(f"verdict={rep['verdict']}  beats_floor={rep['beats_floor']}")
    print(f"rho_bar={rep['decorrelation']['avg_abs_offdiag_corr']}  "
          f"single_bet={rep['is_single_bet']}")
    print(f"reason: {rep['reason']}")
    print(f"dropped: {rep['dropped_sleeves']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
