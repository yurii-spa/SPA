"""
MP-976: DeFiRiskAdjustedYieldComparator

Advisory/read-only module. Compares DeFi strategies by risk-adjusted yield,
computing composite risk scores, DeFi Sharpe ratios, and efficiency metrics
to rank protocols on risk/reward profile.

Pure Python stdlib only. Atomic JSON writes via tmp+os.replace. Ring-buffer cap 100.
"""

import json
import math
import os
import tempfile
from datetime import datetime, timezone
from typing import List, Optional

# ---------------------------------------------------------------------------
# Data file
# ---------------------------------------------------------------------------
_DEFAULT_DATA_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "risk_adjusted_yield_log.json"
)

# ---------------------------------------------------------------------------
# Weights for composite risk score
# ---------------------------------------------------------------------------
_SC_WEIGHT = 0.30    # smart contract risk
_LIQ_WEIGHT = 0.20   # liquidity risk
_CP_WEIGHT = 0.20    # counterparty risk
_IL_WEIGHT = 0.15    # impermanent loss risk
_REG_WEIGHT = 0.15   # regulatory risk

# ---------------------------------------------------------------------------
# Label thresholds
# ---------------------------------------------------------------------------
_LABEL_TOP_TIER = "TOP_TIER"
_LABEL_HIGH_QUALITY = "HIGH_QUALITY"
_LABEL_STANDARD = "STANDARD"
_LABEL_HIGH_RISK = "HIGH_RISK"
_LABEL_RISK_TRAP = "RISK_TRAP"

# ---------------------------------------------------------------------------
# Flag constants
# ---------------------------------------------------------------------------
FLAG_NEW_PROTOCOL = "NEW_PROTOCOL"
FLAG_HIGH_VOLATILITY = "HIGH_VOLATILITY"
FLAG_SMART_CONTRACT_CONCERN = "SMART_CONTRACT_CONCERN"
FLAG_EFFICIENT_FRONTIER = "EFFICIENT_FRONTIER"
FLAG_RISK_TRAP = "RISK_TRAP"


def _clamp(value: float, lo: float = 0.0, hi: float = 100.0) -> float:
    return max(lo, min(hi, value))


def _safe_div(numerator: float, denominator: float, default: float = 0.0) -> float:
    if denominator == 0.0:
        return default
    return numerator / denominator


