"""
scripts/edge_multi_seam_stability.py — #157 MSS: Multi-Seam Stability

ORDER from #155:
    "Сколько независимых наблюдений нужно, чтобы «отбор угадал» перестало быть удачей?
    У фикстуры один шов. Приёмка — названное число швов/панелей, на которых правило отбора
    по скорости восстановления можно проверить НЕ ПОВТОРНО, и честный ответ «их столько нет»,
    если столько нет."

MECHANICS:
    Slide the TRAIN/TEST seam over a monthly grid 2024-09-01 … 2025-12-01 (16 seam dates).
    For each seam date S:
        TRAIN crises  = {c | c.from < S}   (strict less-than: crisis must start BEFORE seam)
        CRP weights   = normalize(recovery_velocity(series, train_crises, S))
        OOS period    = [S, 2026-05-31]
        Collect: OOS APY_crp, APY_ew, ΔAPY = APY_crp − APY_ew

    Independence analysis:
        A seam is a NEW independent observation only if it brings either:
          (a) a NEW TRAIN crisis set (different input to the sizer), OR
          (b) a non-overlapping OOS period.
        Neither is true within Block-1 or Block-2 (see below).

    Three crisis windows in fixture:
        eth_crash_2024_08    (from 2024-08-01)
        usde_unwind_2025_10  (from 2025-10-01)
        rseth_depeg_2026_04  (from 2026-04-01) ← always OOS for every seam ≤ 2025-12

    Crisis TRAIN membership by seam (strict <):
        Seam 2024-09 … 2025-10 → TRAIN = {eth_crash}                  [Block 1, 14 seams]
        Seam 2025-11 … 2025-12 → TRAIN = {eth_crash, usde_unwind}     [Block 2,  2 seams]

    Within Block-1: all 14 seams have IDENTICAL CRP weights (same TRAIN crisis set).
        OOS periods are nested:  seam 2024-09 OOS ⊃ seam 2024-10 OOS ⊃ … ⊃ seam 2025-10 OOS.
        → Outcomes are correlated, not independent.

    Structural independent count = 2 (one per distinct TRAIN crisis block).
    Conventional minimum for 80%+ power (binomial, p=0.5, one-sided α=0.05) ≈ 5+ successes
    out of 20+ trials.

VERDICT: N_independent = 2 on this fixture.
    CRP cannot be confirmed or refuted at any conventional significance level.
    Status: INSUFFICIENT_EVIDENCE — this is the HONEST answer the ORDER asked for.

stdlib-only, deterministic, LLM FORBIDDEN.
IS_ADVISORY=True, OUTSIDE_RISKPOLICY=True.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import sys
import datetime
import importlib.util
import json
import tempfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_MODULE_ROOT = Path(__file__).resolve().parents[1]
_CRP_PATH = _MODULE_ROOT / "scripts" / "edge_crisis_recovery_profile.py"

IS_ADVISORY = True
OUTSIDE_RISKPOLICY = True

ELIGIBLE_BOOKS = ["susde_dn", "lrt_carry", "leverage_loop", "points_farm", "variant_d"]
OOS_END = datetime.date(2026, 5, 31)
ENTRY_TOLL_BPS = 96  # #149 convention

CRISIS_WINDOWS: List[Dict] = [
    {"key": "eth_crash_2024_08",    "from": datetime.date(2024, 8, 1),  "to": datetime.date(2024, 8, 31)},
    {"key": "usde_unwind_2025_10",  "from": datetime.date(2025, 10, 1), "to": datetime.date(2025, 10, 31)},
    {"key": "rseth_depeg_2026_04",  "from": datetime.date(2026, 4, 1),  "to": datetime.date(2026, 4, 30)},
]

RWA_FLOOR_PCT = 3.4  # from #153 order


class Unmeasured(Exception):
    """Third outcome: neither 'measured and positive' nor 'measured and negative'."""


# ── seam grid ──────────────────────────────────────────────────────────────────

def _monthly_seams() -> List[datetime.date]:
    """Generate monthly seam dates 2024-09-01 … 2025-12-01 (16 dates)."""
    seams = []
    y, m = 2024, 9
    while (y, m) <= (2025, 12):
        seams.append(datetime.date(y, m, 1))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return seams


SEAM_DATES = _monthly_seams()


# ── CRP module loading ─────────────────────────────────────────────────────────

def _load_crp_module():
    """Import #153 edge_crisis_recovery_profile as a module."""
    if not _CRP_PATH.exists():
        raise Unmeasured(f"CRP module not found: {_CRP_PATH}")
    spec = importlib.util.spec_from_file_location("edge_crp", _CRP_PATH)
    if spec is None or spec.loader is None:
        raise Unmeasured(f"Cannot load CRP module at {_CRP_PATH}")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except (FileNotFoundError, ImportError) as exc:
        raise Unmeasured(f"CRP module load failed: {exc}") from exc
    return mod


