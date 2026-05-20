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

import json
import logging
import math
import argparse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from database.init_db import get_connection, get_db_path
from risk.policy import RiskPolicy, RiskConfig, Position, PortfolioState, RiskCheckResult

log = logging.getLogger(__name__)

# ─── Константы ────────────────────────────────────────────────────────────────

STRATEGY_ID = "paper-v1"
INITIAL_CAPITAL = 100_000.0          # виртуальный стартовый капитал ($100K paper trading)
MIN_PAPER_WEEKS = 8                  # минимум paper trading перед live
SHARPE_RISK_FREE_RATE = 0.05         # 5% годовых безрисковая ставка (proxy)


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

    def __init__(self, db_path: Path = None, config: RiskConfig = None):
        self.db_path = db_path or get_db_path()
        self.policy = RiskPolicy(config=config)
        self._ensure_strategy_state()

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
            """, (trade_id, STRATEGY_ID, ts, protocol_key, proto["asset"],
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

        avg_days = total_pnl / (total_amount * 0.0001 + 1)  # approx
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
                SELECT s.protocol_key, s.apy_total, s.tvl_usd, p.tier
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

            if key in open_protocols:
                continue  # уже инвестировали

            # Обновить state для корректного расчёта лимитов
            state = self._load_portfolio_state()
            if state.cash_usd < min_cash_threshold:
                break  # кэш исчерпан

            amount = self.policy.max_safe_position_size(state, key, tier)
            if amount < 10.0:  # минимальная позиция $10
                log.debug(f"auto_allocate: {key} max_safe_size=${amount:.2f} too small, skip")
                continue

            try:
                result = self.open_position(key, amount, apy, tvl)
                actions.append({
                    "action":     "OPEN",
                    "protocol":   key,
                    "amount_usd": round(amount, 2),
                    "apy":        round(apy, 4),
                    "tier":       tier,
                    "approved":   result.approved,
                    "warnings":   result.warnings,
                })
                open_protocols.add(key)
                log.info(
                    f"auto_allocate: opened {key} "
                    f"${amount:.2f} @ APY {apy:.2f}%"
                )
            except RiskPolicyViolation as exc:
                log.warning(f"auto_allocate: {key} blocked by risk policy: {exc}")
                actions.append({
                    "action":   "BLOCKED",
                    "protocol": key,
                    "reason":   str(exc),
                })
            except Exception as exc:
                log.error(f"auto_allocate: unexpected error for {key}: {exc}", exc_info=True)
                actions.append({
                    "action":   "ERROR",
                    "protocol": key,
                    "reason":   str(exc),
                })

        if not actions:
            actions.append({"action": "NO_OP", "reason": "no_suitable_protocol"})

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
            """, (STRATEGY_ID,)).fetchall()

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

    # ── Внутренние методы ─────────────────────────────────────────────────────

    def _load_portfolio_state(self) -> PortfolioState:
        """Загрузить текущее состояние портфеля из БД."""
        with get_connection(self.db_path) as conn:
            strategy = conn.execute("""
                SELECT total_capital_usd FROM strategy_state
                WHERE strategy_id = ?
                ORDER BY id DESC LIMIT 1
            """, (STRATEGY_ID,)).fetchone()

            total_capital = strategy["total_capital_usd"] if strategy else INITIAL_CAPITAL

            open_trades = conn.execute("""
                SELECT t.trade_id, t.protocol_key, t.amount_usd,
                       t.net_apy_annualized, t.pnl_usd, t.timestamp_open,
                       p.tier, p.asset
                FROM paper_trades t
                JOIN protocols p ON t.protocol_key = p.key
                WHERE t.strategy_id = ? AND t.timestamp_close IS NULL
                ORDER BY t.timestamp_open
            """, (STRATEGY_ID,)).fetchall()

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
            """, (STRATEGY_ID, protocol_key)).fetchall()

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
                (STRATEGY_ID,)
            ).fetchone()
            if not existing:
                conn.execute("""
                    INSERT INTO strategy_state
                        (strategy_id, total_capital_usd, deployed_capital_usd,
                         cash_usd, total_pnl_usd, max_drawdown_pct,
                         sharpe_to_date, trade_count)
                    VALUES (?, ?, 0, ?, 0, 0, 0, 0)
                """, (STRATEGY_ID, INITIAL_CAPITAL, INITIAL_CAPITAL))
                conn.commit()
                log.info(f"Strategy state initialised: {STRATEGY_ID}, capital=${INITIAL_CAPITAL:,.2f}")
            elif existing["total_capital_usd"] != INITIAL_CAPITAL:
                # Капитал изменился — безопасно мигрировать если нет сделок
                trade_count = conn.execute(
                    "SELECT COUNT(*) FROM paper_trades WHERE strategy_id = ?", (STRATEGY_ID,)
                ).fetchone()[0]
                if trade_count == 0:
                    conn.execute("""
                        UPDATE strategy_state SET
                            total_capital_usd = ?,
                            cash_usd = ?,
                            deployed_capital_usd = 0,
                            total_pnl_usd = 0
                        WHERE strategy_id = ?
                    """, (INITIAL_CAPITAL, INITIAL_CAPITAL, STRATEGY_ID))
                    conn.commit()
                    old_cap = existing["total_capital_usd"]
                    log.info(f"Capital migrated: ${old_cap:,.2f} → ${INITIAL_CAPITAL:,.2f}")
                else:
                    log.warning(f"Capital mismatch (${existing['total_capital_usd']} vs ${INITIAL_CAPITAL}) "
                                f"but {trade_count} trades exist — keeping existing capital")

    def _update_strategy_state(self, conn) -> None:
        """Пересчитать и сохранить strategy_state (вызывать внутри транзакции)."""
        state = self._load_portfolio_state()

        # Sharpe proxy: (avg_apy - risk_free) / std_apy
        apys = [p.current_apy for p in state.positions]
        if apys:
            avg_apy = sum(apys) / len(apys)
            std_apy = math.sqrt(sum((a - avg_apy)**2 for a in apys) / len(apys)) if len(apys) > 1 else 1.0
            sharpe = (avg_apy - SHARPE_RISK_FREE_RATE * 100) / max(std_apy, 0.1)
        else:
            sharpe = 0.0

        trade_count = conn.execute(
            "SELECT COUNT(*) FROM paper_trades WHERE strategy_id = ?", (STRATEGY_ID,)
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
            state.deployed_usd,
            state.cash_usd,
            state.total_pnl_usd,
            state.total_drawdown_pct,
            round(sharpe, 4),
            trade_count,
            STRATEGY_ID,
        ))

    def _get_strategy_state(self):
        with get_connection(self.db_path) as conn:
            return conn.execute(
                "SELECT * FROM strategy_state WHERE strategy_id = ?", (STRATEGY_ID,)
            ).fetchone()

    def _get_first_trade_ts(self) -> Optional[datetime]:
        with get_connection(self.db_path) as conn:
            row = conn.execute("""
                SELECT MIN(timestamp_open) FROM paper_trades
                WHERE strategy_id = ?
            """, (STRATEGY_ID,)).fetchone()
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
