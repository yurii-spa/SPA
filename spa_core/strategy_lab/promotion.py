"""
spa_core/strategy_lab/promotion.py — the PROMOTION ENGINE for the Strategy Lab.

The missing DECISION layer. The lab backtest (backtest.py) produces an honest, risk-adjusted
comparison of every sleeve vs the live RWA floor (data/strategy_lab_backtest.json). This module
reads that comparison (plus walk-forward + reverse-stress when present), scores EACH sleeve on a
fixed multi-criterion rubric, and assigns each one a STAGE along the promotion pipeline:

    RESEARCH → BACKTEST → WALK-FORWARD → PAPER → CANARY → FULL

A sleeve lands in one of three honest verdicts:
    REJECT          — fails the floor or a hard risk criterion (most crypto sleeves)
    BACKTEST_PASS   — clears the floor + risk IN THE BACKTEST (the stable engines / rwa_sleeve)
    PAPER_CANDIDATE — also walk-forward-robust AND capacity-sufficient → eligible for paper

This is a RISK / GOVERNANCE gate, so it is:
  - DETERMINISTIC — pure arithmetic over the inputs; two runs over the same files are identical.
  - LLM-FORBIDDEN in the decision logic (a gate must never depend on a model's whim).
  - FAIL-CLOSED — a missing/unparseable criterion fails that criterion (never silently passes).
                  No usable backtest record → REJECT (we never promote on absent evidence).
  - CONFIG-DRIVEN — every threshold comes from the SSOT "promotion" block; nothing hardcoded.
  - ATOMIC — the report is written tmp→shutil.move (repo rule #4).

HONESTY: most crypto sleeves (variant_n/d, eth_lst_*, btc_*) do NOT beat the ~3.4% RWA floor on
a risk-adjusted basis and several get killed — they correctly land REJECT. The stable engines
(engine_a/b/c) and rwa_sleeve clear the floor with zero drawdown and pass. We do not fudge the
rubric to make crypto pass.

stdlib only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional

from spa_core.strategy_lab import config as lab_config

_ROOT = Path(__file__).resolve().parents[2]  # …/SPA_Claude
_DATA = _ROOT / "data"
DEFAULT_BACKTEST = _DATA / "strategy_lab_backtest.json"
DEFAULT_WALK_FORWARD = _DATA / "tier1_walk_forward.json"
DEFAULT_REVERSE_STRESS = _DATA / "tier1_reverse_stress.json"
DEFAULT_OUT = _DATA / "strategy_lab_promotion.json"

# Pipeline stages (the canonical promotion ladder, docs/ARCHITECTURE_TIER1.md).
STAGE_REJECT = "REJECT"
STAGE_BACKTEST_PASS = "BACKTEST_PASS"
STAGE_PAPER_CANDIDATE = "PAPER_CANDIDATE"

# Default promotion thresholds — the fail-CLOSED fallback used ONLY if the SSOT config lacks a
# "promotion" block (so a fresh clone / hermetic test still runs). The SSOT block is primary.
_DEFAULT_PROMOTION = {
    "max_drawdown_band_pct": 15.0,
    "wf_consistency_min_pct": 70.0,
    "min_capacity_aum_usd": 1_000_000.0,
    "min_net_apy_pct": 0.0,
    "data_gap_kill_substrings": [
        "missing/invalid",
        "fail-closed (step raised)",
        "missing",
        "no valid",
    ],
}


# ── atomic JSON write (repo rule #4) ──────────────────────────────────────────────────────────
def _atomic_write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix="." + path.stem + "_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(obj, f, indent=2, sort_keys=True)
        shutil.move(tmp, str(path))
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def _read_json(path: Path) -> Optional[dict]:
    """Read a JSON file → dict, or None on missing/corrupt (graceful, fail-closed callers)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


