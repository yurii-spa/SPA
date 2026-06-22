"""
MP-1187: DeFiProtocolVaultDenominationCurrencyYieldBasisAnalyzer
================================================================
Advisory/read-only analytics module.

A vault's headline APR is quoted in the vault's DENOMINATION token (an ETH
vault yields an APR measured "in ETH", a stETH vault "in stETH", etc.). A
holder who measures wealth in a numeraire (typically USD) will realise a
DIFFERENT effective yield once the denomination token's price drifts:

    numeraire_effective_apr ≈ token_apr + annualized_price_drift

The more volatile the denomination token and the larger the plausible drift
over the horizon, the LESS the token-denominated headline reflects the real
(numeraire) outcome. This measures the denomination/currency BASIS of the
headline: the denomination token, the token-APR, the expected and worst-case
annualized price drift, the numeraire-effective APR band, the basis-gap, and a
trust-score.

Angle: "headline 5% APR is quoted in ETH; ETH could plausibly drift ±60%/yr →
your USD outcome ranges from roughly -55% to +65%; the 5% headline barely
describes your numeraire result." Conversely a USDC/stablecoin vault has
drift≈0 → the headline is an honest numeraire quote → high score.

HIGHER score = the headline closely tracks the numeraire outcome (stable
denomination, e.g. a stablecoin vault → drift≈0 → high score).

Distinct from:
  * defi_protocol_vault_reward_token_price_exposure_analyzer — that module is
    about the price risk of the REWARD token paid INSIDE the rewards stream;
    THIS module is about the price / denomination basis of the PRINCIPAL token
    in which the headline yield itself is quoted.

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
    "data", "vault_denomination_currency_yield_basis_log.json"
)
LOG_CAP = 100

# Default holding horizon (days) when none / non-positive supplied.
DEFAULT_HOLDING_HORIZON_DAYS = 30.0

# Days in a year for annualization.
DAYS_PER_YEAR = 365.0

# Worst-case drift is modelled as a one-sigma adverse move over the horizon,
# annualized back. This is the number of sigmas used for the worst case.
WORST_CASE_SIGMA = 1.0

# Basis-gap (pp of horizon-scaled adverse swing) classification thresholds.
# horizon_basis_gap_pct at/below this → TIGHT_BASIS.
TIGHT_BASIS_PCT = 1.0
# at/below this → MILD_BASIS.
MILD_BASIS_PCT = 5.0
# at/below this → WIDE_BASIS.
WIDE_BASIS_PCT = 15.0
# at/below this → LOOSE_BASIS; above → DECOUPLED_BASIS.
LOOSE_BASIS_PCT = 35.0

# Reference horizon-basis-gap (pp) at which the score reaches 0.
BASIS_GAP_CEILING_PCT = 50.0

# Flag: denomination token is volatile.
HIGH_VOL_PCT = 40.0
# Flag: expected drift materially shifts the headline (abs pp over horizon).
MATERIAL_DRIFT_PCT = 3.0


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

class DeFiProtocolVaultDenominationCurrencyYieldBasisAnalyzer:
    """
    Measures how faithfully a vault's token-denominated headline APR describes
    the holder's numeraire (USD) outcome. The token-APR is the yield "in the
    denomination token"; the numeraire-effective APR adds the annualized price
    drift of that token. The horizon basis-gap is the magnitude of the adverse
    price swing scaled to the holding horizon: the larger it is, the less the
    headline can be trusted as a numeraire quote. A stablecoin denomination
    (drift≈0, vol≈0) yields a near-zero basis-gap → high trust. Advisory only —
    it does not move funds.

    Per-position input dict fields:
        vault / token             : str
        headline_apr_pct          : float (token-APR); non-finite →
                                    INSUFFICIENT_DATA.
        denomination_token        : str — the token the APR is quoted in.
        expected_annual_drift_pct : float (may be negative; default 0.0) —
                                    expected annualized price drift of the
                                    denomination token vs numeraire.
        drift_volatility_pct      : float (max(0,..); default 0.0) — annualized
                                    volatility of the denomination token.
        holding_horizon_days      : float (max(0,..); default 30.0); <=0 →
                                    default.
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
        headline_raw = p.get("headline_apr_pct")
        headline = _f(headline_raw)

        # Insufficient data fast-path: a missing / non-finite headline gives
        # nothing to measure basis against.
        if headline_raw is None or not math.isfinite(headline):
            return self._insufficient(token)

        denom = p.get("denomination_token", "UNKNOWN")
        if not isinstance(denom, str) or not denom:
            denom = "UNKNOWN"

        expected_drift = _f(p.get("expected_annual_drift_pct"), 0.0)
        if not math.isfinite(expected_drift):
            expected_drift = 0.0

        vol = max(0.0, _f(p.get("drift_volatility_pct"), 0.0))
        if not math.isfinite(vol):
            vol = 0.0

        horizon = max(0.0, _f(p.get("holding_horizon_days"),
                              DEFAULT_HOLDING_HORIZON_DAYS))
        if horizon <= 0 or not math.isfinite(horizon):
            horizon = DEFAULT_HOLDING_HORIZON_DAYS

        horizon_years = _clamp(
            _safe_div(horizon, DAYS_PER_YEAR, 0.0), 0.0, 1.0)
        if not math.isfinite(horizon_years):
            horizon_years = 0.0
        # sqrt-time scaling for the volatility swing over the horizon.
        time_sqrt = math.sqrt(horizon_years) if horizon_years > 0 else 0.0

        # numeraire-effective APR (annualized) = token APR + expected drift.
        numeraire_apr = headline + expected_drift
        if not math.isfinite(numeraire_apr):
            numeraire_apr = headline

        # One-sigma adverse annualized swing → numeraire band (annualized).
        swing_annual = WORST_CASE_SIGMA * vol
        numeraire_apr_low = numeraire_apr - swing_annual
        numeraire_apr_high = numeraire_apr + swing_annual
        if not math.isfinite(numeraire_apr_low):
            numeraire_apr_low = numeraire_apr
        if not math.isfinite(numeraire_apr_high):
            numeraire_apr_high = numeraire_apr

        # Horizon-scaled adverse swing (the part that actually accrues over the
        # holding period) — this is the basis-gap magnitude in pp.
        horizon_swing = swing_annual * time_sqrt
        horizon_expected_drift = expected_drift * horizon_years
        # basis-gap = how far the numeraire outcome can drift from the headline
        # over the horizon: adverse-swing plus the magnitude of expected drift.
        horizon_basis_gap = abs(horizon_swing) + abs(horizon_expected_drift)
        if not math.isfinite(horizon_basis_gap):
            horizon_basis_gap = 0.0
        horizon_basis_gap = max(0.0, horizon_basis_gap)

        high_vol = bool(vol >= HIGH_VOL_PCT)
        material_drift = bool(abs(horizon_expected_drift) >= MATERIAL_DRIFT_PCT)
        adverse_drift = bool(expected_drift < 0.0)

        score = self._score(horizon_basis_gap)
        classification = self._classify(horizon_basis_gap)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags = self._flags(
            classification, high_vol, material_drift, adverse_drift)

        return {
            "token": token,
            "denomination_token": denom,
            "headline_apr_pct": round(headline, 4),
            "expected_annual_drift_pct": round(expected_drift, 4),
            "drift_volatility_pct": round(vol, 4),
            "holding_horizon_days": round(horizon, 4),
            "numeraire_apr_pct": round(numeraire_apr, 4),
            "numeraire_apr_low_pct": round(numeraire_apr_low, 4),
            "numeraire_apr_high_pct": round(numeraire_apr_high, 4),
            "horizon_expected_drift_pct": round(horizon_expected_drift, 4),
            "horizon_swing_pct": round(horizon_swing, 4),
            "horizon_basis_gap_pct": round(horizon_basis_gap, 4),
            "high_volatility": high_vol,
            "material_drift": material_drift,
            "adverse_drift": adverse_drift,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(self, horizon_basis_gap: float) -> float:
        """
        0–100, HIGHER = the headline tracks the numeraire outcome (tight basis).
          trust (100) — 100 × (1 - clamp(horizon_basis_gap /
            BASIS_GAP_CEILING_PCT, 0, 1)). A zero basis-gap (a stablecoin
            denomination) scores 100; a basis-gap at/above the ceiling scores 0.
        """
        gap = max(0.0, horizon_basis_gap)
        frac = _clamp(gap / BASIS_GAP_CEILING_PCT, 0.0, 1.0)
        total = 100.0 * (1.0 - frac)
        return _clamp(total, 0.0, 100.0)

    def _classify(self, horizon_basis_gap: float) -> str:
        gap = max(0.0, horizon_basis_gap)
        if gap <= TIGHT_BASIS_PCT:
            return "TIGHT_BASIS"
        if gap <= MILD_BASIS_PCT:
            return "MILD_BASIS"
        if gap <= WIDE_BASIS_PCT:
            return "WIDE_BASIS"
        if gap <= LOOSE_BASIS_PCT:
            return "LOOSE_BASIS"
        return "DECOUPLED_BASIS"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "VERIFY_DATA"
        if classification == "TIGHT_BASIS":
            return "NO_ACTION"
        if classification == "MILD_BASIS":
            return "MONITOR"
        if classification == "WIDE_BASIS":
            return "ADJUST_FOR_DRIFT"
        if classification == "LOOSE_BASIS":
            return "HEDGE_DENOMINATION"
        # DECOUPLED_BASIS
        return "TREAT_AS_DIRECTIONAL"

    def _flags(
        self,
        classification: str,
        high_vol: bool,
        material_drift: bool,
        adverse_drift: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "TIGHT_BASIS":
            flags.append("TIGHT_BASIS")
        if classification == "MILD_BASIS":
            flags.append("MILD_BASIS")
        if classification == "WIDE_BASIS":
            flags.append("WIDE_BASIS")
        if classification == "LOOSE_BASIS":
            flags.append("LOOSE_BASIS")
        if classification == "DECOUPLED_BASIS":
            flags.append("DECOUPLED_BASIS")
        if high_vol:
            flags.append("HIGH_DENOMINATION_VOLATILITY")
        if material_drift:
            flags.append("MATERIAL_EXPECTED_DRIFT")
        if adverse_drift:
            flags.append("ADVERSE_EXPECTED_DRIFT")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "denomination_token": "UNKNOWN",
            "headline_apr_pct": 0.0,
            "expected_annual_drift_pct": 0.0,
            "drift_volatility_pct": 0.0,
            "holding_horizon_days": round(DEFAULT_HOLDING_HORIZON_DAYS, 4),
            "numeraire_apr_pct": None,
            "numeraire_apr_low_pct": None,
            "numeraire_apr_high_pct": None,
            "horizon_expected_drift_pct": None,
            "horizon_swing_pct": None,
            "horizon_basis_gap_pct": None,
            "high_volatility": False,
            "material_drift": False,
            "adverse_drift": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "VERIFY_DATA",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [r for r in results
                  if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "tightest_basis_vault": None,
                "loosest_basis_vault": None,
                "avg_score": 0.0,
                "decoupled_count": 0,
                "avg_basis_gap_pct": 0.0,
                "position_count": len(results),
            }
        # Higher score = tighter basis → highest score is the tightest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        decoupled = sum(
            1 for r in results
            if r["classification"] == "DECOUPLED_BASIS")
        avg_gap = _mean([
            r["horizon_basis_gap_pct"] for r in scored
            if isinstance(r["horizon_basis_gap_pct"], (int, float))])
        return {
            "tightest_basis_vault": by_score[-1]["token"],
            "loosest_basis_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "decoupled_count": decoupled,
            "avg_basis_gap_pct": round(avg_gap, 4),
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
            "vault": "USDC-Vault-Tight",
            "headline_apr_pct": 6.0,
            "denomination_token": "USDC",
            "expected_annual_drift_pct": 0.0,
            "drift_volatility_pct": 0.5,
            "holding_horizon_days": 30.0,
        },
        {
            "vault": "stETH-Vault-Mild",
            "headline_apr_pct": 4.0,
            "denomination_token": "stETH",
            "expected_annual_drift_pct": 2.0,
            "drift_volatility_pct": 15.0,
            "holding_horizon_days": 30.0,
        },
        {
            "vault": "ETH-Vault-Wide",
            "headline_apr_pct": 5.0,
            "denomination_token": "ETH",
            "expected_annual_drift_pct": -5.0,
            "drift_volatility_pct": 40.0,
            "holding_horizon_days": 30.0,
        },
        {
            "vault": "wBTC-Vault-Loose",
            "headline_apr_pct": 3.0,
            "denomination_token": "wBTC",
            "expected_annual_drift_pct": -8.0,
            "drift_volatility_pct": 45.0,
            "holding_horizon_days": 90.0,
        },
        {
            "vault": "ALT-Vault-Decoupled",
            "headline_apr_pct": 8.0,
            "denomination_token": "ALT",
            "expected_annual_drift_pct": -30.0,
            "drift_volatility_pct": 130.0,
            "holding_horizon_days": 365.0,
        },
        {
            "vault": "Mystery-Vault-NoData",
            "headline_apr_pct": None,
            "denomination_token": "???",
            "expected_annual_drift_pct": 0.0,
            "drift_volatility_pct": 0.0,
            "holding_horizon_days": 30.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1187 Vault Denomination Currency Yield Basis Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultDenominationCurrencyYieldBasisAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
