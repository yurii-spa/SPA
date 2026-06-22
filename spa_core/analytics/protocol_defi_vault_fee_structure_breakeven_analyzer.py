"""
MP-1005: ProtocolDeFiVaultFeeStructureBreakevenAnalyzer

For a yield vault charging BOTH a management fee (% of AUM per year) and a performance
fee (% of profit, optionally above a hurdle rate), computes the total fee drag, the
resulting net APY, the gross APY required to hit a target net APY (inverting the fee
formula), what share of the gross yield the manager effectively takes, and a
fee-fairness score vs a peer benchmark.

Fee mechanics for gross APY g, management fee m (% AUM/yr), performance fee f (% of
profit above hurdle h):
    profit_above_hurdle = max(0, g - h)
    perf_fee_drag       = profit_above_hurdle * f/100
    total_fee_drag      = m + perf_fee_drag
    net_apy             = g - total_fee_drag
    effective_fee_load  = total_fee_drag / g * 100        (manager's share of gross)
Inverting for the gross required to reach a target net t (assuming g > h):
    g = (t + m - h*f/100) / (1 - f/100)     guarded for f == 100.

Distinct from defi_protocol_fee_tier_optimizer (swap-pool fees), defi_gas_cost_yield_drag
(gas), and fee_drag_calculator (generic single-fee): no prior module models the combined
management + performance + hurdle structure and inverts it for a required gross APY
(gap confirmed v7.40).

Pure stdlib, read-only/advisory, all divisions guarded, atomic tempfile+os.replace
writes, ring-buffer 100 (`data/vault_fee_structure_breakeven_log.json`).
"""

import json
import os
import time


