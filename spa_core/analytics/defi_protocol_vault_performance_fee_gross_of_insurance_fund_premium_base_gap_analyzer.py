"""
MP-1244: DeFiProtocolVaultPerformanceFeeGrossOfInsuranceFundPremiumBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

Many yield vaults buy continuous slashing/hack COVER for their deposits: they
pay an ongoing INSURANCE FUND PREMIUM out to a safety module or external cover
provider — staked-token Safety Module (e.g. Aave's stkAAVE module), a mutual /
cover protocol (Nexus Mutual, Sherlock), or a protocol-owned insurance fund —
in exchange for the fund backstopping depositor losses if the vault is hacked,
its underlying is slashed, or a covered shortfall is realized. That premium is a
continuous skim PAID OUT of the vault's gross yield to the cover provider /
safety-module stakers, taken before the depositor sees anything. It is NOT the
protocol reserve factor RETAINED as the protocol's own revenue, NOT residual bad
debt socialised across depositors after a failed liquidation, NOT the actual
slashing event, and NOT a gas / messaging / oracle / keeper layer. Economically,
the depositor's NET yield is:

    net_of_insurance_fund_premium_yield = gross_yield - insurance_fund_premium

But many vaults charge the performance fee on the GROSS yield (before netting
the INSURANCE FUND PREMIUM — the continuous cover premium paid out to the safety
module / cover provider during the measurement window), not on the
net-of-insurance-fund-premium yield the depositor economically realized. The
result is a "fee-on-insurance-fund-premium" / fee-base inflation: the performance
fee is levied on the yield slice the insurance fund premium already erased. The
fair performance fee would be levied only on the net-of-insurance-fund-premium
yield:

    fee_frac                              = clamp(performance_fee_pct / 100, 0, 1)
    insurance_fund_premium_consumed_yield_pct  = max(0, gross_yield - net_of_ifp_yield)
    fee_charged_pct                       = fee_frac * max(0, gross_yield)
    fair_fee_pct                          = fee_frac * max(0, net_of_ifp_yield)
    fee_on_insurance_fund_premium_gap_pct      = max(0, fee_charged - fair_fee)
                                            (= performance fee charged on the
                                             insurance-fund-premium slice of the yield,
                                             which the depositor never received)
    net_return_after_fee_pct              = net_of_ifp_yield - fee_charged
    net_return_fair_pct                   = net_of_ifp_yield - fair_fee
    overstatement_pct                     = fee_on_insurance_fund_premium_gap_pct
    fee_on_insurance_fund_premium_fraction     = clamp(gap / fee_charged, 0, 1)
    realization_ratio                     = clamp(net_after_fee / net_fair, 0, 1)

The headline says "you only pay performance fees on profits", but when the
performance fee is charged on gross yield a chunk of the performance fee lands
on the insurance-fund-premium slice the depositor never received. The scale-free
fee_on_insurance_fund_premium_fraction is the share of the charged performance fee
that landed on the insurance-fund-premium slice; it is the basis of the
classification. When the insurance fund premium consumed nothing (net_of_ifp
approx gross) the performance fee was effectively fair (HIGHER score). When the
insurance fund premium consumed most of the yield, the performance fee was charged
almost entirely on the insurance-fund-premium slice (LOWER score).

HIGHER score = the performance fee was charged on the net-of-insurance-fund-premium
base (gross approx net_of_ifp), the fee was effectively fair, nothing to fix.
LOWER score = a large share of the performance fee landed on the
insurance-fund-premium slice, or the net return goes negative after the fee.

Override path (when fee_on_insurance_fund_premium_gap_pct is supplied directly,
finite, AND a valid POSITIVE gross_yield_pct and POSITIVE fee_charged_pct are
present): take the gap verbatim (negative -> magnitude) and skip the
net-of-insurance-fund-premium geometry — fee_on_insurance_fund_premium_fraction and the
metrics are computed the same way:

    fee_on_insurance_fund_premium_fraction = clamp(gap / fee_charged_pct, 0, 1)

(On the override path the net-of-insurance-fund-premium / premium-slice / fair geometry
is not known -> those fields are reported as None, and the geometry-only flags
FEE_ON_INSURANCE_FUND_PREMIUM / FULL_FEE_ON_INSURANCE_FUND_PREMIUM / NET_NEGATIVE_AFTER_FEE
are NOT raised; realization_ratio is anchored to
(1 - fee_on_insurance_fund_premium_fraction).)

Distinct from (this is the GROSS-OF-INSURANCE-FUND-PREMIUM performance-fee BASE —
the fee being charged on the gross yield before the INSURANCE FUND PREMIUM the
vault pays OUT to a cover provider / safety-module stakers for slashing/hack
protection is netted out, not a fee paid to an AMM pool, nor value extracted
adversarially by mempool searchers, nor execution gas, nor another cost layer):
  * defi_protocol_vault_performance_fee_gross_of_reserve_contribution_base_gap_analyzer
    — that module prices the PROTOCOL RESERVE FACTOR retained as the protocol's
    OWN revenue (a treasury skim the protocol keeps). HERE the premium is paid
    OUT to a cover provider / safety-module stakers as the cost of slashing/hack
    cover, NOT retained by the protocol as its own revenue.
  * defi_protocol_vault_performance_fee_gross_of_bad_debt_socialization_base_gap_analyzer
    — that module prices RESIDUAL BAD DEBT socialised across depositors when a
    liquidation FAILS to recover the full debt. HERE it is the continuous cover
    PREMIUM paid to backstop such losses, not a realized residual loss spread to
    depositors after a failed liquidation.
  * defi_protocol_vault_performance_fee_gross_of_slashing_loss_base_gap_analyzer
    — that module prices the ACTUAL SLASHING EVENT (value destroyed when a
    validator / restaking position is slashed). HERE it is the ongoing premium
    paid to insure against such a loss, NOT the slashing loss itself.
  * defi_protocol_vault_performance_fee_gross_of_liquidation_penalty_base_gap_analyzer
    — that module prices the LIQUIDATION PENALTY (liquidator bonus + protocol
    liquidation fee) bled from a leveraged vault's collateral at a liquidation
    event. HERE it is a continuous cover premium paid to a safety module, not a
    one-off liquidation penalty seized from collateral.
  * defi_protocol_vault_performance_fee_gross_of_exit_slippage / swap_fee /
    rebalancing_cost / mev_tax base gap analyzers
    — those price the vault's OWN trade-execution drag: deterministic price impact
    along the pool curve, the AMM LP swap fee, aggregate turnover cost, and value
    sandwiched/backrun by searchers. HERE it is an insurance fund premium paid to
    a cover provider, not a trade-execution cost.
  * defi_protocol_vault_performance_fee_gross_of_cost / priority_fee / blob_fee /
    l1_data_fee / bundler_fee / crosschain_message_fee / oracle_update_fee /
    harvest_bounty base gap analyzers
    — those price EXECUTION GAS / a proposer tip / blob-gas DA posting / L1 data
    fee / ERC-4337 bundler premium / cross-chain messaging delivery / oracle
    price-feed post / a keeper-caller bounty. HERE it is the insurance fund premium,
    NOT a gas-market, account-abstraction, messaging, oracle or keeper fee.
  * defi_protocol_vault_performance_fee_gross_of_funding_cost /
    bridge_fee / flash_loan_fee / management_fee / deposit_fee / withdrawal_fee
    (and the other gross_of_* perf-fee modules: gross_of_insurance_premium,
    gross_of_validator_commission, gross_of_impermanent_loss,
    gross_of_borrow_cost, gross_of_referral_fee, gross_of_boost_fee,
    gross_of_intent_solver_fee)
    — each prices a DIFFERENT erosion layer (perp funding, cross-chain transfer,
    flash-loan premium, AUM charge, entry/exit fee, …). None of those layers is
    the INSURANCE FUND PREMIUM paid out of the vault's yield to a cover provider /
    safety module. (gross_of_insurance_premium prices a one-shot / upfront cover
    charge framing; HERE the axis is the continuous safety-module / cover-provider
    premium skimmed from gross yield before the performance fee is struck.)
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer and related
    performance-fee mechanic modules — those measure HWM/crystallization
    fairness. HERE the axis is the fee-BASE inflation from charging the
    performance fee on gross (pre-insurance-fund-premium) yield, not HWM or
    crystallization mechanics.

The novel axis here: the performance-fee BASE being GROSS-OF-INSURANCE-FUND-PREMIUM
rather than NET-OF-INSURANCE-FUND-PREMIUM — a fee-on-insurance-fund-premium / fee-base
inflation in which the performance fee is charged on the slice of yield the
INSURANCE FUND PREMIUM (the continuous cover premium paid out to a safety module /
cover provider for slashing/hack protection) already consumed.

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
    "data",
    "vault_performance_fee_gross_of_insurance_fund_premium_base_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free fee_on_insurance_fund_premium_fraction in [0, 1]
# (= fee_on_insurance_fund_premium_gap_pct / fee_charged_pct).
CLEAN_FRACTION = 0.05        # at/below → cleanly on the net-of-insurance-fund-premium base
MILD_FRACTION = 0.20         # at/below → mild fee-on-insurance-fund-premium gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe gap

# High-insurance-fund-premium flag threshold on insurance_fund_premium_rate_pct
# (interpreted as the INSURANCE FUND PREMIUM — the continuous cover premium paid
# OUT to a safety module / cover provider for slashing/hack protection —
# expressed as a % of the position notional skimmed over the measurement
# window). A cover premium consuming more than ~0.3% of the position notional
# over the window is atypical for a vault carrying modest, prudently-priced
# cover; only richly-insured vaults or vaults paying a steep cover spread on a
# high-risk underlying approach this level.
HIGH_INSURANCE_FUND_PREMIUM_PCT = 0.3

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
    net-of-insurance-fund-premium-yield field, which may legitimately be negative.
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

class DeFiProtocolVaultPerformanceFeeGrossOfInsuranceFundPremiumBaseGapAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the INSURANCE FUND PREMIUM — the continuous cover premium paid
    OUT to a safety module / cover provider for slashing/hack protection — is
    netted out) and the FAIR fee it would charge on
    the NET-OF-INSURANCE-FUND-PREMIUM yield the depositor economically realized, and
    the share of the charged performance fee that therefore landed on the
    INSURANCE-FUND-PREMIUM slice of the yield (a fee-on-insurance-fund-premium /
    fee-base inflation).

        fee_frac                   = clamp(performance_fee_pct / 100, 0, 1)
        insurance_fund_premium_consumed_yield_pct = max(0, gross_yield - net_of_insurance_fund_premium_yield)
        fee_charged_pct            = fee_frac * max(0, gross_yield)
        fair_fee_pct               = fee_frac * max(0, net_of_insurance_fund_premium_yield)
        fee_on_insurance_fund_premium_gap_pct     = max(0, fee_charged - fair_fee)
        net_return_after_fee_pct   = net_of_insurance_fund_premium_yield - fee_charged
        net_return_fair_pct        = net_of_insurance_fund_premium_yield - fair_fee
        overstatement_pct          = fee_on_insurance_fund_premium_gap_pct
        fee_on_insurance_fund_premium_fraction    = clamp(gap / fee_charged, 0, 1)
        realization_ratio          = clamp(net_after_fee / net_fair, 0, 1)

    The performance fee is charged on the gross yield; the fair fee would be
    charged only on the net-of-insurance-fund-premium yield. When the
    net-of-insurance-fund-premium yield equals (or exceeds) the gross yield the
    insurance fund premium consumed nothing and the performance fee was charged on
    the right base (CLEAN_NET_OF_INSURANCE_FUND_PREMIUM_BASE). When the insurance fund premium
    consumed a large share of the yield, a large share of the performance fee was
    charged on the insurance-fund-premium slice (MODERATE / SEVERE
    fee-on-insurance-fund-premium gap), and if the fee exceeds the
    net-of-insurance-fund-premium yield the net return goes negative.

    HIGHER score = the performance fee was charged on the net-of-insurance-fund-premium
    base (gross ≈ net_of_insurance_fund_premium), the fee was effectively fair, nothing
    to fix. LOWER score = a large share of the performance fee landed on the
    insurance-fund-premium slice the depositor never realized, or the net return goes
    negative after the fee.

    Per-position input dict fields:
        vault / token                : str
        gross_yield_pct              : float — the GROSS yield (before the
                                       insurance fund premium is netted) on which the
                                       performance fee is assessed. REQUIRED, must
                                       be a finite POSITIVE number (else
                                       INSUFFICIENT_DATA).
        net_of_insurance_fund_premium_yield_pct     : float — the yield NET OF the
                                       INSURANCE FUND PREMIUM (the continuous cover
                                       premium paid out to the safety module /
                                       cover provider)
                                       (finite; may be < gross; may be negative;
                                       default 0.0 = the insurance fund premium consumed
                                       the whole yield).
        performance_fee_pct          : float — performance-fee rate % (REQUIRED
                                       finite, clamped into 0..100; non-finite →
                                       INSUFFICIENT_DATA on the main path).
        insurance_fund_premium_rate_pct             : float — OPTIONAL informational
                                       INSURANCE FUND PREMIUM as a % of position
                                       notional skimmed over the window;
                                       ≥ HIGH_INSURANCE_FUND_PREMIUM_PCT raises HIGH_INSURANCE_FUND_PREMIUM
                                       flag.
        fee_on_insurance_fund_premium_gap_pct       : float — OPTIONAL direct override of the
                                       fee-on-insurance-fund-premium gap (the
                                       performance fee charged on the
                                       insurance-fund-premium slice). When
                                       supplied (finite; negative → magnitude)
                                       AND a valid POSITIVE gross_yield_pct and
                                       POSITIVE fee_charged_pct are present, take
                                       this gap directly and skip the
                                       net-of-insurance-fund-premium geometry (override
                                       path; geometry → None).
        fee_charged_pct              : float — OPTIONAL, only used on the override
                                       path as the denominator for
                                       fee_on_insurance_fund_premium_fraction (finite > 0
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

        insurance_fund_premium_rate = _coerce_num(p.get("insurance_fund_premium_rate_pct"))

        # Override path: a direct fee-on-insurance-fund-premium gap + a positive fee_charged.
        gap_o = _coerce_num(p.get("fee_on_insurance_fund_premium_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o, insurance_fund_premium_rate)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(
            token, p, gross_gain, fee_pct, insurance_fund_premium_rate)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        insurance_fund_premium_rate: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        # net-of-insurance-fund-premium yield may legitimately be negative (the
        # insurance fund premium exceeds the gross yield, or the strategy lost).
        net_gain = _coerce_signed(p.get("net_of_insurance_fund_premium_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        insurance_fund_premium_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        fee_on_insurance_fund_premium_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_insurance_fund_premium_yield_pct=net_gain,
            insurance_fund_premium_consumed_yield_pct=insurance_fund_premium_consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            fee_on_insurance_fund_premium_gap_pct=fee_on_insurance_fund_premium_gap_pct,
            insurance_fund_premium_rate_pct=insurance_fund_premium_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        insurance_fund_premium_rate: Optional[float],
    ) -> dict:
        # The gap cannot exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # net-of-insurance-fund-premium / insurance-fund-premium-slice / fair geometry is unknown on the
        # override path → report None.
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_insurance_fund_premium_yield_pct=None,
            insurance_fund_premium_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            fee_on_insurance_fund_premium_gap_pct=gap,
            insurance_fund_premium_rate_pct=insurance_fund_premium_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_insurance_fund_premium_yield_pct: Optional[float],
        insurance_fund_premium_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        fee_on_insurance_fund_premium_gap_pct: float,
        insurance_fund_premium_rate_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the performance fee charged on the insurance-fund-premium slice.
        overstatement_pct = fee_on_insurance_fund_premium_gap_pct

        # Net return: only computable when net-of-insurance-fund-premium geometry is known.
        if net_of_insurance_fund_premium_yield_pct is not None:
            net_return_after_fee_pct = (
                net_of_insurance_fund_premium_yield_pct - fee_charged_pct)
            net_return_fair_pct = (
                net_of_insurance_fund_premium_yield_pct - fair_fee_pct)
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

        # Scale-free fee-on-insurance-fund-premium fraction — share of charged fee on the
        # insurance-fund-premium slice.
        if fee_charged_pct > EPS:
            fee_on_insurance_fund_premium_fraction = _clamp(
                fee_on_insurance_fund_premium_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_insurance_fund_premium_fraction = 0.0

        # Override path: anchor realisation on (1 - fee_on_insurance_fund_premium_fraction).
        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_insurance_fund_premium_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_insurance_fund_premium_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_insurance_fund_premium_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_insurance_fund_premium_yield_pct,
            insurance_fund_premium_consumed_yield_pct,
            gross_yield_pct,
            insurance_fund_premium_rate_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_insurance_fund_premium_yield_pct": (
                round(net_of_insurance_fund_premium_yield_pct, 4)
                if net_of_insurance_fund_premium_yield_pct is not None else None),
            "insurance_fund_premium_consumed_yield_pct": (
                round(insurance_fund_premium_consumed_yield_pct, 4)
                if insurance_fund_premium_consumed_yield_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "fee_on_insurance_fund_premium_gap_pct": round(fee_on_insurance_fund_premium_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_insurance_fund_premium_fraction": round(fee_on_insurance_fund_premium_fraction, 4),
            "net_is_negative": net_is_negative,
            "insurance_fund_premium_rate_pct": (
                round(insurance_fund_premium_rate_pct, 4)
                if insurance_fund_premium_rate_pct is not None else None),
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
        fee_on_insurance_fund_premium_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the performance fee was charged on the
        net-of-insurance-fund-premium yield the depositor actually realized: the
        depositor keeps the yield that survived the insurance fund premium.
        Two components:
          * realisation = clamp(realization_ratio, 0, 1)
          * fee-base penalty = clamp(1 − fee_on_insurance_fund_premium_fraction, 0, 1)
        Weighted 70/30 toward realisation.
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_insurance_fund_premium_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_insurance_fund_premium_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            return "SEVERE_FEE_ON_INSURANCE_FUND_PREMIUM_GAP"
        if fee_on_insurance_fund_premium_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_INSURANCE_FUND_PREMIUM_BASE"
        if fee_on_insurance_fund_premium_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_INSURANCE_FUND_PREMIUM_GAP"
        if fee_on_insurance_fund_premium_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_INSURANCE_FUND_PREMIUM_GAP"
        return "SEVERE_FEE_ON_INSURANCE_FUND_PREMIUM_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_INSURANCE_FUND_PREMIUM"
        if classification == "CLEAN_NET_OF_INSURANCE_FUND_PREMIUM_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_INSURANCE_FUND_PREMIUM_GAP":
            return "MINOR_FEE_ON_INSURANCE_FUND_PREMIUM"
        if classification == "MODERATE_FEE_ON_INSURANCE_FUND_PREMIUM_GAP":
            return "DEMAND_NET_OF_INSURANCE_FUND_PREMIUM_BASE"
        # SEVERE_FEE_ON_INSURANCE_FUND_PREMIUM_GAP
        return "AVOID_FEE_ON_INSURANCE_FUND_PREMIUM"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_insurance_fund_premium_yield_pct: Optional[float],
        insurance_fund_premium_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        insurance_fund_premium_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        flags.append(classification)

        if classification == "CLEAN_NET_OF_INSURANCE_FUND_PREMIUM_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (insurance_fund_premium_rate_pct is not None
                and insurance_fund_premium_rate_pct >= HIGH_INSURANCE_FUND_PREMIUM_PCT):
            flags.append("HIGH_INSURANCE_FUND_PREMIUM")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if (insurance_fund_premium_consumed_yield_pct is not None
                    and insurance_fund_premium_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_INSURANCE_FUND_PREMIUM")
            if (net_of_insurance_fund_premium_yield_pct is not None
                    and net_of_insurance_fund_premium_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_INSURANCE_FUND_PREMIUM")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_insurance_fund_premium_yield_pct": None,
            "insurance_fund_premium_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "fee_on_insurance_fund_premium_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_insurance_fund_premium_fraction": None,
            "net_is_negative": False,
            "insurance_fund_premium_rate_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_INSURANCE_FUND_PREMIUM",
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
                "worst_insurance_fund_premium_gap_vault": None,
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
            "worst_insurance_fund_premium_gap_vault": by_score[0]["token"],
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
            # CLEAN_NET_OF_INSURANCE_FUND_PREMIUM_BASE: net ≈ gross → a vault
            # carrying only a thin slashing-cover premium skimmed essentially
            # nothing over a 15% annual yield, the performance fee was on the
            # right base.
            "vault": "USDC-IFP-Vault-CleanInsuranceFundPremium",
            "gross_yield_pct": 15.0,
            "net_of_insurance_fund_premium_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "insurance_fund_premium_rate_pct": 0.05,
        },
        {
            # MODERATE_FEE_ON_INSURANCE_FUND_PREMIUM_GAP: gross 14, net 7 → ~half the
            # performance fee was charged on the insurance-fund-premium slice
            # (fraction ≈ 0.5).
            "vault": "CRV-IFP-Vault-ModerateInsuranceFundPremium",
            "gross_yield_pct": 14.0,
            "net_of_insurance_fund_premium_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "insurance_fund_premium_rate_pct": 0.2,
        },
        {
            # SEVERE_FEE_ON_INSURANCE_FUND_PREMIUM_GAP (net negative): the vault
            # pays a steep continuous cover premium to its safety module on a
            # high-risk underlying; the cumulative premium paid out to the cover
            # provider pushed net yield negative — yet the performance fee is
            # still charged on gross yield.
            "vault": "BAL-IFP-Vault-SevereInsuranceFundPremium",
            "gross_yield_pct": 10.0,
            "net_of_insurance_fund_premium_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "insurance_fund_premium_rate_pct": 0.6,
        },
        {
            # Override path: fee-on-insurance-fund-premium gap supplied directly.
            # gap 4.8, fee_charged 12 → fraction 0.4 → MODERATE.
            "vault": "UNI-IFP-Vault-OverrideInsuranceFundPremiumGap",
            "gross_yield_pct": 20.0,
            "fee_on_insurance_fund_premium_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_insurance_fund_premium_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1244 Vault Performance-Fee Gross-Of-Insurance-Fund-Premium-Base Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeGrossOfInsuranceFundPremiumBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
