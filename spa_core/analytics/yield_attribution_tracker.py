"""Yield Attribution Tracker (MP-600).

Отслеживает вклад каждого адаптера в общий доход портфеля.
Attribution analysis — разбивка доходности по источникам (adapter_id, chain, tier).

Читает позиции из:
  1. data/paper_positions.json (если существует)
  2. data/current_positions.json (fallback)
  3. Симулированные позиции из adapter_status.json (если оба отсутствуют)

Сохраняет историю атрибуции в data/yield_attribution_tracker.json (ring-buffer 30).

Design constraints
------------------
* Pure stdlib — no external deps (no requests / numpy / pandas / web3 / LLM SDK).
* Advisory only — never touches allocator / risk / execution.
* Atomic writes — tmp + os.replace on every JSON update.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.yield_attribution_tracker --check
    python3 -m spa_core.analytics.yield_attribution_tracker --run
    python3 -m spa_core.analytics.yield_attribution_tracker --run --data-dir /path/to/data
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
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

OUTPUT_FILENAME = "yield_attribution_tracker.json"
RING_BUFFER_MAX = 30
DEFAULT_PORTFOLIO_USD = 100_000.0

# Top-level keys in adapter_status.json that are NOT adapter entries
_SKIP_KEYS = frozenset({
    "generated_at", "schema_version", "execution_mode", "live_apy_enabled",
    "mev_protection", "adapters", "morpho_steakhouse", "base_gas_monitor",
})

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


def _extract_chain(data: Dict[str, Any]) -> str:
    """Extract primary chain name from adapter data dict."""
    for key in ("chain", "network"):
        val = data.get(key)
        if isinstance(val, str) and val:
            return val
    chains = data.get("chains")
    if isinstance(chains, list) and chains:
        return str(chains[0])
    return "unknown"


def _extract_tier(data: Dict[str, Any]) -> str:
    """Extract tier string from adapter data dict."""
    tier = data.get("tier")
    if isinstance(tier, str) and tier:
        return tier
    return "unknown"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AdapterContribution:
    """Yield contribution metrics for a single adapter.

    Attributes
    ----------
    adapter_id       : Protocol / adapter identifier.
    chain            : Blockchain network (e.g. "ethereum").
    tier             : Risk tier ("T1", "T2", …).
    weight_pct       : Adapter allocation as % of total portfolio (0–100).
    allocated_usd    : Capital deployed in USD.
    apy_pct          : Current APY in %.
    daily_yield_usd  : ``allocated_usd × apy_pct / 100 / 365``
    annual_yield_usd : ``allocated_usd × apy_pct / 100``
    contribution_pct : This adapter's daily_yield / total_daily_yield × 100
    """

    adapter_id: str
    chain: str
    tier: str
    weight_pct: float
    allocated_usd: float
    apy_pct: float
    daily_yield_usd: float
    annual_yield_usd: float
    contribution_pct: float

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


@dataclass
class AttributionReport:
    """Full attribution snapshot for the portfolio.

    Attributes
    ----------
    generated_at         : ISO-8601 UTC timestamp.
    total_allocated_usd  : Total deployed capital.
    total_daily_yield_usd: Sum of daily yields across all adapters.
    total_annual_yield_usd: Sum of annual yields.
    effective_apy_pct    : ``total_annual_yield / total_allocated × 100``
    contributions        : Per-adapter contributions, sorted desc by contribution_pct.
    top_contributor      : adapter_id with highest contribution_pct.
    top_by_apy           : adapter_id with highest apy_pct.
    chain_breakdown      : ``{chain: {allocated_usd, annual_yield_usd, weight_pct}}``
    tier_breakdown       : ``{tier: {allocated_usd, annual_yield_usd, weight_pct}}``
    diversification_score: ``1 − HHI``; 0 = concentrated, 1 = fully diversified.
    """

    generated_at: str
    total_allocated_usd: float
    total_daily_yield_usd: float
    total_annual_yield_usd: float
    effective_apy_pct: float
    contributions: List[AdapterContribution] = field(default_factory=list)
    top_contributor: str = ""
    top_by_apy: str = ""
    chain_breakdown: Dict[str, Any] = field(default_factory=dict)
    tier_breakdown: Dict[str, Any] = field(default_factory=dict)
    diversification_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# YieldAttributionTracker
# ---------------------------------------------------------------------------


class YieldAttributionTracker:
    """Per-adapter yield attribution tracker.

    Parameters
    ----------
    data_path : str or Path, optional
        Directory containing ``adapter_status.json``, ``current_positions.json``
        etc., and where ``yield_attribution_tracker.json`` is written.
        Defaults to the repo ``data/`` directory.
    """

    DEFAULT_PORTFOLIO_USD: float = DEFAULT_PORTFOLIO_USD

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            self.data_dir = _DEFAULT_DATA_DIR
        else:
            self.data_dir = Path(data_path)

    # -----------------------------------------------------------------------
    # Data loading
    # -----------------------------------------------------------------------

    def load_positions(self) -> Dict[str, float]:
        """Load current positions ``{adapter_id: allocated_usd}``.

        Tries sources in order:

        1. ``data/paper_positions.json``  — ``{"positions": {...}}``
        2. ``data/current_positions.json`` — same schema
        3. Simulated positions via :meth:`_simulate_positions`

        Returns a dict with only positive allocations.
        """
        for filename in ("paper_positions.json", "current_positions.json"):
            path = self.data_dir / filename
            if not path.exists():
                continue
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (ValueError, OSError):
                continue
            if not isinstance(raw, dict):
                continue
            positions = raw.get("positions")
            if not isinstance(positions, dict):
                continue
            result: Dict[str, float] = {}
            for k, v in positions.items():
                f = _safe_float(v)
                if f > 0:
                    result[k] = f
            if result:
                return result
        return self._simulate_positions()

    def _simulate_positions(self) -> Dict[str, float]:
        """Distribute DEFAULT_PORTFOLIO_USD proportionally by TVL.

        Only adapters with ``apy > 0`` and ``tvl_usd >= 5_000_000`` are
        eligible. Falls back to any adapter with positive APY when the TVL
        floor filters out everything. Allocates 95 % of capital (5 % cash).
        """
        adapter_data = self.load_adapter_data()
        if not adapter_data:
            return {}

        # Eligible: APY > 0 and TVL ≥ $5M
        eligible = {
            aid: data for aid, data in adapter_data.items()
            if _extract_apy(data) > 0
            and _safe_float(data.get("tvl_usd", 0)) >= 5_000_000
        }
        if not eligible:
            # Relax TVL constraint — any adapter with APY > 0
            eligible = {
                aid: data for aid, data in adapter_data.items()
                if _extract_apy(data) > 0
            }
        if not eligible:
            return {}

        tvls = {
            aid: max(_safe_float(data.get("tvl_usd", 0)), 1.0)
            for aid, data in eligible.items()
        }
        total_tvl = sum(tvls.values())
        deployable = self.DEFAULT_PORTFOLIO_USD * 0.95

        return {
            aid: round(deployable * (tvl / total_tvl), 2)
            for aid, tvl in tvls.items()
        }

    def load_adapter_data(self) -> Dict[str, Dict[str, Any]]:
        """Load adapter data from ``adapter_status.json``.

        Returns ``{adapter_id: data_dict}`` for every entry that has a
        ``"tier"`` field.  Non-adapter metadata keys (``generated_at``,
        ``mev_protection``, etc.) are skipped.  The ``"adapters"`` array is
        also processed — each entry keyed by its ``protocol_key`` (hyphens
        normalised to underscores).

        Returns ``{}`` when the file is missing or unreadable.
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

        # Top-level protocol entries
        for key, val in raw.items():
            if key in _SKIP_KEYS:
                continue
            if not isinstance(val, dict):
                continue
            if "tier" not in val:
                continue
            result[key] = val

        # "adapters" array
        adapters_list = raw.get("adapters")
        if isinstance(adapters_list, list):
            for item in adapters_list:
                if not isinstance(item, dict):
                    continue
                protocol_key = item.get("protocol_key") or item.get("adapter_id")
                if not protocol_key or not isinstance(protocol_key, str):
                    continue
                # Store under both original key and normalised key
                normalized = protocol_key.replace("-", "_")
                for k in (protocol_key, normalized):
                    if k not in result:
                        result[k] = item

        return result

    # -----------------------------------------------------------------------
    # Core computation
    # -----------------------------------------------------------------------

    def compute_contribution(
        self,
        adapter_id: str,
        allocated_usd: float,
        adapter_data: Dict[str, Any],
        total_allocated: float,
        total_daily_yield: float = 0.0,
    ) -> AdapterContribution:
        """Compute yield contribution for one adapter.

        Parameters
        ----------
        adapter_id        : Adapter identifier string.
        allocated_usd     : USD amount allocated to this adapter.
        adapter_data      : Raw adapter data dict (used to extract APY / chain / tier).
        total_allocated   : Total portfolio USD (used for weight_pct).
        total_daily_yield : Portfolio-wide daily yield USD (used for contribution_pct).
                            Pass 0.0 to skip contribution_pct (single-adapter convenience).

        Returns
        -------
        AdapterContribution
        """
        apy = _extract_apy(adapter_data)
        chain = _extract_chain(adapter_data)
        tier = _extract_tier(adapter_data)

        annual_yield = allocated_usd * apy / 100.0
        daily_yield = annual_yield / 365.0

        weight_pct = (allocated_usd / total_allocated * 100.0) if total_allocated > 0 else 0.0
        contribution_pct = (
            daily_yield / total_daily_yield * 100.0
            if total_daily_yield > 0 else 0.0
        )

        return AdapterContribution(
            adapter_id=adapter_id,
            chain=chain,
            tier=tier,
            weight_pct=round(weight_pct, 4),
            allocated_usd=round(allocated_usd, 2),
            apy_pct=round(apy, 4),
            daily_yield_usd=round(daily_yield, 6),
            annual_yield_usd=round(annual_yield, 4),
            contribution_pct=round(contribution_pct, 4),
        )

    def compute_diversification_score(
        self, contributions: List[AdapterContribution]
    ) -> float:
        """Compute HHI-based diversification score.

        Formula::

            HHI   = Σ (weight_i / 100) ²
            score = 1 - HHI   ∈ [0, 1]

        0 = fully concentrated (one adapter = 100%), 1 = perfectly uniform.
        Empty input returns 0.0.
        """
        if not contributions:
            return 0.0
        hhi = sum((c.weight_pct / 100.0) ** 2 for c in contributions)
        return round(max(0.0, min(1.0, 1.0 - hhi)), 6)

    # -----------------------------------------------------------------------
    # Report generation
    # -----------------------------------------------------------------------

    def generate_report(
        self, positions: Optional[Dict[str, float]] = None
    ) -> AttributionReport:
        """Generate a full attribution report.

        Parameters
        ----------
        positions : dict, optional
            ``{adapter_id: allocated_usd}``.  When ``None``, calls
            :meth:`load_positions` to read from disk.

        Returns
        -------
        AttributionReport
        """
        now = datetime.now(timezone.utc).isoformat()

        if positions is None:
            positions = self.load_positions()

        adapter_data = self.load_adapter_data()

        # Filter to positive allocations
        active = {k: v for k, v in (positions or {}).items() if _safe_float(v) > 0}

        if not active:
            return AttributionReport(
                generated_at=now,
                total_allocated_usd=0.0,
                total_daily_yield_usd=0.0,
                total_annual_yield_usd=0.0,
                effective_apy_pct=0.0,
            )

        total_allocated = sum(active.values())

        # Pass 1: compute per-adapter yields
        raw: List[tuple] = []
        for aid, usd in active.items():
            data = adapter_data.get(aid) or {}
            apy = _extract_apy(data)
            annual = usd * apy / 100.0
            daily = annual / 365.0
            raw.append((aid, usd, data, apy, annual, daily))

        total_daily = sum(r[5] for r in raw)
        total_annual = sum(r[4] for r in raw)

        # Pass 2: build AdapterContribution objects with contribution_pct
        contributions: List[AdapterContribution] = []
        for aid, usd, data, apy, annual, daily in raw:
            chain = _extract_chain(data)
            tier = _extract_tier(data)
            weight_pct = (usd / total_allocated * 100.0) if total_allocated > 0 else 0.0
            contribution_pct = (daily / total_daily * 100.0) if total_daily > 0 else 0.0
            contributions.append(AdapterContribution(
                adapter_id=aid,
                chain=chain,
                tier=tier,
                weight_pct=round(weight_pct, 4),
                allocated_usd=round(usd, 2),
                apy_pct=round(apy, 4),
                daily_yield_usd=round(daily, 6),
                annual_yield_usd=round(annual, 4),
                contribution_pct=round(contribution_pct, 4),
            ))

        # Sort descending by contribution_pct
        contributions.sort(key=lambda c: c.contribution_pct, reverse=True)

        effective_apy = (total_annual / total_allocated * 100.0) if total_allocated > 0 else 0.0
        top_contributor = contributions[0].adapter_id if contributions else ""
        top_by_apy = max(contributions, key=lambda c: c.apy_pct).adapter_id if contributions else ""

        # Chain breakdown
        chain_breakdown: Dict[str, Dict[str, Any]] = {}
        for c in contributions:
            cb = chain_breakdown.setdefault(c.chain, {
                "allocated_usd": 0.0, "annual_yield_usd": 0.0, "weight_pct": 0.0
            })
            cb["allocated_usd"] += c.allocated_usd
            cb["annual_yield_usd"] += c.annual_yield_usd
        for cb in chain_breakdown.values():
            cb["weight_pct"] = round(
                cb["allocated_usd"] / total_allocated * 100.0 if total_allocated > 0 else 0.0,
                4,
            )
            cb["allocated_usd"] = round(cb["allocated_usd"], 2)
            cb["annual_yield_usd"] = round(cb["annual_yield_usd"], 4)

        # Tier breakdown
        tier_breakdown: Dict[str, Dict[str, Any]] = {}
        for c in contributions:
            tb = tier_breakdown.setdefault(c.tier, {
                "allocated_usd": 0.0, "annual_yield_usd": 0.0, "weight_pct": 0.0
            })
            tb["allocated_usd"] += c.allocated_usd
            tb["annual_yield_usd"] += c.annual_yield_usd
        for tb in tier_breakdown.values():
            tb["weight_pct"] = round(
                tb["allocated_usd"] / total_allocated * 100.0 if total_allocated > 0 else 0.0,
                4,
            )
            tb["allocated_usd"] = round(tb["allocated_usd"], 2)
            tb["annual_yield_usd"] = round(tb["annual_yield_usd"], 4)

        div_score = self.compute_diversification_score(contributions)

        return AttributionReport(
            generated_at=now,
            total_allocated_usd=round(total_allocated, 2),
            total_daily_yield_usd=round(total_daily, 6),
            total_annual_yield_usd=round(total_annual, 4),
            effective_apy_pct=round(effective_apy, 4),
            contributions=contributions,
            top_contributor=top_contributor,
            top_by_apy=top_by_apy,
            chain_breakdown=chain_breakdown,
            tier_breakdown=tier_breakdown,
            diversification_score=div_score,
        )

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def save_report(self, output_path: Optional[str] = None) -> str:
        """Generate and atomically save the attribution report.

        Maintains a ring-buffer of the last :data:`RING_BUFFER_MAX` (30)
        snapshots inside the output file.

        Parameters
        ----------
        output_path : str, optional
            Full file path for the JSON output.  Defaults to
            ``{data_dir}/yield_attribution_tracker.json``.

        Returns
        -------
        str
            Absolute path of the written file.
        """
        if output_path is None:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.data_dir / OUTPUT_FILENAME
        else:
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)

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

        report_dict = self.to_dict()
        snapshots.append(report_dict)
        snapshots = snapshots[-RING_BUFFER_MAX:]

        out: Dict[str, Any] = {
            "schema_version": "1.0",
            "source": "yield_attribution_tracker",
            "last_updated": report_dict.get("generated_at", ""),
            "latest": report_dict,
            "snapshots": snapshots,
        }

        # Atomic write: tmp → os.replace
        atomic_save(out, str(out_path))
        return str(out_path)

    # -----------------------------------------------------------------------
    # Rebalance suggestions
    # -----------------------------------------------------------------------

    def get_rebalance_suggestions(
        self, target_min_contribution_pct: float = 5.0
    ) -> List[Dict[str, Any]]:
        """Suggest allocation changes to balance yield contributions.

        An adapter is **underweight** when ``contribution_pct < target_min``
        and the portfolio has at least one overweight adapter.
        An adapter is **overweight** when ``contribution_pct > 2 × target_min``
        and the portfolio has at least one underweight adapter.

        Returns an empty list when the portfolio is balanced or has no
        active positions.

        Parameters
        ----------
        target_min_contribution_pct : float
            Minimum acceptable contribution % per adapter.  Default 5.0.

        Returns
        -------
        list of dict
            Each dict: ``{action, adapter_id, current_contribution_pct,
            target_min_contribution_pct, reason}``
        """
        report = self.generate_report()
        contributions = report.contributions
        if not contributions:
            return []

        overweight = [
            c for c in contributions
            if c.contribution_pct > 2 * target_min_contribution_pct
        ]
        underweight = [
            c for c in contributions
            if c.contribution_pct < target_min_contribution_pct and c.allocated_usd > 0
        ]

        suggestions: List[Dict[str, Any]] = []

        # Only surface imbalances when both sides exist
        if underweight and overweight:
            for c in underweight:
                suggestions.append({
                    "action": "increase",
                    "adapter_id": c.adapter_id,
                    "current_contribution_pct": c.contribution_pct,
                    "target_min_contribution_pct": target_min_contribution_pct,
                    "reason": (
                        f"Contribution {c.contribution_pct:.1f}% < "
                        f"target {target_min_contribution_pct:.1f}%"
                    ),
                })
            for c in overweight:
                suggestions.append({
                    "action": "decrease",
                    "adapter_id": c.adapter_id,
                    "current_contribution_pct": c.contribution_pct,
                    "target_min_contribution_pct": target_min_contribution_pct,
                    "reason": (
                        f"Contribution {c.contribution_pct:.1f}% > "
                        f"2× target {2 * target_min_contribution_pct:.1f}%"
                    ),
                })

        return suggestions

    # -----------------------------------------------------------------------
    # Output helpers
    # -----------------------------------------------------------------------

    def format_telegram_message(self) -> str:
        """Format a Telegram-ready summary message (≤1500 chars).

        Includes: effective APY, diversification score, daily yield, and the
        top-3 contributors.
        """
        report = self.generate_report()
        lines: List[str] = [
            "📊 Yield Attribution Report",
            (
                f"💰 Total: ${report.total_allocated_usd:,.0f} | "
                f"APY: {report.effective_apy_pct:.2f}%"
            ),
            f"🎯 Diversification: {report.diversification_score:.3f}",
            f"📈 Daily yield: ${report.total_daily_yield_usd:,.2f}",
            "",
            "🏆 Top contributors:",
        ]
        for c in report.contributions[:3]:
            lines.append(
                f"  {c.adapter_id}: {c.contribution_pct:.1f}% "
                f"(APY {c.apy_pct:.1f}%, ${c.allocated_usd:,.0f})"
            )
        msg = "\n".join(lines)
        return msg[:1500]

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the current attribution report."""
        report = self.generate_report()
        return {
            "generated_at": report.generated_at,
            "total_allocated_usd": report.total_allocated_usd,
            "total_daily_yield_usd": report.total_daily_yield_usd,
            "total_annual_yield_usd": report.total_annual_yield_usd,
            "effective_apy_pct": report.effective_apy_pct,
            "top_contributor": report.top_contributor,
            "top_by_apy": report.top_by_apy,
            "chain_breakdown": report.chain_breakdown,
            "tier_breakdown": report.tier_breakdown,
            "diversification_score": report.diversification_score,
            "contributions": [
                {
                    "adapter_id": c.adapter_id,
                    "chain": c.chain,
                    "tier": c.tier,
                    "weight_pct": c.weight_pct,
                    "allocated_usd": c.allocated_usd,
                    "apy_pct": c.apy_pct,
                    "daily_yield_usd": c.daily_yield_usd,
                    "annual_yield_usd": c.annual_yield_usd,
                    "contribution_pct": c.contribution_pct,
                }
                for c in report.contributions
            ],
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="SPA Yield Attribution Tracker (MP-600) — per-adapter contribution analysis."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print report without writing (default).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute and atomically save to data/yield_attribution_tracker.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help="Data directory path.",
    )
    args = parser.parse_args(argv)

    tracker = YieldAttributionTracker(data_path=args.data_dir)
    report = tracker.generate_report()

    print(f"Generated: {report.generated_at}")
    print(f"Total allocated: ${report.total_allocated_usd:,.2f}")
    print(f"Effective APY:   {report.effective_apy_pct:.4f}%")
    print(f"Daily yield:     ${report.total_daily_yield_usd:,.4f}")
    print(f"Annual yield:    ${report.total_annual_yield_usd:,.2f}")
    print(f"Diversification: {report.diversification_score:.6f}")
    print(f"Top contributor: {report.top_contributor}")
    print(f"Top APY:         {report.top_by_apy}")
    print(f"Adapters:        {len(report.contributions)}")
    print("")
    if report.contributions:
        print("Contributions (top 10):")
        for c in report.contributions[:10]:
            print(
                f"  {c.adapter_id:<30s}  "
                f"alloc=${c.allocated_usd:>10,.0f}  "
                f"apy={c.apy_pct:>6.2f}%  "
                f"contrib={c.contribution_pct:>6.1f}%"
            )
    print("")
    if report.chain_breakdown:
        print("Chain breakdown:")
        for chain, cb in sorted(report.chain_breakdown.items()):
            print(
                f"  {chain:<15s}  weight={cb['weight_pct']:>6.1f}%  "
                f"annual=${cb['annual_yield_usd']:>10,.2f}"
            )
    if report.tier_breakdown:
        print("Tier breakdown:")
        for tier, tb in sorted(report.tier_breakdown.items()):
            print(
                f"  {tier:<12s}  weight={tb['weight_pct']:>6.1f}%  "
                f"annual=${tb['annual_yield_usd']:>10,.2f}"
            )

    if args.run:
        path = tracker.save_report()
        print(f"\nSaved → {path}")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
