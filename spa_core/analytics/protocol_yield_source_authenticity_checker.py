"""
MP-957: Protocol Yield Source Authenticity Checker
Checks authenticity of yield sources (real vs emission vs ponzi).
Pure stdlib, read-only/advisory, atomic writes.
"""

import json
import os
import time

LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data", "yield_authenticity_log.json"
)
LOG_CAP = 100


class ProtocolYieldSourceAuthenticityChecker:
    """Checks authenticity of yield sources for DeFi protocols."""

    def check(self, protocols: list, config: dict) -> dict:
        """
        Check yield authenticity for a list of protocols.

        Args:
            protocols: list of protocol dicts with fields:
                - name (str)
                - reported_apy_pct (float)
                - fee_revenue_apy_pct (float)
                - token_emission_apy_pct (float)
                - external_incentive_apy_pct (float)
                - points_apy_pct (float)
                - total_tvl_usd (float)
                - token_fully_diluted_valuation_usd (float)
                - emission_rate_pct_fdv_annual (float)
                - has_revenue_sharing (bool)
                - days_since_launch (int)
                - audit_count (int)
            config: dict with optional config overrides

        Returns:
            dict with authenticity analysis results
        """
        if not isinstance(protocols, list):
            raise TypeError("protocols must be a list")
        if not isinstance(config, dict):
            raise TypeError("config must be a dict")

        checked = []
        for proto in protocols:
            checked.append(self._check_protocol(proto, config))

        aggregates = self._compute_aggregates(checked)
        result = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "protocols_checked": checked,
            "aggregates": aggregates,
            "total_count": len(checked),
        }

        self._append_log(result)
        return result

    def _check_protocol(self, proto: dict, config: dict) -> dict:
        """Check a single protocol's yield authenticity."""
        name = proto.get("name", "unknown")
        reported_apy = float(proto.get("reported_apy_pct", 0.0))
        fee_apy = float(proto.get("fee_revenue_apy_pct", 0.0))
        emission_apy = float(proto.get("token_emission_apy_pct", 0.0))
        incentive_apy = float(proto.get("external_incentive_apy_pct", 0.0))
        points_apy = float(proto.get("points_apy_pct", 0.0))
        tvl = float(proto.get("total_tvl_usd", 0.0))
        fdv = float(proto.get("token_fully_diluted_valuation_usd", 0.0))
        emission_rate = float(proto.get("emission_rate_pct_fdv_annual", 0.0))
        has_rev_share = bool(proto.get("has_revenue_sharing", False))
        days_launch = int(proto.get("days_since_launch", 0))
        audit_count = int(proto.get("audit_count", 0))

        # Computed fields
        real_yield = fee_apy
        inflation_yield = emission_apy + incentive_apy
        total_computed = real_yield + inflation_yield + points_apy

        # Sustainability ratio: real / total (handle zero)
        sustainability_ratio = (
            real_yield / total_computed if total_computed > 0 else 1.0
        )

        # FDV to TVL ratio
        fdv_to_tvl = (fdv / tvl) if tvl > 0 else 0.0

        # Yield inflation pressure: how much buyers need to absorb to sustain emissions
        # emission_rate_pct_fdv_annual × (fdv/tvl) gives pressure per TVL dollar
        yield_inflation_pressure = emission_rate * fdv_to_tvl if fdv_to_tvl > 0 else 0.0

        # Authenticity label
        label = self._authenticity_label(
            real_yield, total_computed, points_apy, reported_apy
        )

        # Flags
        flags = self._compute_flags(
            emission_rate, yield_inflation_pressure, days_launch,
            has_rev_share, audit_count, fdv_to_tvl
        )

        return {
            "name": name,
            "reported_apy_pct": reported_apy,
            "fee_revenue_apy_pct": fee_apy,
            "token_emission_apy_pct": emission_apy,
            "external_incentive_apy_pct": incentive_apy,
            "points_apy_pct": points_apy,
            "total_tvl_usd": tvl,
            "token_fully_diluted_valuation_usd": fdv,
            "emission_rate_pct_fdv_annual": emission_rate,
            "has_revenue_sharing": has_rev_share,
            "days_since_launch": days_launch,
            "audit_count": audit_count,
            "derived": {
                "real_yield_pct": round(real_yield, 4),
                "inflation_yield_pct": round(inflation_yield, 4),
                "sustainability_ratio": round(sustainability_ratio, 4),
                "fdv_to_tvl_ratio": round(fdv_to_tvl, 4),
                "yield_inflation_pressure": round(yield_inflation_pressure, 4),
            },
            "label": label,
            "flags": flags,
        }

    def _authenticity_label(
        self,
        real_yield: float,
        total_yield: float,
        points_apy: float,
        reported_apy: float,
    ) -> str:
        """
        REAL_YIELD / MOSTLY_REAL / MIXED / MOSTLY_INCENTIVIZED / PURE_EMISSION / POINTS_BASED
        """
        if total_yield <= 0 and reported_apy <= 0:
            return "REAL_YIELD"  # nothing to compare, assume neutral

        # If points dominate (>50% of reported)
        if reported_apy > 0 and (points_apy / reported_apy) > 0.5:
            return "POINTS_BASED"

        # Sustainability ratio
        ratio = real_yield / total_yield if total_yield > 0 else 1.0

        if ratio >= 0.8:
            return "REAL_YIELD"
        if ratio >= 0.6:
            return "MOSTLY_REAL"
        if ratio >= 0.4:
            return "MIXED"
        if ratio >= 0.1:
            return "MOSTLY_INCENTIVIZED"
        return "PURE_EMISSION"

    def _compute_flags(
        self,
        emission_rate: float,
        inflation_pressure: float,
        days_launch: int,
        has_rev_share: bool,
        audit_count: int,
        fdv_to_tvl: float,
    ) -> list:
        flags = []
        if emission_rate > 50.0:
            flags.append("UNSUSTAINABLE")
        if inflation_pressure > 100.0:
            flags.append("PONZI_PATTERN")
        if days_launch < 90:
            flags.append("NEW_PROTOCOL")
        if has_rev_share:
            flags.append("REVENUE_SHARING")
        if audit_count > 0:
            flags.append("AUDITED")
        if fdv_to_tvl > 10.0:
            flags.append("HIGH_FDV_TVL")
        return flags

    def _compute_aggregates(self, checked: list) -> dict:
        if not checked:
            return {
                "most_authentic": None,
                "least_authentic": None,
                "average_real_yield_pct": 0.0,
                "real_yield_protocols_count": 0,
                "ponzi_pattern_count": 0,
            }

        # Most authentic: highest sustainability ratio
        most_auth = max(
            checked, key=lambda p: p["derived"]["sustainability_ratio"]
        )
        # Least authentic: lowest sustainability ratio
        least_auth = min(
            checked, key=lambda p: p["derived"]["sustainability_ratio"]
        )

        real_yields = [p["derived"]["real_yield_pct"] for p in checked]
        avg_real = round(sum(real_yields) / len(real_yields), 4) if real_yields else 0.0

        real_yield_count = sum(
            1 for p in checked
            if p["label"] in ("REAL_YIELD", "MOSTLY_REAL")
        )

        ponzi_count = sum(
            1 for p in checked
            if "PONZI_PATTERN" in p["flags"]
        )

        return {
            "most_authentic": most_auth["name"],
            "least_authentic": least_auth["name"],
            "average_real_yield_pct": avg_real,
            "real_yield_protocols_count": real_yield_count,
            "ponzi_pattern_count": ponzi_count,
        }

    def _append_log(self, result: dict) -> None:
        """Ring-buffer append to yield_authenticity_log.json (cap 100)."""
        log_path = LOG_PATH
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        existing = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        existing = data
            except (json.JSONDecodeError, OSError):
                existing = []

        entry = {
            "ts": result["timestamp"],
            "total_count": result["total_count"],
            "aggregates": result["aggregates"],
        }
        existing.append(entry)
        if len(existing) > LOG_CAP:
            existing = existing[-LOG_CAP:]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(existing, f, indent=2)
        os.replace(tmp_path, log_path)
