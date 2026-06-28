"""Strategy-Lab router — comparative backtest, promotion verdicts, refusal engine,
RWA safety board. Behavior-preserving extraction from server.py; all payloads
(including the clearly-separated rates_desk promotion section and honesty meta)
are byte-identical to the monolith.
"""

from __future__ import annotations

from fastapi import APIRouter

from spa_core.api._shared import (
    _SLEEVE_YIELD_BASIS_NOTE,
    backtest_meta,
    read_state,
    sleeve_yield_basis,
)

router = APIRouter(tags=["strategy_lab"])


@router.get("/api/strategy-lab")
def get_strategy_lab():
    """Strategy-Lab comparative backtest — data/strategy_lab_backtest.json.

    Projects the lab backtest result into the flat shape the site /strategies page consumes.
    Read-only, graceful: returns an empty {} payload (not an error) when the backtest JSON is
    missing/corrupt. Values are passed through VERBATIM from the file — no recomputation here.
    """
    raw = read_state("strategy_lab_backtest.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "strategies": [], "rwa_floor_pct": None,
            "window_start": None, "window_end": None, "generated_at": None,
            "meta": backtest_meta(
                basis="comparative backtest, equal-capital, net-of-cost",
                period="strategy_lab backtest window (see window_start/window_end)",
            ),
        }
    manifest = raw.get("manifest", {}) or {}
    kills = raw.get("kills", {}) or {}
    strategies = []
    for sid, blk in (raw.get("strategies", {}) or {}).items():
        m = blk.get("metrics", {}) or {}
        extra = m.get("extra", {}) or {}
        kill = blk.get("kill") or kills.get(sid)
        sid_key = blk.get("id", sid)
        strategies.append({
            "id": sid_key,
            "name": blk.get("name", sid),
            "mandate": blk.get("mandate", ""),
            "net_apy_pct": m.get("net_apy_pct"),
            "max_drawdown_pct": m.get("max_drawdown_pct"),
            "sharpe": m.get("sharpe"),
            "beta_to_eth": m.get("beta_to_eth"),
            "funding_drag_pct": m.get("funding_drag_pct"),
            "beats_rwa_floor": m.get("beats_rwa_floor"),
            "killed": bool(kill) or bool(extra.get("killed")),
            "kill_reason": (kill or {}).get("reason") if isinstance(kill, dict) else None,
            "yield_basis": sleeve_yield_basis(sid_key),
            "yield_basis_note": _SLEEVE_YIELD_BASIS_NOTE.get(sid_key),
        })
    win_start = manifest.get("window_start")
    win_end = manifest.get("window_end")
    return {
        "strategies": strategies,
        "rwa_floor_pct": manifest.get("rwa_floor_apy_pct"),
        "window_start": win_start,
        "window_end": win_end,
        "generated_at": manifest.get("generated_at"),
        "meta": backtest_meta(
            basis="comparative backtest, equal-capital, net-of-cost; per-sleeve "
                  "yield_basis distinguishes assumed/live_feed/realized",
            period=f"{win_start or '?'} → {win_end or '?'}",
        ),
    }


# ── Rates-Desk promotion section (REPORTING ONLY — NEVER a live-allocation path) ───
_RATES_DESK_SHAPE_LABEL = {
    "fixed_carry": "FixedCarry",
    "levered_carry": "LeveredCarry",
    "basis_hedge": "BasisHedge",
    "rate_matrix": "RateMatrix",
}
_RATES_DESK_ORDER = ("fixed_carry", "levered_carry", "rate_matrix", "basis_hedge")


