"""
MP-1250: GrossOfLpAmmFeeDragAnalyzer
================================================================================
Advisory/read-only analytics module.

Many yield vaults route their harvest proceeds, rebalancing swaps, or
compounding operations through AMM liquidity pools (Uniswap V2/V3, Curve,
Balancer, SushiSwap, PancakeSwap, etc.). Each swap routed through these pools
incurs an LP FEE charged by the pool's liquidity providers — typically 0.01%
to 1% per swap on Uniswap V3 (depending on fee tier), variable on Curve
(0.04% base + admin), and dynamic on Balancer (swap fee set by pool owner).
Over many compounding / rebalancing cycles these LP fees accumulate into a
continuous drag on the vault's gross yield. This is NOT a one-off swap
slippage event, NOT a cross-chain bridge fee, NOT a flash-loan fee, and NOT
the base execution gas or priority tip of getting the transaction included.
Economically, the depositor's NET yield is:

    net_of_lp_amm_fee_yield = gross_yield - cumulative_lp_amm_fee_drag

But many vaults charge the performance fee on the GROSS yield (before netting
the cumulative LP AMM fee drag accrued over the measurement window from
routing swaps through AMM pools), not on the net-of-LP-fee yield the
depositor economically realized. The result is a "fee-on-LP-fee" / fee-base
inflation: the performance fee is levied on the yield slice the LP AMM fees
already erased. The fair performance fee would be levied only on the
net-of-LP-fee yield:

    fee_frac                        = clamp(performance_fee_pct / 100, 0, 1)
    lp_amm_fee_consumed_yield_pct   = max(0, gross_yield - net_of_lp_yield)
    fee_charged_pct                 = fee_frac * max(0, gross_yield)
    fair_fee_pct                    = fee_frac * max(0, net_of_lp_yield)
    lp_amm_fee_gap_pct              = max(0, fee_charged - fair_fee)
                                      (= performance fee charged on the LP-fee
                                       slice of the yield, which the depositor
                                       never received)
    net_return_after_fee_pct        = net_of_lp_yield - fee_charged
    net_return_fair_pct             = net_of_lp_yield - fair_fee
    overstatement_pct               = lp_amm_fee_gap_pct
    fee_on_lp_amm_fee_fraction      = clamp(gap / fee_charged, 0, 1)
    realization_ratio               = clamp(net_after_fee / net_fair, 0, 1)

The headline says "you only pay performance fees on profits", but when the
performance fee is charged on gross yield a chunk of the performance fee lands
on the LP-AMM-fee slice the depositor never received. The scale-free
fee_on_lp_amm_fee_fraction is the share of the charged performance fee that
landed on the LP-fee slice; it is the basis of the classification. When the
LP AMM fee drag consumed nothing (net_of_lp approx gross) the performance fee
was effectively fair (HIGHER score). When the LP fees consumed most of the
yield, the performance fee was charged almost entirely on the LP-fee slice
(LOWER score).

HIGHER score = the performance fee was charged on the net-of-LP-AMM-fee base
(gross approx net_of_lp), the fee was effectively fair, nothing to fix.
LOWER score = a large share of the performance fee landed on the LP-fee
slice, or the net return goes negative after the fee.

Override path (when lp_amm_fee_gap_pct is supplied directly, finite, AND a
valid POSITIVE gross_yield_pct and POSITIVE fee_charged_pct are present): take
the gap verbatim (negative -> magnitude) and skip the net-of-LP-fee geometry —
fee_on_lp_amm_fee_fraction and the metrics are computed the same way:

    fee_on_lp_amm_fee_fraction = clamp(gap / fee_charged_pct, 0, 1)

(On the override path the net-of-LP-fee / LP-fee-slice / fair geometry is not
known -> those fields are reported as None, and the geometry-only flags
FEE_ON_LP_AMM_FEE / FULL_FEE_ON_LP_AMM_FEE / NET_NEGATIVE_AFTER_FEE are NOT
raised; realization_ratio is anchored to (1 - fee_on_lp_amm_fee_fraction).)

Distinct from (this is the GROSS-OF-LP-AMM-FEE performance-fee BASE — the fee
being charged on the gross yield before the cumulative LP AMM FEE DRAG the
vault incurs by routing swaps through AMM liquidity pools (Uniswap V2/V3 /
Curve / Balancer) is netted out, not an automation-network upkeep fee, not
value extracted adversarially by mempool searchers, not base execution gas,
not another cost layer):
  * defi_protocol_vault_performance_fee_gross_of_swap_fee_base_gap_analyzer
    — that module prices a ONE-OFF discrete swap fee charged by a DEX
    aggregator or protocol-level swap router on a single trade event. HERE
    the LP AMM fee is the CUMULATIVE fee drag from the AMM POOL's liquidity
    providers over many compounding / rebalancing swaps routed through the
    pool over the measurement window — continuous drag, not a one-off event.
  * defi_protocol_vault_performance_fee_gross_of_keeper_fee /
    harvest_bounty / management_fee base gap analyzers
    — those price the automation-network upkeep charge, one-off harvest
    bounty, or protocol AUM fee. HERE it is the AMM liquidity-provider fee
    charged on swaps routed through the pool.
  * defi_protocol_vault_performance_fee_gross_of_priority_fee / blob_fee /
    l1_data_fee / bundler_fee / oracle_update_fee base gap analyzers
    — those price base execution gas / proposer tip / blob DA posting /
    L1 data fee / bundler premium / oracle pull-price fee. HERE it is the
    AMM LP fee, not a gas or infrastructure cost.
  * defi_protocol_vault_performance_fee_gross_of_bridge_fee /
    crosschain_message_fee / flash_loan_fee base gap analyzers
    — those price cross-chain transfer, messaging, or flash-loan premium.
    HERE it is the AMM LP swap fee on same-chain pool routing.
  * defi_protocol_vault_performance_fee_gross_of_insurance_fund_premium /
    reserve_contribution / borrow_cost / funding_cost /
    rebalancing_cost / mev_tax / exit_slippage base gap analyzers
    — those price insurance premium, protocol reserve, perp borrow/funding,
    aggregate turnover cost, MEV extraction, or exit price impact. None of
    those layers is the AMM LP fee charged by pool liquidity providers.
  * defi_protocol_vault_performance_fee_gross_of_impermanent_loss /
    slashing_loss / liquidation_penalty / bad_debt_socialization base gap
    analyzers — each prices a DIFFERENT value-loss layer. None is the LP
    AMM fee charged on routed swaps.
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer and related
    performance-fee mechanic modules — those measure HWM/crystallization
    fairness. HERE the axis is the fee-BASE inflation from charging the
    performance fee on gross (pre-LP-AMM-fee) yield, not HWM or
    crystallization mechanics.

The novel axis here: the performance-fee BASE being GROSS-OF-LP-AMM-FEE
rather than NET-OF-LP-AMM-FEE — a fee-on-LP-fee / fee-base inflation in
which the performance fee is charged on the slice of yield the cumulative LP
AMM FEE DRAG (from routing swaps through Uniswap V2/V3 / Curve / Balancer
pools) already consumed.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""
import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data",
    "vault_performance_fee_gross_of_lp_amm_fee_drag_log.json"
)
LOG_CAP = 100

CLEAN_FRACTION = 0.05
MILD_FRACTION = 0.20
MODERATE_FRACTION = 0.50

HIGH_LP_AMM_FEE_PCT = 0.25

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
    return _coerce_num(val)


def _coerce_count(val) -> Optional[int]:
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

class GrossOfLpAmmFeeDragAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the cumulative LP AMM FEE DRAG — the fees charged by AMM
    liquidity providers in pools like Uniswap V2/V3, Curve, and Balancer when
    the vault routes its harvest / rebalancing / compounding swaps through
    those pools — is netted out) and the FAIR fee it would charge on the
    NET-OF-LP-AMM-FEE yield the depositor economically realized, and the share
    of the charged performance fee that therefore landed on the LP-AMM-FEE
    slice of the yield (a fee-on-LP-fee / fee-base inflation).

        fee_frac                    = clamp(performance_fee_pct / 100, 0, 1)
        lp_amm_fee_consumed_yield   = max(0, gross_yield - net_of_lp_yield)
        fee_charged_pct             = fee_frac * max(0, gross_yield)
        fair_fee_pct                = fee_frac * max(0, net_of_lp_yield)
        lp_amm_fee_gap_pct          = max(0, fee_charged - fair_fee)
        net_return_after_fee_pct    = net_of_lp_yield - fee_charged
        net_return_fair_pct         = net_of_lp_yield - fair_fee
        overstatement_pct           = lp_amm_fee_gap_pct
        fee_on_lp_amm_fee_fraction  = clamp(gap / fee_charged, 0, 1)
        realization_ratio           = clamp(net_after_fee / net_fair, 0, 1)

    HIGHER score = the performance fee was charged on the net-of-LP-AMM-fee
    base (gross ≈ net_of_lp), effectively fair.
    LOWER score = a large share of the performance fee landed on the LP-fee
    slice the depositor never realized, or the net return goes negative.

    Per-position input dict fields:
        vault / token                   : str
        gross_yield_pct                 : float — GROSS yield before LP AMM fee
                                          drag. REQUIRED, finite POSITIVE.
        net_of_lp_amm_fee_yield_pct     : float — yield NET OF cumulative LP AMM
                                          fees. May be < gross, may be negative.
                                          Default 0.0.
        performance_fee_pct             : float — performance-fee rate %.
                                          REQUIRED on main path (finite).
        lp_amm_fee_rate_pct             : float — OPTIONAL informational LP AMM
                                          fee as % of position notional over
                                          the window. ≥ HIGH_LP_AMM_FEE_PCT
                                          raises HIGH_LP_AMM_FEE flag.
        lp_amm_fee_gap_pct              : float — OPTIONAL direct override of
                                          the fee-on-LP-fee gap.
        fee_charged_pct                 : float — OPTIONAL override denominator
                                          (finite > 0 to take override path).
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

        gross_gain = _coerce_num(p.get("gross_yield_pct"))
        if gross_gain is None or not math.isfinite(gross_gain) or gross_gain <= 0.0:
            return self._insufficient(token)

        lp_amm_fee_rate = _coerce_num(p.get("lp_amm_fee_rate_pct"))

        gap_o = _coerce_num(p.get("lp_amm_fee_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o, lp_amm_fee_rate)

        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(
            token, p, gross_gain, fee_pct, lp_amm_fee_rate)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        lp_amm_fee_rate: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        net_gain = _coerce_signed(p.get("net_of_lp_amm_fee_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        lp_amm_fee_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        lp_amm_fee_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_lp_amm_fee_yield_pct=net_gain,
            lp_amm_fee_consumed_yield_pct=lp_amm_fee_consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            lp_amm_fee_gap_pct=lp_amm_fee_gap_pct,
            lp_amm_fee_rate_pct=lp_amm_fee_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        lp_amm_fee_rate: Optional[float],
    ) -> dict:
        gap = min(gap, fee_charged)
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_lp_amm_fee_yield_pct=None,
            lp_amm_fee_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            lp_amm_fee_gap_pct=gap,
            lp_amm_fee_rate_pct=lp_amm_fee_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_lp_amm_fee_yield_pct: Optional[float],
        lp_amm_fee_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        lp_amm_fee_gap_pct: float,
        lp_amm_fee_rate_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        overstatement_pct = lp_amm_fee_gap_pct

        if net_of_lp_amm_fee_yield_pct is not None:
            net_return_after_fee_pct = (
                net_of_lp_amm_fee_yield_pct - fee_charged_pct)
            net_return_fair_pct = (
                net_of_lp_amm_fee_yield_pct - fair_fee_pct)
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

        if fee_charged_pct > EPS:
            fee_on_lp_amm_fee_fraction = _clamp(
                lp_amm_fee_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_lp_amm_fee_fraction = 0.0

        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_lp_amm_fee_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_lp_amm_fee_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_lp_amm_fee_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_lp_amm_fee_yield_pct,
            lp_amm_fee_consumed_yield_pct,
            gross_yield_pct,
            lp_amm_fee_rate_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_lp_amm_fee_yield_pct": (
                round(net_of_lp_amm_fee_yield_pct, 4)
                if net_of_lp_amm_fee_yield_pct is not None else None),
            "lp_amm_fee_consumed_yield_pct": (
                round(lp_amm_fee_consumed_yield_pct, 4)
                if lp_amm_fee_consumed_yield_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "lp_amm_fee_gap_pct": round(lp_amm_fee_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_lp_amm_fee_fraction": round(fee_on_lp_amm_fee_fraction, 4),
            "net_is_negative": net_is_negative,
            "lp_amm_fee_rate_pct": (
                round(lp_amm_fee_rate_pct, 4)
                if lp_amm_fee_rate_pct is not None else None),
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
        fee_on_lp_amm_fee_fraction: float,
        classification: str,
    ) -> float:
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_lp_amm_fee_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_lp_amm_fee_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            return "SEVERE_FEE_ON_LP_AMM_FEE_GAP"
        if fee_on_lp_amm_fee_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_LP_AMM_FEE_BASE"
        if fee_on_lp_amm_fee_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_LP_AMM_FEE_GAP"
        if fee_on_lp_amm_fee_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_LP_AMM_FEE_GAP"
        return "SEVERE_FEE_ON_LP_AMM_FEE_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_LP_AMM_FEE"
        if classification == "CLEAN_NET_OF_LP_AMM_FEE_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_LP_AMM_FEE_GAP":
            return "MINOR_FEE_ON_LP_AMM_FEE"
        if classification == "MODERATE_FEE_ON_LP_AMM_FEE_GAP":
            return "DEMAND_NET_OF_LP_AMM_FEE_BASE"
        return "AVOID_FEE_ON_LP_AMM_FEE"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_lp_amm_fee_yield_pct: Optional[float],
        lp_amm_fee_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        lp_amm_fee_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        flags.append(classification)

        if classification == "CLEAN_NET_OF_LP_AMM_FEE_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (lp_amm_fee_rate_pct is not None
                and lp_amm_fee_rate_pct >= HIGH_LP_AMM_FEE_PCT):
            flags.append("HIGH_LP_AMM_FEE")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            if (lp_amm_fee_consumed_yield_pct is not None
                    and lp_amm_fee_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_LP_AMM_FEE")
            if (net_of_lp_amm_fee_yield_pct is not None
                    and net_of_lp_amm_fee_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_LP_AMM_FEE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_lp_amm_fee_yield_pct": None,
            "lp_amm_fee_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "lp_amm_fee_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_lp_amm_fee_fraction": None,
            "net_is_negative": False,
            "lp_amm_fee_rate_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_LP_AMM_FEE",
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
                "worst_lp_amm_fee_gap_vault": None,
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
            "worst_lp_amm_fee_gap_vault": by_score[0]["token"],
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
            "vault": "USDC-LP-Vault-CleanLpFee",
            "gross_yield_pct": 15.0,
            "net_of_lp_amm_fee_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "lp_amm_fee_rate_pct": 0.03,
        },
        {
            "vault": "CRV-LP-Vault-ModerateLpFee",
            "gross_yield_pct": 14.0,
            "net_of_lp_amm_fee_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "lp_amm_fee_rate_pct": 0.15,
        },
        {
            "vault": "BAL-LP-Vault-SevereLpFee",
            "gross_yield_pct": 10.0,
            "net_of_lp_amm_fee_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "lp_amm_fee_rate_pct": 0.5,
        },
        {
            "vault": "UNI-LP-Vault-OverrideLpFeeGap",
            "gross_yield_pct": 20.0,
            "lp_amm_fee_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_lp_amm_fee_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1250 Vault Performance-Fee Gross-Of-LP-AMM-Fee-Drag Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = GrossOfLpAmmFeeDragAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
