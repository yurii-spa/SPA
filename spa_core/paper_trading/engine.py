"""
SPA Paper Trading Engine — M2
Виртуальный портфель $100K. Все операции проходят через Risk Policy.

ПРАВИЛА:
  - RiskPolicy.check_new_position() вызывается ДО каждой сделки
  - Если result.approved is False — сделка ЗАПРЕЩЕНА, исключение
  - 8-недельный минимум paper trading до перехода к live
  - Никакой реальный капитал не задействован

Использование:
    from paper_trading.engine import PaperTrader
    trader = PaperTrader()
    trader.open_position("aave-v3-usdc-ethereum", amount_usd=3000.0, current_apy=4.65, tvl_usd=138e6)
    trader.print_status()

CLI:
    python engine.py --status
    python engine.py --open aave-v3-usdc-ethereum --amount 3000 --apy 4.65 --tvl 138000000
    python engine.py --close aave-v3-usdc-ethereum
    python engine.py --rebalance
"""

from __future__ import annotations

import logging
import math
import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.init_db import get_connection, get_db_path
from spa_core.risk.policy import RiskPolicy, RiskConfig, Position, PortfolioState, RiskCheckResult

# Pendle PT strategy (imported lazily where needed to avoid heavy deps at startup)
# from paper_trading.pendle_strategy import PendlePosition, pendle_allocation_size, build_pendle_position

# Optional — imported lazily to avoid circular deps; will be None if unavailable
try:
    from agents.decision_logger import DecisionLogger as _DecisionLogger
except Exception:
    _DecisionLogger = None  # type: ignore

log = logging.getLogger(__name__)

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID = "paper-v1"             # default strategy id (backward compat)
INITIAL_CAPITAL = 100_000.0          # виртуальный стартовый капитал ($100K paper trading)
MIN_PAPER_WEEKS = 8                  # минимум paper trading перед live
SHARPE_RISK_FREE_RATE = 0.05         # 5% годовых безрисковая ставка (proxy)

# ── v2 Aggressive strategy constants ──────────────────────────────────────────
_V2_T1_CAP      = 0.30   # max 30% of portfolio per T1 protocol
_V2_T2_CAP      = 0.15   # max 15% of portfolio per T2 protocol
_V2_CASH_BUFFER = 0.03   # keep 3% cash buffer
_V2_MAX_POS     = 8      # up to 8 simultaneous positions
_V2_APY_MIN     = 3.0    # min target APY
_V2_APY_MAX     = 20.0   # max target APY


# ─── Исключения ───────────────────────────────────────────────────────────────

class RiskPolicyViolation(Exception):
    """Сделка отклонена Risk Policy. Не может быть проигнорировано."""
    def __init__(self, result: RiskCheckResult):
        self.result = result
        violations = "; ".join(result.violations)
        super().__init__(f"Risk Policy REJECTED {result.check_name}: {violations}")


class InsufficientData(Exception):
    """Недостаточно данных для операции."""


# ─── Paper Trader ──────────────────────────────────────────────────────────────