# ── independence analysis ──────────────────────────────────────────────────────

def _train_crisis_set(seam: datetime.date) -> Tuple[str, ...]:
    """Return the SORTED tuple of crisis keys whose window starts BEFORE the seam."""
    return tuple(sorted(c["key"] for c in CRISIS_WINDOWS if c["from"] < seam))


def _count_independent_seams(seams: List[datetime.date]) -> Tuple[int, List[dict]]:
    """
    Count structurally independent seam observations.

    A seam is independent IFF it introduces a new TRAIN crisis set.
    Within the same TRAIN crisis set, OOS periods are nested (all correlated).

    Returns (n_independent, block_list).
    Each block: {crisis_set, representative_seam, seam_count}.
    """
    seen: Dict[Tuple[str, ...], datetime.date] = {}
    blocks: List[dict] = []
    n = 0
    for s in seams:
        cs = _train_crisis_set(s)
        if not cs:
            continue  # no training crisis before this seam — skip
        if cs not in seen:
            seen[cs] = s
            n += 1
            blocks.append({
                "crisis_set": list(cs),
                "representative_seam": s.isoformat(),
                "seam_dates": [],
            })
        blocks[list(seen.keys()).index(cs)]["seam_dates"].append(s.isoformat())
    return n, blocks


# ── per-seam run ───────────────────────────────────────────────────────────────

def _run_one_seam(
    seam: datetime.date,
    series_map: Dict[str, List[Tuple[datetime.date, float]]],
    crp_mod,
) -> Optional[dict]:
    """
    For one seam date:
      1. Build TRAIN crises (strict <)
      2. Compute CRP weights using velocities on TRAIN crises
      3. Compute EW weights
      4. Simulate OOS for both
      5. Return result dict or None if no TRAIN crises

    Returns None if seam has no TRAIN crises (can't form a sizer).
    """
    train_crises = [c for c in CRISIS_WINDOWS if c["from"] < seam]
    if not train_crises:
        return None

    # Compute recovery velocities using CRP module helpers
    velocity_map: Dict[str, float] = {}
    for sid in ELIGIBLE_BOOKS:
        vel, _ = crp_mod.recovery_velocity(series_map[sid], train_crises, seam)
        velocity_map[sid] = vel

    # Inf velocities: assign max finite
    finite_vels = [v for v in velocity_map.values() if v != float("inf")]
    max_finite = max(finite_vels) if finite_vels else 1.0
    vel_capped = {k: (v if v != float("inf") else max_finite) for k, v in velocity_map.items()}

    crp_w = crp_mod.normalize_weights(vel_capped)
    ew_w = {sid: 1.0 / len(ELIGIBLE_BOOKS) for sid in ELIGIBLE_BOOKS}

    oos_days = (OOS_END - seam).days
    if oos_days < 30:
        return None  # too short OOS period to be meaningful

    crp_apy, crp_dd, crp_calmar = crp_mod.run_portfolio(series_map, crp_w, seam, OOS_END, ENTRY_TOLL_BPS)
    ew_apy, ew_dd, ew_calmar = crp_mod.run_portfolio(series_map, ew_w, seam, OOS_END, ENTRY_TOLL_BPS)

    return {
        "seam": seam.isoformat(),
        "train_crises": [c["key"] for c in train_crises],
        "crisis_set": list(_train_crisis_set(seam)),
        "oos_days": oos_days,
        "crp_weights": crp_w,
        "crp_apy": round(crp_apy, 4),
        "crp_maxdd": round(crp_dd, 4),
        "crp_calmar": round(crp_calmar, 4) if crp_calmar == crp_calmar else None,
        "ew_apy": round(ew_apy, 4),
        "ew_maxdd": round(ew_dd, 4),
        "ew_calmar": round(ew_calmar, 4) if ew_calmar == ew_calmar else None,
        "delta_apy": round(crp_apy - ew_apy, 4),
        "crp_beats_ew": bool(crp_apy > ew_apy),
    }


