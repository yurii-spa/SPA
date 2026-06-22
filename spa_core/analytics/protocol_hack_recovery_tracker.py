"""
MP-981: ProtocolHackRecoveryTracker
Tracks protocol recovery after hacks and exploits.
Stdlib only. Atomic ring-buffer log (cap 100).
"""

import json
import os
import time


class ProtocolHackRecoveryTracker:
    """
    Evaluates how well DeFi protocols have recovered from security incidents.

    Input per incident:
      protocol                   str
      hack_date_days_ago         float  (days since hack)
      amount_hacked_usd          float
      amount_recovered_usd       float
      recovery_mechanism         str: insurance | treasury | fundraise |
                                       none | partial_reimbursement
      tvl_before_hack_usd        float
      tvl_current_usd            float
      users_compensated_pct      float (0-100)
      audit_count_post_hack      int
      new_security_measures      list[str]: bug_bounty | formal_verification |
                                             multisig | timelock | insurance
      days_since_resumption      float | None  (None = not resumed yet)

    Computed per incident:
      recovery_rate_pct          recovered / hacked × 100
      tvl_recovery_pct           current / before × 100
      compensation_score         0-100
      security_improvement_score 0-100
      overall_recovery_score     0-100
      label, flags

    Labels:
      FULLY_RECOVERED    tvl > 90% AND users_comp > 90%
      MOSTLY_RECOVERED   tvl > 70% OR users_comp > 70%
      PARTIALLY_RECOVERED tvl 30-70% OR users_comp 30-70%
      STRUGGLING         tvl < 30% AND users_comp < 30%
      ABANDONED          not resumed AND hack > 365 days ago

    Flags:
      UNCOMPENSATED_USERS       users_compensated_pct < 50%
      NO_POST_AUDIT             audit_count_post_hack == 0
      RESUMED_QUICKLY           days_since_resumption < 30 AND resumed
      OVER_INSURED_RECOVERY     amount_recovered_usd > amount_hacked_usd
      REPEAT_HACK               hack_date_days_ago < 180 AND prior_hacks exist
    """

    LOG_PATH = "data/hack_recovery_log.json"
    LOG_CAP = 100

    # ------------------------------------------------------------------ public

    def track(self, incidents: list, config: dict) -> dict:
        """
        Analyse recovery status for each incident and return aggregated report.

        config keys (all optional):
          log_path    override log file path
        """
        if not incidents:
            return self._empty_result(config)

        analyzed = [self._analyze(inc, incidents) for inc in incidents]
        aggregates = self._compute_aggregates(analyzed)

        result = {
            "incidents": analyzed,
            "best_recovery": aggregates["best_recovery"],
            "worst_recovery": aggregates["worst_recovery"],
            "average_recovery_score": aggregates["average_recovery_score"],
            "fully_recovered_count": aggregates["fully_recovered_count"],
            "abandoned_count": aggregates["abandoned_count"],
            "config_used": dict(config),
        }

        log_path = config.get("log_path", self.LOG_PATH)
        self._append_log(result, log_path)
        return result

    # ----------------------------------------------------------------- private

    def _analyze(self, inc: dict, all_incidents: list) -> dict:
        protocol = str(inc.get("protocol", "unknown"))
        hack_days_ago = float(inc.get("hack_date_days_ago", 0.0))
        amount_hacked = float(inc.get("amount_hacked_usd", 0.0))
        amount_recovered = float(inc.get("amount_recovered_usd", 0.0))
        recovery_mechanism = str(inc.get("recovery_mechanism", "none"))
        tvl_before = float(inc.get("tvl_before_hack_usd", 0.0))
        tvl_current = float(inc.get("tvl_current_usd", 0.0))
        users_comp_pct = float(inc.get("users_compensated_pct", 0.0))
        audit_count = int(inc.get("audit_count_post_hack", 0))
        new_measures = list(inc.get("new_security_measures", []) or [])
        days_since_resumption = inc.get("days_since_resumption", None)
        if days_since_resumption is not None:
            days_since_resumption = float(days_since_resumption)
        prior_hacks = list(inc.get("prior_hacks", []) or [])

        # Recovery rate
        if amount_hacked > 0:
            recovery_rate_pct = min(amount_recovered / amount_hacked * 100.0, 200.0)
        else:
            recovery_rate_pct = 100.0 if amount_recovered == 0 else 200.0

        # TVL recovery
        if tvl_before > 0:
            tvl_recovery_pct = tvl_current / tvl_before * 100.0
        else:
            tvl_recovery_pct = 100.0 if tvl_current == 0 else 0.0

        # Compensation score (0-100):
        # users_compensated_pct × recovery_rate_factor (capped at 1.0)
        recovery_rate_factor = min(recovery_rate_pct / 100.0, 1.0)
        compensation_score = users_comp_pct * recovery_rate_factor

        # Security improvement score (0-100):
        # Measures: up to 5 known types → 10 pts each = 50; audits: min(audit_count,5) × 10 = 50
        known_measures = {"bug_bounty", "formal_verification", "multisig", "timelock", "insurance"}
        unique_measures = set(str(m).lower() for m in new_measures) & known_measures
        measures_score = len(unique_measures) * 10.0          # 0-50
        audit_score = min(audit_count, 5) * 10.0              # 0-50
        security_improvement_score = min(measures_score + audit_score, 100.0)

        # Overall recovery score (0-100):
        # 40% tvl_recovery (capped 100), 30% compensation_score, 30% security_improvement
        tvl_component = min(tvl_recovery_pct, 100.0) * 0.40
        comp_component = compensation_score * 0.30
        sec_component = security_improvement_score * 0.30
        overall_recovery_score = round(tvl_component + comp_component + sec_component, 4)

        # Flags
        flags = []

        if users_comp_pct < 50.0:
            flags.append("UNCOMPENSATED_USERS")

        if audit_count == 0:
            flags.append("NO_POST_AUDIT")

        if days_since_resumption is not None and days_since_resumption < 30.0:
            flags.append("RESUMED_QUICKLY")

        if amount_hacked > 0 and amount_recovered > amount_hacked:
            flags.append("OVER_INSURED_RECOVERY")

        # REPEAT_HACK: hack was recent (<180 days ago) AND prior_hacks exist
        if hack_days_ago < 180.0 and len(prior_hacks) > 0:
            flags.append("REPEAT_HACK")

        # Label: ABANDONED first
        resumed = days_since_resumption is not None
        if not resumed and hack_days_ago > 365.0:
            label = "ABANDONED"
        elif tvl_recovery_pct > 90.0 and users_comp_pct > 90.0:
            label = "FULLY_RECOVERED"
        elif tvl_recovery_pct > 70.0 or users_comp_pct > 70.0:
            label = "MOSTLY_RECOVERED"
        elif tvl_recovery_pct >= 30.0 or users_comp_pct >= 30.0:
            label = "PARTIALLY_RECOVERED"
        else:
            label = "STRUGGLING"

        return {
            "protocol": protocol,
            "hack_date_days_ago": hack_days_ago,
            "amount_hacked_usd": amount_hacked,
            "amount_recovered_usd": amount_recovered,
            "recovery_mechanism": recovery_mechanism,
            "tvl_before_hack_usd": tvl_before,
            "tvl_current_usd": tvl_current,
            "users_compensated_pct": users_comp_pct,
            "audit_count_post_hack": audit_count,
            "new_security_measures": new_measures,
            "days_since_resumption": days_since_resumption,
            "recovery_rate_pct": round(recovery_rate_pct, 4),
            "tvl_recovery_pct": round(tvl_recovery_pct, 4),
            "compensation_score": round(compensation_score, 4),
            "security_improvement_score": round(security_improvement_score, 4),
            "overall_recovery_score": overall_recovery_score,
            "label": label,
            "flags": flags,
        }

    def _compute_aggregates(self, analyzed: list) -> dict:
        by_score = sorted(analyzed, key=lambda x: x["overall_recovery_score"], reverse=True)
        best = by_score[0]["protocol"]
        worst = by_score[-1]["protocol"]
        avg_score = round(
            sum(a["overall_recovery_score"] for a in analyzed) / len(analyzed), 4
        )
        fully_count = sum(1 for a in analyzed if a["label"] == "FULLY_RECOVERED")
        abandoned_count = sum(1 for a in analyzed if a["label"] == "ABANDONED")

        return {
            "best_recovery": best,
            "worst_recovery": worst,
            "average_recovery_score": avg_score,
            "fully_recovered_count": fully_count,
            "abandoned_count": abandoned_count,
        }

    def _empty_result(self, config: dict) -> dict:
        return {
            "incidents": [],
            "best_recovery": None,
            "worst_recovery": None,
            "average_recovery_score": None,
            "fully_recovered_count": 0,
            "abandoned_count": 0,
            "config_used": dict(config),
        }

    def _append_log(self, result: dict, log_path: str) -> None:
        dir_ = os.path.dirname(log_path)
        if dir_:
            os.makedirs(dir_, exist_ok=True)

        try:
            with open(log_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except Exception:
            log = []

        entry = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "incident_count": len(result.get("incidents", [])),
            "fully_recovered_count": result.get("fully_recovered_count", 0),
            "abandoned_count": result.get("abandoned_count", 0),
            "best_recovery": result.get("best_recovery"),
            "average_recovery_score": result.get("average_recovery_score"),
        }
        log.append(entry)
        log = log[-self.LOG_CAP:]

        tmp = log_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp, log_path)
