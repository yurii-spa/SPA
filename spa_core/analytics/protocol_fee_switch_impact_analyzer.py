"""
MP-969: ProtocolFeeSwitchImpactAnalyzer
Analyzes the impact of enabling / changing a protocol fee switch on token
holders and the protocol itself. Advisory/read-only. Pure stdlib only.

CLI:
    python3 -m spa_core.analytics.protocol_fee_switch_impact_analyzer --check
    python3 -m spa_core.analytics.protocol_fee_switch_impact_analyzer --run [--data-dir data]
"""

import json
import os
import sys
from datetime import datetime, timezone

DATA_FILE = "data/fee_switch_impact_log.json"
LOG_CAP = 100

DEFAULT_CONFIG: dict = {
    "log_path": DATA_FILE,
    "log_cap": LOG_CAP,
    # Implied yield >= this AND yield > competitor avg → HIGHLY_ACCRETIVE
    "highly_accretive_yield_threshold": 5.0,
    # Implied yield >= this → ACCRETIVE
    "accretive_yield_threshold": 2.0,
    # Potential yield > this while switch OFF → FEE_SWITCH_OFF_OPPORTUNITY flag
    "fee_switch_opportunity_threshold": 3.0,
    # yield > competitor_avg * multiplier → COMPETITIVE_ADVANTAGE flag
    "competitive_advantage_multiplier": 1.5,
    # treasury_runway < this months → TREASURY_RISK label + TREASURY_CONCERN flag
    "treasury_concern_months": 6.0,
    # PE > this → HIGH_PE flag
    "high_pe_threshold": 100.0,
    # staking_ratio >= this % → STAKING_ALIGNED flag
    "staking_aligned_threshold": 50.0,
}


# ---------------------------------------------------------------------------
# Per-protocol helpers
# ---------------------------------------------------------------------------

def _annual_revenue(revenue_30d_usd: float) -> float:
    """Annualise 30-day revenue: multiply by 12."""
    return revenue_30d_usd * 12.0


def _potential_yield_pct(
    annual_revenue: float,
    fee_switch_pct: float,
    circulating_supply: float,
    token_price_usd: float,
) -> float:
    """
    Potential implied yield IF the fee switch were enabled (or is already).

    Formula:
        holder_revenue = annual_revenue * fee_switch_pct / 100
        fee_per_token  = holder_revenue / circulating_supply
        yield_pct      = fee_per_token / token_price * 100
    """
    if circulating_supply <= 0 or token_price_usd <= 0:
        return 0.0
    holder_rev = annual_revenue * (fee_switch_pct / 100.0)
    fee_per_tok = holder_rev / circulating_supply
    return fee_per_tok / token_price_usd * 100.0


def _pe_ratio(market_cap_usd: float, annual_revenue: float) -> float | None:
    """P/E equivalent: market_cap / annual_revenue. None if revenue == 0."""
    if annual_revenue <= 0:
        return None
    return market_cap_usd / annual_revenue


def _impact_label(
    enabled: bool,
    implied_yield: float,
    competing_avg: float,
    treasury_runway: float,
    cfg: dict,
) -> str:
    """
    Determine impact label for a single protocol.

    Priority order:
    1. TREASURY_RISK  (runway > 0 and < threshold)
    2. HIGHLY_ACCRETIVE (enabled, yield > 5%, yield > competitor avg)
    3. ACCRETIVE (enabled, yield ≥ 2%)
    4. NEUTRAL (switch off, or low positive yield)
    5. DILUTIVE (yield ≤ 0 and switch enabled)
    """
    treasury_thresh = float(cfg.get("treasury_concern_months",
                                    DEFAULT_CONFIG["treasury_concern_months"]))
    if treasury_runway is not None and 0 < treasury_runway < treasury_thresh:
        return "TREASURY_RISK"

    if not enabled:
        return "NEUTRAL"

    ha_thresh = float(cfg.get("highly_accretive_yield_threshold",
                               DEFAULT_CONFIG["highly_accretive_yield_threshold"]))
    ac_thresh = float(cfg.get("accretive_yield_threshold",
                               DEFAULT_CONFIG["accretive_yield_threshold"]))

    if implied_yield >= ha_thresh and implied_yield > competing_avg:
        return "HIGHLY_ACCRETIVE"
    if implied_yield >= ac_thresh:
        return "ACCRETIVE"
    if implied_yield > 0:
        return "NEUTRAL"
    return "DILUTIVE"


