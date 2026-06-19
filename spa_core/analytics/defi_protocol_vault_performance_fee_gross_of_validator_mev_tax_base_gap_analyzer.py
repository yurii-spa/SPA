"""
MP-1239: DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer
================================================================================
Advisory/read-only analytics module.

When a block proposer (validator) participates in PBS / MEV-boost, they receive
a PROPOSER PAYMENT from the block builder — the builder's bid for the right to
construct the block.  Part of that proposer payment exceeds the vanilla base
block reward; the excess is the VALIDATOR MEV TAX — the cut the validator takes
from the MEV extracted in the block they propose.  This validator MEV tax does
NOT directly sandwich the vault's swap (that is the searcher MEV tax priced by
gross_of_mev_tax_base_gap_analyzer); instead it creates WORSE EXECUTION
INDIRECTLY: builders who must pay a large proposer payment maximise the MEV
they extract from every transaction in the block, and vaults' harvest/rebalance
swaps are among the richest targets.  The validator's cut of this extraction is
a hidden cost that degrades the effective yield the depositor receives.

Economically, the depositor's NET yield is:

    net_of_validator_mev_tax_yield = gross_yield − validator_mev_tax

But many vaults charge the performance fee on the GROSS yield (before the
VALIDATOR MEV TAX — the proposer's cut of MEV extracted via PBS/MEV-boost from
the block containing the vault's harvest/rebalance — is netted out), not on the
net-of-validator-mev-tax yield the depositor economically realized.  The result
is a "fee-on-validator-mev-tax" / fee-base inflation.  The fair performance fee
would be levied only on the net-of-validator-mev-tax yield:

    fee_frac                               = clamp(perf_fee_pct / 100, 0, 1)
    validator_mev_tax_consumed_yield_pct   = max(0, gross - net)
    fee_charged_pct                        = fee_frac * max(0, gross)
    fair_fee_pct                           = fee_frac * max(0, net)
    fee_on_validator_mev_tax_gap_pct       = max(0, fee_charged - fair_fee)
    net_return_after_fee_pct               = net - fee_charged
    net_return_fair_pct                    = net - fair_fee
    overstatement_pct                      = fee_on_validator_mev_tax_gap_pct
    fee_on_validator_mev_tax_fraction      = clamp(gap / fee_charged, 0, 1)
    realization_ratio                      = clamp(net_after / net_fair, 0, 1)

HIGHER score = the performance fee was charged on the net-of-validator-mev-tax
base (gross ≈ net), the fee was effectively fair, nothing to fix.
LOWER score = a large share of the performance fee landed on the
validator-mev-tax slice, or the net return goes negative after the fee.

Override path (when fee_on_validator_mev_tax_gap_pct is supplied directly,
finite, AND a valid POSITIVE gross_yield_pct and POSITIVE fee_charged_pct are
present): take the gap verbatim (negative → magnitude) and skip the net
geometry — fee_on_validator_mev_tax_fraction and the metrics are computed the
same way:

    fee_on_validator_mev_tax_fraction = clamp(gap / fee_charged_pct, 0, 1)

(On the override path the net / consumed / fair geometry is not known → those
fields are reported as None, and the geometry-only flags
FEE_ON_VALIDATOR_MEV_TAX / FULL_FEE_ON_VALIDATOR_MEV_TAX /
NET_NEGATIVE_AFTER_FEE are NOT raised; realization_ratio is anchored to
(1 - fee_on_validator_mev_tax_fraction).)

Distinct from (this is the GROSS-OF-VALIDATOR-MEV-TAX performance-fee BASE —
the fee being charged on the gross yield before the VALIDATOR's CUT of MEV via
PBS/MEV-boost proposer payments — not the searcher's sandwich extraction, not
execution gas, not another cost layer):
  * defi_protocol_vault_performance_fee_gross_of_mev_tax_base_gap_analyzer
    — that module prices the SEARCHER MEV TAX (sandwich / backrun extraction).
    HERE it is the VALIDATOR's / PROPOSER's cut of MEV via PBS/MEV-boost.
  * defi_protocol_vault_performance_fee_gross_of_cost /
    priority_fee / blob_fee / l1_data_fee base gap analyzers
    — those price execution gas / proposer tip / blob-gas DA posting / L1 data
    fee.  HERE it is the proposer's MEV-boost payment above the base reward.
  * defi_protocol_vault_performance_fee_gross_of_bundler_fee /
    oracle_update_fee / harvest_bounty base gap analyzers
    — those price the ERC-4337 bundler premium / oracle feed post / keeper
    bounty.  HERE it is the validator MEV tax from PBS block-building.

Chain-specific: ETH mainnet ~92% MEV-boost adoption → 5–15 bps annual validator
MEV tax on DeFi strategies.  L2s (Arbitrum, Base, Optimism) have a single
sequencer with near-zero validator MEV tax (~1 bps).

Pure stdlib, read-only/advisory, atomic ring-buffer log, sentinels (no inf/NaN).
"""

