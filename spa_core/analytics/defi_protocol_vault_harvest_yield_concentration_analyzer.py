"""
MP-1200: DeFiProtocolVaultHarvestYieldConcentrationAnalyzer
===========================================================
Advisory/read-only analytics module.

A vault's headline trailing APR annualises the SUM of yield it COLLECTED over a
trailing window. But that sum is frequently DOMINATED by a few large, NON-
REPEATABLE harvest events — a one-off airdrop, a single fat bribe epoch, a
liquidation windfall, a retro-active bonus distribution. When the trailing total
is concentrated into a handful of lumpy events, the implied forward RUN-RATE is
overstated: those lumps will not recur at the same cadence, so a depositor who
arrives after them earns far less than the annualised headline implies.

This module looks at the TEMPORAL distribution of the per-harvest yield
contributions over the window and measures how CONCENTRATED (lumpy / windfall-
driven) the trailing yield is, then estimates a deconcentrated, repeatable
run-rate by anchoring on the TYPICAL (median) harvest rather than the windfall-
inflated mean:

    shares_i           = harvest_i / sum(harvest)           (sum to 1)
    hhi                = sum(shares_i^2)            in [1/n, 1]
    effective_harvests = 1 / hhi                            (Herfindahl N_eff)
    realization_ratio  = clamp(median(harvest) * n / sum(harvest), 0, 1)
    recurring_apr_pct   = headline_apr_pct * realization_ratio
    overstatement_pct   = headline_apr_pct - recurring_apr_pct

Angle: "the vault advertises 40% trailing APR, but over the trailing window
~70% of all yield came from a single airdrop harvest; strip that windfall and
the typical-harvest run-rate annualises to only ≈ 12% — discount the headline
toward the recurring run-rate, because that lump is not repeatable at this
cadence."

HIGHER score = yield is spread EVENLY across many recurring harvests (the
typical harvest ≈ the average → the headline is a repeatable run-rate). LOWER
score = the trailing yield is a windfall lump that inflates the annualised
headline above the repeatable run-rate.

Distinct from:
  * defi_protocol_vault_yield_variance_drag_realization_analyzer — that module
    converts the DISPERSION of per-period RETURNS into a geometric-vs-arithmetic
    compounding deficit (a SECOND-MOMENT penalty on a compounding holder). HERE
    we measure CONCENTRATION of the trailing yield SUM into a few events and ask
    whether the annualised headline reflects a REPEATABLE run-rate — a
    repeatability / run-rate-honesty question, not a compounding penalty.
  * defi_protocol_vault_relative_yield_outlier_analyzer — flags a vault whose
    yield is an outlier ACROSS PEERS (a cross-sectional comparison). HERE the
    concentration is WITHIN one vault's own trailing harvest series over TIME.
  * yield_source_concentration_risk / strategy_diversification_scorer — measure
    concentration across yield SOURCES / strategies (which protocols fund the
    yield). HERE the concentration is TEMPORAL: across harvest EVENTS in time.
  * defi_protocol_vault_harvest_cycle_entry_timing_analyzer /
    defi_protocol_vault_pending_harvest_premium_analyzer — those concern the
    TIMING of capturing an accrued harvest (when you enter vs the harvest
    boundary, or overpaying for already-accrued rewards). HERE we audit whether
    the trailing yield is a repeatable stream vs a one-off lump.
  * defi_protocol_vault_price_return_contamination_analyzer — subtracts a PRICE-
    return component from NAV growth (a token-rally contaminating the headline).
    HERE every harvest IS yield; the issue is that its trailing TOTAL is lumpy
    and the lumps are not repeatable.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
import statistics
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data", "vault_harvest_yield_concentration_log.json"
)
LOG_CAP = 100

# Minimum valid harvest samples required to measure concentration.
MIN_SAMPLES = 2

# A harvest above windfall_multiple * typical(harvest) is a "windfall".
WINDFALL_MULTIPLE_DEFAULT = 4.0

# Classification thresholds on the scale-free concentration_index in [0, 1].
DIVERSE_IDX = 0.10       # at/below → diverse / recurring (evenly spread)
MILD_IDX = 0.30          # at/below → mildly lumpy
CONCENTRATED_IDX = 0.60  # at/below → concentrated; above → windfall-dominated

# A single harvest at/above this share of the trailing total dominates the window.
SINGLE_EVENT_SHARE = 0.50
# Coefficient of variation at/above this is "high dispersion".
HIGH_CV = 1.0
# Below this harvest count the series is thin / few harvests.
FEW_HARVESTS_N = 4

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


def _coerce_harvests(raw) -> List[float]:
    """
    Coerce a list of per-harvest yield magnitudes to finite, NON-NEGATIVE floats.
    A harvest yield magnitude cannot be negative, so negative (and non-finite /
    non-numeric) entries are skipped. Order is preserved.
    """
    out: List[float] = []
    if not raw:
        return out
    for v in list(raw):
        cv = _coerce_num(v)
        if cv is None:
            continue
        if cv < 0.0:
            continue
        out.append(cv)
    return out


def _pstdev(values: List[float]) -> float:
    if len(values) < 2:
        return 0.0
    try:
        sd = statistics.pstdev(values)
    except statistics.StatisticsError:
        return 0.0
    return sd if math.isfinite(sd) else 0.0


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    try:
        m = statistics.median(values)
    except statistics.StatisticsError:
        return 0.0
    return m if math.isfinite(m) else 0.0


def _gini(values: List[float]) -> float:
    """
    Gini coefficient of a list of NON-NEGATIVE magnitudes, in [0, 1).
    0 = perfectly even (all harvests equal), → 1 = one harvest holds it all.
    Returns 0.0 for empty / all-zero inputs.
    """
    vals = sorted(v for v in values if v >= 0.0)
    n = len(vals)
    s = sum(vals)
    if n == 0 or s <= 0:
        return 0.0
    cum = 0.0
    for i, v in enumerate(vals, start=1):
        cum += i * v
    g = (2.0 * cum) / (n * s) - (n + 1.0) / n
    if not math.isfinite(g):
        return 0.0
    return _clamp(g, 0.0, 1.0)


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

class DeFiProtocolVaultHarvestYieldConcentrationAnalyzer:
    """
    Measures how CONCENTRATED (lumpy / windfall-driven) a vault's trailing yield
    is across harvest EVENTS, and discounts the annualised headline toward a
    repeatable, deconcentrated run-rate anchored on the TYPICAL (median) harvest.

        shares_i           = harvest_i / sum(harvest)
        hhi                = sum(shares_i^2)
        effective_harvests = 1 / hhi
        realization_ratio  = clamp(median(harvest) * n / sum(harvest), 0, 1)
        recurring_apr_pct   = headline_apr_pct * realization_ratio
        overstatement_pct   = headline_apr_pct - recurring_apr_pct

    A trailing total dominated by a few non-repeatable lumps overstates the
    forward run-rate: the typical harvest is far below the windfall-inflated mean,
    so the annualised headline is not a repeatable rate.

    HIGHER score = yield is spread evenly across many recurring harvests (typical
    ≈ average → headline is a repeatable run-rate). LOWER score = the trailing
    yield is a windfall lump inflating the annualised headline.

    Per-position input dict fields:
        vault / token        : str
        headline_apr_pct     : float — advertised trailing APR, annualised; must be
                               finite and > 0 (else INSUFFICIENT_DATA).
        harvest_yield_samples: list — per-harvest yield magnitudes over the trailing
                               window (USD or APR-contribution units; only the
                               RELATIVE distribution matters), newest last
                               (optional). Negative / non-finite entries are skipped.
        recurring_apr_pct    : float — OPTIONAL direct override of the repeatable
                               run-rate, used when samples are absent / too few.
        windfall_multiple    : float — a harvest above this multiple of the typical
                               harvest is a "windfall" (default 4.0).

    MIN_SAMPLES = 2 valid harvest samples are required to use the sample path.
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
        headline = _f(p.get("headline_apr_pct"), default=float("nan"))

        # Headline must be finite and strictly positive to be meaningful.
        if not math.isfinite(headline) or headline <= 0.0:
            return self._insufficient(token)

        windfall_multiple = _f(
            p.get("windfall_multiple"), default=WINDFALL_MULTIPLE_DEFAULT)
        if not math.isfinite(windfall_multiple) or windfall_multiple <= 0.0:
            windfall_multiple = WINDFALL_MULTIPLE_DEFAULT

        harvests = _coerce_harvests(p.get("harvest_yield_samples"))
        n = len(harvests)
        used_samples = n >= MIN_SAMPLES

        if used_samples:
            total = sum(harvests)
            if total <= 0.0:
                # All harvests zero → degenerate, no recoverable run-rate.
                return self._insufficient(token)

            shares = [h / total for h in harvests]
            hhi = sum(s * s for s in shares)
            effective_harvests = (1.0 / hhi) if hhi > 0 else float(n)
            top_event_share = max(shares)
            top3_event_share = sum(sorted(shares, reverse=True)[:3])

            median_harvest = _median(harvests)
            mean_harvest = _mean(harvests)
            gini = _gini(harvests)

            realization_ratio = _clamp(
                (median_harvest * n) / total, 0.0, 1.0)

            base = median_harvest if median_harvest > 0.0 else mean_harvest
            threshold = windfall_multiple * base
            windfall_count = sum(1 for h in harvests if h > threshold)
            windfall_share = (
                sum(h for h in harvests if h > threshold) / total)

            sd = _pstdev(harvests)
            coefficient_of_variation = (
                round(sd / mean_harvest, 4)
                if mean_harvest > EPS and math.isfinite(sd / mean_harvest)
                else None)

            # Herfindahl-normalised concentration in [0, 1]:
            # 0 = perfectly even, 1 = single event.
            if n >= 2:
                concentration_index = _clamp(
                    (hhi - 1.0 / n) / (1.0 - 1.0 / n), 0.0, 1.0)
            else:
                concentration_index = 0.0

            used_override = False
        else:
            run_override = p.get("recurring_apr_pct")
            if run_override is None:
                return self._insufficient(token)
            rec_o = _f(run_override, default=float("nan"))
            if not math.isfinite(rec_o) or rec_o < 0.0:
                return self._insufficient(token)

            realization_ratio = _clamp(
                _safe_div(rec_o, headline, sentinel=0.0), 0.0, 1.0)
            # Without a harvest series the concentration is inferred from how far
            # the run-rate falls below the headline (1 - realization_ratio).
            concentration_index = _clamp(1.0 - realization_ratio, 0.0, 1.0)

            hhi = None
            effective_harvests = None
            top_event_share = None
            top3_event_share = None
            median_harvest = None
            mean_harvest = None
            gini = None
            windfall_count = None
            windfall_share = None
            coefficient_of_variation = None
            total = None
            used_override = True

        recurring_apr_pct = headline * realization_ratio
        overstatement_pct = headline - recurring_apr_pct

        classification = self._classify(concentration_index)
        score = self._score(realization_ratio, concentration_index)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            top_event_share,
            windfall_count,
            coefficient_of_variation,
            n,
            used_samples,
            used_override,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline, 4),
            "recurring_apr_pct": round(recurring_apr_pct, 4),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "concentration_index": round(concentration_index, 4),
            "hhi": (round(hhi, 4) if hhi is not None else None),
            "effective_harvests": (
                round(effective_harvests, 4)
                if effective_harvests is not None else None),
            "top_event_share": (
                round(top_event_share, 4)
                if top_event_share is not None else None),
            "top3_event_share": (
                round(top3_event_share, 4)
                if top3_event_share is not None else None),
            "gini": (round(gini, 4) if gini is not None else None),
            "windfall_count": windfall_count,
            "windfall_share": (
                round(windfall_share, 4)
                if windfall_share is not None else None),
            "coefficient_of_variation": coefficient_of_variation,
            "harvest_total": (
                round(total, 4) if total is not None else None),
            "median_harvest": (
                round(median_harvest, 4)
                if median_harvest is not None else None),
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
        realization_ratio: float,
        concentration_index: float,
    ) -> float:
        """
        0–100, HIGHER = the trailing yield is evenly spread across recurring
        harvests (the typical harvest ≈ the average → the annualised headline is a
        repeatable run-rate). Two components:
          * realisation = clamp(realization_ratio, 0, 1) — how much of the headline
            survives anchoring on the TYPICAL (median) harvest instead of the
            windfall-inflated mean (1 → median ≈ mean, 0 → all in one lump),
          * evenness = clamp(1 − concentration_index, 0, 1) — the Herfindahl-
            normalised spread of the harvest series (1 → perfectly even, 0 → a
            single event).
        Weighted 70/30 toward realisation (it directly maps to the run-rate a
        depositor keeps); evenness corroborates how lumpy / windfall-prone the
        series is. On the override path (no harvest series) concentration_index is
        derived from 1 − realization_ratio, so the two components agree.
        """
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        evenness = _clamp(1.0 - concentration_index, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * evenness, 0.0, 100.0)

    def _classify(self, concentration_index: float) -> str:
        if concentration_index <= DIVERSE_IDX:
            return "DIVERSE_RECURRING"
        if concentration_index <= MILD_IDX:
            return "MILDLY_LUMPY"
        if concentration_index <= CONCENTRATED_IDX:
            return "CONCENTRATED"
        return "WINDFALL_DOMINATED"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "DIVERSE_RECURRING":
            return "TRUST_HEADLINE"
        if classification == "MILDLY_LUMPY":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "CONCENTRATED":
            return "DISCOUNT_HEADLINE"
        # WINDFALL_DOMINATED
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        top_event_share: Optional[float],
        windfall_count: Optional[int],
        coefficient_of_variation: Optional[float],
        n: int,
        used_samples: bool,
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        flags.append(classification)

        if top_event_share is not None and top_event_share >= SINGLE_EVENT_SHARE:
            flags.append("SINGLE_EVENT_DOMINATED")
        if windfall_count is not None and windfall_count >= 1:
            flags.append("WINDFALL_PRESENT")
        if (coefficient_of_variation is not None
                and coefficient_of_variation >= HIGH_CV):
            flags.append("HIGH_DISPERSION")
        if used_samples and n < FEW_HARVESTS_N:
            flags.append("FEW_HARVESTS")
        if classification == "DIVERSE_RECURRING":
            flags.append("SMOOTH_RECURRING")
        if used_override:
            flags.append("RUN_RATE_FROM_OVERRIDE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": None,
            "recurring_apr_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "concentration_index": None,
            "hhi": None,
            "effective_harvests": None,
            "top_event_share": None,
            "top3_event_share": None,
            "gini": None,
            "windfall_count": None,
            "windfall_share": None,
            "coefficient_of_variation": None,
            "harvest_total": None,
            "median_harvest": None,
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
                "most_recurring_vault": None,
                "most_lumpy_vault": None,
                "avg_score": 0.0,
                "windfall_dominated_count": 0,
                "position_count": len(results),
            }
        # Higher score = more recurring → highest score is most recurring.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        windfall_dominated = sum(
            1 for r in results
            if r["classification"] == "WINDFALL_DOMINATED")
        return {
            "most_recurring_vault": by_score[-1]["token"],
            "most_lumpy_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "windfall_dominated_count": windfall_dominated,
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
            # DIVERSE_RECURRING: yield spread evenly across many harvests; the
            # typical harvest ≈ the average → the headline is a repeatable rate.
            "vault": "USDC-Lending-EvenHarvests",
            "headline_apr_pct": 10.0,
            "harvest_yield_samples": [100, 102, 98, 101, 99, 100, 103, 97],
        },
        {
            # MILDLY_LUMPY: mostly even with one moderately larger harvest.
            "vault": "ETH-Vault-MildLump",
            "headline_apr_pct": 14.0,
            "harvest_yield_samples": [100, 100, 100, 400],
        },
        {
            # WINDFALL_DOMINATED: a single airdrop harvest dwarfs the rest →
            # trailing total is a non-repeatable lump inflating the headline.
            "vault": "GOV-Vault-AirdropWindfall",
            "headline_apr_pct": 40.0,
            "harvest_yield_samples": [50, 45, 55, 48, 1800, 52],
        },
        {
            # Override run-rate: a direct repeatable-rate estimate below headline.
            "vault": "LST-Vault-OverrideRunRate",
            "headline_apr_pct": 20.0,
            "recurring_apr_pct": 6.0,
        },
        {
            # INSUFFICIENT_DATA: positive headline but no harvest series / override.
            "vault": "MYSTERY-Vault-NoData",
            "headline_apr_pct": 18.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1200 Vault Harvest Yield Concentration Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultHarvestYieldConcentrationAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
