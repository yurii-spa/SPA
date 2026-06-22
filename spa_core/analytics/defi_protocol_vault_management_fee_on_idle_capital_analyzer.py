"""
MP-1210: DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer
============================================================
Advisory/read-only analytics module.

A vault levies a TIME-BASED management (AUM) fee on its FULL assets-under-
management, including the IDLE / undeployed liquidity buffer that is NOT deployed
into the strategy and therefore earns ZERO yield. The depositor consequently pays
a management fee on "dead" capital that generates no return. A FAIR fee would be
charged only on the DEPLOYED (yield-earning) portion of AUM. This module measures
what share of the fee falls on idle capital and how badly that erodes the
depositor's effective net yield:

    fee                       = max(0, management_fee_pct)
    idle_frac                 = clamp(idle_fraction, 0, 1)
    deployed_frac             = 1 - idle_frac
    effective_gross_apr_pct   = gross_apr_pct * deployed_frac   # idle earns 0
    fee_charged_apr_pct       = fee                             # fee on FULL AUM
    fair_fee_apr_pct          = fee * deployed_frac             # fee on deployed only
    idle_fee_apr_pct          = max(0, fee_charged_apr_pct - fair_fee_apr_pct)
                              (= fee * idle_frac, the fee on dead capital = gap)
    net_apr_charged_pct       = effective_gross_apr_pct - fee_charged_apr_pct
    net_apr_fair_pct          = effective_gross_apr_pct - fair_fee_apr_pct
    overstatement_pct         = idle_fee_apr_pct
    net_is_negative           = net_apr_charged_pct < 0
    idle_fee_yield_share      = clamp(idle_fee_apr_pct / effective_gross_apr_pct, 0, 1)
    yield_realization_ratio   = clamp(net_apr_charged_pct / net_apr_fair_pct, 0, 1)

The headline says "we charge a small management fee", but with the fee assessed on
the FULL AUM the depositor also pays it on the idle buffer, which produces no
yield — so a chunk of the fee lands on dead capital while the deployed slice has
to carry the whole bill. The scale-free idle_fee_yield_share is the share of the
depositor's effective gross yield eaten by the fee charged on idle capital; it is
the basis of the classification. When the vault is (nearly) fully deployed there
is no idle buffer and the fee is fair (HIGHER score). When a large idle buffer
sits undeployed (or the net yield goes negative after the fee), the fee is charged
heavily on capital that earns nothing (LOWER score).

HIGHER score = capital is fully deployed (idle ≈ 0), the management fee was
effectively fair, charging the fee on deployed-only would change nothing. LOWER
score = a large share of the depositor's gross yield is eaten by the management
fee charged on idle capital, or the net yield goes negative after the fee.

Override path (when management_fee_on_idle_pct is supplied directly, finite, AND a
valid POSITIVE gross_apr_pct and POSITIVE fee_charged_apr_pct are present): take
the gap verbatim (negative → magnitude) and skip the deployed/idle/effective/fair
geometry — idle_fee_yield_share and the metrics are computed against the gross
APR:

    idle_fee_yield_share = clamp(idle_fee_apr_pct / gross_apr_pct, 0, 1)

(On the override path the deployed_frac / idle_frac / effective_gross / fair
geometry is not known → those fields are reported as None, and the geometry-only
flags FEE_ON_IDLE_CAPITAL / MOSTLY_IDLE / NET_NEGATIVE_AFTER_FEE / CLEAN_FULLY_
DEPLOYED are NOT raised; yield_realization_ratio is anchored to
(1 - idle_fee_yield_share).)

Distinct from:
  * defi_protocol_vault_idle_cash_drag_analyzer — that models the YIELD drag from
    idle capital (the APY lost because the buffer earns nothing), with NO fee in
    play. HERE the axis is the management FEE charged ON the idle slice and how it
    bites into the depositor's net yield.
  * defi_protocol_vault_management_fee_accrual_analyzer — that prices a continuous
    AUM fee on a MONOLITHIC AUM (total accrued fee / drag / net APR over days
    held) and does NOT model a deployed/idle split or the fee BASE. HERE the axis
    is the fee BASE (full AUM vs deployed-only) and the share of the fee that
    lands on dead capital.
  * defi_protocol_vault_deployment_ramp_drag_analyzer — that prices a TEMPORAL
    ramp as capital is gradually deployed over time. HERE the idle buffer is a
    STATIC undeployed slice and the fee charged on it, with no time dimension.
  * the six performance-fee modules (high_water_mark / volatility_tax /
    crystallization_frequency / hurdle_rate_gap / unrealized_gain_clawback /
    cross_sleeve_netting) — all price a PERFORMANCE fee (taken from PROFIT). HERE
    it is a MANAGEMENT (AUM) fee charged on the IDLE base, independent of profit.

The novel axis here: a time-based management (AUM) fee charged on the FULL AUM —
including the idle / undeployed buffer that earns zero — vs the fair fee that would
be charged only on the deployed, yield-earning slice (the fee base axis).

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
    "data", "vault_management_fee_on_idle_capital_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free idle_fee_yield_share in [0, 1]
# (= idle_fee_apr_pct / effective_gross_apr_pct).
CLEAN_FRACTION = 0.05        # at/below → cleanly deployed (no idle fee bite)
MILD_FRACTION = 0.20         # at/below → mild idle fee
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe idle fee

# Idle-fraction band for the MOSTLY_IDLE flag.
MOSTLY_IDLE_FRACTION = 0.50

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


def _coerce_signed(val) -> Optional[float]:
    """
    Coerce a value to a finite SIGNED float (may be negative), or None if it is
    not interpretable. Identical to _coerce_num; kept as a named alias for fields
    that may legitimately be negative.
    """
    return _coerce_num(val)


def _coerce_count(val) -> Optional[int]:
    """
    Coerce a value to a non-negative integer count, or None if not interpretable.
    """
    cv = _coerce_num(val)
    if cv is None or not math.isfinite(cv):
        return None
    iv = int(cv)
    return iv if iv >= 0 else None


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

class DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer:
    """
    Measures the share of a vault's time-based management (AUM) fee that lands on
    the IDLE / undeployed liquidity buffer — capital that earns ZERO yield — vs the
    FAIR fee that would be charged only on the DEPLOYED, yield-earning slice, and
    how badly the fee charged on idle capital erodes the depositor's net yield.

        fee                      = max(0, management_fee_pct)
        idle_frac                = clamp(idle_fraction, 0, 1)
        deployed_frac            = 1 - idle_frac
        effective_gross_apr_pct  = gross_apr_pct * deployed_frac
        fee_charged_apr_pct      = fee                       (fee on FULL AUM)
        fair_fee_apr_pct         = fee * deployed_frac       (fee on deployed only)
        idle_fee_apr_pct         = max(0, fee_charged - fair_fee) = fee * idle_frac
        net_apr_charged_pct      = effective_gross_apr - fee_charged_apr
        net_apr_fair_pct         = effective_gross_apr - fair_fee_apr
        overstatement_pct        = idle_fee_apr_pct
        idle_fee_yield_share     = clamp(idle_fee_apr / effective_gross_apr, 0, 1)
        yield_realization_ratio  = clamp(net_apr_charged / net_apr_fair, 0, 1)

    The fee is charged on the full AUM; the fair fee would be charged only on the
    deployed slice. When the vault is (nearly) fully deployed there is no idle
    buffer and the fee is fair (CLEAN_DEPLOYED). When a large idle buffer sits
    undeployed, a large share of the depositor's gross yield is eaten by the fee
    on idle capital (MODERATE / SEVERE idle fee), and if the fee exceeds the
    effective gross yield the net yield goes negative.

    HIGHER score = capital fully deployed (idle ≈ 0), the fee was effectively fair,
    charging it on deployed-only would change nothing. LOWER score = a large share
    of the gross yield is eaten by the fee on idle capital, or the net yield goes
    negative after the fee.

    Per-position input dict fields:
        vault / token             : str
        gross_apr_pct             : float — strategy APR on the DEPLOYED capital.
                                    REQUIRED, must be a finite POSITIVE number
                                    (else INSUFFICIENT_DATA).
        idle_fraction             : float — REQUIRED; fraction of AUM sitting idle
                                    (clamped into 0..1; non-finite →
                                    INSUFFICIENT_DATA).
        management_fee_pct        : float — annual AUM fee % (REQUIRED finite;
                                    negative → max(0, ...); non-finite →
                                    INSUFFICIENT_DATA on the main path).
        aum_usd                   : float — OPTIONAL, for absolute USD reporting
                                    (used only when finite > 0).
        management_fee_on_idle_pct: float — OPTIONAL direct override of the fee
                                    charged on idle capital (the gap). When
                                    supplied (finite; negative → magnitude) AND a
                                    valid POSITIVE gross_apr_pct and POSITIVE
                                    fee_charged_apr_pct are present, take this gap
                                    directly and skip the deployed/idle geometry
                                    (override path; geometry → None).
        fee_charged_apr_pct       : float — OPTIONAL, only used on the override path
                                    (finite > 0 required to take the override path).
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

        # The gross APR is required and must be finite & positive.
        gross_apr = _coerce_num(p.get("gross_apr_pct"))
        if gross_apr is None or not math.isfinite(gross_apr) or gross_apr <= 0.0:
            return self._insufficient(token)

        aum_usd = _coerce_num(p.get("aum_usd"))
        if aum_usd is None or not math.isfinite(aum_usd) or aum_usd <= 0.0:
            aum_usd = None

        # Override path: a direct fee-on-idle gap + a positive fee_charged.
        gap_o = _coerce_num(p.get("management_fee_on_idle_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_apr_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_apr, abs(gap_o), fee_charged_o, aum_usd)

        # Main path: idle_fraction is required and must be finite.
        idle_raw = _coerce_num(p.get("idle_fraction"))
        if idle_raw is None or not math.isfinite(idle_raw):
            return self._insufficient(token)

        # Main path: the management fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("management_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(token, gross_apr, idle_raw, fee_pct, aum_usd)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, gross_apr: float, idle_raw: float, fee_pct: float,
        aum_usd: Optional[float],
    ) -> dict:
        fee = max(0.0, fee_pct)
        idle_frac = _clamp(idle_raw, 0.0, 1.0)
        deployed_frac = 1.0 - idle_frac

        effective_gross_apr_pct = gross_apr * deployed_frac
        fee_charged_apr_pct = fee
        fair_fee_apr_pct = fee * deployed_frac
        idle_fee_apr_pct = max(0.0, fee_charged_apr_pct - fair_fee_apr_pct)

        return self._finish(
            token=token,
            gross_apr_pct=gross_apr,
            fee=fee,
            idle_frac=idle_frac,
            deployed_frac=deployed_frac,
            effective_gross_apr_pct=effective_gross_apr_pct,
            fee_charged_apr_pct=fee_charged_apr_pct,
            fair_fee_apr_pct=fair_fee_apr_pct,
            idle_fee_apr_pct=idle_fee_apr_pct,
            aum_usd=aum_usd,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_apr: float, gap: float, fee_charged: float,
        aum_usd: Optional[float],
    ) -> dict:
        # The gap can not exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # deployed/idle/effective/fair geometry is unknown on the override path →
        # report None; net yield can not be derived without the geometry, so the
        # geometry-only flags fall back to the gap share.
        return self._finish(
            token=token,
            gross_apr_pct=gross_apr,
            fee=None,
            idle_frac=None,
            deployed_frac=None,
            effective_gross_apr_pct=None,
            fee_charged_apr_pct=fee_charged,
            fair_fee_apr_pct=max(0.0, fee_charged - gap),
            idle_fee_apr_pct=gap,
            aum_usd=aum_usd,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_apr_pct: float,
        fee: Optional[float],
        idle_frac: Optional[float],
        deployed_frac: Optional[float],
        effective_gross_apr_pct: Optional[float],
        fee_charged_apr_pct: float,
        fair_fee_apr_pct: float,
        idle_fee_apr_pct: float,
        aum_usd: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the fee charged on idle (dead) capital (kept for family
        # consistency with the headline-honesty family).
        overstatement_pct = idle_fee_apr_pct

        # Net yield: only computable when the deployed/idle geometry is known.
        if effective_gross_apr_pct is not None:
            net_apr_charged_pct = effective_gross_apr_pct - fee_charged_apr_pct
            net_apr_fair_pct = effective_gross_apr_pct - fair_fee_apr_pct
            net_is_negative = net_apr_charged_pct < 0.0
            if net_apr_fair_pct > EPS:
                yield_realization_ratio = _clamp(
                    net_apr_charged_pct / net_apr_fair_pct, 0.0, 1.0)
            else:
                # Mirror the cross-sleeve template edge: when the fair net is
                # non-positive, the ratio is 1.0 only if the charged net still
                # clears the fair net and is itself non-negative, else 0.0.
                yield_realization_ratio = (
                    1.0 if (net_apr_charged_pct >= net_apr_fair_pct
                            and net_apr_charged_pct >= 0.0) else 0.0)
        else:
            # Override path: geometry unknown. Anchor realisation via the
            # fee-on-idle share below; flag net as not known.
            net_apr_charged_pct = None
            net_apr_fair_pct = None
            net_is_negative = False
            yield_realization_ratio = None

        # Scale-free idle-fee yield share — the share of the depositor's effective
        # gross yield eaten by the fee charged on idle capital.
        if effective_gross_apr_pct is not None:
            if effective_gross_apr_pct > EPS:
                idle_fee_yield_share = _clamp(
                    idle_fee_apr_pct / effective_gross_apr_pct, 0.0, 1.0)
            else:
                # Edge: no effective gross yield → 1.0 if any idle fee, else 0.0.
                idle_fee_yield_share = 1.0 if idle_fee_apr_pct > 0.0 else 0.0
        else:
            # Override path: no effective gross known → use gross APR directly.
            if gross_apr_pct > EPS:
                idle_fee_yield_share = _clamp(
                    idle_fee_apr_pct / gross_apr_pct, 0.0, 1.0)
            else:
                idle_fee_yield_share = 1.0 if idle_fee_apr_pct > 0.0 else 0.0

        # On the override path, with no net geometry, anchor the realisation on
        # (1 - idle_fee_yield_share): the share of the gross yield not eaten by the
        # idle fee is the share the depositor "realised fairly".
        if yield_realization_ratio is None:
            yield_realization_ratio = _clamp(
                1.0 - idle_fee_yield_share, 0.0, 1.0)

        # Absolute USD reporting (optional).
        if aum_usd is not None:
            idle_fee_usd = round(aum_usd * (idle_fee_apr_pct / 100.0), 4)
        else:
            idle_fee_usd = None

        classification = self._classify(idle_fee_yield_share, net_is_negative)
        score = self._score(
            yield_realization_ratio, idle_fee_yield_share, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            idle_frac,
            idle_fee_apr_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_apr_pct": round(gross_apr_pct, 4),
            "management_fee_pct": (
                round(fee, 4) if fee is not None else None),
            "idle_fraction": (
                round(idle_frac, 4) if idle_frac is not None else None),
            "deployed_fraction": (
                round(deployed_frac, 4) if deployed_frac is not None else None),
            "effective_gross_apr_pct": (
                round(effective_gross_apr_pct, 4)
                if effective_gross_apr_pct is not None else None),
            "fee_charged_apr_pct": round(fee_charged_apr_pct, 4),
            "fair_fee_apr_pct": round(fair_fee_apr_pct, 4),
            "idle_fee_apr_pct": round(idle_fee_apr_pct, 4),
            "net_apr_charged_pct": (
                round(net_apr_charged_pct, 4)
                if net_apr_charged_pct is not None else None),
            "net_apr_fair_pct": (
                round(net_apr_fair_pct, 4)
                if net_apr_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "yield_realization_ratio": round(yield_realization_ratio, 4),
            "idle_fee_yield_share": round(idle_fee_yield_share, 4),
            "net_is_negative": net_is_negative,
            "aum_usd": (round(aum_usd, 4) if aum_usd is not None else None),
            "idle_fee_usd": idle_fee_usd,
            "sample_count": 0,
            "used_override": used_override,
            "used_main": used_main,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags_out,
        }

    # ── scoring ────────────────────────────────────────────────────────────────

    def _score(
        self,
        yield_realization_ratio: float,
        idle_fee_yield_share: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the management fee was charged on capital that actually
        earns: the depositor keeps the net yield the deployed capital produced.
        Two components:
          * realisation = clamp(yield_realization_ratio, 0, 1) — the fraction of
            the fair net yield that survives the fee charged on the full AUM,
          * fee-base penalty = clamp(1 − idle_fee_yield_share, 0, 1) — penalises a
            large share of the gross yield being eaten by the fee on idle capital.
        Weighted 70/30 toward realisation (it directly maps to the net yield the
        depositor keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(yield_realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - idle_fee_yield_share, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, idle_fee_yield_share: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            # The fee has eaten the whole effective gross yield (or more).
            return "SEVERE_IDLE_FEE"
        if idle_fee_yield_share <= CLEAN_FRACTION:
            return "CLEAN_DEPLOYED"
        if idle_fee_yield_share <= MILD_FRACTION:
            return "MILD_IDLE_FEE"
        if idle_fee_yield_share <= MODERATE_FRACTION:
            return "MODERATE_IDLE_FEE"
        return "SEVERE_IDLE_FEE"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_IDLE"
        if classification == "CLEAN_DEPLOYED":
            return "TRUST_FEE_BASE"
        if classification == "MILD_IDLE_FEE":
            return "MINOR_IDLE_FEE"
        if classification == "MODERATE_IDLE_FEE":
            return "DEMAND_DEPLOYED_ONLY_FEE"
        # SEVERE_IDLE_FEE
        return "AVOID_FEE_ON_IDLE"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        idle_frac: Optional[float],
        idle_fee_apr_pct: float,
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if classification == "CLEAN_DEPLOYED":
                flags.append("CLEAN_FULLY_DEPLOYED")
            if net_is_negative:
                flags.append("NET_NEGATIVE_AFTER_FEE")
            if idle_fee_apr_pct > 0.0:
                flags.append("FEE_ON_IDLE_CAPITAL")
            if idle_frac is not None and idle_frac >= MOSTLY_IDLE_FRACTION:
                flags.append("MOSTLY_IDLE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_apr_pct": None,
            "management_fee_pct": None,
            "idle_fraction": None,
            "deployed_fraction": None,
            "effective_gross_apr_pct": None,
            "fee_charged_apr_pct": None,
            "fair_fee_apr_pct": None,
            "idle_fee_apr_pct": None,
            "net_apr_charged_pct": None,
            "net_apr_fair_pct": None,
            "overstatement_pct": None,
            "yield_realization_ratio": None,
            "idle_fee_yield_share": None,
            "net_is_negative": False,
            "aum_usd": None,
            "idle_fee_usd": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_IDLE",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "cleanest_vault": None,
                "worst_idle_fee_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = cleanly deployed → highest score is the cleanest vault.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_idle_fee_vault": by_score[0]["token"],
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
            # CLEAN_DEPLOYED: idle ≈ 0 → fully deployed, fee was effectively fair.
            "vault": "USDC-Vault-CleanDeployed",
            "gross_apr_pct": 12.0,
            "idle_fraction": 0.01,
            "management_fee_pct": 1.0,
            "aum_usd": 5_000_000.0,
        },
        {
            # MODERATE_IDLE_FEE: a large idle buffer carries a chunky fee →
            # ~half the gross yield eaten by the fee on idle capital.
            "vault": "stETH-Vault-LargeIdleBuffer",
            "gross_apr_pct": 6.0,
            "idle_fraction": 0.40,
            "management_fee_pct": 2.0,
            "aum_usd": 20_000_000.0,
        },
        {
            # SEVERE_IDLE_FEE (net negative): a fat fee on a mostly-idle vault
            # whose deployed slice can not carry the bill → net yield negative.
            "vault": "GOV-Vault-MostlyIdle",
            "gross_apr_pct": 4.0,
            "idle_fraction": 0.70,
            "management_fee_pct": 3.0,
            "aum_usd": 8_000_000.0,
        },
        {
            # Override path: a fee-on-idle gap supplied directly with the fee
            # charged → idle_fee_yield_share = 4/20 = 0.2 → MILD_IDLE_FEE.
            "vault": "LST-Vault-OverrideGap",
            "gross_apr_pct": 20.0,
            "management_fee_on_idle_pct": 4.0,
            "fee_charged_apr_pct": 5.0,
        },
        {
            # INSUFFICIENT_DATA: no gross APR supplied.
            "vault": "MYSTERY-Vault-NoData",
            "idle_fraction": 0.30,
            "management_fee_pct": 2.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1210 Vault Management-Fee-On-Idle-Capital Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = DeFiProtocolVaultManagementFeeOnIdleCapitalAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
