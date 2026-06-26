#!/usr/bin/env python3
"""Multi-strategy tournament step for the paper-trading cycle (N12 decomposition).

PURE-MOVE EXTRACTION from ``cycle_runner.run_cycle``: the MP-386/405/423/523/591/
599/604/608 + S_BASIS tournament registration + ``MultiStrategyRunner`` daily run.
The body is byte-identical to the original inline block (verbatim, only dedented
and wrapped in a function taking the two locals it used: ``ddir`` + ``apy_map``).

STRICTLY READ-ONLY / ADVISORY: it never touches trades.json, equity_curve_daily,
current_positions or any risk/policy state, and the whole block is fail-safe —
any exception is logged as a WARNING and swallowed (the cycle never crashes).
stdlib only.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("spa.cycle_runner")


def run_tournament_step(ddir: Path, apy_map: dict) -> None:
    """Run the advisory multi-strategy tournament for one cycle day.

    Verbatim move of the inline ``run_cycle`` block. Fail-safe by construction
    (the entire body is one try/except that only logs on error).
    """
    # ── MP-386/MP-405/MP-423: Multi-Strategy Tournament S2–S11 Integration ──────────
    # Запускает MultiStrategyRunner с S0/S1/S2/S3/S4/S5/S6/S7/S11 стратегиями.
    # S2–S11 преобразуются в StrategyConfig из модульных констант.
    # Active strategies: S0, S1, S2, S3, S4, S5, S6, S7, S11
    # Advisory — не трогает trades.json, equity_curve, risk/policy.
    # Fail-safe: любое исключение → WARNING, цикл продолжается.
    try:
        from spa_core.paper_trading.strategy_registry import (
            S0_CONSERVATIVE_T1 as _ms_s0,
            S1_BALANCED as _ms_s1,
            StrategyConfig as _MSStrategyConfig,
        )
        from spa_core.paper_trading.multi_strategy_runner import (
            MultiStrategyRunner as _MultiStrategyRunner,
        )
        from spa_core.strategies.s2_pendle_morpho import (
            STRATEGY_ID as _s2_id,
            STRATEGY_NAME as _s2_name,
            TIER as _s2_tier,
            ALLOCATION as _s2_alloc,
            TARGET_APY_MIN as _s2_apy_min,
            TARGET_APY_MAX as _s2_apy_max,
        )
        from spa_core.strategies.s3_aave_arb_morpho import (
            STRATEGY_ID as _s3_id,
            STRATEGY_NAME as _s3_name,
            TIER as _s3_tier,
            ALLOCATION as _s3_alloc,
            TARGET_APY_MIN as _s3_apy_min,
            TARGET_APY_MAX as _s3_apy_max,
        )
        try:
            from spa_core.strategies.s4_spark_fluid_conservative import (
                STRATEGY_ID as _s4_id,
                STRATEGY_NAME as _s4_name,
                TIER as _s4_tier,
                ALLOCATION as _s4_alloc,
                TARGET_APY_MIN as _s4_apy_min,
                TARGET_APY_MAX as _s4_apy_max,
            )
        except ImportError:
            _s4_id = _s4_name = _s4_tier = _s4_alloc = _s4_apy_min = _s4_apy_max = None
        try:
            from spa_core.strategies.s5_pendle_enhanced import (
                STRATEGY_ID as _s5_id,
                STRATEGY_NAME as _s5_name,
                TIER_LIMIT as _s5_tier,
                ALLOCATION as _s5_alloc,
                TARGET_APY_MIN as _s5_apy_min,
                TARGET_APY_MAX as _s5_apy_max,
            )
        except ImportError:
            _s5_id = _s5_name = _s5_tier = _s5_alloc = _s5_apy_min = _s5_apy_max = None
        try:
            from spa_core.strategies.s6_max_diversified import (
                STRATEGY_ID as _s6_id,
                STRATEGY_NAME as _s6_name,
                TIER as _s6_tier,
                ALLOCATION as _s6_alloc,
                TARGET_APY_MIN as _s6_apy_min,
                TARGET_APY_MAX as _s6_apy_max,
            )
        except ImportError:
            _s6_id = _s6_name = _s6_tier = _s6_alloc = _s6_apy_min = _s6_apy_max = None
        try:
            from spa_core.strategies.s7_pendle_yt_aggressive import (
                STRATEGY_ID as _s7_id,
                STRATEGY_NAME as _s7_name,
                RISK_TIER as _s7_tier,
                ALLOCATION as _s7_alloc,
                TARGET_APY_MIN as _s7_apy_min,
                TARGET_APY_MAX as _s7_apy_max,
            )
        except ImportError:
            _s7_id = _s7_name = _s7_tier = _s7_alloc = _s7_apy_min = _s7_apy_max = None
        try:
            from spa_core.strategies.s11_hybrid_yield_max import (
                STRATEGY_ID as _s11_id,
                STRATEGY_NAME as _s11_name,
                RISK_TIER as _s11_tier,
                BASE_ALLOCATION as _s11_alloc,
                TARGET_APY_MIN as _s11_apy_min,
                TARGET_APY_MAX as _s11_apy_max,
            )
        except ImportError:
            _s11_id = _s11_name = _s11_tier = _s11_alloc = _s11_apy_min = _s11_apy_max = None
        try:
            from spa_core.strategies.s12_base_layer_yield import (
                STRATEGY_ID as _s12_id,
                STRATEGY_NAME as _s12_name,
                TIER as _s12_tier,
                PHASE1_WEIGHTS as _s12_alloc,
                TARGET_APY_PCT as _s12_apy_pct,
            )
            _s12_apy_min = _s12_apy_pct * 0.80
            _s12_apy_max = _s12_apy_pct * 1.20
        except ImportError:
            _s12_id = _s12_name = _s12_tier = _s12_alloc = _s12_apy_min = _s12_apy_max = None
        # ── MP-523: S13 Multi-Chain Yield Arbitrage ────────────────────────
        try:
            from spa_core.strategies.s13_multi_chain_arb import (
                STRATEGY_ID as _s13_id,
                STRATEGY_NAME as _s13_name,
                TIER as _s13_tier,
                PHASE1_WEIGHTS as _s13_phase1_weights,
                TARGET_APY_PCT as _s13_target_apy,
            )
            _s13_apy_min = _s13_target_apy * 0.80
            _s13_apy_max = _s13_target_apy * 1.20
        except ImportError:
            _s13_id = None
        # S2: исключаем pendle_pt (external — в _SKIP_PROTOCOLS MultiStrategyRunner)
        _ms_s2 = _MSStrategyConfig(
            id=_s2_id,
            name=_s2_name,
            description="S2 Pendle PT + Morpho Heavy (pendle_pt excl.)",
            allocations={k: v for k, v in _s2_alloc.items() if k != "pendle_pt"},
            tier=_s2_tier,
            target_apy_min=_s2_apy_min,
            target_apy_max=_s2_apy_max,
        )
        # S3: все T1 — aave_arbitrum + morpho_steakhouse + aave_mainnet
        _ms_s3 = _MSStrategyConfig(
            id=_s3_id,
            name=_s3_name,
            description="S3 Aave Arbitrum L2 + Morpho (all T1)",
            allocations=dict(_s3_alloc),
            tier=_s3_tier,
            target_apy_min=_s3_apy_min,
            target_apy_max=_s3_apy_max,
        )
        _ms_strategies = [_ms_s0, _ms_s1, _ms_s2, _ms_s3]
        # S4: Conservative Spark+Fluid (T1+T2, нет pendle-протоколов)
        if _s4_id is not None:
            _ms_s4 = _MSStrategyConfig(
                id=_s4_id,
                name=_s4_name,
                description="S4 Conservative Spark+Fluid (T1+T2)",
                allocations=dict(_s4_alloc),
                tier=_s4_tier,
                target_apy_min=_s4_apy_min,
                target_apy_max=_s4_apy_max,
            )
            _ms_strategies.append(_ms_s4)
        # S5: Pendle PT Enhanced — исключаем pendle_pt (_SKIP_PROTOCOLS)
        if _s5_id is not None:
            _ms_s5 = _MSStrategyConfig(
                id=_s5_id,
                name=_s5_name,
                description="S5 Pendle PT Enhanced (pendle_pt excl.)",
                allocations={k: v for k, v in _s5_alloc.items() if k != "pendle_pt"},
                tier=_s5_tier,
                target_apy_min=_s5_apy_min,
                target_apy_max=_s5_apy_max,
            )
            _ms_strategies.append(_ms_s5)
        # S6: Max Diversified — исключаем pendle_pt (_SKIP_PROTOCOLS)
        if _s6_id is not None:
            _ms_s6 = _MSStrategyConfig(
                id=_s6_id,
                name=_s6_name,
                description="S6 Max Diversified (pendle_pt excl.)",
                allocations={k: v for k, v in _s6_alloc.items() if k != "pendle_pt"},
                tier=_s6_tier,
                target_apy_min=_s6_apy_min,
                target_apy_max=_s6_apy_max,
            )
            _ms_strategies.append(_ms_s6)
        # S7: Pendle YT+PT Aggressive — исключаем pendle_yt+pendle_pt (_SKIP_PROTOCOLS)
        if _s7_id is not None:
            _ms_s7 = _MSStrategyConfig(
                id=_s7_id,
                name=_s7_name,
                description="S7 Pendle YT+PT Aggressive (pendle excl.)",
                allocations={k: v for k, v in _s7_alloc.items()
                             if k not in ("pendle_yt", "pendle_pt")},
                tier=_s7_tier,
                target_apy_min=_s7_apy_min,
                target_apy_max=_s7_apy_max,
            )
            _ms_strategies.append(_ms_s7)
        # S11: Hybrid Yield Maximizer — исключаем pendle_yt (_SKIP_PROTOCOLS)
        if _s11_id is not None:
            _ms_s11 = _MSStrategyConfig(
                id=_s11_id,
                name=_s11_name,
                description="S11 Hybrid Yield Maximizer (pendle excl.)",
                allocations={k: v for k, v in _s11_alloc.items()
                             if k not in ("pendle_yt", "pendle_pt")},
                tier=_s11_tier,
                target_apy_min=_s11_apy_min,
                target_apy_max=_s11_apy_max,
            )
            _ms_strategies.append(_ms_s11)
        # S12: Base Layer Yield — Phase 1 fallback weights (ETH only until 2026-08-01)
        if _s12_id is not None:
            _ms_s12 = _MSStrategyConfig(
                id=_s12_id,
                name=_s12_name,
                description="S12 Base Layer Yield (Phase 1: ETH fallback)",
                allocations=_s12_alloc,
                tier=_s12_tier,
                target_apy_min=_s12_apy_min,
                target_apy_max=_s12_apy_max,
            )
            _ms_strategies.append(_ms_s12)
        # S13: Multi-Chain Yield Arbitrage — Phase 1 ETH fallback (cross-chain after 2026-08-01)
        if _s13_id is not None:
            _ms_s13 = _MSStrategyConfig(
                id=_s13_id,
                name=_s13_name,
                description="S13 Multi-Chain Yield Arbitrage (Phase 1: ETH fallback)",
                allocations=_s13_phase1_weights,
                tier=_s13_tier,
                target_apy_min=_s13_apy_min,
                target_apy_max=_s13_apy_max,
            )
            _ms_strategies.append(_ms_s13)
        # ── MP-591: S15 MultiChain L2 Yield — Base40%+Opt35%+Arb25% ──────────
        try:
            from spa_core.strategies.s15_multichain_l2 import (
                STRATEGY_ID as _s15_id,
                STRATEGY_NAME as _s15_name,
                TIER as _s15_tier,
                CHAIN_WEIGHTS as _s15_weights,
                TARGET_APY_PCT as _s15_target_apy,
            )
            _s15_apy_min = _s15_target_apy * 0.80
            _s15_apy_max = _s15_target_apy * 1.20
            _ms_s15 = _MSStrategyConfig(
                id=_s15_id,
                name=_s15_name,
                description="S15 MultiChain L2 Yield (Base 40%+Opt 35%+Arb 25%)",
                allocations=dict(_s15_weights),
                tier=_s15_tier,
                target_apy_min=_s15_apy_min,
                target_apy_max=_s15_apy_max,
            )
            _ms_strategies.append(_ms_s15)
        except ImportError:
            pass
        # ── MP-599: S17 Polygon Yield — Core60%+Anchor25%+Boost15% ──────────
        try:
            from spa_core.strategies.s17_polygon_yield import (
                STRATEGY_ID as _s17_id,
                STRATEGY_NAME as _s17_name,
                TIER as _s17_tier,
                ALLOCATION_WEIGHTS as _s17_weights,
                TARGET_APY_PCT as _s17_target_apy,
            )
            _s17_apy_min = _s17_target_apy * 0.80
            _s17_apy_max = _s17_target_apy * 1.20
            _ms_s17 = _MSStrategyConfig(
                id=_s17_id,
                name=_s17_name,
                description="S17 Polygon Yield (Core 60%+Anchor 25%+Boost 15%)",
                allocations=dict(_s17_weights),
                tier=_s17_tier,
                target_apy_min=_s17_apy_min,
                target_apy_max=_s17_apy_max,
            )
            _ms_strategies.append(_ms_s17)
        except ImportError:
            pass
        # ── MP-604: S18 High Yield T2 — Safety30%+CoreA35%+CoreB25%+Boost10% ──
        try:
            from spa_core.strategies.s18_high_yield_t2 import (
                STRATEGY_ID as _s18_id,
                STRATEGY_NAME as _s18_name,
                TIER as _s18_tier,
                ALLOCATION_WEIGHTS as _s18_weights,
                TARGET_APY_PCT as _s18_target_apy,
            )
            _s18_apy_min = _s18_target_apy * 0.80
            _s18_apy_max = _s18_target_apy * 1.20
            _ms_s18 = _MSStrategyConfig(
                id=_s18_id,
                name=_s18_name,
                description="S18 High Yield T2 (Safety30%+CoreA35%+CoreB25%+Boost10%)",
                allocations=dict(_s18_weights),
                tier=_s18_tier,
                target_apy_min=_s18_apy_min,
                target_apy_max=_s18_apy_max,
            )
            _ms_strategies.append(_ms_s18)
        except ImportError:
            pass
        # ── MP-608: S19 Balanced L2 — equal 25% across ARB+BASE+OPT+POLY ─────
        try:
            from spa_core.strategies.s19_balanced_l2 import (
                STRATEGY_ID as _s19_id,
                STRATEGY_NAME as _s19_name,
                TIER as _s19_tier,
                L2_ADAPTERS as _s19_weights,
                TARGET_APY_PCT as _s19_target_apy,
            )
            _s19_apy_min = _s19_target_apy * 0.80
            _s19_apy_max = _s19_target_apy * 1.20
            _ms_s19 = _MSStrategyConfig(
                id=_s19_id,
                name=_s19_name,
                description="S19 Balanced L2 (ARB25%+BASE25%+OPT25%+POLY25%)",
                allocations=dict(_s19_weights),
                tier=_s19_tier,
                target_apy_min=_s19_apy_min,
                target_apy_max=_s19_apy_max,
            )
            _ms_strategies.append(_ms_s19)
        except ImportError:
            pass
        # ── BTS: S_BASIS Live Basis Trade (Funding Harvest) ───────────────
        try:
            from spa_core.strategies.s_basis import (
                STRATEGY_ID as _sbasis_id,
                STRATEGY_NAME as _sbasis_name,
                TIER as _sbasis_tier,
                ALLOCATION as _sbasis_alloc,
                TARGET_APY_MIN as _sbasis_apy_min,
                TARGET_APY_MAX as _sbasis_apy_max,
            )
            _ms_sbasis = _MSStrategyConfig(
                id=_sbasis_id,
                name=_sbasis_name,
                description=(
                    "S_BASIS Live Basis Trade: long USDC lending + "
                    "short ETH/BTC perp (funding harvest, max 20%)"
                ),
                allocations=dict(_sbasis_alloc),
                tier=_sbasis_tier,
                target_apy_min=_sbasis_apy_min,
                target_apy_max=_sbasis_apy_max,
                kill_drawdown_pct=0.05,
            )
            _ms_strategies.append(_ms_sbasis)
            log.info("S_BASIS registered in tournament")
        except ImportError as _sbasis_exc:
            log.warning(
                "S_BASIS unavailable (%s) — tournament continues without it",
                _sbasis_exc,
            )
        _ms_runner = _MultiStrategyRunner(
            strategies=_ms_strategies, capital=100_000
        )
        _ms_runner.run_day(apy_map=apy_map)
        _ms_rankings = _ms_runner.get_rankings()
        _ms_runner.export_results(ddir / "tournament_ranking.json")
        _ms_top = _ms_rankings[0] if _ms_rankings else None
        if _ms_top:
            log.info(
                "MP-386 Tournament leader: %s APY=%.4f composite=%.3f",
                _ms_top.get("strategy_id", "?"),
                _ms_top.get("net_apy", 0.0),
                _ms_top.get("composite_score", 0.0),
            )
    except Exception as _ms_exc:  # noqa: BLE001 — never crash the cycle
        log.warning("MultiStrategyRunner S2–S15 skipped: %s", _ms_exc)
