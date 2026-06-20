"""
spa_core/utils/type_utils.py
Common type aliases shared across the SPA codebase (MP-1233).

Pure typing module — no runtime logic, stdlib only. Importing this costs
nothing at runtime and gives the type checker (mypy) and human readers a
single, documented vocabulary for the domain's recurring scalar shapes.

Conventions
-----------
* APY / weight floats are FRACTIONS in [0.0, 1.0] unless the name ends in
  ``_pct`` (then they are percent, e.g. 4.8 == 4.8%). Mixing the two has been
  a recurring bug source, so the alias names below encode the convention.
* USD floats are plain dollar amounts (e.g. 100_000.0 == $100k).

These are *aliases*, not new types — at runtime ``APYFloat is float`` is True.
They document intent without changing behavior or adding validation.
"""
from __future__ import annotations

from typing import Literal

# ── Scalar domain aliases ────────────────────────────────────────────────────

APYFloat = float
"""Annualised yield as a FRACTION in [0.0, 1.0] (0.048 == 4.8%). Not percent."""

USDFloat = float
"""A US-dollar amount (e.g. 100_000.0 == $100,000)."""

WeightFloat = float
"""Allocation weight as a FRACTION in [0.0, 1.0] (0.40 == 40% of portfolio)."""

# ── Identifier aliases ───────────────────────────────────────────────────────

AdapterName = str
"""Registry key of a protocol adapter, e.g. ``"aave_v3"`` (see ADAPTER_REGISTRY)."""

StrategyName = str
"""Registry id of a tournament strategy, e.g. ``"s8_delta_neutral_susde"``."""

# ── Enumerated aliases ───────────────────────────────────────────────────────

ProtocolTier = Literal["T1", "T2", "T3"]
"""Risk tier of a protocol: T1 (bluest chip) … T3 (speculative / private credit)."""


__all__ = [
    "APYFloat",
    "USDFloat",
    "WeightFloat",
    "AdapterName",
    "StrategyName",
    "ProtocolTier",
]
