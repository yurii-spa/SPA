"""
MP-941: Protocol Total Value Secured Analyzer
Analyzes Total Value Secured (TVS) — an extension of TVL that captures all
assets protected, secured, or relied upon by a protocol.

Standalone module — stdlib only, no external dependencies.
Atomic writes: tmp file + os.replace().
"""
import json
import os
import tempfile
from typing import Any, Dict, List, Optional


class ProtocolTotalValueSecuredAnalyzer:
    """
    Analyzes Total Value Secured (TVS) across DeFi protocols.

    Input fields per protocol (dict):
        name (str)                          – protocol name
        tvl_usd (float)                     – total value locked (USD)
        bridged_assets_usd (float)          – assets bridged through protocol (USD)
        insured_assets_usd (float)          – assets covered by protocol's insurance (USD)
        staked_for_security_usd (float)     – restaking / security-staked capital (USD)
        oracle_secured_usd (float)          – TVL in protocols using this oracle (USD)
        validator_set_value_usd (float)     – economic value of validator set (USD)
        protocol_revenue_monthly_usd (float)– monthly protocol revenue (USD)
        security_budget_monthly_usd (float) – monthly security spend
                                              (validator rewards + insurance fund) (USD)

    Computed per protocol:
        total_value_secured_usd   sum of tvl + bridged + insured + staked + oracle + validator
        tvs_to_tvl_ratio          total_value_secured / tvl (if tvl > 0)
        security_ratio            (security_budget_monthly * 12) / total_value_secured
        security_adequacy_score   0-100 composite (higher = more secure)
        attack_cost_estimate_usd  estimated cost of a 51%/governance attack

    Security label:
        FORTRESS / SECURE / ADEQUATE / UNDERFUNDED / CRITICAL

    Flags:
        LOW_SECURITY_BUDGET       security_ratio < 0.001 (< 0.1% TVS annual)
        ORACLE_SYSTEMIC           oracle_secured > 10x TVL
        HIGH_TVS_RATIO            tvs_to_tvl_ratio > 5x
        REVENUE_COVERS_SECURITY   monthly revenue > monthly security_budget
        RESTAKING_DEPENDENT       staked_for_security > 50% of total_value_secured

    Aggregates:
        most_secure, least_secure, total_ecosystem_tvs,
        average_security_ratio, fortress_count

    config keys:
        log_path (str)   – path for ring-buffer JSON log
        persist (bool)   – if True, append result to log
    """

    LOG_CAP = 100
    DEFAULT_LOG_PATH = "data/total_value_secured_log.json"

    # Flag thresholds
    LOW_SECURITY_BUDGET_RATIO  = 0.001        # < 0.1% TVS annual
    ORACLE_SYSTEMIC_MULTIPLIER = 10.0         # oracle_secured > 10x TVL
    HIGH_TVS_RATIO_THRESHOLD   = 5.0          # tvs > 5x TVL
    RESTAKING_DEPENDENT_RATIO  = 0.50         # restaking > 50% TVS

    # Security label thresholds (adequacy_score, descending)
    _LABEL_THRESHOLDS = [
        (80.0, "FORTRESS"),
        (60.0, "SECURE"),
        (40.0, "ADEQUATE"),
        (20.0, "UNDERFUNDED"),
    ]

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def analyze(
        self,
        protocols: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Analyze Total Value Secured across a list of protocols.

        :param protocols: list of protocol dicts (see class docstring)
        :param config:    configuration dict (log_path, persist)
        :return:          dict with per-protocol analysis and aggregates
        """
        log_path = config.get("log_path", self.DEFAULT_LOG_PATH)
        persist  = config.get("persist", False)

        if not protocols:
            result = self._empty_result()
            if persist:
                self._append_log(log_path, result)
            return result

        analyzed = [self._analyze_single(p) for p in protocols]
        aggregates = self._compute_aggregates(analyzed)

        result = {
            "protocols": analyzed,
            "aggregates": aggregates,
            "status": "ok",
        }

        if persist:
            self._append_log(log_path, result)

        return result

    # ------------------------------------------------------------------ #
    # Private — single protocol analysis                                   #
    # ------------------------------------------------------------------ #

    def _analyze_single(self, p: Dict[str, Any]) -> Dict[str, Any]:
        name             = str(p.get("name", "unknown"))
        tvl              = float(p.get("tvl_usd", 0.0))
        bridged          = float(p.get("bridged_assets_usd", 0.0))
        insured          = float(p.get("insured_assets_usd", 0.0))
        staked           = float(p.get("staked_for_security_usd", 0.0))
        oracle_secured   = float(p.get("oracle_secured_usd", 0.0))
        validator_val    = float(p.get("validator_set_value_usd", 0.0))
        revenue_monthly  = float(p.get("protocol_revenue_monthly_usd", 0.0))
        security_monthly = float(p.get("security_budget_monthly_usd", 0.0))

        # --- TVS ---
        total_tvs = tvl + bridged + insured + staked + oracle_secured + validator_val
        total_tvs = max(0.0, total_tvs)

        # --- TVS-to-TVL ratio ---
        if tvl > 0:
            tvs_to_tvl_ratio = total_tvs / tvl
        else:
            tvs_to_tvl_ratio = 0.0

        # --- Security ratio: annualised security_budget / TVS ---
        if total_tvs > 0:
            security_ratio = (security_monthly * 12.0) / total_tvs
        else:
            security_ratio = 0.0

        # --- Attack cost estimate ---
        attack_cost = self._estimate_attack_cost(
            tvl=tvl,
            staked=staked,
            validator_val=validator_val,
            security_monthly=security_monthly,
        )

        # --- Security adequacy score (0-100) ---
        adequacy_score = self._compute_adequacy_score(
            security_ratio=security_ratio,
            tvs_to_tvl_ratio=tvs_to_tvl_ratio,
            staked=staked,
            total_tvs=total_tvs,
            revenue_monthly=revenue_monthly,
            security_monthly=security_monthly,
        )

        # --- Label ---
        label = self._get_label(adequacy_score)

        # --- Flags ---
        flags = self._compute_flags(
            security_ratio=security_ratio,
            oracle_secured=oracle_secured,
            tvl=tvl,
            tvs_to_tvl_ratio=tvs_to_tvl_ratio,
            revenue_monthly=revenue_monthly,
            security_monthly=security_monthly,
            staked=staked,
            total_tvs=total_tvs,
        )

        return {
            "name":                      name,
            "tvl_usd":                   tvl,
            "bridged_assets_usd":        bridged,
            "insured_assets_usd":        insured,
            "staked_for_security_usd":   staked,
            "oracle_secured_usd":        oracle_secured,
            "validator_set_value_usd":   validator_val,
            "protocol_revenue_monthly_usd":  revenue_monthly,
            "security_budget_monthly_usd":   security_monthly,
            # Computed
            "total_value_secured_usd":   round(total_tvs, 2),
            "tvs_to_tvl_ratio":          round(tvs_to_tvl_ratio, 4),
            "security_ratio":            round(security_ratio, 6),
            "security_adequacy_score":   round(adequacy_score, 2),
            "attack_cost_estimate_usd":  round(attack_cost, 2),
            "security_label":            label,
            "flags":                     flags,
        }

    def _estimate_attack_cost(
        self,
        tvl: float,
        staked: float,
        validator_val: float,
        security_monthly: float,
    ) -> float:
        """
        Heuristic attack cost estimate.

        For a 51% attack the attacker needs to control >50% of the
        security stake. Governance attacks typically require >50% of
        governance tokens at market value.

        Use: max(50% of staked/validator security, 6 months security budget)
        as a conservative lower-bound estimate.
        """
        security_capital = staked + validator_val
        half_security = security_capital * 0.50

        # Annualised security budget provides a lower bound
        budget_6m = security_monthly * 6.0

        # Attack cost is the higher of the two heuristics
        attack_cost = max(half_security, budget_6m)

        # Floor: at least 1% of TVL
        floor_val = tvl * 0.01
        attack_cost = max(attack_cost, floor_val)

        return attack_cost

    def _compute_adequacy_score(
        self,
        security_ratio: float,
        tvs_to_tvl_ratio: float,
        staked: float,
        total_tvs: float,
        revenue_monthly: float,
        security_monthly: float,
    ) -> float:
        """
        Security adequacy score (0-100, higher = more secure).

        Components:
          - security_ratio_score (50%): penalise low annualised security/TVS
          - diversification_score (25%): low restaking dependency is better
          - revenue_coverage_score (25%): revenue covering security budget is positive
        """
        # Security ratio component: 0.01+ is excellent, log scale
        import math
        if security_ratio >= 0.01:
            ratio_score = 100.0
        elif security_ratio > 0:
            # log10(security_ratio) ranges from -inf to -2 for 0<ratio<0.01
            # Map log10(ratio) from [-5, -2] → [0, 100]
            log_r = math.log10(security_ratio)
            log_r = max(-5.0, log_r)
            ratio_score = ((log_r + 5.0) / 3.0) * 100.0
            ratio_score = max(0.0, min(100.0, ratio_score))
        else:
            ratio_score = 0.0

        # Diversification: restaking dependency
        if total_tvs > 0:
            restaking_share = staked / total_tvs
        else:
            restaking_share = 0.0
        # Penalise heavy reliance on restaking (>50% = 0 score)
        if restaking_share <= 0.20:
            div_score = 100.0
        elif restaking_share <= 0.50:
            div_score = 100.0 - ((restaking_share - 0.20) / 0.30) * 100.0
        else:
            div_score = 0.0

        # Revenue coverage: monthly revenue > security budget is healthy
        if security_monthly > 0:
            coverage = revenue_monthly / security_monthly
        else:
            coverage = 1.0 if revenue_monthly > 0 else 0.0
        rev_score = min(100.0, coverage * 50.0)  # 2x coverage = 100 score

        adequacy = (
            ratio_score * 0.50 +
            div_score   * 0.25 +
            rev_score   * 0.25
        )
        return max(0.0, min(100.0, adequacy))

    def _get_label(self, adequacy_score: float) -> str:
        for threshold, label in self._LABEL_THRESHOLDS:
            if adequacy_score >= threshold:
                return label
        return "CRITICAL"

    def _compute_flags(
        self,
        security_ratio: float,
        oracle_secured: float,
        tvl: float,
        tvs_to_tvl_ratio: float,
        revenue_monthly: float,
        security_monthly: float,
        staked: float,
        total_tvs: float,
    ) -> List[str]:
        flags = []

        if security_ratio < self.LOW_SECURITY_BUDGET_RATIO:
            flags.append("LOW_SECURITY_BUDGET")

        if tvl > 0 and oracle_secured > (tvl * self.ORACLE_SYSTEMIC_MULTIPLIER):
            flags.append("ORACLE_SYSTEMIC")

        if tvs_to_tvl_ratio > self.HIGH_TVS_RATIO_THRESHOLD:
            flags.append("HIGH_TVS_RATIO")

        if security_monthly > 0 and revenue_monthly > security_monthly:
            flags.append("REVENUE_COVERS_SECURITY")

        if total_tvs > 0 and staked > (total_tvs * self.RESTAKING_DEPENDENT_RATIO):
            flags.append("RESTAKING_DEPENDENT")

        return flags

    # ------------------------------------------------------------------ #
    # Private — aggregates                                                 #
    # ------------------------------------------------------------------ #

    def _compute_aggregates(
        self, analyzed: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        scores = [a["security_adequacy_score"] for a in analyzed]
        best_idx  = scores.index(max(scores))
        worst_idx = scores.index(min(scores))

        total_ecosystem_tvs = sum(a["total_value_secured_usd"] for a in analyzed)

        # Average security ratio (only over protocols with TVS > 0)
        valid_ratios = [a["security_ratio"] for a in analyzed if a["total_value_secured_usd"] > 0]
        if valid_ratios:
            avg_security_ratio = sum(valid_ratios) / len(valid_ratios)
        else:
            avg_security_ratio = 0.0

        fortress_count = sum(1 for a in analyzed if a["security_label"] == "FORTRESS")

        return {
            "most_secure":              analyzed[best_idx]["name"],
            "least_secure":             analyzed[worst_idx]["name"],
            "total_ecosystem_tvs":      round(total_ecosystem_tvs, 2),
            "average_security_ratio":   round(avg_security_ratio, 6),
            "fortress_count":           fortress_count,
            "total_protocols":          len(analyzed),
        }

    # ------------------------------------------------------------------ #
    # Private — empty result                                               #
    # ------------------------------------------------------------------ #

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "protocols": [],
            "aggregates": {
                "most_secure":            None,
                "least_secure":           None,
                "total_ecosystem_tvs":    0.0,
                "average_security_ratio": 0.0,
                "fortress_count":         0,
                "total_protocols":        0,
            },
            "status": "ok",
        }

    # ------------------------------------------------------------------ #
    # Private — log persistence                                            #
    # ------------------------------------------------------------------ #

    def _append_log(self, log_path: str, entry: Dict) -> None:
        """Append entry to ring-buffer log (cap=LOG_CAP), atomic write."""
        try:
            if os.path.exists(log_path):
                with open(log_path, "r") as fh:
                    data = json.load(fh)
                if not isinstance(data, list):
                    data = []
            else:
                data = []

            data.append(entry)
            if len(data) > self.LOG_CAP:
                data = data[-self.LOG_CAP:]

            dir_name = os.path.dirname(os.path.abspath(log_path))
            os.makedirs(dir_name, exist_ok=True)

            fd, tmp_path = tempfile.mkstemp(
                dir=dir_name, prefix=".tvs_analyzer_tmp_"
            )
            try:
                with os.fdopen(fd, "w") as fh:
                    json.dump(data, fh, indent=2)
                os.replace(tmp_path, log_path)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception:
            pass  # analytics must never crash the system