def _compute_flags(
    enabled: bool,
    implied_yield: float,
    potential_yield: float,
    competing_avg: float,
    treasury_runway: float,
    pe: float | None,
    staking_ratio: float,
    cfg: dict,
) -> list:
    flags = []

    opp_thresh = float(cfg.get("fee_switch_opportunity_threshold",
                               DEFAULT_CONFIG["fee_switch_opportunity_threshold"]))
    comp_mult = float(cfg.get("competitive_advantage_multiplier",
                              DEFAULT_CONFIG["competitive_advantage_multiplier"]))
    treasury_thresh = float(cfg.get("treasury_concern_months",
                                    DEFAULT_CONFIG["treasury_concern_months"]))
    pe_thresh = float(cfg.get("high_pe_threshold", DEFAULT_CONFIG["high_pe_threshold"]))
    staking_thresh = float(cfg.get("staking_aligned_threshold",
                                   DEFAULT_CONFIG["staking_aligned_threshold"]))

    # FEE_SWITCH_OFF_OPPORTUNITY: switch is OFF but potential yield > threshold
    if not enabled and potential_yield > opp_thresh:
        flags.append("FEE_SWITCH_OFF_OPPORTUNITY")

    # COMPETITIVE_ADVANTAGE: enabled AND yield > competitor_avg * multiplier
    if enabled and competing_avg > 0 and implied_yield > competing_avg * comp_mult:
        flags.append("COMPETITIVE_ADVANTAGE")

    # TREASURY_CONCERN: runway > 0 and < threshold
    if treasury_runway is not None and 0 < treasury_runway < treasury_thresh:
        flags.append("TREASURY_CONCERN")

    # HIGH_PE
    if pe is not None and pe > pe_thresh:
        flags.append("HIGH_PE")

    # STAKING_ALIGNED: staking_ratio >= 50%
    if staking_ratio >= staking_thresh:
        flags.append("STAKING_ALIGNED")

    return flags


def _analyze_single(proto: dict, cfg: dict) -> dict:
    """Analyze one protocol's fee switch impact."""
    name = proto.get("name", "unknown")
    token_name = proto.get("token_name", "")
    enabled = bool(proto.get("current_fee_switch_enabled", False))
    revenue_30d = float(proto.get("total_protocol_revenue_30d_usd", 0.0))
    fee_sw_pct = float(proto.get("fee_switch_pct", 0.0))
    circ_supply = float(proto.get("circulating_supply", 0.0))
    token_price = float(proto.get("token_price_usd", 0.0))
    market_cap = float(proto.get("market_cap_usd", 0.0))
    staking_ratio = float(proto.get("staking_ratio_pct", 0.0))
    competing_avg = float(proto.get("competing_protocols_avg_fee_yield_pct", 0.0))
    treasury_balance = float(proto.get("treasury_balance_usd", 0.0))
    treasury_runway = proto.get("treasury_runway_months")
    if treasury_runway is not None:
        treasury_runway = float(treasury_runway)

    annual_rev = _annual_revenue(revenue_30d)

    # Potential yield (always computed, used for opportunity flag)
    pot_yield = _potential_yield_pct(annual_rev, fee_sw_pct, circ_supply, token_price)

    # Actual implied yield (0 when switch off)
    implied_yield = pot_yield if enabled else 0.0

    # Fee per token annually (0 when switch off)
    if enabled and circ_supply > 0:
        holder_rev = annual_rev * (fee_sw_pct / 100.0)
        fee_per_token = holder_rev / circ_supply
    else:
        fee_per_token = 0.0

    # Holder annual income for median 1000 tokens
    holder_annual_income = fee_per_token * 1000.0

    # PE ratio
    pe = _pe_ratio(market_cap, annual_rev)

    # Fee yield vs competitors
    fee_yield_vs_comp = implied_yield - competing_avg

    # Label
    label = _impact_label(enabled, implied_yield, competing_avg, treasury_runway, cfg)

    # Flags
    flags = _compute_flags(
        enabled, implied_yield, pot_yield, competing_avg,
        treasury_runway, pe, staking_ratio, cfg,
    )

    return {
        "name": name,
        "token_name": token_name,
        "fee_switch_enabled": enabled,
        "annual_fee_revenue_usd": round(annual_rev, 4),
        "fee_per_token_annual_usd": round(fee_per_token, 8),
        "implied_fee_yield_pct": round(implied_yield, 4),
        "pe_ratio_equivalent": round(pe, 4) if pe is not None else None,
        "fee_yield_vs_competitors_pct": round(fee_yield_vs_comp, 4),
        "holder_annual_income_usd": round(holder_annual_income, 4),
        "impact_label": label,
        "flags": flags,
        "treasury_runway_months": treasury_runway,
        "potential_fee_yield_pct": round(pot_yield, 4),
    }


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
        "protocol_count": agg.get("protocol_count", 0),
        "average_implied_yield": agg.get("average_implied_yield", 0.0),
        "highly_accretive_count": agg.get("highly_accretive_count", 0),
        "treasury_risk_count": agg.get("treasury_risk_count", 0),
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

