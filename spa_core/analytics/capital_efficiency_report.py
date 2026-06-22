"""Capital Efficiency Report (MP-616).

Отслеживает эффективность использования капитала:
  - Deployment rate: % капитала в eligible адаптерах.
  - Idle capital: $ не deployed.
  - RAROC: Risk-Adjusted Return on Capital = (APY - T-bill) / avg_risk_score.
  - Opportunity cost: idle_capital * (best_adapter_apy - tbill) / 100 / 365 (daily $).

Данные берёт из:
  1. data/yield_attribution_tracker.json → последний снапшот contributions
  2. data/adapter_status.json → max APY среди eligible адаптеров

Сохраняет историю в data/capital_efficiency.json (ring-buffer 30).

Design constraints
------------------
* Pure stdlib — no external deps (no requests / numpy / pandas / web3 / LLM SDK).
* Advisory only — never touches allocator / risk / execution.
* Atomic writes — tmp + os.replace on every JSON update.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.capital_efficiency_report --check
    python3 -m spa_core.analytics.capital_efficiency_report --run
    python3 -m spa_core.analytics.capital_efficiency_report --run --data-dir /path/to/data

MP-616.
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
# Project root & paths
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

OUTPUT_FILENAME = "capital_efficiency.json"
RING_BUFFER_MAX = 30

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Keys верхнего уровня adapter_status.json, которые не являются адаптерами
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


def _extract_apy_from_adapter(data: Dict[str, Any]) -> float:
    """Extract APY % from an adapter data dict.

    Tries: ``apy_pct`` → ``apy`` → first value from ``mock_apy[chain][asset]``.
    Returns 0.0 when nothing usable found.
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


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class AdapterEfficiency:
    """Capital efficiency metrics for a single adapter.

    Attributes
    ----------
    adapter_key         : Protocol / adapter identifier.
    allocated_usd       : Capital deployed in USD.
    apy_pct             : Current APY in %.
    risk_score          : Risk score (0.0 – 1.0); higher = riskier.
    daily_yield_usd     : allocated_usd * apy_pct / 100 / 365.
    raroc               : (apy_pct - TBILL_RATE) / risk_score if risk_score > 0 else 0.0.
    efficiency_grade    : "A" (raroc > 15) / "B" (> 8) / "C" (> 3) / "D" (≤ 3).
    """

    adapter_key: str
    allocated_usd: float
    apy_pct: float
    risk_score: float
    daily_yield_usd: float
    raroc: float
    efficiency_grade: str

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return asdict(self)


@dataclass
class CapitalEfficiencyData:
    """Full capital efficiency snapshot for the portfolio.

    Attributes
    ----------
    generated_at                 : ISO-8601 UTC timestamp.
    total_capital_usd            : Total portfolio capital (deployed + idle).
    deployed_capital_usd         : Capital in eligible adapters.
    idle_capital_usd             : Capital not deployed (total - deployed).
    deployment_rate_pct          : deployed / total * 100.
    portfolio_apy_pct            : Weighted average APY across deployed capital.
    daily_yield_usd              : deployed * portfolio_apy / 100 / 365.
    annual_yield_usd             : deployed * portfolio_apy / 100.
    avg_risk_score               : Mean risk_score across deployed adapters (0.5 fallback).
    portfolio_raroc              : (portfolio_apy - tbill_rate) / avg_risk_score.
    tbill_rate_pct               : Risk-free rate (4.5%).
    best_adapter_apy_pct         : Maximum APY among eligible adapters.
    idle_opportunity_cost_daily  : idle * (best_apy - tbill) / 100 / 365 daily $ foregone.
    adapters                     : Per-adapter efficiency breakdown.
    top_efficiency_adapter       : Adapter key with max RAROC.
    bottom_efficiency_adapter    : Adapter key with min RAROC (among deployed).
    overall_grade                : Portfolio-level grade A/B/C/D.
    summary                      : Human-readable one-liner.
    """

    generated_at: str
    total_capital_usd: float
    deployed_capital_usd: float
    idle_capital_usd: float
    deployment_rate_pct: float

    # Yield
    portfolio_apy_pct: float
    daily_yield_usd: float
    annual_yield_usd: float

    # Risk-adjusted
    avg_risk_score: float
    portfolio_raroc: float

    # Opportunity cost
    tbill_rate_pct: float
    best_adapter_apy_pct: float
    idle_opportunity_cost_daily: float

    # Adapter breakdown
    adapters: List[AdapterEfficiency] = field(default_factory=list)
    top_efficiency_adapter: str = ""
    bottom_efficiency_adapter: str = ""

    # Grade
    overall_grade: str = "D"
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        d = asdict(self)
        return d