def _rates_desk_promotion_section() -> dict:
    """Build the clearly-separated `rates_desk` reporting section for /api/strategy-lab/promotion.

    Read VERBATIM from data/rates_desk/rates_desk_promotion.json, enriched with the BasisHedge
    BACKTEST-ONLY funding proxy from data/rates_desk/rates_backtest.json. HARD SEPARATION: every
    sleeve is force-flagged is_advisory=True + live_eligible=False; returned under its own key,
    never merged into the live-pipeline `sleeves` list. Fail-CLOSED + graceful.
    """
    raw = read_state("rates_desk/rates_desk_promotion.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None,
            "model": "rates_desk_promotion",
            "advisory": True,
            "live_eligible": False,
            "rwa_floor_pct": None,
            "n_sleeves": 0,
            "stage_counts": {},
            "sleeves": [],
            "note": ("RATES DESK — reporting only. These sleeves are IS_ADVISORY=True and are "
                     "NEVER routed to the live tournament/allocator before go-live."),
        }

    bt = read_state("rates_desk/rates_backtest.json", {})
    bh_proxy = None
    if isinstance(bt, dict):
        bh_blk = (bt.get("sleeves") or {}).get("basis_hedge")
        if isinstance(bh_blk, dict):
            proxy = bh_blk.get("backtest_proxy")
            if isinstance(proxy, dict):
                bh_proxy = {
                    "net_apy_pct": proxy.get("net_apy_pct"),
                    "mean_apy_pct": proxy.get("mean_apy_pct"),
                    "beats_floor": bool(proxy.get("beats_floor")),
                    "deflated_sharpe": proxy.get("deflated_sharpe"),
                    "carry_days": proxy.get("carry_days"),
                    "hedge_rate_source": proxy.get("hedge_rate_source"),
                    "live_eligible": False,
                    "research_only": True,
                    "label": proxy.get(
                        "label",
                        "BACKTEST-ONLY (funding proxy) · live-BLOCKED until Boros permissionless"),
                }

    in_sleeves = raw.get("sleeves") if isinstance(raw.get("sleeves"), list) else []
    by_shape = {}
    for s in in_sleeves:
        if isinstance(s, dict):
            by_shape[s.get("shape")] = s

    out_sleeves = []
    for shape in _RATES_DESK_ORDER:
        s = by_shape.get(shape)
        if not isinstance(s, dict):
            continue
        sleeve = dict(s)
        sleeve["shape_label"] = _RATES_DESK_SHAPE_LABEL.get(shape, shape)
        sleeve["is_advisory"] = True
        sleeve["live_eligible"] = False
        if shape == "basis_hedge" and bh_proxy is not None:
            sleeve["backtest_proxy"] = bh_proxy
        out_sleeves.append(sleeve)

    stage_counts = {}
    for s in out_sleeves:
        stage_counts[s.get("stage")] = stage_counts.get(s.get("stage"), 0) + 1

    return {
        "generated_at": raw.get("generated_at"),
        "model": raw.get("model", "rates_desk_promotion"),
        "advisory": True,
        "live_eligible": False,
        "rwa_floor_pct": raw.get("rwa_floor_pct"),
        "pipeline": raw.get("pipeline"),
        "n_sleeves": len(out_sleeves),
        "stage_counts": stage_counts,
        "sleeves": out_sleeves,
        "note": ("RATES DESK — reporting only. These four sleeves are IS_ADVISORY=True and are "
                 "NEVER routed to the live tournament/allocator before go-live. BasisHedge is "
                 "live-BLOCKED (no keyless forward-funding venue); its ~4.99% figure is a "
                 "BACKTEST-ONLY funding proxy under backtest_proxy, research-only."),
    }


@router.get("/api/strategy-lab/promotion")
def get_strategy_lab_promotion():
    """Strategy-Lab promotion engine verdicts — data/strategy_lab_promotion.json.

    Carries a clearly-separated `rates_desk` section (REPORTING ONLY — IS_ADVISORY). Read-only,
    graceful: served VERBATIM; empty payload (not an error) when the JSON is missing/corrupt.
    """
    raw = read_state("strategy_lab_promotion.json", {})
    _promo_meta = backtest_meta(
        basis="deterministic promotion rubric over strategy_lab backtest/walk-forward metrics",
        period="strategy_lab backtest window",
    )
    rates_desk = _rates_desk_promotion_section()
    trust, trust_reason = _tournament_trust_verdict()
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None,
            "model": "strategy_lab_promotion",
            "rwa_floor_pct": None,
            "n_sleeves": 0,
            "stage_counts": {},
            "sleeves": [],
            "rates_desk": rates_desk,
            "tournament_trustworthy": trust,
            "tournament_trust_reason": trust_reason,
            "meta": _promo_meta,
        }
    raw.setdefault("meta", _promo_meta)
    raw["rates_desk"] = rates_desk
    # Surface the tournament-trust verdict on the promotion surface so the dashboard's
    # promotion-refusal panel can show "NOT TRUSTWORTHY" WITHOUT a separate fetch. Fail-CLOSED:
    # a missing/unreadable flag → False (a degenerate Sharpe leaderboard is never rendered live).
    raw["tournament_trustworthy"] = trust
    raw["tournament_trust_reason"] = trust_reason
    return raw


