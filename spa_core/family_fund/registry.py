"""
SPA Family Fund — Investor Registry
Atomic read/write to data/investors.json via mkstemp + os.replace.
Pure stdlib. No external dependencies.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import List, Optional

from spa_core.family_fund.models import Investor

__all__ = ["InvestorRegistry"]

# Default storage path relative to the project root
_DEFAULT_INVESTORS_PATH = Path(__file__).resolve().parents[2] / "data" / "investors.json"


class InvestorRegistry:
    """
    Persistent investor store backed by data/investors.json.

    All writes use mkstemp + os.replace for crash-safe atomicity.
    """

    def __init__(self, investors_path: Optional[Path] = None) -> None:
        self._path: Path = Path(investors_path) if investors_path else _DEFAULT_INVESTORS_PATH

    # ------------------------------------------------------------------ #
    # Low-level I/O
    # ------------------------------------------------------------------ #

    def _read_raw(self) -> dict:
        """Read and parse the full investors.json envelope."""
        if not self._path.exists():
            return self._empty_envelope()
        with open(self._path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _write_raw(self, data: dict) -> None:
        """Atomically write the investors.json envelope."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=self._path.parent, prefix=".investors_tmp_"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, ensure_ascii=False, indent=2)
            os.replace(tmp_path, self._path)
        except Exception:
            # Clean up temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    @staticmethod
    def _empty_envelope() -> dict:
        return {
            "investors": [],
            "fund_start_date": "2026-06-12",
            "fund_name": "SPA Family Fund",
            "base_currency": "USD",
            "nav_base": 1.0,
            "metadata": {
                "version": "1.0",
                "updated_at": "2026-06-12T00:00:00Z",
            },
        }

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def load(self) -> List[Investor]:
        """Return all investors from disk."""
        raw = self._read_raw()
        return [Investor.from_dict(d) for d in raw.get("investors", [])]

    def save(self, investors: List[Investor]) -> None:
        """Persist a full list of investors (replaces existing)."""
        raw = self._read_raw()
        raw["investors"] = [inv.to_dict() for inv in investors]
        self._write_raw(raw)

    def add_investor(self, investor: Investor) -> None:
        """Append a new investor. Raises ValueError on duplicate id."""
        investor.validate()
        investors = self.load()
        existing_ids = {inv.id for inv in investors}
        if investor.id in existing_ids:
            raise ValueError(
                f"Investor with id={investor.id!r} already exists"
            )
        investors.append(investor)
        self.recompute_shares(investors)
        self.save(investors)

    def get_investor(self, investor_id: str) -> Optional[Investor]:
        """Return investor by id, or None if not found."""
        for inv in self.load():
            if inv.id == investor_id:
                return inv
        return None

    def update_investor(self, investor_id: str, **kwargs) -> Investor:
        """
        Update mutable fields of an investor in-place.
        Returns the updated Investor.
        Raises KeyError if investor not found.
        Raises ValueError for unknown fields or invalid values.
        """
        mutable_fields = {
            "name", "email", "wallet_address", "status",
            "notes", "current_share_pct", "initial_capital_usd",
        }
        unknown = set(kwargs) - mutable_fields
        if unknown:
            raise ValueError(f"Unknown investor fields: {unknown}")

        investors = self.load()
        for i, inv in enumerate(investors):
            if inv.id == investor_id:
                d = inv.to_dict()
                d.update(kwargs)
                updated = Investor.from_dict(d)
                updated.validate()
                investors[i] = updated
                self.recompute_shares(investors)
                self.save(investors)
                return investors[i]
        raise KeyError(f"Investor id={investor_id!r} not found")

    def active_investors(self) -> List[Investor]:
        """Return only investors with status='active'."""
        return [inv for inv in self.load() if inv.status == "active"]

    def total_capital_usd(self) -> float:
        """Sum of initial_capital_usd for all active investors."""
        return sum(inv.initial_capital_usd for inv in self.active_investors())

    def recompute_shares(self, investors: Optional[List[Investor]] = None) -> None:
        """
        Recompute current_share_pct for all active investors based on
        their initial_capital_usd proportions.

        If `investors` is provided, mutates that list in-place (used
        internally before save). Otherwise reads from disk and saves back.
        """
        _save_after = investors is None
        if investors is None:
            investors = self.load()

        active = [inv for inv in investors if inv.status == "active"]
        total = sum(inv.initial_capital_usd for inv in active)

        for inv in investors:
            if inv.status == "active" and total > 0:
                inv.current_share_pct = round(
                    inv.initial_capital_usd / total * 100.0, 6
                )
            elif inv.status != "active":
                inv.current_share_pct = 0.0
            else:
                # total == 0: all active investors get equal shares
                n = len(active)
                inv.current_share_pct = round(100.0 / n, 6) if n > 0 else 0.0

        if _save_after:
            self.save(investors)
