"""
MP-1240: SequencerTipGapAnalyzer
================================================================================
Advisory/read-only analytics module.

On L2 networks (Arbitrum, Optimism, Base, Scroll, zkSync) the SEQUENCER
charges a PRIORITY TIP on every transaction — a per-tx fee paid to the
centralised sequencer operator ON TOP OF the L1 data-availability cost
(calldata / blob posting fee) and the base execution gas.  DeFi vault
harvest and rebalance transactions pay this tip, but performance fees are
typically charged on the yield GROSS OF the sequencer tip cost.

The depositor's NET yield after the sequencer tip is:

    net_of_tip_yield = gross_yield − sequencer_tip_drag

But many vaults charge the performance fee on GROSS yield (before netting
the sequencer tip), creating a fee-on-tip / fee-base inflation:

    fee_frac                     = clamp(performance_fee_pct / 100, 0, 1)
    tip_consumed_yield_pct       = max(0, gross_yield - net_of_tip_yield)
    fee_charged_pct              = fee_frac * max(0, gross_yield)
    fair_fee_pct                 = fee_frac * max(0, net_of_tip_yield)
    fee_on_tip_gap_pct           = max(0, fee_charged - fair_fee)
    net_return_after_fee_pct     = net_of_tip_yield - fee_charged
    net_return_fair_pct          = net_of_tip_yield - fair_fee
    overstatement_pct            = fee_on_tip_gap_pct
    fee_on_tip_fraction          = clamp(gap / fee_charged, 0, 1)
    realization_ratio            = clamp(net_after_fee / net_fair, 0, 1)

HIGHER score = the performance fee was charged on the net-of-tip base
(gross ≈ net_of_tip), the fee was effectively fair, nothing to fix.
LOWER score = a large share of the performance fee landed on the
sequencer-tip slice, or the net return goes negative after the fee.

On Ethereum mainnet there is NO sequencer (validators, not a sequencer),
so sequencer tip = 0 and the gap is structurally absent.  This module
distinguishes L2 sequencer chains from L1/validator chains.

Distinct from:
  * gross_of_priority_fee — that is the EIP-1559 PRIORITY FEE / VALIDATOR
    TIP on L1 Ethereum (a per-gas tip to the block proposer).  HERE it is
    the L2 SEQUENCER TIP charged by the centralised sequencer operator on
    L2 rollups, a SEPARATE fee layer.
  * gross_of_cost / gross_of_l1_data_fee — those price the L1 base
    execution gas or L1 data-availability posting fee.  HERE it is the
    SEQUENCER-SPECIFIC tip on L2.
  * gross_of_bridge_fee — that prices the cross-chain bridge transfer fee.
    HERE it is the per-tx sequencer tip, not a bridge fee.

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import List, Optional

from spa_core.analytics.gross_of.sequencer_tip_config import (
    ANNUAL_TIP_BPS_ESTIMATE,
    CHAINS_WITH_SEQUENCER,
    CHAINS_WITHOUT_SEQUENCER,
    TX_PER_YEAR_TYPICAL,
)

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))),
    "data", "vault_performance_fee_gross_of_sequencer_tip_base_gap_log.json",
)
LOG_CAP = 100

CLEAN_FRACTION = 0.05
MILD_FRACTION = 0.20
MODERATE_FRACTION = 0.50

HIGH_TIP_BPS = 5

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


def is_sequencer_chain(chain: str) -> bool:
    return chain.lower().strip() in CHAINS_WITH_SEQUENCER


def estimate_annual_tip_bps(chain: str, tx_frequency: Optional[int] = None) -> float:
    chain_key = chain.lower().strip()
    if chain_key not in CHAINS_WITH_SEQUENCER:
        return 0.0
    base_bps = ANNUAL_TIP_BPS_ESTIMATE.get(chain_key, 1)
    if tx_frequency is not None and tx_frequency > 0:
        ratio = tx_frequency / TX_PER_YEAR_TYPICAL
        return base_bps * ratio
    return float(base_bps)


def compute_tip_drag(allocation_usd: float, annual_tip_bps: float) -> float:
    if allocation_usd <= 0 or annual_tip_bps <= 0:
        return 0.0
    return allocation_usd * annual_tip_bps / 10000.0


def apply_gap(gross_yield_pct: float, tip_bps: float) -> float:
    tip_pct = tip_bps / 100.0
    return gross_yield_pct - tip_pct


# ── main class ────────────────────────────────────────────────────────────────

class SequencerTipGapAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the L2 sequencer tip is netted out) and the FAIR fee it
    would charge on the NET-OF-SEQUENCER-TIP yield the depositor economically
    realized, and the share of the charged performance fee that therefore
    landed on the SEQUENCER-TIP slice of the yield.

    Per-position input dict fields:
        vault / token                  : str
        chain                          : str — chain name (e.g. "arbitrum",
                                         "ethereum").  Determines whether
                                         sequencer tip applies.
        gross_yield_pct                : float — REQUIRED, finite, positive.
        net_of_tip_yield_pct           : float — yield NET OF the sequencer tip.
                                         May be negative.  Default 0.0.
        performance_fee_pct            : float — performance-fee rate %.
                                         REQUIRED finite on main path.
        tip_rate_bps                   : float — OPTIONAL informational sequencer
                                         tip in basis points.
        fee_on_tip_gap_pct             : float — OPTIONAL direct override.
        fee_charged_pct                : float — OPTIONAL, for override path.
        allocation_usd                 : float — OPTIONAL position size in USD.
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

    # ── per-position ──────────────────────────────────────────────────────────

    def _analyze_one(self, p: dict) -> dict:
        token = p.get("vault", p.get("token", "UNKNOWN"))
        chain = str(p.get("chain", "")).lower().strip()

        gross_gain = _coerce_num(p.get("gross_yield_pct"))
        if gross_gain is None or not math.isfinite(gross_gain) or gross_gain <= 0.0:
            return self._insufficient(token, chain)

        tip_rate_bps = _coerce_num(p.get("tip_rate_bps"))
        allocation_usd = _coerce_num(p.get("allocation_usd"))

        if chain and chain in CHAINS_WITHOUT_SEQUENCER:
            return self._no_sequencer(token, chain, gross_gain, tip_rate_bps,
                                      allocation_usd, p)

        gap_o = _coerce_num(p.get("fee_on_tip_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, chain, gross_gain, abs(gap_o), fee_charged_o,
                tip_rate_bps, allocation_usd)

        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token, chain)

        return self._analyze_main(
            token, chain, p, gross_gain, fee_pct, tip_rate_bps, allocation_usd)

    # ── no-sequencer path (ETH mainnet) ──────────────────────────────────────

    def _no_sequencer(
        self, token: str, chain: str, gross_gain: float,
        tip_rate_bps: Optional[float], allocation_usd: Optional[float],
        p: dict,
    ) -> dict:
        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0) if fee_pct is not None else None
        fee_charged = fee_frac * max(0.0, gross_gain) if fee_frac is not None else None
        return {
            "token": token,
            "chain": chain,
            "has_sequencer": False,
            "gross_yield_pct": round(gross_gain, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_tip_yield_pct": round(gross_gain, 4),
            "tip_consumed_yield_pct": 0.0,
            "fee_charged_pct": round(fee_charged, 4) if fee_charged is not None else None,
            "fair_fee_pct": round(fee_charged, 4) if fee_charged is not None else None,
            "fee_on_tip_gap_pct": 0.0,
            "net_return_after_fee_pct": (
                round(gross_gain - fee_charged, 4) if fee_charged is not None else None),
            "net_return_fair_pct": (
                round(gross_gain - fee_charged, 4) if fee_charged is not None else None),
            "overstatement_pct": 0.0,
            "realization_ratio": 1.0,
            "fee_on_tip_fraction": 0.0,
            "net_is_negative": False,
            "tip_rate_bps": (
                round(tip_rate_bps, 4) if tip_rate_bps is not None else None),
            "tip_drag_usd": 0.0,
            "annual_tip_bps_estimate": 0.0,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 100.0,
            "classification": "NO_SEQUENCER",
            "recommendation": "NO_ACTION_NEEDED",
            "grade": "A",
            "flags": ["NO_SEQUENCER"],
        }

    # ── main path ─────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, chain: str, p: dict, gross_gain: float,
        fee_pct: float, tip_rate_bps: Optional[float],
        allocation_usd: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        net_gain = _coerce_signed(p.get("net_of_tip_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        tip_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        fee_on_tip_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        annual_est = estimate_annual_tip_bps(chain) if chain else 0.0
        tip_drag = (
            compute_tip_drag(allocation_usd, annual_est)
            if allocation_usd is not None and allocation_usd > 0 else 0.0)

        return self._finish(
            token=token,
            chain=chain,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_tip_yield_pct=net_gain,
            tip_consumed_yield_pct=tip_consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            fee_on_tip_gap_pct=fee_on_tip_gap_pct,
            tip_rate_bps=tip_rate_bps,
            allocation_usd=allocation_usd,
            annual_tip_bps_estimate=annual_est,
            tip_drag_usd=tip_drag,
            used_override=False,
            used_main=True,
        )

    # ── override path ────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, chain: str, gross_gain: float, gap: float,
        fee_charged: float, tip_rate_bps: Optional[float],
        allocation_usd: Optional[float],
    ) -> dict:
        gap = min(gap, fee_charged)
        annual_est = estimate_annual_tip_bps(chain) if chain else 0.0
        tip_drag = (
            compute_tip_drag(allocation_usd, annual_est)
            if allocation_usd is not None and allocation_usd > 0 else 0.0)
        return self._finish(
            token=token,
            chain=chain,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_tip_yield_pct=None,
            tip_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            fee_on_tip_gap_pct=gap,
            tip_rate_bps=tip_rate_bps,
            allocation_usd=allocation_usd,
            annual_tip_bps_estimate=annual_est,
            tip_drag_usd=tip_drag,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ──────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        chain: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_tip_yield_pct: Optional[float],
        tip_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        fee_on_tip_gap_pct: float,
        tip_rate_bps: Optional[float],
        allocation_usd: Optional[float],
        annual_tip_bps_estimate: float,
        tip_drag_usd: float,
        used_override: bool,
        used_main: bool,
    ) -> dict:
        overstatement_pct = fee_on_tip_gap_pct

        if net_of_tip_yield_pct is not None:
            net_return_after_fee_pct = net_of_tip_yield_pct - fee_charged_pct
            net_return_fair_pct = net_of_tip_yield_pct - fair_fee_pct
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
            fee_on_tip_fraction = _clamp(
                fee_on_tip_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_tip_fraction = 0.0

        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_tip_fraction, 0.0, 1.0)

        has_sequencer = bool(chain and chain in CHAINS_WITH_SEQUENCER)

        classification = self._classify(fee_on_tip_fraction, net_is_negative)
        score = self._score(realization_ratio, fee_on_tip_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification, net_is_negative, net_of_tip_yield_pct,
            tip_consumed_yield_pct, gross_yield_pct, tip_rate_bps,
            used_override, has_sequencer)

        return {
            "token": token,
            "chain": chain,
            "has_sequencer": has_sequencer,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_tip_yield_pct": (
                round(net_of_tip_yield_pct, 4)
                if net_of_tip_yield_pct is not None else None),
            "tip_consumed_yield_pct": (
                round(tip_consumed_yield_pct, 4)
                if tip_consumed_yield_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "fee_on_tip_gap_pct": round(fee_on_tip_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_tip_fraction": round(fee_on_tip_fraction, 4),
            "net_is_negative": net_is_negative,
            "tip_rate_bps": (
                round(tip_rate_bps, 4) if tip_rate_bps is not None else None),
            "tip_drag_usd": round(tip_drag_usd, 2),
            "annual_tip_bps_estimate": round(annual_tip_bps_estimate, 4),
            "sample_count": 0,
            "used_override": used_override,
            "used_main": used_main,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags_out,
        }

    # ── scoring ──────────────────────────────────────────────────────────────

    def _score(
        self,
        realization_ratio: float,
        fee_on_tip_fraction: float,
        classification: str,
    ) -> float:
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_tip_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_tip_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            return "SEVERE_FEE_ON_TIP_GAP"
        if fee_on_tip_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_TIP_BASE"
        if fee_on_tip_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_TIP_GAP"
        if fee_on_tip_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_TIP_GAP"
        return "SEVERE_FEE_ON_TIP_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_TIP"
        if classification == "CLEAN_NET_OF_TIP_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_TIP_GAP":
            return "MINOR_FEE_ON_TIP"
        if classification == "MODERATE_FEE_ON_TIP_GAP":
            return "DEMAND_NET_OF_TIP_BASE"
        return "AVOID_FEE_ON_TIP"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_tip_yield_pct: Optional[float],
        tip_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        tip_rate_bps: Optional[float],
        used_override: bool,
        has_sequencer: bool,
    ) -> List[str]:
        flags: List[str] = []
        flags.append(classification)

        if classification == "CLEAN_NET_OF_TIP_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (tip_rate_bps is not None and tip_rate_bps >= HIGH_TIP_BPS):
            flags.append("HIGH_SEQUENCER_TIP")

        if not has_sequencer:
            flags.append("NO_SEQUENCER_ON_CHAIN")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            if (tip_consumed_yield_pct is not None
                    and tip_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_TIP")
            if (net_of_tip_yield_pct is not None
                    and net_of_tip_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_TIP")

        return flags

    def _insufficient(self, token: str, chain: str) -> dict:
        return {
            "token": token,
            "chain": chain,
            "has_sequencer": bool(chain and chain in CHAINS_WITH_SEQUENCER),
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_tip_yield_pct": None,
            "tip_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "fee_on_tip_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_tip_fraction": None,
            "net_is_negative": False,
            "tip_rate_bps": None,
            "tip_drag_usd": 0.0,
            "annual_tip_bps_estimate": 0.0,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_TIP",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results
            if r["classification"] not in ("INSUFFICIENT_DATA", "NO_SEQUENCER")]
        if not scored:
            return {
                "cleanest_vault": None,
                "worst_tip_gap_vault": None,
                "avg_score": 0.0,
                "net_negative_count": 0,
                "position_count": len(results),
                "total_tip_drag_usd": sum(
                    r.get("tip_drag_usd", 0.0) for r in results),
            }
        by_score = sorted(scored, key=lambda r: r["score"])
        avg = _mean([r["score"] for r in scored])
        net_negative = sum(
            1 for r in results
            if "NET_NEGATIVE_AFTER_FEE" in r.get("flags", []))
        return {
            "cleanest_vault": by_score[-1]["token"],
            "worst_tip_gap_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "net_negative_count": net_negative,
            "position_count": len(results),
            "total_tip_drag_usd": round(
                sum(r.get("tip_drag_usd", 0.0) for r in results), 2),
        }

    # ── ring-buffer log ──────────────────────────────────────────────────────

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
                    "chain": r.get("chain", ""),
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
            "vault": "USDC-Base-Vault-CleanTip",
            "chain": "base",
            "gross_yield_pct": 15.0,
            "net_of_tip_yield_pct": 14.97,
            "performance_fee_pct": 20.0,
            "tip_rate_bps": 1.0,
            "allocation_usd": 50000.0,
        },
        {
            "vault": "CRV-Arbitrum-Vault-ModerateTip",
            "chain": "arbitrum",
            "gross_yield_pct": 14.0,
            "net_of_tip_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "tip_rate_bps": 3.0,
            "allocation_usd": 30000.0,
        },
        {
            "vault": "BAL-Optimism-Vault-SevereTip",
            "chain": "optimism",
            "gross_yield_pct": 10.0,
            "net_of_tip_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "tip_rate_bps": 8.0,
            "allocation_usd": 20000.0,
        },
        {
            "vault": "WETH-Mainnet-Vault-NoSequencer",
            "chain": "ethereum",
            "gross_yield_pct": 12.0,
            "performance_fee_pct": 20.0,
            "allocation_usd": 40000.0,
        },
        {
            "vault": "UNI-Scroll-Vault-Override",
            "chain": "scroll",
            "gross_yield_pct": 20.0,
            "fee_on_tip_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
            "allocation_usd": 10000.0,
        },
        {
            "vault": "MYSTERY-Vault-NoData",
            "chain": "arbitrum",
            "performance_fee_pct": 20.0,
            "net_of_tip_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description="MP-1240 SequencerTipGapAnalyzer"
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = SequencerTipGapAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
