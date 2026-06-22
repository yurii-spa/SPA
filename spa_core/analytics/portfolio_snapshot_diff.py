"""Portfolio Snapshot Diff (MP-609).

Сравнивает два последовательных снапшота портфеля из yield_attribution_tracker.json
и показывает что изменилось: какие адаптеры добавились/убрались,
как изменились веса и APY.

Design constraints
------------------
* Pure stdlib — no external deps.
* Advisory / read-only — never touches allocator / risk / execution.
* Atomic writes — tmp + os.replace on every JSON update.
* LLM_FORBIDDEN domain: NOT imported from risk / execution / monitoring.
* exit(0) always from CLI.

CLI
---
    python3 -m spa_core.analytics.portfolio_snapshot_diff --check
    python3 -m spa_core.analytics.portfolio_snapshot_diff --run
    python3 -m spa_core.analytics.portfolio_snapshot_diff --run --data-dir /path/to/data
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from spa_core.utils.atomic import atomic_save

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REPO_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_DATA_DIR = _REPO_ROOT / "data"
_TRACKER_FILENAME = "yield_attribution_tracker.json"
_OUTPUT_FILENAME = "snapshot_diff.json"
_RING_BUFFER_MAX = 30


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


@dataclass
class AdapterChange:
    """Change record for a single adapter between two snapshots.

    Attributes
    ----------
    adapter_key     : Adapter identifier (matches adapter_id in contributions).
    change_type     : One of "added" / "removed" / "weight_up" / "weight_down" /
                      "apy_up" / "apy_down" / "unchanged".
    old_weight_pct  : Portfolio weight % in old snapshot; None if adapter was absent.
    new_weight_pct  : Portfolio weight % in new snapshot; None if adapter was absent.
    old_apy_pct     : APY % in old snapshot; None if adapter was absent.
    new_apy_pct     : APY % in new snapshot; None if adapter was absent.
    weight_delta    : new_weight - old_weight (0.0 when adapter is added or removed).
    apy_delta       : new_apy - old_apy (0.0 when adapter is added or removed).
    is_significant  : True when |weight_delta| > 1.0 % OR |apy_delta| > 0.1 %.
    """

    adapter_key: str
    change_type: str
    old_weight_pct: Optional[float]
    new_weight_pct: Optional[float]
    old_apy_pct: Optional[float]
    new_apy_pct: Optional[float]
    weight_delta: float
    apy_delta: float
    is_significant: bool

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "adapter_key": self.adapter_key,
            "change_type": self.change_type,
            "old_weight_pct": self.old_weight_pct,
            "new_weight_pct": self.new_weight_pct,
            "old_apy_pct": self.old_apy_pct,
            "new_apy_pct": self.new_apy_pct,
            "weight_delta": round(self.weight_delta, 6),
            "apy_delta": round(self.apy_delta, 6),
            "is_significant": self.is_significant,
        }


@dataclass
class PortfolioDiff:
    """Full diff report between two consecutive portfolio snapshots.

    Attributes
    ----------
    generated_at        : ISO-8601 UTC timestamp when this diff was produced.
    snapshot_old_at     : ``generated_at`` of the older snapshot.
    snapshot_new_at     : ``generated_at`` of the newer snapshot.
    hours_apart         : Time between snapshots in hours.
    old_portfolio_apy   : ``effective_apy_pct`` of old snapshot.
    new_portfolio_apy   : ``effective_apy_pct`` of new snapshot.
    apy_delta           : new - old portfolio APY (pp).
    old_allocated_usd   : Total allocated capital in old snapshot.
    new_allocated_usd   : Total allocated capital in new snapshot.
    allocated_delta_usd : new - old allocated USD.
    changes             : Per-adapter change records.
    added_adapters      : adapter_keys that appeared in new but not old.
    removed_adapters    : adapter_keys that were in old but not new.
    significant_changes : adapter_keys with is_significant == True.
    total_adapters_old  : Count of adapters in old snapshot.
    total_adapters_new  : Count of adapters in new snapshot.
    unchanged_count     : Count of adapters with change_type == "unchanged".
    changed_count       : Count of adapters with any non-"unchanged" change_type.
    trend               : "IMPROVING" / "STABLE" / "DECLINING" based on apy_delta.
    summary             : One-line human-readable summary.
    """

    generated_at: str
    snapshot_old_at: str
    snapshot_new_at: str
    hours_apart: float

    old_portfolio_apy: float
    new_portfolio_apy: float
    apy_delta: float

    old_allocated_usd: float
    new_allocated_usd: float
    allocated_delta_usd: float

    changes: List[AdapterChange] = field(default_factory=list)
    added_adapters: List[str] = field(default_factory=list)
    removed_adapters: List[str] = field(default_factory=list)
    significant_changes: List[str] = field(default_factory=list)

    total_adapters_old: int = 0
    total_adapters_new: int = 0
    unchanged_count: int = 0
    changed_count: int = 0

    trend: str = "STABLE"
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serialisable dict."""
        return {
            "generated_at": self.generated_at,
            "snapshot_old_at": self.snapshot_old_at,
            "snapshot_new_at": self.snapshot_new_at,
            "hours_apart": round(self.hours_apart, 4),
            "old_portfolio_apy": self.old_portfolio_apy,
            "new_portfolio_apy": self.new_portfolio_apy,
            "apy_delta": round(self.apy_delta, 6),
            "old_allocated_usd": self.old_allocated_usd,
            "new_allocated_usd": self.new_allocated_usd,
            "allocated_delta_usd": round(self.allocated_delta_usd, 2),
            "changes": [c.to_dict() for c in self.changes],
            "added_adapters": self.added_adapters,
            "removed_adapters": self.removed_adapters,
            "significant_changes": self.significant_changes,
            "total_adapters_old": self.total_adapters_old,
            "total_adapters_new": self.total_adapters_new,
            "unchanged_count": self.unchanged_count,
            "changed_count": self.changed_count,
            "trend": self.trend,
            "summary": self.summary,
        }


