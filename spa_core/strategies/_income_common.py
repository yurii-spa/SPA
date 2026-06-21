"""
spa_core/strategies/_income_common.py — shared helpers for the S46–S50
income-generation strategy batch.

This module factors out the bits that every income strategy needs:
  - a canonical fallback-APY table (percent units) for each protocol slot,
  - the adapter import map (slot key → module/class),
  - APY normalisation (some adapters return decimal 0.065, others percent 6.5),
  - an AdapterAPYMixin that loads adapters best-effort and exposes
    `_get_adapter_apy` / `_is_eligible`.

Rules (inherited from the strategy domain):
  - stdlib only, no external runtime dependencies,
  - read-only / advisory — never calls execution/ or risk-agents,
  - LLM FORBIDDEN in this module,
  - atomic data/ writes only (this module writes nothing).

Date: 2026-06-21 (S46–S50 income batch)
"""
from __future__ import annotations

from typing import Dict, List, Optional

# ─── Canonical fallback APYs (PERCENT units) ──────────────────────────────────
# Used when an adapter is offline / returns None. Tuned to live paper book
# levels (Aave ≈ 3.6%, Compound ≈ 3.9%) and CLAUDE.md orientation values.

PROTOCOL_FALLBACK_APY: Dict[str, float] = {
    "aave_v3":     3.6,
    "compound_v3": 3.9,
    "sky_susds":   4.0,
    "morpho_blue": 6.0,
    "fluid":       4.5,
    "yearn_v3":    4.8,
    "euler_v2":    5.0,
}

# Risk tier per slot.
PROTOCOL_TIER: Dict[str, str] = {
    "aave_v3":     "T1",
    "compound_v3": "T1",
    "sky_susds":   "T1",
    "morpho_blue": "T2",
    "fluid":       "T2",
    "yearn_v3":    "T2",
    "euler_v2":    "T2",
}

# Per-slot risk scores (0..1, higher = riskier).
PROTOCOL_RISK_SCORE: Dict[str, float] = {
    "aave_v3":     0.22,
    "compound_v3": 0.24,
    "sky_susds":   0.20,
    "morpho_blue": 0.42,
    "fluid":       0.40,
    "yearn_v3":    0.44,
    "euler_v2":    0.45,
}

# Slot key → (module path, class name). Best-effort import; missing → fallback.
ADAPTER_IMPORTS: Dict[str, tuple] = {
    "aave_v3":     ("spa_core.adapters.aave_v3", "AaveV3Adapter"),
    "compound_v3": ("spa_core.adapters.compound_v3", "CompoundV3Adapter"),
    "sky_susds":   ("spa_core.adapters.sky_susds_feed", "SkySUSDSFeed"),
    "morpho_blue": ("spa_core.adapters.morpho_blue", "MorphoBlueAdapter"),
    "fluid":       ("spa_core.adapters.fluid_usdc_adapter", "FluidUSDCAdapter"),
    "yearn_v3":    ("spa_core.adapters.yearn_v3", "YearnV3Adapter"),
    "euler_v2":    ("spa_core.adapters.euler_v2", "EulerV2Adapter"),
}

# RiskPolicy v1.0 new-position eligibility window (percent).
MIN_APY_ELIGIBLE: float = 1.0
MAX_APY_ELIGIBLE: float = 30.0

# RiskPolicy v1.0 caps (fractions).
T2_TOTAL_CAP:        float = 0.50    # ADR-019
T2_PER_PROTOCOL_CAP: float = 0.20
T1_PER_PROTOCOL_CAP: float = 0.40
MIN_CASH_BUFFER:     float = 0.05


def normalize_apy(value) -> Optional[float]:
    """Normalise an adapter APY reading to PERCENT units.

    Adapters are inconsistent: some `get_apy()` return decimal fractions
    (Sky/Aave/Yearn/Euler → 0.065 == 6.5%), others return percent
    (newer Base/spark adapters → 6.5). Heuristic: a positive reading below
    1.0 is treated as a decimal fraction and scaled ×100; everything ≥ 1.0
    is assumed to already be in percent. Returns None for non-numeric /
    non-positive inputs.
    """
    if value is None or isinstance(value, bool):
        return None
    if not isinstance(value, (int, float)):
        return None
    v = float(value)
    if v <= 0.0:
        return None
    return v * 100.0 if v < 1.0 else v


class AdapterAPYMixin:
    """Best-effort live-APY access with deterministic fallbacks.

    Subclasses must define a `_adapter_keys()` returning the slot keys they
    use. Adapters are loaded lazily on first construction; any import or call
    failure degrades silently to the fallback APY (never raises).
    """

    def _load_adapters(self) -> None:
        import importlib
        self._adapters: Dict[str, object] = {}
        for key in self._adapter_keys():
            spec = ADAPTER_IMPORTS.get(key)
            if not spec:
                continue
            module_path, class_name = spec
            try:
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                self._adapters[key] = cls()
            except Exception:   # noqa: BLE001 — degrade to fallback APY
                pass

    def _adapter_keys(self) -> List[str]:   # pragma: no cover - overridden
        return []

    def _get_adapter_apy(self, key: str) -> float:
        """Live APY (percent) → fallback APY (percent) → 0.0."""
        adapter = getattr(self, "_adapters", {}).get(key)
        if adapter is not None:
            try:
                norm = normalize_apy(adapter.get_apy())  # type: ignore[attr-defined]
                if norm is not None:
                    return round(norm, 4)
            except Exception:   # noqa: BLE001
                pass
        return float(PROTOCOL_FALLBACK_APY.get(key, 0.0))

    def _is_eligible(self, key: str) -> bool:
        """Eligible if adapter missing (use fallback) or is_eligible() truthy."""
        adapter = getattr(self, "_adapters", {}).get(key)
        if adapter is None:
            return True
        try:
            return bool(adapter.is_eligible())  # type: ignore[attr-defined]
        except Exception:   # noqa: BLE001
            return True
