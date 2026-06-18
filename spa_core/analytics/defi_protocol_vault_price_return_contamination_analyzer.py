"""
MP-1199: DeFiProtocolVaultPriceReturnContaminationAnalyzer
==========================================================
Advisory/read-only analytics module.

A vault quotes a headline "APY" / trailing return computed from the growth of its
share-price (NAV) over a window. But NAV growth mixes TWO fundamentally different
components:

  (1) RECURRING YIELD   — fees / interest / emissions accrued into the share price.
      This is PERSISTENT and REPEATABLE: it is the productive income stream a holder
      can reasonably expect to keep earning forward.

  (2) PRICE RETURN of the underlying volatile asset — governance token, LST, LP /
      basket constituents whose spot price rose (or fell) over the window. This is a
      ONE-TIME mark-to-market shift that MEAN-REVERTS and is NOT a repeatable income:
      it is a capital gain that happened to land inside the measurement window.

A vault that rode a token rally therefore prints an INFLATED trailing "APY" that
overstates its forward recurring yield. The honest, forward-realisable recurring
yield SUBTRACTS the price-return contamination from the headline:

    recurring_return_i = total_return_i - price_return_i        (per period)
    recurring_yield_apr_pct       = mean(recurring_return_i) * periods_per_year
    price_return_contribution_pct = mean(price_return_i)        * periods_per_year

Angle: "the vault advertises a 22% trailing 'APY', but ~14pp of that is the
underlying token rallying over the window (a one-time price return that mean-reverts
and is NOT repeatable), and the genuine recurring yield is only ≈ 8% — discount the
headline toward the recurring component for any forward expectation."

HIGHER score = the headline is almost entirely recurring yield (low price-return
contamination) → forward-realisable. LOWER score = the headline is mostly one-time
appreciation of the underlying token → the trailing "APY" overstates the recurring
yield a holder will actually keep earning.

Distinct from:
  * defi_protocol_vault_reward_token_price_exposure_analyzer — measures FORWARD
    price-RISK of reward tokens (how exposed future yield is to a token's price). HERE
    we DECOMPOSE an ALREADY-REALISED trailing return into recurring vs price-return
    components — a backward-looking honesty audit of the headline, not a forward risk.
  * defi_protocol_vault_headline_spot_snapshot_vs_twap_analyzer — representativeness of
    the rate LEVEL (spot snapshot vs TWAP, a FIRST-MOMENT question: is the quoted rate
    a spike?). HERE we separate NON-REPEATABLE capital gain from REPEATABLE yield — the
    quoted rate may be a perfectly representative trailing average yet still be inflated
    by price appreciation baked into NAV growth.
  * defi_protocol_vault_yield_variance_drag_realization_analyzer — geometric < arithmetic
    realisation deficit arising from the DISPERSION of a (positive) yield series (a
    SECOND-MOMENT effect). HERE we subtract a PRICE component from the FIRST moment of
    the return; it is not a variance penalty.
  * defi_protocol_vault_share_price_premium_analyzer — the premium of the share PRICE
    over NAV (you pay above fair value to enter). HERE we audit the COMPOSITION of NAV
    GROWTH itself (how much of the realised gain is recurring yield vs token price move).

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
import statistics
from datetime import datetime, timezone
from typing import List, Optional, Tuple

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_price_return_contamination_log.json"
)
LOG_CAP = 100

# Minimum total/price sample PAIRS required to decompose the return.
MIN_SAMPLES = 2

# Default annualisation factor (per-period samples per year).
DEFAULT_PERIODS_PER_YEAR = 365.0

# Classification thresholds on contamination_fraction (price share of |headline|).
PURE_YIELD_FRAC = 0.05       # at/below → headline is essentially all recurring yield
LIGHT_CONTAM_FRAC = 0.20     # at/below → lightly contaminated
MODERATE_CONTAM_FRAC = 0.50  # at/below → moderately contaminated; above → price-driven

# A positive price contribution at/above this contamination fraction is "rally-inflated".
RALLY_INFLATED_FRAC = 0.20
# Above this contamination fraction the headline is mostly appreciation.
APPRECIATION_FRAC = 0.50
# Price-return volatility at/above this (pct) is "notable" for mean-reversion exposure.
NOTABLE_PRICE_VOL = 1e-9     # any non-trivial positive price vol counts

# Small epsilon to keep normalisers finite.
EPS = 1e-12


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


def _coerce_num(val) -> Optional[float]:
    """
    Coerce a single sample to a finite float, or None if it is not interpretable
    (skipped). Accepts int/float/numeric-string; rejects bool, None, NaN, inf,
    and non-numeric values.
    """
    if isinstance(val, bool):
        return None
    if isinstance(val, (int, float)):
        try:
            fv = float(val)
        except (TypeError, ValueError):
            return None
        return fv if math.isfinite(fv) else None
    if isinstance(val, str):
        s = val.strip()
        if not s:
            return None
        try:
            fv = float(s)
        except (TypeError, ValueError):
            return None
        return fv if math.isfinite(fv) else None
    return None


def _pair_samples(total_raw, price_raw) -> Tuple[List[float], List[float]]:
    """
    Pair-wise coerce (total[i], price[i]); skip a pair if EITHER element is not a
    finite number. Returns (totals, prices) of equal length, order preserved.
    """
    totals: List[float] = []
    prices: List[float] = []
    total_list = list(total_raw) if total_raw else []
    price_list = list(price_raw) if price_raw else []
    for tv, pv in zip(total_list, price_list):
        ct = _coerce_num(tv)
        cp = _coerce_num(pv)
        if ct is None or cp is None:
            continue
        totals.append(ct)
        prices.append(cp)
    return totals, prices


def _pstdev(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    try:
        sd = statistics.pstdev(values)
    except statistics.StatisticsError:
        return 0.0
    return sd if math.isfinite(sd) else 0.0


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

class DeFiProtocolVaultPriceReturnContaminationAnalyzer:
    """
    Decomposes a vault's trailing headline "APY" (computed from share-price / NAV
    growth) into a RECURRING YIELD component (fees / interest / emissions —
    persistent and repeatable) and a PRICE-RETURN component (a one-time, mean-
    reverting mark-to-market move of the underlying volatile token, NOT repeatable):

        recurring_return_i = total_return_i - price_return_i
        recurring_yield_apr_pct       = mean(recurring_return_i) * periods_per_year
        price_return_contribution_pct = mean(price_return_i)     * periods_per_year

    A vault that rode a token rally prints an inflated trailing headline that
    overstates its forward recurring yield. The honest forward-realisable yield is
    the recurring component, with the price return subtracted out.

    HIGHER score = headline is almost all recurring yield (low contamination) →
    forward-realisable. LOWER score = headline is mostly one-time token appreciation
    → the trailing "APY" overstates the repeatable recurring yield.

    Per-position input dict fields:
        vault / token        : str
        headline_apr_pct     : float — advertised trailing "APY" / return, annualised;
                               must be finite (a non-finite headline → INSUFFICIENT_DATA;
                               headline == 0 with no decomposable data → INSUFFICIENT_DATA).
                               May be negative in principle.
        total_return_samples : list — per-period TOTAL % returns (the NAV growth path),
                               newest last (optional).
        price_return_samples : list — per-period % price-return of the underlying token
                               over the same periods (the contaminating component).
        recurring_yield_apr_pct       : float — OPTIONAL direct override of the recurring
                               component, used when samples are absent / too few.
        price_return_contribution_pct : float — OPTIONAL direct override of the price
                               component, used when samples are absent / too few.
        periods_per_year     : float — annualisation factor (default 365).

    Non-finite / non-numeric samples are filtered PAIR-WISE (a pair is skipped if
    either element is uninterpretable); MIN_SAMPLES = 2 valid pairs are required to
    use the sample path.
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
        headline = _f(headline_raw, default=float("nan"))

        # Headline must be finite to be meaningful.
        if not math.isfinite(headline):
            return self._insufficient(token)

        ppy = _f(p.get("periods_per_year"), default=DEFAULT_PERIODS_PER_YEAR)
        if not math.isfinite(ppy) or ppy <= 0:
            ppy = DEFAULT_PERIODS_PER_YEAR

        totals, prices = _pair_samples(
            p.get("total_return_samples"), p.get("price_return_samples"))
        n = len(totals)
        used_samples = n >= MIN_SAMPLES

        if used_samples:
            recurring_returns = [t - pr for t, pr in zip(totals, prices)]
            recurring_yield_apr_pct = _mean(recurring_returns) * ppy
            price_return_contribution_pct = _mean(prices) * ppy
            total_window_apr_pct = _mean(totals) * ppy
            price_return_volatility_pct = _pstdev(prices)
            recurring_yield_volatility_pct = _pstdev(recurring_returns)
            used_override = False
        else:
            rec_override = p.get("recurring_yield_apr_pct")
            price_override = p.get("price_return_contribution_pct")
            if rec_override is None and price_override is None:
                return self._insufficient(token)
            rec_o = _f(rec_override, default=float("nan"))
            price_o = _f(price_override, default=float("nan"))
            # If both overrides given they must be finite; if only one given the
            # other defaults to a derived/zero value but must still be finite.
            if rec_override is not None and not math.isfinite(rec_o):
                return self._insufficient(token)
            if price_override is not None and not math.isfinite(price_o):
                return self._insufficient(token)
            if rec_override is None:
                # Only price override → recurring = headline - price.
                rec_o = headline - price_o
            if price_override is None:
                # Only recurring override → price = headline - recurring.
                price_o = headline - rec_o
            if not math.isfinite(rec_o) or not math.isfinite(price_o):
                return self._insufficient(token)
            recurring_yield_apr_pct = rec_o
            price_return_contribution_pct = price_o
            total_window_apr_pct = rec_o + price_o
            price_return_volatility_pct = None
            recurring_yield_volatility_pct = None
            used_override = True

        # If headline is exactly 0 and there is genuinely no decomposable signal,
        # treat as insufficient (already covered by the override/sample gates above;
        # this guards the degenerate all-zero case).
        if (headline == 0.0
                and recurring_yield_apr_pct == 0.0
                and price_return_contribution_pct == 0.0):
            return self._insufficient(token)

        overstatement_pct = headline - recurring_yield_apr_pct
        realization_ratio = _safe_div(
            recurring_yield_apr_pct, headline, sentinel=None)
        if realization_ratio is not None:
            realization_ratio = _clamp(realization_ratio, -10.0, 10.0)

        # Scale-free contamination fraction in [0, 1]: price share of the magnitude.
        abs_rec = abs(recurring_yield_apr_pct)
        abs_price = abs(price_return_contribution_pct)
        denom = abs_rec + abs_price
        if denom > EPS:
            contamination_fraction = _clamp(abs_price / denom, 0.0, 1.0)
        else:
            contamination_fraction = 0.0

        # Coefficient of variation of the price component (optional, may be None).
        if (price_return_volatility_pct is not None
                and abs(_mean(prices) if used_samples else 0.0) > EPS):
            cov = price_return_volatility_pct / abs(_mean(prices))
            coefficient_of_variation = (
                round(cov, 4) if math.isfinite(cov) else None)
        else:
            coefficient_of_variation = None

        classification = self._classify(contamination_fraction)
        score = self._score(
            contamination_fraction,
            recurring_yield_apr_pct,
            price_return_volatility_pct,
            ppy,
            used_override,
        )
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            contamination_fraction,
            price_return_contribution_pct,
            recurring_yield_apr_pct,
            price_return_volatility_pct,
            used_override,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "recurring_yield_apr_pct": round(recurring_yield_apr_pct, 4),
            "price_return_contribution_pct": round(
                price_return_contribution_pct, 4),
            "total_window_apr_pct": round(total_window_apr_pct, 4),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": (
                round(realization_ratio, 4)
                if realization_ratio is not None else None),
            "contamination_fraction": round(contamination_fraction, 4),
            "price_return_volatility_pct": (
                round(price_return_volatility_pct, 4)
                if price_return_volatility_pct is not None else None),
            "recurring_yield_volatility_pct": (
                round(recurring_yield_volatility_pct, 4)
                if recurring_yield_volatility_pct is not None else None),
            "coefficient_of_variation": coefficient_of_variation,
            "periods_per_year": round(ppy, 4),
            "sample_count": n,
            "used_samples": used_samples,
            "used_override": used_override,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags_out,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        contamination_fraction: float,
        recurring_yield_apr_pct: float,
        price_return_volatility_pct: Optional[float],
        ppy: float,
        used_override: bool,
    ) -> float:
        """
        0–100, HIGHER = LESS price-return contamination (the headline is almost
        entirely recurring yield → forward-realisable). Two components:
          * purity = clamp(1 − contamination_fraction, 0, 1) — the recurring share of
            the decomposed magnitude (1 → all recurring, 0 → all price),
          * stability = clamp(1 − normalised_price_vol, 0, 1), where
                normalised_price_vol = price_vol / (|recurring_per_period| + price_vol)
            penalises a volatile (mean-reversion-prone) price component (a one-time
            gain that swings is more likely to reverse).
        Weighted 70/30 toward purity (the contamination share is the dominant signal;
        price volatility is a corroborating mean-reversion view). When the
        decomposition comes from a direct override (no price-volatility samples)
        stability is unknown → it contributes its neutral FULL weight.
        """
        purity = _clamp(1.0 - contamination_fraction, 0.0, 1.0)
        if used_override or price_return_volatility_pct is None:
            stability = 1.0
        else:
            recurring_per_period = abs(recurring_yield_apr_pct) / ppy
            denom = recurring_per_period + price_return_volatility_pct + EPS
            normalised_price_vol = _clamp(
                price_return_volatility_pct / denom, 0.0, 1.0)
            stability = _clamp(1.0 - normalised_price_vol, 0.0, 1.0)
        return _clamp(70.0 * purity + 30.0 * stability, 0.0, 100.0)

    def _classify(self, contamination_fraction: float) -> str:
        if contamination_fraction <= PURE_YIELD_FRAC:
            return "PURE_YIELD"
        if contamination_fraction <= LIGHT_CONTAM_FRAC:
            return "LIGHTLY_CONTAMINATED"
        if contamination_fraction <= MODERATE_CONTAM_FRAC:
            return "MODERATELY_CONTAMINATED"
        return "PRICE_DRIVEN"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "PURE_YIELD":
            return "TRUST_HEADLINE"
        if classification == "LIGHTLY_CONTAMINATED":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "MODERATELY_CONTAMINATED":
            return "DISCOUNT_HEADLINE"
        # PRICE_DRIVEN
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        contamination_fraction: float,
        price_return_contribution_pct: float,
        recurring_yield_apr_pct: float,
        price_return_volatility_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        if classification == "PURE_YIELD":
            flags.append("PURE_YIELD")
        if classification == "LIGHTLY_CONTAMINATED":
            flags.append("LIGHTLY_CONTAMINATED")
        if classification == "MODERATELY_CONTAMINATED":
            flags.append("MODERATELY_CONTAMINATED")
        if classification == "PRICE_DRIVEN":
            flags.append("PRICE_DRIVEN")

        if (price_return_contribution_pct > 0.0
                and contamination_fraction >= RALLY_INFLATED_FRAC):
            flags.append("PRICE_RALLY_INFLATED")
        if recurring_yield_apr_pct < 0.0:
            flags.append("RECURRING_YIELD_NEGATIVE")
        if (price_return_contribution_pct > 0.0
                and price_return_volatility_pct is not None
                and price_return_volatility_pct > NOTABLE_PRICE_VOL):
            flags.append("MEAN_REVERSION_EXPOSED")
        if contamination_fraction > APPRECIATION_FRAC:
            flags.append("HEADLINE_FROM_APPRECIATION")
        if classification == "PURE_YIELD":
            flags.append("GENUINE_YIELD")
        if used_override:
            flags.append("CONTRIBUTION_FROM_OVERRIDE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": None,
            "recurring_yield_apr_pct": None,
            "price_return_contribution_pct": None,
            "total_window_apr_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "contamination_fraction": None,
            "price_return_volatility_pct": None,
            "recurring_yield_volatility_pct": None,
            "coefficient_of_variation": None,
            "periods_per_year": None,
            "sample_count": 0,
            "used_samples": False,
            "used_override": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_OR_VERIFY",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "most_honest_vault": None,
                "least_honest_vault": None,
                "avg_score": 0.0,
                "price_driven_count": 0,
                "position_count": len(results),
            }
        # Higher score = less contamination → highest score is most honest.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        price_driven = sum(
            1 for r in results
            if r["classification"] == "PRICE_DRIVEN")
        return {
            "most_honest_vault": by_score[-1]["token"],
            "least_honest_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "price_driven_count": price_driven,
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
            # PURE_YIELD: NAV growth is essentially all recurring yield; the token
            # barely moved over the window → headline ≈ recurring.
            "vault": "USDC-Lending-PureYield",
            "headline_apr_pct": 8.0,
            "total_return_samples": [0.022, 0.021, 0.022, 0.023, 0.021, 0.022],
            "price_return_samples": [0.0, 0.001, -0.001, 0.0, 0.0005, -0.0005],
            "periods_per_year": 365.0,
        },
        {
            # LIGHTLY_CONTAMINATED: most of the gain is yield, a small slice is a
            # mild token drift.
            "vault": "stETH-Vault-LightDrift",
            "headline_apr_pct": 10.0,
            "total_return_samples": [0.030, 0.028, 0.031, 0.029, 0.030, 0.032],
            "price_return_samples": [0.004, 0.003, 0.005, 0.004, 0.003, 0.005],
            "periods_per_year": 365.0,
        },
        {
            # MODERATELY_CONTAMINATED: a meaningful chunk of the headline is the
            # underlying token rallying.
            "vault": "GOV-Token-Vault-Rally",
            "headline_apr_pct": 22.0,
            "total_return_samples": [0.060, 0.058, 0.062, 0.059, 0.061, 0.060],
            "price_return_samples": [0.038, 0.036, 0.040, 0.037, 0.039, 0.040],
            "periods_per_year": 365.0,
        },
        {
            # PRICE_DRIVEN via direct overrides: the headline is mostly a one-time
            # token appreciation, recurring yield is small.
            "vault": "LST-Vault-OverridePriceDriven",
            "headline_apr_pct": 30.0,
            "recurring_yield_apr_pct": 6.0,
            "price_return_contribution_pct": 24.0,
        },
        {
            # INSUFFICIENT_DATA: finite headline but no samples and no overrides.
            "vault": "MYSTERY-Vault-NoData",
            "headline_apr_pct": 18.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1199 Vault Price Return Contamination Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultPriceReturnContaminationAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