# ---------------------------------------------------------------------------
# PortfolioSnapshotDiff
# ---------------------------------------------------------------------------


class PortfolioSnapshotDiff:
    """Compare two consecutive portfolio snapshots from yield_attribution_tracker.json.

    Parameters
    ----------
    data_path : str or Path, optional
        Directory containing ``yield_attribution_tracker.json`` and where
        ``snapshot_diff.json`` is written.  Defaults to the repo ``data/``
        directory.
    """

    SIGNIFICANT_WEIGHT_THRESHOLD: float = 1.0   # percentage points
    SIGNIFICANT_APY_THRESHOLD: float = 0.1       # percentage points
    APY_TREND_THRESHOLD: float = 0.1             # percentage points

    def __init__(self, data_path: Optional[str] = None) -> None:
        if data_path is None:
            self.data_dir = _DEFAULT_DATA_DIR
        else:
            self.data_dir = Path(data_path)

    # -----------------------------------------------------------------------
    # Data loading
    # -----------------------------------------------------------------------

    def load_snapshots(self) -> List[Dict[str, Any]]:
        """Load snapshots from yield_attribution_tracker.json.

        The file stores snapshots in a ring-buffer list under ``"snapshots"``
        with the newest entry last.  Returns an empty list when the file is
        missing, unreadable, or contains no snapshots.

        Returns
        -------
        list of dict
            Up to the last 30 snapshot dicts (newest last).
        """
        tracker_path = self.data_dir / _TRACKER_FILENAME
        if not tracker_path.exists():
            return []
        try:
            raw = json.loads(tracker_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return []
        if not isinstance(raw, dict):
            return []

        snapshots_raw = raw.get("snapshots")
        if not isinstance(snapshots_raw, list):
            return []

        result = [s for s in snapshots_raw if isinstance(s, dict)]
        # Guard: never exceed ring-buffer size in memory
        return result[-_RING_BUFFER_MAX:]

    def get_last_two(self) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        """Return the two most recent snapshots (old, new).

        Raises
        ------
        ValueError
            When fewer than 2 snapshots are available.
        """
        snapshots = self.load_snapshots()
        if len(snapshots) < 2:
            raise ValueError(
                f"Need at least 2 snapshots to compute a diff; "
                f"found {len(snapshots)}."
            )
        return snapshots[-2], snapshots[-1]

    # -----------------------------------------------------------------------
    # Core diff logic
    # -----------------------------------------------------------------------

    def diff_adapters(
        self,
        old_snap: Dict[str, Any],
        new_snap: Dict[str, Any],
    ) -> List[AdapterChange]:
        """Compare per-adapter contributions between two snapshots.

        Reads ``old_snap["contributions"]`` and ``new_snap["contributions"]``
        (each a list of dicts with ``adapter_id``, ``weight_pct``, ``apy_pct``).
        Produces one :class:`AdapterChange` per adapter in the union of both sets.

        change_type selection (priority order):
        1. "added"       — present in new, absent in old.
        2. "removed"     — present in old, absent in new.
        3. "weight_up"   — |weight_delta| > threshold and weight_delta > 0.
        4. "weight_down" — |weight_delta| > threshold and weight_delta < 0.
        5. "apy_up"      — |apy_delta| > threshold and apy_delta > 0.
        6. "apy_down"    — |apy_delta| > threshold and apy_delta < 0.
        7. "unchanged"   — no significant change.
        """

        def _contributions_map(
            snap: Dict[str, Any],
        ) -> Dict[str, Dict[str, float]]:
            """Build {adapter_id: {weight_pct, apy_pct}} from a snapshot."""
            result: Dict[str, Dict[str, float]] = {}
            contribs = snap.get("contributions")
            if not isinstance(contribs, list):
                return result
            for item in contribs:
                if not isinstance(item, dict):
                    continue
                key = item.get("adapter_id")
                if not isinstance(key, str) or not key:
                    continue
                try:
                    w = float(item.get("weight_pct", 0.0))
                    a = float(item.get("apy_pct", 0.0))
                except (TypeError, ValueError):
                    w, a = 0.0, 0.0
                result[key] = {"weight_pct": w, "apy_pct": a}
            return result

        old_map = _contributions_map(old_snap)
        new_map = _contributions_map(new_snap)

        all_keys = sorted(set(old_map) | set(new_map))
        changes: List[AdapterChange] = []

        for key in all_keys:
            in_old = key in old_map
            in_new = key in new_map

            if in_new and not in_old:
                # Added
                new_w = new_map[key]["weight_pct"]
                new_a = new_map[key]["apy_pct"]
                weight_delta = 0.0
                apy_delta = 0.0
                is_sig = False
                changes.append(AdapterChange(
                    adapter_key=key,
                    change_type="added",
                    old_weight_pct=None,
                    new_weight_pct=new_w,
                    old_apy_pct=None,
                    new_apy_pct=new_a,
                    weight_delta=weight_delta,
                    apy_delta=apy_delta,
                    is_significant=is_sig,
                ))
                continue

            if in_old and not in_new:
                # Removed
                old_w = old_map[key]["weight_pct"]
                old_a = old_map[key]["apy_pct"]
                weight_delta = 0.0
                apy_delta = 0.0
                is_sig = False
                changes.append(AdapterChange(
                    adapter_key=key,
                    change_type="removed",
                    old_weight_pct=old_w,
                    new_weight_pct=None,
                    old_apy_pct=old_a,
                    new_apy_pct=None,
                    weight_delta=weight_delta,
                    apy_delta=apy_delta,
                    is_significant=is_sig,
                ))
                continue

            # Present in both — compute deltas
            old_w = old_map[key]["weight_pct"]
            new_w = new_map[key]["weight_pct"]
            old_a = old_map[key]["apy_pct"]
            new_a = new_map[key]["apy_pct"]
            weight_delta = new_w - old_w
            apy_delta = new_a - old_a

            is_sig = (
                abs(weight_delta) > self.SIGNIFICANT_WEIGHT_THRESHOLD
                or abs(apy_delta) > self.SIGNIFICANT_APY_THRESHOLD
            )

            if abs(weight_delta) > self.SIGNIFICANT_WEIGHT_THRESHOLD:
                change_type = "weight_up" if weight_delta > 0 else "weight_down"
            elif abs(apy_delta) > self.SIGNIFICANT_APY_THRESHOLD:
                change_type = "apy_up" if apy_delta > 0 else "apy_down"
            else:
                change_type = "unchanged"

            changes.append(AdapterChange(
                adapter_key=key,
                change_type=change_type,
                old_weight_pct=old_w,
                new_weight_pct=new_w,
                old_apy_pct=old_a,
                new_apy_pct=new_a,
                weight_delta=weight_delta,
                apy_delta=apy_delta,
                is_significant=is_sig,
            ))

        return changes

    def _parse_timestamp(self, ts: Any) -> Optional[datetime]:
        """Parse an ISO-8601 timestamp string to a UTC-aware datetime."""
        if not isinstance(ts, str) or not ts:
            return None
        try:
            normalized = ts.replace("Z", "+00:00")
            dt = datetime.fromisoformat(normalized)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, AttributeError):
            return None

    def compute_diff(
        self,
        old_snap: Optional[Dict[str, Any]] = None,
        new_snap: Optional[Dict[str, Any]] = None,
    ) -> PortfolioDiff:
        """Compute the diff between two snapshots.

        When ``old_snap`` and ``new_snap`` are both ``None`` (the default),
        loads the two most recent snapshots from disk via :meth:`get_last_two`.

        Parameters
        ----------
        old_snap : dict, optional
        new_snap : dict, optional

        Returns
        -------
        PortfolioDiff
        """
        if old_snap is None or new_snap is None:
            old_snap, new_snap = self.get_last_two()

        now_str = datetime.now(timezone.utc).isoformat()

        old_at = old_snap.get("generated_at", "")
        new_at = new_snap.get("generated_at", "")

        # Hours apart
        old_dt = self._parse_timestamp(old_at)
        new_dt = self._parse_timestamp(new_at)
        if old_dt is not None and new_dt is not None:
            hours_apart = abs((new_dt - old_dt).total_seconds()) / 3600.0
        else:
            hours_apart = 0.0

        # Portfolio APYs
        try:
            old_apy = float(old_snap.get("effective_apy_pct", 0.0))
        except (TypeError, ValueError):
            old_apy = 0.0
        try:
            new_apy = float(new_snap.get("effective_apy_pct", 0.0))
        except (TypeError, ValueError):
            new_apy = 0.0
        apy_delta = new_apy - old_apy

        # Allocated capital
        try:
            old_alloc = float(old_snap.get("total_allocated_usd", 0.0))
        except (TypeError, ValueError):
            old_alloc = 0.0
        try:
            new_alloc = float(new_snap.get("total_allocated_usd", 0.0))
        except (TypeError, ValueError):
            new_alloc = 0.0
        allocated_delta = new_alloc - old_alloc

        # Adapter changes
        changes = self.diff_adapters(old_snap, new_snap)

        added_adapters = [c.adapter_key for c in changes if c.change_type == "added"]
        removed_adapters = [c.adapter_key for c in changes if c.change_type == "removed"]
        significant_changes = [c.adapter_key for c in changes if c.is_significant]

        old_contribs = old_snap.get("contributions")
        new_contribs = new_snap.get("contributions")
        total_adapters_old = len(old_contribs) if isinstance(old_contribs, list) else 0
        total_adapters_new = len(new_contribs) if isinstance(new_contribs, list) else 0

        unchanged_count = sum(1 for c in changes if c.change_type == "unchanged")
        changed_count = len(changes) - unchanged_count

        # Trend
        if apy_delta > self.APY_TREND_THRESHOLD:
            trend = "IMPROVING"
        elif apy_delta < -self.APY_TREND_THRESHOLD:
            trend = "DECLINING"
        else:
            trend = "STABLE"

        # Summary
        sign = "+" if apy_delta >= 0 else ""
        parts = [
            f"APY {sign}{apy_delta:.2f}% ({old_apy:.2f}%→{new_apy:.2f}%)",
        ]
        if added_adapters:
            parts.append(f"{len(added_adapters)} adapter(s) added")
        if removed_adapters:
            parts.append(f"{len(removed_adapters)} adapter(s) removed")
        if significant_changes and not added_adapters and not removed_adapters:
            parts.append(f"{len(significant_changes)} significant change(s)")
        summary = ", ".join(parts)

        return PortfolioDiff(
            generated_at=now_str,
            snapshot_old_at=old_at,
            snapshot_new_at=new_at,
            hours_apart=round(hours_apart, 4),
            old_portfolio_apy=round(old_apy, 4),
            new_portfolio_apy=round(new_apy, 4),
            apy_delta=round(apy_delta, 6),
            old_allocated_usd=round(old_alloc, 2),
            new_allocated_usd=round(new_alloc, 2),
            allocated_delta_usd=round(allocated_delta, 2),
            changes=changes,
            added_adapters=added_adapters,
            removed_adapters=removed_adapters,
            significant_changes=significant_changes,
            total_adapters_old=total_adapters_old,
            total_adapters_new=total_adapters_new,
            unchanged_count=unchanged_count,
            changed_count=changed_count,
            trend=trend,
            summary=summary,
        )

    # -----------------------------------------------------------------------
    # Persistence
    # -----------------------------------------------------------------------

    def save_diff(
        self,
        diff: Optional[PortfolioDiff] = None,
        output_path: Optional[str] = None,
    ) -> str:
        """Atomically save the diff report, maintaining a ring-buffer of 30.

        Parameters
        ----------
        diff : PortfolioDiff, optional
            Pre-computed diff.  When ``None``, :meth:`compute_diff` is called.
        output_path : str, optional
            Full output file path.  Defaults to ``{data_dir}/snapshot_diff.json``.

        Returns
        -------
        str
            Absolute path of the written file.
        """
        if diff is None:
            diff = self.compute_diff()

        if output_path is None:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            out_path = self.data_dir / _OUTPUT_FILENAME
        else:
            out_path = Path(output_path)
            out_path.parent.mkdir(parents=True, exist_ok=True)

        # Load existing ring-buffer
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

        diff_dict = diff.to_dict()
        history.append(diff_dict)
        history = history[-_RING_BUFFER_MAX:]

        out: Dict[str, Any] = {
            "schema_version": "1.0",
            "source": "portfolio_snapshot_diff",
            "last_updated": diff_dict["generated_at"],
            "count": len(history),
            "latest": diff_dict,
            "history": history,
        }

        # Atomic write
        atomic_save(out, str(out_path))
        return str(out_path)

    # -----------------------------------------------------------------------
    # Output helpers
    # -----------------------------------------------------------------------

    def format_telegram_message(
        self, diff: Optional[PortfolioDiff] = None
    ) -> str:
        """Format a Telegram-ready diff message (≤1500 chars).

        Parameters
        ----------
        diff : PortfolioDiff, optional
            Pre-computed diff.  When ``None``, :meth:`compute_diff` is called.
        """
        if diff is None:
            diff = self.compute_diff()

        trend_emoji = {
            "IMPROVING": "📈",
            "STABLE": "➡️",
            "DECLINING": "📉",
        }.get(diff.trend, "❓")

        sign = "+" if diff.apy_delta >= 0 else ""
        capital_k_old = diff.old_allocated_usd / 1000.0
        capital_k_new = diff.new_allocated_usd / 1000.0

        lines = [
            f"📊 Portfolio Diff: {trend_emoji} {diff.trend}",
            f"APY: {diff.old_portfolio_apy:.2f}% → {diff.new_portfolio_apy:.2f}% "
            f"({sign}{diff.apy_delta:.2f}%)",
            f"Capital: ${capital_k_old:,.0f}K → ${capital_k_new:,.0f}K",
        ]

        if diff.added_adapters:
            lines.append("➕ Added: " + ", ".join(diff.added_adapters))
        else:
            lines.append("➕ Added: none")

        if diff.removed_adapters:
            lines.append("➖ Removed: " + ", ".join(diff.removed_adapters))
        else:
            lines.append("➖ Removed: none")

        if diff.significant_changes:
            # Show up to 5 significant changes with details
            sig_parts = []
            for c in diff.changes:
                if not c.is_significant:
                    continue
                if c.change_type == "weight_up":
                    sig_parts.append(
                        f"{c.adapter_key} (+{c.weight_delta:.1f}% weight)"
                    )
                elif c.change_type == "weight_down":
                    sig_parts.append(
                        f"{c.adapter_key} ({c.weight_delta:.1f}% weight)"
                    )
                elif c.change_type == "apy_up":
                    sig_parts.append(
                        f"{c.adapter_key} (+{c.apy_delta:.2f}% APY)"
                    )
                elif c.change_type == "apy_down":
                    sig_parts.append(
                        f"{c.adapter_key} ({c.apy_delta:.2f}% APY)"
                    )
                if len(sig_parts) >= 5:
                    break
            if sig_parts:
                lines.append("📈 Significant: " + "; ".join(sig_parts))
        else:
            lines.append("✅ No significant weight/APY changes")

        lines.append(
            f"Adapters: {diff.total_adapters_old} → {diff.total_adapters_new} "
            f"({diff.changed_count} changed, {diff.unchanged_count} unchanged)"
        )

        msg = "\n".join(lines)
        return msg[:1500]

    def to_dict(self, diff: Optional[PortfolioDiff] = None) -> Dict[str, Any]:
        """Return a JSON-serialisable dict of the diff.

        Parameters
        ----------
        diff : PortfolioDiff, optional
            Pre-computed diff.  When ``None``, :meth:`compute_diff` is called.
        """
        if diff is None:
            diff = self.compute_diff()
        return diff.to_dict()


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "SPA Portfolio Snapshot Diff (MP-609) — "
            "compare two consecutive yield attribution snapshots."
        )
    )
    parser.add_argument(
        "--check",
        action="store_true",
        default=True,
        help="Compute and print diff without writing (default).",
    )
    parser.add_argument(
        "--run",
        action="store_true",
        help="Compute and atomically save to data/snapshot_diff.json.",
    )
    parser.add_argument(
        "--data-dir",
        default=str(_DEFAULT_DATA_DIR),
        help="Data directory path.",
    )
    args = parser.parse_args(argv)

    differ = PortfolioSnapshotDiff(data_path=args.data_dir)

    try:
        diff = differ.compute_diff()
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 0

    print(f"Generated:        {diff.generated_at}")
    print(f"Old snapshot:     {diff.snapshot_old_at}")
    print(f"New snapshot:     {diff.snapshot_new_at}")
    print(f"Hours apart:      {diff.hours_apart:.2f}h")
    print(f"Trend:            {diff.trend}")
    print(f"APY:              {diff.old_portfolio_apy:.4f}% → "
          f"{diff.new_portfolio_apy:.4f}% (Δ{diff.apy_delta:+.4f}%)")
    print(f"Capital:          ${diff.old_allocated_usd:,.2f} → "
          f"${diff.new_allocated_usd:,.2f} "
          f"(Δ${diff.allocated_delta_usd:+,.2f})")
    print(f"Adapters old/new: {diff.total_adapters_old} / {diff.total_adapters_new}")
    print(f"Added:            {diff.added_adapters or 'none'}")
    print(f"Removed:          {diff.removed_adapters or 'none'}")
    print(f"Significant:      {diff.significant_changes or 'none'}")
    print(f"Changed/Unchanged:{diff.changed_count} / {diff.unchanged_count}")
    print(f"Summary:          {diff.summary}")
    print()

    if diff.changes:
        print("Adapter changes:")
        for c in diff.changes:
            if c.change_type != "unchanged":
                print(
                    f"  [{c.change_type:11s}] {c.adapter_key:<35s}  "
                    f"weight: {str(c.old_weight_pct):>8s} → {str(c.new_weight_pct):>8s}  "
                    f"apy: {str(c.old_apy_pct):>6s} → {str(c.new_apy_pct):>6s}"
                )

    if args.run:
        path = differ.save_diff(diff)
        print(f"\nSaved → {path}")

    return 0


if __name__ == "__main__":
    sys.exit(_main())
