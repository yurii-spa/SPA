"""
MP-1205: DeFiProtocolVaultEntryExitFeeAmortizationAnalyzer
==========================================================
Advisory/read-only analytics module.

A vault quotes a headline RUNNING APR — the annualised yield from emissions,
trading fees and interest — that EXCLUDES the one-off ENTRY (deposit) and EXIT
(withdrawal) fees the LP pays to get in and out of the vault. Those round-trip
fees are paid ONCE, but the running APR they are netted against accrues over the
LP's ACTUAL HOLDING HORIZON. Amortised over that horizon, the one-off round-trip
fee becomes an ANNUALISED DRAG on the realised APR — and the SHORTER the holding
period, the LARGER that annualised drag:

    amortized_fee_drag_apr_pct = round_trip_fee_pct * (365 / holding_days)

A 0.50% round-trip fee held 30 days amortises to ~6.08% APR of drag; held one
year it is 0.50%; held two years it is ~0.25%. So the headline running APR
OVERSTATES the holding-period-adjusted realised APR, and it overstates it MOST for
short-term holders. This module amortises the one-off round-trip fee over the
holding horizon and nets it out:

    round_trip_fee_pct        = round_trip override (if valid) else entry + exit
    amortized_fee_drag_apr_pct = round_trip_fee_pct * (365 / holding_days)
    net_realized_apr_pct      = headline_apr_pct - amortized_fee_drag_apr_pct
    overstatement_pct         = headline_apr_pct - net_realized_apr_pct
                              = amortized_fee_drag_apr_pct
    realization_ratio         = clamp(net_realized / headline, 0, 1)   (headline > 0)
    fee_drag_fraction         = clamp(amortized_fee_drag / headline, 0, 1)
    breakeven_days            = round_trip_fee_pct / headline_apr_pct * 365

The headline says "12% running APR", but the LP pays a 0.50% round-trip fee and
holds only 30 days → the amortised fee drag is ~6.08% APR, the net-of-fee realised
APR is ~5.92%, and the headline overstates by half. Discount the headline toward
the holding-period-adjusted realised APR, especially for short holds.

When the holding period is long and/or the round-trip fee is tiny the amortised
drag vanishes → net ≈ headline → realisation is near perfect (HIGHER score). When
the holding period is short and/or the round-trip fee is large the amortised drag
rivals or exceeds the headline → net collapses toward or below zero (LOWER score).

HIGHER score = the amortised fee drag is negligible relative to the headline (long
hold and/or low fees → realised ≈ headline; the LP keeps the brochure APR). LOWER
score = a large amortised fee drag (short hold and/or high round-trip fee →
realised far below the headline, or net-negative).

Override path (when amortized_fee_drag_apr_pct is supplied directly, finite >= 0,
AND a valid POSITIVE headline_apr_pct is present): take the drag directly and skip
the holding/round-trip geometry — net it out the same way:

    net_realized_apr_pct = headline_apr_pct - amortized_fee_drag_apr_pct
    overstatement_pct    = headline_apr_pct - net_realized_apr_pct

(On the override path the round-trip fee and holding geometry are not known →
round_trip_fee_pct / breakeven_days / holding_days are reported as None.)

Distinct from:
  * defi_protocol_vault_net_of_loss_yield_realization_analyzer — that nets a
    RECURRING realised LOSS stream (IL / slashing / bad debt) against the positive
    yield. HERE it is a ONE-OFF round-trip FEE amortised over the holding horizon —
    a fee-honesty gap, not a loss-honesty gap, and it depends on the HOLDING PERIOD
    (the same fee is a bigger drag for shorter holds).
  * defi_protocol_vault_performance_fee_volatility_tax_analyzer — that prices the
    asymmetric drag of a high-water-mark PERFORMANCE fee on the running yield. HERE
    it is the FIXED deposit/withdrawal fee, paid once, amortised over the hold.
  * defi_protocol_real_yield_vs_incentive_yield_analyzer — that SPLITS a positive
    yield into real-fee vs incentive components (both positive). HERE we SUBTRACT a
    one-off cost amortised over time.

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
    "data", "vault_entry_exit_fee_amortization_log.json"
)
LOG_CAP = 100

# Default holding horizon (days) when none supplied / invalid on the holding path.
DEFAULT_HOLDING_DAYS = 365.0

# Days per year for annualising the one-off round-trip fee.
DAYS_PER_YEAR = 365.0

# Classification thresholds on the scale-free fee_drag_fraction in [0, 1]
# (= amortized_fee_drag_apr_pct / headline_apr_pct).
CLEAN_FRACTION = 0.05        # at/below → clean low fee (realised ≈ headline)
MILD_FRACTION = 0.20         # at/below → mild fee drag
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe fee drag

# Flag thresholds (holding path only).
SHORT_HOLD_DAYS = 60.0           # holding_days below → SHORT_HOLD_PENALTY
HIGH_ROUND_TRIP_FEE_PCT = 1.0    # round_trip_fee at/above → HIGH_ROUND_TRIP_FEE

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
    Coerce a single value to a finite float, or None if it is not interpretable.
    Accepts int/float/numeric-string; rejects bool, None, NaN, inf, and
    non-numeric values.
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


def _coerce_fee(val) -> float:
    """
    Coerce a one-off fee % to a finite NON-NEGATIVE magnitude. A signed negative
    fee is taken as its magnitude; non-finite / non-numeric / bool / None → 0.0.
    """
    cv = _coerce_num(val)
    if cv is None or not math.isfinite(cv):
        return 0.0
    return abs(cv)


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

class DeFiProtocolVaultEntryExitFeeAmortizationAnalyzer:
    """
    Amortises a vault's one-off ENTRY + EXIT (round-trip) fee over the LP's actual
    holding horizon and nets it out of the headline RUNNING APR to recover the
    holding-period-adjusted realised APR and the headline overstatement.

        round_trip_fee_pct         = round_trip override (if valid) else entry + exit
        amortized_fee_drag_apr_pct = round_trip_fee_pct * (365 / holding_days)
        net_realized_apr_pct       = headline_apr_pct - amortized_fee_drag_apr_pct
        overstatement_pct          = headline_apr_pct - net_realized_apr_pct
        realization_ratio          = clamp(net_realized / headline, 0, 1)
        fee_drag_fraction          = clamp(amortized_fee_drag / headline, 0, 1)
        breakeven_days             = round_trip_fee_pct / headline_apr_pct * 365

    The headline excludes the one-off round-trip fee, so the same fee is a LARGER
    annualised drag the SHORTER the holding period. With a long hold and/or a tiny
    fee the amortised drag vanishes → net coincides with the headline
    (CLEAN_LOW_FEE). With a short hold and/or a high round-trip fee the realised APR
    collapses (SEVERE_FEE_DRAG / net-negative).

    HIGHER score = realised ≈ headline (fee drag negligible — the LP keeps the
    brochure APR). LOWER score = a large amortised fee drag (realised far below the
    headline, or net-negative).

    Per-position input dict fields:
        vault / token        : str
        headline_apr_pct     : float — running yield APR excluding entry/exit fees.
                               REQUIRED, must be a finite POSITIVE number (else
                               INSUFFICIENT_DATA).
        entry_fee_pct        : float — one-off deposit fee % (coerced abs >= 0;
                               default 0).
        exit_fee_pct         : float — one-off withdrawal fee % (coerced abs >= 0;
                               default 0).
        round_trip_fee_pct   : float — OPTIONAL direct round-trip fee; if supplied
                               (finite >= 0) it OVERRIDES entry + exit.
        holding_days         : float — LP holding horizon in days. Must be finite > 0
                               to use the holding path; default 365 if absent/invalid
                               and not using the drag-override path.
        amortized_fee_drag_apr_pct : float — OPTIONAL direct override of the
                               annualised amortised fee drag. When supplied
                               (finite >= 0) AND a valid positive headline_apr_pct is
                               present, take this drag directly and skip the holding /
                               round-trip computation (override path; holding geometry
                               → None).
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

        # The headline running APR is required and must be finite & positive.
        headline = _coerce_num(p.get("headline_apr_pct"))
        if headline is None or not math.isfinite(headline) or headline <= 0.0:
            return self._insufficient(token)

        # Override path: a direct amortised fee drag supplied → use it verbatim.
        drag_o = _coerce_num(p.get("amortized_fee_drag_apr_pct"))
        if drag_o is not None and math.isfinite(drag_o) and drag_o >= 0.0:
            return self._analyze_override(token, headline, drag_o)

        # Holding path: resolve the round-trip fee and the holding horizon.
        return self._analyze_holding(token, p, headline)

    # ── holding path ─────────────────────────────────────────────────────────────

    def _analyze_holding(self, token: str, p: dict, headline: float) -> dict:
        # Round-trip fee: explicit override (finite >= 0) else entry + exit.
        round_trip_o = _coerce_num(p.get("round_trip_fee_pct"))
        if round_trip_o is not None and math.isfinite(round_trip_o) \
                and round_trip_o >= 0.0:
            round_trip_fee_pct = round_trip_o
        else:
            round_trip_fee_pct = (
                _coerce_fee(p.get("entry_fee_pct"))
                + _coerce_fee(p.get("exit_fee_pct")))

        # Holding horizon: must be finite > 0, else fall back to default.
        holding_days = _coerce_num(p.get("holding_days"))
        if holding_days is None or not math.isfinite(holding_days) \
                or holding_days <= 0.0:
            holding_days = DEFAULT_HOLDING_DAYS

        amortized_fee_drag_apr_pct = (
            round_trip_fee_pct * (DAYS_PER_YEAR / holding_days))
        if not math.isfinite(amortized_fee_drag_apr_pct) \
                or amortized_fee_drag_apr_pct < 0.0:
            amortized_fee_drag_apr_pct = 0.0

        # Breakeven horizon: days the round-trip fee takes to amortise to the
        # headline drag (only meaningful when there is a positive fee).
        if headline > EPS and round_trip_fee_pct > 0.0:
            breakeven_days = round_trip_fee_pct / headline * DAYS_PER_YEAR
        else:
            breakeven_days = None

        return self._finish(
            token=token,
            headline_apr_pct=headline,
            round_trip_fee_pct=round_trip_fee_pct,
            amortized_fee_drag_apr_pct=amortized_fee_drag_apr_pct,
            breakeven_days=breakeven_days,
            holding_days=holding_days,
            used_override=False,
            used_holding=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(self, token: str, headline: float, drag: float) -> dict:
        drag = abs(drag)
        return self._finish(
            token=token,
            headline_apr_pct=headline,
            round_trip_fee_pct=None,
            amortized_fee_drag_apr_pct=drag,
            breakeven_days=None,
            holding_days=None,
            used_override=True,
            used_holding=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        headline_apr_pct: float,
        round_trip_fee_pct: Optional[float],
        amortized_fee_drag_apr_pct: float,
        breakeven_days: Optional[float],
        holding_days: Optional[float],
        used_override: bool,
        used_holding: bool,
    ) -> dict:
        net_realized_apr_pct = headline_apr_pct - amortized_fee_drag_apr_pct
        # overstatement = headline - net = amortized_fee_drag (computed as the
        # difference for override consistency).
        overstatement_pct = headline_apr_pct - net_realized_apr_pct

        net_is_negative = net_realized_apr_pct <= 0.0

        # Scale-free realisation_ratio / fee_drag_fraction against the headline APR.
        if headline_apr_pct > EPS and math.isfinite(headline_apr_pct):
            realization_ratio = _clamp(
                net_realized_apr_pct / headline_apr_pct, 0.0, 1.0)
            fee_drag_fraction = _clamp(
                amortized_fee_drag_apr_pct / headline_apr_pct, 0.0, 1.0)
            insufficient_headline = False
        else:
            realization_ratio = None
            fee_drag_fraction = None
            insufficient_headline = True

        if insufficient_headline:
            return self._insufficient(token)

        classification = self._classify(fee_drag_fraction, net_is_negative)
        score = self._score(realization_ratio, fee_drag_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            round_trip_fee_pct,
            holding_days,
            used_override,
        )

        return {
            "token": token,
            "headline_apr_pct": round(headline_apr_pct, 4),
            "round_trip_fee_pct": (
                round(round_trip_fee_pct, 4)
                if round_trip_fee_pct is not None else None),
            "amortized_fee_drag_apr_pct": round(amortized_fee_drag_apr_pct, 4),
            "net_realized_apr_pct": round(net_realized_apr_pct, 4),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_drag_fraction": round(fee_drag_fraction, 4),
            "breakeven_days": (
                round(breakeven_days, 4)
                if breakeven_days is not None else None),
            "holding_days": (
                round(holding_days, 4) if holding_days is not None else None),
            "net_is_negative": net_is_negative,
            "sample_count": 0,
            "used_override": used_override,
            "used_holding": used_holding,
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
        fee_drag_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the net-of-fee realised APR is close to the headline running
        APR (fee drag negligible → the LP keeps the brochure APR). Two components:
          * realisation = clamp(realization_ratio, 0, 1) — the fraction of the
            headline APR that survives the amortised fee drag,
          * fee penalty = clamp(1 − fee_drag_fraction, 0, 1) — penalises a large
            amortised fee drag relative to the headline.
        Weighted 70/30 toward realisation (it directly maps to the net the LP keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_drag_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(self, fee_drag_fraction: float, net_is_negative: bool) -> str:
        if net_is_negative:
            # The amortised fee drag has eaten the whole headline APR (or more).
            return "SEVERE_FEE_DRAG"
        if fee_drag_fraction <= CLEAN_FRACTION:
            return "CLEAN_LOW_FEE"
        if fee_drag_fraction <= MILD_FRACTION:
            return "MILD_FEE_DRAG"
        if fee_drag_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_DRAG"
        return "SEVERE_FEE_DRAG"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "CLEAN_LOW_FEE":
            return "TRUST_HEADLINE"
        if classification == "MILD_FEE_DRAG":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "MODERATE_FEE_DRAG":
            return "DISCOUNT_HEADLINE"
        # SEVERE_FEE_DRAG
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        round_trip_fee_pct: Optional[float],
        holding_days: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEES")

        if classification == "CLEAN_LOW_FEE":
            flags.append("CLEAN_LOW_FEE_HOLD")

        if used_override:
            flags.append("DRAG_FROM_OVERRIDE")
        else:
            # Holding-only flags are NOT meaningful on the override path.
            if holding_days is not None and holding_days < SHORT_HOLD_DAYS:
                flags.append("SHORT_HOLD_PENALTY")
            if (round_trip_fee_pct is not None
                    and round_trip_fee_pct >= HIGH_ROUND_TRIP_FEE_PCT):
                flags.append("HIGH_ROUND_TRIP_FEE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "headline_apr_pct": None,
            "round_trip_fee_pct": None,
            "amortized_fee_drag_apr_pct": None,
            "net_realized_apr_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_drag_fraction": None,
            "breakeven_days": None,
            "holding_days": None,
            "net_is_negative": False,
            "sample_count": 0,
            "used_override": False,
            "used_holding": False,
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
                "cleanest_fee_vault": None,
                "worst_fee_drag_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = realised ≈ headline → highest score is the cleanest fee.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEES" in r.get("flags", []))
        return {
            "cleanest_fee_vault": by_score[-1]["token"],
            "worst_fee_drag_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "net_negative_count": net_negative,
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
            # CLEAN_LOW_FEE: a tiny round-trip fee held a long time → drag ≈ 0.
            "vault": "USDC-Vault-CleanLowFee",
            "headline_apr_pct": 12.0,
            "entry_fee_pct": 0.05,
            "exit_fee_pct": 0.05,
            "holding_days": 730.0,
        },
        {
            # MILD_FEE_DRAG: a modest round-trip fee held a year.
            "vault": "stETH-Vault-MildFee",
            "headline_apr_pct": 12.0,
            "entry_fee_pct": 1.0,
            "exit_fee_pct": 1.0,
            "holding_days": 365.0,
        },
        {
            # SEVERE_FEE_DRAG: a high round-trip fee held only 20 days →
            # the amortised drag exceeds the headline → net negative.
            "vault": "GOV-Vault-SevereFee",
            "headline_apr_pct": 10.0,
            "entry_fee_pct": 1.5,
            "exit_fee_pct": 1.5,
            "holding_days": 20.0,
        },
        {
            # Override path: an annualised amortised fee drag supplied directly.
            "vault": "LST-Vault-OverrideDrag",
            "headline_apr_pct": 24.0,
            "amortized_fee_drag_apr_pct": 9.0,
        },
        {
            # INSUFFICIENT_DATA: no headline running APR supplied.
            "vault": "MYSTERY-Vault-NoData",
            "entry_fee_pct": 0.5,
            "exit_fee_pct": 0.5,
            "holding_days": 30.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1205 Vault Entry/Exit Fee Amortization Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultEntryExitFeeAmortizationAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