# ── Spearman rank correlation ──────────────────────────────────────────────────

def _spearman(a: List[float], b: List[float]) -> Optional[float]:
    """Spearman rank correlation between two equal-length lists. None if degenerate."""
    n = len(a)
    if n < 2:
        return None

    def _rank(xs: List[float]) -> List[float]:
        indexed = sorted(enumerate(xs), key=lambda t: t[1])
        ranks = [0.0] * n
        for rank_idx, (orig_idx, _) in enumerate(indexed):
            ranks[orig_idx] = float(rank_idx + 1)
        return ranks

    ra = _rank(a)
    rb = _rank(b)
    d2 = sum((ra[i] - rb[i]) ** 2 for i in range(n))
    return 1.0 - 6.0 * d2 / (n * (n ** 2 - 1))


# ── OOS overlap computation ────────────────────────────────────────────────────

def _oos_overlap_fraction(seams: List[datetime.date]) -> float:
    """
    Compute mean pairwise OOS overlap fraction across all Block-1 seams.
    Overlap fraction of two OOS periods [S1, END] and [S2, END]:
        overlap = (END - max(S1, S2)).days / (END - min(S1, S2)).days
    = 1.0 if S1==S2, < 1.0 otherwise.
    """
    block1 = [s for s in seams if _train_crisis_set(s) == _train_crisis_set(seams[0])
              and _train_crisis_set(s)]
    if len(block1) < 2:
        return float("nan")
    end_days = OOS_END.toordinal()
    pairs = 0
    total_overlap = 0.0
    for i in range(len(block1)):
        for j in range(i + 1, len(block1)):
            s1 = block1[i].toordinal()
            s2 = block1[j].toordinal()
            shorter = end_days - max(s1, s2)
            longer = end_days - min(s1, s2)
            if longer > 0:
                total_overlap += shorter / longer
                pairs += 1
    return total_overlap / pairs if pairs > 0 else float("nan")


# ── main report ────────────────────────────────────────────────────────────────