class PaperTrader:
    """
    Виртуальный трейдер. Все операции детерминированы и логируются в БД.

    Жизненный цикл:
        1. open_position()  — Risk Policy check → INSERT paper_trades (OPEN)
        2. update_prices()  — обновить текущие APY/PnL из снапшотов
        3. close_position() — Risk Policy check пропускается (закрытие всегда разрешено)
                              INSERT paper_trades (CLOSE)
        4. rebalance()      — проверить все позиции, закрыть/открыть по стратегии
    """

    def __init__(
        self,
        db_path: Path = None,
        config: RiskConfig = None,
        strategy_id: str = STRATEGY_ID,
        decision_logger=None,
        live_execution: bool = False,
    ):
        self.db_path = db_path or get_db_path()
        self.policy = RiskPolicy(config=config)
        self.strategy_id = strategy_id
        # FEAT-004/005 Phase 4 (SPA-V41-001): per-strategy opt-in for the
        # live execution leg. The bridge is ONLY constructed if this flag is
        # True AND SPA_EXECUTION_MODE=live at call time. Default False keeps
        # 100+ existing call-sites byte-identical to pre-v3.11 behaviour.
        self.live_execution: bool = bool(live_execution)
        self._live_bridge = None  # lazy; see _get_live_bridge()
        # Accept an injected DecisionLogger, or create one automatically if
        # the class is available (backwards-compatible: stays None otherwise).
        if decision_logger is not None:
            self._dlog = decision_logger
        elif _DecisionLogger is not None:
            self._dlog = _DecisionLogger(
                db_path=self.db_path,
                agent_name="TraderAgent",
                strategy_id=self.strategy_id,
            )
        else:
            self._dlog = None
        self._ensure_strategy_state()

    # ── Live execution bridge (Phase 4) ───────────────────────────────────────

    def _get_live_bridge(self):
        """Lazy-construct the LiveExecutionBridge.

        Returns ``None`` if ``self.live_execution`` is False — in which case
        the caller should skip the bridge entirely. The import is performed
        here (NOT at module top) so test runs that don't touch live exec
        skip the import cost and avoid pulling adapter deps.
        """
        if not self.live_execution:
            return None
        if self._live_bridge is None:
            try:
                from execution.engine_bridge import LiveExecutionBridge
            except ImportError:
                from spa_core.execution.engine_bridge import LiveExecutionBridge
            self._live_bridge = LiveExecutionBridge()
        return self._live_bridge

    # ── Основные операции ─────────────────────────────────────────────────────

    def open_position(
        self,
        protocol_key: str,
        amount_usd: float,
        current_apy: float,
        tvl_usd: float,
    ) -> RiskCheckResult:
        """
        Открыть виртуальную позицию.

        Raises:
            RiskPolicyViolation — если Risk Policy отклонила сделку
            ValueError — если протокол не найден в whitelist
        """
        state = self._load_portfolio_state()
        proto = self._get_protocol(protocol_key)

        # ── Risk Policy check (ОБЯЗАТЕЛЬНО) ──────────────────────────────────
        result = self.policy.check_new_position(
            state=state,
            protocol_key=protocol_key,
            tier=proto["tier"],
            amount_usd=amount_usd,
            current_apy=current_apy,
            tvl_usd=tvl_usd,
        )

        if not result.approved:
            log.error(f"Trade BLOCKED by Risk Policy: {result}")
            raise RiskPolicyViolation(result)

        # ── Live execution leg (FEAT-004/005 Phase 4 — SPA-V41-001) ──────────
        # Additive: paper INSERT below is unconditional. Bridge is fully
        # gated by self.live_execution AND SPA_EXECUTION_MODE=live; if either
        # is off the bridge returns {status: SKIPPED} and we log nothing.
        bridge = self._get_live_bridge()
        if bridge is not None:
            try:
                live_result = bridge.execute_supply(protocol_key, amount_usd)
                live_status = live_result.get("status") if isinstance(live_result, dict) else "ERROR"
                if live_status in ("FAILED", "BLOCKED", "ERROR"):
                    log.warning(
                        "Live supply non-success for %s ($%.2f): status=%s reason=%s",
                        protocol_key, amount_usd, live_status,
                        live_result.get("reason") if isinstance(live_result, dict) else None,
                    )
                elif live_status == "SUCCESS":
                    log.info(
                        "Live supply SUCCESS for %s ($%.2f): supply_tx=%s",
                        protocol_key, amount_usd,
                        live_result.get("supply_tx"),
                    )
                # SKIPPED is silent at this level — bridge already logs it.
            except Exception as exc:  # noqa: BLE001 — never abort paper trade
                log.warning(
                    "Live supply bridge unexpectedly raised for %s: %s — "
                    "continuing with paper INSERT",
                    protocol_key, exc,
                )

        ts = _now()

        import uuid
        trade_id = f"PT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

        with get_connection(self.db_path) as conn:
            # Записываем сделку
            conn.execute("""
                INSERT INTO paper_trades
                    (trade_id, strategy_id, timestamp_open, protocol_key, asset, action,
                     amount_usd, apy_at_open, net_apy_annualized,
                     risk_check_passed)
                VALUES (?, ?, ?, ?, ?, 'OPEN', ?, ?, ?, 1)
            """, (trade_id, self.strategy_id, ts, protocol_key, proto["asset"],
                  amount_usd, current_apy, current_apy))

            # Обновляем strategy_state
            self._update_strategy_state(conn)
            conn.commit()

        log.info(f"Opened {protocol_key} ${amount_usd:,.0f} @ APY {current_apy:.2f}%")
        if result.warnings:
            for w in result.warnings:
                log.warning(f"  ⚠ {w}")

        return result

    def close_position(
        self,
        protocol_key: str,
        reason: str = "manual",
    ) -> dict:
        """
        Закрыть виртуальную позицию. Закрытие всегда разрешено (Risk Policy не блокирует).

        Returns:
            dict с realized_pnl_usd, days_held, net_apy_annualized
        """
        state = self._load_portfolio_state()
        open_trades = self._get_open_trades(protocol_key)

        if not open_trades:
            raise ValueError(f"No open position for {protocol_key}")

        # ── Live execution leg (FEAT-004/005 Phase 4 — SPA-V41-001) ──────────
        # Additive: SQL UPDATE below is unconditional. Bridge gated as in
        # open_position(); routes to the SAME protocol the position was
        # opened on (from paper_trades.protocol_key — already in DB).
        bridge = self._get_live_bridge()
        if bridge is not None:
            try:
                amount_total_open = sum(
                    (t["amount_usd"] or 0.0) for t in open_trades
                )
                if amount_total_open > 0:
                    live_result = bridge.execute_withdraw(
                        protocol_key, float(amount_total_open),
                    )
                    live_status = live_result.get("status") if isinstance(live_result, dict) else "ERROR"
                    if live_status in ("FAILED", "BLOCKED", "ERROR"):
                        log.warning(
                            "Live withdraw non-success for %s ($%.2f): status=%s reason=%s",
                            protocol_key, amount_total_open, live_status,
                            live_result.get("reason") if isinstance(live_result, dict) else None,
                        )
                    elif live_status == "SUCCESS":
                        log.info(
                            "Live withdraw SUCCESS for %s ($%.2f): withdraw_tx=%s",
                            protocol_key, amount_total_open,
                            live_result.get("withdraw_tx"),
                        )
            except Exception as exc:  # noqa: BLE001 — never abort paper close
                log.warning(
                    "Live withdraw bridge unexpectedly raised for %s: %s — "
                    "continuing with paper UPDATE",
                    protocol_key, exc,
                )

        ts = _now()
        total_pnl = 0.0
        total_amount = 0.0

        with get_connection(self.db_path) as conn:
            for trade in open_trades:
                trade_id = trade["trade_id"]
                amount = trade["amount_usd"]
                opened_at = datetime.fromisoformat(trade["timestamp_open"])
                days_held = (datetime.now(timezone.utc) - opened_at).total_seconds() / 86400

                # Рассчитываем PnL: amount × APY × days / 365
                apy = trade["net_apy_annualized"] or 0.0
                pnl = amount * (apy / 100) * (days_held / 365)
                total_pnl += pnl
                total_amount += amount

                # Закрываем trade
                conn.execute("""
                    UPDATE paper_trades
                    SET timestamp_close = ?,
                        pnl_usd = ?,
                        action = 'CLOSE'
                    WHERE trade_id = ?
                """, (ts, pnl, trade_id))

            self._update_strategy_state(conn)
            conn.commit()

        log.info(f"Closed {protocol_key}: PnL ${total_pnl:+.2f} | reason={reason}")

        return {
            "protocol_key": protocol_key,
            "realized_pnl_usd": round(total_pnl, 4),
            "total_amount_usd": total_amount,
            "reason": reason,
        }


    def auto_allocate(self) -> list[dict]:
        """
        Strategy v1_passive: автоматическое размещение свободного кэша.

        Логика:
        1. Взять свежие APY-данные из БД (последние 8 часов)
        2. Отсортировать по APY desc
        3. Открыть позиции в лучших протоколах в порядке убывания APY,
           пока есть кэш (≥10% портфеля)

        Не открывает повторные позиции в протоколах, где уже открыта позиция.
        """
        actions = []
        state = self._load_portfolio_state()

        min_cash_threshold = state.total_capital_usd * 0.10
        if state.cash_usd < min_cash_threshold:
            log.info(
                f"auto_allocate: cash ${state.cash_usd:.2f} < "
                f"threshold ${min_cash_threshold:.2f} (10%), skipping"
            )
            return [{"action": "NO_OP", "reason": "insufficient_cash",
                     "cash_usd": round(state.cash_usd, 2)}]

        # Свежие APY данные (не старше 8 часов, валидные)
        with get_connection(self.db_path) as conn:
            rows = conn.execute("""
                SELECT s.protocol_key, s.apy_total, s.tvl_usd, p.tier,
                       COALESCE(p.chain, 'ethereum') AS chain
                FROM apy_snapshots s
                JOIN protocols p ON p.key = s.protocol_key
                WHERE s.is_valid = 1
                  AND s.timestamp >= datetime('now', '-8 hours')
                  AND p.is_active = 1
                  AND s.id IN (
                      SELECT MAX(id) FROM apy_snapshots
                      WHERE is_valid = 1
                        AND timestamp >= datetime('now', '-8 hours')
                      GROUP BY protocol_key
                  )
                ORDER BY s.apy_total DESC
            """).fetchall()

        if not rows:
            log.info("auto_allocate: no fresh APY data (< 8h) — fetch first")
            return [{"action": "NO_OP", "reason": "no_fresh_data"}]

        # Протоколы с уже открытыми позициями
        open_protocols = {p.protocol_key for p in state.positions}

        for row in rows:
            key      = row["protocol_key"]
            apy      = row["apy_total"]
            tvl      = row["tvl_usd"]
            tier     = row["tier"]
            chain    = (row["chain"] or "ethereum").lower()

            if key in open_protocols:
                continue  # уже инвестировали

            # Обновить state для корректного расчёта лимитов
            state = self._load_portfolio_state()
            if state.cash_usd < min_cash_threshold:
                break  # кэш исчерпан

            amount = self.policy.max_safe_position_size(state, key, tier)
            if amount < 10.0:  # минимальная позиция $10
                log.debug(f"auto_allocate: {key} max_safe_size=${amount:.2f} too small, skip")
                if self._dlog:
                    self._dlog.log_pass(
                        key,
                        f"{key} skipped: max safe position ${amount:.2f} below $10 minimum",
                        apy=apy,
                        data={"tvl_usd": tvl, "tier": tier},
                    )
                continue

            try:
                result = self.open_position(key, amount, apy, tvl)
                actions.append({
                    "action":     "OPEN",
                    "protocol":   key,
                    "amount_usd": round(amount, 2),
                    "apy":        round(apy, 4),
                    "tier":       tier,
                    "chain":      chain,
                    "approved":   result.approved,
                    "warnings":   result.warnings,
                })
                open_protocols.add(key)
                log.info(
                    f"auto_allocate: opened {key} [{chain}] "
                    f"${amount:.2f} @ APY {apy:.2f}%"
                )
                if self._dlog:
                    conc_pct = state.concentration_pct(key) * 100
                    reasoning = (
                        f"{key} selected: APY {apy:.2f}% within target range, "
                        f"TVL ${tvl/1e6:.1f}M, {tier} tier, chain={chain}, "
                        f"concentration {conc_pct:.0f}%, RiskPolicy APPROVED"
                    )
                    if result.warnings:
                        reasoning += f"; warnings: {'; '.join(result.warnings)}"
                    self._dlog.log_allocate(
                        key, amount, apy, tier, reasoning, risk_approved=True
                    )
            except RiskPolicyViolation as exc:
                log.warning(f"auto_allocate: {key} blocked by risk policy: {exc}")
                actions.append({
                    "action":   "BLOCKED",
                    "protocol": key,
                    "chain":    chain,
                    "reason":   str(exc),
                })
                if self._dlog:
                    violations = "; ".join(exc.result.violations)
                    self._dlog.log_pass(
                        key,
                        f"{key} blocked by RiskPolicy: {violations}",
                        apy=apy,
                        data={"tvl_usd": tvl, "tier": tier, "chain": chain,
                              "violations": exc.result.violations},
                    )
            except Exception as exc:
                log.error(f"auto_allocate: unexpected error for {key}: {exc}", exc_info=True)
                actions.append({
                    "action":   "ERROR",
                    "protocol": key,
                    "chain":    chain,
                    "reason":   str(exc),
                })

        # ── Pendle PT allocation (T2, fixed-rate) ────────────────────────────
        # After T1/T2 lending pools, check if any Pendle PT pools are available.
        # Pendle positions use fixed APY locked at entry — modelled separately
        # from variable-rate lending positions.
        # ADR-002 PROPOSED: paper test only until owner approves go-live.
        try:
            state = self._load_portfolio_state()
            # Only proceed if we have meaningful cash left (≥ $1,000 or 1% of capital)
            min_pendle_cash = max(1_000.0, state.total_capital_usd * 0.01)
            if state.cash_usd >= min_pendle_cash:
                from data_pipeline.pendle_fetcher import PendleFetcher
                from paper_trading.pendle_strategy import pendle_allocation_size, build_pendle_position

                best_pt = PendleFetcher().get_best_pt()
                if best_pt:
                    # Compute T2 allocation size based on APY premium over T1 baseline
                    # T1 baseline approximated from current positions or 4% default
                    t1_positions = [p for p in state.positions if p.tier == "T1"]
                    t1_baseline = (
                        sum(p.current_apy for p in t1_positions) / len(t1_positions)
                        if t1_positions else 4.0
                    )
                    # Build the protocol key early so we can call max_safe_position_size
                    pendle_protocol_key = (
                        f"pendle-pt-{best_pt.get('symbol', 'unknown').lower()}"
                    )
                    pendle_chain = best_pt.get("chain", "arbitrum")

                    # Strategy preference: how much we'd like to allocate
                    # Uses the TOTAL T2 cap as the ceiling for the formula, but the
                    # actual per-protocol concentration limit (max_concentration_t2)
                    # is enforced by max_safe_position_size() below.
                    t2_cap_pct = self.policy.config.max_total_t2_allocation  # e.g. 0.35
                    pendle_want = pendle_allocation_size(
                        capital=state.total_capital_usd,
                        current_apy=best_pt["apy"],
                        t1_baseline_apy=t1_baseline,
                        max_t2_pct=t2_cap_pct,
                    )
                    # Hard ceiling from risk policy (respects per-protocol T2 concentration
                    # AND total T2 aggregate AND cash buffer — all at once)
                    pendle_max_safe = self.policy.max_safe_position_size(
                        state, pendle_protocol_key, "T2"
                    )
                    pendle_size = min(pendle_want, pendle_max_safe, state.cash_usd - min_pendle_cash)
                    pendle_size = round(pendle_size, 2)

                    if pendle_size >= 100.0:  # minimum meaningful Pendle position
                        # Run full RiskPolicy check — final gate for Pendle positions.
                        # max_safe_position_size() already pre-screened the size, so this
                        # should normally pass. It catches edge-cases (e.g. race conditions
                        # between state reads) and adds the circuit-breaker checks.
                        pendle_risk = self.policy.check_new_position(
                            state=state,
                            protocol_key=pendle_protocol_key,
                            tier="T2",
                            amount_usd=pendle_size,
                            current_apy=best_pt["apy"],
                            tvl_usd=best_pt.get("tvl_usd", 0.0),
                            chain=pendle_chain,
                        )
                        if not pendle_risk.approved:
                            log.info(
                                f"auto_allocate: Pendle PT blocked by RiskPolicy — "
                                f"{'; '.join(pendle_risk.violations)}"
                            )
                            actions.append({
                                "action":   "BLOCKED",
                                "protocol": pendle_protocol_key,
                                "chain":    pendle_chain,
                                "tier":     "T2",
                                "reason":   "; ".join(pendle_risk.violations),
                                "note":     "Pendle PT blocked by RiskPolicy T2 limit",
                            })
                        else:
                            position = build_pendle_position(best_pt, pendle_size)
                            actions.append({
                                "action":           "OPEN_PENDLE_PT",
                                "protocol":         pendle_protocol_key,
                                "symbol":           best_pt.get("symbol"),
                                "chain":            pendle_chain,
                                "amount_usd":       pendle_size,
                                "apy":              best_pt["apy"],
                                "tier":             "T2",
                                "special":          "fixed_rate",
                                "maturity_date":    best_pt.get("maturity_date"),
                                "days_to_maturity": best_pt.get("days_to_maturity"),
                                "t1_baseline_apy":  round(t1_baseline, 4),
                                "apy_premium":      round(best_pt["apy"] - t1_baseline, 4),
                                "approved":         True,
                                "warnings":         pendle_risk.warnings,
                                "note":             "ADR-002 PROPOSED — paper only",
                            })
                            log.info(
                                f"auto_allocate: Pendle PT {best_pt.get('symbol')} "
                                f"${pendle_size:,.2f} @ {best_pt['apy']:.2f}% APY "
                                f"(premium +{best_pt['apy'] - t1_baseline:.2f}% over T1 baseline, "
                                f"RiskPolicy APPROVED)"
                            )
                    else:
                        log.info(
                            f"auto_allocate: Pendle PT skipped — "
                            f"size ${pendle_size:.2f} < $100 minimum "
                            f"(max_safe=${pendle_max_safe:.0f}, cash=${state.cash_usd:.0f})"
                        )
                else:
                    log.debug("auto_allocate: no eligible Pendle PT pools available")
        except Exception as exc:
            log.warning(f"auto_allocate: Pendle PT allocation failed (non-fatal): {exc}")

        # Check for drift-based rebalancing
        try:
            _rebal_state = self._load_portfolio_state()
            _rebal_positions = [
                {"protocol": p.protocol_key, "amount_usd": p.amount_usd}
                for p in _rebal_state.positions
            ]
            if self.should_rebalance(_rebal_positions, _rebal_state.total_capital_usd):
                rebalance_ops = self.rebalance_actions(
                    _rebal_positions, _rebal_state.total_capital_usd
                )
                for op in rebalance_ops:
                    actions.append(op)
                if rebalance_ops:
                    print(f"[REBALANCE] {len(rebalance_ops)} positions flagged for rebalancing")
        except Exception as _re:
            log.warning(f"auto_allocate: drift rebalance check failed (non-fatal): {_re}")

        if not actions:
            actions.append({"action": "NO_OP", "reason": "no_suitable_protocol"})

        return actions

    def auto_allocate_v2(self, pools: list[dict] | None = None) -> list[dict]:
        """
        Strategy v2_aggressive: агрессивное размещение — T1 + T2, выше APY.

        Параметры стратегии:
          - T1 cap: 30% на протокол (vs 40% в v1)
          - T2 cap: 15% на протокол (vs 20% в v1)
          - Cash buffer: 3% (vs 5% в v1)
          - До 8 позиций (vs 5 в v1)
          - APY диапазон: 3–20%

        Args:
            pools: Опциональный список пулов [{protocol_key, apy_total, tvl_usd, tier}].
                   Если None — данные читаются из БД (не старше 8 часов).

        Returns:
            Список действий в том же формате что и auto_allocate().
        """
        actions = []
        state = self._load_portfolio_state()

        min_cash_threshold = state.total_capital_usd * _V2_CASH_BUFFER
        if state.cash_usd < min_cash_threshold:
            log.info(
                f"auto_allocate_v2: cash ${state.cash_usd:.2f} < "
                f"threshold ${min_cash_threshold:.2f} ({_V2_CASH_BUFFER:.0%}), skipping"
            )
            return [{"action": "NO_OP", "reason": "insufficient_cash",
                     "cash_usd": round(state.cash_usd, 2)}]

        # Если пулы не переданы — читаем из БД (T1 + T2, не старше 8 часов)
        if pools is None:
            with get_connection(self.db_path) as conn:
                rows = conn.execute("""
                    SELECT s.protocol_key, s.apy_total, s.tvl_usd, p.tier,
                           COALESCE(p.chain, 'ethereum') AS chain
                    FROM apy_snapshots s
                    JOIN protocols p ON p.key = s.protocol_key
                    WHERE s.is_valid = 1
                      AND s.timestamp >= datetime('now', '-8 hours')
                      AND p.is_active = 1
                      AND p.tier IN ('T1', 'T2')
                      AND s.id IN (
                          SELECT MAX(id) FROM apy_snapshots
                          WHERE is_valid = 1
                            AND timestamp >= datetime('now', '-8 hours')
                          GROUP BY protocol_key
                      )
                    ORDER BY s.apy_total DESC
                """).fetchall()
            pools = [dict(r) for r in rows]

        if not pools:
            log.info("auto_allocate_v2: no fresh APY data (< 8h) — fetch first")
            return [{"action": "NO_OP", "reason": "no_fresh_data"}]

        # Протоколы с уже открытыми позициями
        open_protocols = {p.protocol_key for p in state.positions}

        _V2_L2_CHAINS = {"arbitrum", "base"}  # RiskPolicy preferred_chains: only Arbitrum + Base allowed
        _V2_CHAIN_CAP = 0.60   # max 60% on any single chain (mirrors RiskConfig default)
        _V2_L2_CAP    = 0.50   # max 50% total on L2s

        for row in pools:
            key   = row["protocol_key"]
            apy   = row["apy_total"]
            tvl   = row["tvl_usd"]
            tier  = row["tier"]
            chain = (row.get("chain") or "ethereum").lower()

            # Только APY в целевом диапазоне стратегии
            if not (_V2_APY_MIN <= apy <= _V2_APY_MAX):
                if self._dlog:
                    self._dlog.log_pass(
                        key,
                        f"{key} skipped: APY {apy:.2f}% outside v2 target range "
                        f"[{_V2_APY_MIN}–{_V2_APY_MAX}%]",
                        apy=apy,
                        data={"tvl_usd": tvl, "tier": tier, "chain": chain},
                    )
                continue

            if key in open_protocols:
                continue  # уже инвестировали

            # Лимит позиций
            if len(open_protocols) >= _V2_MAX_POS:
                log.info(f"auto_allocate_v2: max positions ({_V2_MAX_POS}) reached")
                break

            # Обновить state для актуальных расчётов
            state = self._load_portfolio_state()
            if state.cash_usd < min_cash_threshold:
                break

            capital = state.total_capital_usd

            # v2 concentration caps (tighter than risk policy defaults)
            conc_cap = _V2_T1_CAP if tier == "T1" else _V2_T2_CAP
            max_by_conc = conc_cap * capital - state.concentration_pct(key) * capital
            max_by_cash = state.cash_usd - _V2_CASH_BUFFER * capital

            # Chain limits for v2 (cross-L2 allocation)
            chain_remaining = _V2_CHAIN_CAP * capital - state.chain_allocation_pct(chain) * capital
            l2_remaining = float("inf")
            if chain.lower() in _V2_L2_CHAINS:
                l2_remaining = _V2_L2_CAP * capital - state.l2_allocation_pct() * capital
            max_by_chain = min(chain_remaining, l2_remaining)

            amount = round(max(0.0, min(max_by_conc, max_by_cash, max_by_chain)), 2)

            if amount < 10.0:
                log.debug(f"auto_allocate_v2: {key} max_size=${amount:.2f} too small, skip")
                if self._dlog:
                    conc_pct = state.concentration_pct(key) * 100
                    self._dlog.log_pass(
                        key,
                        f"{key} skipped: {tier} concentration {conc_pct:.1f}% would exceed "
                        f"{conc_cap*100:.0f}% v2 limit, or cash/chain limit exhausted",
                        apy=apy,
                        data={"tvl_usd": tvl, "tier": tier, "chain": chain,
                              "max_by_conc": max_by_conc, "max_by_cash": max_by_cash,
                              "max_by_chain": max_by_chain},
                    )
                continue

            try:
                result = self.open_position(key, amount, apy, tvl)
                actions.append({
                    "action":     "OPEN",
                    "protocol":   key,
                    "amount_usd": amount,
                    "apy":        round(apy, 4),
                    "tier":       tier,
                    "chain":      chain,
                    "approved":   result.approved,
                    "warnings":   result.warnings,
                    "strategy":   "v2_aggressive",
                })
                open_protocols.add(key)
                log.info(f"auto_allocate_v2: opened {key} [{chain}] ${amount:.2f} @ APY {apy:.2f}%")
                if self._dlog:
                    conc_pct = state.concentration_pct(key) * 100
                    reasoning = (
                        f"{key} selected [v2_aggressive]: APY {apy:.2f}% in range "
                        f"[{_V2_APY_MIN}–{_V2_APY_MAX}%], TVL ${tvl/1e6:.1f}M, "
                        f"{tier} tier, chain={chain}, concentration {conc_pct:.0f}%, "
                        f"RiskPolicy APPROVED"
                    )
                    if result.warnings:
                        reasoning += f"; warnings: {'; '.join(result.warnings)}"
                    self._dlog.log_allocate(
                        key, amount, apy, tier, reasoning, risk_approved=True
                    )
            except RiskPolicyViolation as exc:
                log.warning(f"auto_allocate_v2: {key} blocked by risk policy: {exc}")
                actions.append({
                    "action":   "BLOCKED",
                    "protocol": key,
                    "chain":    chain,
                    "reason":   str(exc),
                    "strategy": "v2_aggressive",
                })
                if self._dlog:
                    violations = "; ".join(exc.result.violations)
                    self._dlog.log_pass(
                        key,
                        f"{key} blocked by RiskPolicy [v2_aggressive]: {violations}",
                        apy=apy,
                        data={"tvl_usd": tvl, "tier": tier, "chain": chain,
                              "violations": exc.result.violations},
                    )
            except Exception as exc:
                log.error(f"auto_allocate_v2: unexpected error for {key}: {exc}", exc_info=True)
                actions.append({
                    "action":   "ERROR",
                    "protocol": key,
                    "chain":    chain,
                    "reason":   str(exc),
                    "strategy": "v2_aggressive",
                })

        if not actions:
            actions.append({"action": "NO_OP", "reason": "no_suitable_protocol",
                            "strategy": "v2_aggressive"})

        return actions

    def rebalance(self) -> list[dict]:
        """
        Автоматическая ребалансировка:
        1. Проверить здоровье портфеля (kill switch)
        2. Закрыть позиции с drawdown > порог
        3. Не открывать новых (это задача стратегии/агента)

        Returns список действий.
        """
        actions = []
        state = self._load_portfolio_state()

        # Проверка здоровья
        health = self.policy.check_portfolio_health(state)
        if not health.approved:
            log.error(f"Portfolio health check FAILED: {health}")
            # Kill switch — закрываем всё
            for pos in state.positions:
                try:
                    result = self.close_position(pos.protocol_key, reason="kill_switch")
                    actions.append({"action": "CLOSE", "protocol": pos.protocol_key,
                                    "reason": "kill_switch", **result})
                except Exception as e:
                    log.error(f"Failed to close {pos.protocol_key}: {e}")
            return actions

        # Закрыть позиции с критическим drawdown
        for pos in state.positions:
            if pos.unrealized_pnl_pct < -self.policy.config.max_single_position_drawdown:
                log.warning(f"Closing {pos.protocol_key}: drawdown {pos.unrealized_pnl_pct:.1%}")
                result = self.close_position(pos.protocol_key, reason="drawdown_stop")
                actions.append({"action": "CLOSE", "protocol": pos.protocol_key,
                                 "reason": "drawdown_stop", **result})

        if not actions:
            actions.append({"action": "NO_OP", "reason": "portfolio_healthy"})

        return actions

    def update_prices(self) -> int:
        """
        Обновить unrealized PnL для всех открытых позиций
        на основе последних снапшотов из БД.

        Returns количество обновлённых позиций.
        """
        updated = 0
        with get_connection(self.db_path) as conn:
            open_trades = conn.execute("""
                SELECT t.trade_id, t.protocol_key, t.amount_usd,
                       t.net_apy_annualized, t.timestamp_open
                FROM paper_trades t
                WHERE t.strategy_id = ? AND t.timestamp_close IS NULL
            """, (self.strategy_id,)).fetchall()

            for trade in open_trades:
                # Последний APY из снапшотов
                snap = conn.execute("""
                    SELECT apy_total FROM apy_snapshots
                    WHERE protocol_key = ?
                    ORDER BY timestamp DESC LIMIT 1
                """, (trade["protocol_key"],)).fetchone()

                if not snap:
                    continue

                current_apy = snap["apy_total"]
                opened_at = datetime.fromisoformat(trade["timestamp_open"])
                days_held = (datetime.now(timezone.utc) - opened_at).total_seconds() / 86400
                pnl = trade["amount_usd"] * (current_apy / 100) * (days_held / 365)

                conn.execute("""
                    UPDATE paper_trades
                    SET pnl_usd = ?, net_apy_annualized = ?
                    WHERE trade_id = ?
                """, (pnl, current_apy, trade["trade_id"]))
                updated += 1

            if updated:
                self._update_strategy_state(conn)
                conn.commit()

        return updated

    # ── Статус и метрики ──────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Вернуть полный статус портфеля."""
        state = self._load_portfolio_state()
        strategy = self._get_strategy_state()
        health = self.policy.check_portfolio_health(state)
        var = self.policy.calculate_var(state)

        # 8-week clock
        first_trade_ts = self._get_first_trade_ts()
        paper_days = 0
        go_live_ready = False
        if first_trade_ts:
            paper_days = (datetime.now(timezone.utc) - first_trade_ts).days
            go_live_ready = paper_days >= MIN_PAPER_WEEKS * 7

        return {
            "timestamp": _now(),
            "portfolio": {
                "total_capital_usd": state.total_capital_usd,
                "deployed_usd": state.deployed_usd,
                "cash_usd": state.cash_usd,
                "cash_pct": round(state.cash_pct, 4),
                "total_pnl_usd": round(state.total_pnl_usd, 2),
                "total_drawdown_pct": round(state.total_drawdown_pct, 4),
            },
            "positions": [
                {
                    "protocol_key": p.protocol_key,
                    "tier": p.tier,
                    "amount_usd": p.amount_usd,
                    "current_apy": p.current_apy,
                    "unrealized_pnl_usd": round(p.unrealized_pnl_usd, 2),
                    "unrealized_pnl_pct": round(p.unrealized_pnl_pct, 4),
                    "days_held": round(p.days_held, 1),
                }
                for p in state.positions
            ],
            "risk": {
                "health_approved": health.approved,
                "violations": health.violations,
                "warnings": health.warnings,
                "var_usd": var["var_usd"],
                "var_pct": round(var["var_pct"] * 100, 3),
                "var_breach": var["breach"],
            },
            "paper_trading": {
                "days_elapsed": paper_days,
                "weeks_elapsed": round(paper_days / 7, 1),
                "min_weeks_required": MIN_PAPER_WEEKS,
                "go_live_ready": go_live_ready,
                "first_trade": first_trade_ts.isoformat() if first_trade_ts else None,
            },
            "strategy": dict(strategy) if strategy else {},
        }

    def print_status(self) -> None:
        """Вывести статус портфеля в консоль."""
        s = self.get_status()
        p = s["portfolio"]
        r = s["risk"]
        pt = s["paper_trading"]

        print(f"\n{'═'*60}")
        print(f"  SPA Paper Trading — {s['timestamp'][:19]} UTC")
        print(f"{'═'*60}")

        # Portfolio summary
        pnl_sign = "+" if p["total_pnl_usd"] >= 0 else ""
        print(f"\n  💰 Portfolio: ${p['total_capital_usd']:,.0f} total")
        print(f"     Deployed:  ${p['deployed_usd']:,.0f}  ({1-p['cash_pct']:.0%})")
        print(f"     Cash:      ${p['cash_usd']:,.0f}  ({p['cash_pct']:.0%})")
        print(f"     PnL:       {pnl_sign}${p['total_pnl_usd']:.2f}")
        print(f"     Drawdown:  {p['total_drawdown_pct']:.2%}")

        # Positions
        if s["positions"]:
            print(f"\n  📊 Positions:")
            print(f"     {'Protocol':<35} {'Tier':<4} {'$Amount':>9} {'APY':>6} {'PnL':>9}")
            print(f"     {'─'*68}")
            for pos in s["positions"]:
                sign = "+" if pos["unrealized_pnl_usd"] >= 0 else ""
                print(f"     {pos['protocol_key']:<35} {pos['tier']:<4} "
                      f"${pos['amount_usd']:>8,.0f} {pos['current_apy']:>5.2f}% "
                      f"{sign}${pos['unrealized_pnl_usd']:>7.2f}")
        else:
            print(f"\n  📊 Positions: none")

        # Risk
        health_icon = "✅" if r["health_approved"] else "🚨"
        print(f"\n  {health_icon} Risk Health: {'OK' if r['health_approved'] else 'ALERT'}")
        for v in r["violations"]:
            print(f"     ✗ {v}")
        for w in r["warnings"]:
            print(f"     ⚠ {w}")
        print(f"     VaR (95%, 7d): ${r['var_usd']:.2f}  ({r['var_pct']:.3f}%)")

        # Paper trading clock
        clock_icon = "✅" if pt["go_live_ready"] else "⏳"
        print(f"\n  {clock_icon} Paper Trading: week {pt['weeks_elapsed']:.1f} / {pt['min_weeks_required']}")
        if not pt["go_live_ready"]:
            weeks_left = pt["min_weeks_required"] - pt["weeks_elapsed"]
            print(f"     {weeks_left:.1f} weeks until Go-Live eligible")
        else:
            print(f"     ✅ Go-Live eligible (ADR required)")

        print(f"\n{'═'*60}\n")

    def max_safe_size(self, protocol_key: str) -> float:
        """Максимальный безопасный размер позиции для протокола."""
        state = self._load_portfolio_state()
        proto = self._get_protocol(protocol_key)
        return self.policy.max_safe_position_size(state, protocol_key, proto["tier"])

    # ── Drift-based rebalancing ───────────────────────────────────────────────

    def calculate_drift(self, positions: list, total_value: float) -> list:
        """
        Calculate how much each position has drifted from its target allocation.

        Args:
            positions: list of dicts with keys: protocol (or protocol_key),
                       amount_usd, and optional target_pct.
            total_value: total portfolio value in USD (deployed + cash).

        Returns:
            list of drift records:
            {
                "protocol": str,
                "current_pct": float,
                "target_pct": float,
                "drift_pct": float,     # current - target (positive = overweight)
                "drift_usd": float,
                "action": "TRIM" | "ADD" | "OK",
                "urgency": "HIGH" | "MEDIUM" | "LOW"
            }
        """
        if not total_value or total_value <= 0:
            return []

        result = []
        for pos in positions:
            # Support both dict positions and Position dataclass objects
            if isinstance(pos, dict):
                protocol = pos.get("protocol") or pos.get("protocol_key", "unknown")
                amount_usd = pos.get("amount_usd", 0.0)
                target_pct_override = pos.get("target_pct")
            else:
                protocol = getattr(pos, "protocol_key", str(pos))
                amount_usd = getattr(pos, "amount_usd", 0.0)
                target_pct_override = getattr(pos, "target_pct", None)

            current_pct = amount_usd / total_value * 100.0

            # Use explicit target if set, otherwise assume current allocation IS the target
            target_pct = target_pct_override if target_pct_override is not None else current_pct

            drift_pct = current_pct - target_pct
            drift_usd = drift_pct / 100.0 * total_value

            abs_drift = abs(drift_pct)
            if drift_pct > 5.0:
                action = "TRIM"
            elif drift_pct < -5.0:
                action = "ADD"
            else:
                action = "OK"

            if abs_drift > 10.0:
                urgency = "HIGH"
            elif abs_drift > 5.0:
                urgency = "MEDIUM"
            else:
                urgency = "LOW"

            result.append({
                "protocol":    protocol,
                "current_pct": round(current_pct, 4),
                "target_pct":  round(target_pct, 4),
                "drift_pct":   round(drift_pct, 4),
                "drift_usd":   round(drift_usd, 2),
                "action":      action,
                "urgency":     urgency,
            })

        return result

    def should_rebalance(self, positions: list, total_value: float) -> bool:
        """
        Returns True if any position has drift > 5% from target, or if
        cash is outside the acceptable range [3%, 20%].
        """
        if not total_value or total_value <= 0:
            return False

        # Check cash bounds
        deployed_usd = sum(
            (p.get("amount_usd", 0.0) if isinstance(p, dict) else getattr(p, "amount_usd", 0.0))
            for p in positions
        )
        cash_usd = total_value - deployed_usd
        cash_pct = cash_usd / total_value * 100.0
        if not (3.0 <= cash_pct <= 20.0):
            return True

        # Check position drift
        drift_records = self.calculate_drift(positions, total_value)
        return any(rec["action"] != "OK" for rec in drift_records)

    def rebalance_actions(self, positions: list, total_value: float) -> list:
        """
        For each position needing rebalancing (action != "OK"), produce a
        rebalance trade dict.

        Returns:
            list of rebalance action dicts:
            {
                "action": "REBALANCE_TRIM" | "REBALANCE_ADD",
                "protocol": str,
                "amount_usd": float,   # abs(drift_usd)
                "from_pct": float,
                "to_pct": float,
                "reason": str
            }
        """
        drift_records = self.calculate_drift(positions, total_value)
        actions = []
        for rec in drift_records:
            if rec["action"] == "OK":
                continue
            rebal_action = "REBALANCE_TRIM" if rec["action"] == "TRIM" else "REBALANCE_ADD"
            actions.append({
                "action":     rebal_action,
                "protocol":   rec["protocol"],
                "amount_usd": abs(rec["drift_usd"]),
                "from_pct":   rec["current_pct"],
                "to_pct":     rec["target_pct"],
                "reason":     f"Drift {rec['drift_pct']:+.1f}% from target",
            })
        return actions

    # ── Внутренние методы ─────────────────────────────────────────────────────

    def _load_portfolio_state(self) -> PortfolioState:
        """Загрузить текущее состояние портфеля из БД."""
        with get_connection(self.db_path) as conn:
            strategy = conn.execute("""
                SELECT total_capital_usd FROM strategy_state
                WHERE strategy_id = ?
                ORDER BY id DESC LIMIT 1
            """, (self.strategy_id,)).fetchone()

            total_capital = strategy["total_capital_usd"] if strategy else INITIAL_CAPITAL

            open_trades = conn.execute("""
                SELECT t.trade_id, t.protocol_key, t.amount_usd,
                       t.net_apy_annualized, t.pnl_usd, t.timestamp_open,
                       p.tier, p.asset,
                       COALESCE(p.chain, 'ethereum') AS chain
                FROM paper_trades t
                JOIN protocols p ON t.protocol_key = p.key
                WHERE t.strategy_id = ? AND t.timestamp_close IS NULL
                ORDER BY t.timestamp_open
            """, (self.strategy_id,)).fetchall()

            positions = []
            for t in open_trades:
                opened_at = datetime.fromisoformat(t["timestamp_open"])
                days_held = (datetime.now(timezone.utc) - opened_at).total_seconds() / 86400

                # Текущий APY из последнего снапшота
                snap = conn.execute("""
                    SELECT apy_total FROM apy_snapshots
                    WHERE protocol_key = ?
                    ORDER BY timestamp DESC LIMIT 1
                """, (t["protocol_key"],)).fetchone()
                current_apy = snap["apy_total"] if snap else (t["net_apy_annualized"] or 0.0)

                # PnL = amount × current_APY × days / 365
                pnl = t["amount_usd"] * (current_apy / 100) * (days_held / 365)

                positions.append(Position(
                    protocol_key=t["protocol_key"],
                    tier=t["tier"],
                    asset=t["asset"],
                    chain=(t["chain"] or "ethereum").lower(),
                    amount_usd=t["amount_usd"],
                    apy_at_open=t["net_apy_annualized"] or current_apy,
                    current_apy=current_apy,
                    unrealized_pnl_usd=round(pnl, 4),
                    days_held=round(days_held, 2),
                ))

        return PortfolioState(total_capital_usd=total_capital, positions=positions)

    def _get_open_trades(self, protocol_key: str) -> list:
        with get_connection(self.db_path) as conn:
            return conn.execute("""
                SELECT trade_id, protocol_key, amount_usd,
                       net_apy_annualized, timestamp_open
                FROM paper_trades
                WHERE strategy_id = ? AND protocol_key = ?
                  AND timestamp_close IS NULL
            """, (self.strategy_id, protocol_key)).fetchall()

    def _get_protocol(self, protocol_key: str) -> dict:
        with get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM protocols WHERE key = ?", (protocol_key,)
            ).fetchone()
        if not row:
            raise ValueError(f"Protocol '{protocol_key}' not found in whitelist")
        return dict(row)

    def _ensure_strategy_state(self) -> None:
        with get_connection(self.db_path) as conn:
            existing = conn.execute(
                "SELECT id, total_capital_usd FROM strategy_state WHERE strategy_id = ? ORDER BY id DESC LIMIT 1",
                (self.strategy_id,)
            ).fetchone()
            if not existing:
                conn.execute("""
                    INSERT INTO strategy_state
                        (strategy_id, total_capital_usd, deployed_capital_usd,
                         cash_usd, total_pnl_usd, max_drawdown_pct,
                         sharpe_to_date, trade_count)
                    VALUES (?, ?, 0, ?, 0, 0, 0, 0)
                """, (self.strategy_id, INITIAL_CAPITAL, INITIAL_CAPITAL))
                conn.commit()
                log.info(f"Strategy state initialised: {self.strategy_id}, capital=${INITIAL_CAPITAL:,.2f}")
            elif existing["total_capital_usd"] != INITIAL_CAPITAL:
                # Капитал изменился — безопасно мигрировать если нет сделок
                trade_count = conn.execute(
                    "SELECT COUNT(*) FROM paper_trades WHERE strategy_id = ?", (self.strategy_id,)
                ).fetchone()[0]
                if trade_count == 0:
                    conn.execute("""
                        UPDATE strategy_state SET
                            total_capital_usd = ?,
                            cash_usd = ?,
                            deployed_capital_usd = 0,
                            total_pnl_usd = 0
                        WHERE strategy_id = ?
                    """, (INITIAL_CAPITAL, INITIAL_CAPITAL, self.strategy_id))
                    conn.commit()
                    old_cap = existing["total_capital_usd"]
                    log.info(f"Capital migrated: ${old_cap:,.2f} → ${INITIAL_CAPITAL:,.2f}")
                else:
                    log.warning(f"Capital mismatch (${existing['total_capital_usd']} vs ${INITIAL_CAPITAL}) "
                                f"but {trade_count} trades exist — keeping existing capital")

    def _update_strategy_state(self, conn) -> None:
        """Recompute and persist strategy_state within the current transaction.

        IMPORTANT: reads portfolio state through the provided *conn* so that
        uncommitted INSERTs/UPDATEs made earlier in the same transaction are
        visible.  Calling self._load_portfolio_state() here would open a *new*
        connection and therefore miss any uncommitted changes (B011 fix).
        """
        # --- Read current capital from strategy_state via the same conn ----------
        strategy = conn.execute("""
            SELECT total_capital_usd FROM strategy_state
            WHERE strategy_id = ?
            ORDER BY id DESC LIMIT 1
        """, (self.strategy_id,)).fetchone()
        total_capital = strategy["total_capital_usd"] if strategy else INITIAL_CAPITAL

        # --- Read open positions via the same conn (sees uncommitted inserts) ----
        open_trades = conn.execute("""
            SELECT t.trade_id, t.protocol_key, t.amount_usd,
                   t.net_apy_annualized
            FROM paper_trades t
            WHERE t.strategy_id = ? AND t.timestamp_close IS NULL
        """, (self.strategy_id,)).fetchall()

        deployed_usd = 0.0
        total_pnl    = 0.0
        apys: list[float] = []

        now_utc = datetime.now(timezone.utc)
        for t in open_trades:
            amt  = t["amount_usd"] or 0.0
            apy  = t["net_apy_annualized"] or 0.0
            # Best-effort: use APY stored at open (live snapshot not available here)
            snap = conn.execute("""
                SELECT apy_total FROM apy_snapshots
                WHERE protocol_key = ?
                ORDER BY timestamp DESC LIMIT 1
            """, (t["protocol_key"],)).fetchone()
            if snap:
                apy = snap["apy_total"]

            # Approximate PnL since open (days_held unavailable without timestamp_open here,
            # so use APY × amount as a proxy for unrealised yield direction)
            deployed_usd += amt
            total_pnl    += amt * (apy / 100) / 365  # single-day proxy; accurate at close
            apys.append(apy)

        cash_usd   = max(total_capital - deployed_usd, 0.0)
        drawdown   = abs(total_pnl) / total_capital if total_capital > 0 and total_pnl < 0 else 0.0

        # Sharpe proxy: (avg_apy - risk_free) / std_apy
        if apys:
            avg_apy = sum(apys) / len(apys)
            std_apy = math.sqrt(sum((a - avg_apy) ** 2 for a in apys) / len(apys)) if len(apys) > 1 else 1.0
            sharpe  = (avg_apy - SHARPE_RISK_FREE_RATE * 100) / max(std_apy, 0.1)
        else:
            sharpe = 0.0

        trade_count = conn.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE strategy_id = ?", (self.strategy_id,)
        ).fetchone()[0]

        conn.execute("""
            UPDATE strategy_state SET
                deployed_capital_usd = ?,
                cash_usd             = ?,
                total_pnl_usd        = ?,
                max_drawdown_pct     = MAX(COALESCE(max_drawdown_pct, 0), ?),
                sharpe_to_date       = ?,
                trade_count          = ?
            WHERE strategy_id = ?
        """, (
            deployed_usd,
            cash_usd,
            total_pnl,
            drawdown,
            round(sharpe, 4),
            trade_count,
            self.strategy_id,
        ))

    def _get_strategy_state(self):
        with get_connection(self.db_path) as conn:
            return conn.execute(
                "SELECT * FROM strategy_state WHERE strategy_id = ?", (self.strategy_id,)
            ).fetchone()

    def _get_first_trade_ts(self) -> Optional[datetime]:
        with get_connection(self.db_path) as conn:
            row = conn.execute("""
                SELECT MIN(timestamp_open) FROM paper_trades
                WHERE strategy_id = ?
            """, (self.strategy_id,)).fetchone()
        if row and row[0]:
            return datetime.fromisoformat(row[0])
        return None


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    parser = argparse.ArgumentParser(description="SPA Paper Trader CLI")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--status",    action="store_true", help="Show portfolio status")
    group.add_argument("--open",      metavar="PROTOCOL",  help="Open position")
    group.add_argument("--close",     metavar="PROTOCOL",  help="Close position")
    group.add_argument("--rebalance", action="store_true", help="Run rebalance check")
    group.add_argument("--update",    action="store_true", help="Update prices from DB snapshots")
    group.add_argument("--json",      action="store_true", help="Print status as JSON")

    parser.add_argument("--amount",  type=float, help="Position size in USD (for --open)")
    parser.add_argument("--apy",     type=float, help="Current APY %% (for --open)")
    parser.add_argument("--tvl",     type=float, help="TVL in USD (for --open)")
    parser.add_argument("--reason",  default="manual", help="Close reason")

    args = parser.parse_args()
    trader = PaperTrader()

    if args.status or args.json:
        if args.json:
            import json as _json
            print(_json.dumps(trader.get_status(), indent=2, default=str))
        else:
            trader.print_status()

    elif args.open:
        if not all([args.amount, args.apy, args.tvl]):
            parser.error("--open requires --amount, --apy, and --tvl")
        try:
            result = trader.open_position(args.open, args.amount, args.apy, args.tvl)
            print(f"✅ Opened {args.open} ${args.amount:,.0f} @ {args.apy:.2f}% APY")
            if result.warnings:
                for w in result.warnings:
                    print(f"   ⚠ {w}")
        except RiskPolicyViolation as e:
            print(f"🚫 BLOCKED by Risk Policy: {e}")
            for v in e.result.violations:
                print(f"   ✗ {v}")

    elif args.close:
        result = trader.close_position(args.close, reason=args.reason)
        print(f"✅ Closed {args.close}: PnL ${result['realized_pnl_usd']:+.4f}")

    elif args.rebalance:
        actions = trader.rebalance()
        print(f"Rebalance complete: {len(actions)} action(s)")
        for a in actions:
            print(f"  → {a}")

    elif args.update:
        n = trader.update_prices()
        print(f"✅ Updated {n} position(s)")


if __name__ == "__main__":
    main()
