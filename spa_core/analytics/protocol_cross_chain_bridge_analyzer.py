"""
MP-904: Protocol Cross-Chain Bridge Analyzer
Evaluates security and efficiency of cross-chain bridge protocols.

Standalone module — stdlib only, no external dependencies.
Atomic writes: tmp file + os.replace().
"""
import json
import os
import tempfile
from typing import Any, Dict, List


class ProtocolCrossChainBridgeAnalyzer:
    """
    Analyzes cross-chain bridge protocols for security and efficiency.

    Input fields per bridge (dict):
        name                  (str)   – bridge name
        tvl_locked_usd        (float) – total value locked (USD)
        hack_history          (list)  – list of hack incidents (dicts or strings)
        validator_count       (int)   – number of validators / relayers
        finality_time_seconds (float) – time to finality (seconds)
        fee_pct               (float) – bridging fee (%)
        supported_chains      (list)  – list of supported chain names/IDs
        audit_count           (int)   – number of security audits
        age_days              (int)   – days since launch
        daily_volume_usd      (float) – daily transaction volume (USD)

    Output per bridge:
        security_score   (0-100, higher = more secure)
        efficiency_score (0-100, higher = more efficient)
        trust_score      (0-100, composite of security + efficiency)
        safety_label     VERY_SAFE / SAFE / MODERATE / RISKY / VERY_RISKY / CRITICAL
        flags            list[str] from HACK_HISTORY / FEW_VALIDATORS /
                                        SLOW_FINALITY / HIGH_FEE / LOW_AUDIT
        hack_count       (int)

    Aggregates:
        safest_bridge, riskiest_bridge, total_tvl_at_risk_usd,
        hack_count_total, average_efficiency, total_bridges

    config keys:
        log_path (str)  – path for ring-buffer JSON log
        persist  (bool) – if True, append result to log
    """

    LOG_CAP = 100
    DEFAULT_LOG_PATH = "data/bridge_analyzer_log.json"

    # Flag thresholds
    FEW_VALIDATORS_THRESHOLD = 5
    SLOW_FINALITY_THRESHOLD  = 3600   # seconds
    HIGH_FEE_THRESHOLD       = 1.0    # percent

    # Safety label thresholds: trust_score → label (ascending trust = safer)
    _SAFETY_LABEL_THRESHOLDS = [
        (20.0,  "CRITICAL"),
        (40.0,  "VERY_RISKY"),
        (55.0,  "RISKY"),
        (70.0,  "MODERATE"),
        (85.0,  "SAFE"),
    ]

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def analyze(
        self,
        bridges: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Analyze cross-chain bridges for security and efficiency.

        :param bridges: list of bridge dicts (see class docstring for fields)
        :param config:  configuration dict (log_path, persist)
        :return:        dict with per-bridge scores and aggregate metrics
        """
        log_path = config.get("log_path", self.DEFAULT_LOG_PATH)
        persist  = config.get("persist", False)

        if not bridges:
            result = self._empty_result()
            if persist:
                self._append_log(log_path, result)
            return result

        analyzed = [self._analyze_single(b, config) for b in bridges]
        aggregates = self._compute_aggregates(analyzed)

        result = {
            "bridges":    analyzed,
            "aggregates": aggregates,
            "status":     "ok",
        }

        if persist:
            self._append_log(log_path, result)

        return result

    # ------------------------------------------------------------------ #
    # Private — per-bridge                                                 #
    # ------------------------------------------------------------------ #

    def _analyze_single(
        self, bridge: Dict[str, Any], config: Dict[str, Any]
    ) -> Dict[str, Any]:
        name             = str(bridge.get("name", "unknown"))
        tvl              = float(bridge.get("tvl_locked_usd", 0.0))
        hack_history     = bridge.get("hack_history", [])
        validator_count  = int(bridge.get("validator_count", 0))
        finality_secs    = float(bridge.get("finality_time_seconds", 0.0))
        fee_pct          = float(bridge.get("fee_pct", 0.0))
        supported_chains = bridge.get("supported_chains", [])
        audit_count      = int(bridge.get("audit_count", 0))
        age_days         = int(bridge.get("age_days", 0))
        daily_volume     = float(bridge.get("daily_volume_usd", 0.0))

        hack_count = len(hack_history) if isinstance(hack_history, list) else 0

        security_score   = self._compute_security_score(
            hack_count, validator_count, audit_count, age_days, tvl
        )
        efficiency_score = self._compute_efficiency_score(
            finality_secs, fee_pct, supported_chains, daily_volume, tvl
        )
        trust_score      = self._compute_trust_score(
            security_score, efficiency_score, hack_count, audit_count
        )
        safety_label     = self._get_safety_label(trust_score)
        flags            = self._compute_flags(
            hack_count, validator_count, finality_secs, fee_pct, audit_count
        )

        return {
            "name":             name,
            "tvl_locked_usd":   tvl,
            "hack_count":       hack_count,
            "security_score":   round(security_score,   2),
            "efficiency_score": round(efficiency_score, 2),
            "trust_score":      round(trust_score,      2),
            "safety_label":     safety_label,
            "flags":            flags,
        }

    # ------------------------------------------------------------------ #
    # Private — sub-scores                                                 #
    # ------------------------------------------------------------------ #

    def _compute_security_score(
        self,
        hack_count: int,
        validator_count: int,
        audit_count: int,
        age_days: int,
        tvl: float,
    ) -> float:
        """Higher = more secure. 0-100."""
        score = 60.0  # base

        # Hack history
        if hack_count == 0:
            score += 15
        elif hack_count == 1:
            score -= 20
        elif hack_count == 2:
            score -= 40
        else:
            score -= 55

        # Validators
        if validator_count >= 50:
            score += 15
        elif validator_count >= 20:
            score += 10
        elif validator_count >= 10:
            score += 5
        elif validator_count >= self.FEW_VALIDATORS_THRESHOLD:
            pass   # neutral
        else:
            score -= 15

        # Audits
        if audit_count >= 3:
            score += 15
        elif audit_count == 2:
            score += 10
        elif audit_count == 1:
            score += 5
        else:
            score -= 15

        # Age
        if age_days >= 730:
            score += 10
        elif age_days >= 365:
            score += 5
        elif age_days >= 90:
            pass
        elif age_days >= 30:
            score -= 5
        else:
            score -= 15

        return max(0.0, min(100.0, score))

    def _compute_efficiency_score(
        self,
        finality_secs: float,
        fee_pct: float,
        supported_chains: list,
        daily_volume: float,
        tvl: float,
    ) -> float:
        """Higher = more efficient. 0-100."""
        score = 50.0

        # Finality time
        if finality_secs <= 60:
            score += 25
        elif finality_secs <= 300:
            score += 15
        elif finality_secs <= 900:
            score += 5
        elif finality_secs <= self.SLOW_FINALITY_THRESHOLD:
            score -= 5
        else:
            score -= 25

        # Fee
        if fee_pct <= 0.05:
            score += 15
        elif fee_pct <= 0.1:
            score += 10
        elif fee_pct <= 0.5:
            score += 5
        elif fee_pct <= self.HIGH_FEE_THRESHOLD:
            score -= 5
        else:
            score -= 20

        # Chain coverage
        chain_count = len(supported_chains) if isinstance(supported_chains, list) else 0
        if chain_count >= 20:
            score += 10
        elif chain_count >= 10:
            score += 5
        elif chain_count >= 5:
            pass
        else:
            score -= 5

        # Volume/TVL utilisation
        if tvl > 0:
            util = daily_volume / tvl
            if util >= 0.1:
                score += 5
            elif util >= 0.01:
                score += 2
            else:
                score -= 3

        return max(0.0, min(100.0, score))

    def _compute_trust_score(
        self,
        security_score: float,
        efficiency_score: float,
        hack_count: int,
        audit_count: int,
    ) -> float:
        """Composite trust. Higher = more trustworthy. 0-100."""
        score = security_score * 0.60 + efficiency_score * 0.40

        # Hack penalty multipliers
        if hack_count >= 2:
            score *= 0.70
        elif hack_count == 1:
            score *= 0.85

        # No audit penalty
        if audit_count == 0:
            score *= 0.90

        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------ #
    # Private — classification                                             #
    # ------------------------------------------------------------------ #

    def _get_safety_label(self, trust_score: float) -> str:
        for threshold, label in self._SAFETY_LABEL_THRESHOLDS:
            if trust_score < threshold:
                return label
        return "VERY_SAFE"

    def _compute_flags(
        self,
        hack_count: int,
        validator_count: int,
        finality_secs: float,
        fee_pct: float,
        audit_count: int,
    ) -> List[str]:
        flags = []
        if hack_count > 0:
            flags.append("HACK_HISTORY")
        if validator_count < self.FEW_VALIDATORS_THRESHOLD:
            flags.append("FEW_VALIDATORS")
        if finality_secs > self.SLOW_FINALITY_THRESHOLD:
            flags.append("SLOW_FINALITY")
        if fee_pct > self.HIGH_FEE_THRESHOLD:
            flags.append("HIGH_FEE")
        if audit_count == 0:
            flags.append("LOW_AUDIT")
        return flags

    # ------------------------------------------------------------------ #
    # Private — aggregates                                                 #
    # ------------------------------------------------------------------ #

    def _compute_aggregates(self, analyzed: List[Dict]) -> Dict[str, Any]:
        trust_scores  = [b["trust_score"] for b in analyzed]
        max_idx       = trust_scores.index(max(trust_scores))
        min_idx       = trust_scores.index(min(trust_scores))

        total_tvl     = sum(b["tvl_locked_usd"] for b in analyzed)
        total_hacks   = sum(b["hack_count"] for b in analyzed)
        avg_efficiency = (
            sum(b["efficiency_score"] for b in analyzed) / len(analyzed)
        )

        return {
            "safest_bridge":        analyzed[max_idx]["name"],
            "riskiest_bridge":      analyzed[min_idx]["name"],
            "total_tvl_at_risk_usd": total_tvl,
            "hack_count_total":     total_hacks,
            "average_efficiency":   round(avg_efficiency, 2),
            "total_bridges":        len(analyzed),
        }

    # ------------------------------------------------------------------ #
    # Private — helpers                                                    #
    # ------------------------------------------------------------------ #

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "bridges": [],
            "aggregates": {
                "safest_bridge":         None,
                "riskiest_bridge":       None,
                "total_tvl_at_risk_usd": 0.0,
                "hack_count_total":      0,
                "average_efficiency":    0.0,
                "total_bridges":         0,
            },
            "status": "ok",
        }

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
                dir=dir_name, prefix=".bridge_analyzer_tmp_"
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
