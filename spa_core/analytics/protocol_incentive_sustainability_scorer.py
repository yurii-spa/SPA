"""
MP-983: Protocol Incentive Sustainability Scorer
Evaluates the sustainability of DeFi incentive programs over time.
Read-only analytics module — never modifies allocator/risk/execution.
Stdlib only, atomic writes, ring-buffer log cap 100.
"""

import json
import os
from datetime import datetime, timezone
from spa_core.utils.atomic import atomic_save

# Default log file
DEFAULT_LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "incentive_sustainability_log.json"
)

LOG_CAP = 100


class ProtocolIncentiveSustainabilityScorer:
    """
    Scores the long-term sustainability of protocol incentive programs.

    Each program dict must contain:
        protocol                          (str)
        incentive_token                   (str)
        monthly_incentive_budget_usd      (float)
        monthly_organic_revenue_usd       (float)
        incentive_tvl_usd                 (float)
        organic_tvl_usd                   (float)
        token_treasury_remaining_months   (float)
        incentive_to_revenue_ratio        (float)  budget / revenue
        user_retention_rate_pct           (float)  0-100
        similar_protocol_post_incentive_tvl_drop_pct (float) 0-100 historical benchmark

    config keys (all optional):
        log_path    (str)   path for ring-buffer JSON log
        write_log   (bool)  default True
    """

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def score(self, programs: list[dict], config: dict | None = None) -> dict:
        """
        Evaluate sustainability of a list of incentive programs.

        Returns dict with:
            programs            list of per-program result dicts
            aggregate           aggregated summary metrics
            scored_at           ISO timestamp
        """
        if config is None:
            config = {}

        log_path  = config.get("log_path", DEFAULT_LOG_PATH)
        write_log = config.get("write_log", True)

        if not programs:
            result = {
                "programs": [],
                "aggregate": {},
                "scored_at": self._now_iso(),
                "error": "no_programs",
            }
            return result

        normalised = [self._normalise(p) for p in programs]
        results    = [self._score_program(p) for p in normalised]
        aggregate  = self._compute_aggregate(results)

        output = {
            "programs":  results,
            "aggregate": aggregate,
            "scored_at": self._now_iso(),
        }

        if write_log:
            self._append_log(output, log_path)

        return output

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    @staticmethod
    def _normalise(p: dict) -> dict:
        return {
            "protocol":                               str(p.get("protocol", "unknown")),
            "incentive_token":                        str(p.get("incentive_token", "UNKNOWN")),
            "monthly_incentive_budget_usd":           float(p.get("monthly_incentive_budget_usd", 0.0)),
            "monthly_organic_revenue_usd":            float(p.get("monthly_organic_revenue_usd", 0.0)),
            "incentive_tvl_usd":                      float(p.get("incentive_tvl_usd", 0.0)),
            "organic_tvl_usd":                        float(p.get("organic_tvl_usd", 0.0)),
            "token_treasury_remaining_months":        float(p.get("token_treasury_remaining_months", 0.0)),
            "incentive_to_revenue_ratio":             float(p.get("incentive_to_revenue_ratio", 0.0)),
            "user_retention_rate_pct":                float(p.get("user_retention_rate_pct", 0.0)),
            "similar_protocol_post_incentive_tvl_drop_pct": float(
                p.get("similar_protocol_post_incentive_tvl_drop_pct", 0.0)
            ),
        }

    def _score_program(self, p: dict) -> dict:
        budget     = p["monthly_incentive_budget_usd"]
        revenue    = p["monthly_organic_revenue_usd"]
        inc_tvl    = p["incentive_tvl_usd"]
        org_tvl    = p["organic_tvl_usd"]
        treasury   = p["token_treasury_remaining_months"]
        retention  = p["user_retention_rate_pct"]
        benchmark_drop = p["similar_protocol_post_incentive_tvl_drop_pct"]

        # --- Derived metrics ---
        sustainability_ratio = (
            revenue / budget if budget > 0 else float("inf")
        )

        tvl_at_risk_usd = inc_tvl * (1.0 - retention / 100.0)

        monthly_cash_burn_net_usd = budget - revenue

        # Runway: only meaningful if burning cash (burn > 0)
        if monthly_cash_burn_net_usd > 0 and treasury > 0:
            runway_months = treasury  # treasury already given in months
        elif monthly_cash_burn_net_usd <= 0:
            runway_months = float("inf")  # not burning, infinite runway
        else:
            runway_months = 0.0

        total_tvl = inc_tvl + org_tvl
        organic_tvl_ratio_pct = (
            org_tvl / total_tvl * 100.0 if total_tvl > 0 else 0.0
        )

        # --- Sustainability label ---
        is_organic_majority = revenue >= budget
        is_high_retention   = retention >= 70.0

        if is_organic_majority and is_high_retention:
            label = "SELF_SUSTAINING"
        elif sustainability_ratio >= 0.5:
            label = "TRANSITION_PHASE"
        elif sustainability_ratio >= 0.1:
            if treasury >= 6.0:
                label = "DEPENDENT"
            else:
                label = "UNSUSTAINABLE"
        else:
            # ratio < 0.1
            if treasury < 6.0:
                label = "PONZI_FLYWHEEL"
            else:
                label = "UNSUSTAINABLE"

        # --- Flags ---
        flags: list[str] = []

        if treasury < 6.0 and monthly_cash_burn_net_usd > 0:
            flags.append("TREASURY_RUNWAY_SHORT")

        if total_tvl > 0 and tvl_at_risk_usd / total_tvl > 0.5:
            flags.append("HIGH_TVL_AT_RISK")

        if organic_tvl_ratio_pct > 50.0:
            flags.append("ORGANIC_MAJORITY")

        if retention < 40.0:
            flags.append("RETENTION_RISK")

        if benchmark_drop > 60.0:
            flags.append("BENCHMARK_WORSE")

        return {
            "protocol":                         p["protocol"],
            "incentive_token":                  p["incentive_token"],
            "sustainability_ratio":             round(sustainability_ratio, 6) if sustainability_ratio != float("inf") else None,
            "tvl_at_risk_usd":                  round(tvl_at_risk_usd, 2),
            "monthly_cash_burn_net_usd":        round(monthly_cash_burn_net_usd, 2),
            "runway_months":                    round(runway_months, 2) if runway_months != float("inf") else None,
            "organic_tvl_ratio_pct":            round(organic_tvl_ratio_pct, 4),
            "sustainability_label":             label,
            "flags":                            flags,
            # pass-through for aggregation
            "_organic_revenue":                 revenue,
            "_budget":                          budget,
            "_total_tvl":                       total_tvl,
            "_tvl_at_risk":                     tvl_at_risk_usd,
        }

    @staticmethod
    def _compute_aggregate(results: list[dict]) -> dict:
        if not results:
            return {}

        self_sustaining_count  = sum(1 for r in results if r["sustainability_label"] == "SELF_SUSTAINING")
        ponzi_flywheel_count   = sum(1 for r in results if r["sustainability_label"] == "PONZI_FLYWHEEL")
        total_tvl_at_risk_usd  = sum(r["tvl_at_risk_usd"] for r in results)

        # most / least sustainable by sustainability_ratio (None treated as infinite)
        def ratio_key(r):
            v = r.get("sustainability_ratio")
            return v if v is not None else 1e18

        most_sustainable  = max(results, key=ratio_key)
        least_sustainable = min(results, key=ratio_key)

        return {
            "most_sustainable":        most_sustainable["protocol"],
            "least_sustainable":       least_sustainable["protocol"],
            "total_tvl_at_risk_usd":   round(total_tvl_at_risk_usd, 2),
            "self_sustaining_count":   self_sustaining_count,
            "ponzi_flywheel_count":    ponzi_flywheel_count,
            "total_programs_scored":   len(results),
        }

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    @staticmethod
    def _append_log(entry: dict, log_path: str) -> None:
        """Atomic ring-buffer append (cap LOG_CAP)."""
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        try:
            with open(log_path, "r", encoding="utf-8") as fh:
                log: list = json.load(fh)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        log.append(entry)
        if len(log) > LOG_CAP:
            log = log[-LOG_CAP:]

        dir_name = os.path.dirname(log_path)
        atomic_save(log, str(log_path))
