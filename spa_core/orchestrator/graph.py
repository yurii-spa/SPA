"""
SPA Orchestrator — Graph (M4)

SPAOrchestrator — последовательный граф агентов.
LangGraph-compatible дизайн: каждый node — функция (state) -> state.

Граф:
    data_node → monitoring_node → strategy_node → ceo_node → execution_node

Условие блокировки:
    Если monitoring_node → is_blocked=True → strategy_node и ceo_node пропускают
    открытие позиций, но CEO публикует HOLD decisions.

Risk Policy:
    НЕ в оркестраторе. Проверяется в PaperTrader.open_position() автоматически.
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.ceo_agent import CEOAgent
from agents.data_agent import DataAgent
from agents.monitoring_agent import MonitoringAgent
from agents.strategy_agent import StrategyAgent
from database.init_db import get_connection, get_db_path
from message_bus.bus import MessageBus
from message_bus.topics import Topic
from orchestrator.state import SPAState, initial_state
from paper_trading.engine import PaperTrader, RiskPolicyViolation

log = logging.getLogger("spa.orchestrator")


class SPAOrchestrator:
    """
    Оркестратор SPA (M4).

    Запускает агентов в правильном порядке, передаёт state между нодами.
    """

    def __init__(self, db_path: Path | None = None):
        self.db_path = db_path or get_db_path()

        # Шина сообщений
        self.bus = MessageBus(db_path=self.db_path)

        # Агенты
        self.data_agent       = DataAgent(self.bus, self.db_path)
        self.monitoring_agent = MonitoringAgent(self.bus, self.db_path)
        self.strategy_agent   = StrategyAgent(self.bus, self.db_path)
        self.ceo_agent        = CEOAgent(self.bus, self.db_path)

        # Paper Trader для исполнения
        self.trader = PaperTrader(db_path=self.db_path)

        self._iteration = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def run_once(self) -> SPAState:
        """Выполнить одну полную итерацию графа. Возвращает финальный state."""
        self._iteration += 1
        state = initial_state(iteration=self._iteration)

        log.info("═══ Iteration #%d start ═══", self._iteration)

        try:
            state = self._data_node(state)
            state = self._monitoring_node(state)
            state = self._strategy_node(state)
            state = self._ceo_node(state)
            state = self._execution_node(state)
        except Exception as exc:
            log.error("Orchestrator error in iteration #%d: %s", self._iteration, exc, exc_info=True)
            state["errors"].append(str(exc))

        # Dead-letter recovery
        requeued = self.bus.requeue_stale()
        if requeued:
            log.warning("Requeued %d stale messages", requeued)

        log.info(
            "═══ Iteration #%d done | fetch_ok=%s | blocked=%s | "
            "signals=%d | decisions=%d | executions=%d | errors=%d ═══",
            self._iteration,
            state.get("fetch_ok"),
            state.get("is_blocked"),
            len(state.get("signals", [])),
            len(state.get("decisions", [])),
            len(state.get("execution_results", [])),
            len(state.get("errors", [])),
        )
        return state

    def print_state(self, state: SPAState) -> None:
        """Вывести результат итерации в консоль."""
        print(f"\n{'═'*65}")
        print(f"  SPA Iteration #{state['iteration']} — {state['timestamp'][:19]} UTC")
        print(f"{'═'*65}")

        # Market data
        snaps = state.get("snapshots", [])
        print(f"\n  📊 Market Data: {len(snaps)} protocols | fetch_ok={state.get('fetch_ok')}")
        for s in sorted(snaps, key=lambda x: x.get("apy_total", 0), reverse=True)[:5]:
            print(f"     {s.get('protocol_key','?'):<35} {s.get('apy_total',0):>6.2f}%")

        # Health
        health = state.get("health", {})
        summary = health.get("summary", {})
        blocked = state.get("is_blocked", False)
        block_icon = "🚨" if blocked else "✅"
        print(f"\n  {block_icon} Health: {summary.get('overall_status','?')} | "
              f"🚨 {summary.get('critical',0)}  ⚠️  {summary.get('warnings',0)}")

        # Decisions
        decisions = state.get("decisions", [])
        print(f"\n  🎯 Decisions: {len(decisions)}")
        for d in decisions:
            icon = "✅" if d.get("approved") else "❌"
            print(f"     {icon} {d.get('action','?')} {d.get('protocol_key','?')} "
                  f"${d.get('amount_usd',0):,.0f}")

        # Executions
        execs = state.get("execution_results", [])
        print(f"\n  ⚡ Executions: {len(execs)}")
        for e in execs:
            icon = "✅" if e.get("approved") else "❌"
            reason = e.get("rejection_reason") or ""
            print(f"     {icon} {e.get('action','?')} {e.get('protocol_key','?')} "
                  f"${e.get('amount_usd',0):,.0f}"
                  + (f" — {reason}" if reason else ""))

        # Errors
        errors = state.get("errors", [])
        if errors:
            print(f"\n  ⚠️  Errors: {len(errors)}")
            for e in errors:
                print(f"     {e}")

        print(f"\n{'═'*65}\n")

    # ── Nodes ─────────────────────────────────────────────────────────────────

    def _data_node(self, state: SPAState) -> SPAState:
        """Node 1: DataAgent → получить рыночные данные."""
        log.info("[data_node] start")
        try:
            msg_ids = self.data_agent.run()
            state["published_ids"] = state.get("published_ids", []) + msg_ids

            # Читаем данные напрямую из последнего MARKET_DATA сообщения
            # (без consume, чтобы не "съедать" для Strategy Agent)
            from database.init_db import get_connection
            with get_connection(self.db_path) as conn:
                rows = conn.execute("""
                    SELECT s.*, p.tier
                    FROM apy_snapshots s
                    JOIN protocols p ON s.protocol_key = p.key
                    WHERE s.id IN (
                        SELECT MAX(id) FROM apy_snapshots GROUP BY protocol_key
                    )
                    ORDER BY s.apy_total DESC
                """).fetchall()
            state["snapshots"] = [dict(r) for r in rows]
            state["fetch_ok"]  = len(state["snapshots"]) > 0
        except Exception as e:
            log.error("[data_node] error: %s", e)
            state["errors"].append(f"data_node: {e}")
            state["fetch_ok"] = False
        return state

    def _monitoring_node(self, state: SPAState) -> SPAState:
        """Node 2: MonitoringAgent → проверить здоровье."""
        log.info("[monitoring_node] start")
        try:
            msg_ids = self.monitoring_agent.run()
            state["published_ids"] = state.get("published_ids", []) + msg_ids

            # Читаем результат из health check напрямую
            from monitoring.health_check import HealthCheck
            checker = HealthCheck(db_path=self.db_path)
            result  = checker.run()
            state["health"]     = result
            state["alerts"]     = result.get("alerts", [])
            state["is_blocked"] = result["summary"]["overall_status"] == "CRITICAL"
        except Exception as e:
            log.error("[monitoring_node] error: %s", e)
            state["errors"].append(f"monitoring_node: {e}")
        return state

    def _strategy_node(self, state: SPAState) -> SPAState:
        """Node 3: StrategyAgent → предложить аллокацию."""
        log.info("[strategy_node] start (blocked=%s)", state.get("is_blocked"))
        try:
            msg_ids = self.strategy_agent.run()
            state["published_ids"] = state.get("published_ids", []) + msg_ids

            # Читаем рекомендации из последнего опубликованного STRATEGY_SIGNAL
            # StrategyAgent уже consume-нул MARKET_DATA
            if msg_ids:
                # Данные из Strategy Agent через поле bus stats (не consume!)
                # Просто используем его внутреннюю логику для state
                from agents.strategy_agent import StrategyAgent as SA, MIN_APY_THRESHOLD
                snaps = state.get("snapshots", [])
                sa_temp = SA(self.bus, self.db_path)
                recs = sa_temp._analyse(snaps)
                state["signals"]   = recs
                state["reasoning"] = sa_temp._build_reasoning(snaps, recs)
        except Exception as e:
            log.error("[strategy_node] error: %s", e)
            state["errors"].append(f"strategy_node: {e}")
        return state

    def _ceo_node(self, state: SPAState) -> SPAState:
        """Node 4: CEOAgent → принять решение."""
        log.info("[ceo_node] start")
        try:
            msg_ids = self.ceo_agent.run()
            state["published_ids"] = state.get("published_ids", []) + msg_ids

            # Берём decisions из signals (CEO уже опубликовал в шину)
            is_blocked = state.get("is_blocked", False)
            decisions  = []
            for rec in state.get("signals", []):
                if is_blocked:
                    decisions.append({**rec, "action": "HOLD", "approved": False,
                                      "rejection_reason": "Health CRITICAL"})
                else:
                    decisions.append({**rec, "approved": True})
            state["decisions"] = decisions
        except Exception as e:
            log.error("[ceo_node] error: %s", e)
            state["errors"].append(f"ceo_node: {e}")
        return state

    def _execution_node(self, state: SPAState) -> SPAState:
        """Node 5: PaperTrader → исполнить решения CEO."""
        log.info("[execution_node] start")
        results = []

        for decision in state.get("decisions", []):
            if not decision.get("approved", False):
                results.append({
                    "protocol_key":    decision.get("protocol_key"),
                    "action":          decision.get("action", "HOLD"),
                    "approved":        False,
                    "amount_usd":      0,
                    "rejection_reason": decision.get("rejection_reason", "Not approved by CEO"),
                })
                continue

            key    = decision.get("protocol_key", "")
            action = decision.get("action", "OPEN")
            amount = decision.get("amount_usd", 0)
            apy    = decision.get("apy", 0)

            try:
                if action == "OPEN":
                    # Проверяем не открыта ли уже позиция
                    status = self.trader.get_status()
                    existing = {p["protocol_key"] for p in status.get("positions", [])}
                    if key in existing:
                        results.append({
                            "protocol_key":    key, "action": action,
                            "approved":        False, "amount_usd": amount,
                            "rejection_reason": "Position already open",
                        })
                        continue

                    # open_position returns RiskCheckResult (approved=True here)
                    self.trader.open_position(
                        protocol_key = key,
                        amount_usd   = amount,
                        current_apy  = apy,
                        tvl_usd      = decision.get("tvl_usd", 100_000_000),
                    )
                    results.append({
                        "protocol_key": key, "action": action,
                        "approved":     True, "amount_usd": amount,
                    })
                    log.info("Opened position: %s $%.0f @ %.2f%%", key, amount, apy)

                elif action == "CLOSE":
                    close_result = self.trader.close_position(key, reason="CEO decision")
                    pnl_usd = close_result.get("realized_pnl_usd", 0.0)
                    results.append({
                        "protocol_key": key, "action": action,
                        "approved":     True, "pnl_usd": pnl_usd,
                        "amount_usd":   close_result.get("total_amount_usd", 0.0),
                    })
                    log.info("Closed position: %s PnL=$%.2f", key, pnl_usd)

                else:  # HOLD
                    results.append({
                        "protocol_key": key, "action": "HOLD",
                        "approved":     False,
                        "rejection_reason": "HOLD decision",
                    })

            except RiskPolicyViolation as rpv:
                log.warning("Risk Policy blocked %s: %s", key, rpv)
                results.append({
                    "protocol_key":    key, "action": action,
                    "approved":        False, "amount_usd": amount,
                    "rejection_reason": f"Risk Policy: {rpv}",
                })
            except Exception as e:
                log.error("Execution error for %s: %s", key, e, exc_info=True)
                results.append({
                    "protocol_key":    key, "action": action,
                    "approved":        False,
                    "rejection_reason": f"Error: {e}",
                })

        # Публикуем EXECUTION_RESULT
        from message_bus.topics import execution_result_payload
        for r in results:
            self.bus.publish(
                Topic.EXECUTION_RESULT,
                "execution_node",
                execution_result_payload(**{
                    k: r.get(k) for k in
                    ["protocol_key","action","approved","amount_usd","pnl_usd","rejection_reason","trade_id"]
                    if k in r
                }),
            )

        state["execution_results"] = results
        return state
