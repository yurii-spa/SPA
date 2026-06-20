"""Chain Exposure Report (MP-620).

Advisory / read-only analytics module: aggregates portfolio exposure by
BLOCKCHAIN (ethereum / arbitrum / base / optimism / polygon / UNKNOWN),
computes per-chain concentration (HHI), checks compliance with the chain
concentration cap policy (MP-387 concern: ethereum <= 70% AUM), computes
chain-weighted APY, flags L2 exposure, and produces a Telegram summary.

The chain of each adapter is read directly from the source ``chain`` field of
each contribution; missing / empty chains resolve to "UNKNOWN".

This is the third slice module of the same source
``data/yield_attribution_tracker.json`` -- alongside
``stablecoin_exposure_report.py`` (slice by underlying stablecoin) and
``tier_exposure_report.py`` (slice by risk tier).  This one slices by chain.

Design constraints (SPA-BL-011)
-------------------------------
* Pure stdlib -- no numpy/pandas/requests/web3/openai, no pip deps.
* Advisory / read-only -- never touches allocator / risk / execution / monitoring.
* Atomic writes -- tmp + os.replace on every JSON update; no .tmp leftovers.
* Fail-safe reads -- missing / corrupt / non-dict JSON -> empty result, never raises.
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.chain_exposure_report --check
    python3 -m spa_core.analytics.chain_exposure_report --run
    python3 -m spa_core.analytics.chain_exposure_report --run --data-dir /path/to/data

MP-620.
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

# Layer-2 chains (vs ethereum L1).
L2_CHAINS = {"arbitrum", "base", "optimism", "polygon"}

# Chain concentration cap (% of AUM). Only ethereum has a cap (MP-387):
#   ethereum <= 70% AUM
CHAIN_CONCENTRATION_CAP: Dict[str, float] = {"ethereum": 70.0}

# Stable ordering for sorting / output.
CHAIN_ORDER: List[str] = [
    "ethereum",
    "arbitrum",
    "base",
    "optimism",
    "polygon",
    "UNKNOWN",
]

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


def _normalize_chain(chain: Any) -> str:
    """Normalise a raw chain value to a lowercase chain id or "UNKNOWN"."""
    if isinstance(chain, str):
        c = chain.strip().lower()
        if c:
            return c
    return _UNKNOWN


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ChainExposure:
    """Exposure aggregate for a single blockchain.

    Attributes
    ----------
    chain          : Chain id (e.g. "ethereum", "arbitrum", "UNKNOWN").
    allocated_usd  : Total allocated capital on this chain.
    weight_pct     : Sum of contribution weight_pct for this chain.
    adapter_count  : Number of distinct adapters on this chain.
    adapters       : Sorted list of distinct adapter_ids.
    avg_apy_pct    : allocated_usd-weighted APY; 0.0 when no capital.
    annual_yield_usd : Sum of annual_yield_usd for this chain.
    is_l2          : True when the chain is a known L2 chain.
    cap_pct        : Policy cap (% AUM) for this chain, or None (no cap).
    within_cap     : True if cap_pct is None or weight_pct <= cap_pct.
    headroom_pct   : cap_pct - weight_pct, or None when no cap.
    """

    chain: str
    allocated_usd: float
    weight_pct: float
    adapter_count: int
    adapters: List[str] = field(default_factory=list)
    avg_apy_pct: float = 0.0
    annual_yield_usd: float = 0.0
    is_l2: bool = False
    cap_pct: Optional[float] = None
    within_cap: bool = True
    headroom_pct: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "chain": self.chain,
            "allocated_usd": round(self.allocated_usd, 2),
            "weight_pct": round(self.weight_pct, 4),
            "adapter_count": self.adapter_count,
            "adapters": list(self.adapters),
            "avg_apy_pct": round(self.avg_apy_pct, 4),
            "annual_yield_usd": round(self.annual_yield_usd, 2),
            "is_l2": self.is_l2,
            "cap_pct": self.cap_pct,
            "within_cap": self.within_cap,
            "headroom_pct": (
                round(self.headroom_pct, 4)
                if self.headroom_pct is not None
                else None
            ),
        }


@dataclass
class ChainExposureReportData:
    """Full chain exposure report.

    Attributes
    ----------
    generated_at        : ISO-8601 UTC timestamp when this report was produced.
    snapshot_at         : ``generated_at`` of the source snapshot used.
    total_allocated_usd : Sum of allocated_usd across contributions.
    total_chains        : Number of distinct chain groups.
    exposures           : Per-chain exposures, sorted by CHAIN_ORDER.
    dominant_chain      : Chain with the largest weight_pct ("" when empty).
    dominant_weight_pct : Largest weight_pct value (0.0 when empty).
    hhi                 : Herfindahl-Hirschman Index = sum (weight/100)^2.
    concentration_label : "CONCENTRATED" / "MODERATE" / "DIVERSIFIED".
    policy_status       : "COMPLIANT" / "BREACH".
    breaches            : Human-readable breach strings.
    portfolio_apy_pct   : Capital-weighted APY across all chains.
    l2_weight_pct       : Sum of weight_pct across L2 chains.
    ethereum_weight_pct : Convenience: ethereum weight_pct (0.0 if absent).
    recommendations     : Advisory text lines.
    summary             : One-line human-readable summary.
    """

    generated_at: str
    snapshot_at: str
    total_allocated_usd: float
    total_chains: int
    exposures: List[ChainExposure] = field(default_factory=list)
    dominant_chain: str = ""
    dominant_weight_pct: float = 0.0
    hhi: float = 0.0
    concentration_label: str = "DIVERSIFIED"
    policy_status: str = "COMPLIANT"
    breaches: List[str] = field(default_factory=list)
    portfolio_apy_pct: float = 0.0
    l2_weight_pct: float = 0.0
    ethereum_weight_pct: float = 0.0
    recommendations: List[str] = field(default_factory=list)
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "generated_at": self.generated_at,
            "snapshot_at": self.snapshot_at,
            "total_allocated_usd": round(self.total_allocated_usd, 2),
            "total_chains": self.total_chains,
            "exposures": [e.to_dict() for e in self.exposures],
            "dominant_chain": self.dominant_chain,
            "dominant_weight_pct": round(self.dominant_weight_pct, 4),
            "hhi": round(self.hhi, 6),
            "concentration_label": self.concentration_label,
            "policy_status": self.policy_status,
            "breaches": list(self.breaches),
            "portfolio_apy_pct": round(self.portfolio_apy_pct, 4),
            "l2_weight_pct": round(self.l2_weight_pct, 4),
            "ethereum_weight_pct": round(self.ethereum_weight_pct, 4),
            "recommendations": list(self.recommendations),
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# ChainExposureReport
# ---------------------------------------------------------------------------


class ChainExposureReport:
    """Aggregate portfolio exposure by blockchain (ethereum / L2 / UNKNOWN).

    Parameters
    ----------
    data_path : str or Path, optional
        Directory containing the source tracker and where the output is
        written.  Defaults to the repo ``data/`` directory.
    """

    SOURCE_FILE: str = "yield_attribution_tracker.json"
    OUTPUT_FILE: str = "chain_exposure.json"
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

    def _empty_report(self, snapshot_at: str = "") -> ChainExposureReportData:
        """Build a meaningful empty report (no contributions)."""
        now_str = datetime.now(timezone.utc).isoformat()
        return ChainExposureReportData(
            generated_at=now_str,
            snapshot_at=snapshot_at,
            total_allocated_usd=0.0,
            total_chains=0,
            exposures=[],
            dominant_chain="",
            dominant_weight_pct=0.0,
            hhi=0.0,
            concentration_label="DIVERSIFIED",
            policy_status="COMPLIANT",
            breaches=[],
            portfolio_apy_pct=0.0,
            l2_weight_pct=0.0,
            ethereum_weight_pct=0.0,
            recommendations=["No allocation data available -- nothing to assess."],
            summary="Chain exposure: no data available",
        )

    def _chain_sort_key(self, chain: str) -> tuple:
        """Sort key honouring CHAIN_ORDER; unknown chains sorted after, by name."""
        try:
            idx = CHAIN_ORDER.index(chain)
        except ValueError:
            # Unknown chains: after known order but before the literal UNKNOWN
            # bucket which is last in CHAIN_ORDER.
            idx = len(CHAIN_ORDER) - 0.5
        return (idx, chain)

    def compute_exposures(
        self, snapshot: Optional[Dict[str, Any]] = None
    ) -> ChainExposureReportData:
        """Compute the chain exposure report for a snapshot.

        Parameters
        ----------
        snapshot : dict, optional
            Source snapshot.  When ``None``, :meth:`load_latest_snapshot` is used.

        Returns
        -------
        ChainExposureReportData
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

        # Group contributions by chain.
        groups: Dict[str, Dict[str, Any]] = {}
        total_allocated = 0.0
        portfolio_apy_weight_sum = 0.0  # sum apy * allocated (across all chains)

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

            chain = _normalize_chain(item.get("chain"))
            grp = groups.setdefault(
                chain,
                {
                    "allocated_usd": 0.0,
                    "weight_pct": 0.0,
                    "annual_yield_usd": 0.0,
                    "adapters": set(),
                    "apy_weight_sum": 0.0,  # sum apy * allocated (this chain)
                    "apy_capital": 0.0,     # sum allocated (this chain)
                },
            )
            grp["allocated_usd"] += allocated
            grp["weight_pct"] += weight
            grp["annual_yield_usd"] += annual_yield
            if isinstance(adapter_id, str) and adapter_id:
                grp["adapters"].add(adapter_id)
            grp["apy_weight_sum"] += apy * allocated
            grp["apy_capital"] += allocated

        exposures: List[ChainExposure] = []
        for chain, grp in groups.items():
            cap = grp["apy_capital"]
            avg_apy = (grp["apy_weight_sum"] / cap) if cap > 0 else 0.0
            adapters_sorted = sorted(grp["adapters"])
            weight_pct = grp["weight_pct"]
            is_l2 = chain in L2_CHAINS

            cap_pct = CHAIN_CONCENTRATION_CAP.get(chain)
            if cap_pct is None:
                within_cap = True
                headroom = None
            else:
                within_cap = weight_pct <= cap_pct
                headroom = cap_pct - weight_pct

            exposures.append(
                ChainExposure(
                    chain=chain,
                    allocated_usd=grp["allocated_usd"],
                    weight_pct=weight_pct,
                    adapter_count=len(adapters_sorted),
                    adapters=adapters_sorted,
                    avg_apy_pct=avg_apy,
                    annual_yield_usd=grp["annual_yield_usd"],
                    is_l2=is_l2,
                    cap_pct=cap_pct,
                    within_cap=within_cap,
                    headroom_pct=headroom,
                )
            )

        # Sort by CHAIN_ORDER for stable output (UNKNOWN last).
        exposures.sort(key=lambda e: self._chain_sort_key(e.chain))

        # HHI = sum (weight_pct / 100)^2 across chains.
        hhi = sum((e.weight_pct / 100.0) ** 2 for e in exposures)

        # Dominant chain = max weight_pct (stable tiebreak by CHAIN_ORDER).
        dominant_chain = ""
        dominant_weight = 0.0
        if exposures:
            dom = max(
                exposures,
                key=lambda e: (e.weight_pct, -self._chain_sort_key(e.chain)[0]),
            )
            dominant_chain = dom.chain
            dominant_weight = dom.weight_pct

        concentration_label = self._concentration_label(hhi)

        # Policy compliance.
        breaches: List[str] = []
        for e in exposures:
            if e.cap_pct is not None and not e.within_cap:
                breaches.append(
                    f"{e.chain} {e.weight_pct:.1f}% > cap {e.cap_pct:.1f}%"
                )
        policy_status = "COMPLIANT" if not breaches else "BREACH"

        # Portfolio APY (capital-weighted across all chains).
        portfolio_apy = (
            portfolio_apy_weight_sum / total_allocated
            if total_allocated > 0
            else 0.0
        )

        # Convenience chain-weight fields.
        weight_by_chain = {e.chain: e.weight_pct for e in exposures}
        ethereum_weight = weight_by_chain.get("ethereum", 0.0)
        l2_weight = sum(e.weight_pct for e in exposures if e.is_l2)

        recommendations = self._build_recommendations(
            exposures=exposures,
            breaches=breaches,
            concentration_label=concentration_label,
            hhi=hhi,
            l2_weight=l2_weight,
            weight_by_chain=weight_by_chain,
        )

        summary = (
            f"Chains: ethereum {ethereum_weight:.1f}% / L2 {l2_weight:.1f}%, "
            f"HHI={hhi:.3f}, policy {policy_status}"
        )

        return ChainExposureReportData(
            generated_at=datetime.now(timezone.utc).isoformat(),
            snapshot_at=snapshot_at,
            total_allocated_usd=total_allocated,
            total_chains=len(exposures),
            exposures=exposures,
            dominant_chain=dominant_chain,
            dominant_weight_pct=dominant_weight,
            hhi=hhi,
            concentration_label=concentration_label,
            policy_status=policy_status,
            breaches=breaches,
            portfolio_apy_pct=portfolio_apy,
            l2_weight_pct=l2_weight,
            ethereum_weight_pct=ethereum_weight,
            recommendations=recommendations,
            summary=summary,
        )

    def _build_recommendations(
        self,
        exposures: List[ChainExposure],
        breaches: List[str],
        concentration_label: str,
        hhi: float,
        l2_weight: float,
        weight_by_chain: Dict[str, float],
    ) -> List[str]:
        """Build advisory recommendation lines."""
        recs: List[str] = []

        # Chain cap breaches (ethereum).
        for e in exposures:
            if e.cap_pct is None or e.within_cap:
                continue
            if e.chain == "ethereum":
                recs.append(
                    "Reduce ethereum exposure below 70% cap (MP-387) -- "
                    "consider diversifying onto L2 chains"
                )
            else:
                recs.append(
                    f"Reduce {e.chain} {e.weight_pct:.1f}% below cap "
                    f"{e.cap_pct:.1f}%"
                )

        # High chain concentration.
        if concentration_label == "CONCENTRATED":
            recs.append(
                "Chain concentration high (HHI>0.5) -- consider spreading "
                "capital across more chains"
            )

        # No L2 diversification.
        if l2_weight <= 0.0:
            recs.append(
                "No L2 exposure -- consider Arbitrum/Base/Optimism/Polygon "
                "for chain diversification"
            )

        # Unknown-chain capital present.
        unknown_weight = weight_by_chain.get(_UNKNOWN, 0.0)
        if unknown_weight > 0:
            recs.append(
                f"Classify UNKNOWN-chain adapters ({unknown_weight:.1f}% of AUM)"
            )

        if not recs:
            recs.append("Chain exposure within policy and well diversified")
        return recs

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def save_report(
        self, report: Optional[ChainExposureReportData] = None
    ) -> str:
        """Atomically save the report, maintaining a ring-buffer of 30.

        Parameters
        ----------
        report : ChainExposureReportData, optional
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
            "source": "chain_exposure_report",
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
        self, report: Optional[ChainExposureReportData] = None
    ) -> str:
        """Format a Telegram-ready message (<=1500 chars)."""
        if report is None:
            report = self.compute_exposures()

        if report.total_chains == 0:
            return "🌐 Chain Exposure\nNo allocation data available."[:1500]

        lines: List[str] = ["🌐 Chain Exposure"]

        for exp in report.exposures:
            if exp.chain == "ethereum" and exp.cap_pct is not None:
                cap_note = (
                    f"cap {exp.cap_pct:.0f}%, headroom "
                    f"{exp.headroom_pct:.1f}%"
                    if exp.headroom_pct is not None
                    else f"cap {exp.cap_pct:.0f}%"
                )
                lines.append(
                    f"  {exp.chain}: {exp.weight_pct:.1f}% ({cap_note})"
                )
            else:
                tag = " [L2]" if exp.is_l2 else ""
                lines.append(
                    f"  {exp.chain}{tag}: {exp.weight_pct:.1f}%"
                )

        lines.append(f"L2 weight: {report.l2_weight_pct:.1f}%")
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
        self, report: Optional[ChainExposureReportData] = None
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
            "SPA Chain Exposure Report (MP-620) -- aggregate portfolio "
            "exposure by blockchain (ethereum/L2), HHI concentration, "
            "ethereum<=70% cap policy (MP-387)."
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
        help="Compute and atomically save to data/chain_exposure.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help="Data directory path.",
    )
    args = parser.parse_args(argv)

    reporter = ChainExposureReport(data_path=args.data_dir)
    report = reporter.compute_exposures()

    print("=== Chain Exposure Report (MP-620) ===")
    print(f"Generated:        {report.generated_at}")
    print(f"Snapshot:         {report.snapshot_at or 'n/a'}")
    print(f"Total allocated:  ${report.total_allocated_usd:,.2f}")
    print(f"Chains:           {report.total_chains}")
    print(f"Dominant:         {report.dominant_chain or 'n/a'} "
          f"({report.dominant_weight_pct:.2f}%)")
    print(f"HHI:              {report.hhi:.4f} ({report.concentration_label})")
    print(f"Policy status:    {report.policy_status}")
    print(f"Portfolio APY:    {report.portfolio_apy_pct:.4f}%")
    print(f"Ethereum/L2 wt:   {report.ethereum_weight_pct:.2f}% / "
          f"{report.l2_weight_pct:.2f}%")
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
                f"  {exp.chain:>10s}  {exp.weight_pct:6.2f}%  "
                f"${exp.allocated_usd:>14,.2f}  "
                f"apy {exp.avg_apy_pct:5.2f}%  "
                f"l2={exp.is_l2}  "
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