# ------------------------------------------------------------------ #
# CLI                                                                  #
# ------------------------------------------------------------------ #

if __name__ == "__main__":
    import json

    sample_programs = [
        {
            "protocol": "Protocol A",
            "incentive_token": "TKN",
            "monthly_incentive_budget_usd": 1_000_000,
            "monthly_organic_revenue_usd": 1_200_000,
            "incentive_tvl_usd": 20_000_000,
            "organic_tvl_usd": 80_000_000,
            "token_treasury_remaining_months": 24,
            "incentive_to_revenue_ratio": 0.83,
            "user_retention_rate_pct": 75.0,
            "similar_protocol_post_incentive_tvl_drop_pct": 30.0,
        },
        {
            "protocol": "Protocol B",
            "incentive_token": "EMI",
            "monthly_incentive_budget_usd": 5_000_000,
            "monthly_organic_revenue_usd": 200_000,
            "incentive_tvl_usd": 150_000_000,
            "organic_tvl_usd": 5_000_000,
            "token_treasury_remaining_months": 3,
            "incentive_to_revenue_ratio": 25.0,
            "user_retention_rate_pct": 15.0,
            "similar_protocol_post_incentive_tvl_drop_pct": 85.0,
        },
    ]

    scorer = ProtocolIncentiveSustainabilityScorer()
    result = scorer.score(sample_programs, {"write_log": False})
    print(json.dumps(result, indent=2))
