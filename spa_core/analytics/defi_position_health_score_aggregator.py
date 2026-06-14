"""
MP-968: DeFiPositionHealthScoreAggregator
Aggregates DeFi position health across lending/lp/staking/perp/vault into
a single portfolio-wide health score. Advisory/read-only. Pure stdlib only.

CLI:
    python3 -m spa_core.analytics.defi_position_health_score_aggregator --check
    python3 -m spa_core.analytics.defi_position_health_score_aggregator --run [--data-dir data]
"""

import json
import os
import sys
from datetime import datetime, timezone

DATA_FILE = "data/position_health_log.json"
LOG_CAP = 100

DEFAULT_CONFIG: dict = {
    "log_path": DATA_FILE,
    "log_cap": LOG_CAP,
    # Weighted-health thresholds for portfolio label
    "health_thresholds": {
        "excellent": 80.0,
        "healthy": 60.0,
        "moderate": 40.0,
        "at_risk": 20.0,
    },
    # Any position below this → IMMINENT_LIQUIDATION flag
    "liquidation_imminent_threshold": 10.0,
    # One protocol > this % of total → SINGLE_PROTOCOL_CONCENTRATION flag
    "concentration_threshold_pct": 50.0,
    # Fewer than this many distinct types → UNDIVERSIFIED flag
    "min_diversification_types": 3,
    # LP portion of portfolio > this % → HIGH_IL_EXPOSURE flag
    "lp_exposure_threshold_pct": 40.0,
    # Position open longer than this → STALE_POSITION flag
    "stale_position_days": 365,
    # Positions below this health → counted as at_risk
    "at_risk_health_threshold": 30.0,
}


# ---------------------------------------------------------------------------
# Scoring helpers (module-level, testable independently)
# ---------------------------------------------------------------------------

def _score_health_factor(hf: float) -> float:
    """
    Map Aave-style health factor to a 0-100 score.

    hf < 1.0   → 0   (liquidated / below water)
    hf 1.0–1.05 → 0–5
    hf 1.05–1.1 → 5–15
    hf 1.1–1.2  → 15–30
    hf 1.2–1.5  → 30–80
    hf 1.5–2.0  → 80–95
    hf ≥ 2.0    → 95–100 (capped at 100)
    """
    if hf < 1.0:
        return 0.0
    if hf < 1.05:
        return (hf - 1.0) / 0.05 * 5.0
    if hf < 1.1:
        return 5.0 + (hf - 1.05) / 0.05 * 10.0
    if hf < 1.2:
        return 15.0 + (hf - 1.1) / 0.1 * 15.0
    if hf < 1.5:
        return 30.0 + (hf - 1.2) / 0.3 * 50.0
    if hf < 2.0:
        return 80.0 + (hf - 1.5) / 0.5 * 15.0
    return min(100.0, 95.0 + (hf - 2.0) * 2.5)


def _score_liquidation_distance(liq_dist_pct: float) -> float:
    """
    Map liquidation_distance_pct (0=at liq, 100=far away) to a 0-100 score.
    Simple linear: score = min(100, liq_dist_pct * 2).
    """
    return min(100.0, max(0.0, liq_dist_pct * 2.0))


def _score_il(il_pct: float) -> float:
    """
    Map impermanent loss % to 0-100 score.
    0% IL → 100, 20% IL → 0 (linear penalty of 5 per IL %).
    """
    return max(0.0, 100.0 - il_pct * 5.0)


def _apy_penalty(apy_net_pct: float) -> float | None:
    """
    Return a cap score when APY is negative (position losing money).
    Positive APY returns None (no cap needed, handled as bonus separately).

    Penalty: 50 + apy*5 (so -10% APY → 0, -2% → 40, 0% → 50).
    """
    if apy_net_pct < 0:
        return max(0.0, 50.0 + apy_net_pct * 5.0)
    return None


def _stale_penalty(days_open: int, stale_days: int) -> float | None:
    """
    Return a cap score when position is stale (open > stale_days).
    Each day beyond the threshold reduces cap by 0.1 (floor 0).
    """
    if days_open > stale_days:
        excess = days_open - stale_days
        return max(0.0, 80.0 - excess * 0.1)
    return None


