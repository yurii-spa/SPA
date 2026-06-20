"""Stablecoin Exposure Report (MP-611).

Advisory / read-only analytics module: aggregates portfolio exposure by the
underlying base stablecoin of each adapter, computes concentration (HHI),
classifies depeg-contagion risk level, and produces a Telegram summary.

The base stablecoin is NOT present in the source data -- it is resolved from
``adapter_id`` via the static ``ADAPTER_STABLECOIN_MAP`` (exact match, then
prefix heuristic, else "UNKNOWN").

Design constraints (SPA-BL-011)
-------------------------------
* Pure stdlib -- no numpy/pandas/requests/web3/openai, no pip deps.
* Advisory / read-only -- never touches allocator / risk / execution / monitoring.
* Atomic writes -- tmp + os.replace on every JSON update; no .tmp leftovers.
* Fail-safe reads -- missing / corrupt JSON -> empty result, never raises.
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.stablecoin_exposure_report --check
    python3 -m spa_core.analytics.stablecoin_exposure_report --run
    python3 -m spa_core.analytics.stablecoin_exposure_report --run --data-dir /path/to/data
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"

# Static map: adapter_id -> underlying base stablecoin symbol.
# Reflects the real underlying of each project adapter.
ADAPTER_STABLECOIN_MAP: Dict[str, str] = {
    "compound_v3": "USDC",
    "aave_v3": "USDC",
    "euler_v2": "USDC",
    "maple": "USDC",
    "yearn_v3": "USDC",
    "morpho_blue": "USDC",
    "aave_arbitrum": "USDC",
    "aave_base": "USDC",
    "aave_optimism": "USDC",
    "aave_polygon": "USDC",
    "fluid_fusdc": "USDC",
    "extra_finance_base": "USDC",
    "moonwell_base": "USDC",
    "morpho_steakhouse": "USDC",
    "frax": "FRAX",
    "sfrax": "FRAX",
    "sdai": "DAI",
    "spark_susds": "USDS",
    "scrvusd": "crvUSD",
    "susde": "USDe",
    "wusdm": "USDM",
    "stusd": "USDC",
    "pendle_pt": "USDC",
}

_UNKNOWN = "UNKNOWN"

# Concentration thresholds (HHI in [0, 1])
_HHI_CONCENTRATED = 0.5
_HHI_MODERATE = 0.25

# Contagion thresholds (dominant weight %, strict greater-than)
_CONTAGION_CRITICAL = 80.0
_CONTAGION_HIGH = 60.0
_CONTAGION_MODERATE = 40.0


def resolve_stablecoin(adapter_id: Any) -> str:
    """Resolve the underlying base stablecoin for an adapter_id.

    Resolution order (case-insensitive on adapter_id):
    1. Exact match in ``ADAPTER_STABLECOIN_MAP``.
    2. Prefix heuristic -- adapter_id startswith a known map key.
    3. ``"UNKNOWN"``.

    Parameters
    ----------
    adapter_id : Any
        Adapter identifier; non-string / empty values resolve to "UNKNOWN".

    Returns
    -------
    str
        Stablecoin symbol, or "UNKNOWN".
    """
    if not isinstance(adapter_id, str) or not adapter_id:
        return _UNKNOWN
    key = adapter_id.lower()
    if key in ADAPTER_STABLECOIN_MAP:
        return ADAPTER_STABLECOIN_MAP[key]
    # Prefix heuristic: longest matching key first for determinism.
    for map_key in sorted(ADAPTER_STABLECOIN_MAP, key=len, reverse=True):
        if key.startswith(map_key):
            return ADAPTER_STABLECOIN_MAP[map_key]
    return _UNKNOWN


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StablecoinExposure:
    """Exposure aggregate for a single base stablecoin.

    Attributes
    ----------
    symbol        : Stablecoin symbol (e.g. "USDC", "UNKNOWN").
    allocated_usd : Total allocated capital mapped to this stablecoin.
    weight_pct    : Sum of contribution weight_pct for this stablecoin.
    adapter_count : Number of distinct adapters mapped to this stablecoin.
    adapters      : Sorted list of distinct adapter_ids.
    avg_apy_pct   : allocated_usd-weighted APY; 0.0 when no capital.
    """

    symbol: str
    allocated_usd: float
    weight_pct: float
    adapter_count: int
    adapters: List[str] = field(default_factory=list)
    avg_apy_pct: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "symbol": self.symbol,
            "allocated_usd": round(self.allocated_usd, 2),
            "weight_pct": round(self.weight_pct, 4),
            "adapter_count": self.adapter_count,
            "adapters": list(self.adapters),
            "avg_apy_pct": round(self.avg_apy_pct, 4),
        }


@dataclass
class StablecoinExposureReportData:
    """Full stablecoin exposure report.

    Attributes
    ----------
    generated_at        : ISO-8601 UTC timestamp when this report was produced.
    snapshot_at         : ``generated_at`` of the source snapshot used.
    total_allocated_usd : Sum of allocated_usd across contributions.
    total_stablecoins   : Number of distinct (non-empty) stablecoin groups.
    exposures           : Per-stablecoin exposures, sorted by weight_pct desc.
    dominant_stablecoin : Symbol with the largest weight_pct ("" when empty).
    dominant_weight_pct : Largest weight_pct value (0.0 when empty).
    hhi                 : Herfindahl-Hirschman Index = sum (weight_pct/100)^2,
                          range 0..1; 0.0 when empty.
    concentration_label : "CONCENTRATED" / "MODERATE" / "DIVERSIFIED".
    contagion_risk      : "CRITICAL" / "HIGH" / "MODERATE" / "LOW".
    unknown_weight_pct  : Combined weight_pct of UNKNOWN-mapped adapters.
    recommendations     : Advisory text lines.
    summary             : One-line human-readable summary.
    """

    generated_at: str
    snapshot_at: str
    total_allocated_usd: float
    total_stablecoins: int
    exposures: List[StablecoinExposure] = field(default_factory=list)
    dominant_stablecoin: str = ""
    dominant_weight_pct: float = 0.0
    hhi: float = 0.0
    concentration_label: str = "DIVERSIFIED"
    contagion_risk: str = "LOW"
    unknown_weight_pct: float = 0.0
    recommendations: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "generated_at": self.generated_at,
            "snapshot_at": self.snapshot_at,
            "total_allocated_usd": round(self.total_allocated_usd, 2),
            "total_stablecoins": self.total_stablecoins,
            "exposures": [e.to_dict() for e in self.exposures],
            "dominant_stablecoin": self.dominant_stablecoin,
            "dominant_weight_pct": round(self.dominant_weight_pct, 4),
            "hhi": round(self.hhi, 6),
            "concentration_label": self.concentration_label,
            "contagion_risk": self.contagion_risk,
            "unknown_weight_pct": round(self.unknown_weight_pct, 4),
            "recommendations": list(self.recommendations),
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# StablecoinExposureReport
# ---------------------------------------------------------------------------


class StablecoinExposureReport:
    """Aggregate portfolio exposure by underlying base stablecoin.

    Parameters
    ----------
    data_path : str, optional
        Directory containing the source tracker and where the output is
        written.  Defaults to ``"data"``.
    """

    SOURCE_FILE: str = "yield_attribution_tracker.json"
    OUTPUT_FILE: str = "stablecoin_exposure.json"
    RING_BUFFER_SIZE: int = 30

    def __init__(self, data_path: str = "data") -> None:
        if data_path is None:
            self.data_dir = _DEFAULT_DATA_DIR
        else:
            self.data_dir = Path(data_path)

    # -----------------------------------------------------------------------
    # Data loading
    # -----------------------------------------------------------------------

    def load_latest_snapshot(self) -> Dict[str, Any]:
        """Fail-safe load of the latest snapshot from the source tracker.

        Returns
        -------
        dict
            The last snapshot dict from ``snapshots``, or ``{}`` when the file
            is missing, unreadable, malformed, or contains no snapshots.
        """
        src_path = self.data_dir / self.SOURCE_FILE
        if not src_path.exists():
            return {}
        try:
            raw = json.loads(src_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}
        if not isinstance(raw, dict):
            return {}
        snapshots = raw.get("snapshots")
        if not isinstance(snapshots, list) or not snapshots:
            return {}
        valid = [s for s in snapshots if isinstance(s, dict)]
        if not valid:
            return {}
        return valid[-1]

    def _parse_timestamp(self, ts: Any) -> datetime:
        """Parse an ISO-8601 timestamp to a UTC-aware datetime.

        Normalises a trailing 'Z' to '+00:00'.  On failure (or non-string),
        returns the current UTC time.
        """
        if isinstance(ts, str) and ts:
            try:
                normalized = ts.replace("Z", "+00:00")
                dt = datetime.fromisoformat(normalized)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt.astimezone(timezone.utc)
            except (ValueError, AttributeError):
                pass
        return datetime.now(timezone.utc)

    def _resolve(self, adapter_id: Any) -> str:
        """Resolve a stablecoin via the module-level resolver."""
        return resolve_stablecoin(adapter_id)

    # -----------------------------------------------------------------------
    # Core logic
    # -----------------------------------------------------------------------

    def _concentration_label(self, hhi: float) -> str:
        if hhi > _HHI_CONCENTRATED:
            return "CONCENTRATED"
        if hhi > _HHI_MODERATE:
            return "MODERATE"
        return "DIVERSIFIED"

    def _contagion_risk(self, dominant_weight_pct: float) -> str:
        if dominant_weight_pct > _CONTAGION_CRITICAL:
            return "CRITICAL"
        if dominant_weight_pct > _CONTAGION_HIGH:
            return "HIGH"
        if dominant_weight_pct > _CONTAGION_MODERATE:
            return "MODERATE"
        return "LOW"

    def _empty_report(self, snapshot_at: str = "") -> StablecoinExposureReportData:
        """Build a meaningful empty report (no contributions)."""
        now_str = datetime.now(timezone.utc).isoformat()
        return StablecoinExposureReportData(
            generated_at=now_str,
            snapshot_at=snapshot_at,
            total_allocated_usd=0.0,
            total_stablecoins=0,
            exposures=[],
            dominant_stablecoin="",
            dominant_weight_pct=0.0,
            hhi=0.0,
            concentration_label="DIVERSIFIED",
            contagion_risk="LOW",
            unknown_weight_pct=0.0,
            recommendations=["i No allocation data available -- nothing to assess."],
            summary="Stablecoin exposure: no data available",
        )

    def compute_exposures(
        self, snapshot: Optional[Dict[str, Any]] = None
    ) -> StablecoinExposureReportData:
        """Compute the stablecoin exposure report for a snapshot.

        Parameters
        ----------
        snapshot : dict, optional
            Source snapshot.  When ``None``, :meth:`load_latest_snapshot` is used.

        Returns
        -------
        StablecoinExposureReportData
        """
        if snapshot is None:
            snapshot = self.load_latest_snapshot()
        if not isinstance(snapshot, dict):
            snapshot = {}

        snapshot_at = snapshot.get("generated_at", "")
        if not isinstance(snapshot_at, str):
            snapshot_at = ""

        contribs = snapshot.get("contributions")
        if not isinstance(contribs, list) or not contribs:
            return self._empty_report(snapshot_at=snapshot_at)

        # Group contributions by resolved stablecoin.
        groups: Dict[str, Dict[str, Any]] = {}
        total_allocated = 0.0

        for item in contribs:
            if not isinstance(item, dict):
                continue
            adapter_id = item.get("adapter_id")
            try:
                allocated = float(item.get("allocated_usd", 0.0))
            except (TypeError, ValueError):
                allocated = 0.0
            try:
                weight = float(item.get("weight_pct", 0.0))
            except (TypeError, ValueError):
                weight = 0.0
            try:
                apy = float(item.get("apy_pct", 0.0))
            except (TypeError, ValueError):
                apy = 0.0

            total_allocated += allocated

            symbol = self._resolve(adapter_id)
            grp = groups.setdefault(
                symbol,
                {
                    "allocated_usd": 0.0,
                    "weight_pct": 0.0,
                    "adapters": set(),
                    "apy_weight_sum": 0.0,  # sum apy * allocated
                    "apy_capital": 0.0,     # sum allocated (for weighting)
                },
            )
            grp["allocated_usd"] += allocated
            grp["weight_pct"] += weight
            if isinstance(adapter_id, str) and adapter_id:
                grp["adapters"].add(adapter_id)
            grp["apy_weight_sum"] += apy * allocated
            grp["apy_capital"] += allocated

        exposures: List[StablecoinExposure] = []
        for symbol, grp in groups.items():
            cap = grp["apy_capital"]
            avg_apy = (grp["apy_weight_sum"] / cap) if cap > 0 else 0.0
            adapters_sorted = sorted(grp["adapters"])
            exposures.append(
                StablecoinExposure(
                    symbol=symbol,
                    allocated_usd=grp["allocated_usd"],
                    weight_pct=grp["weight_pct"],
                    adapter_count=len(adapters_sorted),
                    adapters=adapters_sorted,
                    avg_apy_pct=avg_apy,
                )
            )

        # Sort by weight_pct desc (stable tiebreak by symbol).
        exposures.sort(key=lambda e: (-e.weight_pct, e.symbol))

        # HHI = sum (weight_pct / 100)^2
        hhi = sum((e.weight_pct / 100.0) ** 2 for e in exposures)

        dominant_symbol = exposures[0].symbol if exposures else ""
        dominant_weight = exposures[0].weight_pct if exposures else 0.0

        unknown_weight = sum(
            e.weight_pct for e in exposures if e.symbol == _UNKNOWN
        )

        concentration_label = self._concentration_label(hhi)
        contagion_risk = self._contagion_risk(dominant_weight)

        recommendations = self._build_recommendations(
            dominant_symbol=dominant_symbol,
            dominant_weight=dominant_weight,
            contagion_risk=contagion_risk,
            unknown_weight=unknown_weight,
        )

        summary = (
            f"Stablecoin exposure: {len(exposures)} coins, "
            f"dominant {dominant_symbol} {dominant_weight:.1f}%, "
            f"HHI {hhi:.3f}, contagion {contagion_risk}"
        )

        return StablecoinExposureReportData(
            generated_at=datetime.now(timezone.utc).isoformat(),
            snapshot_at=snapshot_at,
            total_allocated_usd=total_allocated,
            total_stablecoins=len(exposures),
            exposures=exposures,
            dominant_stablecoin=dominant_symbol,
            dominant_weight_pct=dominant_weight,
            hhi=hhi,
            concentration_label=concentration_label,
            contagion_risk=contagion_risk,
            unknown_weight_pct=unknown_weight,
            recommendations=recommendations,
            summary=summary,
        )

    def _build_recommendations(
        self,
        dominant_symbol: str,
        dominant_weight: float,
        contagion_risk: str,
        unknown_weight: float,
    ) -> List[str]:
        """Build advisory recommendation lines."""
        recs: List[str] = []
        if contagion_risk in ("CRITICAL", "HIGH"):
            recs.append(
                f"! {dominant_symbol} exposure {dominant_weight:.1f}% -- "
                f"vysokij risk depeg-kontagiona, diversificiruj bazovyj aktiv"
            )
        if unknown_weight > 0:
            recs.append(
                f"i {unknown_weight:.1f}% kapitala na adapterah s neizvestnym "
                f"bazovym aktivom -- popolni ADAPTER_STABLECOIN_MAP"
            )
        if not recs:
            recs.append("ok Ekspoziciya diversificirovana")
        return recs

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def save_report(
        self, report: Optional[StablecoinExposureReportData] = None
    ) -> str:
        """Atomically save the report, maintaining a ring-buffer of 30.

        Parameters
        ----------
        report : StablecoinExposureReportData, optional
            Pre-computed report.  When ``None``, :meth:`compute_exposures`
            is called.

        Returns
        -------
        str
            Absolute path of the written file.
        """
        if report is None:
            report = self.compute_exposures()

        self.data_dir.mkdir(parents=True, exist_ok=True)
        out_path = self.data_dir / self.OUTPUT_FILE

        # Load existing ring-buffer.
        history: List[Dict[str, Any]] = []
        if out_path.exists():
            try:
                existing = json.loads(out_path.read_text(encoding="utf-8"))
                if isinstance(existing, dict):
                    hist = existing.get("history", [])
                    if isinstance(hist, list):
                        history = [h for h in hist if isinstance(h, dict)]
            except (ValueError, OSError):
                pass

        report_dict = report.to_dict()
        history.append(report_dict)
        history = history[-self.RING_BUFFER_SIZE:]

        out: Dict[str, Any] = {
            "schema_version": 1,
            "source": "stablecoin_exposure_report",
            "last_updated": report_dict["generated_at"],
            "count": len(history),
            "latest": report_dict,
            "history": history,
        }

        # Atomic write: tmp + os.replace.
        atomic_save(out, str(out_path))
        return str(out_path)

    # -----------------------------------------------------------------------
    # Output helpers
    # -----------------------------------------------------------------------

    def format_telegram_message(
        self, report: Optional[StablecoinExposureReportData] = None
    ) -> str:
        """Format a Telegram-ready message (<=1500 chars)."""
        if report is None:
            report = self.compute_exposures()

        if report.total_stablecoins == 0:
            return "Stablecoin Exposure\nNo allocation data available."[:1500]

        if report.contagion_risk in ("CRITICAL", "HIGH"):
            risk_emoji = "!"
        elif report.contagion_risk == "LOW":
            risk_emoji = "ok"
        else:
            risk_emoji = "~"

        lines = [
            "Stablecoin Exposure",
            f"Dominant: {report.dominant_stablecoin} "
            f"{report.dominant_weight_pct:.1f}%",
            f"HHI: {report.hhi:.3f} ({report.concentration_label})",
            f"{risk_emoji} Contagion: {report.contagion_risk}",
            "Top stablecoins:",
        ]
        for exp in report.exposures[:3]:
            lines.append(
                f"  - {exp.symbol}: {exp.weight_pct:.1f}% "
                f"(${exp.allocated_usd/1000.0:,.0f}K, {exp.adapter_count} adapter(s))"
            )

        if report.unknown_weight_pct > 0:
            lines.append(f"? Unknown base: {report.unknown_weight_pct:.1f}%")

        lines.append(f"t {report.snapshot_at or report.generated_at}")

        msg = "\n".join(lines)
        return msg[:1500]

    def to_dict(
        self, report: Optional[StablecoinExposureReportData] = None
    ) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the report."""
        if report is None:
            report = self.compute_exposures()
        return report.to_dict()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SPA Stablecoin Exposure Report (MP-611) -- "
            "aggregate portfolio exposure by underlying base stablecoin."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print summary without writing (default).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute and atomically save to data/stablecoin_exposure.json.",
    )
    parser.add_argument(
        "--data-dir",
        default="data",
        help="Data directory path (default: data).",
    )
    args = parser.parse_args(argv)

    reporter = StablecoinExposureReport(data_path=args.data_dir)
    report = reporter.compute_exposures()

    print(f"Generated:        {report.generated_at}")
    print(f"Snapshot:         {report.snapshot_at or 'n/a'}")
    print(f"Total allocated:  ${report.total_allocated_usd:,.2f}")
    print(f"Stablecoins:      {report.total_stablecoins}")
    print(f"Dominant:         {report.dominant_stablecoin or 'n/a'} "
          f"({report.dominant_weight_pct:.2f}%)")
    print(f"HHI:              {report.hhi:.4f} ({report.concentration_label})")
    print(f"Contagion risk:   {report.contagion_risk}")
    print(f"Unknown weight:   {report.unknown_weight_pct:.2f}%")
    print(f"Summary:          {report.summary}")
    print()

    if report.exposures:
        print("Exposures:")
        for exp in report.exposures:
            print(
                f"  {exp.symbol:>8s}  {exp.weight_pct:6.2f}%  "
                f"${exp.allocated_usd:>14,.2f}  "
                f"apy {exp.avg_apy_pct:5.2f}%  "
                f"adapters={exp.adapters}"
            )
        print()

    if report.recommendations:
        print("Recommendations:")
        for rec in report.recommendations:
            print(f"  {rec}")
        print()

    if args.run:
        path = reporter.save_report(report)
        print(f"Saved -> {path}")
        print(f"Summary: {report.summary}")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
