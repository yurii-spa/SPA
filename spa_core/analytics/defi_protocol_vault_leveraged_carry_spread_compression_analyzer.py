"""
MP-1201: DeFiProtocolVaultLeveragedCarrySpreadCompressionAnalyzer
================================================================
Advisory/read-only analytics module.

A leveraged / looping vault (recursive LST looping, leveraged staking, folded
lending) advertises a headline NET APR computed at a SNAPSHOT — and usually
favourable, currently-low — borrow rate:

    net_headline = base_yield * L - borrow_snapshot * (L - 1)

where L = leverage = total_exposure / equity >= 1, and base_yield is the
unlevered supply / staking yield. The depositor's realised carry is the gap
between what the levered exposure EARNS and what the borrowed leg COSTS.

But the borrow rate is VARIABLE: it rises with utilisation and mean-reverts
upward from the favourable snapshot the headline was struck at. Over a holding
window the honest realised net carry uses the TRAILING borrow-rate samples
(their mean), which may have climbed toward — or above — the base yield:

    borrow_realized = mean(borrow_samples)
    net_realized    = base_yield * L - borrow_realized * (L - 1)
    spread_compression = net_headline - net_realized
                       = (borrow_realized - borrow_snapshot) * (L - 1)

Crucially the borrow cost is multiplied by the AMPLIFICATION factor (L - 1), so a
small rise in the borrow rate is magnified into the net carry. If the realised
borrow rate reaches the base yield the GROSS spread inverts and the levered carry
can go NEGATIVE — the depositor pays to hold the position.

Angle: "a 3x looped LST vault advertises 18% net APR struck at a 2% snapshot
borrow rate (base 8% staking: 8%*3 - 2%*2 = 20% gross-ish), but over the trailing
window the borrow rate averaged 5.5% (it spiked with utilisation) → realised net
= 8%*3 - 5.5%*2 = 13% — ~5pp of compression from a 3.5pp borrow rise amplified by
(L-1)=2; and a borrow rate above 12% would invert the carry entirely. Discount
the headline toward the realised, borrow-aware net carry."

HIGHER score = the realised borrow cost is close to the snapshot the headline was
struck at (stable, deep borrow spread → the levered net carry survives). LOWER
score = the borrow rate compressed (or inverted) the spread, so the amplified net
carry realises far below the headline.

Distinct from:
  * defi_protocol_leverage_adjusted_apy_calculator — that module PRESCRIPTIVELY
    computes a leveraged APY from given base/borrow/leverage inputs (a forward
    calculator). HERE we audit headline HONESTY: how much the trailing,
    time-varying borrow cost compresses an already-quoted levered net carry.
  * defi_protocol_leverage_loop_risk_analyzer — that scores the LIQUIDATION /
    unwind risk of the loop (protocol_health). HERE the question is yield
    REALISATION (net carry survival), not liquidation safety.
  * defi_protocol_vault_funding_rate_carry_persistence_analyzer — that concerns a
    signed PERPETUAL FUNDING carry on a delta-neutral position (futures funding).
    HERE the cost leg is a LENDING borrow rate on a borrowed principal, and the
    distinctive mechanic is the (L-1) AMPLIFICATION of borrow moves into the net.
  * defi_protocol_stablecoin_yield_basis_spread_analyzer — that measures a basis
    spread between stablecoin yield venues. HERE the spread is base-yield-minus-
    borrow-cost on a single levered position, amplified by leverage.
  * defi_protocol_vault_yield_variance_drag_realization_analyzer — that converts
    DISPERSION of per-period returns into a geometric-vs-arithmetic compounding
    deficit (a SECOND-MOMENT penalty). HERE the compression is a FIRST-MOMENT
    rise in the mean borrow cost, amplified by (L-1) — not a variance penalty.

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
    "data", "vault_leveraged_carry_spread_compression_log.json"
)
LOG_CAP = 100

# Minimum valid borrow-rate samples required to use the sample path.
MIN_SAMPLES = 2

# Classification thresholds on the scale-free compression_fraction in [0, 1].
STABLE_FRACTION = 0.05      # at/below → stable spread (headline ~ realised)
MILD_FRACTION = 0.20        # at/below → mild compression
HEAVY_FRACTION = 0.50       # at/below → heavy; above → severe compression

# Leverage at/above this amplifies borrow moves strongly into the net carry.
HIGH_LEVERAGE = 3.0
# A leverage at/below this (≈1x) carries no borrowed leg → no amplification.
NO_LEVERAGE_MAX = 1.0 + 1e-9
# Coefficient of variation of the borrow series at/above this is "volatile".
HIGH_CV = 0.5

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


def _coerce_borrow_rates(raw) -> List[float]:
    """
    Coerce a list of per-interval borrow-rate (APR %) samples to finite,
    NON-NEGATIVE floats. A borrow rate cannot be negative, so negative (and
    non-finite / non-numeric) entries are skipped. Order is preserved.
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