# ── config ─────────────────────────────────────────────────────────────────────────────────────
def promotion_config(config: Optional[dict] = None) -> Dict[str, Any]:
    """The 'promotion' threshold block from the SSOT config (fail-CLOSED merge over defaults).

    Args:
        config: a full lab config dict (lab_config.load_config()). None → load the SSOT.
    Returns a dict carrying every threshold (SSOT value wins; default fills any gap).
    """
    cfg = config if config is not None else lab_config.load_config()
    block = dict(_DEFAULT_PROMOTION)
    user = (cfg or {}).get("promotion")
    if isinstance(user, dict):
        for k in _DEFAULT_PROMOTION:
            if k in user and user[k] is not None:
                block[k] = user[k]
    return block


# ── kill classification ──────────────────────────────────────────────────────────────────────
def _is_data_gap_kill(kill: Optional[dict], gap_substrings: List[str]) -> bool:
    """True if a kill was a DATA-GAP artifact (a fail-closed safe-hold on a missing feed value),
    NOT a genuine risk event (e.g. a drawdown stop). Fail-CLOSED: a kill with no recognisable
    data-gap marker is treated as a REAL kill (the conservative choice for a gate)."""
    if not isinstance(kill, dict):
        return False
    reason = str(kill.get("reason", "")).lower()
    if not reason:
        return False
    return any(sub.lower() in reason for sub in gap_substrings)


