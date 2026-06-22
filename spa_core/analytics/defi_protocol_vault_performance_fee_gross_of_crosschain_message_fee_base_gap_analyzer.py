"""
MP-1238: DeFiProtocolVaultPerformanceFeeGrossOfCrosschainMessageFeeBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

Vaults that run a cross-chain strategy — keeping a sleeve of capital on a remote
chain and steering it from the home chain — cannot harvest or rebalance that
remote sleeve with a plain local transaction. On every harvest / rebalance that
touches the remote sleeve the vault must send a CROSS-CHAIN MESSAGE — an
instruction packet ("harvest the remote sleeve", "rebalance into pool X on
chain Y") — through a CROSS-CHAIN MESSAGING PROTOCOL (LayerZero, Chainlink CCIP,
Hyperlane, Axelar, a Wormhole relayer), and the vault MUST pay a per-message
CROSS-CHAIN MESSAGE FEE — the messaging protocol's endpoint / relayer / executor
fee plus the destination-chain gas prepayment that the messaging layer charges
to verify and deliver the instruction (e.g. the LayerZero endpoint native fee +
executor fee, the Chainlink CCIP fee, the Hyperlane interchain gas payment).
This CROSS-CHAIN MESSAGE FEE — the messaging-protocol charge for verifying and
delivering the harvest/rebalance instruction across chains — goes to the
messaging protocol / relayer for the cross-chain delivery service, and is
deducted from the cycle's gross yield before the depositor sees anything.
Economically, the depositor's NET yield is:

    net_of_crosschain_message_fee_yield = gross_yield − crosschain_message_fee

But many vaults charge the performance fee on the GROSS yield (before netting
the per-message CROSS-CHAIN MESSAGE FEE — the messaging-protocol fee paid to
deliver the harvest/rebalance instruction across chains during the measurement
window), not on the net-of-crosschain-message-fee yield the depositor
economically realized. The result is a "fee-on-crosschain-message-fee" /
fee-base inflation: the performance fee is levied on the yield slice the
cross-chain message fee already consumed. The fair performance fee would be
levied only on the net-of-crosschain-message-fee yield:

    fee_frac                                  = clamp(performance_fee_pct / 100, 0, 1)
    crosschain_message_fee_consumed_yield_pct = max(0, gross_yield - net_of_crosschain_message_fee_yield)
    fee_charged_pct                           = fee_frac * max(0, gross_yield)
    fair_fee_pct                              = fee_frac * max(0, net_of_crosschain_message_fee_yield)
    fee_on_crosschain_message_fee_gap_pct     = max(0, fee_charged - fair_fee)
                                                (= performance fee charged on the
                                                 crosschain-message-fee slice of
                                                 the yield, which the depositor
                                                 never received)
    net_return_after_fee_pct                  = net_of_crosschain_message_fee_yield - fee_charged
    net_return_fair_pct                       = net_of_crosschain_message_fee_yield - fair_fee
    overstatement_pct                         = fee_on_crosschain_message_fee_gap_pct
    fee_on_crosschain_message_fee_fraction    = clamp(gap / fee_charged, 0, 1)
    realization_ratio                         = clamp(net_after_fee / net_fair, 0, 1)

The headline says "you only pay performance fees on profits", but when the
performance fee is charged on gross yield a chunk of the performance fee lands
on the cross-chain-message-fee slice the depositor never received. The
scale-free fee_on_crosschain_message_fee_fraction is the share of the charged
performance fee that landed on the cross-chain-message-fee slice; it is the
basis of the classification. When the cross-chain message fee consumed nothing
(net_of_crosschain_message_fee ≈ gross) the performance fee was effectively fair
(HIGHER score). When the cross-chain message fee consumed most of the yield, the
performance fee was charged almost entirely on the message-fee slice (LOWER
score).

HIGHER score = the performance fee was charged on the
net-of-crosschain-message-fee base (gross ≈ net_of_crosschain_message_fee), the
fee was effectively fair, nothing to fix.
LOWER score = a large share of the performance fee landed on the
cross-chain-message-fee slice, or the net return goes negative after the fee.

Override path (when fee_on_crosschain_message_fee_gap_pct is supplied directly,
finite, AND a valid POSITIVE gross_yield_pct and POSITIVE fee_charged_pct are
present): take the gap verbatim (negative → magnitude) and skip the
net-of-crosschain-message-fee geometry —
fee_on_crosschain_message_fee_fraction and the metrics are computed the same
way:

    fee_on_crosschain_message_fee_fraction = clamp(gap / fee_charged_pct, 0, 1)

(On the override path the net-of-crosschain-message-fee / message-fee-slice /
fair geometry is not known → those fields are reported as None, and the
geometry-only flags FEE_ON_CROSSCHAIN_MESSAGE_FEE /
FULL_FEE_ON_CROSSCHAIN_MESSAGE_FEE / NET_NEGATIVE_AFTER_FEE are NOT raised;
realization_ratio is anchored to (1 - fee_on_crosschain_message_fee_fraction).)

Distinct from (this is the GROSS-OF-CROSSCHAIN-MESSAGE-FEE performance-fee BASE —
the fee being charged on the gross yield before the per-message CROSS-CHAIN
MESSAGE FEE the vault pays TO THE CROSS-CHAIN MESSAGING PROTOCOL / RELAYER to
verify and deliver the harvest/rebalance instruction across chains — the
messaging endpoint / relayer / executor fee — is netted out, not execution gas
paid to a validator, nor a proposer tip, nor a data-availability posting fee, nor
the cost of moving the assets themselves, nor another cost layer):
  * defi_protocol_vault_performance_fee_gross_of_bridge_fee_base_gap_analyzer
    — that module prices the BRIDGE FEE for moving the actual ASSETS / principal
    ACROSS a bridge between chains. HERE no assets move: it is the fee to deliver
    an INSTRUCTION MESSAGE across chains through a messaging protocol, paid to
    the messaging layer — not the asset-transfer bridge fee.
  * defi_protocol_vault_performance_fee_gross_of_cost_base_gap_analyzer
    — that module prices a FLAT L2 EXECUTION GAS / BASE FEE, a FIXED DENOMINATED
    constant per tx for running the transaction on the local chain, paid to the
    validator. HERE it is the cross-chain messaging-protocol fee for delivering
    the instruction to a remote chain — not the local execution-gas base cost.
  * defi_protocol_vault_performance_fee_gross_of_priority_fee_base_gap_analyzer
    — that module prices the EIP-1559 PRIORITY FEE / PROPOSER TIP
    (maxPriorityFeePerGas) the vault bids ON TOP OF the base fee to get its tx
    PRIORITISED and INCLUDED in a block. HERE it is the cross-chain messaging
    protocol fee, NOT a proposer tip for inclusion priority.
  * defi_protocol_vault_performance_fee_gross_of_blob_fee_base_gap_analyzer
    — that module prices the EIP-4844 BLOB FEE for the BLOB GAS a rollup
    consumes to post its DATA AVAILABILITY to the post-Dencun blob market. HERE
    it is the cross-chain messaging-protocol delivery fee, NOT blob-gas DA
    posting.
  * defi_protocol_vault_performance_fee_gross_of_oracle_update_fee_base_gap_analyzer
    — that module prices the per-update ORACLE UPDATE FEE (Pyth
    `updatePriceFeeds` / Wormhole VAA verification) paid TO THE ORACLE PROTOCOL
    to post a fresh on-chain PRICE update. HERE it is the messaging-protocol fee
    for delivering a generic harvest/rebalance INSTRUCTION across chains, NOT an
    oracle price-feed post.
  * defi_protocol_vault_performance_fee_gross_of_bundler_fee_base_gap_analyzer
    — that module prices the ERC-4337 BUNDLER / PAYMASTER premium for packing
    and sponsoring a UserOperation through the EntryPoint on a single chain. HERE
    it is the CROSS-CHAIN MESSAGING protocol fee for delivering an instruction
    BETWEEN chains, not an account-abstraction bundling premium.
  * defi_protocol_vault_performance_fee_gross_of_harvest_bounty_base_gap_analyzer
    — that module prices a BOUNTY the vault itself pays to the KEEPER / caller
    that triggers harvest(). HERE it is the fee paid to the CROSS-CHAIN MESSAGING
    PROTOCOL / RELAYER for delivering the instruction, not a reward to the
    keeper-caller.
  * defi_protocol_vault_performance_fee_gross_of_funding_cost / borrow_cost /
    swap_fee / rebalancing_cost / flash_loan_fee / management_fee /
    deposit_fee / withdrawal_fee
    (and the other gross_of_* perf-fee modules: gross_of_insurance_premium,
    gross_of_slashing_loss, gross_of_validator_commission,
    gross_of_impermanent_loss, gross_of_bad_debt_socialization,
    gross_of_reserve_contribution, gross_of_referral_fee, gross_of_boost_fee,
    gross_of_exit_slippage, gross_of_protocol_revenue_share)
    — each prices a DIFFERENT erosion layer (debt interest, pool fee, turnover
    slippage, flash-loan premium, AUM charge, entry/exit fee, …). None of those
    layers is the CROSS-CHAIN MESSAGE FEE / messaging-protocol charge paid to
    deliver a harvest/rebalance instruction across chains.
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer and related
    performance-fee mechanic modules — those measure HWM/crystallization
    fairness. HERE the axis is the fee-BASE inflation from charging the
    performance fee on gross (pre-crosschain-message-fee) yield, not HWM or
    crystallization mechanics.

The novel axis here: the performance-fee BASE being
GROSS-OF-CROSSCHAIN-MESSAGE-FEE rather than NET-OF-CROSSCHAIN-MESSAGE-FEE — a
fee-on-crosschain-message-fee / fee-base inflation in which the performance fee
is charged on the slice of yield the per-message CROSS-CHAIN MESSAGE FEE (the
messaging-protocol / relayer fee paid to deliver the harvest/rebalance
instruction across chains) already consumed.

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
    "vault_performance_fee_gross_of_crosschain_message_fee_base_gap_log.json"
)
LOG_CAP = 100

# Classification thresholds on the scale-free
# fee_on_crosschain_message_fee_fraction in [0, 1]
# (= fee_on_crosschain_message_fee_gap_pct / fee_charged_pct).
CLEAN_FRACTION = 0.05        # at/below → cleanly on the net-of-message-fee base
MILD_FRACTION = 0.20         # at/below → mild fee-on-message-fee gap
MODERATE_FRACTION = 0.50     # at/below → moderate; above → severe gap

# High-message-fee flag threshold on crosschain_message_fee_rate_pct
# (interpreted as the CROSS-CHAIN MESSAGE FEE — the messaging-protocol / relayer
# fee paid to verify and deliver the harvest/rebalance instruction across chains
# — expressed as a % of the position notional paid on a single harvest/rebalance
# message). A message fee consuming more than ~0.3% of the position on one
# instruction is atypical — a single cross-chain message (endpoint + executor /
# CCIP / interchain-gas payment) is normally a small fraction of a percent of the
# position; only when the destination-chain gas prepayment is large, or many
# messages are sent, does it approach this level.
HIGH_CROSSCHAIN_MESSAGE_FEE_PCT = 0.3

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
    net-of-crosschain-message-fee-yield field, which may legitimately be
    negative.
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

class DeFiProtocolVaultPerformanceFeeGrossOfCrosschainMessageFeeBaseGapAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the per-message CROSS-CHAIN MESSAGE FEE — the messaging-protocol
    / relayer fee paid to verify and deliver the harvest/rebalance instruction
    across chains — is netted out) and the FAIR fee it would charge on the
    NET-OF-CROSSCHAIN-MESSAGE-FEE yield the depositor economically realized, and
    the share of the charged performance fee that therefore landed on the
    MESSAGE-FEE slice of the yield (a fee-on-crosschain-message-fee / fee-base
    inflation).

        fee_frac                                  = clamp(performance_fee_pct / 100, 0, 1)
        crosschain_message_fee_consumed_yield_pct = max(0, gross_yield - net_of_crosschain_message_fee_yield)
        fee_charged_pct                           = fee_frac * max(0, gross_yield)
        fair_fee_pct                              = fee_frac * max(0, net_of_crosschain_message_fee_yield)
        fee_on_crosschain_message_fee_gap_pct     = max(0, fee_charged - fair_fee)
        net_return_after_fee_pct                  = net_of_crosschain_message_fee_yield - fee_charged
        net_return_fair_pct                       = net_of_crosschain_message_fee_yield - fair_fee
        overstatement_pct                         = fee_on_crosschain_message_fee_gap_pct
        fee_on_crosschain_message_fee_fraction    = clamp(gap / fee_charged, 0, 1)
        realization_ratio                         = clamp(net_after_fee / net_fair, 0, 1)

    The performance fee is charged on the gross yield; the fair fee would be
    charged only on the net-of-crosschain-message-fee yield. When the
    net-of-crosschain-message-fee yield equals (or exceeds) the gross yield the
    cross-chain message fee consumed nothing and the performance fee was charged
    on the right base (CLEAN_NET_OF_CROSSCHAIN_MESSAGE_FEE_BASE). When the
    message fee consumed a large share of the yield, a large share of the
    performance fee was charged on the message-fee slice (MODERATE / SEVERE
    fee-on-crosschain-message-fee gap), and if the fee exceeds the
    net-of-crosschain-message-fee yield the net return goes negative.

    HIGHER score = the performance fee was charged on the
    net-of-crosschain-message-fee base (gross ≈ net_of_crosschain_message_fee),
    the fee was effectively fair, nothing to fix.
    LOWER score = a large share of the performance fee landed on the
    cross-chain-message-fee slice the depositor never realized, or the net return
    goes negative after the fee.

    Per-position input dict fields:
        vault / token                : str
        gross_yield_pct              : float — the GROSS yield (before the
                                       cross-chain message fee is netted) on
                                       which the performance fee is assessed.
                                       REQUIRED, must be a finite POSITIVE number
                                       (else INSUFFICIENT_DATA).
        net_of_crosschain_message_fee_yield_pct : float — the yield NET OF the
                                       CROSS-CHAIN MESSAGE FEE (messaging-protocol
                                       / relayer fee) (finite; may be < gross; may
                                       be negative; default 0.0 = the message fee
                                       consumed the whole yield).
        performance_fee_pct          : float — performance-fee rate % (REQUIRED
                                       finite, clamped into 0..100; non-finite →
                                       INSUFFICIENT_DATA on the main path).
        crosschain_message_fee_rate_pct : float — OPTIONAL informational
                                       CROSS-CHAIN MESSAGE FEE (messaging-protocol
                                       / relayer fee) as a % of position notional;
                                       ≥ HIGH_CROSSCHAIN_MESSAGE_FEE_PCT raises
                                       HIGH_CROSSCHAIN_MESSAGE_FEE flag.
        fee_on_crosschain_message_fee_gap_pct : float — OPTIONAL direct override
                                       of the fee-on-crosschain-message-fee gap
                                       (the performance fee charged on the
                                       message-fee slice). When supplied (finite;
                                       negative → magnitude) AND a valid POSITIVE
                                       gross_yield_pct and POSITIVE
                                       fee_charged_pct are present, take this gap
                                       directly and skip the
                                       net-of-crosschain-message-fee geometry
                                       (override path; geometry → None).
        fee_charged_pct              : float — OPTIONAL, only used on the override
                                       path as the denominator for
                                       fee_on_crosschain_message_fee_fraction
                                       (finite > 0 required to take the override
                                       path).
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

        crosschain_message_fee_rate = _coerce_num(
            p.get("crosschain_message_fee_rate_pct"))

        # Override path: a direct fee-on-crosschain-message-fee gap + a positive
        # fee_charged.
        gap_o = _coerce_num(p.get("fee_on_crosschain_message_fee_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o,
                crosschain_message_fee_rate)

        # Main path: the performance fee rate is required and must be finite.
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(
            token, p, gross_gain, fee_pct, crosschain_message_fee_rate)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        crosschain_message_fee_rate: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        # net-of-crosschain-message-fee yield may legitimately be negative (the
        # message fee exceeds the gross yield, or the strategy lost).
        net_gain = _coerce_signed(
            p.get("net_of_crosschain_message_fee_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        crosschain_message_fee_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        fee_on_crosschain_message_fee_gap_pct = max(
            0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_crosschain_message_fee_yield_pct=net_gain,
            crosschain_message_fee_consumed_yield_pct=crosschain_message_fee_consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            fee_on_crosschain_message_fee_gap_pct=fee_on_crosschain_message_fee_gap_pct,
            crosschain_message_fee_rate_pct=crosschain_message_fee_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        crosschain_message_fee_rate: Optional[float],
    ) -> dict:
        # The gap cannot exceed the fee charged (it is a SHARE of it).
        gap = min(gap, fee_charged)
        # net-of-crosschain-message-fee / message-fee-slice / fair geometry is
        # unknown on the override path → report None.
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_crosschain_message_fee_yield_pct=None,
            crosschain_message_fee_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            fee_on_crosschain_message_fee_gap_pct=gap,
            crosschain_message_fee_rate_pct=crosschain_message_fee_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_crosschain_message_fee_yield_pct: Optional[float],
        crosschain_message_fee_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        fee_on_crosschain_message_fee_gap_pct: float,
        crosschain_message_fee_rate_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        # overstatement = the performance fee charged on the message-fee slice.
        overstatement_pct = fee_on_crosschain_message_fee_gap_pct

        # Net return: only computable when net-of-message-fee geometry is known.
        if net_of_crosschain_message_fee_yield_pct is not None:
            net_return_after_fee_pct = (
                net_of_crosschain_message_fee_yield_pct - fee_charged_pct)
            net_return_fair_pct = (
                net_of_crosschain_message_fee_yield_pct - fair_fee_pct)
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

        # Scale-free fee-on-crosschain-message-fee fraction — share of charged
        # fee on the message-fee slice.
        if fee_charged_pct > EPS:
            fee_on_crosschain_message_fee_fraction = _clamp(
                fee_on_crosschain_message_fee_gap_pct / fee_charged_pct,
                0.0, 1.0)
        else:
            fee_on_crosschain_message_fee_fraction = 0.0

        # Override path: anchor realisation on
        # (1 - fee_on_crosschain_message_fee_fraction).
        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_crosschain_message_fee_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_crosschain_message_fee_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_crosschain_message_fee_fraction,
            classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_crosschain_message_fee_yield_pct,
            crosschain_message_fee_consumed_yield_pct,
            gross_yield_pct,
            crosschain_message_fee_rate_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_crosschain_message_fee_yield_pct": (
                round(net_of_crosschain_message_fee_yield_pct, 4)
                if net_of_crosschain_message_fee_yield_pct is not None
                else None),
            "crosschain_message_fee_consumed_yield_pct": (
                round(crosschain_message_fee_consumed_yield_pct, 4)
                if crosschain_message_fee_consumed_yield_pct is not None
                else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "fee_on_crosschain_message_fee_gap_pct": round(
                fee_on_crosschain_message_fee_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_crosschain_message_fee_fraction": round(
                fee_on_crosschain_message_fee_fraction, 4),
            "net_is_negative": net_is_negative,
            "crosschain_message_fee_rate_pct": (
                round(crosschain_message_fee_rate_pct, 4)
                if crosschain_message_fee_rate_pct is not None else None),
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
        fee_on_crosschain_message_fee_fraction: float,
        classification: str,
    ) -> float:
        """
        0–100, HIGHER = the performance fee was charged on the
        net-of-crosschain-message-fee yield the depositor actually realized: the
        depositor keeps the yield that survived the cross-chain message fee.
        Two components:
          * realisation = clamp(realization_ratio, 0, 1)
          * fee-base penalty = clamp(1 − fee_on_crosschain_message_fee_fraction, 0, 1)
        Weighted 70/30 toward realisation.
        """
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(
            1.0 - fee_on_crosschain_message_fee_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_crosschain_message_fee_fraction: float,
        net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            return "SEVERE_FEE_ON_CROSSCHAIN_MESSAGE_FEE_GAP"
        if fee_on_crosschain_message_fee_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_CROSSCHAIN_MESSAGE_FEE_BASE"
        if fee_on_crosschain_message_fee_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_CROSSCHAIN_MESSAGE_FEE_GAP"
        if fee_on_crosschain_message_fee_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_CROSSCHAIN_MESSAGE_FEE_GAP"
        return "SEVERE_FEE_ON_CROSSCHAIN_MESSAGE_FEE_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_CROSSCHAIN_MESSAGE_FEE"
        if classification == "CLEAN_NET_OF_CROSSCHAIN_MESSAGE_FEE_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_CROSSCHAIN_MESSAGE_FEE_GAP":
            return "MINOR_FEE_ON_CROSSCHAIN_MESSAGE_FEE"
        if classification == "MODERATE_FEE_ON_CROSSCHAIN_MESSAGE_FEE_GAP":
            return "DEMAND_NET_OF_CROSSCHAIN_MESSAGE_FEE_BASE"
        # SEVERE_FEE_ON_CROSSCHAIN_MESSAGE_FEE_GAP
        return "AVOID_FEE_ON_CROSSCHAIN_MESSAGE_FEE"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_crosschain_message_fee_yield_pct: Optional[float],
        crosschain_message_fee_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        crosschain_message_fee_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        flags.append(classification)

        if classification == "CLEAN_NET_OF_CROSSCHAIN_MESSAGE_FEE_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (crosschain_message_fee_rate_pct is not None
                and crosschain_message_fee_rate_pct
                >= HIGH_CROSSCHAIN_MESSAGE_FEE_PCT):
            flags.append("HIGH_CROSSCHAIN_MESSAGE_FEE")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            # Geometry-only flags are NOT meaningful on the override path.
            if (crosschain_message_fee_consumed_yield_pct is not None
                    and crosschain_message_fee_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_CROSSCHAIN_MESSAGE_FEE")
            if (net_of_crosschain_message_fee_yield_pct is not None
                    and net_of_crosschain_message_fee_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_CROSSCHAIN_MESSAGE_FEE")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_crosschain_message_fee_yield_pct": None,
            "crosschain_message_fee_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "fee_on_crosschain_message_fee_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_crosschain_message_fee_fraction": None,
            "net_is_negative": False,
            "crosschain_message_fee_rate_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_CROSSCHAIN_MESSAGE_FEE",
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
                "worst_crosschain_message_fee_gap_vault": None,
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
            "worst_crosschain_message_fee_gap_vault": by_score[0]["token"],
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
            # CLEAN_NET_OF_CROSSCHAIN_MESSAGE_FEE_BASE: net ≈ gross → the
            # per-message CROSS-CHAIN MESSAGE FEE (a single messaging-protocol
            # endpoint + executor fee) consumed nothing on a 15% annual yield
            # (the per-message fee is a tiny fixed amount, net ≈ gross), the
            # performance fee was on the right base.
            "vault": "USDC-XC-Vault-CleanCrosschainMessageFee",
            "gross_yield_pct": 15.0,
            "net_of_crosschain_message_fee_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "crosschain_message_fee_rate_pct": 0.05,
        },
        {
            # MODERATE_FEE_ON_CROSSCHAIN_MESSAGE_FEE_GAP: gross 14, net 7 →
            # ~half the performance fee was charged on the message-fee slice
            # (fraction ≈ 0.5).
            "vault": "CRV-XC-Vault-ModerateCrosschainMessageFee",
            "gross_yield_pct": 14.0,
            "net_of_crosschain_message_fee_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "crosschain_message_fee_rate_pct": 0.2,
        },
        {
            # SEVERE_FEE_ON_CROSSCHAIN_MESSAGE_FEE_GAP (net negative): the vault
            # steers a remote sleeve and sends many cross-chain harvest/rebalance
            # messages, each charging a per-message CROSS-CHAIN MESSAGE FEE
            # (endpoint + executor / CCIP / interchain-gas payment) to deliver
            # the instruction, and the cumulative message fee pushed net yield
            # negative — yet the performance fee is still charged on gross yield.
            "vault": "BAL-XC-Vault-SevereCrosschainMessageFee",
            "gross_yield_pct": 10.0,
            "net_of_crosschain_message_fee_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "crosschain_message_fee_rate_pct": 0.6,
        },
        {
            # Override path: fee-on-crosschain-message-fee gap supplied directly.
            # gap 4.8, fee_charged 12 → fraction 0.4 → MODERATE.
            "vault": "UNI-XC-Vault-OverrideCrosschainMessageFeeGap",
            "gross_yield_pct": 20.0,
            "fee_on_crosschain_message_fee_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            # INSUFFICIENT_DATA: no gross yield supplied.
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_crosschain_message_fee_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1238 Vault Performance-Fee "
            "Gross-Of-Crosschain-Message-Fee-Base Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeGrossOfCrosschainMessageFeeBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
