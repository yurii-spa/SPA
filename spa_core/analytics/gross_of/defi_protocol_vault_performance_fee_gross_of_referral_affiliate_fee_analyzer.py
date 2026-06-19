"""
MP-1251: GrossOfReferralAffiliateFeeAnalyzer
================================================================================
Advisory/read-only analytics module.

Many DeFi protocols offer referral or affiliate programs (Morpho referral fee,
Aave V3 referral code, Curve gauge vote-routing referral kickback, Pendle
referral, 1inch affiliate fee, etc.) that reward integrators or front-end
operators for directing deposits and trades to the protocol. The fee is
typically a basis-point cut deducted from GROSS yield before performance fee
is calculated, or charged on trade volume routed through the affiliate
channel. Over continuous deposit / compounding cycles these referral &
affiliate fees accumulate into a drag on the depositor's net yield.

This is NOT a protocol_revenue_share (platform cut from total protocol
revenue to the DAO treasury or token stakers), NOT a curator_fee (risk
curator compensation for vault curation), NOT a vote_incentive_fee (bribe or
gauge-vote incentive), and NOT a management / keeper / harvest bounty fee.

Economically, the depositor's NET yield is:

    net_of_ref_aff_yield = gross_yield - cumulative_referral_affiliate_fee

But many vaults charge the performance fee on the GROSS yield (before netting
the referral/affiliate fee drag), not on the net-of-referral-affiliate yield
the depositor economically realized. The result is a "fee-on-referral-fee" /
fee-base inflation: the performance fee is levied on the yield slice the
referral/affiliate fees already erased. The fair performance fee would be
levied only on the net-of-referral-affiliate yield:

    fee_frac                          = clamp(perf_fee_pct / 100, 0, 1)
    ref_aff_consumed_yield_pct        = max(0, gross - net_of_ref_aff)
    fee_charged_pct                   = fee_frac * max(0, gross)
    fair_fee_pct                      = fee_frac * max(0, net_of_ref_aff)
    ref_aff_gap_pct                   = max(0, fee_charged - fair_fee)
    net_return_after_fee_pct          = net_of_ref_aff - fee_charged
    net_return_fair_pct               = net_of_ref_aff - fair_fee
    overstatement_pct                 = ref_aff_gap_pct
    fee_on_ref_aff_fraction           = clamp(gap / fee_charged, 0, 1)
    realization_ratio                 = clamp(net_after / net_fair, 0, 1)

HIGHER score = the performance fee was charged on the net-of-referral-
affiliate base (gross ≈ net_of_ref_aff), the fee was effectively fair.
LOWER score = a large share of the performance fee landed on the referral/
affiliate fee slice, or the net return goes negative after the fee.

Override path (when ref_aff_gap_pct is supplied directly, finite, AND a
valid POSITIVE gross_yield_pct and POSITIVE fee_charged_pct are present):
take the gap verbatim (negative -> magnitude) and skip the net-of-ref-aff
geometry — fee_on_ref_aff_fraction and the metrics are computed the same way:

    fee_on_ref_aff_fraction = clamp(gap / fee_charged_pct, 0, 1)

(On the override path the net-of-ref-aff / ref-aff-slice / fair geometry is
not known -> those fields are reported as None, and the geometry-only flags
FEE_ON_REF_AFF / FULL_FEE_ON_REF_AFF / NET_NEGATIVE_AFTER_FEE are NOT
raised; realization_ratio is anchored to (1 - fee_on_ref_aff_fraction).)

Distinct from (this is the GROSS-OF-REFERRAL-AFFILIATE-FEE performance-fee
BASE — the fee being charged on the gross yield before the referral or
affiliate program fee paid to integrators / front-end operators is netted
out, not a protocol revenue share, not a curator compensation, not a gauge
vote incentive bribe, not another cost layer):
  * defi_protocol_vault_performance_fee_gross_of_referral_fee_base_gap_analyzer
    — that module prices a PROTOCOL-LEVEL referral code discount or referral
    fee that the protocol itself charges on a specific deposit/trade event.
    HERE the referral/affiliate fee is the AFFILIATE PROGRAM fee paid to
    third-party integrators or front-end operators (e.g. 1inch affiliate
    fee, Morpho Points-based referral kickback to integrators, Aave V3
    integrator referral code fee, Curve gauge-routing affiliate kickback)
    — a distinct fee layer from the protocol's own referral mechanism.
  * defi_protocol_vault_performance_fee_gross_of_curator_fee_base_gap_analyzer
    — that prices the risk curator's vault curation fee. HERE it is the
    affiliate/referral program fee, not curator compensation.
  * defi_protocol_vault_performance_fee_gross_of_vote_incentive_fee_base_gap_analyzer
    — that prices gauge-vote bribe incentive. HERE it is the affiliate/
    referral program fee, not a bribe or vote incentive.
  * defi_protocol_vault_performance_fee_gross_of_management_fee /
    keeper_fee / harvest_bounty / insurance_fund_premium / reserve_contribution
    base gap analyzers — those price AUM fee, automation upkeep, harvest
    bounty, insurance premium, or protocol reserve. None is the affiliate/
    referral program fee.
  * defi_protocol_vault_performance_fee_gross_of_swap_fee / lp_amm_fee_drag /
    bridge_fee / crosschain_message_fee / flash_loan_fee base gap analyzers
    — those price swap, LP AMM, bridge, messaging, or flash-loan costs.
    None is the affiliate/referral program fee.
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer and related
    performance-fee mechanic modules — those measure HWM/crystallization
    fairness. HERE the axis is the fee-BASE inflation from charging the
    performance fee on gross (pre-referral-affiliate-fee) yield, not HWM or
    crystallization mechanics.

The novel axis here: the performance-fee BASE being GROSS-OF-REFERRAL-
AFFILIATE-FEE rather than NET-OF-REFERRAL-AFFILIATE-FEE — a fee-on-
referral-affiliate-fee / fee-base inflation in which the performance fee
is charged on the slice of yield the referral/affiliate program fee
already consumed.

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
    "vault_performance_fee_gross_of_referral_affiliate_fee_log.json"
)
LOG_CAP = 100

CLEAN_FRACTION = 0.05
MILD_FRACTION = 0.20
MODERATE_FRACTION = 0.50

HIGH_REF_AFF_FEE_PCT = 0.50

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

class GrossOfReferralAffiliateFeeAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the referral/affiliate program fee — the fee paid to third-
    party integrators, front-end operators, or affiliate partners for routing
    deposits and trades to the protocol — is netted out) and the FAIR fee it
    would charge on the NET-OF-REFERRAL-AFFILIATE-FEE yield the depositor
    economically realized, and the share of the charged performance fee that
    therefore landed on the referral/affiliate fee slice of the yield (a
    fee-on-referral-affiliate-fee / fee-base inflation).

    HIGHER score = the performance fee was charged on the net-of-referral-
    affiliate base (gross ≈ net_of_ref_aff), effectively fair.
    LOWER score = a large share of the performance fee landed on the
    referral/affiliate fee slice the depositor never realized.

    Per-position input dict fields:
        vault / token                       : str
        gross_yield_pct                     : float — GROSS yield before
                                              referral/affiliate fee.
                                              REQUIRED, finite POSITIVE.
        net_of_ref_aff_fee_yield_pct        : float — yield NET OF referral/
                                              affiliate fee. May be < gross,
                                              may be negative. Default 0.0.
        performance_fee_pct                 : float — performance-fee rate %.
                                              REQUIRED on main path (finite).
        ref_aff_fee_rate_pct                : float — OPTIONAL informational
                                              referral/affiliate fee as % of
                                              position notional over the
                                              window. >= HIGH_REF_AFF_FEE_PCT
                                              raises HIGH_REF_AFF_FEE flag.
        ref_aff_gap_pct                     : float — OPTIONAL direct override
                                              of the fee-on-ref-aff gap.
        fee_charged_pct                     : float — OPTIONAL override denom
                                              (finite > 0 to take override
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

        gross_gain = _coerce_num(p.get("gross_yield_pct"))
        if gross_gain is None or not math.isfinite(gross_gain) or gross_gain <= 0.0:
            return self._insufficient(token)

        ref_aff_fee_rate = _coerce_num(p.get("ref_aff_fee_rate_pct"))

        gap_o = _coerce_num(p.get("ref_aff_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o, ref_aff_fee_rate)

        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(
            token, p, gross_gain, fee_pct, ref_aff_fee_rate)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        ref_aff_fee_rate: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        net_gain = _coerce_signed(p.get("net_of_ref_aff_fee_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        ref_aff_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        ref_aff_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_ref_aff_fee_yield_pct=net_gain,
            ref_aff_consumed_yield_pct=ref_aff_consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            ref_aff_gap_pct=ref_aff_gap_pct,
            ref_aff_fee_rate_pct=ref_aff_fee_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        ref_aff_fee_rate: Optional[float],
    ) -> dict:
        gap = min(gap, fee_charged)
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_ref_aff_fee_yield_pct=None,
            ref_aff_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            ref_aff_gap_pct=gap,
            ref_aff_fee_rate_pct=ref_aff_fee_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_ref_aff_fee_yield_pct: Optional[float],
        ref_aff_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        ref_aff_gap_pct: float,
        ref_aff_fee_rate_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        overstatement_pct = ref_aff_gap_pct

        if net_of_ref_aff_fee_yield_pct is not None:
            net_return_after_fee_pct = (
                net_of_ref_aff_fee_yield_pct - fee_charged_pct)
            net_return_fair_pct = (
                net_of_ref_aff_fee_yield_pct - fair_fee_pct)
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
            fee_on_ref_aff_fraction = _clamp(
                ref_aff_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_ref_aff_fraction = 0.0

        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_ref_aff_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_ref_aff_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_ref_aff_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_ref_aff_fee_yield_pct,
            ref_aff_consumed_yield_pct,
            gross_yield_pct,
            ref_aff_fee_rate_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_ref_aff_fee_yield_pct": (
                round(net_of_ref_aff_fee_yield_pct, 4)
                if net_of_ref_aff_fee_yield_pct is not None else None),
            "ref_aff_consumed_yield_pct": (
                round(ref_aff_consumed_yield_pct, 4)
                if ref_aff_consumed_yield_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "ref_aff_gap_pct": round(ref_aff_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_ref_aff_fraction": round(fee_on_ref_aff_fraction, 4),
            "net_is_negative": net_is_negative,
            "ref_aff_fee_rate_pct": (
                round(ref_aff_fee_rate_pct, 4)
                if ref_aff_fee_rate_pct is not None else None),
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
        fee_on_ref_aff_fraction: float,
        classification: str,
    ) -> float:
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_ref_aff_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_ref_aff_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            return "SEVERE_FEE_ON_REF_AFF_GAP"
        if fee_on_ref_aff_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_REF_AFF_BASE"
        if fee_on_ref_aff_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_REF_AFF_GAP"
        if fee_on_ref_aff_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_REF_AFF_GAP"
        return "SEVERE_FEE_ON_REF_AFF_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_REF_AFF"
        if classification == "CLEAN_NET_OF_REF_AFF_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_REF_AFF_GAP":
            return "MINOR_FEE_ON_REF_AFF"
        if classification == "MODERATE_FEE_ON_REF_AFF_GAP":
            return "DEMAND_NET_OF_REF_AFF_BASE"
        return "AVOID_FEE_ON_REF_AFF"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_ref_aff_fee_yield_pct: Optional[float],
        ref_aff_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        ref_aff_fee_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        flags.append(classification)

        if classification == "CLEAN_NET_OF_REF_AFF_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (ref_aff_fee_rate_pct is not None
                and ref_aff_fee_rate_pct >= HIGH_REF_AFF_FEE_PCT):
            flags.append("HIGH_REF_AFF_FEE")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            if (ref_aff_consumed_yield_pct is not None
                    and ref_aff_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_REF_AFF")
            if (net_of_ref_aff_fee_yield_pct is not None
                    and net_of_ref_aff_fee_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_REF_AFF")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_ref_aff_fee_yield_pct": None,
            "ref_aff_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "ref_aff_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_ref_aff_fraction": None,
            "net_is_negative": False,
            "ref_aff_fee_rate_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_REF_AFF",
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
                "worst_ref_aff_gap_vault": None,
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
            "worst_ref_aff_gap_vault": by_score[0]["token"],
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
            "vault": "USDC-RefAff-Vault-CleanFee",
            "gross_yield_pct": 15.0,
            "net_of_ref_aff_fee_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "ref_aff_fee_rate_pct": 0.05,
        },
        {
            "vault": "Morpho-RefAff-Vault-ModerateFee",
            "gross_yield_pct": 14.0,
            "net_of_ref_aff_fee_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "ref_aff_fee_rate_pct": 0.30,
        },
        {
            "vault": "1inch-RefAff-Vault-SevereFee",
            "gross_yield_pct": 10.0,
            "net_of_ref_aff_fee_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "ref_aff_fee_rate_pct": 0.80,
        },
        {
            "vault": "Aave-RefAff-Vault-OverrideGap",
            "gross_yield_pct": 20.0,
            "ref_aff_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_ref_aff_fee_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1251 Vault Performance-Fee Gross-Of-Referral-Affiliate-Fee Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = GrossOfReferralAffiliateFeeAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
