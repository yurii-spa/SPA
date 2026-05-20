"""
SPA Strategy Agent (M4)

Модель: Gemini Flash (в реальном деплое)
Роль:   Анализирует MARKET_DATA, предлагает аллокацию, публикует STRATEGY_SIGNAL.

Логика (детерминированная v1_passive):
  Стратегия passive = rank протоколь по APY с учётом tier и текущих позиций.
  Рекомендует:
    - TOP T1 протоколы (до 40% капитала каждый)
    - TOP T2 протоколы (до 20% каждый, совокупно до 35%)
    - Закрыть позиции с APY < min_apy threshold

  В M4 логика детерминированная. В M5 будет LLM reasoning.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from agents.base import BaseAgent
from message_bus.bus import MessageBus
from message_bus.topics import Priority, Topic, strategy_signal_payload


# Параметры стратегии v1_passive
MIN_APY_THRESHOLD   = 2.0    # % — ниже этого закрываем позицию
TARGET_CASH_PCT     = 0.15   # держать 15% кэша (min 5%, target 15%)
T1_MAX_SINGLE_PCT   = 0.40   # лимит одного T1 протокола
T2_MAX_SINGLE_PCT   = 0.20   # лимит одного T2 протокола
T2_MAX_TOTAL_PCT    = 0.35   # лимит T2 совокупно
TOTAL_CAPITAL       = 10_000.0


class StrategyAgent(BaseAgent):
    """
    Strategy Agent v1_passive.
    Потребляет MARKET_DATA, публикует STRATEGY_SIGNAL.
    """

    AGENT_ID = "strategy_agent"

    def run(self) -> list[str]:
        """Потребить MARKET_DATA и опубликовать STRATEGY_SIGNAL."""
        self._run_count += 1
        self.log.info("Run #%d — analysing market data", self._run_count)

        msgs = self.consume(Topic.MARKET_DATA, limit=5)
        if not msgs:
            self.log.info("No MARKET_DATA in queue — skipping")
            return []

        # Берём самый свежий snapshot
        latest = msgs[-1]
        for m in msgs:
            self.ack(m.id)

        snapshots = latest.payload.get("snapshots", [])
        if not snapshots:
            self.log.warning("Empty snapshots in MARKET_DATA")
            return []

        recommendations = self._analyse(snapshots)
        reasoning       = self._build_reasoning(snapshots, recommendations)

        payload = strategy_signal_payload(
            recommendations = recommendations,
            reasoning       = reasoning,
            confidence      = 0.85,
        )

        msg_id = self.publish(Topic.STRATEGY_SIGNAL, payload, priority=Priority.HIGH)
        self.log.info(
            "Published STRATEGY_SIGNAL: %d recs, id=%s",
            len(recommendations), msg_id[:8],
        )
        return [msg_id]

    # ── Private ───────────────────────────────────────────────────────────────

    def _analyse(self, snapshots: list[dict]) -> list[dict]:
        """
        Детерминированная стратегия v1_passive:
        1. Отфильтровать невалидные/нулевые APY
        2. Отсортировать по APY descending
        3. Назначить аллокацию с учётом tier-лимитов
        """
        # Фильтрация
        valid = [
            s for s in snapshots
            if (s.get("apy_total") or 0) >= MIN_APY_THRESHOLD
        ]
        valid.sort(key=lambda s: s.get("apy_total", 0), reverse=True)

        recommendations = []
        allocated_t2    = 0.0
        deployable      = TOTAL_CAPITAL * (1 - TARGET_CASH_PCT)  # $8,500

        for snap in valid:
            key  = snap.get("protocol_key", "")
            tier = snap.get("tier", "T2")
            apy  = snap.get("apy_total", 0)

            if tier == "T1":
                max_alloc = TOTAL_CAPITAL * T1_MAX_SINGLE_PCT
            else:
                remaining_t2 = TOTAL_CAPITAL * T2_MAX_TOTAL_PCT - allocated_t2
                if remaining_t2 <= 0:
                    continue
                max_alloc = min(TOTAL_CAPITAL * T2_MAX_SINGLE_PCT, remaining_t2)

            # Простое равновесное распределение: капитал / (число хороших протоколов)
            target_amount = min(deployable / max(len(valid), 1), max_alloc)
            target_amount = round(target_amount / 500) * 500  # округляем до $500

            if target_amount < 500:
                continue

            if tier == "T2":
                allocated_t2 += target_amount

            recommendations.append({
                "protocol_key": key,
                "tier":         tier,
                "action":       "OPEN",
                "amount_usd":   target_amount,
                "apy":          apy,
                "priority":     len(recommendations) + 1,
                "rationale":    f"APY={apy:.2f}%, tier={tier}, within limits",
            })

        return recommendations

    def _build_reasoning(self, snapshots: list[dict], recs: list[dict]) -> str:
        """Построить текстовое обоснование (stub для LLM в M5)."""
        top = sorted(snapshots, key=lambda s: s.get("apy_total", 0), reverse=True)[:3]
        top_str = ", ".join(
            f"{s['protocol_key']} ({s.get('apy_total', 0):.2f}%)" for s in top
        )
        return (
            f"v1_passive strategy: top protocols by APY: {top_str}. "
            f"Proposing {len(recs)} positions within tier concentration limits. "
            f"Cash buffer target: {TARGET_CASH_PCT:.0%}."
        )