# ── single-sleeve score ──────────────────────────────────────────────────────────────────────
def score_sleeve(
    strategy_result: dict,
    walk_forward: Optional[dict] = None,
    reverse_stress: Optional[dict] = None,
    rwa_floor: Optional[float] = None,
    promotion: Optional[dict] = None,
) -> dict:
    """Deterministic, multi-criterion score + criteria breakdown for ONE sleeve.

    Args:
        strategy_result: one entry from strategy_lab_backtest.json["strategies"] — carries
                         {id, mandate, metrics:{net_apy_pct, max_drawdown_pct, beats_rwa_floor,
                         ...}, kill}.
        walk_forward:    optional per-sleeve walk-forward block (tier1_walk_forward.json's
                         per-strategy "walk_forward" sub-dict: {wf_robust, consistency_pct,
                         status}). None / absent → the WF criterion is PENDING (not a pass).
        reverse_stress:  optional per-sleeve capacity source — either a tier1_walk_forward
                         "capacity" block ({max_safe_aum_usd}) or a tier1_reverse_stress block.
        rwa_floor:       the RWA floor APY % the sleeve must beat (header echo; the per-sleeve
                         beats_rwa_floor decision already lives in the backtest metrics).
        promotion:       resolved promotion threshold block (promotion_config()). None → load.

    Returns a dict:
        {id, mandate, score (0..N passed), max_score, criteria:{name:{pass,value,detail}},
         beats_floor, killed, kill_is_data_gap}
    Each criterion is a pass/fail with its value, computed from the SSOT thresholds.
    """
    thr = promotion if promotion is not None else promotion_config()
    band = float(thr["max_drawdown_band_pct"])
    wf_min = float(thr["wf_consistency_min_pct"])
    cap_min = float(thr["min_capacity_aum_usd"])
    napy_min = float(thr["min_net_apy_pct"])
    gap_subs = list(thr.get("data_gap_kill_substrings") or [])

    sid = strategy_result.get("id", "?")
    mandate = strategy_result.get("mandate", "")
    metrics = strategy_result.get("metrics", {}) or {}
    kill = strategy_result.get("kill")

    net_apy = metrics.get("net_apy_pct")
    max_dd = metrics.get("max_drawdown_pct")
    beats = bool(metrics.get("beats_rwa_floor"))

    kill_is_data_gap = _is_data_gap_kill(kill, gap_subs)
    real_kill = bool(kill) and not kill_is_data_gap

    criteria: Dict[str, dict] = {}

    # (1) beats the RWA floor on a RISK-ADJUSTED basis (the backtest already computed this).
    criteria["beats_rwa_floor"] = {
        "pass": beats,
        "value": beats,
        "detail": "risk-adjusted excess over the RWA floor must be positive and cover drawdown",
    }

    # (2) max drawdown within the configured band.
    dd_pass = max_dd is not None and float(max_dd) <= band
    criteria["drawdown_within_band"] = {
        "pass": bool(dd_pass),
        "value": None if max_dd is None else round(float(max_dd), 4),
        "detail": f"max drawdown must be <= {band:.2f}%",
    }

    # (3) NOT killed by a REAL risk event in the deep window (a data-gap kill is tolerated —
    #     it is a safe-hold on a missing feed value, not a strategy risk failure).
    not_real_kill = not real_kill
    if not kill:
        kdetail = "no kill in the deep window"
    elif kill_is_data_gap:
        kdetail = "killed by a DATA-GAP (fail-closed safe-hold), not a real risk event — tolerated"
    else:
        kdetail = f"REAL risk kill: {str((kill or {}).get('reason',''))[:120]}"
    criteria["not_killed_real"] = {
        "pass": bool(not_real_kill),
        "value": None if not kill else str((kill or {}).get("reason", ""))[:160],
        "detail": kdetail,
    }

    # (4) walk-forward consistency >= threshold (only when WF data is present; else PENDING).
    # Accept BOTH the flattened shape ({status, consistency_pct, wf_robust, capacity}) AND the
    # tier1_walk_forward per-strategy schema ({walk_forward:{...}, capacity:{...}}).
    wf_outer = walk_forward or {}
    wf = wf_outer.get("walk_forward") if isinstance(wf_outer.get("walk_forward"), dict) else wf_outer
    wf_status = wf.get("status")
    wf_consistency = wf.get("consistency_pct")
    wf_robust = wf.get("wf_robust")
    if wf and wf_status == "ok" and wf_consistency is not None:
        wf_pass = float(wf_consistency) >= wf_min and bool(wf_robust)
        wf_value = round(float(wf_consistency), 4)
        wf_detail = f"walk-forward consistency must be >= {wf_min:.1f}% and wf_robust=True"
    else:
        # No usable WF evidence → this criterion does NOT pass (fail-closed) but is flagged
        # PENDING so the verdict can still award BACKTEST_PASS on the backtest-only criteria.
        wf_pass = False
        wf_value = wf_consistency
        wf_detail = "walk-forward evidence absent/insufficient (PENDING — not yet validated)"
    criteria["walk_forward_robust"] = {
        "pass": bool(wf_pass),
        "value": wf_value,
        "pending": not (wf and wf_status == "ok" and wf_consistency is not None),
        "detail": wf_detail,
    }

    # (5) capacity >= the minimum AUM (from a walk_forward "capacity" block or reverse_stress).
    cap_aum = _capacity_aum(walk_forward, reverse_stress)
    if cap_aum is None:
        cap_pass = False
        cap_pending = True
        cap_detail = "capacity evidence absent (PENDING — not yet sized)"
    else:
        cap_pass = float(cap_aum) >= cap_min
        cap_pending = False
        cap_detail = f"max safe AUM must be >= ${cap_min:,.0f}"
    criteria["capacity_sufficient"] = {
        "pass": bool(cap_pass),
        "value": None if cap_aum is None else round(float(cap_aum), 2),
        "pending": cap_pending,
        "detail": cap_detail,
    }

    # (6) positive net APY (a floor sanity check independent of the risk-adjusted decision).
    napy_pass = net_apy is not None and float(net_apy) > napy_min
    criteria["positive_net_apy"] = {
        "pass": bool(napy_pass),
        "value": None if net_apy is None else round(float(net_apy), 4),
        "detail": f"net APY must be > {napy_min:.2f}%",
    }

    score = sum(1 for c in criteria.values() if c["pass"])
    return {
        "id": sid,
        "mandate": mandate,
        "score": score,
        "max_score": len(criteria),
        "criteria": criteria,
        "beats_floor": beats,
        "killed": bool(kill),
        "kill_is_data_gap": kill_is_data_gap,
        "net_apy_pct": None if net_apy is None else round(float(net_apy), 4),
        "max_drawdown_pct": None if max_dd is None else round(float(max_dd), 4),
    }