def mss_report(data_dir: Path, *, now: Optional[datetime.date] = None) -> dict:
    """Run the full Multi-Seam Stability analysis. Returns a structured report dict."""
    _ = now  # clock injection reserved; not used here (all dates are fixture-static)

    crp_mod = _load_crp_module()

    # Load all series
    series_map: Dict[str, List[Tuple[datetime.date, float]]] = {}
    for sid in ELIGIBLE_BOOKS:
        series_map[sid] = crp_mod.load_backtest_series(data_dir, sid)

    # Independence analysis
    n_independent, blocks = _count_independent_seams(SEAM_DATES)

    # Per-seam results
    seam_results = []
    for s in SEAM_DATES:
        r = _run_one_seam(s, series_map, crp_mod)
        if r is not None:
            seam_results.append(r)

    # Summary stats
    n_beats = sum(1 for r in seam_results if r["crp_beats_ew"])
    n_total = len(seam_results)
    mean_delta = sum(r["delta_apy"] for r in seam_results) / n_total if n_total else float("nan")

    # Block-level aggregation
    block_summaries = []
    seen_cs: Dict[Tuple, List] = {}
    for r in seam_results:
        cs = tuple(r["crisis_set"])
        seen_cs.setdefault(cs, []).append(r)
    for cs_key, cs_results in seen_cs.items():
        deltas = [r["delta_apy"] for r in cs_results]
        beats = sum(1 for r in cs_results if r["crp_beats_ew"])
        # CRP weights identical within block (from same training set)
        rep_weights = cs_results[0]["crp_weights"]
        block_summaries.append({
            "crisis_set": list(cs_key),
            "n_seams_in_block": len(cs_results),
            "n_beats_ew": beats,
            "mean_delta_apy": round(sum(deltas) / len(deltas), 4),
            "representative_crp_weights": {k: round(v, 4) for k, v in rep_weights.items()},
        })

    # Rank stability: for each block with >1 distinct crisis set observation,
    # compare CRP weight rankings between representative seams of each block
    rank_stability = None
    if len(block_summaries) >= 2:
        b1_weights = block_summaries[0]["representative_crp_weights"]
        b2_weights = block_summaries[1]["representative_crp_weights"]
        books_sorted = sorted(b1_weights.keys())
        a_vals = [b1_weights[k] for k in books_sorted]
        b_vals = [b2_weights[k] for k in books_sorted]
        rank_stability = _spearman(a_vals, b_vals)

    # OOS overlap within largest block
    oos_overlap = _oos_overlap_fraction(SEAM_DATES)

    # Identify best and worst seam
    best = max(seam_results, key=lambda r: r["delta_apy"]) if seam_results else None
    worst = min(seam_results, key=lambda r: r["delta_apy"]) if seam_results else None

    verdict = "INSUFFICIENT_EVIDENCE"
    verdict_detail = (
        f"N_independent = {n_independent} (fixture has {n_independent} distinct TRAIN crisis "
        f"configurations out of {n_total} seams evaluated). Within Block-1 ({block_summaries[0]['n_seams_in_block'] if block_summaries else '?'} "
        f"seams), CRP weights are IDENTICAL and OOS periods are nested (mean pairwise overlap "
        f"{oos_overlap:.1%}). Cannot distinguish signal from luck at N=2."
    )

    return {
        "idea": "MSS — Multi-Seam Stability",
        "idea_number": 157,
        "question_answered": (
            "How many independent seam observations does this fixture provide? "
            f"Answer: {n_independent}."
        ),
        "is_advisory": IS_ADVISORY,
        "outside_riskpolicy": OUTSIDE_RISKPOLICY,
        "seam_grid": {
            "start": SEAM_DATES[0].isoformat(),
            "end": SEAM_DATES[-1].isoformat(),
            "n_seams_attempted": len(SEAM_DATES),
            "n_seams_with_train_crises": n_total,
        },
        "independence": {
            "n_independent": n_independent,
            "blocks": block_summaries,
            "oos_overlap_within_block1": round(oos_overlap, 4) if oos_overlap == oos_overlap else None,
            "rank_stability_between_blocks": round(rank_stability, 4) if rank_stability is not None else None,
        },
        "summary_stats": {
            "n_seams_crp_beats_ew": n_beats,
            "n_seams_total": n_total,
            "fraction_crp_beats_ew": round(n_beats / n_total, 4) if n_total else None,
            "mean_delta_apy_pct": round(mean_delta, 4) if mean_delta == mean_delta else None,
            "best_seam": {
                "seam": best["seam"],
                "delta_apy": best["delta_apy"],
                "crisis_set": best["crisis_set"],
            } if best else None,
            "worst_seam": {
                "seam": worst["seam"],
                "delta_apy": worst["delta_apy"],
                "crisis_set": worst["crisis_set"],
            } if worst else None,
        },
        "seam_results": seam_results,
        "verdict": verdict,
        "verdict_detail": verdict_detail,
        "evidence_level": "L0 — backtest on synthetic fixture, NOT realized",
    }