def _score_position(pos: dict, cfg: dict) -> dict:
    """
    Score a single position (0-100, 100=perfect, 0=critical).

    Returns enriched dict with `position_health_score` and `score_components`.
    """
    ptype = pos.get("type", "unknown")
    score = 100.0
    components: dict = {}

    # ── Liquidation distance (all types where provided) ─────────────────────
    liq_dist = pos.get("liquidation_distance_pct")
    if liq_dist is not None:
        liq_score = _score_liquidation_distance(float(liq_dist))
        components["liquidation_distance"] = liq_score
        score = min(score, liq_score)

    # ── Lending-specific: health factor + collateral ratio ───────────────────
    if ptype == "lending":
        hf = pos.get("health_factor")
        if hf is not None:
            hf_score = _score_health_factor(float(hf))
            components["health_factor"] = hf_score
            score = min(score, hf_score)

        cr = pos.get("collateral_ratio_pct")
        if cr is not None:
            # Below 110% → meaningful penalty; >150% → negligible
            cr_raw = float(cr)
            if cr_raw < 110.0:
                cr_score = max(0.0, (cr_raw - 100.0) * 10.0)  # 0..100 for 100..110
                components["collateral_ratio"] = cr_score
                score = min(score, cr_score)

    # ── LP-specific: impermanent loss ───────────────────────────────────────
    if ptype == "lp":
        il = pos.get("il_pct")
        il_val = float(il) if il is not None else 0.0
        il_score = _score_il(il_val)
        components["il_score"] = il_score
        score = min(score, il_score)

    # ── APY net: negative = penalty, positive = small bonus ─────────────────
    apy = pos.get("apy_net_pct")
    if apy is not None:
        apy_val = float(apy)
        penalty = _apy_penalty(apy_val)
        if penalty is not None:
            components["apy_penalty"] = penalty
            score = min(score, penalty)
        elif apy_val > 0:
            bonus = min(10.0, apy_val * 0.5)
            components["apy_bonus"] = bonus
            # bonus does not increase score beyond current, just logged

    # ── Staleness ────────────────────────────────────────────────────────────
    days_open = pos.get("days_open")
    stale_days = int(cfg.get("stale_position_days", DEFAULT_CONFIG["stale_position_days"]))
    if days_open is not None:
        sp = _stale_penalty(int(days_open), stale_days)
        if sp is not None:
            components["stale_penalty"] = sp
            score = min(score, sp)

    # ── External risk score (optional) ───────────────────────────────────────
    ext_risk = pos.get("risk_score_0_100")
    if ext_risk is not None:
        inverted = 100.0 - float(ext_risk)
        components["external_risk_inverted"] = inverted
        # Blend: 70% current, 30% external inverted
        score = 0.7 * score + 0.3 * inverted

    # ── Clamp ────────────────────────────────────────────────────────────────
    score = max(0.0, min(100.0, score))

    return {
        "id": pos.get("id", "unknown"),
        "type": ptype,
        "protocol": pos.get("protocol", "unknown"),
        "value_usd": float(pos.get("value_usd", 0.0)),
        "position_health_score": round(score, 4),
        "score_components": components,
    }


def _portfolio_label(weighted_health: float, thresholds: dict) -> str:
    if weighted_health > thresholds["excellent"]:
        return "EXCELLENT"
    if weighted_health > thresholds["healthy"]:
        return "HEALTHY"
    if weighted_health > thresholds["moderate"]:
        return "MODERATE"
    if weighted_health > thresholds["at_risk"]:
        return "AT_RISK"
    return "CRITICAL"


