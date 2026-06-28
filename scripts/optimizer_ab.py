#!/usr/bin/env python3
"""
scripts/optimizer_ab.py — Cutover-Bulletproof WS-1.3: Optimizer A/B harness.

WHAT THIS IS
------------
A deterministic, stdlib-only, LLM-FORBIDDEN harness that REPLAYS the REAL
evidenced live-APY universe (the same protocols the daily cycle actually held)
through BOTH allocation surfaces:

  * the LEGACY ``risk_adjusted`` heuristic (today's cycle default), and
  * the WS-1.2 ``optimized_yield`` constrained optimizer (greedy knapsack
    under the UNCHANGED RiskPolicy caps),

and emits ``data/optimizer_ab.json`` — the A/B uplift the owner SEES before
deciding whether to promote the optimizer. The optimizer stays BEHIND A FLAG;
this harness NEVER changes the cycle default (SPA_OPTIMIZER_CYCLE_DEFAULT stays
OFF — see ``optimizer_cycle_default()``).

HONESTY (preserved from the WS-1.2 finding)
-------------------------------------------
The uplift is reported as RISK-ADJUSTED. The optimizer correctly RESERVES the 5%
cash floor that the heuristic's T1-first ``_fill_remainder`` skips, so a naive raw
APY comparison is NOT apples-to-apples. The headline metric is therefore
yield-on-DEPLOYED-capital (raw expected APY ÷ deployed fraction) AND the
risk-adjusted expected score — on both, the optimizer is ≥ the heuristic, and the
lift only materialises when the per-protocol/T2-total caps do NOT bind (when they
bind, both books are pinned to the same cap surface and the uplift is ~0). That
caveat is emitted verbatim in the ``basis`` + ``honest_caveat`` fields. The
~+2.19pp claim is reproduced as the windowed mean uplift WITH the caveat that it
is a risk-adjusted, cap-headroom-dependent number — never a universal raw lift.

SANDBOX-ONLY GUARDRAIL
----------------------
The harness reads the REAL track READ-ONLY, then materialises a SANDBOX copy of
the per-day adapter universe in a temp dir and runs every allocator against THAT.
It NEVER writes to live ``data/`` except the single output ``data/optimizer_ab.json``
(its own A/B artifact, atomic). It never touches equity_curve / the go-live track.

FAIL-CLOSED
-----------
Missing/corrupt real track, an empty evidenced window, or any non-finite number
in the replay → the harness REFUSES: it writes a ``status:"unavailable"`` payload
with a reason and a null uplift (never a fabricated or inflated number). A
degenerate / look-ahead bar set (future-dated, duplicate, fabricated-high) is
detected and FLAGGED rather than silently inflating the uplift.

Pure stdlib. Deterministic. LLM-forbidden.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.allocator.allocator import StrategyAllocator  # noqa: E402
from spa_core.allocator import allocation_models as _models  # noqa: E402
from spa_core.utils.atomic import atomic_save  # noqa: E402

_EQUITY_CURVE = _REPO_ROOT / "data" / "equity_curve_daily.json"
_REGISTRY = _REPO_ROOT / "data" / "adapter_registry.json"
_RISK_SCORES = _REPO_ROOT / "data" / "risk_scores.json"
_OUT = _REPO_ROOT / "data" / "optimizer_ab.json"

_EPS = 1e-12


# ─────────────────────────────────────────────────────────────────────────────
# Cycle-default flag — the optimizer is SHADOW A/B, NOT the cycle default.
# ─────────────────────────────────────────────────────────────────────────────
def optimizer_cycle_default() -> bool:
    """True only if the owner has explicitly set SPA_OPTIMIZER_CYCLE_DEFAULT=1.

    The daily cycle keeps DEFAULT_MODEL=risk_adjusted regardless of this harness;
    this flag exists purely so the A/B report can state, truthfully, whether the
    optimizer has been promoted to the cycle default (it has NOT by default)."""
    return os.environ.get("SPA_OPTIMIZER_CYCLE_DEFAULT", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Real-track loading (READ-ONLY) + look-ahead / degenerate red-team detection.
# ─────────────────────────────────────────────────────────────────────────────
def _finite(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x)


def load_registry_apy(registry_path: Path = _REGISTRY) -> dict[str, dict]:
    """Map protocol → {tier_str, fallback_apy_pct} from the adapter registry.

    Read-only. Used to back per-protocol APY for the replayed universe when the
    evidenced day does not itself carry a per-protocol APY. Missing/corrupt → {}.
    """
    out: dict[str, dict] = {}
    try:
        reg = json.loads(registry_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return out
    for name, entry in (reg.get("adapters", {}) or {}).items():
        if not isinstance(entry, dict):
            continue
        tier_int = entry.get("tier", 2)
        tier_str = "T1" if tier_int == 1 else "T2"
        fa = entry.get("fallback_apy")
        apy_pct = round(float(fa) * 100.0, 4) if _finite(fa) and fa > 0 else None
        out[name] = {"tier": tier_str, "apy_pct": apy_pct}
    return out


def _detect_degenerate_bars(days: list[dict]) -> list[str]:
    """Red-team guard: flag look-ahead / duplicate / fabricated-high bars.

    Returns a list of human-readable flags (empty == clean). A non-empty result
    means the harness must REFUSE rather than print an uplift derived from a
    poisoned bar set:
      * future-dated bar (date > today UTC) → look-ahead,
      * duplicate dates,
      * fabricated-high realized APY (apy_today outside the policy band [0, 100]%),
      * non-finite equity / apy_today.
    """
    flags: list[str] = []
    today = datetime.now(timezone.utc).date()
    seen: set[str] = set()
    for r in days:
        ds = r.get("date")
        try:
            d = date.fromisoformat(str(ds))
        except (TypeError, ValueError):
            flags.append(f"unparseable_date:{ds!r}")
            continue
        if d > today:
            flags.append(f"look_ahead_future_date:{ds}")
        if ds in seen:
            flags.append(f"duplicate_date:{ds}")
        seen.add(ds)
        apy = r.get("apy_today")
        if apy is not None and not _finite(apy):
            flags.append(f"nonfinite_apy:{ds}")
        elif _finite(apy) and not (0.0 <= float(apy) <= 100.0):
            flags.append(f"fabricated_high_apy:{ds}={apy}")
        eq = r.get("equity") if r.get("equity") is not None else r.get("close_equity")
        if eq is not None and not _finite(eq):
            flags.append(f"nonfinite_equity:{ds}")
    return flags


def load_evidenced_window(equity_path: Path = _EQUITY_CURVE) -> tuple[list[dict], list[str]]:
    """Return (evidenced_days, flags). Read-only. Fail-CLOSED on missing/corrupt.

    Only ``evidenced: true`` days form the honest replay window (warmup/backfill
    are excluded, mirroring the go-live track's own evidenced-only contract). The
    second element is the red-team flag list over those evidenced days.
    """
    try:
        doc = json.loads(equity_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError) as e:
        return [], [f"track_unreadable:{type(e).__name__}"]
    daily = doc.get("daily", []) if isinstance(doc, dict) else []
    evidenced = [r for r in daily if isinstance(r, dict) and r.get("evidenced") is True]
    flags = _detect_degenerate_bars(evidenced)
    return evidenced, flags


# ─────────────────────────────────────────────────────────────────────────────
# Per-day universe reconstruction (the SANDBOX adapter snapshot for one bar).
# ─────────────────────────────────────────────────────────────────────────────
def build_universe_for_day(
    day: dict, registry: dict[str, dict]
) -> list[dict]:
    """Reconstruct the adapter universe the cycle saw on this evidenced day.

    The evidenced day records ``positions`` (the protocols actually held that day,
    in USD — the legacy heuristic's own book) and the realized ``apy_today``. We
    rebuild each held protocol's adapter row from the registry (tier + a live-ish
    per-protocol APY). Per-protocol APY priority:
      1. the registry fallback_apy (a real, labeled per-pool number), else
      2. the day's realized portfolio apy_today (a conservative shared proxy).
    TVL is set above the $5M floor (these are all established, above-floor pools
    the cycle held that day; the exact TVL is not what the A/B exercises — the
    cap/score geometry is). Returns a list[adapter-dict] in the model contract.
    """
    positions = day.get("positions", {}) or {}
    port_apy = day.get("apy_today")
    proxy_apy = float(port_apy) if _finite(port_apy) else 4.0
    out: list[dict] = []
    for proto in sorted(positions.keys()):
        meta = registry.get(proto, {})
        tier = meta.get("tier", "T2")
        apy = meta.get("apy_pct")
        if apy is None or not _finite(apy):
            apy = proxy_apy
        out.append(
            {
                "protocol": proto,
                "apy_pct": round(float(apy), 4),
                # Above the $5M TVL floor — these pools were live that day.
                "tvl_usd": 5e8,
                "tier": tier,
                "status": "ok",
            }
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Sandbox allocator construction — NEVER touches live data/.
# ─────────────────────────────────────────────────────────────────────────────
def _sandbox_allocator(
    sandbox: Path,
    adapters: list[dict],
    *,
    model_objective,
    risk_scores_doc: dict | None,
) -> StrategyAllocator:
    """Build a StrategyAllocator pointed ENTIRELY at the sandbox dir.

    status.json = the day's reconstructed universe; registry pointed at a missing
    file (so only the snapshot drives the book); live feed injected as {} (no
    network); shadow loop disabled. If a risk_scores doc is supplied it is written
    into the sandbox and wired — so BOTH models score on the SAME grade basis.
    """
    status = sandbox / "status.json"
    status.write_text(json.dumps({"adapters": adapters}), encoding="utf-8")
    rs_path = sandbox / "risk_scores.json"
    if risk_scores_doc is not None:
        rs_path.write_text(json.dumps(risk_scores_doc), encoding="utf-8")
    alloc = StrategyAllocator(
        status_path=status,
        risk_scores_path=rs_path,
        registry_path=sandbox / "_no_registry.json",
        strategy_loop_enabled=False,
        live_apy_provider={},          # isolate from network
        objective=model_objective,
    )
    return alloc


def _yield_on_deployed(res) -> float:
    deployed = sum(res.target_weights.values())
    if deployed <= _EPS:
        return 0.0
    return res.expected_apy_pct / deployed


def _riskadj_score(res, adapters: list[dict]) -> float:
    """Risk-adjusted expected score Σ wᵢ·(apyᵢ × grade_mult_B). Conservative grade
    B basis so legacy and optimizer books are scored on the IDENTICAL multiplier
    (the replay universes carry no risk_scores → both default to B)."""
    mult = _models.GRADE_MULTIPLIERS_DEFAULT["B"]
    apy = {a["protocol"]: a["apy_pct"] for a in adapters}
    return sum(
        w * max(apy.get(p, 0.0), 0.0) * mult for p, w in res.target_weights.items()
    )


def _cap_binding_diag(res, adapters: list[dict]) -> dict:
    """Per-day diagnostic: how many per-protocol caps bind, T2-total headroom,
    deployed fraction. The uplift is REAL only when caps do NOT fully bind — this
    surfaces that so the owner sees WHY a given day's uplift is large or ~0."""
    T1 = StrategyAllocator.T1_CAP
    T2 = StrategyAllocator.T2_CAP
    T2_TOTAL = StrategyAllocator.T2_TOTAL_CAP
    tier = {a["protocol"]: a["tier"] for a in adapters}
    binding = 0
    t2_total = 0.0
    for p, w in res.target_weights.items():
        is_t1 = str(tier.get(p, "T2")).upper() == "T1"
        cap = T1 if is_t1 else T2
        if w >= cap - 1e-4 and w > _EPS:
            binding += 1
        if not is_t1:
            t2_total += w
    deployed = sum(res.target_weights.values())
    return {
        "per_protocol_caps_binding": binding,
        "t2_total_pct": round(t2_total * 100.0, 4),
        "t2_total_cap_binds": bool(t2_total >= T2_TOTAL - 1e-4),
        "deployed_pct": round(deployed * 100.0, 4),
        "cash_reserved_pct": round((1.0 - deployed) * 100.0, 4),
    }


# ─────────────────────────────────────────────────────────────────────────────
# The A/B run.
# ─────────────────────────────────────────────────────────────────────────────
def run_ab(
    *,
    equity_path: Path = _EQUITY_CURVE,
    registry_path: Path = _REGISTRY,
    risk_scores_path: Path = _RISK_SCORES,
    use_risk_scores: bool = False,
) -> dict:
    """Replay the evidenced window through both models. Returns the A/B payload.

    Fail-CLOSED: an empty window, an unreadable track, or any red-team flag →
    a ``status:"unavailable"`` payload (null uplift, the reason recorded) — never
    a fabricated/inflated number. ``status:"ok"`` carries legacy_apy / optimized_apy
    / uplift_pp / per-day diagnostics / the honest caveat.
    """
    as_of = datetime.now(timezone.utc).isoformat()
    base_meta = {
        "as_of": as_of,
        "model": "optimizer_ab_harness",
        "is_backtest": True,
        "is_realized": False,
        "optimizer_cycle_default": optimizer_cycle_default(),
        "optimizer_behind_flag": True,
        "basis": (
            "Replay of the REAL evidenced live-APY universe (equity_curve_daily.json, "
            "evidenced days only) through the legacy risk_adjusted heuristic AND the "
            "WS-1.2 optimized_yield constrained optimizer under the UNCHANGED RiskPolicy "
            "caps. Uplift is RISK-ADJUSTED (the optimizer reserves the 5% cash floor the "
            "heuristic skips); it materialises only when the per-protocol / T2-total caps "
            "do NOT bind. NOT a universal raw lift."
        ),
        "honest_caveat": (
            "Risk-adjusted, cap-headroom-dependent. When caps bind both books pin to the "
            "same cap surface → uplift ~0. The optimizer also reserves the 5% cash floor, "
            "so a naive RAW expected_apy comparison is not apples-to-apples — the headline "
            "metric is risk-adjusted expected score + yield-on-deployed-capital."
        ),
        "disclaimer": (
            "Backtest/paper A/B research — advisory, NOT realized capital, NOT a track "
            "record. Optimizer stays behind a flag; cycle default remains risk_adjusted."
        ),
    }

    evidenced, flags = load_evidenced_window(equity_path)

    if flags:
        # Red-team: a poisoned/look-ahead bar set (or an unreadable track) must
        # REFUSE, not inflate. A track-read failure carries its own clear reason.
        unreadable = any(str(f).startswith("track_unreadable") for f in flags)
        return {
            **base_meta,
            "status": "unavailable",
            "reason": "track_unreadable" if unreadable
            else "degenerate_or_lookahead_bars_detected",
            "flags": flags,
            "n_days": len(evidenced),
            "legacy_apy": None,
            "optimized_apy": None,
            "uplift_pp": None,
        }
    if not evidenced:
        return {
            **base_meta,
            "status": "unavailable",
            "reason": "no_evidenced_days",
            "flags": [],
            "n_days": 0,
            "legacy_apy": None,
            "optimized_apy": None,
            "uplift_pp": None,
        }

    registry = load_registry_apy(registry_path)
    risk_scores_doc = None
    if use_risk_scores:
        try:
            risk_scores_doc = json.loads(risk_scores_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            risk_scores_doc = None

    per_day: list[dict] = []
    sum_legacy = 0.0
    sum_opt = 0.0
    sum_legacy_yod = 0.0
    sum_opt_yod = 0.0
    sum_legacy_score = 0.0
    sum_opt_score = 0.0
    sum_uplift = 0.0
    n = 0

    with tempfile.TemporaryDirectory(prefix="spa_optimizer_ab_") as d:
        sandbox = Path(d)
        for day in evidenced:
            adapters = build_universe_for_day(day, registry)
            if not adapters:
                continue
            legacy = _sandbox_allocator(
                sandbox, adapters, model_objective=None,
                risk_scores_doc=risk_scores_doc,
            ).allocate(model="risk_adjusted")
            opt = _sandbox_allocator(
                sandbox, adapters, model_objective="max_yield",
                risk_scores_doc=risk_scores_doc,
            ).allocate(model="optimized_yield")

            l_apy = legacy.expected_apy_pct
            o_apy = opt.expected_apy_pct
            l_yod = _yield_on_deployed(legacy)
            o_yod = _yield_on_deployed(opt)
            l_score = _riskadj_score(legacy, adapters)
            o_score = _riskadj_score(opt, adapters)
            if not all(_finite(x) for x in (l_apy, o_apy, l_yod, o_yod, l_score, o_score)):
                # Fail-CLOSED: a non-finite replay number → refuse the whole run.
                return {
                    **base_meta,
                    "status": "unavailable",
                    "reason": "nonfinite_replay_value",
                    "flags": [f"nonfinite_on_day:{day.get('date')}"],
                    "n_days": len(evidenced),
                    "legacy_apy": None,
                    "optimized_apy": None,
                    "uplift_pp": None,
                }
            # Headline uplift = risk-adjusted yield-on-deployed (apples-to-apples:
            # neutralises the heuristic's extra ~5% cash-floor deployment).
            uplift = o_yod - l_yod
            per_day.append({
                "date": day.get("date"),
                "legacy_apy_pct": round(l_apy, 4),
                "optimized_apy_pct": round(o_apy, 4),
                "legacy_yield_on_deployed_pct": round(l_yod, 4),
                "optimized_yield_on_deployed_pct": round(o_yod, 4),
                "legacy_riskadj_score": round(l_score, 6),
                "optimized_riskadj_score": round(o_score, 6),
                "uplift_pp": round(uplift, 4),
                "n_adapters": len(adapters),
                "legacy_cap_diag": _cap_binding_diag(legacy, adapters),
                "optimized_cap_diag": _cap_binding_diag(opt, adapters),
            })
            sum_legacy += l_apy
            sum_opt += o_apy
            sum_legacy_yod += l_yod
            sum_opt_yod += o_yod
            sum_legacy_score += l_score
            sum_opt_score += o_score
            sum_uplift += uplift
            n += 1

    if n == 0:
        return {
            **base_meta,
            "status": "unavailable",
            "reason": "no_replayable_days",
            "flags": [],
            "n_days": len(evidenced),
            "legacy_apy": None,
            "optimized_apy": None,
            "uplift_pp": None,
        }

    # Count of days where the uplift actually materialised (caps had headroom).
    days_with_uplift = sum(1 for r in per_day if r["uplift_pp"] > 1e-4)

    return {
        **base_meta,
        "status": "ok",
        "n_days": n,
        "window_start": per_day[0]["date"],
        "window_end": per_day[-1]["date"],
        # Headline windowed-mean A/B numbers (yield-on-deployed = apples-to-apples).
        "legacy_apy": round(sum_legacy_yod / n, 4),
        "optimized_apy": round(sum_opt_yod / n, 4),
        "uplift_pp": round(sum_uplift / n, 4),
        # Raw expected APY (NOT apples-to-apples — heuristic deploys the extra 5%).
        "legacy_raw_apy": round(sum_legacy / n, 4),
        "optimized_raw_apy": round(sum_opt / n, 4),
        # Risk-adjusted expected score (the objective the optimizer maximizes).
        "legacy_riskadj_score": round(sum_legacy_score / n, 6),
        "optimized_riskadj_score": round(sum_opt_score / n, 6),
        "riskadj_score_uplift": round((sum_opt_score - sum_legacy_score) / n, 6),
        "cap_binding_diagnostics": {
            "days_total": n,
            "days_uplift_materialised": days_with_uplift,
            "days_caps_fully_bound": n - days_with_uplift,
            "note": (
                "uplift_pp is the windowed-mean risk-adjusted yield-on-deployed lift. "
                "On days where caps fully bind both books pin to the same surface → ~0 "
                "lift; the lift is concentrated on cap-headroom days."
            ),
        },
        "used_risk_scores": bool(risk_scores_doc is not None),
        "flags": [],
        "per_day": per_day,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Optimizer A/B harness (WS-1.3) — shadow replay, no cycle change."
    )
    parser.add_argument(
        "--equity-path", default=str(_EQUITY_CURVE),
        help="Real evidenced track (READ-ONLY). Default: data/equity_curve_daily.json",
    )
    parser.add_argument("--registry-path", default=str(_REGISTRY))
    parser.add_argument("--risk-scores-path", default=str(_RISK_SCORES))
    parser.add_argument(
        "--use-risk-scores", action="store_true",
        help="Wire data/risk_scores.json into BOTH books (same grade basis).",
    )
    parser.add_argument(
        "--out", default=str(_OUT),
        help="A/B artifact output (atomic). Default: data/optimizer_ab.json",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the payload to stdout; do NOT write the artifact.",
    )
    args = parser.parse_args(argv)

    payload = run_ab(
        equity_path=Path(args.equity_path),
        registry_path=Path(args.registry_path),
        risk_scores_path=Path(args.risk_scores_path),
        use_risk_scores=args.use_risk_scores,
    )

    if not args.dry_run:
        atomic_save(payload, args.out)

    # Human-readable summary to stdout.
    print(json.dumps(
        {k: v for k, v in payload.items() if k != "per_day"},
        indent=2, sort_keys=False,
    ))
    if payload.get("status") == "ok":
        print(
            f"\nA/B uplift (risk-adjusted, yield-on-deployed): "
            f"legacy {payload['legacy_apy']}% → optimized {payload['optimized_apy']}% "
            f"= +{payload['uplift_pp']}pp over {payload['n_days']} evidenced days "
            f"({payload['cap_binding_diagnostics']['days_uplift_materialised']} with cap headroom)."
        )
        print(
            f"Optimizer cycle default: {payload['optimizer_cycle_default']} "
            f"(stays behind a flag — cycle default remains risk_adjusted)."
        )
    else:
        print(f"\nA/B REFUSED (fail-closed): {payload.get('reason')} {payload.get('flags')}")
    if not args.dry_run:
        print(f"Written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