import json
import math
import os
from datetime import datetime, timezone
from typing import Dict, List, Optional

# ── constants ─────────────────────────────────────────────────────────────────
LOG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "data",
    "vault_performance_fee_gross_of_validator_mev_tax_base_gap_log.json",
)
LOG_CAP = 100

CLEAN_FRACTION = 0.05
MILD_FRACTION = 0.20
MODERATE_FRACTION = 0.50

HIGH_VALIDATOR_MEV_TAX_PCT = 0.3

EPS = 1e-12

CHAIN_MEV_TAX_BPS: Dict[str, int] = {
    "ethereum": 8,
    "arbitrum": 1,
    "base": 1,
    "optimism": 1,
}

MEV_BOOST_ADOPTION_RATE: Dict[str, float] = {
    "ethereum": 0.92,
}

PROPOSER_PAYMENT_THRESHOLD_ETH = 0.01


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


def estimate_annual_mev_tax_bps(chain: str) -> int:
    return CHAIN_MEV_TAX_BPS.get(chain.lower(), 0)


def get_mev_boost_adoption(chain: str) -> float:
    return MEV_BOOST_ADOPTION_RATE.get(chain.lower(), 0.0)


def apply_gap(gross_yield_pct: float, validator_mev_tax_bps: float) -> float:
    tax_pct = validator_mev_tax_bps / 100.0
    return max(0.0, gross_yield_pct - tax_pct)


# ── main class ────────────────────────────────────────────────────────────────

class DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the VALIDATOR MEV TAX — the proposer's cut of MEV via
    PBS/MEV-boost — is netted out) and the FAIR fee it would charge on the
    NET-OF-VALIDATOR-MEV-TAX yield the depositor economically realized.
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

        gross_gain = _coerce_num(p.get("gross_yield_pct"))
        if gross_gain is None or not math.isfinite(gross_gain) or gross_gain <= 0.0:
            return self._insufficient(token)

        validator_mev_tax_rate = _coerce_num(p.get("validator_mev_tax_rate_pct"))

        gap_o = _coerce_num(p.get("fee_on_validator_mev_tax_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o,
                validator_mev_tax_rate)

        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(
            token, p, gross_gain, fee_pct, validator_mev_tax_rate)

    # ── main path ─────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        validator_mev_tax_rate: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        net_gain = _coerce_signed(
            p.get("net_of_validator_mev_tax_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        validator_mev_tax_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        fee_on_validator_mev_tax_gap_pct = max(
            0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_validator_mev_tax_yield_pct=net_gain,
            validator_mev_tax_consumed_yield_pct=(
                validator_mev_tax_consumed_yield_pct),
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            fee_on_validator_mev_tax_gap_pct=(
                fee_on_validator_mev_tax_gap_pct),
            validator_mev_tax_rate_pct=validator_mev_tax_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float,
        fee_charged: float, validator_mev_tax_rate: Optional[float],
    ) -> dict:
        gap = min(gap, fee_charged)
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_validator_mev_tax_yield_pct=None,
            validator_mev_tax_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            fee_on_validator_mev_tax_gap_pct=gap,
            validator_mev_tax_rate_pct=validator_mev_tax_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ───────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_validator_mev_tax_yield_pct: Optional[float],
        validator_mev_tax_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        fee_on_validator_mev_tax_gap_pct: float,
        validator_mev_tax_rate_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        overstatement_pct = fee_on_validator_mev_tax_gap_pct

        if net_of_validator_mev_tax_yield_pct is not None:
            net_return_after_fee_pct = (
                net_of_validator_mev_tax_yield_pct - fee_charged_pct)
            net_return_fair_pct = (
                net_of_validator_mev_tax_yield_pct - fair_fee_pct)
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
            fee_on_validator_mev_tax_fraction = _clamp(
                fee_on_validator_mev_tax_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_validator_mev_tax_fraction = 0.0

        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_validator_mev_tax_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_validator_mev_tax_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_validator_mev_tax_fraction,
            classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_validator_mev_tax_yield_pct,
            validator_mev_tax_consumed_yield_pct,
            gross_yield_pct,
            validator_mev_tax_rate_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4)
                if fee_frac is not None else None),
            "net_of_validator_mev_tax_yield_pct": (
                round(net_of_validator_mev_tax_yield_pct, 4)
                if net_of_validator_mev_tax_yield_pct is not None else None),
            "validator_mev_tax_consumed_yield_pct": (
                round(validator_mev_tax_consumed_yield_pct, 4)
                if validator_mev_tax_consumed_yield_pct is not None
                else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "fee_on_validator_mev_tax_gap_pct": round(
                fee_on_validator_mev_tax_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_validator_mev_tax_fraction": round(
                fee_on_validator_mev_tax_fraction, 4),
            "net_is_negative": net_is_negative,
            "validator_mev_tax_rate_pct": (
                round(validator_mev_tax_rate_pct, 4)
                if validator_mev_tax_rate_pct is not None else None),
            "sample_count": 0,
            "used_override": used_override,
            "used_main": used_main,
            "score": round(score, 2),
            "classification": classification,
            "recommendation": recommendation,
            "grade": grade,
            "flags": flags_out,
        }

    # ── scoring ───────────────────────────────────────────────────────────────

    def _score(
        self,
        realization_ratio: float,
        fee_on_validator_mev_tax_fraction: float,
        classification: str,
    ) -> float:
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(
            1.0 - fee_on_validator_mev_tax_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_validator_mev_tax_fraction: float,
        net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            return "SEVERE_FEE_ON_VALIDATOR_MEV_TAX_GAP"
        if fee_on_validator_mev_tax_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_VALIDATOR_MEV_TAX_BASE"
        if fee_on_validator_mev_tax_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_VALIDATOR_MEV_TAX_GAP"
        if fee_on_validator_mev_tax_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_VALIDATOR_MEV_TAX_GAP"
        return "SEVERE_FEE_ON_VALIDATOR_MEV_TAX_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_VALIDATOR_MEV_TAX"
        if classification == "CLEAN_NET_OF_VALIDATOR_MEV_TAX_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_VALIDATOR_MEV_TAX_GAP":
            return "MINOR_FEE_ON_VALIDATOR_MEV_TAX"
        if classification == "MODERATE_FEE_ON_VALIDATOR_MEV_TAX_GAP":
            return "DEMAND_NET_OF_VALIDATOR_MEV_TAX_BASE"
        return "AVOID_FEE_ON_VALIDATOR_MEV_TAX"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_validator_mev_tax_yield_pct: Optional[float],
        validator_mev_tax_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        validator_mev_tax_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []
        flags.append(classification)

        if classification == "CLEAN_NET_OF_VALIDATOR_MEV_TAX_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (validator_mev_tax_rate_pct is not None
                and validator_mev_tax_rate_pct >= HIGH_VALIDATOR_MEV_TAX_PCT):
            flags.append("HIGH_VALIDATOR_MEV_TAX")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            if (validator_mev_tax_consumed_yield_pct is not None
                    and validator_mev_tax_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_VALIDATOR_MEV_TAX")
            if (net_of_validator_mev_tax_yield_pct is not None
                    and net_of_validator_mev_tax_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_VALIDATOR_MEV_TAX")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_validator_mev_tax_yield_pct": None,
            "validator_mev_tax_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "fee_on_validator_mev_tax_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_validator_mev_tax_fraction": None,
            "net_is_negative": False,
            "validator_mev_tax_rate_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_VALIDATOR_MEV_TAX",
            "grade": "F",
            "flags": ["INSUFFICIENT_DATA"],
        }

    # ── aggregate ─────────────────────────────────────────────────────────────

    def _aggregate(self, results: List[dict]) -> dict:
        scored = [
            r for r in results
            if r["classification"] != "INSUFFICIENT_DATA"]
        if not scored:
            return {
                "cleanest_vault": None,
                "worst_validator_mev_tax_gap_vault": None,
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
            "worst_validator_mev_tax_gap_vault": by_score[0]["token"],
            "avg_score": round(avg, 2),
            "net_negative_count": net_negative,
            "position_count": len(results),
        }

    # ── ring-buffer log ───────────────────────────────────────────────────────

    def _write_log(
        self, results: List[dict], agg: dict, cfg: dict,
    ) -> None:
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
            "vault": "USDC-ValidatorMEV-CleanTax",
            "gross_yield_pct": 15.0,
            "net_of_validator_mev_tax_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "validator_mev_tax_rate_pct": 0.02,
        },
        {
            "vault": "CRV-ValidatorMEV-ModerateTax",
            "gross_yield_pct": 14.0,
            "net_of_validator_mev_tax_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "validator_mev_tax_rate_pct": 0.15,
        },
        {
            "vault": "BAL-ValidatorMEV-SevereTax",
            "gross_yield_pct": 10.0,
            "net_of_validator_mev_tax_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "validator_mev_tax_rate_pct": 0.5,
        },
        {
            "vault": "UNI-ValidatorMEV-Override",
            "gross_yield_pct": 20.0,
            "fee_on_validator_mev_tax_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_validator_mev_tax_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1239 Vault Performance-Fee Gross-Of-Validator-Mev-Tax-Base "
            "Gap Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = (
        DeFiProtocolVaultPerformanceFeeGrossOfValidatorMevTaxBaseGapAnalyzer())
    result = analyzer.analyze_portfolio(
        _demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