class ProtocolDeFiVaultFeeStructureBreakevenAnalyzer:
    """
    Per-vault management + performance fee break-even / fairness analysis.

    Input fields (per vault dict):
      name, protocol,
      gross_apy_pct                 (yield before fees)
      management_fee_pct            (annual, on AUM)
      performance_fee_pct           (on profit above hurdle)
      hurdle_rate_pct               (optional, default 0)
      aum_usd                       (optional, for $ figures)
      peer_avg_total_fee_load_pct   (optional benchmark, % of gross taken)
      target_net_apy_pct            (optional, for required-gross calc)
    """

    LOG_CAP = 100

    EPS = 1e-9

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def analyze(self, vaults: list, config: dict = None) -> dict:
        if config is None:
            config = {}

        results = [self._analyze_one(v) for v in vaults]
        aggregates = self._compute_aggregates(results)

        output = {
            "vaults": results,
            "aggregates": aggregates,
            "vault_count": len(results),
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }

        if config.get("write_log", False):
            self._write_log(output, config.get("data_dir", "data"))

        return output

    # ------------------------------------------------------------------ #
    # Per-vault analysis
    # ------------------------------------------------------------------ #

    def _analyze_one(self, v: dict) -> dict:
        name = v.get("name", "unknown")
        protocol = v.get("protocol", "unknown")

        gross_apy = float(v.get("gross_apy_pct", 0.0))
        management_fee = max(0.0, float(v.get("management_fee_pct", 0.0)))
        performance_fee = min(100.0, max(0.0, float(v.get("performance_fee_pct", 0.0))))
        hurdle_rate = max(0.0, float(v.get("hurdle_rate_pct", 0.0)))
        aum = max(0.0, float(v.get("aum_usd", 0.0)))

        peer_load = v.get("peer_avg_total_fee_load_pct", None)
        if peer_load is not None:
            peer_load = float(peer_load)
        target_net = v.get("target_net_apy_pct", None)
        if target_net is not None:
            target_net = float(target_net)

        # Fee drag decomposition.
        profit_above_hurdle_pct = max(0.0, gross_apy - hurdle_rate)
        perf_fee_drag_pct = profit_above_hurdle_pct * (performance_fee / 100.0)
        total_fee_drag_pct = management_fee + perf_fee_drag_pct
        net_apy_pct = gross_apy - total_fee_drag_pct

        # Effective fee load: share of gross the manager takes.
        effective_fee_load_pct = total_fee_drag_pct / max(gross_apy, self.EPS) * 100.0

        # Required gross APY to reach the target net (invert the fee formula).
        required_gross_apy_pct = self._required_gross(
            target_net, management_fee, performance_fee, hurdle_rate
        )

        # $ figures over a year on the supplied AUM.
        management_fee_usd = aum * (management_fee / 100.0)
        performance_fee_usd = aum * (perf_fee_drag_pct / 100.0)
        total_fee_usd = aum * (total_fee_drag_pct / 100.0)
        net_yield_usd = aum * (net_apy_pct / 100.0)

        fee_value_score = self._fee_value_score(effective_fee_load_pct, peer_load)
        grade = self._grade(fee_value_score)
        classification = self._classify(
            effective_fee_load_pct, net_apy_pct, gross_apy, management_fee,
        )
        flags = self._flags(
            net_apy_pct, effective_fee_load_pct, management_fee, performance_fee,
            hurdle_rate, peer_load, gross_apy,
        )

        return {
            "name": name,
            "protocol": protocol,
            "gross_apy_pct": round(gross_apy, 4),
            "management_fee_pct": round(management_fee, 4),
            "performance_fee_pct": round(performance_fee, 4),
            "hurdle_rate_pct": round(hurdle_rate, 4),
            "profit_above_hurdle_pct": round(profit_above_hurdle_pct, 4),
            "perf_fee_drag_pct": round(perf_fee_drag_pct, 4),
            "total_fee_drag_pct": round(total_fee_drag_pct, 4),
            "net_apy_pct": round(net_apy_pct, 4),
            "effective_fee_load_pct": round(effective_fee_load_pct, 4),
            "required_gross_apy_pct": (
                round(required_gross_apy_pct, 4)
                if required_gross_apy_pct is not None else None
            ),
            "management_fee_usd": round(management_fee_usd, 2),
            "performance_fee_usd": round(performance_fee_usd, 2),
            "total_fee_usd": round(total_fee_usd, 2),
            "net_yield_usd": round(net_yield_usd, 2),
            "fee_value_score": round(fee_value_score, 4),
            "grade": grade,
            "classification": classification,
            "flags": flags,
        }

    def _required_gross(
        self, target_net, management_fee, performance_fee, hurdle_rate
    ):
        """
        Gross APY needed to net `target_net`, assuming the gross clears the hurdle.
        From net = g - m - (g-h)*f/100  ->  g = (target_net + m - h*f/100) / (1 - f/100).
        Returns None if target absent or perf_fee == 100 (denominator zero -> no finite
        gross reaches the target since 100% of every marginal profit dollar is taken).
        """
        if target_net is None:
            return None
        f = performance_fee / 100.0
        denom = 1.0 - f
        if denom <= self.EPS:
            return None
        return (target_net + management_fee - hurdle_rate * f) / denom

    # ------------------------------------------------------------------ #
    # Score / grade / classification / flags
    # ------------------------------------------------------------------ #

    def _fee_value_score(self, effective_fee_load_pct, peer_load) -> float:
        """
        0-100, higher == better value (manager takes less of the gross). Base score
        falls linearly with effective load (load 0% -> 100, load 50% -> 50, load
        100%+ -> 0). A peer adjustment rewards being below the peer benchmark and
        penalizes being above it, bounded +/-15.
        """
        load = max(0.0, effective_fee_load_pct)
        base = max(0.0, 100.0 - load)

        if peer_load is not None and peer_load > 0:
            delta = peer_load - load  # positive == cheaper than peers
            adjustment = max(-15.0, min(15.0, delta * 0.5))
        else:
            adjustment = 0.0

        return max(0.0, min(100.0, base + adjustment))

    def _grade(self, score: float) -> str:
        if score >= 90.0:
            return "A"
        if score >= 75.0:
            return "B"
        if score >= 60.0:
            return "C"
        if score >= 45.0:
            return "D"
        return "F"

    def _classify(
        self, effective_fee_load_pct, net_apy_pct, gross_apy, management_fee
    ) -> str:
        if gross_apy <= 0 and management_fee <= 0:
            return "INSUFFICIENT_DATA"
        if net_apy_pct < 0.0:
            return "VALUE_DESTRUCTIVE"
        load = effective_fee_load_pct
        if load <= 15.0:
            return "EXCELLENT_VALUE"
        if load <= 30.0:
            return "FAIR"
        if load <= 50.0:
            return "EXPENSIVE"
        return "OVERPRICED"

    def _flags(
        self, net_apy_pct, effective_fee_load_pct, management_fee, performance_fee,
        hurdle_rate, peer_load, gross_apy,
    ) -> list:
        flags = []
        if gross_apy <= 0 and management_fee <= 0:
            flags.append("INSUFFICIENT_DATA")
        if net_apy_pct < 0.0:
            flags.append("NET_NEGATIVE")
        if peer_load is not None:
            if effective_fee_load_pct > peer_load:
                flags.append("ABOVE_PEER_FEES")
            else:
                flags.append("BELOW_PEER_FEES")
        if management_fee >= 2.0:
            flags.append("HIGH_MANAGEMENT_FEE")
        if performance_fee >= 20.0:
            flags.append("HIGH_PERFORMANCE_FEE")
        if performance_fee > 0 and hurdle_rate <= 0:
            flags.append("NO_HURDLE")
        if effective_fee_load_pct > 50.0:
            flags.append("MANAGER_TAKES_MAJORITY")
        return flags

    # ------------------------------------------------------------------ #
    # Aggregates
    # ------------------------------------------------------------------ #

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "best_vault": None,
                "worst_vault": None,
                "average_fee_value_score": None,
                "overpriced_count": 0,
                "net_negative_count": 0,
            }

        best = max(results, key=lambda r: r["fee_value_score"])
        worst = min(results, key=lambda r: r["fee_value_score"])
        avg = sum(r["fee_value_score"] for r in results) / len(results)
        overpriced = sum(
            1 for r in results
            if r["classification"] in ("OVERPRICED", "VALUE_DESTRUCTIVE")
        )
        net_negative = sum(1 for r in results if r["net_apy_pct"] < 0.0)

        return {
            "best_vault": {
                "name": best["name"],
                "fee_value_score": best["fee_value_score"],
                "classification": best["classification"],
            },
            "worst_vault": {
                "name": worst["name"],
                "fee_value_score": worst["fee_value_score"],
                "classification": worst["classification"],
            },
            "average_fee_value_score": round(avg, 4),
            "overpriced_count": overpriced,
            "net_negative_count": net_negative,
        }

    # ------------------------------------------------------------------ #
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------ #

    def _write_log(self, result: dict, data_dir: str = "data") -> None:
        os.makedirs(data_dir, exist_ok=True)
        log_path = os.path.join(data_dir, "vault_fee_structure_breakeven_log.json")

        try:
            with open(log_path, "r") as f:
                log = json.load(f)
            if not isinstance(log, list):
                log = []
        except (FileNotFoundError, json.JSONDecodeError):
            log = []

        agg = result.get("aggregates", {})
        log.append({
            "timestamp": result.get("timestamp", ""),
            "vault_count": result.get("vault_count", 0),
            "average_fee_value_score": agg.get("average_fee_value_score"),
            "overpriced_count": agg.get("overpriced_count", 0),
            "net_negative_count": agg.get("net_negative_count", 0),
        })

        if len(log) > self.LOG_CAP:
            log = log[-self.LOG_CAP:]

        tmp_path = log_path + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(log, f, indent=2)
        os.replace(tmp_path, log_path)