# ---------------------------------------------------------------------------
# CapitalEfficiencyReport
# ---------------------------------------------------------------------------


class CapitalEfficiencyReport:
    """Capital efficiency tracker for the SPA portfolio.

    Measures how effectively capital is deployed:
      * Deployment rate (% in eligible adapters)
      * Idle capital ($ not deployed)
      * RAROC = (APY - T-bill) / avg_risk_score
      * Opportunity cost of idle capital (daily $)
      * Per-adapter efficiency grades A/B/C/D

    Parameters
    ----------
    data_path : str or Path, optional
        Directory containing data files.  Defaults to repo ``data/``.
    """

    TBILL_RATE: float = 4.50              # US 3-month T-bill rate (%)
    TOTAL_CAPITAL_USD: float = 100_000.0  # Default total portfolio capital

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            self.data_dir = _DEFAULT_DATA_DIR
        else:
            self.data_dir = Path(data_path)

    # -----------------------------------------------------------------------
    # Data loading
    # -----------------------------------------------------------------------

    def load_positions(self) -> tuple:
        """Load positions from yield_attribution_tracker.json.

        Reads ``latest.contributions`` from the tracker snapshot and returns
        a (total_capital_usd, contributions_list) tuple.

        Each contribution dict is expected to have at least:
            adapter_id / adapter_key, allocated_usd, apy_pct, risk_score.

        Returns
        -------
        tuple[float, list[dict]]
            (total_capital_usd, contributions) — contributions is a list of
            dicts.  Falls back to (TOTAL_CAPITAL_USD, []) on any error.
        """
        path = self.data_dir / "yield_attribution_tracker.json"
        fallback = (self.TOTAL_CAPITAL_USD, [])
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
            total = self.TOTAL_CAPITAL_USD

        contributions = latest.get("contributions", [])
        if not isinstance(contributions, list):
            contributions = []

        # Filter to dicts with positive allocation
        valid: List[Dict[str, Any]] = []
        for c in contributions:
            if not isinstance(c, dict):
                continue
            usd = _safe_float(c.get("allocated_usd", 0))
            if usd > 0:
                valid.append(c)

        return (total, valid)

    def load_best_apy(self) -> float:
        """Get the best single adapter APY from adapter_status.json.

        Reads all adapters and returns the maximum APY found.
        Represents the "naive optimal strategy" — deploy everything in best adapter.

        Returns
        -------
        float
            Maximum adapter APY in %.  Falls back to 5.0 if file is missing
            or no valid APY found.
        """
        path = self.data_dir / "adapter_status.json"
        fallback = 5.0
        if not path.exists():
            return fallback
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return fallback
        if not isinstance(raw, dict):
            return fallback

        apys: List[float] = []

        # Top-level protocol entries
        for key, val in raw.items():
            if key in _SKIP_KEYS:
                continue
            if not isinstance(val, dict):
                continue
            apy = _extract_apy_from_adapter(val)
            if apy > 0:
                apys.append(apy)

        # "adapters" array
        adapters_list = raw.get("adapters")
        if isinstance(adapters_list, list):
            for item in adapters_list:
                if not isinstance(item, dict):
                    continue
                apy = _extract_apy_from_adapter(item)
                if apy > 0:
                    apys.append(apy)

        if not apys:
            return fallback
        return round(max(apys), 4)

    # -----------------------------------------------------------------------
    # Computation helpers
    # -----------------------------------------------------------------------

    @staticmethod
    def _efficiency_grade(raroc: float) -> str:
        """Map RAROC value to efficiency grade.

        Thresholds:
          "A": raroc > 15
          "B": raroc > 8
          "C": raroc > 3
          "D": raroc ≤ 3
        """
        if raroc > 15:
            return "A"
        if raroc > 8:
            return "B"
        if raroc > 3:
            return "C"
        return "D"

    @staticmethod
    def _overall_grade(deployment_rate_pct: float, raroc: float) -> str:
        """Determine overall portfolio efficiency grade.

        Rules:
          "A": deployment_rate > 90% AND raroc > 10
          "B": deployment_rate > 70% OR raroc > 6
          "C": deployment_rate > 50%
          "D": otherwise
        """
        if deployment_rate_pct > 90 and raroc > 10:
            return "A"
        if deployment_rate_pct > 70 or raroc > 6:
            return "B"
        if deployment_rate_pct > 50:
            return "C"
        return "D"

    def compute_adapter_efficiency(self, contribution: dict) -> AdapterEfficiency:
        """Compute capital efficiency for a single adapter contribution.

        Parameters
        ----------
        contribution : dict
            Dict with fields: adapter_id (or adapter_key), allocated_usd,
            apy_pct, risk_score (optional, defaults to 0.5).

        Returns
        -------
        AdapterEfficiency
        """
        # Normalise key — accept both adapter_id and adapter_key
        adapter_key = (
            contribution.get("adapter_key")
            or contribution.get("adapter_id")
            or "unknown"
        )
        allocated_usd = _safe_float(contribution.get("allocated_usd", 0))
        apy_pct = _safe_float(contribution.get("apy_pct", 0))

        daily_yield_usd = round(allocated_usd * apy_pct / 100.0 / 365.0, 6)

        # RAROC: (APY - T-bill) / risk_score if risk_score > 0 else 0.0
        # Distinguish between "key absent → use default 0.5" and "explicit 0 → raroc=0.0"
        raw_risk_in_source = contribution.get("risk_score")
        if raw_risk_in_source is None:
            # Not provided in source data → use default 0.5 for both display and RAROC
            risk_score = 0.5
            raroc = round((apy_pct - self.TBILL_RATE) / risk_score, 4)
        else:
            source_risk = _safe_float(raw_risk_in_source)
            if source_risk <= 0:
                # Explicit zero (or invalid) → raroc undefined → 0.0; display default
                risk_score = 0.5
                raroc = 0.0
            else:
                risk_score = source_risk
                raroc = round((apy_pct - self.TBILL_RATE) / risk_score, 4)

        grade = self._efficiency_grade(raroc)

        return AdapterEfficiency(
            adapter_key=str(adapter_key),
            allocated_usd=round(allocated_usd, 2),
            apy_pct=round(apy_pct, 4),
            risk_score=round(risk_score, 4),
            daily_yield_usd=daily_yield_usd,
            raroc=raroc,
            efficiency_grade=grade,
        )

    # -----------------------------------------------------------------------
    # Report generation
    # -----------------------------------------------------------------------

    def generate_report(self) -> CapitalEfficiencyData:
        """Generate a full capital efficiency report.

        Steps:
          1. Load positions from yield_attribution_tracker.json.
          2. Compute AdapterEfficiency for each contribution.
          3. Compute aggregate metrics (idle, deployment rate, RAROC, …).
          4. Load best adapter APY from adapter_status.json.
          5. Compute opportunity cost of idle capital.
          6. Determine overall grade.

        Returns
        -------
        CapitalEfficiencyData
        """
        now = datetime.now(timezone.utc).isoformat()
        tbill = self.TBILL_RATE

        total_capital, contributions = self.load_positions()
        best_apy = self.load_best_apy()

        # Compute per-adapter efficiency
        adapter_results: List[AdapterEfficiency] = []
        for c in contributions:
            ae = self.compute_adapter_efficiency(c)
            if ae.allocated_usd > 0:
                adapter_results.append(ae)

        # Aggregate deployed capital
        deployed_usd = sum(ae.allocated_usd for ae in adapter_results)
        idle_usd = round(max(0.0, total_capital - deployed_usd), 2)
        deployment_rate = round(deployed_usd / total_capital * 100.0, 4) if total_capital > 0 else 0.0

        # Portfolio APY (weighted average by allocation)
        if deployed_usd > 0:
            portfolio_apy = sum(ae.apy_pct * ae.allocated_usd for ae in adapter_results) / deployed_usd
        else:
            portfolio_apy = 0.0
        portfolio_apy = round(portfolio_apy, 4)

        daily_yield = round(deployed_usd * portfolio_apy / 100.0 / 365.0, 6)
        annual_yield = round(deployed_usd * portfolio_apy / 100.0, 4)

        # Average risk score
        if adapter_results:
            avg_risk = sum(ae.risk_score for ae in adapter_results) / len(adapter_results)
        else:
            avg_risk = 0.5
        avg_risk = round(avg_risk, 4)

        # Portfolio RAROC
        if avg_risk > 0:
            portfolio_raroc = round((portfolio_apy - tbill) / avg_risk, 4)
        else:
            portfolio_raroc = 0.0

        # Opportunity cost of idle capital (daily $)
        excess_apy = max(0.0, best_apy - tbill)
        idle_opp_cost = round(idle_usd * excess_apy / 100.0 / 365.0, 6)

        # Top / bottom adapters by RAROC (among deployed)
        top_key = ""
        bottom_key = ""
        if adapter_results:
            top_key = max(adapter_results, key=lambda ae: ae.raroc).adapter_key
            bottom_key = min(adapter_results, key=lambda ae: ae.raroc).adapter_key

        # Overall grade
        overall = self._overall_grade(deployment_rate, portfolio_raroc)

        # Summary line
        deployed_k = deployed_usd / 1000.0
        total_k = total_capital / 1000.0
        summary = (
            f"Deployed {deployment_rate:.1f}% (${deployed_k:.0f}K / ${total_k:.0f}K), "
            f"RAROC {portfolio_raroc:.1f}x, Grade {overall}"
        )

        return CapitalEfficiencyData(
            generated_at=now,
            total_capital_usd=round(total_capital, 2),
            deployed_capital_usd=round(deployed_usd, 2),
            idle_capital_usd=idle_usd,
            deployment_rate_pct=deployment_rate,
            portfolio_apy_pct=portfolio_apy,
            daily_yield_usd=daily_yield,
            annual_yield_usd=annual_yield,
            avg_risk_score=avg_risk,
            portfolio_raroc=portfolio_raroc,
            tbill_rate_pct=tbill,
            best_adapter_apy_pct=round(best_apy, 4),
            idle_opportunity_cost_daily=idle_opp_cost,
            adapters=adapter_results,
            top_efficiency_adapter=top_key,
            bottom_efficiency_adapter=bottom_key,
            overall_grade=overall,
            summary=summary,
        )

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def save_report(self, report: Optional[CapitalEfficiencyData] = None) -> str:
        """Generate (if needed) and atomically save the capital efficiency report.

        Maintains a ring-buffer of the last :data:`RING_BUFFER_MAX` (30)
        snapshots inside ``data/capital_efficiency.json``.

        Parameters
        ----------
        report : CapitalEfficiencyData, optional
            Pre-computed report.  If ``None``, calls :meth:`generate_report`.

        Returns
        -------
        str
            Absolute path of the written file.
        """
        if report is None:
            report = self.generate_report()

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

        report_dict = self.to_dict(report)
        snapshots.append(report_dict)
        snapshots = snapshots[-RING_BUFFER_MAX:]

        out: Dict[str, Any] = {
            "schema_version": "1.0",
            "source": "capital_efficiency_report",
            "last_updated": report_dict.get("generated_at", ""),
            "latest": report_dict,
            "snapshots": snapshots,
        }

        # Atomic write: tmp → os.replace
        atomic_save(out, str(out_path))
        return str(out_path)

    # -----------------------------------------------------------------------
    # Output helpers
    # -----------------------------------------------------------------------

    def format_telegram_message(self, report: Optional[CapitalEfficiencyData] = None) -> str:
        """Format a Telegram-ready capital efficiency message (≤1500 chars).

        Example output::

            💰 Capital Efficiency — Grade A
            Deployed: 85.0% ($85K / $100K)
            Idle: $15K | Opp.cost/day: $2.30
            APY: 5.22% | RAROC: 12.3x
            Top: morpho_blue (RAROC 18.5x) | Bottom: compound_v3 (3.2x)

        Parameters
        ----------
        report : CapitalEfficiencyData, optional
            Pre-computed report.  If ``None``, calls :meth:`generate_report`.

        Returns
        -------
        str
            Formatted message, max 1500 characters.
        """
        if report is None:
            report = self.generate_report()

        deployed_k = report.deployed_capital_usd / 1000.0
        total_k = report.total_capital_usd / 1000.0
        idle_k = report.idle_capital_usd / 1000.0

        lines: List[str] = [
            f"💰 Capital Efficiency — Grade {report.overall_grade}",
            f"Deployed: {report.deployment_rate_pct:.1f}% (${deployed_k:.0f}K / ${total_k:.0f}K)",
            f"Idle: ${idle_k:.0f}K | Opp.cost/day: ${report.idle_opportunity_cost_daily:.2f}",
            f"APY: {report.portfolio_apy_pct:.2f}% | RAROC: {report.portfolio_raroc:.1f}x",
        ]

        if report.adapters:
            top_ae = next(
                (ae for ae in report.adapters if ae.adapter_key == report.top_efficiency_adapter),
                None,
            )
            bot_ae = next(
                (ae for ae in report.adapters if ae.adapter_key == report.bottom_efficiency_adapter),
                None,
            )
            if top_ae and bot_ae and top_ae.adapter_key != bot_ae.adapter_key:
                lines.append(
                    f"Top: {top_ae.adapter_key} (RAROC {top_ae.raroc:.1f}x) | "
                    f"Bottom: {bot_ae.adapter_key} (RAROC {bot_ae.raroc:.1f}x)"
                )
            elif top_ae:
                lines.append(f"Top: {top_ae.adapter_key} (RAROC {top_ae.raroc:.1f}x)")
        else:
            lines.append("No adapters deployed")

        lines.append(f"T-bill: {report.tbill_rate_pct:.1f}% | Best adapter: {report.best_adapter_apy_pct:.2f}%")

        msg = "\n".join(lines)
        return msg[:1500]

    def to_dict(self, report: Optional[CapitalEfficiencyData] = None) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the capital efficiency report.

        Parameters
        ----------
        report : CapitalEfficiencyData, optional
            Pre-computed report.  If ``None``, calls :meth:`generate_report`.
        """
        if report is None:
            report = self.generate_report()
        d = asdict(report)
        return d


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="SPA Capital Efficiency Report (MP-616) — deployment rate, idle capital, RAROC."
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
        help="Compute and atomically save to data/capital_efficiency.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help="Data directory path.",
    )
    args = parser.parse_args(argv)

    reporter = CapitalEfficiencyReport(data_path=args.data_dir)
    report = reporter.generate_report()

    print("=== Capital Efficiency Report (MP-616) ===")
    print(f"Generated:       {report.generated_at}")
    print(f"Total capital:   ${report.total_capital_usd:,.2f}")
    print(f"Deployed:        ${report.deployed_capital_usd:,.2f} ({report.deployment_rate_pct:.2f}%)")
    print(f"Idle:            ${report.idle_capital_usd:,.2f}")
    print(f"Portfolio APY:   {report.portfolio_apy_pct:.4f}%")
    print(f"Daily yield:     ${report.daily_yield_usd:,.4f}")
    print(f"Annual yield:    ${report.annual_yield_usd:,.2f}")
    print(f"Avg risk score:  {report.avg_risk_score:.4f}")
    print(f"Portfolio RAROC: {report.portfolio_raroc:.4f}x")
    print(f"T-bill rate:     {report.tbill_rate_pct:.2f}%")
    print(f"Best adapter APY:{report.best_adapter_apy_pct:.4f}%")
    print(f"Opp.cost/day:   ${report.idle_opportunity_cost_daily:.4f}")
    print(f"Overall grade:   {report.overall_grade}")
    print(f"Summary:         {report.summary}")
    print(f"Top adapter:     {report.top_efficiency_adapter}")
    print(f"Bottom adapter:  {report.bottom_efficiency_adapter}")
    print(f"Adapters:        {len(report.adapters)}")
    print("")

    if report.adapters:
        print("Adapter efficiency:")
        for ae in sorted(report.adapters, key=lambda x: x.raroc, reverse=True):
            print(
                f"  [{ae.efficiency_grade}] {ae.adapter_key:<30s}  "
                f"alloc=${ae.allocated_usd:>10,.0f}  "
                f"apy={ae.apy_pct:>6.2f}%  "
                f"risk={ae.risk_score:.2f}  "
                f"raroc={ae.raroc:>7.2f}x"
            )

    if args.run:
        path = reporter.save_report(report)
        print(f"\nSaved → {path}")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
