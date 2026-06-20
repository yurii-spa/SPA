"""
Rebalance Optimizer — ADVISORY ONLY (MP-619).

Предлагает ребалансировочные операции для максимизации APY в рамках tier limits.
НЕ выполняет реальных транзакций. Только рекомендации.

Читает позиции из:
  1. data/yield_attribution_tracker.json → latest.contributions
  2. data/adapter_status.json → APY/tier справочник адаптеров

Сохраняет план в data/rebalance_plan.json (ring-buffer 30).

Design constraints
------------------
* Pure stdlib — no external deps (no requests / numpy / pandas / web3 / LLM SDK).
* Advisory only — never touches allocator / risk / execution.
* Atomic writes — tmp + os.replace on every JSON update.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* exit(0) always from CLI.

Tier limits (зеркало RiskPolicy v1.0):
  T2 total cap : ≤ 50% портфеля
  T3 total cap : ≤ 10% портфеля

Priority thresholds для RebalanceMove:
  HIGH   : apy_gain > 1.5%
  MEDIUM : 0.5% ≤ apy_gain ≤ 1.5%
  LOW    : apy_gain < 0.5%

Recommendation:
  REBALANCE : есть HIGH priority ходы
  MONITOR   : есть MEDIUM priority ходы (нет HIGH)
  HOLD      : только LOW priority или нет ходов

CLI
---
    python3 -m spa_core.analytics.rebalance_optimizer --check
    python3 -m spa_core.analytics.rebalance_optimizer --run
    python3 -m spa_core.analytics.rebalance_optimizer --run --data-dir /path/to/data
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Project root & paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

OUTPUT_FILENAME = "rebalance_plan.json"
RING_BUFFER_MAX = 30

# Top-level keys in adapter_status.json that are NOT adapter entries
_SKIP_KEYS = frozenset({
    "generated_at", "schema_version", "execution_mode", "live_apy_enabled",
    "mev_protection", "adapters", "morpho_steakhouse", "base_gas_monitor",
})

DISCLAIMER = "Advisory only. No transactions executed."

# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any) -> float:
    """Coerce value to finite float; return 0.0 on any failure."""
    if isinstance(val, bool):
        return 0.0
    try:
        f = float(val)
        return f if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _extract_apy(data: Dict[str, Any]) -> float:
    """Extract APY % from an adapter data dict.

    Tries keys in order: ``apy_pct`` → ``apy`` → first value from
    ``mock_apy[chain][asset]``.  Returns 0.0 when nothing usable found.
    """
    for key in ("apy_pct", "apy"):
        val = data.get(key)
        if not isinstance(val, bool) and isinstance(val, (int, float)):
            f = float(val)
            if math.isfinite(f) and f > 0:
                return f
    mock = data.get("mock_apy")
    if isinstance(mock, dict):
        for chain_data in mock.values():
            if isinstance(chain_data, dict):
                for apy_val in chain_data.values():
                    if not isinstance(apy_val, bool) and isinstance(apy_val, (int, float)):
                        f = float(apy_val)
                        if math.isfinite(f) and f > 0:
                            return f
    return 0.0


def _classify_priority(apy_gain: float) -> str:
    """Classify a move priority by APY gain.

    HIGH   : apy_gain > 1.5%
    MEDIUM : 0.5% ≤ apy_gain ≤ 1.5%
    LOW    : apy_gain < 0.5%
    """
    if apy_gain > 1.5:
        return "HIGH"
    if apy_gain >= 0.5:
        return "MEDIUM"
    return "LOW"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class RebalanceMove:
    """A single advisory rebalance operation.

    Attributes
    ----------
    from_adapter    : Source adapter key.
    to_adapter      : Destination adapter key.
    amount_usd      : Capital to move in USD.
    from_apy        : Current source APY (%).
    to_apy          : Target destination APY (%).
    apy_gain_pct    : to_apy - from_apy (%).
    annual_gain_usd : amount_usd * apy_gain_pct / 100 — estimated annual gain.
    priority        : "HIGH" / "MEDIUM" / "LOW".
    reason          : Human-readable rationale (e.g. "Higher APY: 5.2% vs 4.1%").
    """

    from_adapter: str
    to_adapter: str
    amount_usd: float
    from_apy: float
    to_apy: float
    apy_gain_pct: float
    annual_gain_usd: float
    priority: str
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


@dataclass
class RebalancePlan:
    """Full advisory rebalance plan for the portfolio.

    Attributes
    ----------
    generated_at            : ISO-8601 UTC timestamp.
    current_portfolio_apy   : Weighted APY before any moves (%).
    optimized_portfolio_apy : Estimated APY after all proposed moves (%).
    apy_improvement         : optimized - current (%).
    annual_improvement_usd  : apy_improvement * total_capital / 100 ($).
    moves                   : All suggested moves (sorted desc by apy_gain).
    high_priority_moves     : Subset of moves with priority == "HIGH".
    total_moves             : len(moves).
    tier_limits_respected   : Whether current positions satisfy T2≤50%, T3≤10%.
    min_move_usd            : Minimum move threshold used ($).
    recommendation          : "REBALANCE" / "MONITOR" / "HOLD".
    summary                 : Human-readable one-liner.
    disclaimer              : "Advisory only. No transactions executed."
    """

    generated_at: str
    current_portfolio_apy: float
    optimized_portfolio_apy: float
    apy_improvement: float
    annual_improvement_usd: float
    moves: List[RebalanceMove] = field(default_factory=list)
    high_priority_moves: List[RebalanceMove] = field(default_factory=list)
    total_moves: int = 0
    tier_limits_respected: bool = True
    min_move_usd: float = 500.0
    recommendation: str = "HOLD"
    summary: str = ""
    disclaimer: str = DISCLAIMER

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


# ---------------------------------------------------------------------------
# RebalanceOptimizer
# ---------------------------------------------------------------------------


class RebalanceOptimizer:
    """Advisory rebalance optimizer for the SPA paper portfolio.

    Analyses current positions and available adapters to suggest APY-maximising
    rebalance moves that respect tier limits.

    Parameters
    ----------
    data_path : str or Path, optional
        Directory containing data files.  Defaults to repo ``data/``.
    """

    MIN_MOVE_USD: float = 500.0   # Minimum move size to generate a suggestion
    T2_CAP: float = 0.50          # T2 total cap (50%)
    T3_CAP: float = 0.10          # T3 total cap (10%)

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            self.data_dir = _DEFAULT_DATA_DIR
        else:
            self.data_dir = Path(data_path)

    # -----------------------------------------------------------------------
    # Data loading
    # -----------------------------------------------------------------------

    def load_current_positions(self) -> Tuple[float, List[Dict[str, Any]]]:
        """Load positions from yield_attribution_tracker.json.

        Reads ``latest.contributions`` and returns
        ``(total_allocated_usd, contributions_list)``.

        Each contribution dict is expected to have at least:
            adapter_id, allocated_usd, apy_pct, tier.

        Returns
        -------
        tuple[float, list[dict]]
            Falls back to ``(100_000.0, [])`` when file is missing,
            unreadable, or contains no valid positions.
        """
        path = self.data_dir / "yield_attribution_tracker.json"
        fallback: Tuple[float, List[Dict[str, Any]]] = (100_000.0, [])

        if not path.exists():
            return fallback
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return fallback
        if not isinstance(raw, dict):
            return fallback

        latest = raw.get("latest")
        if not isinstance(latest, dict):
            return fallback

        total = _safe_float(latest.get("total_allocated_usd", 0))
        if total <= 0:
            total = 100_000.0

        contributions = latest.get("contributions", [])
        if not isinstance(contributions, list):
            contributions = []

        # Keep only dicts with positive allocation
        valid: List[Dict[str, Any]] = []
        for c in contributions:
            if not isinstance(c, dict):
                continue
            if _safe_float(c.get("allocated_usd", 0)) > 0:
                valid.append(c)

        return (total, valid)

    def load_adapter_registry(self) -> Dict[str, Dict[str, Any]]:
        """Load adapter APY/tier info from adapter_status.json.

        Returns
        -------
        dict
            ``{adapter_key: {apy_pct, tier, is_eligible, risk_score}}``.
            Returns ``{}`` when file is missing, unreadable, or contains no
            adapters with a valid tier and positive APY.
        """
        path = self.data_dir / "adapter_status.json"
        if not path.exists():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}

        result: Dict[str, Dict[str, Any]] = {}

        def _process_entry(key: str, val: Dict[str, Any]) -> None:
            tier = val.get("tier")
            if not isinstance(tier, str) or not tier or tier == "unknown":
                return
            apy = _extract_apy(val)
            if apy <= 0:
                return
            risk_score = _safe_float(val.get("risk_score", 0.5))
            is_eligible_raw = val.get("is_eligible")
            # Default to True when key absent; False only when explicitly False
            is_eligible = (is_eligible_raw is not False) if isinstance(is_eligible_raw, bool) else True
            result[key] = {
                "apy_pct": round(apy, 4),
                "tier": tier,
                "is_eligible": is_eligible,
                "risk_score": risk_score,
            }

        # Top-level protocol entries
        for key, val in raw.items():
            if key in _SKIP_KEYS:
                continue
            if not isinstance(val, dict):
                continue
            if "tier" not in val:
                continue
            _process_entry(key, val)

        # "adapters" array
        adapters_list = raw.get("adapters")
        if isinstance(adapters_list, list):
            for item in adapters_list:
                if not isinstance(item, dict):
                    continue
                protocol_key = (
                    item.get("protocol_key")
                    or item.get("adapter_id")
                    or item.get("adapter_key")
                )
                if not protocol_key or not isinstance(protocol_key, str):
                    continue
                normalized = protocol_key.replace("-", "_")
                if normalized not in result:
                    _process_entry(normalized, item)

        return result

    # -----------------------------------------------------------------------
    # Core logic
    # -----------------------------------------------------------------------

    def check_tier_limits(
        self, positions: List[Dict[str, Any]], total_usd: float
    ) -> bool:
        """Check T2 ≤ 50% and T3 ≤ 10% constraints.

        Parameters
        ----------
        positions : list of dicts
            Each dict must have ``allocated_usd`` (float) and ``tier`` (str).
        total_usd : float
            Total portfolio capital; returns True when ≤ 0 (no constraint check).

        Returns
        -------
        bool
            True when both tier caps are satisfied.
        """
        if total_usd <= 0:
            return True

        t2_total = 0.0
        t3_total = 0.0

        for p in positions:
            usd = _safe_float(p.get("allocated_usd", 0))
            tier = p.get("tier", "")
            if not isinstance(tier, str):
                tier = ""
            tier_upper = tier.upper()
            if tier_upper == "T2":
                t2_total += usd
            elif tier_upper in ("T3", "T3-SPEC"):
                t3_total += usd

        t2_ratio = t2_total / total_usd
        t3_ratio = t3_total / total_usd

        return t2_ratio <= self.T2_CAP and t3_ratio <= self.T3_CAP

    def _simulate_positions_after_move(
        self,
        current_positions: List[Dict[str, Any]],
        from_adapter: str,
        to_adapter: str,
        amount_usd: float,
        registry: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Return hypothetical positions list after applying one move.

        Does NOT mutate ``current_positions``.
        """
        # Copy with minimal fields needed for tier check
        simulated: List[Dict[str, Any]] = []
        for p in current_positions:
            adapter_key = p.get("adapter_id") or p.get("adapter_key") or ""
            tier = p.get("tier") or registry.get(adapter_key, {}).get("tier", "unknown")
            simulated.append({
                "adapter_id": adapter_key,
                "allocated_usd": _safe_float(p.get("allocated_usd", 0)),
                "tier": tier,
            })

        # Subtract from source
        for p in simulated:
            if p["adapter_id"] == from_adapter:
                p["allocated_usd"] = max(0.0, p["allocated_usd"] - amount_usd)

        # Add to destination
        to_found = False
        for p in simulated:
            if p["adapter_id"] == to_adapter:
                p["allocated_usd"] += amount_usd
                to_found = True

        if not to_found:
            to_tier = registry.get(to_adapter, {}).get("tier", "unknown")
            simulated.append({
                "adapter_id": to_adapter,
                "allocated_usd": amount_usd,
                "tier": to_tier,
            })

        # Remove zero-allocation entries
        return [p for p in simulated if p["allocated_usd"] > 0]

    def find_upgrade_opportunities(
        self,
        current_positions: List[Dict[str, Any]],
        registry: Dict[str, Dict[str, Any]],
        total_usd: float,
    ) -> List[RebalanceMove]:
        """Find APY upgrade moves respecting tier limits.

        For each current position finds the single best eligible adapter with
        higher APY (apy_gain ≥ 0.1%) that, after the hypothetical move, still
        satisfies T2/T3 caps.  Only positions with ``allocated_usd ≥ MIN_MOVE_USD``
        generate a suggestion.

        Parameters
        ----------
        current_positions : list[dict]
            Contributions from yield_attribution_tracker.json.
        registry : dict
            Adapter registry from :meth:`load_adapter_registry`.
        total_usd : float
            Total portfolio capital.

        Returns
        -------
        list[RebalanceMove]
            Sorted descending by apy_gain_pct.
        """
        moves: List[RebalanceMove] = []

        if not current_positions or not registry:
            return moves

        for position in current_positions:
            from_adapter = (
                position.get("adapter_id") or position.get("adapter_key") or ""
            )
            if not from_adapter:
                continue

            amount_usd = _safe_float(position.get("allocated_usd", 0))
            if amount_usd < self.MIN_MOVE_USD:
                continue

            # APY from contribution data; fallback to registry
            from_apy = _safe_float(position.get("apy_pct", 0))
            if from_apy <= 0:
                from_apy = registry.get(from_adapter, {}).get("apy_pct", 0.0)

            # Find the best eligible upgrade target
            best_gain = 0.0
            best_candidate: Optional[str] = None
            best_candidate_apy = 0.0

            for candidate_key, candidate_info in registry.items():
                if candidate_key == from_adapter:
                    continue
                if not candidate_info.get("is_eligible", True):
                    continue

                candidate_apy = _safe_float(candidate_info.get("apy_pct", 0))
                apy_gain = candidate_apy - from_apy

                # Threshold: skip gains below 0.1%
                if apy_gain < 0.1:
                    continue

                # Tier limit guard: simulate the move and verify caps
                simulated = self._simulate_positions_after_move(
                    current_positions,
                    from_adapter,
                    candidate_key,
                    amount_usd,
                    registry,
                )
                if not self.check_tier_limits(simulated, total_usd):
                    continue

                if apy_gain > best_gain:
                    best_gain = apy_gain
                    best_candidate = candidate_key
                    best_candidate_apy = candidate_apy

            if best_candidate is None:
                continue

            apy_gain_pct = round(best_gain, 4)
            annual_gain_usd = round(amount_usd * apy_gain_pct / 100.0, 2)
            priority = _classify_priority(apy_gain_pct)
            reason = f"Higher APY: {best_candidate_apy:.1f}% vs {from_apy:.1f}%"

            moves.append(
                RebalanceMove(
                    from_adapter=from_adapter,
                    to_adapter=best_candidate,
                    amount_usd=round(amount_usd, 2),
                    from_apy=round(from_apy, 4),
                    to_apy=round(best_candidate_apy, 4),
                    apy_gain_pct=apy_gain_pct,
                    annual_gain_usd=annual_gain_usd,
                    priority=priority,
                    reason=reason,
                )
            )

        # Sort descending by apy_gain_pct
        moves.sort(key=lambda m: m.apy_gain_pct, reverse=True)
        return moves

    def estimate_optimized_apy(
        self,
        moves: List[RebalanceMove],
        current_apy: float,
        total_usd: float = 100_000.0,
    ) -> float:
        """Estimate portfolio APY after applying all moves.

        Uses simplified formula:
            optimized_apy = current_apy + Σ(apy_gain_pct_i * amount_usd_i / total_usd)

        Parameters
        ----------
        moves       : Proposed move list (may be empty).
        current_apy : Weighted portfolio APY before moves (%).
        total_usd   : Total portfolio capital (%).

        Returns
        -------
        float
            Estimated APY after rebalancing.  Returns current_apy unchanged
            when moves is empty or total_usd ≤ 0.
        """
        if not moves or total_usd <= 0:
            return round(current_apy, 4)

        delta = sum(
            m.apy_gain_pct * m.amount_usd / total_usd for m in moves
        )
        return round(current_apy + delta, 4)

    def generate_plan(self) -> RebalancePlan:
        """Generate a complete advisory rebalance plan.

        Orchestrates: load positions → load registry → find upgrades →
        estimate improvement → build :class:`RebalancePlan`.

        Returns
        -------
        RebalancePlan
            With ``recommendation="HOLD"`` and empty moves when no positions
            are found.
        """
        now = datetime.now(timezone.utc).isoformat()

        total_usd, contributions = self.load_current_positions()
        registry = self.load_adapter_registry()

        # Weighted current APY
        current_apy = 0.0
        if total_usd > 0 and contributions:
            weighted_sum = sum(
                _safe_float(c.get("apy_pct", 0)) * _safe_float(c.get("allocated_usd", 0))
                for c in contributions
            )
            current_apy = weighted_sum / total_usd

        if not contributions:
            return RebalancePlan(
                generated_at=now,
                current_portfolio_apy=round(current_apy, 4),
                optimized_portfolio_apy=round(current_apy, 4),
                apy_improvement=0.0,
                annual_improvement_usd=0.0,
                moves=[],
                high_priority_moves=[],
                total_moves=0,
                tier_limits_respected=True,
                min_move_usd=self.MIN_MOVE_USD,
                recommendation="HOLD",
                summary="No positions found. Nothing to rebalance.",
                disclaimer=DISCLAIMER,
            )

        moves = self.find_upgrade_opportunities(contributions, registry, total_usd)

        optimized_apy = self.estimate_optimized_apy(moves, current_apy, total_usd)
        apy_improvement = round(optimized_apy - current_apy, 4)
        annual_improvement_usd = round(total_usd * apy_improvement / 100.0, 2)

        high_priority = [m for m in moves if m.priority == "HIGH"]
        medium_priority = [m for m in moves if m.priority == "MEDIUM"]

        # Determine recommendation
        if high_priority:
            recommendation = "REBALANCE"
        elif medium_priority:
            recommendation = "MONITOR"
        else:
            recommendation = "HOLD"

        # Tier limits check on current (pre-move) positions
        tier_limits_respected = self.check_tier_limits(contributions, total_usd)

        # Build summary
        n = len(moves)
        if n == 0:
            summary = f"No moves suggested. Portfolio APY: {current_apy:.2f}%"
        else:
            summary = (
                f"{n} move{'s' if n != 1 else ''} suggested, "
                f"+{apy_improvement:.2f}% APY → "
                f"${annual_improvement_usd:,.0f}/yr gain"
            )

        return RebalancePlan(
            generated_at=now,
            current_portfolio_apy=round(current_apy, 4),
            optimized_portfolio_apy=round(optimized_apy, 4),
            apy_improvement=apy_improvement,
            annual_improvement_usd=annual_improvement_usd,
            moves=moves,
            high_priority_moves=high_priority,
            total_moves=n,
            tier_limits_respected=tier_limits_respected,
            min_move_usd=self.MIN_MOVE_USD,
            recommendation=recommendation,
            summary=summary,
            disclaimer=DISCLAIMER,
        )

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def save_plan(self, plan: Optional[RebalancePlan] = None) -> str:
        """Generate (if needed) and atomically save the plan.

        Maintains a ring-buffer of the last :data:`RING_BUFFER_MAX` (30)
        snapshots inside ``data/rebalance_plan.json``.

        Parameters
        ----------
        plan : RebalancePlan, optional
            Pre-generated plan.  When ``None``, calls :meth:`generate_plan`.

        Returns
        -------
        str
            Absolute path of the written file.
        """
        if plan is None:
            plan = self.generate_plan()

        self.data_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.data_dir / OUTPUT_FILENAME

        # Load existing snapshots for ring-buffer
        snapshots: List[Dict[str, Any]] = []
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    old = existing.get("snapshots", [])
                    if isinstance(old, list):
                        snapshots = [s for s in old if isinstance(s, dict)]
            except (ValueError, OSError):
                pass

        plan_dict = self.to_dict(plan)
        snapshots.append(plan_dict)
        snapshots = snapshots[-RING_BUFFER_MAX:]

        out: Dict[str, Any] = {
            "schema_version": "1.0",
            "source": "rebalance_optimizer",
            "last_updated": plan_dict.get("generated_at", ""),
            "latest": plan_dict,
            "snapshots": snapshots,
        }

        # Atomic write: tmp → os.replace
        atomic_save(out, str(out_path))
        return str(out_path)

    # -----------------------------------------------------------------------
    # Output helpers
    # -----------------------------------------------------------------------

    def format_telegram_message(self, plan: Optional[RebalancePlan] = None) -> str:
        """Format a Telegram-ready summary (≤1500 chars).

        Parameters
        ----------
        plan : RebalancePlan, optional
            Pre-generated plan.  When ``None``, calls :meth:`generate_plan`.
        """
        if plan is None:
            plan = self.generate_plan()

        lines: List[str] = [
            f"🔄 Rebalance Plan — {plan.recommendation}",
            (
                f"Current APY: {plan.current_portfolio_apy:.2f}% → "
                f"Optimized: {plan.optimized_portfolio_apy:.2f}% "
                f"(+{plan.apy_improvement:.2f}%)"
            ),
            f"Annual gain: +${plan.annual_improvement_usd:,.0f}",
        ]

        if plan.moves:
            lines.append("Moves:")
            for i, m in enumerate(plan.moves[:5], 1):
                amount_str = (
                    f"${m.amount_usd / 1000:.0f}K"
                    if m.amount_usd >= 1000
                    else f"${m.amount_usd:.0f}"
                )
                check = " ✅" if m.priority == "HIGH" else ""
                lines.append(
                    f"  {i}. {m.from_adapter} → {m.to_adapter}: "
                    f"{amount_str}, +{m.apy_gain_pct:.1f}% ({m.priority}){check}"
                )
        else:
            lines.append("No moves suggested.")

        lines.append("⚠️ Advisory only. No transactions executed.")

        msg = "\n".join(lines)
        return msg[:1500]

    def to_dict(self, plan: Optional[RebalancePlan] = None) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the plan.

        Parameters
        ----------
        plan : RebalancePlan, optional
            Pre-generated plan.  When ``None``, calls :meth:`generate_plan`.
        """
        if plan is None:
            plan = self.generate_plan()
        return asdict(plan)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SPA Rebalance Optimizer (MP-619) — advisory APY upgrade suggestions "
            "with T2/T3 tier limit enforcement."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print plan without writing (default).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute and atomically save to data/rebalance_plan.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help="Data directory path.",
    )
    args = parser.parse_args(argv)

    optimizer = RebalanceOptimizer(data_path=args.data_dir)
    plan = optimizer.generate_plan()

    print(f"Generated:       {plan.generated_at}")
    print(f"Recommendation:  {plan.recommendation}")
    print(f"Current APY:     {plan.current_portfolio_apy:.4f}%")
    print(f"Optimized APY:   {plan.optimized_portfolio_apy:.4f}%")
    print(f"APY improvement: +{plan.apy_improvement:.4f}%")
    print(f"Annual gain:     ${plan.annual_improvement_usd:,.2f}")
    print(f"Total moves:     {plan.total_moves}")
    print(f"High priority:   {len(plan.high_priority_moves)}")
    print(f"Tier limits OK:  {plan.tier_limits_respected}")
    print(f"Summary:         {plan.summary}")
    print(f"Disclaimer:      {plan.disclaimer}")

    if plan.moves:
        print("\nProposed moves:")
        for i, m in enumerate(plan.moves, 1):
            print(
                f"  {i:2d}. [{m.priority:<6s}] {m.from_adapter:<25s} → "
                f"{m.to_adapter:<25s}  "
                f"${m.amount_usd:>10,.0f}  "
                f"+{m.apy_gain_pct:.2f}%  "
                f"~${m.annual_gain_usd:,.0f}/yr"
            )
    else:
        print("\nNo upgrade moves found.")

    if args.run:
        saved_path = optimizer.save_plan(plan)
        print(f"\nSaved → {saved_path}")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