def _capacity_aum(
    walk_forward: Optional[dict], reverse_stress: Optional[dict]
) -> Optional[float]:
    """Best-available max-safe-AUM for a sleeve, in USD. Prefers the walk_forward "capacity"
    block; falls back to a reverse_stress block if it carries an AUM figure. None when neither
    exposes a usable number (fail-closed: absent capacity is not 'unlimited')."""
    wf = walk_forward or {}
    cap = wf.get("capacity")
    if isinstance(cap, dict):
        aum = cap.get("max_safe_aum_usd")
        if aum is not None:
            return float(aum)
    rs = reverse_stress or {}
    # reverse_stress carries a principal-loss profile, not an AUM, but honor an explicit AUM key
    # if a future schema adds one (keeps the contract forward-compatible, still fail-closed).
    for key in ("max_safe_aum_usd", "capacity_aum_usd"):
        if rs.get(key) is not None:
            return float(rs[key])
    return None


# ── verdict ────────────────────────────────────────────────────────────────────────────────────
def promotion_verdict(score: dict) -> dict:
    """Assign a pipeline STAGE + honest reasoning from a score_sleeve() result.

    Ladder (RESEARCH → BACKTEST → WALK-FORWARD → PAPER → CANARY → FULL):

      REJECT          — fails the floor OR a hard risk criterion (real kill / drawdown band /
                        non-positive net APY). It never even clears BACKTEST.
      BACKTEST_PASS   — clears the floor + ALL risk criteria in the backtest, but is not yet
                        walk-forward-robust AND capacity-sized (those are PENDING or failing).
      PAPER_CANDIDATE — BACKTEST_PASS *and* walk-forward-robust *and* capacity-sufficient →
                        graduate to the PAPER stage of the pipeline.

    Returns {stage, reason} added onto a copy of the score dict's verdict view (the caller
    merges these into the sleeve record)."""
    c = score["criteria"]
    beats = c["beats_rwa_floor"]["pass"]
    dd_ok = c["drawdown_within_band"]["pass"]
    not_real_kill = c["not_killed_real"]["pass"]
    napy_ok = c["positive_net_apy"]["pass"]
    wf_ok = c["walk_forward_robust"]["pass"]
    cap_ok = c["capacity_sufficient"]["pass"]

    # Hard backtest gate: floor + every risk criterion must hold.
    backtest_clears = beats and dd_ok and not_real_kill and napy_ok

    if not backtest_clears:
        fails = []
        if not beats:
            fails.append("does not beat the RWA floor (risk-adjusted)")
        if not napy_ok:
            v = c["positive_net_apy"]["value"]
            fails.append(f"net APY not positive ({v}%)" if v is not None else "net APY missing")
        if not dd_ok:
            v = c["drawdown_within_band"]["value"]
            fails.append(f"drawdown {v}% breaches the band" if v is not None else "drawdown missing")
        if not not_real_kill:
            fails.append("killed by a real risk event in the deep window")
        stage = STAGE_REJECT
        reason = "REJECT — " + "; ".join(fails)
        return {"stage": stage, "reason": reason}

    # Cleared the backtest. Walk-forward + capacity decide PAPER eligibility.
    if wf_ok and cap_ok:
        stage = STAGE_PAPER_CANDIDATE
        reason = (
            "PAPER_CANDIDATE — clears the RWA floor + risk in the backtest, is walk-forward "
            f"robust ({c['walk_forward_robust']['value']}% consistency) and capacity-sufficient "
            f"(max safe AUM ${c['capacity_sufficient']['value']:,.0f}); eligible for the PAPER stage"
        )
        return {"stage": stage, "reason": reason}

    pend = []
    if not wf_ok:
        if c["walk_forward_robust"].get("pending"):
            pend.append("walk-forward not yet validated (PENDING)")
        else:
            pend.append(
                f"walk-forward not robust ({c['walk_forward_robust']['value']}% consistency)"
            )
    if not cap_ok:
        if c["capacity_sufficient"].get("pending"):
            pend.append("capacity not yet sized (PENDING)")
        else:
            v = c["capacity_sufficient"]["value"]
            pend.append(f"capacity below the minimum AUM (${v:,.0f})" if v is not None else "capacity unknown")
    stage = STAGE_BACKTEST_PASS
    reason = "BACKTEST_PASS — clears the RWA floor + risk in the backtest; " + "; ".join(pend)
    return {"stage": stage, "reason": reason}