def print_report(r: dict) -> None:
    sep = "─" * 72

    print(f"\n{'=' * 72}")
    print(f"  #157 MSS: Multi-Seam Stability")
    print(f"  IS_ADVISORY=True  OUTSIDE_RISKPOLICY=True  evidence={r['evidence_level']}")
    print(f"{'=' * 72}")

    print(f"\n  ORDER from #155: {r['question_answered']}")
    print(f"  Seam grid: {r['seam_grid']['start']} … {r['seam_grid']['end']}")
    print(f"  Seams attempted: {r['seam_grid']['n_seams_attempted']} | "
          f"with TRAIN crises: {r['seam_grid']['n_seams_with_train_crises']}")

    print(f"\n{sep}")
    print("  INDEPENDENCE ANALYSIS")
    print(sep)
    indep = r["independence"]
    print(f"  N_independent = {indep['n_independent']}")
    if indep.get("oos_overlap_within_block1") is not None:
        print(f"  Mean OOS overlap within Block-1: {indep['oos_overlap_within_block1']:.1%}")
    if indep.get("rank_stability_between_blocks") is not None:
        print(f"  CRP rank stability between blocks (Spearman): "
              f"{indep['rank_stability_between_blocks']:.3f}")

    for i, blk in enumerate(indep["blocks"]):
        print(f"\n  Block {i + 1}: TRAIN = {blk['crisis_set']}")
        print(f"    Seams in block: {blk['n_seams_in_block']}")
        print(f"    CRP beats EW:   {blk['n_beats_ew']} / {blk['n_seams_in_block']}")
        print(f"    Mean ΔAPY:      {blk['mean_delta_apy']:+.2f}%")
        print(f"    CRP weights: " + "  ".join(
            f"{k}={v:.3f}" for k, v in sorted(blk["representative_crp_weights"].items())
        ))

    print(f"\n{sep}")
    print("  SUMMARY STATISTICS (all seams)")
    print(sep)
    stats = r["summary_stats"]
    print(f"  CRP beats EW: {stats['n_seams_crp_beats_ew']} / {stats['n_seams_total']} "
          f"({stats['fraction_crp_beats_ew']:.1%})")
    if stats["mean_delta_apy_pct"] is not None:
        print(f"  Mean ΔAPY (CRP − EW): {stats['mean_delta_apy_pct']:+.2f}%")
    if stats["best_seam"]:
        b = stats["best_seam"]
        print(f"  Best seam:  {b['seam']}  ΔAPY={b['delta_apy']:+.2f}%  TRAIN={b['crisis_set']}")
    if stats["worst_seam"]:
        w = stats["worst_seam"]
        print(f"  Worst seam: {w['seam']}  ΔAPY={w['delta_apy']:+.2f}%  TRAIN={w['crisis_set']}")

    print(f"\n  Selected per-seam results:")
    print(f"  {'Seam':<12} {'TRAIN crises':<35} {'CRP APY':>8} {'EW APY':>8} {'Δ':>7}")
    print(f"  {'-'*12} {'-'*35} {'-'*8} {'-'*8} {'-'*7}")
    for sr in r["seam_results"]:
        cs = ",".join(sr["crisis_set"])
        print(f"  {sr['seam']:<12} {cs:<35} {sr['crp_apy']:>7.2f}% {sr['ew_apy']:>7.2f}% "
              f"{sr['delta_apy']:>+6.2f}%")

    print(f"\n{sep}")
    print(f"  VERDICT: {r['verdict']}")
    print(f"  {r['verdict_detail']}")
    print(sep)


def main() -> int:
    import sys
    from spa_core.strategy_lab.aggressive_lab import fixtures

    with tempfile.TemporaryDirectory() as tmpdir:
        data_dir = fixtures.materialize(Path(tmpdir))
        try:
            report = mss_report(data_dir)
        except Unmeasured as e:
            print(f"UNMEASURED: {e}", file=sys.stderr)
            return 2

    print_report(report)

    # JSON output if requested
    if "--json" in sys.argv:
        # sanitize floats
        def _fix(obj):
            if isinstance(obj, float):
                if obj != obj:
                    return "nan"
                if obj == float("inf"):
                    return "inf"
                if obj == float("-inf"):
                    return "-inf"
                return obj
            if isinstance(obj, dict):
                return {k: _fix(v) for k, v in obj.items()}
            if isinstance(obj, list):
                return [_fix(v) for v in obj]
            return obj
        print(json.dumps(_fix(report), indent=2))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
