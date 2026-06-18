"""
MP-1227: DeFiProtocolVaultPerformanceFeeGrossOfWithdrawalFeeBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

A vault's strategy must periodically REDEEM / ROTATE its position out of an
underlying protocol that charges an explicit recurring PERCENTAGE WITHDRAWAL /
REDEMPTION / UNSTAKE FEE on every realization — e.g. an LST/LSD that takes an
instant-unstake fee on each exit, a lending or money-market that charges a
redemption fee, an algo-stable or structured-product vault that levies a
withdrawal/redemption cut, an exit/redemption fee a meta-vault pays its
underlying vault each time it harvests by redeeming shares. Each period the
strategy realizes its yield only by redeeming, so it pays
withdrawal_rate × yield × intervals (a PERCENTAGE cut of the realized yield
skimmed by the underlying protocol's redemption fee BEFORE the remainder reaches
the depositor). The vault earns a GROSS yield, but the depositor's economically
realized yield is the yield NET OF the recurring withdrawal fee
(gross_yield − withdrawal_fee). That withdrawal fee is a real cash outflow the
depositor actually bears but does NOT see as spendable yield this period. The
vault charges its PERFORMANCE fee on the GROSS yield (BEFORE netting the
withdrawal fee), not on the NET-OF-WITHDRAWAL-FEE yield the depositor
economically realized. So the depositor pays a performance fee on the very slice
of yield the withdrawal fee already erased — a "fee-on-withdrawal-fee" /
fee-base inflation. The fee is levied on the gross yield; the FAIR fee would be
levied only on the net-of-withdrawal-fee yield:

    fee_frac                          = clamp(performance_fee_pct / 100, 0, 1)
    withdrawal_fee_consumed_yield_pct  = max(0, gross_yield - net_of_withdrawal_fee_yield)
    fee_charged_pct                   = fee_frac * max(0, gross_yield)
    fair_fee_pct                      = fee_frac * max(0, net_of_withdrawal_fee_yield)
    fee_on_withdrawal_fee_gap_pct    = max(0, fee_charged - fair_fee)
                                      (= performance fee charged on the
                                       withdrawal-fee slice of the yield, which
                                       the depositor never received)
    net_return_after_fee_pct          = net_of_withdrawal_fee_yield - fee_charged
    net_return_fair_pct               = net_of_withdrawal_fee_yield - fair_fee
    overstatement_pct                 = fee_on_withdrawal_fee_gap_pct
    fee_on_withdrawal_fee_fraction   = clamp(gap / fee_charged, 0, 1)
    realization_ratio                 = clamp(net_after_fee / net_fair, 0, 1)

The headline says "you only pay a performance fee on what you earned", but with
the performance fee charged on the gross yield the fee is taken on the whole
pre-withdrawal-fee yield while the depositor only ever realized the
net-of-withdrawal-fee slice — so a chunk of the performance fee landed on the
withdrawal-fee slice the redemption fee already erased. The scale-free
fee_on_withdrawal_fee_fraction is the share of the charged performance fee
that landed on the withdrawal-fee slice; it is the basis of the
classification. When the withdrawal fee consumed nothing
(net_of_withdrawal_fee ≈ gross) there was no withdrawal-fee slice and the
performance fee was fair (HIGHER score). When the withdrawal fee consumed most
of the yield (net_of_withdrawal_fee ≈ 0 or the net return goes negative after
the fee), the performance fee was charged almost entirely on the
withdrawal-fee slice (LOWER score).

HIGHER score = the performance fee was charged on the net-of-withdrawal-fee
base (gross ≈ net_of_withdrawal_fee), the fee was effectively fair, nothing to
fix.
LOWER score = a large share of the performance fee landed on the
withdrawal-fee slice, or the net return goes negative after the fee.

Override path (when fee_on_withdrawal_fee_gap_pct is supplied directly,
finite, AND a valid POSITIVE gross_yield_pct and POSITIVE fee_charged_pct are
present): take the gap verbatim (negative → magnitude) and skip the
net-of-withdrawal-fee geometry — fee_on_withdrawal_fee_fraction
and the metrics are computed the same way:

    fee_on_withdrawal_fee_fraction = clamp(gap / fee_charged_pct, 0, 1)

(On the override path the net-of-withdrawal-fee / withdrawal-fee-slice /
fair geometry is not known → those fields are reported as None, and the
geometry-only flags FEE_ON_WITHDRAWAL_FEE / FULL_FEE_ON_WITHDRAWAL_FEE /
NET_NEGATIVE_AFTER_FEE are NOT raised; realization_ratio is anchored to
(1 - fee_on_withdrawal_fee_fraction).)

Distinct from (this is the GROSS-OF-WITHDRAWAL-FEE performance-fee BASE — the
fee being charged on the gross yield before the recurring withdrawal fee is
netted out, not the withdrawal fee itself nor an external/internal fee layer):
  * the other gross_of_* perf-fee modules
    (defi_protocol_vault_performance_fee_gross_of_cost_base_gap_analyzer,
    ..._gross_of_borrow_cost_base_gap_analyzer,
    ..._gross_of_rebalancing_cost_base_gap_analyzer,
    ..._gross_of_exit_slippage_base_gap_analyzer,
    ..._gross_of_funding_cost_base_gap_analyzer,
    ..._gross_of_reserve_contribution_base_gap_analyzer,
    ..._gross_of_impermanent_loss_base_gap_analyzer,
    ..._gross_of_bad_debt_socialization_base_gap_analyzer,
    ..._gross_of_bridge_fee_base_gap_analyzer,
    ..._protocol_revenue_share_base_gap_analyzer,
    ..._management_fee_base_gap_analyzer) — each prices the perf-fee charged on a
    DIFFERENT erosion layer of the return (fixed gas/keeper-TX cost,
    lending-market borrow interest, swap turnover on rebalances, a ONE-OFF
    principal exit slippage, a perpetual funding carry, an internal reserve
    buffer, the LP's impermanent/divergence loss, a socialized bad-debt haircut,
    a cross-chain bridge transport fee, an external protocol's revenue-share cut,
    the vault's own management-fee layer).
    NONE of those layers is a recurring PERCENTAGE WITHDRAWAL / REDEMPTION /
    UNSTAKE FEE charged by the underlying protocol on every realization the
    strategy must redeem through. The key difference from
    gross_of_exit_slippage: there the eroding layer is a ONE-OFF, MARKET-DRIVEN
    price impact on a single principal exit (slippage against AMM/orderbook
    depth, not a posted fee); HERE it is an EXPLICIT, DETERMINISTIC protocol-set
    PERCENTAGE redemption fee taken on EVERY recurring realization, not a one-off
    market move. The key difference from gross_of_protocol_revenue_share: there
    the eroding layer is the PROTOCOL'S OWN INTERNAL cut of the yield to its own
    treasury; HERE it is a posted redemption fee on the value being WITHDRAWN, not
    a revenue-share on the yield earned. The key difference from
    gross_of_harvest_bounty: there the eroding layer is a PER-HARVEST caller
    reward paid to a keeper to trigger the harvest TX; HERE it is the redemption
    fee charged by the underlying on the exit itself, independent of any keeper.
    The key difference from gross_of_management_fee: there the eroding layer is an
    AUM-based management fee (a % of PRINCIPAL accrued over time); HERE it is a %
    of the realized YIELD taken at the moment of withdrawal. The key difference
    from gross_of_bridge_fee: there the eroding layer is the CROSS-CHAIN transport
    cut for moving value BETWEEN chains; HERE it is a SAME-PROTOCOL redemption fee
    on the exit, independent of any cross-chain transport. The key difference from
    gross_of_boost_fee: there the eroding layer is an external boost-provider
    PLATFORM fee on AMPLIFIED gauge emissions; HERE it is the redemption fee on
    the WITHDRAWAL, independent of any boost. The key difference from
    gross_of_cost: there the eroding layer is a FIXED gas / keeper-TX NETWORK cost
    (a flat denominated amount that does NOT scale with the yield); HERE it is a
    PERCENTAGE withdrawal fee of the yield (withdrawal_rate × yield × intervals) —
    it scales with the yield, not the gas price. The key difference from
    gross_of_funding_cost: there the eroding layer is the periodic PERP FUNDING
    payment on a notional perp/short position of a delta-neutral / basis hedge;
    HERE it is the percentage redemption fee on the exit, independent of any
    hedge. The key difference from gross_of_borrow_cost: there the eroding layer
    is INTEREST on a debt drawn from a lending market; HERE it is the withdrawal
    fee, independent of any debt. The key difference from
    gross_of_rebalancing_cost: there the eroding layer is the SWAP turnover from
    rotating the portfolio WITHIN the position; HERE it is the protocol's posted
    redemption fee on EXITING the position, not an AMM swap. NONE of these is the
    withdrawal fee: NOT borrow_cost, rebalancing_cost, exit_slippage,
    funding_cost, insurance_premium, slashing_loss, reserve_contribution,
    impermanent_loss, bad_debt_socialization, referral_fee, bridge_fee, boost_fee
    or validator_commission erosion layers either.
  * defi_protocol_vault_withdrawal_fee_decay_analyzer — that prices a
    TIME-DECAYING withdrawal-fee SCHEDULE (an early-exit fee that tapers with
    holding time) to inform the hold-time / exit-timing decision. HERE the axis
    is the performance-fee BASE inflation from charging the perf fee on the gross
    (pre-withdrawal-fee) yield, NOT the withdrawal fee's time schedule or the
    exit-timing decision itself.
  * defi_protocol_vault_harvest_timing_analyzer,
    defi_protocol_vault_harvest_cycle_entry_timing_analyzer,
    defi_reward_harvesting_optimizer and
    defi_protocol_yield_harvesting_frequency_optimizer — those measure WHEN /
    HOW OFTEN to harvest (the timing, frequency and concentration of the
    harvest itself). HERE the axis is the performance-fee BASE inflation from
    charging the fee on the gross (pre-withdrawal-fee) yield, NOT the harvest
    timing or the size of the withdrawal fee itself.
  * net_of_loss_yield_realization — that nets a general realized-loss stream
    ACROSS epochs (multi-period loss carry). HERE it is the perf-fee BASE for a
    SINGLE period: the static gap between the gross base and the
    net-of-withdrawal-fee base.
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer — that prices
    the mechanics of the HWM RESET over TIME for the WHOLE NAV series. HERE it is
    the static gap between the GROSS base and the NET-OF-WITHDRAWAL-FEE base
    for a SINGLE fee period.
  * defi_protocol_vault_performance_fee_volatility_tax_analyzer — that prices the
    PATH asymmetry of a HWM fee over a VOLATILE gross path. HERE there is no
    path: it is the static gap between the gross yield and the yield net of the
    recurring withdrawal fee.
  * defi_protocol_performance_fee_crystallization_frequency_analyzer — that
    prices how OFTEN the fee crystallises. HERE it is what the fee is assessed
    ACROSS (gross yield vs the net-of-withdrawal-fee slice), regardless of
    frequency.
  * defi_protocol_vault_performance_fee_hurdle_rate_gap_analyzer — that prices
    the fee charged on BETA (benchmark-level return over a too-low hurdle) vs
    ALPHA. HERE it is the fee charged on the withdrawal-fee slice of the
    yield, independent of any benchmark.
  * defi_protocol_vault_performance_fee_catch_up_clause_gap_analyzer — that
    prices the catch-up clause clawing back the hurdle exemption. HERE it is the
    static gross-of-withdrawal-fee base, independent of any hurdle/catch-up.

The novel axis here: the performance-fee BASE being GROSS-OF-WITHDRAWAL-FEE
rather than NET-OF-WITHDRAWAL-FEE — a fee-on-withdrawal-fee / fee-base
inflation in which the performance fee is charged on the slice of yield the
recurring withdrawal fee already erased.

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
    "data", "vault_performance_fee_gross_of_withdrawal_fee_base_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free fee_on_withdrawal_fee_fraction
# in [0, 1] (= fee_on_withdrawal_fee_gap_pct / fee_charged_pct).
CLEAN_FRACTION = 0.05        # at/below → cleanly on the net-of-withdrawal-fee base
MILD_FRACTION = 0.20         # at/below → mild fee-on-withdrawal-fee gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe gap

# High-withdrawal-fee flag threshold on withdrawal_fee_cost_pct.
HIGH_WITHDRAWAL_FEE_PCT = 10.0

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
    net-of-withdrawal-fee-yield field, which may legitimately be negative.
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

class DeFiProtocolVaultPerformanceFeeGrossOfWithdrawalFeeBaseGapAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the recurring withdrawal fee is netted out) and the FAIR
    fee it would charge on the NET-OF-WITHDRAWAL-FEE yield the depositor
    economically realized, and the share of the charged performance fee that
    therefore landed on the WITHDRAWAL-FEE slice of the yield (a
    fee-on-withdrawal-fee / fee-base inflation).

        fee_frac               = clamp(performance_fee_pct / 100, 0, 1)
        withdrawal_fee_consumed_yield_pct = max(0, gross_yield - net_of_withdrawal_fee_yield)
        fee_charged_pct        = fee_frac * max(0, gross_yield)
        fair_fee_pct           = fee_frac * max(0, net_of_withdrawal_fee_yield)
        fee_on_withdrawal_fee_gap_pct = max(0, fee_charged - fair_fee)
        net_return_after_fee_pct = net_of_withdrawal_fee_yield - fee_charged
        net_return_fair_pct      = net_of_withdrawal_fee_yield - fair_fee
        overstatement_pct      = fee_on_withdrawal_fee_gap_pct
        fee_on_withdrawal_fee_fraction = clamp(gap / fee_charged, 0, 1)
        realization_ratio      = clamp(net_after_fee / net_fair, 0, 1)

    The performance fee is charged on the gross yield; the fair fee would be
    charged only on the net-of-withdrawal-fee yield. When the
    net-of-withdrawal-fee yield equals (or exceeds) the gross yield the
    withdrawal fee consumed nothing and the performance fee was charged on the
    right base (CLEAN_NET_OF_WITHDRAWAL_FEE_BASE). When the withdrawal fee
    consumed a large share of the yield, a large share of the performance fee was
    charged on the withdrawal-fee slice (MODERATE / SEVERE
    fee-on-withdrawal-fee gap), and if the fee exceeds the
    net-of-withdrawal-fee yield the net return goes negative.

    HIGHER score = the performance fee was charged on the
    net-of-withdrawal-fee base (gross ≈ net_of_withdrawal_fee), the fee was
    effectively fair, nothing to fix.
    LOWER score = a large share of the performance fee landed on the
    withdrawal-fee slice the depositor never realized, or the net return goes
    negative after the fee.

    Per-position input dict fields:
        vault / token                  : str
        gross_yield_pct                : float — the GROSS yield (before the
                                         recurring withdrawal fee is netted)
                                         on which the performance fee is assessed.
                                         REQUIRED, must be a finite POSITIVE number
                                         (else INSUFFICIENT_DATA).
        net_of_withdrawal_fee_yield_pct  : float — the yield NET OF the
                                         withdrawal fee (finite; may be <
                                         gross; may be negative; default 0.0 = the
                                         withdrawal fee consumed the whole
                                         yield).
        performance_fee_pct            : float — performance-fee rate % (REQUIRED
                                         finite, clamped into 0..100; non-finite →
                                         INSUFFICIENT_DATA on the main path).
        withdrawal_fee_cost_pct      : float — OPTIONAL informational underlying
                                         redemption / withdrawal fee rate %;
                                         ≥ HIGH_WITHDRAWAL_FEE_PCT raises
                                         HIGH_WITHDRAWAL_FEE.
        fee_on_withdrawal_fee_gap_pct  : float — OPTIONAL direct override of the
                                         fee-on-withdrawal-fee gap (the
                                         performance fee charged on the
                                         withdrawal-fee slice). When
                                         supplied (finite; negative → magnitude)
                                         AND a valid POSITIVE gross_yield_pct and
                                         POSITIVE fee_charged_pct are present, take
                                         this gap directly and skip the
                                         net-of-withdrawal-fee
                                         geometry (override path; geometry → None).
        fee_charged_pct                : float — OPTIONAL, only used on the override
                                         path as the denominator for
                                         fee_on_withdrawal_fee_fraction (finite >
                                         0 required to take the override path).
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

        withdrawal_fee_rate = _coerce_num(p.get("withdrawal_fee_cost_pct"))

        # Override path: a direct fee-on-withdrawal-fee gap + a positive
        # fee_charged.
        gap_o = _coerce_num(p.get("fee_on_withdrawal_fee_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o,
                withdrawal_fee_rate)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(
            token, p, gross_gain, fee_pct, withdrawal_fee_rate)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        withdrawal_fee_rate: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        # net-of-withdrawal-fee yield may legitimately be negative (the
        # withdrawal fee exceeds the gross yield, or the strategy lost).
        net_gain = _coerce_signed(p.get("net_of_withdrawal_fee_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        withdrawal_fee_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        fee_on_withdrawal_fee_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_withdrawal_fee_yield_pct=net_gain,
            withdrawal_fee_consumed_yield_pct=withdrawal_fee_consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            fee_on_withdrawal_fee_gap_pct=fee_on_withdrawal_fee_gap_pct,
            withdrawal_fee_cost_pct=withdrawal_fee_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        withdrawal_fee_rate: Optional[float],
    ) -> dict:
        # The gap can not exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # net-of-withdrawal-fee / withdrawal-fee-slice / fair geometry is
        # unknown on the override path → report None; net return can not be
        # derived without net_of_withdrawal_fee_yield, so net-negative /
        # full-fee-on-withdrawal-fee flags / ratio fall back to the gap share.
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_withdrawal_fee_yield_pct=None,
            withdrawal_fee_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            fee_on_withdrawal_fee_gap_pct=gap,
            withdrawal_fee_cost_pct=withdrawal_fee_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_withdrawal_fee_yield_pct: Optional[float],
        withdrawal_fee_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        fee_on_withdrawal_fee_gap_pct: float,
        withdrawal_fee_cost_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the performance fee charged on the withdrawal-fee
        # slice (kept for family consistency with the headline-honesty family).
        overstatement_pct = fee_on_withdrawal_fee_gap_pct

        # Net return: only computable when net-of-withdrawal-fee geometry is
        # known.
        if net_of_withdrawal_fee_yield_pct is not None:
            net_return_after_fee_pct = (
                net_of_withdrawal_fee_yield_pct - fee_charged_pct)
            net_return_fair_pct = (
                net_of_withdrawal_fee_yield_pct - fair_fee_pct)
            net_is_negative = net_return_fair_pct < 0.0
            if net_return_fair_pct > EPS:
                realization_ratio = _clamp(
                    net_return_after_fee_pct / net_return_fair_pct, 0.0, 1.0)
            else:
                # Mirror the hurdle/clawback template edge: when the fair net is
                # non-positive, the ratio is 1.0 only if the charged net still
                # clears the fair net and is itself non-negative, else 0.0.
                realization_ratio = (
                    1.0 if (net_return_after_fee_pct >= net_return_fair_pct
                            and net_return_after_fee_pct >= 0.0) else 0.0)
        else:
            # Override path: net-of-withdrawal-fee geometry unknown. Treat
            # realisation via the fee-on-withdrawal-fee share as the proxy
            # below; flag as not known.
            net_return_after_fee_pct = None
            net_return_fair_pct = None
            net_is_negative = False
            realization_ratio = None

        # Scale-free fee-on-withdrawal-fee fraction — the share of the charged
        # performance fee that landed on the withdrawal-fee slice.
        if fee_charged_pct > EPS:
            fee_on_withdrawal_fee_fraction = _clamp(
                fee_on_withdrawal_fee_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_withdrawal_fee_fraction = 0.0

        # On the override path, with no net-of-withdrawal-fee geometry, anchor
        # the realisation on (1 - fee_on_withdrawal_fee_fraction): the share
        # of the fee that fell on the net-of-withdrawal-fee yield is the share
        # the depositor "paid fairly".
        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_withdrawal_fee_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_withdrawal_fee_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_withdrawal_fee_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_withdrawal_fee_yield_pct,
            withdrawal_fee_consumed_yield_pct,
            gross_yield_pct,
            withdrawal_fee_cost_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_withdrawal_fee_yield_pct": (
                round(net_of_withdrawal_fee_yield_pct, 4)
                if net_of_withdrawal_fee_yield_pct is not None else None),
            "withdrawal_fee_consumed_yield_pct": (
                round(withdrawal_fee_consumed_yield_pct, 4)
                if withdrawal_fee_consumed_yield_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "fee_on_withdrawal_fee_gap_pct": round(
                fee_on_withdrawal_fee_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_withdrawal_fee_fraction": round(
                fee_on_withdrawal_fee_fraction, 4),
            "net_is_negative": net_is_negative,
            "withdrawal_fee_cost_pct": (
                round(withdrawal_fee_cost_pct, 4)
                if withdrawal_fee_cost_pct is not None else None),
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
        fee_on_withdrawal_fee_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the performance fee was charged on the
        net-of-withdrawal-fee yield the depositor actually realized: the
        depositor keeps the yield that survived the recurring withdrawal fee.
        Two components:
          * realisation = clamp(realization_ratio, 0, 1) — the fraction of the
            fair net return that survives the gross-based fee,
          * fee-base penalty = clamp(1 − fee_on_withdrawal_fee_fraction, 0, 1)
            — penalises a large share of the fee being charged on the
            withdrawal-fee slice.
        Weighted 70/30 toward realisation (it directly maps to the net return the
        depositor keeps).
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_withdrawal_fee_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_withdrawal_fee_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            # The fee has eaten the whole net-of-withdrawal-fee yield (or
            # more).
            return "SEVERE_FEE_ON_WITHDRAWAL_FEE_GAP"
        if fee_on_withdrawal_fee_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_WITHDRAWAL_FEE_BASE"
        if fee_on_withdrawal_fee_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_WITHDRAWAL_FEE_GAP"
        if fee_on_withdrawal_fee_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_WITHDRAWAL_FEE_GAP"
        return "SEVERE_FEE_ON_WITHDRAWAL_FEE_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_WITHDRAWAL_FEE"
        if classification == "CLEAN_NET_OF_WITHDRAWAL_FEE_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_WITHDRAWAL_FEE_GAP":
            return "MINOR_FEE_ON_WITHDRAWAL_FEE"
        if classification == "MODERATE_FEE_ON_WITHDRAWAL_FEE_GAP":
            return "DEMAND_NET_OF_WITHDRAWAL_FEE_BASE"
        # SEVERE_FEE_ON_WITHDRAWAL_FEE_GAP
        return "AVOID_FEE_ON_WITHDRAWAL_FEE"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_withdrawal_fee_yield_pct: Optional[float],
        withdrawal_fee_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        withdrawal_fee_cost_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        # Classification flag.
        flags.append(classification)

        if classification == "CLEAN_NET_OF_WITHDRAWAL_FEE_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (withdrawal_fee_cost_pct is not None
                and withdrawal_fee_cost_pct >= HIGH_WITHDRAWAL_FEE_PCT):
            flags.append("HIGH_WITHDRAWAL_FEE")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if (withdrawal_fee_consumed_yield_pct is not None
                    and withdrawal_fee_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_WITHDRAWAL_FEE")
            if (net_of_withdrawal_fee_yield_pct is not None
                    and net_of_withdrawal_fee_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_WITHDRAWAL_FEE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_withdrawal_fee_yield_pct": None,
            "withdrawal_fee_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "fee_on_withdrawal_fee_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_withdrawal_fee_fraction": None,
            "net_is_negative": False,
            "withdrawal_fee_cost_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_WITHDRAWAL_FEE",
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
                "worst_withdrawal_fee_gap_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
            }
        # Higher score = charged on the net-of-withdrawal-fee base / fee fair
        # → highest score is the cleanest vault.
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_withdrawal_fee_gap_vault": by_score[0]["token"],
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
            # CLEAN_NET_OF_WITHDRAWAL_FEE_BASE: net_of_withdrawal_fee ≈
            # gross → the withdrawal fee consumed nothing, the performance fee
            # was charged on the right base.
            "vault": "USDC-Vault-CleanNetBase",
            "gross_yield_pct": 18.0,
            "net_of_withdrawal_fee_yield_pct": 18.0,
            "performance_fee_pct": 20.0,
            "withdrawal_fee_cost_pct": 0.0,
        },
        {
            # MODERATE_FEE_ON_WITHDRAWAL_FEE_GAP: gross 16, net 8 → ~half the
            # fee was charged on the withdrawal-fee slice (fraction ~ 0.5).
            "vault": "AAVE-Vault-ModerateWithdrawalFee",
            "gross_yield_pct": 16.0,
            "net_of_withdrawal_fee_yield_pct": 8.0,
            "performance_fee_pct": 20.0,
            "withdrawal_fee_cost_pct": 12.0,
        },
        {
            # SEVERE_FEE_ON_WITHDRAWAL_FEE_GAP (net negative): the withdrawal
            # fee drove the net-of-withdrawal-fee yield negative, yet the
            # performance fee is still charged on the gross yield → fair net
            # return is negative.
            "vault": "CRV-Vault-SevereWithdrawalFee",
            "gross_yield_pct": 12.0,
            "net_of_withdrawal_fee_yield_pct": -3.0,
            "performance_fee_pct": 50.0,
            "withdrawal_fee_cost_pct": 15.0,
        },
        {
            # Override path: a fee-on-withdrawal-fee gap supplied directly with
            # the fee charged → fraction = 5/12 ≈ 0.4167 → MODERATE.
            "vault": "LST-Vault-OverrideGap",
            "gross_yield_pct": 24.0,
            "fee_on_withdrawal_fee_gap_pct": 5.0,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_withdrawal_fee_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1227 Vault Performance-Fee Gross-Of-Withdrawal-Fee-Base "
            "Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeGrossOfWithdrawalFeeBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
