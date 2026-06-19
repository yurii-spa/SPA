"""
MP-1260: GrossOfRebalancingTransactionCostAnalyzer
================================================================================
Advisory/read-only analytics module.

When a DeFi vault rebalances its portfolio — triggered by position drift beyond
a threshold (Uniswap V3 range out-of-range, portfolio weight drift, Yearn V3
strategy migration, Balancer pool reweight) — the vault incurs transaction costs:
gas fees for on-chain execution, slippage from trading large notional through
AMM pools, and price impact from moving liquidity between positions. These
rebalancing transaction costs should be deducted from GROSS yield before the
performance fee is calculated. However, the performance fee is typically levied
on the GROSS yield (before rebalancing costs are netted out). The result is a
"fee-on-rebalancing-cost" / fee-base inflation: the performance fee is charged
on a yield figure that overstates the depositor's economic benefit by ignoring
the transaction costs consumed during rebalancing.

    net_of_rebalancing_yield = gross_yield - rebalancing_transaction_cost
    fee_frac                 = clamp(performance_fee_pct / 100, 0, 1)
    fee_charged_pct          = fee_frac * max(0, gross_yield)
    fair_fee_pct             = fee_frac * max(0, net_of_rebalancing_yield)
    rebalancing_gap_pct      = max(0, fee_charged - fair_fee)
    net_return_after_fee_pct = net_of_rebalancing_yield - fee_charged
    net_return_fair_pct      = net_of_rebalancing_yield - fair_fee
    overstatement_pct        = rebalancing_gap_pct
    fee_on_rebalancing_frac  = clamp(gap / fee_charged, 0, 1)
    realization_ratio        = clamp(net_after_fee / net_fair, 0, 1)

HIGHER score = the performance fee was charged on the net-of-rebalancing-cost
base (gross ≈ net_of_rebalancing), the fee was effectively fair.
LOWER score = a large share of the performance fee landed on the
rebalancing transaction cost slice of the yield.

Override path (when rebalancing_transaction_cost_gap_pct is supplied directly,
finite, AND a valid POSITIVE gross_yield_pct and POSITIVE fee_charged_pct are
present): take the gap verbatim (negative -> magnitude) and skip the
net-of-rebalancing geometry — fee_on_rebalancing_fraction and the metrics are
computed the same way:

    fee_on_rebalancing_fraction = clamp(gap / fee_charged_pct, 0, 1)

Distinct from (this is the GROSS-OF-REBALANCING-TRANSACTION-COST performance-fee
BASE — the fee being charged on the gross yield before the transaction costs
incurred during vault rebalancing are netted out, not a swap fee, not a gas fee,
not an LP AMM fee drag, not a liquidity mining opportunity cost):
  * defi_protocol_vault_performance_fee_gross_of_swap_fee
    — that module prices the per-trade AMM swap fee (e.g., Uniswap 0.3% fee).
    HERE the rebalancing transaction cost is the TOTAL cost of executing
    rebalancing trades (gas + slippage + price impact), not just the AMM fee.
  * defi_protocol_vault_performance_fee_gross_of_gas_fee
    — that module prices the base gas cost per transaction.
    HERE it is the aggregate transaction cost from rebalancing events, not
    the per-tx base gas cost alone.
  * defi_protocol_vault_performance_fee_gross_of_lp_amm_fee_drag
    — that module prices the ongoing LP routing drag from AMM fee tiers.
    HERE the rebalancing cost is incurred episodically when positions are
    restructured, not continuously from trade routing.
  * defi_protocol_vault_performance_fee_gross_of_liquidity_mining_opportunity_cost
    — that module prices the forgone yield from capital locked in mining.
    HERE the rebalancing cost is a realized expense from executing trades,
    not an implicit opportunity cost.
  * defi_protocol_vault_performance_fee_gross_of_exit_slippage /
    impermanent_loss_premium / funding_cost / borrow_cost /
    keeper_fee / bridge_fee / base_fee / priority_fee / blob_fee /
    l1_data_fee / bundler_fee / crosschain_message_fee / insurance_fund /
    reserve_contribution / avs_operator_fee / intent_solver_fee /
    early_withdrawal_penalty / mev_tax / flash_loan_fee /
    oracle_update_fee / deposit_fee / regulatory_risk_premium /
    governance_attack_risk_premium / curator_fee / referral_affiliate_fee /
    protocol_revenue_share / management_fee / withdrawal_delay_cost /
    yield_aggregator_platform_fee / basis_risk_premium /
    smart_contract_risk_premium / oracle_manipulation_risk_premium /
    counterparty_default_risk_premium
    base gap analyzers — each prices a DIFFERENT cost layer. None is
    the rebalancing transaction cost.
  * defi_protocol_vault_performance_fee_high_water_mark_analyzer
    — measures HWM/crystallization fairness. HERE the axis is fee-BASE
    inflation from charging on gross (pre-rebalancing-cost) yield.

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
    "vault_performance_fee_gross_of_rebalancing_transaction_cost_log.json"
)
LOG_CAP = 100

CLEAN_FRACTION = 0.05
MILD_FRACTION = 0.20
MODERATE_FRACTION = 0.50

HIGH_REBALANCING_COST_PCT = 0.25

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

class GrossOfRebalancingTransactionCostAnalyzer:
    """
    Measures the gap between the performance fee a vault charges on the GROSS
    yield (before the transaction costs incurred during portfolio rebalancing
    — gas fees, slippage, and price impact from restructuring positions when
    drift exceeds threshold — are netted out) and the FAIR fee it would charge
    on the NET-OF-REBALANCING yield the depositor economically received, and the
    share of the charged performance fee that therefore landed on the rebalancing
    transaction cost slice of the yield.

    HIGHER score = the performance fee was charged on the net-of-rebalancing
    base (gross ≈ net), effectively fair.
    LOWER score = a large share of the performance fee landed on the
    rebalancing transaction cost slice consumed by gas/slippage/price-impact.
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

        rebalancing_rate = _coerce_num(p.get("rebalancing_transaction_cost_rate_pct"))

        gap_o = _coerce_num(p.get("rebalancing_transaction_cost_gap_pct"))
        fee_charged_o = _coerce_num(p.get("fee_charged_pct"))
        if (gap_o is not None and math.isfinite(gap_o)
                and fee_charged_o is not None and math.isfinite(fee_charged_o)
                and fee_charged_o > 0.0):
            return self._analyze_override(
                token, gross_gain, abs(gap_o), fee_charged_o, rebalancing_rate)

        fee_pct = _coerce_num(p.get("performance_fee_pct"))
        if fee_pct is None or not math.isfinite(fee_pct):
            return self._insufficient(token)

        return self._analyze_main(
            token, p, gross_gain, fee_pct, rebalancing_rate)

    # ── main path ───────────────────────────────────────────────────────────────

    def _analyze_main(
        self, token: str, p: dict, gross_gain: float, fee_pct: float,
        rebalancing_rate: Optional[float],
    ) -> dict:
        fee_frac = _clamp(fee_pct / 100.0, 0.0, 1.0)

        net_gain = _coerce_signed(p.get("net_of_rebalancing_yield_pct"))
        if net_gain is None or not math.isfinite(net_gain):
            net_gain = 0.0

        rebalancing_consumed_yield_pct = max(0.0, gross_gain - net_gain)
        fee_charged_pct = fee_frac * max(0.0, gross_gain)
        fair_fee_pct = fee_frac * max(0.0, net_gain)
        rebalancing_gap_pct = max(0.0, fee_charged_pct - fair_fee_pct)

        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=fee_frac,
            net_of_rebalancing_yield_pct=net_gain,
            rebalancing_consumed_yield_pct=rebalancing_consumed_yield_pct,
            fee_charged_pct=fee_charged_pct,
            fair_fee_pct=fair_fee_pct,
            rebalancing_gap_pct=rebalancing_gap_pct,
            rebalancing_rate_pct=rebalancing_rate,
            used_override=False,
            used_main=True,
        )

    # ── override path ─────────────────────────────────────────────────────────

    def _analyze_override(
        self, token: str, gross_gain: float, gap: float, fee_charged: float,
        rebalancing_rate: Optional[float],
    ) -> dict:
        gap = min(gap, fee_charged)
        return self._finish(
            token=token,
            gross_yield_pct=gross_gain,
            fee_frac=None,
            net_of_rebalancing_yield_pct=None,
            rebalancing_consumed_yield_pct=None,
            fee_charged_pct=fee_charged,
            fair_fee_pct=max(0.0, fee_charged - gap),
            rebalancing_gap_pct=gap,
            rebalancing_rate_pct=rebalancing_rate,
            used_override=True,
            used_main=False,
        )

    # ── shared finisher ─────────────────────────────────────────────────────────

    def _finish(
        self,
        token: str,
        gross_yield_pct: float,
        fee_frac: Optional[float],
        net_of_rebalancing_yield_pct: Optional[float],
        rebalancing_consumed_yield_pct: Optional[float],
        fee_charged_pct: float,
        fair_fee_pct: float,
        rebalancing_gap_pct: float,
        rebalancing_rate_pct: Optional[float],
        used_override: bool,
        used_main: bool,
    ) -> dict:
        overstatement_pct = rebalancing_gap_pct

        if net_of_rebalancing_yield_pct is not None:
            net_return_after_fee_pct = (
                net_of_rebalancing_yield_pct - fee_charged_pct)
            net_return_fair_pct = (
                net_of_rebalancing_yield_pct - fair_fee_pct)
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
            fee_on_rebalancing_fraction = _clamp(
                rebalancing_gap_pct / fee_charged_pct, 0.0, 1.0)
        else:
            fee_on_rebalancing_fraction = 0.0

        if realization_ratio is None:
            realization_ratio = _clamp(
                1.0 - fee_on_rebalancing_fraction, 0.0, 1.0)

        classification = self._classify(
            fee_on_rebalancing_fraction, net_is_negative)
        score = self._score(
            realization_ratio, fee_on_rebalancing_fraction, classification)
        grade = _grade_from_score(score)
        recommendation = self._recommend(classification)
        flags_out = self._flags(
            classification,
            net_is_negative,
            net_of_rebalancing_yield_pct,
            rebalancing_consumed_yield_pct,
            gross_yield_pct,
            rebalancing_rate_pct,
            used_override,
        )

        return {
            "token": token,
            "gross_yield_pct": round(gross_yield_pct, 4),
            "performance_fee_pct": (
                round(fee_frac * 100.0, 4) if fee_frac is not None else None),
            "net_of_rebalancing_yield_pct": (
                round(net_of_rebalancing_yield_pct, 4)
                if net_of_rebalancing_yield_pct is not None else None),
            "rebalancing_consumed_yield_pct": (
                round(rebalancing_consumed_yield_pct, 4)
                if rebalancing_consumed_yield_pct is not None else None),
            "fee_charged_pct": round(fee_charged_pct, 4),
            "fair_fee_pct": round(fair_fee_pct, 4),
            "rebalancing_transaction_cost_gap_pct": round(rebalancing_gap_pct, 4),
            "net_return_after_fee_pct": (
                round(net_return_after_fee_pct, 4)
                if net_return_after_fee_pct is not None else None),
            "net_return_fair_pct": (
                round(net_return_fair_pct, 4)
                if net_return_fair_pct is not None else None),
            "overstatement_pct": round(overstatement_pct, 4),
            "realization_ratio": round(realization_ratio, 4),
            "fee_on_rebalancing_fraction": round(fee_on_rebalancing_fraction, 4),
            "net_is_negative": net_is_negative,
            "rebalancing_transaction_cost_rate_pct": (
                round(rebalancing_rate_pct, 4)
                if rebalancing_rate_pct is not None else None),
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
        fee_on_rebalancing_fraction: float,
        classification: str,
    ) -> float:
        if classification == "INSUFFICIENT_DATA":
            return 0.0
        realisation = _clamp(realization_ratio, 0.0, 1.0)
        fee_penalty = _clamp(1.0 - fee_on_rebalancing_fraction, 0.0, 1.0)
        return _clamp(70.0 * realisation + 30.0 * fee_penalty, 0.0, 100.0)

    def _classify(
        self, fee_on_rebalancing_fraction: float, net_is_negative: bool,
    ) -> str:
        if net_is_negative:
            return "SEVERE_FEE_ON_REBALANCING_GAP"
        if fee_on_rebalancing_fraction <= CLEAN_FRACTION:
            return "CLEAN_NET_OF_REBALANCING_BASE"
        if fee_on_rebalancing_fraction <= MILD_FRACTION:
            return "MILD_FEE_ON_REBALANCING_GAP"
        if fee_on_rebalancing_fraction <= MODERATE_FRACTION:
            return "MODERATE_FEE_ON_REBALANCING_GAP"
        return "SEVERE_FEE_ON_REBALANCING_GAP"

    def _recommend(self, classification: str) -> str:
        if classification == "INSUFFICIENT_DATA":
            return "AVOID_FEE_ON_REBALANCING"
        if classification == "CLEAN_NET_OF_REBALANCING_BASE":
            return "TRUST_FEE_STRUCTURE"
        if classification == "MILD_FEE_ON_REBALANCING_GAP":
            return "MINOR_FEE_ON_REBALANCING"
        if classification == "MODERATE_FEE_ON_REBALANCING_GAP":
            return "DEMAND_NET_OF_REBALANCING_BASE"
        return "AVOID_FEE_ON_REBALANCING"

    def _flags(
        self,
        classification: str,
        net_is_negative: bool,
        net_of_rebalancing_yield_pct: Optional[float],
        rebalancing_consumed_yield_pct: Optional[float],
        gross_yield_pct: float,
        rebalancing_rate_pct: Optional[float],
        used_override: bool,
    ) -> List[str]:
        flags: List[str] = []

        flags.append(classification)

        if classification == "CLEAN_NET_OF_REBALANCING_BASE":
            flags.append("CLEAN_NET_BASE")

        if net_is_negative:
            flags.append("NET_NEGATIVE_AFTER_FEE")

        if (rebalancing_rate_pct is not None
                and rebalancing_rate_pct >= HIGH_REBALANCING_COST_PCT):
            flags.append("HIGH_REBALANCING_COST")

        if used_override:
            flags.append("GAP_FROM_OVERRIDE")
        else:
            if (rebalancing_consumed_yield_pct is not None
                    and rebalancing_consumed_yield_pct > 0.0):
                flags.append("FEE_ON_REBALANCING")
            if (net_of_rebalancing_yield_pct is not None
                    and net_of_rebalancing_yield_pct <= 0.0
                    and gross_yield_pct > 0.0):
                flags.append("FULL_FEE_ON_REBALANCING")

        return flags

    def _insufficient(self, token: str) -> dict:
        return {
            "token": token,
            "gross_yield_pct": None,
            "performance_fee_pct": None,
            "net_of_rebalancing_yield_pct": None,
            "rebalancing_consumed_yield_pct": None,
            "fee_charged_pct": None,
            "fair_fee_pct": None,
            "rebalancing_transaction_cost_gap_pct": None,
            "net_return_after_fee_pct": None,
            "net_return_fair_pct": None,
            "overstatement_pct": None,
            "realization_ratio": None,
            "fee_on_rebalancing_fraction": None,
            "net_is_negative": False,
            "rebalancing_transaction_cost_rate_pct": None,
            "sample_count": 0,
            "used_override": False,
            "used_main": False,
            "score": 0.0,
            "classification": "INSUFFICIENT_DATA",
            "recommendation": "AVOID_FEE_ON_REBALANCING",
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
                "worst_rebalancing_gap_vault": None,
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
            "worst_rebalancing_gap_vault": by_score[0]["token"],
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
            "vault": "USDC-ETH-UniV3-CleanRebalancing",
            "gross_yield_pct": 15.0,
            "net_of_rebalancing_yield_pct": 15.0,
            "performance_fee_pct": 20.0,
            "rebalancing_transaction_cost_rate_pct": 0.03,
        },
        {
            "vault": "ETH-USDT-Balancer-ModerateRebalancing",
            "gross_yield_pct": 14.0,
            "net_of_rebalancing_yield_pct": 7.0,
            "performance_fee_pct": 20.0,
            "rebalancing_transaction_cost_rate_pct": 0.15,
        },
        {
            "vault": "WBTC-ETH-Curve-SevereRebalancing",
            "gross_yield_pct": 10.0,
            "net_of_rebalancing_yield_pct": -2.0,
            "performance_fee_pct": 50.0,
            "rebalancing_transaction_cost_rate_pct": 0.5,
        },
        {
            "vault": "DAI-USDC-UniV3-Override-Gap",
            "gross_yield_pct": 20.0,
            "rebalancing_transaction_cost_gap_pct": 4.8,
            "fee_charged_pct": 12.0,
        },
        {
            "vault": "MYSTERY-Vault-NoData",
            "performance_fee_pct": 20.0,
            "net_of_rebalancing_yield_pct": 5.0,
        },
    ]


if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser(
        description=(
            "MP-1260 Vault Performance-Fee Gross-Of-Rebalancing-Transaction-Cost Analyzer"
        )
    )
    parser.add_argument("--run", action="store_true")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()

    analyzer = GrossOfRebalancingTransactionCostAnalyzer()
    result = analyzer.analyze_portfolio(_demo_positions(), write_log=args.run)
    print(json.dumps(result, indent=2))
    sys.exit(0)