def _derive_leverage(p: dict) -> Optional[float]:
    """
    Resolve the leverage factor L >= 1 from an explicit `leverage` /
    `leverage_factor`, or derive it from `total_exposure_usd` / `equity_usd`.
    Returns None if no valid L >= 1 can be obtained.
    """
    raw = p.get("leverage", p.get("leverage_factor"))
    lev = _f(raw, default=float("nan"))
    if math.isfinite(lev) and lev >= 1.0:
        return lev
    te = _f(p.get("total_exposure_usd"), default=float("nan"))
    eq = _f(p.get("equity_usd"), default=float("nan"))
    if math.isfinite(te) and math.isfinite(eq) and eq > 0.0 and te >= eq:
        derived = te / eq
        if math.isfinite(derived) and derived >= 1.0:
            return derived
    return None


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

class DeFiProtocolVaultLeveragedCarrySpreadCompressionAnalyzer:
    """
    Measures how much a VARIABLE, trailing borrow cost compresses the net carry
    of a leveraged / looping vault relative to the favourable snapshot borrow
    rate its headline net APR was struck at, with the borrow move AMPLIFIED by
    the (L - 1) leverage factor:

        net_headline       = base_yield * L - borrow_snapshot * (L - 1)
        net_realized       = base_yield * L - borrow_realized * (L - 1)
        spread_compression = net_headline - net_realized
                           = (borrow_realized - borrow_snapshot) * (L - 1)
        realization_ratio  = clamp(net_realized / net_headline, 0, 1)
        compression_frac   = clamp(spread_compression / net_headline, 0, 1)

    HIGHER score = the realised borrow cost stays near the snapshot (stable, deep
    spread → the levered net carry survives). LOWER score = the borrow rate
    compressed or inverted the amplified spread, so the net carry realises far
    below the headline.

    Per-position input dict fields:
        vault / token          : str
        base_yield_apr_pct     : float — the UNLEVERED supply / staking yield;
                                 must be finite and > 0 (else INSUFFICIENT_DATA).
        leverage / leverage_factor : float >= 1 — leverage L (or supply
                                 total_exposure_usd + equity_usd to derive it).
        borrow_rate_samples    : list — trailing per-interval borrow rates (APR %),
                                 newest last (optional). Negative / non-finite
                                 entries are skipped.
        borrow_rate_snapshot_pct : float — the (favourable) borrow rate the headline
                                 was struck at. Default = MIN of the samples
                                 (the most favourable point) when omitted.
        net_apr_headline_pct   : float — OPTIONAL direct override of the headline
                                 net APR (else computed from the formula above).
        borrow_rate_realized_pct : float — OPTIONAL direct override of the realised
                                 borrow rate, used when samples are absent / too few.

    MIN_SAMPLES = 2 valid borrow samples are required to use the sample path.
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

        base_yield = _f(p.get("base_yield_apr_pct"), default=float("nan"))
        if not math.isfinite(base_yield) or base_yield <= 0.0:
            return self._insufficient(token)

        leverage = _derive_leverage(p)
        if leverage is None:
            return self._insufficient(token)
        amplification = max(0.0, leverage - 1.0)

        samples = _coerce_borrow_rates(p.get("borrow_rate_samples"))
        n = len(samples)
        used_samples = n >= MIN_SAMPLES

        if used_samples:
            borrow_realized = _mean(samples)
            max_borrow = max(samples)
            snap_raw = p.get("borrow_rate_snapshot_pct")
            snap = _coerce_num(snap_raw)
            # Headline is typically struck at the most favourable (lowest) point.
            borrow_snapshot = snap if snap is not None else min(samples)
            sd = _pstdev(samples)
            coefficient_of_variation = (
                round(sd / borrow_realized, 4)
                if borrow_realized > EPS and math.isfinite(sd / borrow_realized)
                else None)
            borrow_volatility = sd
            used_override = False
        else:
            realized_o = _coerce_num(p.get("borrow_rate_realized_pct"))
            if realized_o is None:
                return self._insufficient(token)
            borrow_realized = realized_o
            snap = _coerce_num(p.get("borrow_rate_snapshot_pct"))
            # Without a series, fall back to the realised rate as the snapshot
            # (→ no compression) unless an explicit snapshot is supplied.
            borrow_snapshot = snap if snap is not None else realized_o
            max_borrow = None
            coefficient_of_variation = None
            borrow_volatility = None
            used_override = True

        # Headline net carry: explicit override or computed from the formula.
        net_override = p.get("net_apr_headline_pct")
        if net_override is not None:
            net_headline = _f(net_override, default=float("nan"))
        else:
            net_headline = base_yield * leverage - borrow_snapshot * amplification

        if not math.isfinite(net_headline) or net_headline <= 0.0:
            # A non-positive advertised levered carry is not a meaningful
            # headline to audit for overstatement.
            return self._insufficient(token)

        net_realized = base_yield * leverage - borrow_realized * amplification
        spread_compression = net_headline - net_realized

        gross_spread_headline = base_yield - borrow_snapshot
        gross_spread_realized = base_yield - borrow_realized

        realization_ratio = _clamp(
            _safe_div(net_realized, net_headline, sentinel=0.0), 0.0, 1.0)
        compression_fraction = _clamp(
            _safe_div(spread_compression, net_headline, sentinel=0.0), 0.0, 1.0)

        carry_inverted = net_realized < 0.0
        borrow_exceeds_base = (
            borrow_realized >= base_yield
            or (max_borrow is not None and max_borrow >= base_yield))

        classification = self._classify(compression_fraction, carry_inverted)
        score = self._score(
            realization_ratio, borrow_volatility, base_yield, used_override)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            carry_inverted,
            borrow_exceeds_base,
            leverage,
            coefficient_of_variation,
            borrow_snapshot,
            borrow_realized,
            used_override,
        )

        return {
            "token": token,
            "base_yield_apr_pct": round(base_yield, 4),
            "leverage_factor": round(leverage, 4),
            "amplification_factor": round(amplification, 4),
            "borrow_rate_headline_pct": round(borrow_snapshot, 4),
            "borrow_rate_realized_pct": round(borrow_realized, 4),
            "borrow_rate_volatility_pct": (
                round(borrow_volatility, 4)
                if borrow_volatility is not None else None),
            "max_borrow_rate_pct": (
                round(max_borrow, 4) if max_borrow is not None else None),
            "gross_spread_headline_pct": round(gross_spread_headline, 4),
            "gross_spread_realized_pct": round(gross_spread_realized, 4),
            "net_apr_headline_pct": round(net_headline, 4),
            "net_apr_realized_pct": round(net_realized, 4),
            "spread_compression_pct": round(spread_compression, 4),
            "realization_ratio": round(realization_ratio, 4),
            "compression_fraction": round(compression_fraction, 4),
            "coefficient_of_variation": coefficient_of_variation,
            "carry_inverted": carry_inverted,
            "borrow_exceeds_base": borrow_exceeds_base,
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
        borrow_volatility: Optional[float],
        base_yield: float,
        used_override: bool,
    ) -> float:
        """
        0–100, HIGHER = the levered net carry survives the realised borrow cost
        (the realised borrow rate stays near the favourable snapshot the headline
        was struck at). Two components:
          * realisation = clamp(realization_ratio, 0, 1) — how much of the headline
            net carry survives the trailing, amplified borrow cost (1 → realised ≈
            headline, 0 → carry compressed away or inverted),
          * stability = clamp(1 − normalised_borrow_vol, 0, 1) — how steady the
            borrow series is relative to the base-yield scale; a jumpy borrow rate
            means the snapshot the headline was struck at is unrepresentative.
        Weighted 70/30 toward realisation (it directly maps to the net carry a
        depositor keeps); stability corroborates how reliable the snapshot is. On
        the override path (no borrow series → no volatility) the stability
        component is neutral (full weight on realisation).
        """
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        if used_override or borrow_volatility is None:
            stability = 1.0
        else:
            denom = base_yield + borrow_volatility + EPS
            normalised_vol = _clamp(borrow_volatility / denom, 0.0, 1.0)
            stability = _clamp(1.0 - normalised_vol, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * stability, 0.0, 100.0)

    def _classify(
        self, compression_fraction: float, carry_inverted: bool
    ) -> str:
        if carry_inverted:
            return "SEVERE_COMPRESSION"
        if compression_fraction <= STABLE_FRACTION:
            return "STABLE_SPREAD"
        if compression_fraction <= MILD_FRACTION:
            return "MILD_COMPRESSION"
        if compression_fraction <= HEAVY_FRACTION:
            return "HEAVY_COMPRESSION"
        return "SEVERE_COMPRESSION"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_OR_VERIFY"
        if classification == "STABLE_SPREAD":
            return "TRUST_HEADLINE"
        if classification == "MILD_COMPRESSION":
            return "DISCOUNT_HEADLINE_SLIGHTLY"
        if classification == "HEAVY_COMPRESSION":
            return "DISCOUNT_HEADLINE"
        # SEVERE_COMPRESSION
        return "AVOID_OR_VERIFY"

    def _flags(
        self,
        classification: str,
        carry_inverted: bool,
        borrow_exceeds_base: bool,
        leverage: float,
        coefficient_of_variation: Optional[float],
        borrow_snapshot: float,
        borrow_realized: float,
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        flags.append(classification)

        if carry_inverted:
            flags.append("CARRY_INVERTED")
        if borrow_exceeds_base:
            flags.append("BORROW_EXCEEDS_BASE")
        if leverage >= HIGH_LEVERAGE:
            flags.append("HIGH_LEVERAGE_AMPLIFICATION")
        if leverage <= NO_LEVERAGE_MAX:
            flags.append("NO_LEVERAGE")
        if (coefficient_of_variation is not None
                and coefficient_of_variation >= HIGH_CV):
            flags.append("VOLATILE_BORROW")
        if borrow_snapshot < borrow_realized - EPS:
            flags.append("SPREAD_FROM_SNAPSHOT")
        if classification == "STABLE_SPREAD":
            flags.append("STABLE_SPREAD_CARRY")
        if used_override:
            flags.append("COMPRESSION_FROM_OVERRIDE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "base_yield_apr_pct": None,
            "leverage_factor": None,
            "amplification_factor": None,
            "borrow_rate_headline_pct": None,
            "borrow_rate_realized_pct": None,
            "borrow_rate_volatility_pct": None,
            "max_borrow_rate_pct": None,
            "gross_spread_headline_pct": None,
            "gross_spread_realized_pct": None,
            "net_apr_headline_pct": None,
            "net_apr_realized_pct": None,
            "spread_compression_pct": None,
            "realization_ratio": None,
            "compression_fraction": None,
            "coefficient_of_variation": None,
            "carry_inverted": None,
            "borrow_exceeds_base": None,
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
                "most_stable_vault": None,
                "most_compressed_vault": None,
                "avg_score": 0.0,
                "carry_inverted_count": 0,
                "position_count": len(results),
            }
        # Higher score = spread survives → highest score is most stable.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        inverted = sum(
            1 for r in results if r.get("carry_inverted") is True)
        return {
            "most_stable_vault": by_score[-1]["token"],
            "most_compressed_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "carry_inverted_count": inverted,
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
            # STABLE_SPREAD: borrow cost barely moved from the snapshot → the
            # levered net carry survives ≈ the headline.
            "vault": "stETH-Loop-StableBorrow",
            "base_yield_apr_pct": 8.0,
            "leverage": 3.0,
            "borrow_rate_samples": [2.0, 2.1, 1.9, 2.05, 2.0],
            "borrow_rate_snapshot_pct": 2.0,
        },
        {
            # MILD_COMPRESSION: borrow drifted modestly above the snapshot.
            "vault": "wBTC-Folded-MildDrift",
            "base_yield_apr_pct": 7.0,
            "leverage": 3.0,
            "borrow_rate_samples": [2.0, 2.5, 3.0, 3.2, 2.8],
            "borrow_rate_snapshot_pct": 2.0,
        },
        {
            # SEVERE_COMPRESSION / inversion: borrow rate spiked above the base
            # yield → the amplified net carry goes negative.
            "vault": "GOV-Loop-BorrowSpike",
            "base_yield_apr_pct": 6.0,
            "leverage": 4.0,
            "borrow_rate_samples": [6.0, 9.0, 11.0, 12.0, 10.0],
            "borrow_rate_snapshot_pct": 2.0,
        },
        {
            # Override path: realised borrow rate supplied directly, above snapshot.
            "vault": "LST-Loop-OverrideRealized",
            "base_yield_apr_pct": 9.0,
            "leverage": 2.5,
            "borrow_rate_realized_pct": 5.0,
            "borrow_rate_snapshot_pct": 2.0,
        },
        {
            # INSUFFICIENT_DATA: positive base yield but no borrow series / override.
            "vault": "MYSTERY-Loop-NoData",
            "base_yield_apr_pct": 8.0,
            "leverage": 3.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1201 Vault Leveraged Carry Spread Compression Analyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultLeveragedCarrySpreadCompressionAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