class DeFiRiskAdjustedYieldComparator:
    """Compare DeFi strategies by risk-adjusted yield metrics."""

    def __init__(self, data_file: Optional[str] = None):
        self._data_file = data_file or _DEFAULT_DATA_FILE

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def compare(self, strategies: List[dict], config: Optional[dict] = None) -> dict:
        """
        Compare strategies by risk-adjusted yield.

        Parameters
        ----------
        strategies : list[dict]
            Each dict must contain:
              name, protocol, gross_apy_pct, smart_contract_risk_score,
              liquidity_risk_score, counterparty_risk_score, il_risk_score,
              regulatory_risk_score, gas_cost_annual_pct, days_of_track_record,
              max_drawdown_pct, yield_volatility_pct
        config : dict, optional
            Optional overrides: top_tier_sharpe_threshold, top_tier_risk_threshold

        Returns
        -------
        dict with keys: results (list), aggregates (dict), run_ts (str)
        """
        if config is None:
            config = {}

        top_sharpe_thresh = float(config.get("top_tier_sharpe_threshold", 2.0))
        top_risk_thresh = float(config.get("top_tier_risk_threshold", 40.0))
        high_risk_thresh = float(config.get("high_risk_threshold", 60.0))
        risk_trap_thresh = float(config.get("risk_trap_risk_threshold", 70.0))
        risk_trap_yield_thresh = float(config.get("risk_trap_yield_threshold", 5.0))

        results = []
        for s in strategies:
            result = self._evaluate_strategy(
                s,
                top_sharpe_thresh=top_sharpe_thresh,
                top_risk_thresh=top_risk_thresh,
                high_risk_thresh=high_risk_thresh,
                risk_trap_thresh=risk_trap_thresh,
                risk_trap_yield_thresh=risk_trap_yield_thresh,
            )
            results.append(result)

        aggregates = self._compute_aggregates(results)
        run_ts = datetime.now(timezone.utc).isoformat()

        output = {
            "results": results,
            "aggregates": aggregates,
            "run_ts": run_ts,
            "strategy_count": len(results),
        }

        self._append_log(output)
        return output

    # ------------------------------------------------------------------
    # Strategy evaluation
    # ------------------------------------------------------------------

    def _evaluate_strategy(
        self,
        s: dict,
        *,
        top_sharpe_thresh: float,
        top_risk_thresh: float,
        high_risk_thresh: float,
        risk_trap_thresh: float,
        risk_trap_yield_thresh: float,
    ) -> dict:
        name = str(s.get("name", "unknown"))
        protocol = str(s.get("protocol", "unknown"))

        gross_apy = float(s.get("gross_apy_pct", 0.0))
        sc_risk = float(s.get("smart_contract_risk_score", 0.0))
        liq_risk = float(s.get("liquidity_risk_score", 0.0))
        cp_risk = float(s.get("counterparty_risk_score", 0.0))
        il_risk = float(s.get("il_risk_score", 0.0))
        reg_risk = float(s.get("regulatory_risk_score", 0.0))
        gas_cost = float(s.get("gas_cost_annual_pct", 0.0))
        track_days = int(s.get("days_of_track_record", 0))
        max_drawdown = float(s.get("max_drawdown_pct", 0.0))
        yield_vol = float(s.get("yield_volatility_pct", 1.0))

        # Composite risk score (weighted average)
        composite_risk = (
            sc_risk * _SC_WEIGHT
            + liq_risk * _LIQ_WEIGHT
            + cp_risk * _CP_WEIGHT
            + il_risk * _IL_WEIGHT
            + reg_risk * _REG_WEIGHT
        )
        composite_risk = _clamp(composite_risk)

        # Risk-adjusted yield (gross / (1 + composite_risk/100))
        risk_adjusted_yield = gross_apy / (1.0 + composite_risk / 100.0)

        # Net APY after gas
        net_apy_after_gas = gross_apy - gas_cost

        # DeFi Sharpe ratio (net_apy / yield_volatility)
        defi_sharpe = _safe_div(net_apy_after_gas, max(yield_vol, 0.001))

        # Risk efficiency score (0-100)
        risk_efficiency_score = _clamp(
            _safe_div(risk_adjusted_yield, max(gross_apy, 0.001)) * 100.0
        )

        # Comparison label
        label = self._compute_label(
            defi_sharpe=defi_sharpe,
            composite_risk=composite_risk,
            net_apy_after_gas=net_apy_after_gas,
            top_sharpe_thresh=top_sharpe_thresh,
            top_risk_thresh=top_risk_thresh,
            high_risk_thresh=high_risk_thresh,
            risk_trap_thresh=risk_trap_thresh,
            risk_trap_yield_thresh=risk_trap_yield_thresh,
        )

        # Flags
        flags = self._compute_flags(
            track_days=track_days,
            yield_vol=yield_vol,
            sc_risk=sc_risk,
            composite_risk=composite_risk,
            net_apy_after_gas=net_apy_after_gas,
            risk_trap_thresh=risk_trap_thresh,
            risk_trap_yield_thresh=risk_trap_yield_thresh,
        )

        return {
            "name": name,
            "protocol": protocol,
            "gross_apy_pct": gross_apy,
            "gas_cost_annual_pct": gas_cost,
            "net_apy_after_gas": round(net_apy_after_gas, 4),
            "composite_risk_score": round(composite_risk, 4),
            "risk_adjusted_yield": round(risk_adjusted_yield, 4),
            "defi_sharpe_ratio": round(defi_sharpe, 4),
            "risk_efficiency_score": round(risk_efficiency_score, 4),
            "max_drawdown_pct": max_drawdown,
            "yield_volatility_pct": yield_vol,
            "days_of_track_record": track_days,
            "label": label,
            "flags": flags,
        }

    def _compute_label(
        self,
        *,
        defi_sharpe: float,
        composite_risk: float,
        net_apy_after_gas: float,
        top_sharpe_thresh: float,
        top_risk_thresh: float,
        high_risk_thresh: float,
        risk_trap_thresh: float,
        risk_trap_yield_thresh: float,
    ) -> str:
        # RISK_TRAP: high risk AND low yield
        if composite_risk > risk_trap_thresh and net_apy_after_gas < risk_trap_yield_thresh:
            return _LABEL_RISK_TRAP

        # TOP_TIER: great sharpe AND low composite risk
        if defi_sharpe > top_sharpe_thresh and composite_risk < top_risk_thresh:
            return _LABEL_TOP_TIER

        # HIGH_RISK
        if composite_risk > high_risk_thresh:
            return _LABEL_HIGH_RISK

        # HIGH_QUALITY: good sharpe but not quite top tier
        if defi_sharpe > top_sharpe_thresh * 0.75 and composite_risk < top_risk_thresh * 1.25:
            return _LABEL_HIGH_QUALITY

        return _LABEL_STANDARD

    def _compute_flags(
        self,
        *,
        track_days: int,
        yield_vol: float,
        sc_risk: float,
        composite_risk: float,
        net_apy_after_gas: float,
        risk_trap_thresh: float,
        risk_trap_yield_thresh: float,
    ) -> List[str]:
        flags = []

        if track_days < 90:
            flags.append(FLAG_NEW_PROTOCOL)

        if yield_vol > 50.0:
            flags.append(FLAG_HIGH_VOLATILITY)

        if sc_risk > 60.0:
            flags.append(FLAG_SMART_CONTRACT_CONCERN)

        if composite_risk < 30.0 and net_apy_after_gas > 10.0:
            flags.append(FLAG_EFFICIENT_FRONTIER)

        if composite_risk > risk_trap_thresh and net_apy_after_gas < risk_trap_yield_thresh:
            flags.append(FLAG_RISK_TRAP)

        return flags

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def _compute_aggregates(self, results: List[dict]) -> dict:
        if not results:
            return {
                "best_risk_adjusted": None,
                "worst_risk_adjusted": None,
                "best_defi_sharpe": None,
                "top_tier_count": 0,
                "average_risk_adjusted_yield": 0.0,
            }

        sorted_by_ray = sorted(results, key=lambda r: r["risk_adjusted_yield"], reverse=True)
        sorted_by_sharpe = sorted(results, key=lambda r: r["defi_sharpe_ratio"], reverse=True)

        rays = [r["risk_adjusted_yield"] for r in results]
        avg_ray = sum(rays) / len(rays)
        top_tier_count = sum(1 for r in results if r["label"] == _LABEL_TOP_TIER)

        return {
            "best_risk_adjusted": sorted_by_ray[0]["name"],
            "worst_risk_adjusted": sorted_by_ray[-1]["name"],
            "best_defi_sharpe": sorted_by_sharpe[0]["name"],
            "top_tier_count": top_tier_count,
            "average_risk_adjusted_yield": round(avg_ray, 4),
        }

    # ------------------------------------------------------------------
    # Ring-buffer log
    # ------------------------------------------------------------------

    def _append_log(self, record: dict) -> None:
        """Atomically append record to ring-buffer log (cap 100)."""
        try:
            log = []
            if os.path.exists(self._data_file):
                try:
                    with open(self._data_file, "r", encoding="utf-8") as fh:
                        log = json.load(fh)
                    if not isinstance(log, list):
                        log = []
                except (json.JSONDecodeError, OSError):
                    log = []

            log.append(record)
            if len(log) > 100:
                log = log[-100:]

            dir_name = os.path.dirname(self._data_file)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)

            fd, tmp_path = tempfile.mkstemp(
                dir=dir_name or ".", suffix=".tmp"
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(log, fh, indent=2)
                os.replace(tmp_path, self._data_file)
            except Exception:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass
                raise
        except Exception:
            # Advisory module — never crash the caller
            pass