class ProtocolFeeSwitchImpactAnalyzer:
    """
    Analyzes the impact of fee switch activation / changes across DeFi protocols.

    Usage::

        analyzer = ProtocolFeeSwitchImpactAnalyzer()
        result = analyzer.analyze(protocols, config)
    """

    def analyze(self, protocols: list, config: dict | None = None) -> dict:
        """
        Analyze fee switch impact for a list of protocols.

        Parameters
        ----------
        protocols : list[dict]
            Each dict may contain:
            - name: str
            - token_name: str
            - current_fee_switch_enabled: bool
            - total_protocol_revenue_30d_usd: float
            - fee_switch_pct: float
            - circulating_supply: float
            - token_price_usd: float
            - market_cap_usd: float
            - token_holders_count: int
            - staking_ratio_pct: float
            - competing_protocols_avg_fee_yield_pct: float
            - treasury_balance_usd: float
            - treasury_runway_months: float

        config : dict | None
            Overrides for DEFAULT_CONFIG keys.

        Returns
        -------
        dict with keys:
            protocols, aggregates, timestamp
        """
        cfg: dict = {**DEFAULT_CONFIG, **(config or {})}

        if not protocols:
            return self._empty_result(cfg)

        analyzed = [_analyze_single(p, cfg) for p in protocols]

        # ── Aggregates ─────────────────────────────────────────────────────
        all_yields = [a["implied_fee_yield_pct"] for a in analyzed]
        avg_yield = sum(all_yields) / len(all_yields) if all_yields else 0.0

        highest = max(analyzed, key=lambda x: x["implied_fee_yield_pct"])
        lowest = min(analyzed, key=lambda x: x["implied_fee_yield_pct"])

        highly_acc_count = sum(1 for a in analyzed if a["impact_label"] == "HIGHLY_ACCRETIVE")
        treasury_risk_count = sum(1 for a in analyzed if a["impact_label"] == "TREASURY_RISK")

        result = {
            "protocols": analyzed,
            "aggregates": {
                "highest_yield_protocol": highest,
                "lowest_yield": lowest,
                "average_implied_yield": round(avg_yield, 4),
                "highly_accretive_count": highly_acc_count,
                "treasury_risk_count": treasury_risk_count,
                "protocol_count": len(protocols),
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        _append_log(result, cfg)
        return result

    def _empty_result(self, cfg: dict) -> dict:
        return {
            "protocols": [],
            "aggregates": {
                "highest_yield_protocol": None,
                "lowest_yield": None,
                "average_implied_yield": 0.0,
                "highly_accretive_count": 0,
                "treasury_risk_count": 0,
                "protocol_count": 0,
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _sample_protocols() -> list:
    return [
        {
            "name": "Uniswap", "token_name": "UNI",
            "current_fee_switch_enabled": False,
            "total_protocol_revenue_30d_usd": 5_000_000,
            "fee_switch_pct": 10.0,
            "circulating_supply": 600_000_000,
            "token_price_usd": 7.0,
            "market_cap_usd": 4_200_000_000,
            "token_holders_count": 300_000,
            "staking_ratio_pct": 20.0,
            "competing_protocols_avg_fee_yield_pct": 1.5,
            "treasury_balance_usd": 50_000_000,
            "treasury_runway_months": 24.0,
        },
        {
            "name": "Compound", "token_name": "COMP",
            "current_fee_switch_enabled": True,
            "total_protocol_revenue_30d_usd": 800_000,
            "fee_switch_pct": 30.0,
            "circulating_supply": 8_000_000,
            "token_price_usd": 50.0,
            "market_cap_usd": 400_000_000,
            "token_holders_count": 40_000,
            "staking_ratio_pct": 55.0,
            "competing_protocols_avg_fee_yield_pct": 2.0,
            "treasury_balance_usd": 5_000_000,
            "treasury_runway_months": 4.0,
        },
    ]


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Protocol Fee Switch Impact Analyzer")
    parser.add_argument("--check", action="store_true", help="Compute and print (no write)")
    parser.add_argument("--run", action="store_true", help="Compute and write log")
    parser.add_argument("--data-dir", default="data", help="Data directory")
    args = parser.parse_args()

    if not args.check and not args.run:
        parser.print_help()
        sys.exit(0)

    protocols = _sample_protocols()
    cfg = {**DEFAULT_CONFIG}
    if args.run:
        cfg["log_path"] = os.path.join(args.data_dir, "fee_switch_impact_log.json")
    else:
        cfg["log_path"] = "/dev/null"

    analyzer = ProtocolFeeSwitchImpactAnalyzer()
    result = analyzer.analyze(protocols, cfg)

    print(json.dumps(result, indent=2))

    if args.run:
        print(f"\n✅ Log written to {cfg['log_path']}", file=sys.stderr)


if __name__ == "__main__":
    main()
