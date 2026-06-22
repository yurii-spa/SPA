"""
MP-1243: DeFiProtocolVaultPerformanceFeeGrossOfCuratorFeeBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

In modular / curated yield vaults (MetaMorpho & Morpho Blue, Euler v2 EulerEarn,
Yearn v3 with external risk managers) a CURATOR — an external risk manager such
as Gauntlet, Steakhouse, Re7, B.Protocol or Block Analitica — sets the vault's
risk parameters (supply caps, allowed markets, LLTVs) and allocates the vault's
deposits across the underlying markets / strategies. For that risk-curation
service the curator charges a CURATOR FEE: a cut of the vault's yield (a share of
the interest / rewards the vault accrues), streamed to the curator's address
before the depositor sees anything. On MetaMorpho this is the vault `fee` routed
to the `feeRecipient` the curator controls; Euler and Yearn-v3 curated vaults
have the equivalent. The curator fee is therefore a real drag on the cycle's
gross yield: it is taken out before the depositor receives anything. It is NOT
the vault operator's flat management (AUM) fee, NOT a validator's commission on
staking rewards, NOT a referrer's cut, and NOT the performance fee itself.
Economically, the depositor's NET yield is:

    net_of_curator_fee_yield = gross_yield - curator_fee

But many vaults charge the performance fee on the GROSS yield (before netting
the CURATOR FEE — the risk-curator's share of the yield, streamed to the
curator's fee recipient over the measurement window), not on the
net-of-curator-fee yield the depositor economically realized. The result
is a "fee-on-curator-fee" / fee-base inflation: the performance fee is
levied on the yield slice the curator fee already consumed. The fair
performance fee would be levied only on the net-of-curator-fee yield:

    fee_frac                              = clamp(performance_fee_pct / 100, 0, 1)
    curator_fee_consumed_yield_pct  = max(0, gross_yield - net_of_cf_yield)
    fee_charged_pct                       = fee_frac * max(0, gross_yield)
    fair_fee_pct                          = fee_frac * max(0, net_of_cf_yield)
    fee_on_curator_fee_gap_pct      = max(0, fee_charged - fair_fee)
                                            (= performance fee charged on the
                                             curator-fee slice of the yield,
                                             which the depositor never received)
    net_return_after_fee_pct              = net_of_cf_yield - fee_charged
    net_return_fair_pct                   = net_of_cf_yield - fair_fee
    overstatement_pct                     = fee_on_curator_fee_gap_pct
    fee_on_curator_fee_fraction     = clamp(gap / fee_charged, 0, 1)
    realization_ratio                     = clamp(net_after_fee / net_fair, 0, 1)

The headline says "you only pay performance fees on profits", but when the
performance fee is charged on gross yield a chunk of the performance fee lands
on the curator-fee slice the depositor never received. The scale-free
fee_on_curator_fee_fraction is the share of the charged performance fee
that landed on the curator-fee slice; it is the basis of the
classification. When the curator fee consumed nothing (net_of_cf approx
gross) the performance fee was effectively fair (HIGHER score). When the
curator fee consumed most of the yield, the performance fee was charged
almost entirely on the curator-fee slice (LOWER score).

HIGHER score = the performance fee was charged on the net-of-curator-fee
base (gross approx net_of_cf), the fee was effectively fair, nothing to fix.
LOWER score = a large share of the performance fee landed on the
curator-fee slice, or the net return goes negative after the fee.

Override path (when fee_on_curator_fee_gap_pct is supplied directly,
finite, AND a valid POSITIVE gross_yield_pct and POSITIVE fee_charged_pct are
present): take the gap verbatim (negative -> magnitude) and skip the
net-of-curator-fee geometry — fee_on_curator_fee_fraction and the
metrics are computed the same way:

    fee_on_curator_fee_fraction = clamp(gap / fee_charged_pct, 0, 1)

(On the override path the net-of-curator-fee / cf-slice / fair geometry
is not known -> those fields are reported as None, and the geometry-only flags
FEE_ON_CURATOR_FEE / FULL_FEE_ON_CURATOR_FEE / NET_NEGATIVE_AFTER_FEE
are NOT raised; realization_ratio is anchored to
(1 - fee_on_curator_fee_fraction).)

Distinct from (this is the GROSS-OF-CURATOR-FEE performance-fee BASE — the fee
being charged on the gross yield before the CURATOR FEE the vault's external
risk-curator skims (the curator's share of the yield, streamed to the curator
fee recipient) is netted out, not a fee paid to an AMM pool, nor value extracted
adversarially by mempool searchers, nor execution gas, nor another cost layer):
  * defi_protocol_vault_performance_fee_gross_of_management_fee_base_gap_analyzer
    — that module prices the vault OPERATOR's flat MANAGEMENT (AUM) fee for
    running the vault wrapper. HERE it is the EXTERNAL RISK-CURATOR's cut for
    setting risk parameters and allocating capital across markets: a different
    actor (Gauntlet / Steakhouse / Re7 vs the vault deployer) charging on a
    different basis (a share of yield vs a flat % of AUM).
  * defi_protocol_vault_performance_fee_gross_of_validator_commission_base_gap_analyzer
    — that module prices a VALIDATOR's commission on PoS staking rewards. HERE it
    is a lending / vault risk-manager's cut, not a validator's.
  * defi_protocol_vault_performance_fee_gross_of_referral_fee_base_gap_analyzer
    — that module prices a REFERRER's cut for routing deposits into the vault.
    HERE the curator earns for ongoing risk-curation and allocation, not for
    referring the deposit.
  * defi_protocol_vault_performance_fee_gross_of_reserve_contribution /
    insurance_fund_premium / insurance_premium / boost_fee base gap analyzers
    — those price PROTOCOL-SIDE allocations skimmed to a reserve / insurance fund
    / a boost-incentive pot. HERE it is comp paid to the external curator actor,
    not a protocol reserve or insurance contribution.
  * defi_protocol_vault_performance_fee_gross_of_harvest_bounty_base_gap_analyzer
    — that module prices a KEEPER-CALLER's per-call bounty for triggering a
    harvest / compound transaction. HERE it is the curator's ONGOING comp for
    strategic risk-curation, not a discrete keeper bounty.
  * defi_protocol_vault_performance_fee_gross_of_exit_slippage / swap_fee /
    rebalancing_cost / mev_tax base gap analyzers
    — those price the vault's OWN trade-execution drag: deterministic price impact
    along the pool curve, the AMM LP swap fee, aggregate turnover cost, and value
    sandwiched/backrun by searchers. HERE it is the curator's fee, not a
    trade-execution cost.
  * defi_protocol_vault_performance_fee_gross_of_cost / priority_fee / blob_fee /
    l1_data_fee / bundler_fee / crosschain_message_fee / oracle_update_fee base
    gap analyzers
    — those price EXECUTION GAS / a proposer tip / blob-gas DA posting / L1 data
    fee / ERC-4337 bundler premium / cross-chain messaging delivery / an oracle
    price-feed post. HERE it is the curator fee, NOT a gas-market,
    account-abstraction, messaging or oracle fee.
  * defi_protocol_vault_performance_fee_gross_of_funding_cost / borrow_cost /
    bridge_fee / flash_loan_fee / deposit_fee / withdrawal_fee /
    liquidation_penalty / bad_debt_socialization / slashing_loss /
    impermanent_loss / intent_solver_fee base gap analyzers
    — each prices a DIFFERENT erosion layer (perp funding, borrow interest,
    cross-chain transfer, flash-loan premium, entry/exit fee, liquidation
    penalty, socialised bad debt, validator slashing, IL, intent-solver margin).
    None of those layers is the CURATOR FEE skimmed by the external risk-curator.
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer and related
    performance-fee mechanic modules — those measure HWM/crystallization
    fairness. HERE the axis is the fee-BASE inflation from charging the
    performance fee on gross (pre-curator-fee) yield, not HWM or
    crystallization mechanics.

The novel axis here: the performance-fee BASE being GROSS-OF-CURATOR-FEE
rather than NET-OF-CURATOR-FEE — a fee-on-curator-fee / fee-base
inflation in which the performance fee is charged on the slice of yield the
CURATOR FEE (the external risk-curator's share of the yield, streamed to the
curator fee recipient) already consumed.

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
    "vault_performance_fee_gross_of_curator_fee_base_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free fee_on_curator_fee_fraction in [0, 1]
# (= fee_on_curator_fee_gap_pct / fee_charged_pct).
CLEAN_FRACTION = 0.05        # at/below → cleanly on the net-of-curator-fee base
MILD_FRACTION = 0.20         # at/below → mild fee-on-curator-fee gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe gap

# High-curator-fee flag threshold on curator_fee_rate_pct
# (interpreted as the CURATOR FEE — the external risk-curator's share of the
# yield, streamed to the curator fee recipient — expressed as a % of the
# position notional eroded over the measurement window). A curator fee consuming
# more than ~0.3% of the position notional over the window is high for a
# typically yield-denominated curator cut; only an aggressively-priced curator
# mandate on a high-yield vault approaches this level.
HIGH_CURATOR_FEE_PCT = 0.3

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
    net-of-curator-fee-yield field, which may legitimately be negative.
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

class DeFiProtocolVaultPerformanceFeeGrossOfCuratorFeeBaseGapAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the CURATOR FEE — the external risk-curator's share of the
    yield, streamed to the curator fee recipient for setting risk parameters and
    allocating the vault's deposits across markets — is netted out) and the FAIR
    fee it would charge on the NET-OF-CURATOR-FEE yield the depositor economically
    realized, and the share of the charged performance fee that therefore landed
    on the CURATOR-FEE slice of the yield (a fee-on-curator-fee /
    fee-base inflation).

        fee_frac                   = clamp(performance_fee_pct / 100, 0, 1)
        curator_fee_consumed_yield_pct = max(0, gross_yield - net_of_curator_fee_yield)
        fee_charged_pct            = fee_frac * max(0, gross_yield)
        fair_fee_pct               = fee_frac * max(0, net_of_curator_fee_yield)
        fee_on_curator_fee_gap_pct     = max(0, fee_charged - fair_fee)
        net_return_after_fee_pct   = net_of_curator_fee_yield - fee_charged
        net_return_fair_pct        = net_of_curator_fee_yield - fair_fee
        overstatement_pct          = fee_on_curator_fee_gap_pct
        fee_on_curator_fee_fraction    = clamp(gap / fee_charged, 0, 1)
        realization_ratio          = clamp(net_after_fee / net_fair, 0, 1)

    The performance fee is charged on the gross yield; the fair fee would be
    charged only on the net-of-curator-fee yield. When the
    net-of-curator-fee yield equals (or exceeds) the gross yield the
    curator fee consumed nothing and the performance fee was charged on
    the right base (CLEAN_NET_OF_CURATOR_FEE_BASE). When the curator fee
    consumed a large share of the yield, a large share of the performance fee was
    charged on the curator-fee slice (MODERATE / SEVERE
    fee-on-curator-fee gap), and if the fee exceeds the
    net-of-curator-fee yield the net return goes negative.

    HIGHER score = the performance fee was charged on the net-of-curator-fee
    base (gross ≈ net_of_curator_fee), the fee was effectively fair, nothing
    to fix. LOWER score = a large share of the performance fee landed on the
    curator-fee slice the depositor never realized, or the net return goes
    negative after the fee.

    Per-position input dict fields:
        vault / token                : str
        gross_yield_pct              : float — the GROSS yield (before the
                                       curator fee is netted) on which the
                                       performance fee is assessed. REQUIRED, must
                                       be a finite POSITIVE number (else
                                       INSUFFICIENT_DATA).
        net_of_curator_fee_yield_pct     : float — the yield NET OF the
                                       CURATOR FEE (the external risk-curator's
                                       share of the yield)
                                       (finite; may be < gross; may be negative;
                                       default 0.0 = the curator fee consumed
                                       the whole yield).
        performance_fee_pct          : float — performance-fee rate % (REQUIRED
                                       finite, clamped into 0..100; non-finite →
                                       INSUFFICIENT_DATA on the main path).
        curator_fee_rate_pct             : float — OPTIONAL informational
                                       CURATOR FEE as a % of position
                                       notional eroded over the window;
                                       ≥ HIGH_CURATOR_FEE_PCT raises HIGH_CURATOR_FEE
                                       flag.
        fee_on_curator_fee_gap_pct       : float — OPTIONAL direct override of the
                                       fee-on-curator-fee gap (the
                                       performance fee charged on the
                                       curator-fee slice). When
                                       supplied (finite; negative → magnitude)
                                       AND a valid POSITIVE gross_yield_pct and
                                       POSITIVE fee_charged_pct are present, take
                                       this gap directly and skip the
                                       net-of-curator-fee geometry (override
                                       path; geometry → None).
        fee_charged_pct              : float — OPTIONAL, only used on the override
                                       path as the denominator for
                                       fee_on_curator_fee_fraction (finite > 0
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

        curator_fee_rate = _coerce_num(p.get("curator_fee_rate_pct"))

        # Override path: a direct fee-on-curator-fee gap + a positive fee_charged.
        gap_o = _coerce_num(p.get("fee_on_curator_fee_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o, curator_fee_rate)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(
            token, p, gross_gain, fee_pct, curator_fee_rate)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        curator_fee_rate: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        # net-of-curator-fee yield may legitimately be negative (the
        # curator fee exceeds the gross yield, or the strategy lost).
        net_gain = _coerce_signed(p.get("net_of_curator_fee_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        curator_fee_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        fee_on_curator_fee_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_curator_fee_yield_pct=net_gain,
            curator_fee_consumed_yield_pct=curator_fee_consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            fee_on_curator_fee_gap_pct=fee_on_curator_fee_gap_pct,
            curator_fee_rate_pct=curator_fee_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        curator_fee_rate: Optional[float],
    ) -> dict:
        # The gap cannot exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # net-of-curator-fee / curator-fee-slice / fair geometry is unknown on the
        # override path → report None.
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_curator_fee_yield_pct=None,
            curator_fee_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            fee_on_curator_fee_gap_pct=gap,
            curator_fee_rate_pct=curator_fee_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_curator_fee_yield_pct: Optional[float],
        curator_fee_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        fee_on_curator_fee_gap_pct: float,
        curator_fee_rate_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the performance fee charged on the curator-fee slice.
        overstatement_pct = fee_on_curator_fee_gap_pct

        # Net return: only computable when net-of-curator-fee geometry is known.
        if net_of_curator_fee_yield_pct is not None:
            net_return_after_fee_pct = (
                net_of_curator_fee_yield_pct - fee_charged_pct)
            net_return_fair_pct = (
                net_of_curator_fee_yield_pct - fair_fee_pct)
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

        # Scale-free fee-on-curator-fee fraction — share of charged fee on the
        # curator-fee slice.
        if fee_charged_pct > EPS:
            fee_on_curator_fee_fraction = _clamp(
                fee_on_curator_fee_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_curator_fee_fraction = 0.0

        # Override path: anchor realisation on (1 - fee_on_curator_fee_fraction).
        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_curator_fee_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_curator_fee_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_curator_fee_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_curator_fee_yield_pct,
            curator_fee_consumed_yield_pct,
            gross_yield_pct,
            curator_fee_rate_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_curator_fee_yield_pct": (
                round(net_of_curator_fee_yield_pct, 4)
                if net_of_curator_fee_yield_pct is not None else None),
            "curator_fee_consumed_yield_pct": (
                round(curator_fee_consumed_yield_pct, 4)
                if curator_fee_consumed_yield_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "fee_on_curator_fee_gap_pct": round(fee_on_curator_fee_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_curator_fee_fraction": round(fee_on_curator_fee_fraction, 4),
            "net_is_negative": net_is_negative,
            "curator_fee_rate_pct": (
                round(curator_fee_rate_pct, 4)
                if curator_fee_rate_pct is not None else None),
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
        fee_on_curator_fee_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the performance fee was charged on the
        net-of-curator-fee yield the depositor actually realized: the
        depositor keeps the yield that survived the curator fee.
        Two components:
          * realisation = clamp(realization_ratio, 0, 1)
          * fee-base penalty = clamp(1 − fee_on_curator_fee_fraction, 0, 1)
        Weighted 70/30 toward realisation.
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_curator_fee_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_curator_fee_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            return "SEVERE_FEE_ON_CURATOR_FEE_GAP"
        if fee_on_curator_fee_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_CURATOR_FEE_BASE"
        if fee_on_curator_fee_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_CURATOR_FEE_GAP"
        if fee_on_curator_fee_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_CURATOR_FEE_GAP"
        return "SEVERE_FEE_ON_CURATOR_FEE_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_CURATOR_FEE"
        if classification == "CLEAN_NET_OF_CURATOR_FEE_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_CURATOR_FEE_GAP":
            return "MINOR_FEE_ON_CURATOR_FEE"
        if classification == "MODERATE_FEE_ON_CURATOR_FEE_GAP":
            return "DEMAND_NET_OF_CURATOR_FEE_BASE"
        # SEVERE_FEE_ON_CURATOR_FEE_GAP
        return "AVOID_FEE_ON_CURATOR_FEE"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_curator_fee_yield_pct: Optional[float],
        curator_fee_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        curator_fee_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        flags.append(classification)

        if classification == "CLEAN_NET_OF_CURATOR_FEE_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (curator_fee_rate_pct is not None
                and curator_fee_rate_pct >= HIGH_CURATOR_FEE_PCT):
            flags.append("HIGH_CURATOR_FEE")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if (curator_fee_consumed_yield_pct is not None
                    and curator_fee_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_CURATOR_FEE")
            if (net_of_curator_fee_yield_pct is not None
                    and net_of_curator_fee_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_CURATOR_FEE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_curator_fee_yield_pct": None,
            "curator_fee_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "fee_on_curator_fee_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_curator_fee_fraction": None,
            "net_is_negative": False,
            "curator_fee_rate_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_CURATOR_FEE",
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
                "worst_curator_fee_gap_vault": None,
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
            "worst_curator_fee_gap_vault": by_score[0]["token"],
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
            # CLEAN_NET_OF_CURATOR_FEE_BASE: net ≈ gross → a vault whose
            # curator takes essentially no cut of the 15% annual yield, the
            # performance fee was on the right base.
            "vault": "USDC-CUR-Vault-CleanCuratorFee",
            "gross_yield_pct": 15.0,
            "net_of_curator_fee_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "curator_fee_rate_pct": 0.05,
        },
        {
            # MODERATE_FEE_ON_CURATOR_FEE_GAP: gross 14, net 7 → ~half the
            # performance fee was charged on the curator-fee slice
            # (fraction ≈ 0.5).
            "vault": "CRV-CUR-Vault-ModerateCuratorFee",
            "gross_yield_pct": 14.0,
            "net_of_curator_fee_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "curator_fee_rate_pct": 0.2,
        },
        {
            # SEVERE_FEE_ON_CURATOR_FEE_GAP (net negative): an aggressively
            # priced curator mandate skims so much of the yield (plus the gross
            # yield itself was thin) that the cumulative curator fee pushed net
            # yield negative — yet the performance fee is still charged on gross
            # yield.
            "vault": "BAL-CUR-Vault-SevereCuratorFee",
            "gross_yield_pct": 10.0,
            "net_of_curator_fee_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "curator_fee_rate_pct": 0.6,
        },
        {
            # Override path: fee-on-curator-fee gap supplied directly.
            # gap 4.8, fee_charged 12 → fraction 0.4 → MODERATE.
            "vault": "UNI-CUR-Vault-OverrideCuratorFeeGap",
            "gross_yield_pct": 20.0,
            "fee_on_curator_fee_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_curator_fee_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1243 Vault Performance-Fee Gross-Of-Curator-Fee-Base Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeGrossOfCuratorFeeBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
