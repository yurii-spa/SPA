"""
spa_core/analytics/source_acquisition_tracker.py

Tracks progress on acquiring real on-chain/API data for SOURCE_NEEDED protocols.
Each source has: status, priority, effort_days, owner (always "team"), notes.

Statuses: NOT_STARTED → IN_PROGRESS → FOUND → INTEGRATED → CLEAN

Sources tracked (initial 12 from RS-001/RS-002):
  - gmx_v2_btc_perp:    NOT_STARTED, priority=1
  - gmx_v2_eth_perp:    NOT_STARTED, priority=2
  - btc_stablepool:     NOT_STARTED, priority=3
  - eth_aggressive_pool: NOT_STARTED, priority=4
  - gold_proxy_ousg:    NOT_STARTED, priority=5
  - btc_usd_conc_lp:   NOT_STARTED, priority=6
  - rwa_lp_ondo:        NOT_STARTED, priority=7
  - trader_losses_vault: NOT_STARTED, priority=8
  - aave_usdc_base:     IN_PROGRESS, priority=9
  - morpho_usdc_main:   IN_PROGRESS, priority=10
  - sky_susds:          CLEAN, priority=11  (already integrated!)
  - spark_susds:        CLEAN, priority=12  (already integrated!)

stdlib only. Atomic saves (tmp + os.replace).
"""

import json
import os
from typing import Dict, List, Optional

from spa_core.base import BaseAnalytics

VALID_STATUSES = ["NOT_STARTED", "IN_PROGRESS", "FOUND", "INTEGRATED", "CLEAN"]

# Status ordering (lower = earlier in pipeline)
_STATUS_ORDER = {s: i for i, s in enumerate(VALID_STATUSES)}

# Default source definitions
_DEFAULT_SOURCES = [
    {
        "source_id": "gmx_v2_btc_perp",
        "status": "NOT_STARTED",
        "priority": 1,
        "effort_days": 3,
        "owner": "team",
        "notes": "GMX v2 BTC perpetual market data — on-chain via Arbitrum",
    },
    {
        "source_id": "gmx_v2_eth_perp",
        "status": "NOT_STARTED",
        "priority": 2,
        "effort_days": 2,
        "owner": "team",
        "notes": "GMX v2 ETH perpetual market data — on-chain via Arbitrum",
    },
    {
        "source_id": "btc_stablepool",
        "status": "NOT_STARTED",
        "priority": 3,
        "effort_days": 2,
        "owner": "team",
        "notes": "BTC-backed stable pool yield series",
    },
    {
        "source_id": "eth_aggressive_pool",
        "status": "NOT_STARTED",
        "priority": 4,
        "effort_days": 2,
        "owner": "team",
        "notes": "ETH aggressive yield pool — leveraged strategy",
    },
    {
        "source_id": "gold_proxy_ousg",
        "status": "NOT_STARTED",
        "priority": 5,
        "effort_days": 3,
        "owner": "team",
        "notes": "OUSG gold proxy via Ondo Finance RWA API",
    },
    {
        "source_id": "btc_usd_conc_lp",
        "status": "NOT_STARTED",
        "priority": 6,
        "effort_days": 3,
        "owner": "team",
        "notes": "BTC/USD concentrated liquidity LP (Uniswap v3 or similar)",
    },
    {
        "source_id": "rwa_lp_ondo",
        "status": "NOT_STARTED",
        "priority": 7,
        "effort_days": 3,
        "owner": "team",
        "notes": "Ondo RWA LP yield series via Ondo API",
    },
    {
        "source_id": "trader_losses_vault",
        "status": "NOT_STARTED",
        "priority": 8,
        "effort_days": 2,
        "owner": "team",
        "notes": "GMX GLP / trader-losses vault yield data",
    },
    {
        "source_id": "aave_usdc_base",
        "status": "IN_PROGRESS",
        "priority": 9,
        "effort_days": 1,
        "owner": "team",
        "notes": "Aave V3 USDC on Base — DeFiLlama feed partially wired",
    },
    {
        "source_id": "morpho_usdc_main",
        "status": "IN_PROGRESS",
        "priority": 10,
        "effort_days": 1,
        "owner": "team",
        "notes": "Morpho Blue USDC mainnet — Morpho API v2 in progress",
    },
    {
        "source_id": "sky_susds",
        "status": "CLEAN",
        "priority": 11,
        "effort_days": 0,
        "owner": "team",
        "notes": "Sky/sUSDS — integrated via sky_monitor.py, GSM Pause Delay watch",
    },
    {
        "source_id": "spark_susds",
        "status": "CLEAN",
        "priority": 12,
        "effort_days": 0,
        "owner": "team",
        "notes": "Spark sUSDS — DeFiLlama ERC-4626 feed, CLEAN",
    },
]


