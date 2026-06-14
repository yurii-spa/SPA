"""
MP-903: DeFi Yield Farming Risk Scorer
Evaluates risk of yield farming positions across multiple dimensions.

Standalone module — stdlib only, no external dependencies.
Atomic writes: tmp file + os.replace().
"""
import json
import os
import tempfile
from typing import Any, Dict, List


class DeFiYieldFarmingRiskScorer:
    """
    Scores yield farming positions for risk.

    Input fields per farm (dict):
        protocol (str)                      – protocol name
        token_pair (str)                    – e.g. "USDC/USDT"
        apy_pct (float)                     – annual percentage yield
        tvl_usd (float)                     – total value locked (USD)
        age_days (int)                      – days since protocol launch
        audit_count (int)                   – number of security audits
        rug_incidents (int)                 – number of rug-pull incidents
        liquidity_depth_usd (float)         – depth of liquidity (USD)
        reward_token_price_change_30d (float) – % change in reward token price over 30 days

    Output per farm:
        sustainability_score  (0-100, higher = more sustainable)
        rug_risk_score        (0-100, higher = riskier)
        il_risk_score         (0-100, higher = more IL risk)
        composite_risk        (0-100, higher = riskier overall)
        risk_label            VERY_LOW / LOW / MODERATE / HIGH / VERY_HIGH / EXTREME
        flags                 list[str] from HIGH_APY_RISK / NEW_PROTOCOL /
                                            LOW_TVL / UNAUDITED / RUG_HISTORY

    Aggregates:
        safest_farm, riskiest_farm, average_composite_risk,
        extreme_count, very_low_count, total_farms

    config keys:
        log_path (str)   – path for ring-buffer JSON log
        persist (bool)   – if True, append result to log
        weights (dict)   – optional weight overrides:
                           sustainability (default 0.30)
                           rug_risk      (default 0.40)
                           il_risk       (default 0.30)
    """

    LOG_CAP = 100
    DEFAULT_LOG_PATH = "data/yield_farming_risk_log.json"

    # Flag thresholds
    APY_HIGH_RISK_THRESHOLD = 500.0
    NEW_PROTOCOL_DAYS = 30
    LOW_TVL_THRESHOLD = 100_000.0

    # Risk label thresholds: (upper_exclusive_bound, label)
    _RISK_LABEL_THRESHOLDS = [
        (20.0,  "VERY_LOW"),
        (40.0,  "LOW"),
        (60.0,  "MODERATE"),
        (75.0,  "HIGH"),
        (90.0,  "VERY_HIGH"),
    ]

    # Stablecoins for IL computation
    _STABLE_SET = frozenset({
        "usdc", "usdt", "dai", "frax", "busd", "tusd",
        "usds", "susd", "lusd", "crvusd", "gusd", "usdp",
        "fei", "rai", "musd",
    })

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    def score(
        self,
        farms: List[Dict[str, Any]],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Score yield farming risk for a list of farm positions.

        :param farms:  list of farm dicts (see class docstring for fields)
        :param config: configuration dict (log_path, persist, weights)
        :return:       dict with per-farm scores and aggregate metrics
        """
        log_path = config.get("log_path", self.DEFAULT_LOG_PATH)
        persist  = config.get("persist", False)

        if not farms:
            result = self._empty_result()
            if persist:
                self._append_log(log_path, result)
            return result

        scored_farms = [self._score_single(f, config) for f in farms]
        aggregates   = self._compute_aggregates(scored_farms)

        result = {
            "farms":      scored_farms,
            "aggregates": aggregates,
            "status":     "ok",
        }

        if persist:
            self._append_log(log_path, result)

        return result

    # ------------------------------------------------------------------ #
    # Private — per-farm                                                   #
    # ------------------------------------------------------------------ #

    def _score_single(
        self,
        farm: Dict[str, Any],
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        protocol      = str(farm.get("protocol", "unknown"))
        token_pair    = str(farm.get("token_pair", "unknown"))
        apy_pct       = float(farm.get("apy_pct", 0.0))
        tvl_usd       = float(farm.get("tvl_usd", 0.0))
        age_days      = int(farm.get("age_days", 0))
        audit_count   = int(farm.get("audit_count", 0))
        rug_incidents = int(farm.get("rug_incidents", 0))
        liq_depth     = float(farm.get("liquidity_depth_usd", 0.0))
        rw_chg        = float(farm.get("reward_token_price_change_30d", 0.0))

        sustainability = self._compute_sustainability(apy_pct, tvl_usd, age_days)
        rug_risk       = self._compute_rug_risk(audit_count, rug_incidents, age_days, tvl_usd)
        il_risk        = self._compute_il_risk(token_pair, rw_chg, liq_depth, apy_pct)

        weights = config.get("weights", {}) if isinstance(config.get("weights"), dict) else {}
        w_sust = float(weights.get("sustainability", 0.30))
        w_rug  = float(weights.get("rug_risk",       0.40))
        w_il   = float(weights.get("il_risk",        0.30))

        composite_risk = (
            (100.0 - sustainability) * w_sust
            + rug_risk               * w_rug
            + il_risk                * w_il
        )
        composite_risk = max(0.0, min(100.0, composite_risk))

        return {
            "protocol":           protocol,
            "token_pair":         token_pair,
            "apy_pct":            apy_pct,
            "sustainability_score": round(sustainability,  2),
            "rug_risk_score":       round(rug_risk,        2),
            "il_risk_score":        round(il_risk,         2),
            "composite_risk":       round(composite_risk,  2),
            "risk_label":           self._get_risk_label(composite_risk),
            "flags":                self._compute_flags(
                                        apy_pct, age_days, tvl_usd,
                                        audit_count, rug_incidents),
        }

    # ------------------------------------------------------------------ #
    # Private — sub-scores                                                 #
    # ------------------------------------------------------------------ #

    def _compute_sustainability(
        self, apy_pct: float, tvl_usd: float, age_days: int
    ) -> float:
        """Higher = more sustainable. 0-100."""
        score = 100.0

        # APY sustainability: very high APY is structurally fragile
        if apy_pct <= 0:
            score -= 40
        elif apy_pct <= 5:
            score -= 0
        elif apy_pct <= 20:
            score -= 5
        elif apy_pct <= 50:
            score -= 15
        elif apy_pct <= 100:
            score -= 30
        elif apy_pct <= 300:
            score -= 50
        elif apy_pct <= 500:
            score -= 65
        else:
            score -= 80

        # TVL: larger TVL → more sustainable
        if tvl_usd >= 100_000_000:
            pass
        elif tvl_usd >= 10_000_000:
            score -= 5
        elif tvl_usd >= 1_000_000:
            score -= 15
        elif tvl_usd >= 100_000:
            score -= 25
        else:
            score -= 40

        # Age: older → more battle-tested
        if age_days >= 365:
            pass
        elif age_days >= 180:
            score -= 5
        elif age_days >= 90:
            score -= 10
        elif age_days >= 30:
            score -= 20
        else:
            score -= 30

        return max(0.0, min(100.0, score))

    def _compute_rug_risk(
        self, audit_count: int, rug_incidents: int, age_days: int, tvl_usd: float
    ) -> float:
        """Higher = riskier (rug). 0-100."""
        score = 0.0

        # Audit count
        if audit_count == 0:
            score += 40
        elif audit_count == 1:
            score += 20
        elif audit_count == 2:
            score += 10
        # ≥3 audits: +0

        # Rug incidents
        if rug_incidents == 1:
            score += 25
        elif rug_incidents == 2:
            score += 45
        elif rug_incidents >= 3:
            score += 60

        # Age
        if age_days < 30:
            score += 20
        elif age_days < 90:
            score += 10
        elif age_days < 180:
            score += 5

        # TVL as trust signal
        if tvl_usd < 100_000:
            score += 10
        elif tvl_usd < 1_000_000:
            score += 5

        return max(0.0, min(100.0, score))

    def _compute_il_risk(
        self,
        token_pair: str,
        reward_price_change: float,
        liquidity_depth: float,
        apy_pct: float,
    ) -> float:
        """Higher = more impermanent-loss risk. 0-100."""
        score = 20.0  # base

        # Determine if pair is stable-stable or single-sided
        pair_lower = (
            token_pair.lower()
            .replace("-", "/")
            .replace("_", "/")
        )
        parts = [p.strip() for p in pair_lower.split("/") if p.strip()]

        is_stable  = all(p in self._STABLE_SET for p in parts)
        is_single  = len(parts) <= 1 or (len(set(parts)) == 1)

        if is_stable or is_single:
            score -= 15   # near-zero IL
        else:
            score += 20   # volatile pairs

        # Reward token price trajectory
        if reward_price_change <= -50:
            score += 30
        elif reward_price_change <= -20:
            score += 20
        elif reward_price_change <= 0:
            score += 10
        elif reward_price_change <= 20:
            pass
        elif reward_price_change <= 50:
            score -= 5
        else:
            score -= 10

        # Liquidity depth — shallow = hard to exit
        if liquidity_depth < 100_000:
            score += 20
        elif liquidity_depth < 1_000_000:
            score += 10
        elif liquidity_depth < 10_000_000:
            score += 5

        # High APY with volatile pair suggests more volatility
        if not (is_stable or is_single) and apy_pct > 100:
            score += 10

        return max(0.0, min(100.0, score))

    # ------------------------------------------------------------------ #
    # Private — classification                                             #
    # ------------------------------------------------------------------ #

    def _get_risk_label(self, composite_risk: float) -> str:
        for threshold, label in self._RISK_LABEL_THRESHOLDS:
            if composite_risk < threshold:
                return label
        return "EXTREME"

    def _compute_flags(
        self,
        apy_pct: float,
        age_days: int,
        tvl_usd: float,
        audit_count: int,
        rug_incidents: int,
    ) -> List[str]:
        flags = []
        if apy_pct > self.APY_HIGH_RISK_THRESHOLD:
            flags.append("HIGH_APY_RISK")
        if age_days < self.NEW_PROTOCOL_DAYS:
            flags.append("NEW_PROTOCOL")
        if tvl_usd < self.LOW_TVL_THRESHOLD:
            flags.append("LOW_TVL")
        if audit_count == 0:
            flags.append("UNAUDITED")
        if rug_incidents > 0:
            flags.append("RUG_HISTORY")
        return flags

    # ------------------------------------------------------------------ #
    # Private — aggregates                                                 #
    # ------------------------------------------------------------------ #

    def _compute_aggregates(self, scored_farms: List[Dict]) -> Dict[str, Any]:
        risks = [f["composite_risk"] for f in scored_farms]
        avg   = sum(risks) / len(risks)

        safest_idx   = risks.index(min(risks))
        riskiest_idx = risks.index(max(risks))

        extreme_count  = sum(1 for f in scored_farms if f["risk_label"] == "EXTREME")
        very_low_count = sum(1 for f in scored_farms if f["risk_label"] == "VERY_LOW")

        return {
            "safest_farm":            scored_farms[safest_idx]["protocol"],
            "riskiest_farm":          scored_farms[riskiest_idx]["protocol"],
            "average_composite_risk": round(avg, 2),
            "extreme_count":          extreme_count,
            "very_low_count":         very_low_count,
            "total_farms":            len(scored_farms),
        }

    # ------------------------------------------------------------------ #
    # Private — log persistence                                            #
    # ------------------------------------------------------------------ #

    def _empty_result(self) -> Dict[str, Any]:
        return {
            "farms": [],
            "aggregates": {
                "safest_farm":            None,
                "riskiest_farm":          None,
                "average_composite_risk": 0.0,
                "extreme_count":          0,
                "very_low_count":         0,
                "total_farms":            0,
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
                dir=dir_name, prefix=".yield_farming_risk_tmp_"
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
