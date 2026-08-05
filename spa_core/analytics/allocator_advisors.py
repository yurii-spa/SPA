"""allocator_advisors — 13 переселённых оптимизаторов голосуют advisory-входом
в allocation_rationale (поток 1 плана docs/analytics_relocation_plan_2026-08-04.md,
own-27, слой Head-of-Investment ADR-055).

Каждый советник запускает СВОЙ существующий движок из spa_core/analytics/ на
живых данных книги (data/current_positions.json, adapter_orchestrator_status.json,
adapter_registry.json, base_gas_history.json, ряды _apy_series) и возвращает одну
рекомендацию: {"advisor", "verdict", "detail", "est_bps"}.

ЖЕЛЕЗНЫЙ ИНВАРИАНТ: строго ADVISORY. Модуль никогда не гейтит исполнение,
не двигает капитал и не пишет в data/ (движковые ring-buffer-логи подавляются;
пишет только вызывающий — SHADOW-писатель rationale). Отказ любого движка
деградирует в запись verdict="ERROR", никогда не роняет вызывающего.

Честность входов:
* модуль без применимых ЖИВЫХ данных отвечает verdict="SKIPPED" с причиной —
  входы не выдумываются (нет peg-скоров → stable-yield SKIPPED, нет LP-позиций
  → LM-ROI/fee-tier SKIPPED, книга без плеча → leverage SKIPPED);
* детерминированные модельные допущения (референс-цена газа 20 gwei, ETH $3000,
  маппинг tier→risk_score) — не измерения; они помечены в detail как
  assumptions и взяты из тех же констант, что и сами движки.

``est_bps`` — оценка ДОСТУПНОГО годового улучшения в б.п. от общего капитала
(None, если советник даёт структурную/тайминговую рекомендацию без оценки).

stdlib-only. LLM FORBIDDEN. Read-only по data/.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("spa.analytics.allocator_advisors")

ADVISORS_VERSION = "advisors-v1"

# ── Детерминированные модельные допущения (см. докстринг) ────────────────────
_STATIC_GAS_PRICE_GWEI = 20.0     # референс fee_calculator (не измерение)
_ETH_PRICE_REF_USD = 3_000.0      # референс движков gas-семейства
_REBALANCE_FREQ_PER_MONTH = 1.0   # допущение каданса для месячных оценок газа
_CURRENT_HARVEST_INTERVAL_DAYS = 1.0  # paper-трек начисляет доход ежедневно
_TIMING_MIN_HISTORY_DAYS = 30     # меньше точек → честный per-protocol skip

_TIER_RISK_SCORE = {"T1": 20.0, "T2": 50.0, "T3": 75.0}   # маппинг тира, не скоринг
_TIER_MAX_LOSS_PCT = {"T1": 10.0, "T2": 25.0, "T3": 50.0}

_ASSUMPTIONS_GAS = {
    "gas_price_gwei": _STATIC_GAS_PRICE_GWEI,
    "gas_price_source": "static_reference",
    "eth_price_usd": _ETH_PRICE_REF_USD,
}


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Факты: живые входы, собранные один раз (read-only)
# ─────────────────────────────────────────────────────────────────────────────

def _gather_facts(book: Optional[dict], data_dir: Path) -> dict:
    book = book or {}
    data_dir = Path(data_dir)

    positions: Dict[str, float] = {}
    for k, v in (book.get("positions") or {}).items():
        try:
            fv = float(v)
        except (TypeError, ValueError):
            continue
        if fv > 0:
            positions[str(k)] = fv

    cp = _load_json(data_dir / "current_positions.json")
    cp = cp if isinstance(cp, dict) else {}
    if not positions and isinstance(cp.get("positions"), dict):
        for k, v in cp["positions"].items():
            try:
                fv = float(v)
            except (TypeError, ValueError):
                continue
            if fv > 0:
                positions[str(k)] = fv

    capital = book.get("capital_usd")
    if not isinstance(capital, (int, float)) or capital <= 0:
        capital = cp.get("capital_usd")
    if not isinstance(capital, (int, float)) or capital <= 0:
        capital = sum(positions.values()) or 0.0
    capital = float(capital)

    accrued = cp.get("accrued_yield_usd")
    accrued = float(accrued) if isinstance(accrued, (int, float)) else None

    # Живой снапшот адаптеров: APY / TVL / tier / провенанс.
    apy: Dict[str, float] = {}
    tvl: Dict[str, float] = {}
    tier: Dict[str, str] = {}
    tvl_live: Dict[str, bool] = {}
    orch = _load_json(data_dir / "adapter_orchestrator_status.json")
    if isinstance(orch, dict):
        for a in orch.get("adapters", []) or []:
            if not isinstance(a, dict) or not a.get("protocol"):
                continue
            p = str(a["protocol"])
            if isinstance(a.get("apy_pct"), (int, float)):
                apy[p] = float(a["apy_pct"])
            if isinstance(a.get("tvl_usd"), (int, float)):
                tvl[p] = float(a["tvl_usd"])
            if a.get("tier"):
                tier[p] = str(a["tier"]).upper()
            tvl_live[p] = a.get("tvl_source") == "live"
    # APY книги (аллокаторные, уже проценты) главнее точки снапшота.
    for k, v in (book.get("apy_pct") or {}).items():
        if isinstance(v, (int, float)):
            apy[str(k)] = float(v)

    chains: Dict[str, str] = {}
    reg = _load_json(data_dir / "adapter_registry.json")
    if isinstance(reg, dict):
        for name, entry in (reg.get("adapters") or {}).items():
            if isinstance(entry, dict) and entry.get("chain"):
                chains[str(name)] = str(entry["chain"]).strip().lower()

    # Единственный живой газ-фид — Base-chain (data/base_gas_history.json).
    base_gwei: Optional[float] = None
    gh = _load_json(data_dir / "base_gas_history.json")
    if isinstance(gh, dict):
        readings = gh.get("recent_readings") or []
        if readings and isinstance(readings[-1], dict) and \
                isinstance(readings[-1].get("gwei"), (int, float)):
            base_gwei = float(readings[-1]["gwei"])

    return {
        "data_dir": data_dir,
        "positions": positions,
        "capital_usd": capital,
        "cash_usd": max(0.0, capital - sum(positions.values())),
        "apy_pct": apy,
        "tvl_usd": tvl,
        "tier": tier,
        "tvl_live": tvl_live,
        "chains": chains,
        "accrued_yield_usd": accrued,
        "base_gwei_live": base_gwei,
    }


def _tier_of(f: dict, proto: str) -> str:
    t = f["tier"].get(proto)
    if t in ("T1", "T2", "T3"):
        return t
    try:
        from spa_core.adapters.tier_map import tier_of
        t2 = tier_of(proto)
        if t2 in ("T1", "T2", "T3"):
            return t2
    except Exception:  # noqa: BLE001 — деградация к T2, как везде в системе
        pass
    return "T2"


def _chain_of(f: dict, proto: str) -> str:
    return f["chains"].get(proto, "ethereum")


def _gas_price_gwei(f: dict, chain: str) -> Tuple[float, str]:
    """(gwei, source): живое чтение только для base-chain, иначе референс."""
    if chain == "base" and f["base_gwei_live"] is not None:
        return f["base_gwei_live"], "live_base_gas_history"
    return _STATIC_GAS_PRICE_GWEI, "static_reference"


def _gas_usd(f: dict, operation: str, chain: str) -> float:
    """Газ одной операции в USD — та же таблица юнитов, что у FeeCalculator."""
    from spa_core.analytics.fee_calculator import FeeCalculator
    gwei, _src = _gas_price_gwei(f, chain)
    return FeeCalculator().estimate_gas_fee_usd(operation, chain, gas_price_gwei=gwei)


def _skip(reason: str) -> Tuple[str, dict, None]:
    return "SKIPPED", {"reason": reason}, None


def _require_positions(f: dict) -> Optional[Tuple[str, dict, None]]:
    if not f["positions"]:
        return _skip("no positions in book (data/current_positions.json empty)")
    return None


# ─────────────────────────────────────────────────────────────────────────────
# 13 советников
# ─────────────────────────────────────────────────────────────────────────────

def _adv_cross_protocol_yield(f: dict) -> Tuple[str, dict, Optional[float]]:
    from spa_core.analytics.defi_cross_protocol_yield_optimizer import (
        DeFiCrossProtocolYieldOptimizer,
    )
    universe = sorted(set(f["apy_pct"]) | set(f["positions"]))
    universe = [p for p in universe if p in f["apy_pct"]]
    if not universe:
        return _skip("no live APY snapshot (adapter_orchestrator_status.json empty)")
    opportunities = []
    for p in universe:
        chain = _chain_of(f, p)
        opportunities.append({
            "protocol": p,
            "asset": "USDC",
            "apy_pct": f["apy_pct"][p],
            "gas_entry_usd": _gas_usd(f, "deposit", chain),
            "gas_exit_usd": _gas_usd(f, "withdraw", chain),
            "risk_score": _TIER_RISK_SCORE[_tier_of(f, p)],
            "capacity_remaining_usd": f["tvl_usd"].get(p, 0.0),
            "max_deposit_usd": f["capital_usd"],
        })
    opt = DeFiCrossProtocolYieldOptimizer()
    opt._append_log = lambda *a, **k: None  # read-only: лог движка — не наш артефакт
    res = opt.optimize(opportunities, {"total_capital_usd": f["capital_usd"]})

    by_proto = {o["protocol"]: o for o in res["opportunities"]}
    held_total = sum(f["positions"].values())
    blended_held = 0.0
    if held_total > 0:
        blended_held = sum(
            usd * by_proto[p]["risk_adjusted_net_apy"]
            for p, usd in f["positions"].items() if p in by_proto
        ) / held_total
    top = res["top_opportunity"]
    top_radj = res["top_opportunity_risk_adj_apy"] or 0.0
    est_bps = round(max(0.0, top_radj - blended_held) * 100.0, 2)
    detail = {
        "top_opportunity": top,
        "top_risk_adjusted_net_apy_pct": top_radj,
        "book_blended_risk_adjusted_apy_pct": round(blended_held, 4),
        "held_labels": {p: by_proto[p]["label"]
                        for p in f["positions"] if p in by_proto},
        "must_allocate_count": res["must_allocate_count"],
        "assumptions": {**_ASSUMPTIONS_GAS,
                        "risk_score_from_tier": _TIER_RISK_SCORE},
    }
    return f"TOP:{top}", detail, est_bps


def _adv_gas_optimization_advisor(f: dict) -> Tuple[str, dict, Optional[float]]:
    skip = _require_positions(f)
    if skip:
        return skip
    import spa_core.analytics.defi_gas_optimization_advisor as gas_mod
    from spa_core.analytics.fee_calculator import _GAS_UNITS, _DEFAULT_GAS_UNITS

    transactions = []
    for p, usd in sorted(f["positions"].items()):
        chain = _chain_of(f, p)
        gwei, _src = _gas_price_gwei(f, chain)
        transactions.append({
            "protocol": p,
            "tx_type": "rebalance",
            "gas_used": _GAS_UNITS.get(("rebalance", chain), _DEFAULT_GAS_UNITS),
            "current_gas_price_gwei": gwei,
            "base_fee_gwei": gwei,
            "priority_fee_gwei": 1.0,
            "tx_value_usd": usd,
            "time_sensitivity": "flexible",
            "chain": chain,
            "batch_possible": True,
        })
    # Единственный движок с модульным _append_log — глушим на время вызова
    # (советники read-only по data/; лог движка принадлежит его Tier-B жизни).
    orig = gas_mod._append_log
    gas_mod._append_log = lambda *a, **k: None
    try:
        res = gas_mod.DeFiGasOptimizationAdvisor().advise(
            transactions, {"eth_price_usd": _ETH_PRICE_REF_USD})
    finally:
        gas_mod._append_log = orig
    agg = res["aggregates"]
    est_bps = None
    if f["capital_usd"] > 0:
        est_bps = round(
            agg["total_potential_savings_usd"] / f["capital_usd"] * 10_000.0, 2)
    verdict = ("GAS_OK" if agg["prohibitive_count"] == 0
               else f"PROHIBITIVE:{agg['prohibitive_count']}")
    detail = {
        "full_book_rebalance_gas_usd": round(agg["total_gas_cost_usd"], 2),
        "potential_savings_usd": round(agg["total_potential_savings_usd"], 2),
        "most_expensive_tx": agg["most_expensive_tx"],
        "prohibitive_count": agg["prohibitive_count"],
        "assumptions": dict(_ASSUMPTIONS_GAS),
    }
    return verdict, detail, est_bps


def _adv_gas_optimization_engine(f: dict) -> Tuple[str, dict, Optional[float]]:
    from dataclasses import asdict
    from spa_core.analytics.gas_optimization_engine import GasOptimizationEngine

    if f["base_gwei_live"] is not None:
        base_fee, src, chain = f["base_gwei_live"], "live_base_gas_history", "base"
    else:
        base_fee, src, chain = _STATIC_GAS_PRICE_GWEI, "static_reference", "ethereum"
    res = GasOptimizationEngine().optimize(
        transaction_type="rebalance",
        urgency="NORMAL",
        base_fee_gwei=base_fee,
        eth_price_usd=_ETH_PRICE_REF_USD,
        gas_units=150_000,
    )  # save_results НЕ вызывается — read-only
    detail = {
        "chain": chain,
        "base_fee_gwei": base_fee,
        "gas_price_source": src,
        "optimal_window": res.optimal_window,
        "selected_quote": asdict(res.selected_quote),
        "l2_savings_pct": res.l2_savings_pct,
        "batch_savings_pct": res.batch_savings_pct,
        "reasoning": res.reasoning,
        "assumptions": {"eth_price_usd": _ETH_PRICE_REF_USD},
    }
    return res.selected_quote.recommendation, detail, None


def _adv_gas_cost_optimizer(f: dict) -> Tuple[str, dict, Optional[float]]:
    skip = _require_positions(f)
    if skip:
        return skip
    from spa_core.analytics.fee_calculator import _GAS_UNITS, _DEFAULT_GAS_UNITS
    from spa_core.analytics.protocol_defi_gas_cost_optimizer import (
        ProtocolDeFiGasCostOptimizer,
    )
    operations = []
    for p, usd in sorted(f["positions"].items()):
        chain = _chain_of(f, p)
        gwei, _src = _gas_price_gwei(f, chain)
        operations.append({
            "name": p,
            "op_type": "rebalance",
            "protocol": p,
            "chain": chain,
            "estimated_gas_units": _GAS_UNITS.get(("rebalance", chain),
                                                  _DEFAULT_GAS_UNITS),
            "current_gas_price_gwei": gwei,
            "eth_price_usd": _ETH_PRICE_REF_USD,
            "transaction_value_usd": usd,
            "frequency_per_month": _REBALANCE_FREQ_PER_MONTH,
            "can_batch": True,
            # Дешёвое окно не измеряем → typical = current: экономия таймингом
            # честно равна нулю, а не выдумана.
            "can_delay": True,
            "typical_cheap_gas_gwei": gwei,
            "congestion_factor": 1.0,
        })
    opt = ProtocolDeFiGasCostOptimizer()
    opt._append_log = lambda *a, **k: None  # read-only
    res = opt.optimize(operations)
    agg = res["aggregates"]
    est_bps = None
    if f["capital_usd"] > 0:
        est_bps = round(agg["total_potential_savings_usd"] * 12.0
                        / f["capital_usd"] * 10_000.0, 2)
    n_bad = agg["cost_prohibitive_count"]
    verdict = "ALL_EFFICIENT" if n_bad == 0 else f"COST_PROHIBITIVE:{n_bad}"
    detail = {
        "monthly_gas_usd": agg["total_monthly_gas_usd"],
        "monthly_potential_savings_usd": agg["total_potential_savings_usd"],
        "most_expensive": agg["most_expensive"],
        "per_operation": [
            {"name": r["name"], "label": r["efficiency_label"],
             "gas_cost_bps": r["gas_cost_bps"]}
            for r in res["operations"]
        ],
        "assumptions": {**_ASSUMPTIONS_GAS,
                        "rebalance_freq_per_month": _REBALANCE_FREQ_PER_MONTH},
    }
    return verdict, detail, est_bps


def _adv_liquidity_mining_roi(f: dict) -> Tuple[str, dict, Optional[float]]:
    return _skip(
        "book holds no liquidity-mining LP positions (lending/PT only) and "
        "data/ has no reward-emission programs to price — inputs would be invented"
    )


def _adv_fee_tier_optimizer(f: dict) -> Tuple[str, dict, Optional[float]]:
    return _skip(
        "engine targets Uniswap-V3-style pool fee tiers; book holds no DEX LP "
        "positions and data/ has no pool volume/tick series"
    )


def _adv_leverage_adjusted_apy(f: dict) -> Tuple[str, dict, Optional[float]]:
    return _skip(
        "book is unleveraged (no borrow legs, no LTV inputs); leverage loops "
        "are outside RiskPolicy v1.0 paper track"
    )


def _adv_harvesting_frequency(f: dict) -> Tuple[str, dict, Optional[float]]:
    skip = _require_positions(f)
    if skip:
        return skip
    from spa_core.analytics.defi_protocol_yield_harvesting_frequency_optimizer import (
        DeFiProtocolYieldHarvestingFrequencyOptimizer,
    )
    positions = []
    skipped: Dict[str, str] = {}
    for p, usd in sorted(f["positions"].items()):
        apy = f["apy_pct"].get(p)
        if not isinstance(apy, (int, float)):
            skipped[p] = "no live APY"
            continue
        chain = _chain_of(f, p)
        positions.append({
            "name": p,
            "protocol": p,
            "position_usd": usd,
            "gross_apy_pct": float(apy),
            "gas_cost_per_harvest_usd": _gas_usd(f, "rebalance", chain),
            "current_harvest_interval_days": _CURRENT_HARVEST_INTERVAL_DAYS,
        })
    if not positions:
        return _skip("no held position has a live APY")
    res = DeFiProtocolYieldHarvestingFrequencyOptimizer().optimize(
        positions, write_log=False)
    total_gain = sum(r["additional_annual_yield_usd"] for r in res["positions"])
    est_bps = (round(total_gain / f["capital_usd"] * 10_000.0, 2)
               if f["capital_usd"] > 0 else None)
    verdict = ("IMPROVEMENT_AVAILABLE" if (est_bps or 0.0) > 0.5
               else "CURRENT_CADENCE_OK")
    detail = {
        "per_position": [
            {"name": r["name"],
             "optimal_interval_days": r["optimal_interval_days"],
             "optimal_frequency_label": r["optimal_frequency_label"],
             "apy_improvement_pct": r["apy_improvement_pct"],
             "additional_annual_yield_usd": r["additional_annual_yield_usd"]}
            for r in res["positions"]
        ],
        "no_apy_skipped": skipped,
        "assumptions": {**_ASSUMPTIONS_GAS,
                        "current_interval_days": _CURRENT_HARVEST_INTERVAL_DAYS},
    }
    return verdict, detail, est_bps


def _series_confidence_pct(proto: str, data_dir: Path) -> Tuple[float, int]:
    """Достоверность APY по ДЛИНЕ фактического ряда (детерминированная шкала)."""
    try:
        from spa_core.analytics import _apy_series
        n = _apy_series.days_available(proto, data_dir=data_dir)
    except Exception:  # noqa: BLE001
        n = 0
    if n >= 90:
        return 85.0, n
    if n >= 30:
        return 70.0, n
    if n >= 7:
        return 55.0, n
    return 40.0, n


def _adv_position_size(f: dict) -> Tuple[str, dict, Optional[float]]:
    skip = _require_positions(f)
    if skip:
        return skip
    from spa_core.analytics.protocol_defi_position_size_optimizer import (
        ProtocolDeFiPositionSizeOptimizer,
    )
    caps: Dict[str, float] = {}
    try:
        from spa_core.risk.policy import RiskConfig
        cfg = RiskConfig()
        caps = {"T1": float(cfg.max_concentration_t1) * 100.0,
                "T2": float(cfg.max_concentration_t2) * 100.0,
                "T3": float(cfg.max_concentration_t2) * 100.0}
    except Exception:  # noqa: BLE001 — без RiskConfig честнее дефолт движка
        pass

    opportunities = []
    conf_used: Dict[str, dict] = {}
    for p, usd in sorted(f["positions"].items()):
        apy = f["apy_pct"].get(p)
        if not isinstance(apy, (int, float)):
            continue
        t = _tier_of(f, p)
        conf, n = _series_confidence_pct(p, f["data_dir"])
        conf_used[p] = {"confidence_pct": conf, "history_days": n}
        tvl = f["tvl_usd"].get(p, 0.0)
        opp = {
            "name": p,
            "protocol": p,
            "expected_apy_pct": float(apy),
            "apy_confidence_pct": conf,
            "max_loss_scenario_pct": _TIER_MAX_LOSS_PCT[t],
            "protocol_risk_score": _TIER_RISK_SCORE[t],
            "tvl_usd": tvl,
            "our_position_impact_pct": (usd / tvl * 100.0) if tvl > 0 else 0.0,
            "portfolio_total_usd": f["capital_usd"],
            "min_viable_size_usd": 0.0,
            "liquidity_exit_days": 1.0,
        }
        if t in caps:
            opp["max_single_position_pct"] = caps[t]
        opportunities.append(opp)
    if not opportunities:
        return _skip("no held position has a live APY")
    res = ProtocolDeFiPositionSizeOptimizer().optimize(
        opportunities, {"log_enabled": False})

    oversized = []
    per_position = []
    for r in res["opportunities"]:
        p = r["name"]
        held_pct = (f["positions"].get(p, 0.0) / f["capital_usd"] * 100.0
                    if f["capital_usd"] > 0 else 0.0)
        opt_pct = r.get("optimal_position_pct", 0.0)
        per_position.append({
            "name": p, "held_pct": round(held_pct, 2),
            "optimal_pct": opt_pct, "label": r.get("label"),
        })
        if held_pct > opt_pct + 1e-9:
            oversized.append(p)
    verdict = ("SIZES_WITHIN_KELLY" if not oversized
               else "OVERSIZED:" + ",".join(sorted(oversized)))
    detail = {
        "per_position": per_position,
        "oversized_vs_kelly": sorted(oversized),
        "assumptions": {
            "confidence_from_history_days": conf_used,
            "max_loss_from_tier_pct": _TIER_MAX_LOSS_PCT,
            "risk_score_from_tier": _TIER_RISK_SCORE,
            "caps_source": "RiskConfig" if caps else "engine_default",
        },
    }
    return verdict, detail, None


def _adv_stable_yield(f: dict) -> Tuple[str, dict, Optional[float]]:
    return _skip(
        "engine requires stablecoin peg scores and protocol age, which data/ "
        "does not measure — supplying them would be fabrication"
    )


def _adv_reinvestment(f: dict) -> Tuple[str, dict, Optional[float]]:
    skip = _require_positions(f)
    if skip:
        return skip
    if f["accrued_yield_usd"] is None:
        return _skip("accrued_yield_usd not available in data/current_positions.json")
    from spa_core.analytics.yield_reinvestment_optimizer import (
        YieldReinvestmentOptimizer,
    )
    held_total = sum(f["positions"].values())
    allocations = {p: usd / held_total * 100.0 for p, usd in f["positions"].items()}
    apys = {p: f["apy_pct"].get(p, 0.0) for p in f["positions"]}
    best_target = max(apys, key=lambda p: apys[p])
    gas = _gas_usd(f, "deposit", _chain_of(f, best_target))
    threshold = 2.0 * gas  # реинвест осмыслен, когда доход ≥ двух цен транзакции
    opt = YieldReinvestmentOptimizer()
    opt._append_log = lambda *a, **k: None  # read-only
    res = opt.optimize({
        "current_yield_usd": f["accrued_yield_usd"],
        "portfolio_allocations": allocations,
        "protocol_apys": apys,
        "reinvest_threshold_usd": threshold,
        "gas_cost_per_tx_usd": gas,
    })
    est_bps = round(float(res["compounding_boost_annual_pct"]) * 100.0, 2)
    verdict = (f"REINVEST:{res['optimal_reinvest_target']}"
               if res["reinvest_worthwhile"] else "HOLD_YIELD")
    detail = {
        "accrued_yield_usd": f["accrued_yield_usd"],
        "optimal_reinvest_target": res["optimal_reinvest_target"],
        "reinvest_worthwhile": res["reinvest_worthwhile"],
        "apy_improvement_pct": res["apy_improvement_pct"],
        "net_reinvest_value_usd": res["net_reinvest_value"],
        "assumptions": {**_ASSUMPTIONS_GAS,
                        "threshold_usd": round(threshold, 2),
                        "threshold_rule": "2x gas cost of one deposit"},
    }
    return verdict, detail, est_bps


def _adv_yield_timing(f: dict) -> Tuple[str, dict, Optional[float]]:
    skip = _require_positions(f)
    if skip:
        return skip
    from datetime import date as _date
    from spa_core.analytics import _apy_series
    from spa_core.analytics.yield_timing_optimizer import YieldTimingOptimizer

    signals: Dict[str, dict] = {}
    insufficient: Dict[str, int] = {}
    for p in sorted(f["positions"]):
        series = None
        try:
            series = _apy_series.get_series(
                p, min_days=_TIMING_MIN_HISTORY_DAYS, data_dir=f["data_dir"])
        except Exception:  # noqa: BLE001
            series = None
        if not series:
            insufficient[p] = _apy_series.days_available(p, data_dir=f["data_dir"])
            continue
        current_apy = f["apy_pct"].get(p, series[-1][1])
        history = [
            (float(_date.fromisoformat(day).toordinal()) * 86400.0, apy)
            for day, apy in series
        ]
        opt = YieldTimingOptimizer()
        opt._append_log = lambda *a, **k: None  # read-only
        res = opt.optimize({
            "protocol": p,
            "apy_history": history,
            "current_apy": float(current_apy),
        })
        signals[p] = {
            "entry_signal": res["entry_signal"],
            "apy_percentile": res["apy_percentile"],
            "expected_apy_next_30d": res["expected_apy_next_30d"],
            "history_days": res["history_count"],
        }
    if not signals:
        return _skip(
            "no held protocol has >= {n} days of APY history "
            "(data/historical_apy + apy_series_daily); available: {have}".format(
                n=_TIMING_MIN_HISTORY_DAYS, have=insufficient))
    verdict = ",".join(f"{p}={signals[p]['entry_signal']}" for p in sorted(signals))
    detail = {"signals": signals, "insufficient_history_days": insufficient}
    return verdict, detail, None


def _adv_fee_calculator(f: dict) -> Tuple[str, dict, Optional[float]]:
    skip = _require_positions(f)
    if skip:
        return skip
    from spa_core.analytics.fee_calculator import FeeCalculator
    calc = FeeCalculator()
    per_position = []
    total = 0.0
    for p, usd in sorted(f["positions"].items()):
        adapter = {
            "apy_pct": f["apy_pct"].get(p, 0.0),
            "tvl_usd": f["tvl_usd"].get(p, 0.0),
            "tier": _tier_of(f, p),
            "chain": _chain_of(f, p),
        }
        cost = calc.compute_total_cost(usd, "deposit", adapter, period_days=365)
        total += cost["total_usd"]
        per_position.append({"name": p, **cost})
    drag_bps = (round(total / f["capital_usd"] * 10_000.0, 2)
                if f["capital_usd"] > 0 else None)
    detail = {
        "per_position": per_position,
        "annual_cost_total_usd": round(total, 2),
        "annual_cost_drag_bps": drag_bps,
        "assumptions": dict(_ASSUMPTIONS_GAS),
    }
    return f"DRAG:{drag_bps}bps", detail, None


# ─────────────────────────────────────────────────────────────────────────────
# Оркестрация
# ─────────────────────────────────────────────────────────────────────────────

_ADVISORS: List[Tuple[str, Callable[[dict], Tuple[str, dict, Optional[float]]]]] = [
    ("defi_cross_protocol_yield_optimizer", _adv_cross_protocol_yield),
    ("defi_gas_optimization_advisor", _adv_gas_optimization_advisor),
    ("gas_optimization_engine", _adv_gas_optimization_engine),
    ("protocol_defi_gas_cost_optimizer", _adv_gas_cost_optimizer),
    ("defi_liquidity_mining_roi_calculator", _adv_liquidity_mining_roi),
    ("defi_protocol_fee_tier_optimizer", _adv_fee_tier_optimizer),
    ("defi_protocol_leverage_adjusted_apy_calculator", _adv_leverage_adjusted_apy),
    ("defi_protocol_yield_harvesting_frequency_optimizer", _adv_harvesting_frequency),
    ("protocol_defi_position_size_optimizer", _adv_position_size),
    ("protocol_defi_stable_yield_optimizer", _adv_stable_yield),
    ("yield_reinvestment_optimizer", _adv_reinvestment),
    ("yield_timing_optimizer", _adv_yield_timing),
    ("fee_calculator", _adv_fee_calculator),
]


def run_advisors(book: Optional[dict], data_dir: Any) -> List[dict]:
    """13 рекомендаций [{advisor, verdict, detail, est_bps}] — строго advisory.

    ``book``: {"positions": {proto: usd}, "capital_usd": float,
    "apy_pct": {proto: pct}} — недостающее честно добирается из data/
    (read-only). Отказ движка → verdict="ERROR" этой записи; исключение
    наружу не уходит никогда.
    """
    facts = _gather_facts(book, Path(data_dir))
    out: List[dict] = []
    for name, fn in _ADVISORS:
        try:
            verdict, detail, est_bps = fn(facts)
        except Exception as exc:  # noqa: BLE001 — советник не роняет писателя
            log.warning("advisor %s failed: %s", name, exc)
            verdict, detail, est_bps = "ERROR", {
                "error": type(exc).__name__, "message": str(exc)[:300]}, None
        out.append({"advisor": name, "verdict": verdict,
                    "detail": detail, "est_bps": est_bps})
    return out
