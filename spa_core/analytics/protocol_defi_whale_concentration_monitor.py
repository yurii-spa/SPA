"""
MP-999: Protocol DeFi Whale Concentration Monitor
Monitors whale-address concentration in DeFi protocols.
Read-only analytics. stdlib only. Atomic ring-buffer write.
"""

import json
import os
from typing import Any
from spa_core.utils import clock

LOG_FILE = os.path.join(
    os.path.dirname(__file__), "..", "..", "data", "whale_concentration_log.json"
)
LOG_CAP = 100


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _safe_div(num: float, denom: float, default: float = 0.0) -> float:
    if denom == 0:
        return default
    return num / denom


class ProtocolDeFiWhaleConcentrationMonitor:
    """
    Monitors whale-address concentration risk in DeFi protocols.
    All computation is deterministic and LLM-free.
    """

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def monitor(self, protocols: list, config: dict) -> dict:
        """
        Monitor whale concentration across a list of protocol dicts.

        Parameters
        ----------
        protocols : list[dict]  — protocol snapshots (see module docstring)
        config    : dict        — options:
            data_dir  (str)  — override log directory
            log_cap   (int)  — override ring-buffer cap (default 100)
            skip_log  (bool) — skip writing the ring-buffer log

        Returns
        -------
        dict with keys:
            protocols  : list[dict]  — per-protocol analysis
            aggregates : dict        — summary stats
            timestamp  : str         — ISO-8601
            version    : str         — module version
        """
        results = [self._monitor_protocol(p, config) for p in protocols]

        aggregates = self._compute_aggregates(results)

        report = {
            "protocols": results,
            "aggregates": aggregates,
            "timestamp": clock.utcnow().isoformat() + "Z",
            "version": "1.0.0",
            "module": "MP-999",
        }

        if not config.get("skip_log", False):
            self._append_log(report, config)

        return report

    # ------------------------------------------------------------------
    # Per-protocol analysis
    # ------------------------------------------------------------------

    def _monitor_protocol(self, p: dict, config: dict) -> dict:
        name = p.get("name", "unknown")
        top10_tvl_pct = float(p.get("top10_wallet_tvl_pct", 0.0))
        top1_tvl_pct = float(p.get("top1_wallet_tvl_pct", 0.0))
        whale_threshold_usd = float(p.get("whale_threshold_usd", 1_000_000))
        whale_count = int(p.get("whale_count", 0))
        total_users = int(p.get("total_users", 1))
        whale_holding_days = float(p.get("whale_avg_holding_days", 30.0))
        retail_holding_days = float(p.get("retail_avg_holding_days", 30.0))
        whale_inflow = float(p.get("whale_inflow_7d_usd", 0.0))
        whale_outflow = float(p.get("whale_outflow_7d_usd", 0.0))
        governance_top10_pct = float(p.get("governance_token_top10_pct", 0.0))
        pol_pct = float(p.get("protocol_owned_liquidity_pct", 0.0))

        # Core metrics
        net_whale_flow_usd = whale_inflow - whale_outflow

        # whale_dominance_score (0-100)
        # top10_tvl_pct×0.4 + top1×0.3 + governance_concentration×0.3
        whale_dominance_score = _clamp(
            top10_tvl_pct * 0.4
            + top1_tvl_pct * 0.3
            + governance_top10_pct * 0.3
        )

        # retail_health_score (0-100)
        # Inverse of whale_dominance + holding_days_ratio bonus
        holding_ratio = _safe_div(retail_holding_days, whale_holding_days, 1.0)
        holding_bonus = _clamp(holding_ratio * 20, 0, 20)
        retail_health_score = _clamp(100 - whale_dominance_score + holding_bonus - 20)

        # whale_exit_risk_score (0-100)
        # Components: outflow_pressure + short_holding + dominance
        # outflow pressure: outflow/(outflow+inflow) × 40
        total_flow = whale_inflow + whale_outflow
        outflow_pressure = _clamp(_safe_div(whale_outflow, total_flow) * 40, 0, 40)
        # short holding: 1 - holding_ratio capped, × 30
        holding_short_penalty = _clamp((1 - min(holding_ratio, 1.0)) * 30, 0, 30)
        dominance_component = _clamp(whale_dominance_score * 0.30, 0, 30)
        whale_exit_risk_score = _clamp(
            outflow_pressure + holding_short_penalty + dominance_component
        )

        # decentralization_score (0-100)
        # 100 - whale_dominance + pol_adjustment (high POL = slightly better than random whales)
        pol_bonus = _clamp((pol_pct / 100.0) * 10, 0, 10)  # POL up to +10
        pol_penalty = _clamp((pol_pct / 100.0) * 20, 0, 20) if pol_pct > 50 else 0  # but big POL → -20
        decentralization_score = _clamp(
            100 - whale_dominance_score + pol_bonus - pol_penalty
        )

        # Concentration label
        label = self._concentration_label(
            top10_tvl_pct=top10_tvl_pct,
            top1_tvl_pct=top1_tvl_pct,
            pol_pct=pol_pct,
            decentralization_score=decentralization_score,
        )

        # Flags
        flags = self._compute_flags(
            net_whale_flow_usd=net_whale_flow_usd,
            whale_inflow=whale_inflow,
            whale_outflow=whale_outflow,
            governance_top10_pct=governance_top10_pct,
            top1_tvl_pct=top1_tvl_pct,
            top10_tvl_pct=top10_tvl_pct,
            retail_holding_days=retail_holding_days,
            whale_holding_days=whale_holding_days,
            whale_dominance_score=whale_dominance_score,
            pol_pct=pol_pct,
        )

        return {
            "name": name,
            "top10_wallet_tvl_pct": top10_tvl_pct,
            "top1_wallet_tvl_pct": top1_tvl_pct,
            "whale_count": whale_count,
            "total_users": total_users,
            "whale_avg_holding_days": whale_holding_days,
            "retail_avg_holding_days": retail_holding_days,
            "whale_inflow_7d_usd": whale_inflow,
            "whale_outflow_7d_usd": whale_outflow,
            "net_whale_flow_usd": round(net_whale_flow_usd, 2),
            "governance_token_top10_pct": governance_top10_pct,
            "protocol_owned_liquidity_pct": pol_pct,
            "whale_dominance_score": round(whale_dominance_score, 2),
            "retail_health_score": round(retail_health_score, 2),
            "whale_exit_risk_score": round(whale_exit_risk_score, 2),
            "decentralization_score": round(decentralization_score, 2),
            "concentration_label": label,
            "flags": flags,
        }

    # ------------------------------------------------------------------
    # Labels & Flags
    # ------------------------------------------------------------------

    def _concentration_label(
        self,
        top10_tvl_pct: float,
        top1_tvl_pct: float,
        pol_pct: float,
        decentralization_score: float,
    ) -> str:
        """Determine concentration label based on primary risk factors."""
        if pol_pct > 50:
            return "PROTOCOL_DOMINATED"
        if top1_tvl_pct > 20:
            return "SINGLE_WHALE_RISK"
        if top10_tvl_pct > 60:
            return "WHALE_HEAVY"
        if top10_tvl_pct < 30 and decentralization_score > 70:
            return "WELL_DISTRIBUTED"
        return "MODERATE_CONCENTRATION"

    def _compute_flags(
        self,
        net_whale_flow_usd: float,
        whale_inflow: float,
        whale_outflow: float,
        governance_top10_pct: float,
        top1_tvl_pct: float,
        top10_tvl_pct: float,
        retail_holding_days: float,
        whale_holding_days: float,
        whale_dominance_score: float,
        pol_pct: float,
    ) -> list:
        flags = []

        # WHALE_EXIT_SIGNAL: net_flow < -$1M AND outflow > inflow × 2
        if net_whale_flow_usd < -1_000_000 and whale_outflow > whale_inflow * 2:
            flags.append("WHALE_EXIT_SIGNAL")

        # GOVERNANCE_CAPTURE_RISK: governance_top10 > 60%
        if governance_top10_pct > 60:
            flags.append("GOVERNANCE_CAPTURE_RISK")

        # SINGLE_WHALE_DOMINANT: top1 > 15%
        if top1_tvl_pct > 15:
            flags.append("SINGLE_WHALE_DOMINANT")

        # RETAIL_EXODUS: retail_holding < whale_holding × 0.5 AND whale_dominance high (>50)
        if retail_holding_days < whale_holding_days * 0.5 and whale_dominance_score > 50:
            flags.append("RETAIL_EXODUS")

        # HIGH_POL: pol_pct > 30%
        if pol_pct > 30:
            flags.append("HIGH_POL")

        # HEALTHY_DISTRIBUTION: top10 < 25%
        if top10_tvl_pct < 25:
            flags.append("HEALTHY_DISTRIBUTION")

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: list) -> dict:
        if not results:
            return {
                "most_distributed": None,
                "most_concentrated": None,
                "avg_decentralization": 0.0,
                "single_whale_risk_count": 0,
                "well_distributed_count": 0,
                "total_protocols": 0,
            }

        scores = [(r["decentralization_score"], r["name"]) for r in results]
        most_distributed = max(scores, key=lambda x: x[0])[1]
        most_concentrated = min(scores, key=lambda x: x[0])[1]
        avg_decentralization = sum(s for s, _ in scores) / len(scores)
        single_whale_risk_count = sum(
            1 for r in results if r["concentration_label"] == "SINGLE_WHALE_RISK"
        )
        well_distributed_count = sum(
            1 for r in results if r["concentration_label"] == "WELL_DISTRIBUTED"
        )

        return {
            "most_distributed": most_distributed,
            "most_concentrated": most_concentrated,
            "avg_decentralization": round(avg_decentralization, 2),
            "single_whale_risk_count": single_whale_risk_count,
            "well_distributed_count": well_distributed_count,
            "total_protocols": len(results),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log (atomic write)
    # ------------------------------------------------------------------

    def _resolve_log_path(self, config: dict) -> str:
        data_dir = config.get("data_dir")
        if data_dir:
            return os.path.join(data_dir, "whale_concentration_log.json")
        return LOG_FILE

    def _append_log(self, report: dict, config: dict) -> None:
        log_path = self._resolve_log_path(config)
        cap = int(config.get("log_cap", LOG_CAP))

        # Load existing
        entries = []
        if os.path.exists(log_path):
            try:
                with open(log_path, "r") as f:
                    data = json.load(f)
                    entries = data if isinstance(data, list) else []
            except (json.JSONDecodeError, OSError):
                entries = []

        # Append summary entry
        entry = {
            "timestamp": report["timestamp"],
            "total_protocols": report["aggregates"]["total_protocols"],
            "avg_decentralization": report["aggregates"]["avg_decentralization"],
            "single_whale_risk_count": report["aggregates"]["single_whale_risk_count"],
            "well_distributed_count": report["aggregates"]["well_distributed_count"],
            "most_distributed": report["aggregates"]["most_distributed"],
            "most_concentrated": report["aggregates"]["most_concentrated"],
        }
        entries.append(entry)

        # Ring-buffer cap
        if len(entries) > cap:
            entries = entries[-cap:]

        # Atomic write
        os.makedirs(os.path.dirname(log_path), exist_ok=True)
        tmp = log_path + ".tmp"
        with open(tmp, "w") as f:
            json.dump(entries, f, indent=2)
        os.replace(tmp, log_path)
