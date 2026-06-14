"""
MP-991: ProtocolDeFiTreasuryRunwayAnalyzer
Analyzes DeFi protocol financial sustainability (treasury runway).
Pure stdlib, read-only/advisory, atomic ring-buffer log.
"""

import json
import os
from datetime import datetime, timezone

# ── constants ────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "treasury_runway_log.json"
)
LOG_CAP = 100

# Native token discount factors
DISCOUNT_CONCENTRATED = 0.30   # concentration_pct > 50
DISCOUNT_DEFAULT      = 0.60   # otherwise


# ── helpers ──────────────────────────────────────────────────────────────────

def _safe_div(num: float, denom: float, default: float = 0.0) -> float:
    if denom == 0:
        return default
    return num / denom


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


# ── main class ───────────────────────────────────────────────────────────────

class ProtocolDeFiTreasuryRunwayAnalyzer:
    """
    Analyzes treasury financial sustainability for a list of DeFi protocols.

    Each protocol dict (input):
        name                    : str
        treasury_stable_usd     : float   stablecoins in treasury
        treasury_native_usd     : float   native_token_price × quantity
        treasury_eth_btc_usd    : float   ETH+BTC portion of treasury
        monthly_opex_usd        : float   salaries + grants + infrastructure
        monthly_token_emissions_usd : float  emissions by current token price
        monthly_protocol_revenue_usd: float  protocol fees/revenue
        token_price_usd         : float
        token_price_ath_usd     : float
        fully_diluted_valuation_usd : float
        token_concentration_pct : float   % held by top-10 wallets (0-100)
        diversification_score   : float   0-100 (how diversified the treasury assets are)

    config (optional keys):
        fortress_runway_months  : float  (default 36)
        strong_runway_months    : float  (default 18)
        adequate_runway_months  : float  (default 12)
        vulnerable_runway_months: float  (default 6)
        native_dep_critical     : float  (default 80)  % native → CRITICAL
        native_dep_flag         : float  (default 70)  % native → NATIVE_TOKEN_DEPENDENT
        fortress_stable_pct     : float  (default 70)  stables% for FORTRESS
        emission_heavy_mult     : float  (default 2.0) emissions > revenue*mult
        diversified_threshold   : float  (default 70)  divScore > → DIVERSIFIED flag
        runway_concern_months   : float  (default 9)   < → RUNWAY_CONCERN
        concentration_threshold : float  (default 50)  top10 > → low discount
        log_path                : str    (override for tests)
        log_cap                 : int    (override for tests)
    """

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(self, protocols: list, config: dict) -> dict:
        cfg = self._merge_config(config)
        results = [self._analyze_one(p, cfg) for p in protocols]
        agg = self._aggregate(results, cfg)
        self._write_log(results, agg, cfg)

        return {
            "analyzed_at":     datetime.now(timezone.utc).isoformat(),
            "protocol_count":  len(results),
            "protocols":       results,
            "aggregates":      agg,
        }

    # ── config ────────────────────────────────────────────────────────────────

    def _merge_config(self, config: dict) -> dict:
        defaults = {
            "fortress_runway_months":   36.0,
            "strong_runway_months":     18.0,
            "adequate_runway_months":   12.0,
            "vulnerable_runway_months":  6.0,
            "native_dep_critical":      80.0,
            "native_dep_flag":          70.0,
            "fortress_stable_pct":      70.0,
            "emission_heavy_mult":       2.0,
            "diversified_threshold":    70.0,
            "runway_concern_months":     9.0,
            "concentration_threshold":  50.0,
            "log_path":                LOG_PATH,
            "log_cap":                 LOG_CAP,
        }
        merged = dict(defaults)
        merged.update(config)
        return merged

    # ── per-protocol analysis ─────────────────────────────────────────────────

    def _analyze_one(self, p: dict, cfg: dict) -> dict:
        stable      = float(p.get("treasury_stable_usd", 0))
        native_usd  = float(p.get("treasury_native_usd", 0))
        eth_btc_usd = float(p.get("treasury_eth_btc_usd", 0))
        opex        = float(p.get("monthly_opex_usd", 0))
        emissions   = float(p.get("monthly_token_emissions_usd", 0))
        revenue     = float(p.get("monthly_protocol_revenue_usd", 0))
        concentration = float(p.get("token_concentration_pct", 0))
        div_score   = float(p.get("diversification_score", 0))
        token_price = float(p.get("token_price_usd", 0))
        token_ath   = float(p.get("token_price_ath_usd", max(token_price, 1)))
        fdv         = float(p.get("fully_diluted_valuation_usd", 0))

        # ── discount factor ───────────────────────────────────────────────────
        discount_factor = (
            DISCOUNT_CONCENTRATED
            if concentration > cfg["concentration_threshold"]
            else DISCOUNT_DEFAULT
        )

        # ── total treasury ────────────────────────────────────────────────────
        discounted_native = native_usd * discount_factor
        # ETH/BTC treated at 0.80 (semi-liquid, some market risk)
        total_treasury = stable + eth_btc_usd * 0.80 + discounted_native

        # ── net monthly burn ──────────────────────────────────────────────────
        net_monthly_burn = opex + emissions - revenue
        # If revenue > expenses, burn can be negative (net inflow)

        # ── runway ────────────────────────────────────────────────────────────
        if net_monthly_burn <= 0:
            # Protocol is revenue-positive and self-sustaining → very long runway
            runway_months = 999.0
        else:
            runway_months = _safe_div(stable, net_monthly_burn, default=0.0)

        # ── native token dependency ───────────────────────────────────────────
        native_dep_pct = (
            _safe_div(discounted_native, total_treasury, 0.0) * 100.0
            if total_treasury > 0 else 0.0
        )
        native_dep_pct = _clamp(native_dep_pct, 0.0, 100.0)

        # ── stables % of total treasury ───────────────────────────────────────
        stable_pct = (
            _safe_div(stable, total_treasury, 0.0) * 100.0
            if total_treasury > 0 else 0.0
        )

        # ── token price vs ATH ────────────────────────────────────────────────
        token_price_vs_ath_pct = (
            _safe_div(token_price, token_ath, 0.0) * 100.0
        )

        # ── health label ──────────────────────────────────────────────────────
        health_label = self._classify_health(
            runway_months, stable_pct, native_dep_pct, cfg
        )

        # ── flags ─────────────────────────────────────────────────────────────
        flags = self._compute_flags(
            native_dep_pct, emissions, revenue, opex,
            div_score, runway_months, cfg
        )

        return {
            "name":                         p.get("name", ""),
            "treasury_stable_usd":          stable,
            "treasury_native_usd":          native_usd,
            "treasury_eth_btc_usd":         eth_btc_usd,
            "monthly_opex_usd":             opex,
            "monthly_token_emissions_usd":  emissions,
            "monthly_protocol_revenue_usd": revenue,
            "token_price_usd":              token_price,
            "token_price_ath_usd":          token_ath,
            "token_price_vs_ath_pct":       round(token_price_vs_ath_pct, 2),
            "fully_diluted_valuation_usd":  fdv,
            "token_concentration_pct":      concentration,
            "diversification_score":        div_score,
            "discount_factor":              discount_factor,
            "total_treasury_usd":           round(total_treasury, 2),
            "net_monthly_burn_usd":         round(net_monthly_burn, 2),
            "runway_months":                round(min(runway_months, 999.0), 2),
            "native_token_dependency_pct":  round(native_dep_pct, 2),
            "stable_pct_of_treasury":       round(stable_pct, 2),
            "health_label":                 health_label,
            "flags":                        flags,
        }

    # ── health label ──────────────────────────────────────────────────────────

    def _classify_health(
        self, runway_months: float, stable_pct: float,
        native_dep_pct: float, cfg: dict
    ) -> str:
        # CRITICAL: runway <6mo OR native dependency >80%
        if runway_months < cfg["vulnerable_runway_months"] or \
                native_dep_pct > cfg["native_dep_critical"]:
            return "CRITICAL"

        # FORTRESS: runway >36mo AND stables >70%
        if runway_months >= cfg["fortress_runway_months"] and \
                stable_pct >= cfg["fortress_stable_pct"]:
            return "FORTRESS"

        # STRONG: runway >18mo
        if runway_months >= cfg["strong_runway_months"]:
            return "STRONG"

        # ADEQUATE: runway >12mo
        if runway_months >= cfg["adequate_runway_months"]:
            return "ADEQUATE"

        # VULNERABLE: runway 6-12mo
        return "VULNERABLE"

    # ── flags ─────────────────────────────────────────────────────────────────

    def _compute_flags(
        self, native_dep_pct: float, emissions: float, revenue: float,
        opex: float, div_score: float, runway_months: float, cfg: dict
    ) -> list:
        flags = []

        # NATIVE_TOKEN_DEPENDENT
        if native_dep_pct > cfg["native_dep_flag"]:
            flags.append("NATIVE_TOKEN_DEPENDENT")

        # EMISSION_HEAVY: emissions > revenue * multiplier
        if revenue > 0 and emissions > revenue * cfg["emission_heavy_mult"]:
            flags.append("EMISSION_HEAVY")
        elif revenue == 0 and emissions > 0:
            flags.append("EMISSION_HEAVY")

        # DIVERSIFIED_TREASURY
        if div_score >= cfg["diversified_threshold"]:
            flags.append("DIVERSIFIED_TREASURY")

        # RUNWAY_CONCERN
        if 0 < runway_months < cfg["runway_concern_months"]:
            flags.append("RUNWAY_CONCERN")

        # REVENUE_POSITIVE
        if revenue > opex:
            flags.append("REVENUE_POSITIVE")

        return flags

    # ── aggregates ───────────────────────────────────────────────────────────

    def _aggregate(self, results: list, cfg: dict) -> dict:
        if not results:
            return {
                "strongest":             None,
                "weakest":               None,
                "avg_runway_months":     0.0,
                "critical_count":        0,
                "revenue_positive_count": 0,
            }

        by_runway = sorted(
            results, key=lambda r: r["runway_months"], reverse=True
        )
        strongest = by_runway[0]["name"]
        weakest   = by_runway[-1]["name"]

        # Cap at 999 for avg (don't let infinite runway skew)
        capped = [min(r["runway_months"], 999.0) for r in results]
        avg_runway = sum(capped) / len(capped)

        critical_count = sum(
            1 for r in results if r["health_label"] == "CRITICAL"
        )
        rev_positive = sum(
            1 for r in results if "REVENUE_POSITIVE" in r["flags"]
        )

        return {
            "strongest":              strongest,
            "weakest":                weakest,
            "avg_runway_months":      round(avg_runway, 2),
            "critical_count":         critical_count,
            "revenue_positive_count": rev_positive,
        }

    # ── ring-buffer log ──────────────────────────────────────────────────────

    def _write_log(self, results: list, agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap      = cfg["log_cap"]

        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts":             datetime.now(timezone.utc).isoformat(),
            "protocol_count": len(results),
            "aggregates":     agg,
            "snapshots": [
                {
                    "name":            r["name"],
                    "runway_months":   r["runway_months"],
                    "health_label":    r["health_label"],
                    "net_burn_usd":    r["net_monthly_burn_usd"],
                    "total_treasury":  r["total_treasury_usd"],
                }
                for r in results
            ],
        }

        log = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as fh:
                    log = json.load(fh)
                if not isinstance(log, list):
                    log = []
            except (json.JSONDecodeError, OSError):
                log = []

        log.append(entry)
        if len(log) > cap:
            log = log[-cap:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(log, fh, indent=2)
        os.replace(tmp, log_path)
