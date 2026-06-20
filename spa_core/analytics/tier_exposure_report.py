"""Tier Exposure Report (MP-617).

Advisory / read-only analytics module: aggregates portfolio exposure by RISK
TIER (T1 / T2 / T3 / UNKNOWN), computes per-tier concentration (HHI), checks
compliance with policy caps (ADR-019: T2 <= 50% AUM; ADR-020: T3 <= 15% AUM),
computes tier-weighted APY, and produces a Telegram summary.

The tier of each adapter is read directly from the source ``tier`` field of
each contribution; missing / empty tiers resolve to "UNKNOWN".

Design constraints (SPA-BL-011)
-------------------------------
* Pure stdlib -- no numpy/pandas/requests/web3/openai, no pip deps.
* Advisory / read-only -- never touches allocator / risk / execution / monitoring.
* Atomic writes -- tmp + os.replace on every JSON update; no .tmp leftovers.
* Fail-safe reads -- missing / corrupt / non-dict JSON -> empty result, never raises.
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.tier_exposure_report --check
    python3 -m spa_core.analytics.tier_exposure_report --run
    python3 -m spa_core.analytics.tier_exposure_report --run --data-dir /path/to/data

MP-617.
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

# Policy caps (% of AUM). T1 has no cap -- it is the anchor tier.
#   ADR-019: T2 <= 50% AUM
#   ADR-020: T3 <= 15% AUM
POLICY_CAPS: Dict[str, float] = {"T2": 50.0, "T3": 15.0}

# Stable ordering for sorting / output.
TIER_ORDER: List[str] = ["T1", "T2", "T3", "UNKNOWN"]

_UNKNOWN = "UNKNOWN"

# Concentration thresholds (HHI in [0, 1]); strict greater-than.
_HHI_CONCENTRATED = 0.5
_HHI_MODERATE = 0.25


# ---------------------------------------------------------------------------
# Scalar helpers
# ---------------------------------------------------------------------------


def _safe_float(val: Any) -> float:
    """Coerce value to finite float; bool / non-number / None -> 0.0."""
    if isinstance(val, bool):
        return 0.0
    try:
        f = float(val)
        return f if math.isfinite(f) else 0.0
    except (TypeError, ValueError):
        return 0.0


def _parse_timestamp(s: Any) -> Optional[datetime]:
    """Parse an ISO-8601 timestamp to a UTC-aware datetime.

    Normalises a trailing 'Z' to '+00:00'.  On failure (or non-string),
    returns ``None``.
    """
    if isinstance(s, str) and s:
        try:
            normalized = s.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, AttributeError):
            return None
    return None


def _normalize_tier(tier: Any) -> str:
    """Normalise a raw tier value to one of T1/T2/T3/UNKNOWN."""
    if isinstance(tier, str):
        t = tier.strip().upper()
        if t:
            return t
    return _UNKNOWN


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class TierExposure:
    """Exposure aggregate for a single risk tier.

    Attributes
    ----------
    tier           : Tier label (e.g. "T1", "T2", "T3", "UNKNOWN").
    allocated_usd  : Total allocated capital in this tier.
    weight_pct     : Sum of contribution weight_pct for this tier.
    adapter_count  : Number of distinct adapters in this tier.
    adapters       : Sorted list of distinct adapter_ids.
    avg_apy_pct    : allocated_usd-weighted APY; 0.0 when no capital.
    annual_yield_usd : Sum of annual_yield_usd for this tier.
    cap_pct        : Policy cap (% AUM) for this tier, or None (T1 / UNKNOWN).
    within_cap     : True if cap_pct is None or weight_pct <= cap_pct.
    headroom_pct   : cap_pct - weight_pct, or None when no cap.
    """

    tier: str
    allocated_usd: float
    weight_pct: float
    adapter_count: int
    adapters: List[str] = field(default_factory=list)
    avg_apy_pct: float = 0.0
    annual_yield_usd: float = 0.0
    cap_pct: Optional[float] = None
    within_cap: bool = True
    headroom_pct: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "tier": self.tier,
            "allocated_usd": round(self.allocated_usd, 2),
            "weight_pct": round(self.weight_pct, 4),
            "adapter_count": self.adapter_count,
            "adapters": list(self.adapters),
            "avg_apy_pct": round(self.avg_apy_pct, 4),
            "annual_yield_usd": round(self.annual_yield_usd, 2),
            "cap_pct": self.cap_pct,
            "within_cap": self.within_cap,
            "headroom_pct": (
                round(self.headroom_pct, 4)
                if self.headroom_pct is not None
                else None
            ),
        }


@dataclass
class TierExposureReportData:
    """Full tier exposure report.

    Attributes
    ----------
    generated_at        : ISO-8601 UTC timestamp when this report was produced.
    snapshot_at         : ``generated_at`` of the source snapshot used.
    total_allocated_usd : Sum of allocated_usd across contributions.
    total_tiers         : Number of distinct tier groups.
    exposures           : Per-tier exposures, sorted by TIER_ORDER.
    dominant_tier       : Tier with the largest weight_pct ("" when empty).
    dominant_weight_pct : Largest weight_pct value (0.0 when empty).
    hhi                 : Herfindahl-Hirschman Index = sum (weight/100)^2.
    concentration_label : "CONCENTRATED" / "MODERATE" / "DIVERSIFIED".
    policy_status       : "COMPLIANT" / "BREACH".
    breaches            : Human-readable breach strings.
    portfolio_apy_pct   : Capital-weighted APY across all tiers.
    t1_weight_pct       : Convenience: T1 weight_pct (0.0 if absent).
    t2_weight_pct       : Convenience: T2 weight_pct (0.0 if absent).
    t3_weight_pct       : Convenience: T3 weight_pct (0.0 if absent).
    recommendations     : Advisory text lines.
    summary             : One-line human-readable summary.
    """

    generated_at: str
    snapshot_at: str
    total_allocated_usd: float
    total_tiers: int
    exposures: List[TierExposure] = field(default_factory=list)
    dominant_tier: str = ""
    dominant_weight_pct: float = 0.0
    hhi: float = 0.0
    concentration_label: str = "DIVERSIFIED"
    policy_status: str = "COMPLIANT"
    breaches: List[str] = field(default_factory=list)
    portfolio_apy_pct: float = 0.0
    t1_weight_pct: float = 0.0
    t2_weight_pct: float = 0.0
    t3_weight_pct: float = 0.0
    recommendations: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "generated_at": self.generated_at,
            "snapshot_at": self.snapshot_at,
            "total_allocated_usd": round(self.total_allocated_usd, 2),
            "total_tiers": self.total_tiers,
            "exposures": [e.to_dict() for e in self.exposures],
            "dominant_tier": self.dominant_tier,
            "dominant_weight_pct": round(self.dominant_weight_pct, 4),
            "hhi": round(self.hhi, 6),
            "concentration_label": self.concentration_label,
            "policy_status": self.policy_status,
            "breaches": list(self.breaches),
            "portfolio_apy_pct": round(self.portfolio_apy_pct, 4),
            "t1_weight_pct": round(self.t1_weight_pct, 4),
            "t2_weight_pct": round(self.t2_weight_pct, 4),
            "t3_weight_pct": round(self.t3_weight_pct, 4),
            "recommendations": list(self.recommendations),
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# TierExposureReport
# ---------------------------------------------------------------------------


class TierExposureReport:
    """Aggregate portfolio exposure by risk tier (T1/T2/T3/UNKNOWN).

    Parameters
    ----------
    data_path : str or Path, optional
        Directory containing the source tracker and where the output is
        written.  Defaults to the repo ``data/`` directory.
    """

    SOURCE_FILE: str = "yield_attribution_tracker.json"
    OUTPUT_FILE: str = "tier_exposure.json"
    RING_BUFFER_SIZE: int = 30

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            self.data_dir = _DEFAULT_DATA_DIR
        else:
            self.data_dir = Path(data_path)

    # -----------------------------------------------------------------------
    # Data loading
    # -----------------------------------------------------------------------

    def load_latest_snapshot(self) -> Dict[str, Any]:
        """Fail-safe load of the ``latest`` snapshot from the source tracker.

        Returns
        -------
        dict
            The ``latest`` dict from the tracker, or ``{}`` when the file is
            missing, unreadable, malformed, non-dict, or has no ``latest`` key.
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
        latest = raw.get("latest")
        if not isinstance(latest, dict):
            return {}
        return latest

    # -----------------------------------------------------------------------
    # Core logic
    # -----------------------------------------------------------------------

    def _concentration_label(self, hhi: float) -> str:
        if hhi > _HHI_CONCENTRATED:
            return "CONCENTRATED"
        if hhi > _HHI_MODERATE:
            return "MODERATE"
        return "DIVERSIFIED"

    def _empty_report(self, snapshot_at: str = "") -> TierExposureReportData:
        """Build a meaningful empty report (no contributions)."""
        now_str = datetime.now(timezone.utc).isoformat()
        return TierExposureReportData(
            generated_at=now_str,
            snapshot_at=snapshot_at,
            total_allocated_usd=0.0,
            total_tiers=0,
            exposures=[],
            dominant_tier="",
            dominant_weight_pct=0.0,
            hhi=0.0,
            concentration_label="DIVERSIFIED",
            policy_status="COMPLIANT",
            breaches=[],
            portfolio_apy_pct=0.0,
            t1_weight_pct=0.0,
            t2_weight_pct=0.0,
            t3_weight_pct=0.0,
            recommendations=["No allocation data available -- nothing to assess."],
            summary="Tier exposure: no data available",
        )

    def _tier_sort_key(self, tier: str) -> tuple:
        """Sort key honouring TIER_ORDER, unknown tiers sorted after, by name."""
        try:
            idx = TIER_ORDER.index(tier)
        except ValueError:
            idx = len(TIER_ORDER)
        return (idx, tier)

    def compute_exposures(
        self, snapshot: Optional[Dict[str, Any]] = None
    ) -> TierExposureReportData:
        """Compute the tier exposure report for a snapshot.

        Parameters
        ----------
        snapshot : dict, optional
            Source snapshot.  When ``None``, :meth:`load_latest_snapshot` is used.

        Returns
        -------
        TierExposureReportData
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

        # Group contributions by tier.
        groups: Dict[str, Dict[str, Any]] = {}
        total_allocated = 0.0
        portfolio_apy_weight_sum = 0.0  # sum apy * allocated (across all tiers)

        for item in contribs:
            if not isinstance(item, dict):
                continue
            adapter_id = item.get("adapter_id")
            allocated = _safe_float(item.get("allocated_usd", 0.0))
            weight = _safe_float(item.get("weight_pct", 0.0))
            apy = _safe_float(item.get("apy_pct", 0.0))
            annual_yield = _safe_float(item.get("annual_yield_usd", 0.0))

            total_allocated += allocated
            portfolio_apy_weight_sum += apy * allocated

            tier = _normalize_tier(item.get("tier"))
            grp = groups.setdefault(
                tier,
                {
                    "allocated_usd": 0.0,
                    "weight_pct": 0.0,
                    "annual_yield_usd": 0.0,
                    "adapters": set(),
                    "apy_weight_sum": 0.0,  # sum apy * allocated (this tier)
                    "apy_capital": 0.0,     # sum allocated (this tier)
                },
            )
            grp["allocated_usd"] += allocated
            grp["weight_pct"] += weight
            grp["annual_yield_usd"] += annual_yield
            if isinstance(adapter_id, str) and adapter_id:
                grp["adapters"].add(adapter_id)
            grp["apy_weight_sum"] += apy * allocated
            grp["apy_capital"] += allocated

        exposures: List[TierExposure] = []
        for tier, grp in groups.items():
            cap = grp["apy_capital"]
            avg_apy = (grp["apy_weight_sum"] / cap) if cap > 0 else 0.0
            adapters_sorted = sorted(grp["adapters"])
            weight_pct = grp["weight_pct"]

            cap_pct = POLICY_CAPS.get(tier)
            if cap_pct is None:
                within_cap = True
                headroom = None
            else:
                within_cap = weight_pct <= cap_pct
                headroom = cap_pct - weight_pct

            exposures.append(
                TierExposure(
                    tier=tier,
                    allocated_usd=grp["allocated_usd"],
                    weight_pct=weight_pct,
                    adapter_count=len(adapters_sorted),
                    adapters=adapters_sorted,
                    avg_apy_pct=avg_apy,
                    annual_yield_usd=grp["annual_yield_usd"],
                    cap_pct=cap_pct,
                    within_cap=within_cap,
                    headroom_pct=headroom,
                )
            )

        # Sort by TIER_ORDER for stable output.
        exposures.sort(key=lambda e: self._tier_sort_key(e.tier))

        # HHI = sum (weight_pct / 100)^2 across tiers.
        hhi = sum((e.weight_pct / 100.0) ** 2 for e in exposures)

        # Dominant tier = max weight_pct (stable tiebreak by TIER_ORDER).
        dominant_tier = ""
        dominant_weight = 0.0
        if exposures:
            dom = max(
                exposures,
                key=lambda e: (e.weight_pct, -self._tier_sort_key(e.tier)[0]),
            )
            dominant_tier = dom.tier
            dominant_weight = dom.weight_pct

        concentration_label = self._concentration_label(hhi)

        # Policy compliance.
        breaches: List[str] = []
        for e in exposures:
            if e.cap_pct is not None and not e.within_cap:
                breaches.append(
                    f"{e.tier} {e.weight_pct:.1f}% > cap {e.cap_pct:.1f}%"
                )
        policy_status = "COMPLIANT" if not breaches else "BREACH"

        # Portfolio APY (capital-weighted across all tiers).
        portfolio_apy = (
            portfolio_apy_weight_sum / total_allocated
            if total_allocated > 0
            else 0.0
        )

        # Convenience tier-weight fields.
        weight_by_tier = {e.tier: e.weight_pct for e in exposures}
        t1_weight = weight_by_tier.get("T1", 0.0)
        t2_weight = weight_by_tier.get("T2", 0.0)
        t3_weight = weight_by_tier.get("T3", 0.0)

        recommendations = self._build_recommendations(
            exposures=exposures,
            breaches=breaches,
            concentration_label=concentration_label,
            weight_by_tier=weight_by_tier,
        )

        summary = (
            f"Tiers: T1 {t1_weight:.1f}% / T2 {t2_weight:.1f}% / "
            f"T3 {t3_weight:.1f}%, HHI={hhi:.3f}, policy {policy_status}"
        )

        return TierExposureReportData(
            generated_at=datetime.now(timezone.utc).isoformat(),
            snapshot_at=snapshot_at,
            total_allocated_usd=total_allocated,
            total_tiers=len(exposures),
            exposures=exposures,
            dominant_tier=dominant_tier,
            dominant_weight_pct=dominant_weight,
            hhi=hhi,
            concentration_label=concentration_label,
            policy_status=policy_status,
            breaches=breaches,
            portfolio_apy_pct=portfolio_apy,
            t1_weight_pct=t1_weight,
            t2_weight_pct=t2_weight,
            t3_weight_pct=t3_weight,
            recommendations=recommendations,
            summary=summary,
        )

    def _build_recommendations(
        self,
        exposures: List[TierExposure],
        breaches: List[str],
        concentration_label: str,
        weight_by_tier: Dict[str, float],
    ) -> List[str]:
        """Build advisory recommendation lines."""
        recs: List[str] = []

        # Cap breaches.
        for e in exposures:
            if e.cap_pct is None or e.within_cap:
                continue
            if e.tier == "T2":
                recs.append("Reduce T2 allocation below 50% cap (ADR-019)")
            elif e.tier == "T3":
                recs.append(
                    "Reduce T3 (speculative) below 15% cap (ADR-020)"
                )
            else:
                recs.append(
                    f"Reduce {e.tier} {e.weight_pct:.1f}% below cap "
                    f"{e.cap_pct:.1f}%"
                )

        # Unknown-tier capital present.
        unknown_weight = weight_by_tier.get(_UNKNOWN, 0.0)
        if unknown_weight > 0:
            recs.append(
                f"Classify UNKNOWN-tier adapters ({unknown_weight:.1f}% of AUM)"
            )

        # Concentration note.
        if concentration_label == "CONCENTRATED":
            recs.append(
                "Tier concentration high (HHI>0.5) -- consider diversifying "
                "across risk tiers"
            )

        if not recs:
            recs.append("Tier exposure within policy and well diversified")
        return recs

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def save_report(
        self, report: Optional[TierExposureReportData] = None
    ) -> str:
        """Atomically save the report, maintaining a ring-buffer of 30.

        Parameters
        ----------
        report : TierExposureReportData, optional
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
            "source": "tier_exposure_report",
            "ring_buffer_max": self.RING_BUFFER_SIZE,
            "report_count": len(history),
            "last_updated": report_dict["generated_at"],
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
        self, report: Optional[TierExposureReportData] = None
    ) -> str:
        """Format a Telegram-ready message (<=1500 chars)."""
        if report is None:
            report = self.compute_exposures()

        if report.total_tiers == 0:
            return "🏛 Tier Exposure\nNo allocation data available."[:1500]

        lines: List[str] = ["🏛 Tier Exposure"]

        for exp in report.exposures:
            if exp.cap_pct is not None:
                cap_note = (
                    f"cap {exp.cap_pct:.0f}%, headroom "
                    f"{exp.headroom_pct:.1f}%"
                    if exp.headroom_pct is not None
                    else f"cap {exp.cap_pct:.0f}%"
                )
                lines.append(
                    f"  {exp.tier}: {exp.weight_pct:.1f}% ({cap_note})"
                )
            else:
                lines.append(
                    f"  {exp.tier}: {exp.weight_pct:.1f}% (no cap)"
                )

        lines.append(
            f"HHI: {report.hhi:.3f} ({report.concentration_label})"
        )

        if report.policy_status == "COMPLIANT":
            lines.append("✅ Policy: COMPLIANT")
        else:
            lines.append("⚠️ Policy: BREACH")
            for b in report.breaches:
                lines.append(f"  - {b}")

        lines.append(f"Portfolio APY: {report.portfolio_apy_pct:.2f}%")
        lines.append(f"t {report.snapshot_at or report.generated_at}")

        msg = "\n".join(lines)
        return msg[:1500]

    def to_dict(
        self, report: Optional[TierExposureReportData] = None
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
            "SPA Tier Exposure Report (MP-617) -- aggregate portfolio "
            "exposure by risk tier (T1/T2/T3), HHI concentration, "
            "ADR-019/ADR-020 policy compliance."
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
        help="Compute and atomically save to data/tier_exposure.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help="Data directory path.",
    )
    args = parser.parse_args(argv)

    reporter = TierExposureReport(data_path=args.data_dir)
    report = reporter.compute_exposures()

    print("=== Tier Exposure Report (MP-617) ===")
    print(f"Generated:        {report.generated_at}")
    print(f"Snapshot:         {report.snapshot_at or 'n/a'}")
    print(f"Total allocated:  ${report.total_allocated_usd:,.2f}")
    print(f"Tiers:            {report.total_tiers}")
    print(f"Dominant:         {report.dominant_tier or 'n/a'} "
          f"({report.dominant_weight_pct:.2f}%)")
    print(f"HHI:              {report.hhi:.4f} ({report.concentration_label})")
    print(f"Policy status:    {report.policy_status}")
    print(f"Portfolio APY:    {report.portfolio_apy_pct:.4f}%")
    print(f"T1/T2/T3 weight:  {report.t1_weight_pct:.2f}% / "
          f"{report.t2_weight_pct:.2f}% / {report.t3_weight_pct:.2f}%")
    print(f"Summary:          {report.summary}")
    print()

    if report.exposures:
        print("Exposures:")
        for exp in report.exposures:
            cap_str = (
                f"cap {exp.cap_pct:.1f}%"
                if exp.cap_pct is not None
                else "no cap"
            )
            print(
                f"  {exp.tier:>8s}  {exp.weight_pct:6.2f}%  "
                f"${exp.allocated_usd:>14,.2f}  "
                f"apy {exp.avg_apy_pct:5.2f}%  "
                f"{cap_str}  "
                f"within={exp.within_cap}  "
                f"adapters={exp.adapters}"
            )
        print()

    if report.breaches:
        print("Breaches:")
        for b in report.breaches:
            print(f"  ! {b}")
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