# ── walk-forward / reverse-stress lookup ────────────────────────────────────────────────────────
def _wf_for_sleeve(sleeve_id: str, wf_doc: Optional[dict]) -> Optional[dict]:
    """Find a per-sleeve walk-forward block (carrying both walk_forward + capacity) in
    tier1_walk_forward.json. The WF doc is keyed by tournament-strategy ids (s27/s65/…) and
    'live_portfolio', NOT by lab sleeve ids — so a lab sleeve usually has no match (→ None,
    meaning its WF/capacity criteria stay PENDING). Honest: we never fabricate WF evidence."""
    if not isinstance(wf_doc, dict):
        return None
    strategies = wf_doc.get("strategies")
    if isinstance(strategies, dict) and sleeve_id in strategies:
        return strategies[sleeve_id]
    if sleeve_id in wf_doc and isinstance(wf_doc[sleeve_id], dict):
        return wf_doc[sleeve_id]
    return None


def _rs_for_sleeve(sleeve_id: str, rs_doc: Optional[dict]) -> Optional[dict]:
    """Find a per-sleeve reverse-stress block in tier1_reverse_stress.json (same id-mismatch
    caveat as walk-forward → usually None for lab sleeves)."""
    if not isinstance(rs_doc, dict):
        return None
    strategies = rs_doc.get("strategies")
    if isinstance(strategies, dict) and sleeve_id in strategies:
        return strategies[sleeve_id].get("reverse_stress") or strategies[sleeve_id]
    return None


# ── full report ──────────────────────────────────────────────────────────────────────────────
def build_report(
    write: bool = True,
    backtest_path: Optional[Path] = None,
    walk_forward_path: Optional[Path] = None,
    reverse_stress_path: Optional[Path] = None,
    out_path: Optional[Path] = None,
    config: Optional[dict] = None,
    backtest: Optional[dict] = None,
) -> dict:
    """Score ALL sleeves in the lab comparison, assign each a stage, and (optionally) write
    data/strategy_lab_promotion.json atomically.

    Args:
        write:               write the JSON when True (default). False = compute only.
        backtest_path:       override the backtest JSON path (tests/hermetic).
        walk_forward_path:   override the walk-forward JSON path.
        reverse_stress_path: override the reverse-stress JSON path.
        out_path:            override the output path.
        config:              a full lab config dict (tests/hermetic). None → load the SSOT.
        backtest:            an injected backtest result dict (tests/determinism). When given it
                             is used verbatim and backtest_path is ignored.

    Returns the report dict:
        {generated_at, rwa_floor_pct, thresholds, n_sleeves, stage_counts,
         sleeves:[{id, mandate, stage, score, max_score, criteria:{...}, reason, ...}]}
    Fail-CLOSED: a missing backtest → an empty sleeves list (we never promote on no evidence).
    """
    thr = promotion_config(config)
    bt = backtest if backtest is not None else _read_json(Path(backtest_path) if backtest_path else DEFAULT_BACKTEST)
    wf_doc = _read_json(Path(walk_forward_path) if walk_forward_path else DEFAULT_WALK_FORWARD)
    rs_doc = _read_json(Path(reverse_stress_path) if reverse_stress_path else DEFAULT_REVERSE_STRESS)

    generated_at = datetime.datetime.now(datetime.timezone.utc).isoformat()
    rwa_floor = None
    sleeves: List[dict] = []

    if isinstance(bt, dict):
        manifest = bt.get("manifest", {}) or {}
        rwa_floor = manifest.get("rwa_floor_apy_pct")
        strategies = bt.get("strategies", {}) or {}
        # benchmark row (rwa_floor) is the reference, not a promotable sleeve — exclude it.
        for sid in sorted(strategies.keys()):
            blk = strategies[sid]
            if not isinstance(blk, dict):
                continue
            if blk.get("is_benchmark"):
                continue
            wf = _wf_for_sleeve(sid, wf_doc)
            rs = _rs_for_sleeve(sid, rs_doc)
            score = score_sleeve(
                blk,
                walk_forward=wf,
                reverse_stress=rs,
                rwa_floor=rwa_floor,
                promotion=thr,
            )
            verdict = promotion_verdict(score)
            sleeve = dict(score)
            sleeve["stage"] = verdict["stage"]
            sleeve["reason"] = verdict["reason"]
            sleeves.append(sleeve)

    stage_counts: Dict[str, int] = {
        STAGE_REJECT: 0,
        STAGE_BACKTEST_PASS: 0,
        STAGE_PAPER_CANDIDATE: 0,
    }
    for s in sleeves:
        stage_counts[s["stage"]] = stage_counts.get(s["stage"], 0) + 1

    report = {
        "generated_at": generated_at,
        "model": "strategy_lab_promotion",
        "llm_forbidden": True,
        "rwa_floor_pct": rwa_floor,
        "pipeline": "RESEARCH -> BACKTEST -> WALK-FORWARD -> PAPER -> CANARY -> FULL",
        "thresholds": thr,
        "n_sleeves": len(sleeves),
        "stage_counts": stage_counts,
        "sleeves": sleeves,
    }

    if write:
        _atomic_write_json(Path(out_path) if out_path else DEFAULT_OUT, report)
    return report


