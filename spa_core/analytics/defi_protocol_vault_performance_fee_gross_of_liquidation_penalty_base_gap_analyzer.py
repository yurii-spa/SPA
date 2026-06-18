"""
MP-1241: DeFiProtocolVaultPerformanceFeeGrossOfLiquidationPenaltyBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

Leveraged / looping yield vaults (leveraged liquid-staking, recursive borrow
loops, leveraged LP) hold collateral against a borrowed leg. When the collateral
value drops or the debt grows, the position is partially LIQUIDATED: a liquidator
repays part of the vault's debt and seizes collateral at a discount. The value
lost in that seizure — the LIQUIDATION PENALTY — is the liquidation bonus /
incentive paid to the liquidator (collateral handed over above the debt repaid)
PLUS any explicit protocol liquidation fee. (Aave's liquidation bonus, Compound's
liquidation incentive, Maker's liquidation penalty all sit in the ~5–15% range of
the seized collateral.) This penalty is extracted from the vault's own collateral
and is therefore a real drag on the cycle's gross yield: it is taken out before
the depositor sees anything. It is NOT residual bad debt socialised across
depositors (the liquidation here SUCCEEDS and covers the debt), NOT the ongoing
interest on the borrowed leg, and NOT a validator slashing penalty. Economically,
the depositor's NET yield is:

    net_of_liquidation_penalty_yield = gross_yield - liquidation_penalty

But many vaults charge the performance fee on the GROSS yield (before netting
the LIQUIDATION PENALTY — the liquidator bonus + protocol liquidation fee bled
from the vault's collateral during the measurement window), not on the
net-of-liquidation-penalty yield the depositor economically realized. The result
is a "fee-on-liquidation-penalty" / fee-base inflation: the performance fee is
levied on the yield slice the liquidation penalty already consumed. The fair
performance fee would be levied only on the net-of-liquidation-penalty yield:

    fee_frac                              = clamp(performance_fee_pct / 100, 0, 1)
    liquidation_penalty_consumed_yield_pct  = max(0, gross_yield - net_of_liq_yield)
    fee_charged_pct                       = fee_frac * max(0, gross_yield)
    fair_fee_pct                          = fee_frac * max(0, net_of_liq_yield)
    fee_on_liquidation_penalty_gap_pct      = max(0, fee_charged - fair_fee)
                                            (= performance fee charged on the
                                             liquidation-penalty slice of the yield,
                                             which the depositor never received)
    net_return_after_fee_pct              = net_of_liq_yield - fee_charged
    net_return_fair_pct                   = net_of_liq_yield - fair_fee
    overstatement_pct                     = fee_on_liquidation_penalty_gap_pct
    fee_on_liquidation_penalty_fraction     = clamp(gap / fee_charged, 0, 1)
    realization_ratio                     = clamp(net_after_fee / net_fair, 0, 1)

The headline says "you only pay performance fees on profits", but when the
performance fee is charged on gross yield a chunk of the performance fee lands
on the liquidation-penalty slice the depositor never received. The scale-free
fee_on_liquidation_penalty_fraction is the share of the charged performance fee
that landed on the liquidation-penalty slice; it is the basis of the
classification. When the liquidation penalty consumed nothing (net_of_liq approx
gross) the performance fee was effectively fair (HIGHER score). When the
liquidation penalty consumed most of the yield, the performance fee was charged
almost entirely on the liquidation-penalty slice (LOWER score).

HIGHER score = the performance fee was charged on the net-of-liquidation-penalty
base (gross approx net_of_liq), the fee was effectively fair, nothing to fix.
LOWER score = a large share of the performance fee landed on the
liquidation-penalty slice, or the net return goes negative after the fee.

Override path (when fee_on_liquidation_penalty_gap_pct is supplied directly,
finite, AND a valid POSITIVE gross_yield_pct and POSITIVE fee_charged_pct are
present): take the gap verbatim (negative -> magnitude) and skip the
net-of-liquidation-penalty geometry — fee_on_liquidation_penalty_fraction and the
metrics are computed the same way:

    fee_on_liquidation_penalty_fraction = clamp(gap / fee_charged_pct, 0, 1)

(On the override path the net-of-liquidation-penalty / liq-slice / fair geometry
is not known -> those fields are reported as None, and the geometry-only flags
FEE_ON_LIQUIDATION_PENALTY / FULL_FEE_ON_LIQUIDATION_PENALTY / NET_NEGATIVE_AFTER_FEE
are NOT raised; realization_ratio is anchored to
(1 - fee_on_liquidation_penalty_fraction).)

Distinct from (this is the GROSS-OF-LIQUIDATION-PENALTY performance-fee BASE —
the fee being charged on the gross yield before the LIQUIDATION PENALTY the
vault's leveraged position pays to the liquidator (liquidation bonus + protocol
liquidation fee bled from the seized collateral) is netted out, not a fee paid
to an AMM pool, nor value extracted adversarially by mempool searchers, nor
execution gas, nor another cost layer):
  * defi_protocol_vault_performance_fee_gross_of_bad_debt_socialization_base_gap_analyzer
    — that module prices RESIDUAL BAD DEBT socialised across depositors when a
    liquidation FAILS to recover the full debt (the position goes underwater and
    the shortfall is spread over the remaining share supply). HERE the
    liquidation SUCCEEDS and covers the debt; the loss is the PENALTY / bonus
    handed to the liquidator who performed it, not uncovered residual debt.
  * defi_protocol_vault_performance_fee_gross_of_borrow_cost_base_gap_analyzer
    — that module prices the ONGOING INTEREST accrued on the borrowed leg of the
    leverage loop. HERE it is the one-off penalty crystallised at the moment of a
    liquidation event, not continuous borrow interest.
  * defi_protocol_vault_performance_fee_gross_of_slashing_loss_base_gap_analyzer
    — that module prices a VALIDATOR / RESTAKING SLASHING penalty imposed by the
    consensus / AVS protocol for misbehaviour. HERE it is a lending-market
    liquidation penalty triggered by a collateral/health-factor breach, paid to a
    liquidator, not a slashing penalty imposed by a validator protocol.
  * defi_protocol_vault_performance_fee_gross_of_exit_slippage / swap_fee /
    rebalancing_cost / mev_tax base gap analyzers
    — those price the vault's OWN trade-execution drag: deterministic price impact
    along the pool curve, the AMM LP swap fee, aggregate turnover cost, and value
    sandwiched/backrun by searchers. HERE it is a liquidation penalty seized from
    collateral by a liquidator, not a trade-execution cost.
  * defi_protocol_vault_performance_fee_gross_of_cost / priority_fee / blob_fee /
    l1_data_fee / bundler_fee / crosschain_message_fee / oracle_update_fee /
    harvest_bounty base gap analyzers
    — those price EXECUTION GAS / a proposer tip / blob-gas DA posting / L1 data
    fee / ERC-4337 bundler premium / cross-chain messaging delivery / oracle
    price-feed post / a keeper-caller bounty. HERE it is the liquidation penalty,
    NOT a gas-market, account-abstraction, messaging, oracle or keeper fee.
  * defi_protocol_vault_performance_fee_gross_of_funding_cost /
    bridge_fee / flash_loan_fee / management_fee / deposit_fee / withdrawal_fee
    (and the other gross_of_* perf-fee modules: gross_of_insurance_premium,
    gross_of_validator_commission, gross_of_impermanent_loss,
    gross_of_reserve_contribution, gross_of_referral_fee, gross_of_boost_fee,
    gross_of_intent_solver_fee)
    — each prices a DIFFERENT erosion layer (perp funding, cross-chain transfer,
    flash-loan premium, AUM charge, entry/exit fee, …). None of those layers is
    the LIQUIDATION PENALTY seized from the vault's collateral by the liquidator.
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer and related
    performance-fee mechanic modules — those measure HWM/crystallization
    fairness. HERE the axis is the fee-BASE inflation from charging the
    performance fee on gross (pre-liquidation-penalty) yield, not HWM or
    crystallization mechanics.

The novel axis here: the performance-fee BASE being GROSS-OF-LIQUIDATION-PENALTY
rather than NET-OF-LIQUIDATION-PENALTY — a fee-on-liquidation-penalty / fee-base
inflation in which the performance fee is charged on the slice of yield the
LIQUIDATION PENALTY (the liquidator bonus + protocol liquidation fee bled from
the vault's seized collateral) already consumed.

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
    "data",
    "vault_performance_fee_gross_of_liquidation_penalty_base_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free fee_on_liquidation_penalty_fraction in [0, 1]
# (= fee_on_liquidation_penalty_gap_pct / fee_charged_pct).
CLEAN_FRACTION = 0.05        # at/below → cleanly on the net-of-liquidation-penalty base
MILD_FRACTION = 0.20         # at/below → mild fee-on-liquidation-penalty gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe gap

# High-liquidation-penalty flag threshold on liquidation_penalty_rate_pct
# (interpreted as the LIQUIDATION PENALTY — the liquidator bonus + protocol
# liquidation fee bled from the vault's seized collateral — expressed as a % of
# the position notional eroded over the measurement window). A liquidation
# penalty consuming more than ~0.3% of the position notional over the window is
# atypical for a prudently-managed, low-LTV leveraged vault; only frequent or
# deep liquidations of a high-LTV position approach this level.
HIGH_LIQUIDATION_PENALTY_PCT = 0.3

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
    not interpretable. Identical to _coerce_num; kept as a named alias for the
    net-of-liquidation-penalty-yield field, which may legitimately be negative.
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

class DeFiProtocolVaultPerformanceFeeGrossOfLiquidationPenaltyBaseGapAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the LIQUIDATION PENALTY — the liquidator bonus + protocol
    liquidation fee bled from the vault's seized collateral when its leveraged
    position is liquidated — is netted out) and the FAIR fee it would charge on
    the NET-OF-LIQUIDATION-PENALTY yield the depositor economically realized, and
    the share of the charged performance fee that therefore landed on the
    LIQUIDATION-PENALTY slice of the yield (a fee-on-liquidation-penalty /
    fee-base inflation).

        fee_frac                   = clamp(performance_fee_pct / 100, 0, 1)
        liquidation_penalty_consumed_yield_pct = max(0, gross_yield - net_of_liquidation_penalty_yield)
        fee_charged_pct            = fee_frac * max(0, gross_yield)
        fair_fee_pct               = fee_frac * max(0, net_of_liquidation_penalty_yield)
        fee_on_liquidation_penalty_gap_pct     = max(0, fee_charged - fair_fee)
        net_return_after_fee_pct   = net_of_liquidation_penalty_yield - fee_charged
        net_return_fair_pct        = net_of_liquidation_penalty_yield - fair_fee
        overstatement_pct          = fee_on_liquidation_penalty_gap_pct
        fee_on_liquidation_penalty_fraction    = clamp(gap / fee_charged, 0, 1)
        realization_ratio          = clamp(net_after_fee / net_fair, 0, 1)

    The performance fee is charged on the gross yield; the fair fee would be
    charged only on the net-of-liquidation-penalty yield. When the
    net-of-liquidation-penalty yield equals (or exceeds) the gross yield the
    liquidation penalty consumed nothing and the performance fee was charged on
    the right base (CLEAN_NET_OF_LIQUIDATION_PENALTY_BASE). When the liquidation penalty
    consumed a large share of the yield, a large share of the performance fee was
    charged on the liquidation-penalty slice (MODERATE / SEVERE
    fee-on-liquidation-penalty gap), and if the fee exceeds the
    net-of-liquidation-penalty yield the net return goes negative.

    HIGHER score = the performance fee was charged on the net-of-liquidation-penalty
    base (gross ≈ net_of_liquidation_penalty), the fee was effectively fair, nothing
    to fix. LOWER score = a large share of the performance fee landed on the
    liquidation-penalty slice the depositor never realized, or the net return goes
    negative after the fee.

    Per-position input dict fields:
        vault / token                : str
        gross_yield_pct              : float — the GROSS yield (before the
                                       liquidation penalty is netted) on which the
                                       performance fee is assessed. REQUIRED, must
                                       be a finite POSITIVE number (else
                                       INSUFFICIENT_DATA).
        net_of_liquidation_penalty_yield_pct     : float — the yield NET OF the
                                       LIQUIDATION PENALTY (liquidator bonus +
                                       protocol liquidation fee)
                                       (finite; may be < gross; may be negative;
                                       default 0.0 = the liquidation penalty consumed
                                       the whole yield).
        performance_fee_pct          : float — performance-fee rate % (REQUIRED
                                       finite, clamped into 0..100; non-finite →
                                       INSUFFICIENT_DATA on the main path).
        liquidation_penalty_rate_pct             : float — OPTIONAL informational
                                       LIQUIDATION PENALTY as a % of position
                                       notional eroded over the window;
                                       ≥ HIGH_LIQUIDATION_PENALTY_PCT raises HIGH_LIQUIDATION_PENALTY
                                       flag.
        fee_on_liquidation_penalty_gap_pct       : float — OPTIONAL direct override of the
                                       fee-on-liquidation-penalty gap (the
                                       performance fee charged on the
                                       liquidation-penalty slice). When
                                       supplied (finite; negative → magnitude)
                                       AND a valid POSITIVE gross_yield_pct and
                                       POSITIVE fee_charged_pct are present, take
                                       this gap directly and skip the
                                       net-of-liquidation-penalty geometry (override
                                       path; geometry → None).
        fee_charged_pct              : float — OPTIONAL, only used on the override
                                       path as the denominator for
                                       fee_on_liquidation_penalty_fraction (finite > 0
                                       required to take the override path).
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

        # The gross yield is required and must be finite & positive.
        gross_gain = _coerce_num(p.get("gross_yield_pct"))
        if gross_gain is None or not math.isfinite(gross_gain) or gross_gain <= 0.0:
            return self._insufficient(token)

        liquidation_penalty_rate = _coerce_num(p.get("liquidation_penalty_rate_pct"))

        # Override path: a direct fee-on-liquidation-penalty gap + a positive fee_charged.
        gap_o = _coerce_num(p.get("fee_on_liquidation_penalty_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o, liquidation_penalty_rate)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(
            token, p, gross_gain, fee_pct, liquidation_penalty_rate)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        liquidation_penalty_rate: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        # net-of-liquidation-penalty yield may legitimately be negative (the
        # liquidation penalty exceeds the gross yield, or the strategy lost).
        net_gain = _coerce_signed(p.get("net_of_liquidation_penalty_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        liquidation_penalty_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        fee_on_liquidation_penalty_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_liquidation_penalty_yield_pct=net_gain,
            liquidation_penalty_consumed_yield_pct=liquidation_penalty_consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            fee_on_liquidation_penalty_gap_pct=fee_on_liquidation_penalty_gap_pct,
            liquidation_penalty_rate_pct=liquidation_penalty_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        liquidation_penalty_rate: Optional[float],
    ) -> dict:
        # The gap cannot exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # net-of-liquidation-penalty / liquidation-penalty-slice / fair geometry is unknown on the
        # override path → report None.
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_liquidation_penalty_yield_pct=None,
            liquidation_penalty_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            fee_on_liquidation_penalty_gap_pct=gap,
            liquidation_penalty_rate_pct=liquidation_penalty_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_liquidation_penalty_yield_pct: Optional[float],
        liquidation_penalty_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        fee_on_liquidation_penalty_gap_pct: float,
        liquidation_penalty_rate_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the performance fee charged on the liquidation-penalty slice.
        overstatement_pct = fee_on_liquidation_penalty_gap_pct

        # Net return: only computable when net-of-liquidation-penalty geometry is known.
        if net_of_liquidation_penalty_yield_pct is not None:
            net_return_after_fee_pct = (
                net_of_liquidation_penalty_yield_pct - fee_charged_pct)
            net_return_fair_pct = (
                net_of_liquidation_penalty_yield_pct - fair_fee_pct)
            net_is_negative = net_return_fair_pct < 0.0
            if net_return_fair_pct > EPS:
                realization_ratio = _clamp(
                    net_return_after_fee_pct / net_return_fair_pct, 0.0, 1.0)
            else:
                realization_ratio = (
                    1.0 if (net_return_after_fee_pct >= net_return_fair_pct
                            and net_return_after_fee_pct >= 0.0) else 0.0)
        else:
            net_return_after_fee_pct = None
            net_return_fair_pct = None
            net_is_negative = False
            realization_ratio = None

        # Scale-free fee-on-liquidation-penalty fraction — share of charged fee on the
        # liquidation-penalty slice.
        if fee_charged_pct > EPS:
            fee_on_liquidation_penalty_fraction = _clamp(
                fee_on_liquidation_penalty_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_liquidation_penalty_fraction = 0.0

        # Override path: anchor realisation on (1 - fee_on_liquidation_penalty_fraction).
        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_liquidation_penalty_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_liquidation_penalty_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_liquidation_penalty_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_liquidation_penalty_yield_pct,
            liquidation_penalty_consumed_yield_pct,
            gross_yield_pct,
            liquidation_penalty_rate_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_liquidation_penalty_yield_pct": (
                round(net_of_liquidation_penalty_yield_pct, 4)
                if net_of_liquidation_penalty_yield_pct is not None else None),
            "liquidation_penalty_consumed_yield_pct": (
                round(liquidation_penalty_consumed_yield_pct, 4)
                if liquidation_penalty_consumed_yield_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "fee_on_liquidation_penalty_gap_pct": round(fee_on_liquidation_penalty_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_liquidation_penalty_fraction": round(fee_on_liquidation_penalty_fraction, 4),
            "net_is_negative": net_is_negative,
            "liquidation_penalty_rate_pct": (
                round(liquidation_penalty_rate_pct, 4)
                if liquidation_penalty_rate_pct is not None else None),
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
        realization_ratio: float,
        fee_on_liquidation_penalty_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the performance fee was charged on the
        net-of-liquidation-penalty yield the depositor actually realized: the
        depositor keeps the yield that survived the liquidation penalty.
        Two components:
          * realisation = clamp(realization_ratio, 0, 1)
          * fee-base penalty = clamp(1 − fee_on_liquidation_penalty_fraction, 0, 1)
        Weighted 70/30 toward realisation.
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_liquidation_penalty_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_liquidation_penalty_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            return "SEVERE_FEE_ON_LIQUIDATION_PENALTY_GAP"
        if fee_on_liquidation_penalty_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_LIQUIDATION_PENALTY_BASE"
        if fee_on_liquidation_penalty_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_LIQUIDATION_PENALTY_GAP"
        if fee_on_liquidation_penalty_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_LIQUIDATION_PENALTY_GAP"
        return "SEVERE_FEE_ON_LIQUIDATION_PENALTY_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_LIQUIDATION_PENALTY"
        if classification == "CLEAN_NET_OF_LIQUIDATION_PENALTY_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_LIQUIDATION_PENALTY_GAP":
            return "MINOR_FEE_ON_LIQUIDATION_PENALTY"
        if classification == "MODERATE_FEE_ON_LIQUIDATION_PENALTY_GAP":
            return "DEMAND_NET_OF_LIQUIDATION_PENALTY_BASE"
        # SEVERE_FEE_ON_LIQUIDATION_PENALTY_GAP
        return "AVOID_FEE_ON_LIQUIDATION_PENALTY"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_liquidation_penalty_yield_pct: Optional[float],
        liquidation_penalty_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        liquidation_penalty_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        flags.append(classification)

        if classification == "CLEAN_NET_OF_LIQUIDATION_PENALTY_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (liquidation_penalty_rate_pct is not None
                and liquidation_penalty_rate_pct >= HIGH_LIQUIDATION_PENALTY_PCT):
            flags.append("HIGH_LIQUIDATION_PENALTY")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if (liquidation_penalty_consumed_yield_pct is not None
                    and liquidation_penalty_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_LIQUIDATION_PENALTY")
            if (net_of_liquidation_penalty_yield_pct is not None
                    and net_of_liquidation_penalty_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_LIQUIDATION_PENALTY")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_liquidation_penalty_yield_pct": None,
            "liquidation_penalty_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "fee_on_liquidation_penalty_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_liquidation_penalty_fraction": None,
            "net_is_negative": False,
            "liquidation_penalty_rate_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_LIQUIDATION_PENALTY",
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
                "worst_liquidation_penalty_gap_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_liquidation_penalty_gap_vault": by_score[0]["token"],
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
            # CLEAN_NET_OF_LIQUIDATION_PENALTY_BASE: net ≈ gross → a prudently
            # managed low-LTV leveraged vault took essentially no liquidation
            # penalty over a 15% annual yield, the performance fee was on the
            # right base.
            "vault": "USDC-LIQ-Vault-CleanLiquidationPenalty",
            "gross_yield_pct": 15.0,
            "net_of_liquidation_penalty_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "liquidation_penalty_rate_pct": 0.05,
        },
        {
            # MODERATE_FEE_ON_LIQUIDATION_PENALTY_GAP: gross 14, net 7 → ~half the
            # performance fee was charged on the liquidation-penalty slice
            # (fraction ≈ 0.5).
            "vault": "CRV-LIQ-Vault-ModerateLiquidationPenalty",
            "gross_yield_pct": 14.0,
            "net_of_liquidation_penalty_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "liquidation_penalty_rate_pct": 0.2,
        },
        {
            # SEVERE_FEE_ON_LIQUIDATION_PENALTY_GAP (net negative): the vault runs
            # a high-LTV leverage loop that is repeatedly liquidated in a volatile
            # window; the cumulative liquidator bonus + protocol liquidation fee
            # bled from collateral pushed net yield negative — yet the performance
            # fee is still charged on gross yield.
            "vault": "BAL-LIQ-Vault-SevereLiquidationPenalty",
            "gross_yield_pct": 10.0,
            "net_of_liquidation_penalty_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "liquidation_penalty_rate_pct": 0.6,
        },
        {
            # Override path: fee-on-liquidation-penalty gap supplied directly.
            # gap 4.8, fee_charged 12 → fraction 0.4 → MODERATE.
            "vault": "UNI-LIQ-Vault-OverrideLiquidationPenaltyGap",
            "gross_yield_pct": 20.0,
            "fee_on_liquidation_penalty_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_liquidation_penalty_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1241 Vault Performance-Fee Gross-Of-Liquidation-Penalty-Base Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeGrossOfLiquidationPenaltyBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
