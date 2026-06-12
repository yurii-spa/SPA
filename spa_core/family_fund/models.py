"""
SPA Family Fund — Data Models (Phase 0)
Pure stdlib dataclasses. No external dependencies.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict, field
from typing import Dict, Optional


__all__ = ["Investor", "InvestorStatement", "FundSnapshot"]


@dataclass
class Investor:
    """Represents a single fund investor."""
    id: str                        # UUID4
    name: str
    email: str
    wallet_address: str            # Ethereum address (empty until verified)
    joined_at: str                 # ISO 8601
    initial_capital_usd: float
    current_share_pct: float       # % of AUM (0.0–100.0)
    status: str                    # "active" | "pending" | "exited"
    notes: str = ""

    # ------------------------------------------------------------------ #
    # Serialization helpers
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Investor":
        return cls(
            id=str(d["id"]),
            name=str(d["name"]),
            email=str(d["email"]),
            wallet_address=str(d.get("wallet_address", "")),
            joined_at=str(d["joined_at"]),
            initial_capital_usd=float(d["initial_capital_usd"]),
            current_share_pct=float(d.get("current_share_pct", 0.0)),
            status=str(d.get("status", "pending")),
            notes=str(d.get("notes", "")),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "Investor":
        return cls.from_dict(json.loads(s))

    # ------------------------------------------------------------------ #
    # Validation helpers
    # ------------------------------------------------------------------ #

    VALID_STATUSES = frozenset({"active", "pending", "exited"})

    def validate(self) -> None:
        if not self.id:
            raise ValueError("Investor.id must not be empty")
        if not self.name:
            raise ValueError("Investor.name must not be empty")
        if "@" not in self.email:
            raise ValueError(f"Investor.email looks invalid: {self.email!r}")
        if self.initial_capital_usd < 0:
            raise ValueError("Investor.initial_capital_usd must be >= 0")
        if not (0.0 <= self.current_share_pct <= 100.0):
            raise ValueError(
                f"Investor.current_share_pct out of range: {self.current_share_pct}"
            )
        if self.status not in self.VALID_STATUSES:
            raise ValueError(
                f"Investor.status must be one of {self.VALID_STATUSES}, "
                f"got {self.status!r}"
            )


@dataclass
class InvestorStatement:
    """Monthly P&L statement for one investor."""
    investor_id: str
    period: str           # "YYYY-MM"
    opening_balance: float
    closing_balance: float
    pnl_usd: float
    pnl_pct: float
    apy_annualized: float
    generated_at: str     # ISO 8601

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "InvestorStatement":
        return cls(
            investor_id=str(d["investor_id"]),
            period=str(d["period"]),
            opening_balance=float(d["opening_balance"]),
            closing_balance=float(d["closing_balance"]),
            pnl_usd=float(d["pnl_usd"]),
            pnl_pct=float(d["pnl_pct"]),
            apy_annualized=float(d["apy_annualized"]),
            generated_at=str(d["generated_at"]),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "InvestorStatement":
        return cls.from_dict(json.loads(s))

    def validate(self) -> None:
        if not self.investor_id:
            raise ValueError("InvestorStatement.investor_id must not be empty")
        # Validate period format YYYY-MM
        parts = self.period.split("-")
        if len(parts) != 2 or not (parts[0].isdigit() and parts[1].isdigit()):
            raise ValueError(
                f"InvestorStatement.period must be YYYY-MM, got {self.period!r}"
            )
        if self.opening_balance < 0:
            raise ValueError("InvestorStatement.opening_balance must be >= 0")
        if self.closing_balance < 0:
            raise ValueError("InvestorStatement.closing_balance must be >= 0")


@dataclass
class FundSnapshot:
    """Point-in-time snapshot of the entire fund."""
    snapshot_date: str          # YYYY-MM-DD
    total_aum_usd: float
    nav_per_share: float        # normalized to 1.0 on day 0
    investor_count: int
    strategy_mix: Dict[str, float]   # {"S0": 0.40, "S1": 0.30, ...}
    realized_apy: float

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "FundSnapshot":
        return cls(
            snapshot_date=str(d["snapshot_date"]),
            total_aum_usd=float(d["total_aum_usd"]),
            nav_per_share=float(d.get("nav_per_share", 1.0)),
            investor_count=int(d["investor_count"]),
            strategy_mix=dict(d.get("strategy_mix", {})),
            realized_apy=float(d.get("realized_apy", 0.0)),
        )

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @classmethod
    def from_json(cls, s: str) -> "FundSnapshot":
        return cls.from_dict(json.loads(s))

    def validate(self) -> None:
        parts = self.snapshot_date.split("-")
        if len(parts) != 3:
            raise ValueError(
                f"FundSnapshot.snapshot_date must be YYYY-MM-DD, "
                f"got {self.snapshot_date!r}"
            )
        if self.total_aum_usd < 0:
            raise ValueError("FundSnapshot.total_aum_usd must be >= 0")
        if self.nav_per_share <= 0:
            raise ValueError("FundSnapshot.nav_per_share must be > 0")
        if self.investor_count < 0:
            raise ValueError("FundSnapshot.investor_count must be >= 0")
        mix_sum = sum(self.strategy_mix.values())
        if self.strategy_mix and not (0.99 <= mix_sum <= 1.01):
            raise ValueError(
                f"FundSnapshot.strategy_mix values must sum to ~1.0, got {mix_sum:.4f}"
            )