# ── CLI table ────────────────────────────────────────────────────────────────────────────────
def _print_table(report: dict) -> None:
    floor = report.get("rwa_floor_pct")
    floor_s = f"{floor:.2f}%" if isinstance(floor, (int, float)) else "—"
    print(f"Strategy Lab — Promotion Engine   (RWA floor {floor_s})")
    print(f"Pipeline: {report.get('pipeline')}")
    print(
        f"Sleeves: {report.get('n_sleeves')}   "
        f"REJECT={report['stage_counts'].get(STAGE_REJECT, 0)}  "
        f"BACKTEST_PASS={report['stage_counts'].get(STAGE_BACKTEST_PASS, 0)}  "
        f"PAPER_CANDIDATE={report['stage_counts'].get(STAGE_PAPER_CANDIDATE, 0)}"
    )
    print()
    hdr = f"{'sleeve':22s} {'mandate':11s} {'stage':16s} {'score':6s} {'napy%':>8s} {'dd%':>7s}  reason"
    print(hdr)
    print("-" * len(hdr))
    # order: PAPER_CANDIDATE, BACKTEST_PASS, REJECT — then by id.
    order = {STAGE_PAPER_CANDIDATE: 0, STAGE_BACKTEST_PASS: 1, STAGE_REJECT: 2}
    for s in sorted(report.get("sleeves", []), key=lambda x: (order.get(x["stage"], 9), x["id"])):
        napy = s.get("net_apy_pct")
        dd = s.get("max_drawdown_pct")
        napy_s = f"{napy:8.3f}" if isinstance(napy, (int, float)) else f"{'—':>8s}"
        dd_s = f"{dd:7.3f}" if isinstance(dd, (int, float)) else f"{'—':>7s}"
        score_s = f"{s['score']}/{s['max_score']}"
        print(
            f"{s['id']:22s} {s['mandate']:11s} {s['stage']:16s} {score_s:6s} "
            f"{napy_s} {dd_s}  {s['reason']}"
        )


def main() -> int:
    report = build_report(write=True)
    _print_table(report)
    print(f"\nWrote {DEFAULT_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