class SourceEntry:
    """Represents a single data source to be acquired."""

    def __init__(
        self,
        source_id: str,
        status: str,
        priority: int,
        effort_days: int = 1,
        owner: str = "team",
        notes: str = "",
    ):
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of {VALID_STATUSES}"
            )
        if priority < 1:
            raise ValueError(f"priority must be >= 1, got {priority}")

        self.source_id = source_id
        self.status = status
        self.priority = priority
        self.effort_days = max(0, int(effort_days))
        self.owner = owner
        self.notes = notes

    def to_dict(self) -> dict:
        return {
            "source_id": self.source_id,
            "status": self.status,
            "priority": self.priority,
            "effort_days": self.effort_days,
            "owner": self.owner,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "SourceEntry":
        return cls(
            source_id=d["source_id"],
            status=d["status"],
            priority=d["priority"],
            effort_days=d.get("effort_days", 1),
            owner=d.get("owner", "team"),
            notes=d.get("notes", ""),
        )

    def __repr__(self) -> str:
        return (
            f"SourceEntry(source_id={self.source_id!r}, status={self.status!r}, "
            f"priority={self.priority}, effort_days={self.effort_days})"
        )


class SourceAcquisitionTracker(BaseAnalytics):
    """
    Tracks the progress of acquiring real on-chain/API data for SOURCE_NEEDED protocols.
    Persists state to a JSON file with atomic writes.
    """

    OUTPUT_PATH = "data/source_acquisition.json"

    def __init__(self, tracker_path: str = "data/source_acquisition.json"):
        super().__init__()
        self.tracker_path = tracker_path
        self._sources: Dict[str, SourceEntry] = {}
        self.load()

    # ── BaseAnalytics interface ───────────────────────────────────────────────

    def to_dict(self) -> dict:
        """Returns current tracker state as JSON-serializable dict."""
        return {
            "sources": [e.to_dict() for e in self._sources.values()],
        }

    # ── I/O ──────────────────────────────────────────────────────────────────

    def load(self) -> None:
        """Loads tracker state from JSON, initializes defaults if missing."""
        if os.path.exists(self.tracker_path):
            try:
                with open(self.tracker_path, "r", encoding="utf-8") as fh:
                    raw = json.load(fh)
                sources_list = raw.get("sources", [])
                self._sources = {
                    d["source_id"]: SourceEntry.from_dict(d) for d in sources_list
                }
                return
            except (json.JSONDecodeError, KeyError, ValueError):
                # Fall through to defaults on corrupt file
                pass

        # Initialize with defaults
        self._sources = {}
        for d in _DEFAULT_SOURCES:
            entry = SourceEntry.from_dict(d)
            self._sources[entry.source_id] = entry

    def save(self) -> None:
        """Atomic save to tracker_path (tmp + os.replace)."""
        payload = {
            "sources": [e.to_dict() for e in self._sources.values()],
        }
        from spa_core.utils.atomic import atomic_save
        atomic_save(payload, str(self.tracker_path))

    # ── Mutation ─────────────────────────────────────────────────────────────

    def update_status(self, source_id: str, status: str, notes: str = "") -> None:
        """
        Updates a source status.
        Raises ValueError for unknown source_id or invalid status.
        """
        if status not in VALID_STATUSES:
            raise ValueError(
                f"Invalid status '{status}'. Must be one of {VALID_STATUSES}"
            )
        if source_id not in self._sources:
            raise ValueError(f"Unknown source_id: {source_id!r}")
        self._sources[source_id].status = status
        if notes:
            self._sources[source_id].notes = notes

    # ── Queries ───────────────────────────────────────────────────────────────

    def status_summary(self) -> dict:
        """Returns counts by status + pct_clean."""
        counts: Dict[str, int] = {s: 0 for s in VALID_STATUSES}
        for entry in self._sources.values():
            counts[entry.status] += 1
        total = len(self._sources)
        counts["pct_clean"] = round(
            (counts["CLEAN"] / total * 100) if total > 0 else 0.0, 1
        )
        return counts

    def priority_queue(self) -> List[SourceEntry]:
        """
        Returns sources sorted so that NOT_STARTED sources come first (by priority),
        then IN_PROGRESS, FOUND, INTEGRATED, CLEAN last.
        Within each status group, sorted by priority ascending.
        """
        return sorted(
            self._sources.values(),
            key=lambda e: (_STATUS_ORDER[e.status], e.priority),
        )

    def clean_pct(self) -> float:
        """% of sources that are CLEAN (by count)."""
        if not self._sources:
            return 0.0
        clean_count = sum(
            1 for e in self._sources.values() if e.status == "CLEAN"
        )
        return round(clean_count / len(self._sources) * 100, 1)

    def days_to_clean(self) -> int:
        """
        Estimated days to make all sources CLEAN.
        Sum of effort_days for all sources that are not yet CLEAN.
        """
        return sum(
            e.effort_days
            for e in self._sources.values()
            if e.status != "CLEAN"
        )

    def get_source(self, source_id: str) -> Optional[SourceEntry]:
        """Returns a SourceEntry by ID, or None if not found."""
        return self._sources.get(source_id)

    def all_sources(self) -> List[SourceEntry]:
        """Returns all sources sorted by priority."""
        return sorted(self._sources.values(), key=lambda e: e.priority)

    # ── Reporting ─────────────────────────────────────────────────────────────

    def to_markdown(self) -> str:
        """Markdown table of all sources, sorted by priority."""
        lines = [
            "| Source ID | Status | Priority | Effort (days) | Owner | Notes |",
            "|-----------|--------|----------|---------------|-------|-------|",
        ]
        for entry in self.all_sources():
            lines.append(
                f"| {entry.source_id} "
                f"| {entry.status} "
                f"| {entry.priority} "
                f"| {entry.effort_days} "
                f"| {entry.owner} "
                f"| {entry.notes} |"
            )
        summary = self.status_summary()
        lines.append("")
        lines.append(
            f"**Summary:** NOT_STARTED={summary['NOT_STARTED']} "
            f"IN_PROGRESS={summary['IN_PROGRESS']} "
            f"FOUND={summary['FOUND']} "
            f"INTEGRATED={summary['INTEGRATED']} "
            f"CLEAN={summary['CLEAN']} "
            f"({summary['pct_clean']}% clean) "
            f"| Est. days to all-CLEAN: {self.days_to_clean()}"
        )
        return "\n".join(lines)

    def __repr__(self) -> str:
        s = self.status_summary()
        return (
            f"SourceAcquisitionTracker("
            f"sources={len(self._sources)}, "
            f"CLEAN={s['CLEAN']}, "
            f"NOT_STARTED={s['NOT_STARTED']}, "
            f"pct_clean={s['pct_clean']}%)"
        )