def _tournament_trust_verdict() -> tuple[bool, str | None]:
    """The mass-tournament honesty gate, read for the promotion surface. Fail-CLOSED: a missing /
    unreadable trust flag returns (False, None) — a Sharpe leaderboard on near-zero stablecoin vol
    is degenerate, so absence of an explicit trustworthy=True is treated as NOT trustworthy."""
    raw = read_state("mass_tournament_results.json", {})
    if not isinstance(raw, dict):
        return False, None
    trust = raw.get("trustworthy")
    meta = raw.get("meta") if isinstance(raw.get("meta"), dict) else {}
    if trust is None:
        trust = meta.get("trustworthy")
    reason = meta.get("trust_reason")
    return (bool(trust) if trust is not None else False), reason


@router.get("/api/refusal")
def get_refusal():
    """Rates-Desk advisory refusal engine — data/refusal_status.json.

    Per-underlying daily tail-risk verdict (SAFE / WATCH / REFUSE / UNKNOWN). ADVISORY only.
    Read-only, graceful: served VERBATIM; empty payload when the JSON is missing/corrupt.
    """
    raw = read_state("refusal_status.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None,
            "model": "rates_desk_refusal_engine",
            "advisory": True,
            "latest_date": None,
            "thresholds": {},
            "verdict_counts": {},
            "underlyings": [],
        }
    return raw


@router.get("/api/rwa-safety-board")
def get_rwa_safety_board():
    """RWA Collateral Safety Board — data/rwa_safety_board.json.

    Per-asset daily verdict (LIQUID / THIN / REDEMPTION_ONLY / UNSAFE) + marketing-vs-Liquidation-NAV
    gap. ADVISORY / RESEARCH only. Read-only, graceful: served VERBATIM; empty payload when missing/corrupt.
    """
    raw = read_state("rwa_safety_board.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "generated_at": None,
            "model": "rwa_backstop_liquidation_nav",
            "advisory": True,
            "research_only": True,
            "verdict_counts": {},
            "n_assets": 0,
            "onchain_nav_coverage": {
                "enabled": False, "onchain_4626": 0, "off_chain_estimate": 0, "total": 0,
                "assets_onchain": [],
                "note": "board not yet generated → coverage unavailable.",
            },
            "assets": [],
        }
    return raw


@router.get("/api/rwa-nav-curve")
def get_rwa_nav_curve():
    """RWA backstop FORWARD RECORD — data/rwa_nav_curve.json.

    The daily measured-NAV forward series for the RWA collateral thesis: one point per UTC day
    (tvl_weighted_nav, on-chain ERC-4626 vs off-chain-estimate counts, marketing-vs-LiqNAV gap %,
    n_assets), parallel to the rates-desk paper track. Honest framing: measured on-chain NAV
    forward record — ADVISORY / RESEARCH only (no capital). Read-only, graceful: served VERBATIM;
    empty series when missing/corrupt.
    """
    raw = read_state("rwa_nav_curve.json", {})
    if not raw or not isinstance(raw, dict):
        return {
            "id": "rwa_backstop_nav_curve",
            "model": "rwa_backstop_liquidation_nav",
            "framing": "measured on-chain NAV forward record — advisory, paper research (no capital)",
            "advisory": True,
            "research_only": True,
            "generated_at": None,
            "n_points": 0,
            "latest": None,
            "series": [],
        }
    return raw
