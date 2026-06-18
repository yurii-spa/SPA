"""
MP-1174: DeFiProtocolVaultSharePriceStalenessAnalyzer
=====================================================
Advisory/read-only analytics module.

How stale is the vault's reported pricePerShare / NAV relative to its expected
update cadence? A vault that updates NAV only on harvest or via a lagged keeper
can show a share price that lags the actual accrued underlying value; entering
or exiting on a stale NAV is mispricing risk. The unreflected value change
(nav_drift) is what the reported price has not yet caught up to. An
oracle-priced vault is continuously fresh, so its effective staleness is zero.

Angle: "the vault last repriced 9h ago against a 2h cadence (4.5x overdue) and
~0.8% of underlying gain is unreflected → the reported NAV is mispriced; await
the next NAV update before trading."

HIGHER score = fresher / more trustworthy reported NAV.

Distinct from:
  * defi_oracle_manipulation_risk_scorer / oracle_freshness — the price oracle
    of the UNDERLYING asset, not the vault's own share-price report.
  * defi_protocol_vault_pending_harvest_premium_analyzer — values the premium
    baked INTO the share price; THIS module isolates the reporting cadence /
    staleness of the vault's own share price / NAV report.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_share_price_staleness_log.json"
)
LOG_CAP = 100

# Freshness scoring ceilings.
STALE_CEILING_RATIO = 2.0   # freshness reaches 0 at this staleness ratio
DRIFT_CEILING_PCT = 2.0     # drift component reaches 0 at this abs drift

# Drift flag / mispricing thresholds (% of NAV).
SIGNIFICANT_DRIFT_PCT = 0.5   # abs drift at/above this is significant

# Staleness-ratio classification thresholds.
FRESH_RATIO = 1.0     # eff ratio at/below this → FRESH
STALE_RATIO = 2.0     # eff ratio at/below this → SLIGHTLY_STALE; >= → sig. stale
SEVERE_RATIO = 4.0    # eff ratio at/below this → STALE; above → SEVERELY_STALE


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


def _safe_div(num: float, den: float, sentinel):
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

class DeFiProtocolVaultSharePriceStalenessAnalyzer:
    """
    Measures how stale a vault's reported pricePerShare / NAV is relative to its
    expected update cadence. The staleness ratio (hours since last update over
    the expected interval) and the unreflected value drift combine into a
    freshness score. An oracle-priced vault is treated as continuously fresh
    (effective ratio zero). A stale NAV with significant unreflected drift is a
    mispricing-risk condition for entering or exiting.

    HIGHER score = fresher / more trustworthy reported NAV.

    Per-position input dict fields:
        vault / token                 : str
        expected_update_interval_hours: float (max(0,..)); <=0 → INSUFFICIENT.
        hours_since_last_nav_update   : float (default 0; max(0,..)).
        nav_drift_pct                 : float (signed, default 0) — underlying
                                        value change accrued since the last NAV
                                        update, not yet reflected in the report.
        is_oracle_priced              : bool (default False) — continuously
                                        repriced; effective staleness is zero.
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
        expected_interval = max(0.0, _f(p.get("expected_update_interval_hours")))

        # Insufficient data fast-path: no expected cadence gives no basis for a
        # staleness judgement.
        if expected_interval <= 0:
            return self._insufficient(token)

        hours_since = max(0.0, _f(p.get("hours_since_last_nav_update")))
        nav_drift_pct = _f(p.get("nav_drift_pct"))
        is_oracle_priced = bool(p.get("is_oracle_priced", False))

        abs_drift_pct = abs(nav_drift_pct)

        # Raw staleness ratio; None sentinel if interval non-positive (already
        # guarded above, but kept consistent with the metric contract).
        staleness_ratio = _safe_div(hours_since, expected_interval, None)
        if staleness_ratio is not None and not math.isfinite(staleness_ratio):
            staleness_ratio = None

        # An oracle-priced vault is continuously fresh → effective ratio 0.
        eff_ratio = 0.0 if is_oracle_priced else (staleness_ratio or 0.0)

        hours_overdue = max(0.0, hours_since - expected_interval)
        is_overdue = hours_since > expected_interval
        significantly_stale = bool(eff_ratio >= STALE_RATIO)
        is_fresh = bool(eff_ratio <= FRESH_RATIO)
        mispricing_risk = bool(
            abs_drift_pct >= SIGNIFICANT_DRIFT_PCT and not is_fresh)

        score = self._score(eff_ratio, abs_drift_pct)
        classification = self._classify(eff_ratio)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification, mispricing_risk)
        flags = self._flags(
            classification,
            is_overdue,
            is_oracle_priced,
            nav_drift_pct,
            mispricing_risk,
        )

        return {
            "token": token,
            "expected_update_interval_hours": round(expected_interval, 4),
            "hours_since_last_nav_update": round(hours_since, 4),
            "staleness_ratio": (
                None if staleness_ratio is None
                else round(staleness_ratio, 4)),
            "eff_ratio": round(eff_ratio, 4),
            "hours_overdue": round(hours_overdue, 4),
            "is_overdue": is_overdue,
            "nav_drift_pct": round(nav_drift_pct, 4),
            "abs_drift_pct": round(abs_drift_pct, 4),
            "is_oracle_priced": is_oracle_priced,
            "significantly_stale": significantly_stale,
            "mispricing_risk": mispricing_risk,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        eff_ratio: float,
        abs_drift_pct: float,
    ) -> float:
        """
        0–100, HIGHER = fresher. Components:
          freshness (60) — (1 - eff_ratio/STALE_CEILING_RATIO) × 60; full
            credit when freshly repriced, zero at the staleness ceiling.
          drift (40) — (1 - abs_drift/DRIFT_CEILING_PCT) × 40; less unreflected
            value = a more trustworthy reported NAV.
        An oracle-priced vault with no drift → 100.
        """
        fresh_comp = 60.0 * (
            1.0 - _clamp(eff_ratio / STALE_CEILING_RATIO, 0.0, 1.0))
        drift_comp = 40.0 * (
            1.0 - _clamp(abs_drift_pct / DRIFT_CEILING_PCT, 0.0, 1.0))
        total = fresh_comp + drift_comp
        return _clamp(total, 0.0, 100.0)

    def _classify(self, eff_ratio: float) -> str:
        if eff_ratio <= FRESH_RATIO:
            return "FRESH"
        if eff_ratio <= STALE_RATIO:
            return "SLIGHTLY_STALE"
        if eff_ratio <= SEVERE_RATIO:
            return "STALE"
        return "SEVERELY_STALE"

    def _recommend(
        self,
        classification: str,
        mispricing_risk: bool,
    ) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if mispricing_risk and classification != "FRESH":
            return "AVOID_OR_VERIFY"
        if classification == "FRESH":
            return "TRUST_NAV"
        if classification == "SLIGHTLY_STALE":
            return "VERIFY_NAV_BEFORE_TRADING"
        if classification == "STALE":
            return "AWAIT_NAV_UPDATE"
        # SEVERELY_STALE
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        is_overdue: bool,
        is_oracle_priced: bool,
        nav_drift_pct: float,
        mispricing_risk: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "FRESH":
            flags.append("FRESH")
        if classification == "SLIGHTLY_STALE":
            flags.append("SLIGHTLY_STALE")
        if classification == "STALE":
            flags.append("STALE")
        if classification == "SEVERELY_STALE":
            flags.append("SEVERELY_STALE")
        if is_overdue:
            flags.append("OVERDUE")
        if is_oracle_priced:
            flags.append("ORACLE_PRICED")
        else:
            flags.append("SNAPSHOT_PRICED")
        if nav_drift_pct > SIGNIFICANT_DRIFT_PCT:
            flags.append("UNREFLECTED_GAIN")
        if nav_drift_pct < -SIGNIFICANT_DRIFT_PCT:
            flags.append("UNREFLECTED_LOSS")
        if mispricing_risk:
            flags.append("MISPRICING_RISK")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "expected_update_interval_hours": 0.0,
            "hours_since_last_nav_update": 0.0,
            "staleness_ratio": None,
            "eff_ratio": 0.0,
            "hours_overdue": 0.0,
            "is_overdue": False,
            "nav_drift_pct": 0.0,
            "abs_drift_pct": 0.0,
            "is_oracle_priced": False,
            "significantly_stale": False,
            "mispricing_risk": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "freshest_vault": None,
                "stalest_vault": None,
                "avg_score": 0.0,
                "stale_count": 0,
                "position_count": len(results),
            }
        # Higher score = fresher → highest score is freshest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        stale_count = sum(
            1 for r in results
            if r["classification"] in ("STALE", "SEVERELY_STALE"))
        return {
            "freshest_vault": by_score[-1]["token"],
            "stalest_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "stale_count": stale_count,
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
            "vault": "USDC-Vault-OraclePriced",
            "expected_update_interval_hours": 1.0,
            "hours_since_last_nav_update": 0.5,
            "nav_drift_pct": 0.0,
            "is_oracle_priced": True,
        },
        {
            "vault": "ETH-Vault-Fresh",
            "expected_update_interval_hours": 24.0,
            "hours_since_last_nav_update": 18.0,
            "nav_drift_pct": 0.1,
            "is_oracle_priced": False,
        },
        {
            "vault": "ARB-Vault-SlightlyStale",
            "expected_update_interval_hours": 12.0,
            "hours_since_last_nav_update": 20.0,
            "nav_drift_pct": 0.3,
            "is_oracle_priced": False,
        },
        {
            "vault": "OP-Vault-Stale-Overdue",
            "expected_update_interval_hours": 6.0,
            "hours_since_last_nav_update": 21.0,
            "nav_drift_pct": 0.6,
            "is_oracle_priced": False,
        },
        {
            "vault": "GMX-Vault-SeverelyStale-Mispriced",
            "expected_update_interval_hours": 2.0,
            "hours_since_last_nav_update": 12.0,
            "nav_drift_pct": -1.4,
            "is_oracle_priced": False,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "expected_update_interval_hours": 0.0,
            "hours_since_last_nav_update": 0.0,
            "nav_drift_pct": 0.0,
            "is_oracle_priced": False,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1174 Vault Share Price Staleness Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultSharePriceStalenessAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