def _compute_flags(
    positions: list,
    scored: list,
    total_value_usd: float,
    type_values: dict,
    cfg: dict,
) -> list:
    flags = []

    # SINGLE_PROTOCOL_CONCENTRATION (>50% in one protocol)
    conc_thresh = float(cfg.get("concentration_threshold_pct",
                                DEFAULT_CONFIG["concentration_threshold_pct"])) / 100.0
    if total_value_usd > 0:
        proto_vals: dict = {}
        for pos in positions:
            proto = pos.get("protocol", "unknown")
            proto_vals[proto] = proto_vals.get(proto, 0.0) + float(pos.get("value_usd", 0.0))
        for val in proto_vals.values():
            if val / total_value_usd > conc_thresh:
                flags.append("SINGLE_PROTOCOL_CONCENTRATION")
                break

    # IMMINENT_LIQUIDATION (any health < threshold)
    imm_thresh = float(cfg.get("liquidation_imminent_threshold",
                               DEFAULT_CONFIG["liquidation_imminent_threshold"]))
    if any(sp["position_health_score"] < imm_thresh for sp in scored):
        flags.append("IMMINENT_LIQUIDATION")

    # UNDIVERSIFIED (<3 position types)
    min_types = int(cfg.get("min_diversification_types",
                            DEFAULT_CONFIG["min_diversification_types"]))
    if len(type_values) < min_types:
        flags.append("UNDIVERSIFIED")

    # HIGH_IL_EXPOSURE (LP > 40% of portfolio)
    lp_thresh = float(cfg.get("lp_exposure_threshold_pct",
                              DEFAULT_CONFIG["lp_exposure_threshold_pct"])) / 100.0
    lp_value = sum(float(pos.get("value_usd", 0.0))
                   for pos in positions if pos.get("type") == "lp")
    if total_value_usd > 0 and lp_value / total_value_usd > lp_thresh:
        flags.append("HIGH_IL_EXPOSURE")

    # STALE_POSITION (any position > stale_days without review)
    stale_days = int(cfg.get("stale_position_days", DEFAULT_CONFIG["stale_position_days"]))
    if any(int(pos.get("days_open", 0)) > stale_days for pos in positions):
        flags.append("STALE_POSITION")

    return flags


