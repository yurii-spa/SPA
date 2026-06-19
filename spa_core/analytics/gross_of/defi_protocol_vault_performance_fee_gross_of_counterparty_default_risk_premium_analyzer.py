"""
MP-1254: GrossOfCounterpartyDefaultRiskPremiumAnalyzer
================================================================================
Advisory/read-only analytics module.

When a DeFi vault holds assets that depend on a counterparty's solvency — e.g.,
USDC (Circle's reserve backing), USDT (Tether's commercial paper reserves),
cbETH (Coinbase custodial risk), wBTC (BitGo custodial risk), stETH (Lido
operator set risk), sDAI (MakerDAO surplus buffer adequacy), FRAX (Frax protocol
algorithmic peg risk) — the depositor implicitly bears counterparty default risk.
If Circle becomes insolvent, USDC depegs; if Tether's reserves are insufficient,
USDT depegs; if Coinbase loses custody of underlying ETH, cbETH loses value.
The gross yield on these vaults implicitly compensates depositors for bearing
this counterparty default risk — the risk premium represents the expected loss
from counterparty failure, which should be deducted from GROSS yield before
computing the performance fee. But the performance fee is typically charged on
the GROSS yield (before the counterparty default risk premium is netted out),
not on the risk-adjusted yield the depositor economically realized. The result
is a "fee-on-risk-premium" / fee-base inflation: the performance fee is levied
on the yield slice that compensates depositors for bearing counterparty default
risk.

    net_of_cp_default_yield   = gross_yield - counterparty_default_risk_premium
    fee_frac                  = clamp(performance_fee_pct / 100, 0, 1)
    fee_charged_pct           = fee_frac * max(0, gross_yield)
    fair_fee_pct              = fee_frac * max(0, net_of_cp_default_yield)
    cp_default_gap_pct        = max(0, fee_charged - fair_fee)
    net_return_after_fee_pct  = net_of_cp_default_yield - fee_charged
    net_return_fair_pct       = net_of_cp_default_yield - fair_fee
    overstatement_pct         = cp_default_gap_pct
    fee_on_cp_default_fraction = clamp(gap / fee_charged, 0, 1)
    realization_ratio         = clamp(net_after_fee / net_fair, 0, 1)

HIGHER score = the performance fee was charged on the net-of-counterparty-
default-risk-premium base (gross ≈ net_of_cp_default), the fee was effectively
fair.
LOWER score = a large share of the performance fee landed on the counterparty
default risk premium slice, or the net return goes negative after the fee.

Override path (when counterparty_default_risk_premium_gap_pct is supplied
directly, finite, AND a valid POSITIVE gross_yield_pct and POSITIVE
fee_charged_pct are present): take the gap verbatim (negative -> magnitude)
and skip the net-of-cp-default geometry — fee_on_cp_default_fraction and
the metrics are computed the same way:

    fee_on_cp_default_fraction = clamp(gap / fee_charged_pct, 0, 1)

Distinct from (this is the GROSS-OF-COUNTERPARTY-DEFAULT-RISK-PREMIUM
performance-fee BASE — the fee being charged on the gross yield before the
implicit counterparty default risk premium is netted out, not smart contract
code bug risk, not governance attack risk, not oracle manipulation risk, not
a gas cost):
  * defi_protocol_vault_performance_fee_gross_of_smart_contract_risk_premium_base_gap
    — that module prices the implicit risk premium for smart contract code
    bugs/exploits. HERE the counterparty default risk premium is the risk
    compensation for bearing counterparty solvency/custody risk, not code risk.
  * defi_protocol_vault_performance_fee_gross_of_governance_attack_risk_premium
    — that module prices the implicit risk premium for governance voting attack
    risk. HERE it is counterparty default/solvency risk, not governance risk.
  * defi_protocol_vault_performance_fee_gross_of_oracle_manipulation_risk_premium
    — that module prices the implicit risk premium for oracle price feed
    manipulation risk. HERE it is counterparty default risk, not oracle risk.
  * defi_protocol_vault_performance_fee_gross_of_regulatory_risk_premium_base_gap
    — that module prices the implicit risk premium for legal/regulatory risk.
    HERE it is counterparty default/solvency risk, not regulatory risk.
  * defi_protocol_vault_performance_fee_gross_of_oracle_update_fee_base_gap
    — that module prices the per-tx gas cost of pushing a fresh on-chain price
    (Pyth updatePriceFeeds, Wormhole VAA verification). HERE the counterparty
    default risk premium is the IMPLICIT risk compensation for bearing
    counterparty solvency risk, not a gas cost.
  * defi_protocol_vault_performance_fee_gross_of_flash_loan_fee_base_gap
    — that module prices the flash-loan fee (Aave 0.09%, dYdX 0%). HERE it
    is the risk premium for counterparty default, not a flash-loan borrowing fee.
  * defi_protocol_vault_performance_fee_gross_of_exit_slippage_base_gap
    — that module prices exit price impact / slippage. HERE it is the
    counterparty default risk premium, not market impact on exit.
  * defi_protocol_vault_performance_fee_gross_of_mev_tax_base_gap
    — that module prices MEV extraction (sandwich, JIT, backrun). HERE it is
    the implicit risk premium for counterparty default, not value extracted
    by MEV searchers.
  * defi_protocol_vault_performance_fee_gross_of_keeper_fee / management_fee /
    priority_fee / blob_fee / base_fee / l1_data_fee / bundler_fee /
    bridge_fee / crosschain_message_fee / insurance_fund_premium /
    reserve_contribution / borrow_cost / funding_cost / rebalancing_cost /
    lp_amm_fee_drag / swap_fee / curator_fee / avs_operator_fee /
    intent_solver_fee / early_withdrawal_penalty / lst_peg_slippage base gap
    analyzers — each prices a DIFFERENT cost layer. None is the implicit
    counterparty default risk premium.
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer
    — measures HWM/crystallization fairness. HERE the axis is fee-BASE
    inflation from charging on gross (pre-counterparty-default-risk-premium)
    yield.

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
    "vault_performance_fee_gross_of_counterparty_default_risk_premium_log.json"
)
LOG_CAP = 100

CLEAN_FRACTION = 0.05
MILD_FRACTION = 0.20
MODERATE_FRACTION = 0.50

HIGH_COUNTERPARTY_DEFAULT_RISK_PREMIUM_PCT = 0.25

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

class GrossOfCounterpartyDefaultRiskPremiumAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the implicit counterparty default risk premium — the risk
    compensation depositors earn for bearing counterparty solvency/custody risk
    when the vault holds assets like USDC (Circle), USDT (Tether), cbETH
    (Coinbase), wBTC (BitGo), stETH (Lido), or FRAX — is netted out) and the
    FAIR fee it would charge on the NET-OF-COUNTERPARTY-DEFAULT-RISK-PREMIUM
    yield the depositor risk-adjusted, and the share of the charged performance
    fee that therefore landed on the counterparty default risk premium slice of
    the yield.

    HIGHER score = the performance fee was charged on the net-of-counterparty-
    default-risk-premium base (gross ≈ net), effectively fair.
    LOWER score = a large share of the performance fee landed on the counterparty
    default risk premium slice the depositor bore as risk compensation.
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

        cp_default_rate = _coerce_num(p.get("counterparty_default_risk_premium_rate_pct"))

        gap_o = _coerce_num(p.get("counterparty_default_risk_premium_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o, cp_default_rate)

        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(
            token, p, gross_gain, fee_pct, cp_default_rate)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        cp_default_rate: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        net_gain = _coerce_signed(p.get("net_of_counterparty_default_risk_premium_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        cp_default_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        cp_default_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_cp_default_yield_pct=net_gain,
            cp_default_consumed_yield_pct=cp_default_consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            cp_default_gap_pct=cp_default_gap_pct,
            cp_default_rate_pct=cp_default_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        cp_default_rate: Optional[float],
    ) -> dict:
        gap = min(gap, fee_charged)
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_cp_default_yield_pct=None,
            cp_default_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            cp_default_gap_pct=gap,
            cp_default_rate_pct=cp_default_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_cp_default_yield_pct: Optional[float],
        cp_default_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        cp_default_gap_pct: float,
        cp_default_rate_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        overstatement_pct = cp_default_gap_pct

        if net_of_cp_default_yield_pct is not None:
            net_return_after_fee_pct = (
                net_of_cp_default_yield_pct - fee_charged_pct)
            net_return_fair_pct = (
                net_of_cp_default_yield_pct - fair_fee_pct)
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
            fee_on_cp_default_fraction = _clamp(
                cp_default_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_cp_default_fraction = 0.0

        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_cp_default_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_cp_default_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_cp_default_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_cp_default_yield_pct,
            cp_default_consumed_yield_pct,
            gross_yield_pct,
            cp_default_rate_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_counterparty_default_risk_premium_yield_pct": (
                round(net_of_cp_default_yield_pct, 4)
                if net_of_cp_default_yield_pct is not None else None),
            "counterparty_default_risk_premium_consumed_yield_pct": (
                round(cp_default_consumed_yield_pct, 4)
                if cp_default_consumed_yield_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "counterparty_default_risk_premium_gap_pct": round(cp_default_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_counterparty_default_risk_premium_fraction": round(fee_on_cp_default_fraction, 4),
            "net_is_negative": net_is_negative,
            "counterparty_default_risk_premium_rate_pct": (
                round(cp_default_rate_pct, 4)
                if cp_default_rate_pct is not None else None),
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
        fee_on_cp_default_fraction: float,
        classification: str,
    ) -> float:
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_cp_default_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_cp_default_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            return "SEVERE_FEE_ON_COUNTERPARTY_DEFAULT_RISK_PREMIUM_GAP"
        if fee_on_cp_default_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_COUNTERPARTY_DEFAULT_RISK_PREMIUM_BASE"
        if fee_on_cp_default_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_COUNTERPARTY_DEFAULT_RISK_PREMIUM_GAP"
        if fee_on_cp_default_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_COUNTERPARTY_DEFAULT_RISK_PREMIUM_GAP"
        return "SEVERE_FEE_ON_COUNTERPARTY_DEFAULT_RISK_PREMIUM_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_COUNTERPARTY_DEFAULT_RISK_PREMIUM"
        if classification == "CLEAN_NET_OF_COUNTERPARTY_DEFAULT_RISK_PREMIUM_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_COUNTERPARTY_DEFAULT_RISK_PREMIUM_GAP":
            return "MINOR_FEE_ON_COUNTERPARTY_DEFAULT_RISK_PREMIUM"
        if classification == "MODERATE_FEE_ON_COUNTERPARTY_DEFAULT_RISK_PREMIUM_GAP":
            return "DEMAND_NET_OF_COUNTERPARTY_DEFAULT_RISK_PREMIUM_BASE"
        return "AVOID_FEE_ON_COUNTERPARTY_DEFAULT_RISK_PREMIUM"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_cp_default_yield_pct: Optional[float],
        cp_default_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        cp_default_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        flags.append(classification)

        if classification == "CLEAN_NET_OF_COUNTERPARTY_DEFAULT_RISK_PREMIUM_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (cp_default_rate_pct is not None
                and cp_default_rate_pct >= HIGH_COUNTERPARTY_DEFAULT_RISK_PREMIUM_PCT):
            flags.append("HIGH_COUNTERPARTY_DEFAULT_RISK_PREMIUM")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            if (cp_default_consumed_yield_pct is not None
                    and cp_default_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_COUNTERPARTY_DEFAULT_RISK_PREMIUM")
            if (net_of_cp_default_yield_pct is not None
                    and net_of_cp_default_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_COUNTERPARTY_DEFAULT_RISK_PREMIUM")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_counterparty_default_risk_premium_yield_pct": None,
            "counterparty_default_risk_premium_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "counterparty_default_risk_premium_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_counterparty_default_risk_premium_fraction": None,
            "net_is_negative": False,
            "counterparty_default_risk_premium_rate_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_COUNTERPARTY_DEFAULT_RISK_PREMIUM",
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
                "worst_counterparty_default_risk_premium_gap_vault": None,
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
            "worst_counterparty_default_risk_premium_gap_vault": by_score[0]["token"],
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
            "vault": "USDC-Circle-Vault-LowCPDefault",
            "gross_yield_pct": 15.0,
            "net_of_counterparty_default_risk_premium_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "counterparty_default_risk_premium_rate_pct": 0.03,
        },
        {
            "vault": "USDT-Tether-Vault-ModerateCPDefault",
            "gross_yield_pct": 14.0,
            "net_of_counterparty_default_risk_premium_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "counterparty_default_risk_premium_rate_pct": 0.15,
        },
        {
            "vault": "wBTC-Custodial-Vault-SevereCPDefault",
            "gross_yield_pct": 10.0,
            "net_of_counterparty_default_risk_premium_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "counterparty_default_risk_premium_rate_pct": 0.5,
        },
        {
            "vault": "cbETH-Coinbase-Vault-OverrideCPGap",
            "gross_yield_pct": 20.0,
            "counterparty_default_risk_premium_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_counterparty_default_risk_premium_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1254 Vault Performance-Fee Gross-Of-Counterparty-Default-Risk-Premium Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = GrossOfCounterpartyDefaultRiskPremiumAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
