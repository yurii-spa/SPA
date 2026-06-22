"""
MP-1168: DeFiProtocolVaultSharePriceDrawdownAnalyzer
====================================================
Advisory/read-only analytics module.

A vault's NAV-per-share (share price) has slipped BELOW its historical
high-water-mark (HWM). A holder must decide whether to HOLD-UNTIL-RECOVERY or
EXIT. This module measures how deep the drawdown is, how long the share price
has been underwater, how much upside is needed to reclaim the HWM, and the
recent trend (recovering vs deepening).

Angle: "share price is $0.94, the HWM was $1.00, it has been underwater for 40
days and is still drifting down → a deep, stale, deepening drawdown."

HIGHER score = shallower drawdown / closer to recovery / recovering trend.

Distinct from:
  * vault_depeg_recovery_analyzer → that one is about a PEGGED asset trading
    against its PEG (e.g. a stablecoin/LST holding $1). This module is about a
    vault's SHARE PRICE against its OWN high-water-mark, independent of any peg
    — the share price can have no peg at all and still drawdown vs its HWM.
  * generic drawdown_recovery_tracker → that one is PORTFOLIO-level. This module
    is strictly PER-VAULT share-price drawdown.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_share_price_drawdown_log.json"
)
LOG_CAP = 100

# Scoring reference: drawdown_pct normalised against this ceiling for the
# shallow-drawdown component (drawdown at/above this contributes nothing).
DRAWDOWN_SCORE_CEILING_PCT = 30.0
# Underwater-days normalised against this ceiling for the fresh component.
UNDERWATER_DAYS_SCORE_CEILING = 60.0

# Classification thresholds (drawdown as a percentage from HWM).
AT_HIGH_DRAWDOWN_PCT = 0.5      # drawdown at/below this → at-high
SHALLOW_DRAWDOWN_PCT = 5.0      # at/below this → shallow
MODERATE_DRAWDOWN_PCT = 20.0    # at/below this → moderate; above → deep

# Flag thresholds.
FRESH_DRAWDOWN_DAYS = 7.0       # underwater days below this → fresh
STALE_DRAWDOWN_DAYS = 30.0      # underwater days at/above this → stale
DEEP_DRAWDOWN_FLAG_PCT = 20.0   # drawdown at/above this → deep flag


# ── helpers ───────────────────────────────────────────────────────────────────

def _f(val, default: float = 0.0) -> float:
    try:
        if val is None:
            return default
        return float(val)
    except (TypeError, ValueError):
        return default


def _clamp(val: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, val))


def _mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _safe_div(num: float, den: float, sentinel: float) -> float:
    if den <= 0:
        return sentinel
    return num / den


def _build_default_cfg(overrides: Optional[dict] = None) -> dict:
    cfg = {"log_path": LOG_PATH, "log_cap": LOG_CAP}
    if overrides:
        cfg.update(overrides)
    return cfg


def _grade_from_score(score: float) -> str:
    if score >= 85:
        return "A"
    if score >= 70:
        return "B"
    if score >= 55:
        return "C"
    if score >= 40:
        return "D"
    return "F"


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolVaultSharePriceDrawdownAnalyzer:
    """
    Models a vault's SHARE-PRICE drawdown against its own historical
    high-water-mark. The current NAV-per-share is compared to the peak HWM to
    measure drawdown depth, the upside needed to reclaim the HWM, how long the
    position has been underwater, and the recent trend. The holder's decision is
    HOLD-UNTIL-RECOVERY vs EXIT.

    HIGHER score = shallower drawdown / closer to recovery / recovering trend.

    Per-position input dict fields:
        vault / token              : str
        current_share_price_usd    : float (default 0)
        high_water_mark_usd        : float (default 0; peak share price)
        entry_share_price_usd      : float (default 0; cost basis)
        days_underwater            : float (default 0; max(0,..))
        recent_share_price_usd     : float (default 0; price N days ago, trend)
    """

    # ── public API ────────────────────────────────────────────────────────────

    def analyze(
        self,
        position: dict,
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        result = self._analyze_one(position)
        if write_log:
            self._write_log([result], self._aggregate([result]), cfg)
        return result

    def analyze_portfolio(
        self,
        positions: List[dict],
        cfg: Optional[dict] = None,
        write_log: bool = False,
    ) -> dict:
        cfg = _build_default_cfg(cfg)
        results = [self._analyze_one(p) for p in positions]
        agg = self._aggregate(results)
        if write_log:
            self._write_log(results, agg, cfg)
        return {"positions": results, "aggregate": agg}

    # ── per-position ───────────────────────────────────────────────────────────

    def _analyze_one(self, p: dict) -> dict:
        token = p.get("vault", p.get("token", "UNKNOWN"))
        current = _f(p.get("current_share_price_usd"))
        hwm = _f(p.get("high_water_mark_usd"))
        entry = _f(p.get("entry_share_price_usd"))
        days_underwater = max(0.0, _f(p.get("days_underwater")))
        recent = _f(p.get("recent_share_price_usd"))

        # Insufficient data: no current price or no HWM to measure against.
        if current <= 0 or hwm <= 0:
            return self._insufficient(token)

        # Drawdown depth from HWM (>= 0).
        drawdown_pct = _clamp((hwm - current) / hwm * 100.0, 0.0, 1e9)

        # Recovery needed: upside % from current to reclaim HWM (>= 0).
        recovery_needed = _safe_div(hwm, current, None)
        if recovery_needed is None or not math.isfinite(recovery_needed):
            recovery_needed_pct = 0.0
        else:
            recovery_needed_pct = _clamp((recovery_needed - 1.0) * 100.0,
                                         0.0, 1e9)

        # Underwater vs entry (cost basis). 0 if no entry recorded.
        if entry > 0:
            underwater_vs_entry_pct = (entry - current) / entry * 100.0
        else:
            underwater_vs_entry_pct = 0.0
        position_underwater = bool(entry > 0 and current < entry)

        is_stale_drawdown = bool(days_underwater >= STALE_DRAWDOWN_DAYS)

        # Trend from the recent (N-days-ago) share price.
        recovering = bool(recent > 0 and current > recent)
        deepening = bool(recent > 0 and current < recent)
        if recent > 0:
            trend_pct = (current / recent - 1.0) * 100.0
            if not math.isfinite(trend_pct):
                trend_pct = 0.0
        else:
            trend_pct = 0.0

        score = self._score(drawdown_pct, days_underwater, recovering,
                             deepening)
        classification = self._classify(drawdown_pct)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, recovering)
        flags = self._flags(
            classification, drawdown_pct, days_underwater, recovering,
            deepening, position_underwater)

        return {
            "token": token,
            "current_share_price_usd": round(current, 4),
            "high_water_mark_usd": round(hwm, 4),
            "entry_share_price_usd": round(entry, 4),
            "days_underwater": round(days_underwater, 4),
            "recent_share_price_usd": round(recent, 4),
            "drawdown_pct": round(drawdown_pct, 4),
            "recovery_needed_pct": round(recovery_needed_pct, 4),
            "underwater_vs_entry_pct": round(underwater_vs_entry_pct, 4),
            "position_underwater": position_underwater,
            "is_stale_drawdown": is_stale_drawdown,
            "recovering": recovering,
            "deepening": deepening,
            "trend_pct": round(trend_pct, 4),
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        drawdown_pct: float,
        days_underwater: float,
        recovering: bool,
        deepening: bool,
    ) -> float:
        """
        0–100, HIGHER = shallower drawdown / closer to recovery. Components:
          shallow drawdown (50) — drawdown normalised against the ceiling.
          fresh / not stale (20) — underwater-days normalised against ceiling.
          recovering trend (30) — recovering→full, deepening→0, flat→half.
        """
        shallow_comp = 50.0 * _clamp(
            1.0 - drawdown_pct / DRAWDOWN_SCORE_CEILING_PCT, 0.0, 1.0)
        fresh_comp = 20.0 * _clamp(
            1.0 - days_underwater / UNDERWATER_DAYS_SCORE_CEILING, 0.0, 1.0)
        if recovering:
            trend_comp = 30.0
        elif deepening:
            trend_comp = 0.0
        else:
            trend_comp = 15.0
        total = shallow_comp + fresh_comp + trend_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, drawdown_pct: float) -> str:
        if drawdown_pct <= AT_HIGH_DRAWDOWN_PCT:
            return "AT_HIGH"
        if drawdown_pct <= SHALLOW_DRAWDOWN_PCT:
            return "SHALLOW_DRAWDOWN"
        if drawdown_pct <= MODERATE_DRAWDOWN_PCT:
            return "MODERATE_DRAWDOWN"
        return "DEEP_DRAWDOWN"

    def _recommend(self, classification: str, recovering: bool) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "HOLD"
        if classification in ("AT_HIGH", "SHALLOW_DRAWDOWN"):
            return "HOLD"
        if classification == "MODERATE_DRAWDOWN":
            # Recovering trend softens by one step (already at HOLD floor).
            return "HOLD" if recovering else "HOLD_FOR_RECOVERY"
        # DEEP_DRAWDOWN
        return "HOLD_FOR_RECOVERY" if recovering else "EXIT"

    def _flags(
        self,
        classification: str,
        drawdown_pct: float,
        days_underwater: float,
        recovering: bool,
        deepening: bool,
        position_underwater: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "AT_HIGH":
            flags.append("AT_HIGH")
        if days_underwater < FRESH_DRAWDOWN_DAYS and \
                drawdown_pct > AT_HIGH_DRAWDOWN_PCT:
            flags.append("FRESH_DRAWDOWN")
        if days_underwater >= STALE_DRAWDOWN_DAYS:
            flags.append("STALE_DRAWDOWN")
        if recovering:
            flags.append("RECOVERING")
        if deepening:
            flags.append("DEEPENING")
        if position_underwater:
            flags.append("POSITION_UNDERWATER")
        if drawdown_pct >= DEEP_DRAWDOWN_FLAG_PCT:
            flags.append("DEEP_DRAWDOWN")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "current_share_price_usd": 0.0,
            "high_water_mark_usd": 0.0,
            "entry_share_price_usd": 0.0,
            "days_underwater": 0.0,
            "recent_share_price_usd": 0.0,
            "drawdown_pct": 0.0,
            "recovery_needed_pct": 0.0,
            "underwater_vs_entry_pct": 0.0,
            "position_underwater": False,
            "is_stale_drawdown": False,
            "recovering": False,
            "deepening": False,
            "trend_pct": 0.0,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "HOLD",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "shallowest_vault": None,
                "deepest_vault": None,
                "avg_score": 0.0,
                "deep_drawdown_count": 0,
                "position_count": len(results),
            }
        # Higher score = shallower drawdown → highest score is shallowest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        deep = sum(
            1 for r in results if r["classification"] == "DEEP_DRAWDOWN")
        return {
            "shallowest_vault": by_score[-1]["token"],
            "deepest_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "deep_drawdown_count": deep,
            "position_count": len(results),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(self, results: List[dict], agg: dict, cfg: dict) -> None:
        log_path = cfg["log_path"]
        cap = cfg["log_cap"]
        os.makedirs(os.path.dirname(log_path), exist_ok=True)

        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "position_count": len(results),
            "aggregate": agg,
            "snapshots": [
                {
                    "token": r["token"],
                    "classification": r["classification"],
                    "score": r["score"],
                    "recommendation": r["recommendation"],
                    "flags": r["flags"],
                }
                for r in results
            ],
        }

        log: List[dict] = []
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


# ── CLI ───────────────────────────────────────────────────────────────────────

def _demo_positions() -> List[dict]:
    return [
        {
            "vault": "USDC-Vault-AtHigh",
            "current_share_price_usd": 1.0,
            "high_water_mark_usd": 1.0,
            "entry_share_price_usd": 0.98,
            "days_underwater": 0.0,
            "recent_share_price_usd": 0.99,
        },
        {
            "vault": "GMX-Vault-DeepStale",
            "current_share_price_usd": 0.70,
            "high_water_mark_usd": 1.0,
            "entry_share_price_usd": 0.95,
            "days_underwater": 45.0,
            "recent_share_price_usd": 0.74,
        },
        {
            "vault": "DAI-Vault-NoData",
            "current_share_price_usd": 0.0,
            "high_water_mark_usd": 0.0,
            "entry_share_price_usd": 0.0,
            "days_underwater": 0.0,
            "recent_share_price_usd": 0.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1168 Vault Share Price Drawdown Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultSharePriceDrawdownAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