def _append_log(result: dict, cfg: dict) -> None:
    """Append summary to ring-buffer log; atomic write."""
    log_path = cfg.get("log_path", DATA_FILE)
    cap = int(cfg.get("log_cap", LOG_CAP))

    dir_name = os.path.dirname(log_path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    try:
        with open(log_path, "r", encoding="utf-8") as fh:
            log = json.load(fh)
        if not isinstance(log, list):
            log = []
    except Exception:
        log = []

    agg = result.get("aggregates", {})
    entry = {
        "timestamp": result.get("timestamp"),
        "portfolio_label": result.get("portfolio_label"),
        "weighted_portfolio_health": result.get("weighted_portfolio_health"),
        "weakest_link_score": result.get("weakest_link_score"),
        "flags": result.get("flags", []),
        "position_count": agg.get("position_count", 0),
    }
    log.append(entry)

    if len(log) > cap:
        log = log[-cap:]

    tmp = log_path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, log_path)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class DeFiPositionHealthScoreAggregator:
    """
    Aggregates health of all open DeFi positions into a single portfolio score.

    Usage::

        aggregator = DeFiPositionHealthScoreAggregator()
        result = aggregator.aggregate(positions, config)
    """

    def aggregate(self, positions: list, config: dict | None = None) -> dict:
        """
        Aggregate position health.

        Parameters
        ----------
        positions : list[dict]
            Each dict may contain:
            - id: str
            - type: "lending" | "lp" | "staking" | "perp" | "vault"
            - protocol: str
            - value_usd: float
            - health_factor: float | None  (lending only)
            - il_pct: float | None         (lp only)
            - liquidation_distance_pct: float | None
            - apy_net_pct: float
            - days_open: int
            - collateral_ratio_pct: float | None
            - risk_score_0_100: float | None

        config : dict | None
            Overrides for DEFAULT_CONFIG keys.

        Returns
        -------
        dict with keys:
            positions, weighted_portfolio_health, weakest_link_score,
            diversification_score, total_at_risk_usd, portfolio_label,
            flags, aggregates, timestamp
        """
        cfg: dict = {**DEFAULT_CONFIG, **(config or {})}

        if not positions:
            return self._empty_result(cfg)

        # ── Score each position ───────────────────────────────────────────
        scored = [_score_position(p, cfg) for p in positions]

        # ── Portfolio-level metrics ───────────────────────────────────────
        total_value_usd = sum(float(p.get("value_usd", 0.0)) for p in positions)

        if total_value_usd > 0:
            weighted_health = sum(
                sp["position_health_score"] * float(p.get("value_usd", 0.0))
                for sp, p in zip(scored, positions)
            ) / total_value_usd
        else:
            weighted_health = (
                sum(sp["position_health_score"] for sp in scored) / len(scored)
                if scored else 0.0
            )

        weakest_link_score = min(sp["position_health_score"] for sp in scored)
        weakest_position = min(scored, key=lambda x: x["position_health_score"])
        strongest_position = max(scored, key=lambda x: x["position_health_score"])

        # ── Diversification score (1 – HHI by position type) × 100 ──────
        type_values: dict = {}
        for p in positions:
            t = p.get("type", "unknown")
            type_values[t] = type_values.get(t, 0.0) + float(p.get("value_usd", 0.0))

        if total_value_usd > 0:
            hhi = sum((v / total_value_usd) ** 2 for v in type_values.values())
        else:
            hhi = 1.0
        diversification_score = (1.0 - hhi) * 100.0

        # ── At-risk metrics ───────────────────────────────────────────────
        at_risk_thresh = float(cfg.get("at_risk_health_threshold",
                                       DEFAULT_CONFIG["at_risk_health_threshold"]))
        total_at_risk_usd = sum(
            float(p.get("value_usd", 0.0))
            for sp, p in zip(scored, positions)
            if sp["position_health_score"] < at_risk_thresh
        )
        positions_at_risk_count = sum(
            1 for sp in scored if sp["position_health_score"] < at_risk_thresh
        )

        average_health_score = sum(sp["position_health_score"] for sp in scored) / len(scored)

        # ── Label & flags ─────────────────────────────────────────────────
        thresholds = cfg.get("health_thresholds", DEFAULT_CONFIG["health_thresholds"])
        label = _portfolio_label(weighted_health, thresholds)
        flags = _compute_flags(positions, scored, total_value_usd, type_values, cfg)

        result = {
            "positions": scored,
            "weighted_portfolio_health": round(weighted_health, 4),
            "weakest_link_score": round(weakest_link_score, 4),
            "diversification_score": round(diversification_score, 4),
            "total_at_risk_usd": round(total_at_risk_usd, 4),
            "portfolio_label": label,
            "flags": flags,
            "aggregates": {
                "weakest_position": weakest_position,
                "strongest_position": strongest_position,
                "total_value_usd": round(total_value_usd, 4),
                "positions_at_risk_count": positions_at_risk_count,
                "average_health_score": round(average_health_score, 4),
                "position_count": len(positions),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        _append_log(result, cfg)
        return result

    # ------------------------------------------------------------------
    def _empty_result(self, cfg: dict) -> dict:
        return {
            "positions": [],
            "weighted_portfolio_health": 0.0,
            "weakest_link_score": 0.0,
            "diversification_score": 0.0,
            "total_at_risk_usd": 0.0,
            "portfolio_label": "CRITICAL",
            "flags": [],
            "aggregates": {
                "weakest_position": None,
                "strongest_position": None,
                "total_value_usd": 0.0,
                "positions_at_risk_count": 0,
                "average_health_score": 0.0,
                "position_count": 0,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _sample_positions() -> list:
    return [
        {
            "id": "pos-1", "type": "lending", "protocol": "Aave V3",
            "value_usd": 30000, "health_factor": 1.8, "liquidation_distance_pct": 40,
            "apy_net_pct": 3.5, "days_open": 30, "collateral_ratio_pct": 150,
            "risk_score_0_100": 20,
        },
        {
            "id": "pos-2", "type": "lp", "protocol": "Uniswap V3",
            "value_usd": 20000, "il_pct": 3.5, "liquidation_distance_pct": None,
            "apy_net_pct": 12.0, "days_open": 60,
        },
        {
            "id": "pos-3", "type": "staking", "protocol": "Lido",
            "value_usd": 50000, "apy_net_pct": 4.0, "days_open": 90,
        },
    ]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="DeFi Position Health Score Aggregator")
    parser.add_argument("--check", action="store_true", help="Compute and print (no write)")
    parser.add_argument("--run", action="store_true", help="Compute and write log")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    if not args.check and not args.run:
        parser.print_help()
        sys.exit(0)

    positions = _sample_positions()
    cfg = {**DEFAULT_CONFIG}
    if args.run:
        cfg["log_path"] = os.path.join(args.data_dir, "position_health_log.json")

    aggregator = DeFiPositionHealthScoreAggregator()
    result = aggregator.aggregate(positions, cfg if args.run else {**cfg, "log_path": "/dev/null"})

    print(json.dumps(result, indent=2))

    if args.run:
        print(f"\n✅ Log written to {cfg['log_path']}", file=sys.stderr)


if __name__ == "__main__":
    main()
