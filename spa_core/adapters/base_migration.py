"""
spa_core/adapters/base_migration.py

Verifies all registered adapters conform to BaseAdapter interface.
Run periodically to catch non-conforming adapters.

MP-1393 (v10.9): Adapter conformance checker.

This module performs DUCK-TYPE conformance checks — it accepts alternative
method / attribute names so that both legacy T1 adapters (which use get_apy /
get_yield_info from adapters/base_adapter.py) and research-only adapters
(which use fetch_apy / source_metadata + module-level constants) are treated
as conforming if they expose the practical interface SPA needs.

Conformance criteria (flexible — any alternative satisfies each slot):
  1. APY getter   : current_apy | get_apy | get_apy_pct | fetch_apy |
                    best_available_apy | btc_exposure_apy | gold_proxy_apy |
                    rwa_lp_apy
  2. Source ID    : SOURCE_ID class attr | PROTOCOL class attr |
                    SOURCE_ID module attr
  3. Fallback APY : FALLBACK_APY class attr | FALLBACK_APY_PCT class attr |
                    registry["fallback_apy"] key
  4. Metadata     : source_metadata() | get_yield_info() | is_research_only()
  5. Research flag: IF registry research_only=True THEN module-level
                    RESEARCH_ONLY must be True

stdlib only — no third-party imports. Never modifies state files or calls
execution / monitoring domains.

Usage:
    from spa_core.adapters.base_migration import check_all, report

    results = check_all()      # {adapter_id: {conforming: bool, missing: list}}
    print(report())            # human-readable conformance report
"""
from __future__ import annotations

import importlib
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Internal — lazy import so the module stays importable even if registry
# has problems.
# ---------------------------------------------------------------------------

def _get_registry() -> Dict[str, Any]:
    from spa_core.adapters.registry import ADAPTER_REGISTRY
    return ADAPTER_REGISTRY


def _get_adapter_safe(adapter_id: str) -> Optional[Any]:
    """Instantiate adapter by ID, returning None on any error."""
    try:
        from spa_core.adapters.registry import get_adapter
        return get_adapter(adapter_id)
    except Exception as exc:
        logger.debug("base_migration: failed to instantiate %s: %s", adapter_id, exc)
        return None


def _get_module_safe(module_path: str) -> Optional[Any]:
    """Import a module by dotted path, returning None on error."""
    try:
        return importlib.import_module(module_path)
    except Exception as exc:
        logger.debug("base_migration: failed to import %s: %s", module_path, exc)
        return None


# ---------------------------------------------------------------------------
# Conformance slots — each list is ordered by preference.
# ---------------------------------------------------------------------------

_APY_METHODS = [
    "current_apy",
    "get_apy",
    "get_apy_pct",
    "fetch_apy",
    "best_available_apy",
    "btc_exposure_apy",
    "gold_proxy_apy",
    "rwa_lp_apy",
]

_META_METHODS = [
    "source_metadata",
    "get_yield_info",
    "is_research_only",
]

_SOURCE_ID_ATTRS = [
    "SOURCE_ID",
    "PROTOCOL",
    "PROTOCOL_NAME",
]

_FALLBACK_ATTRS = [
    "FALLBACK_APY",
    "FALLBACK_APY_PCT",
]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def check_adapter_interface(adapter_id: str) -> dict:
    """Check whether a single adapter satisfies the SPA conformance interface.

    Parameters
    ----------
    adapter_id:
        Key in ADAPTER_REGISTRY (e.g. ``"aave_usdc"``).

    Returns
    -------
    dict
        ``{adapter_id, conforming: bool, missing: list[str], note: str}``

        ``conforming=True`` means ALL five slots are satisfied (via any
        accepted alternative). ``missing`` lists only the *strict*
        spa_core/base.py BaseAdapter attribute names that are absent — it
        may be non-empty even when ``conforming=True`` because the flexible
        alternative filled the slot.
    """
    registry = _get_registry()

    if adapter_id not in registry:
        return {
            "adapter_id": adapter_id,
            "conforming": False,
            "missing": ["registry"],
            "note": f"'{adapter_id}' not found in ADAPTER_REGISTRY",
        }

    meta = registry[adapter_id]
    failures: List[str] = []   # slots that could NOT be filled by any alternative
    missing: List[str] = []    # strict base.py attrs that are absent (for reporting)

    # -- 1. Instantiate -------------------------------------------------------
    instance = _get_adapter_safe(adapter_id)
    if instance is None:
        return {
            "adapter_id": adapter_id,
            "conforming": False,
            "missing": ["instantiation_failed"],
            "note": "Adapter could not be instantiated",
        }

    cls = type(instance)

    # -- 2. APY getter slot ---------------------------------------------------
    has_apy_method = any(
        callable(getattr(instance, m, None)) for m in _APY_METHODS
    )
    if not has_apy_method:
        failures.append("apy_method")
    # track strict miss
    if not callable(getattr(instance, "current_apy", None)):
        missing.append("current_apy")

    # -- 3. Source ID slot ----------------------------------------------------
    module_obj = _get_module_safe(meta.get("module", ""))
    has_source_id = (
        any(getattr(cls, attr, None) is not None for attr in _SOURCE_ID_ATTRS)
        or any(getattr(module_obj, attr, None) is not None for attr in ["SOURCE_ID"])
    )
    if not has_source_id:
        failures.append("source_id")
    if getattr(cls, "SOURCE_ID", None) is None:
        missing.append("SOURCE_ID")

    # -- 4. Fallback APY slot -------------------------------------------------
    has_fallback = (
        any(getattr(cls, attr, None) is not None for attr in _FALLBACK_ATTRS)
        or isinstance(meta.get("fallback_apy"), (int, float))
    )
    if not has_fallback:
        failures.append("fallback_apy")
    if getattr(cls, "FALLBACK_APY", None) is None:
        missing.append("FALLBACK_APY")

    # -- 5. Metadata method slot ----------------------------------------------
    has_meta = any(
        callable(getattr(instance, m, None)) for m in _META_METHODS
    )
    if not has_meta:
        failures.append("meta_method")
    if not callable(getattr(instance, "source_metadata", None)):
        missing.append("source_metadata")

    # -- 6. Research flag consistency -----------------------------------------
    if meta.get("research_only") is True:
        module_research_only = getattr(module_obj, "RESEARCH_ONLY", None)
        cls_research_only = getattr(cls, "RESEARCH_ONLY", None)
        flag_ok = (module_research_only is True) or (cls_research_only is True)
        if not flag_ok:
            failures.append("RESEARCH_ONLY_flag")
        if getattr(cls, "RESEARCH_ONLY", None) is None:
            missing.append("RESEARCH_ONLY")

    conforming = len(failures) == 0
    note = "OK" if conforming else f"slot failures: {failures}"

    return {
        "adapter_id": adapter_id,
        "conforming": conforming,
        "missing": missing,
        "note": note,
    }


def check_all() -> Dict[str, dict]:
    """Run :func:`check_adapter_interface` for every adapter in the registry.

    Returns
    -------
    dict
        ``{adapter_id: check_result}`` where each value has the same shape as
        :func:`check_adapter_interface` output.
    """
    registry = _get_registry()
    results: Dict[str, dict] = {}
    for adapter_id in registry:
        results[adapter_id] = check_adapter_interface(adapter_id)
    return results


def report() -> str:
    """Return a human-readable conformance report for all registered adapters.

    Example output::

        === SPA Adapter Conformance Report ===
        Total: 19  |  PASS: 19  |  FAIL: 0

        PASS  aave_usdc         (T1) missing strict: current_apy, SOURCE_ID, FALLBACK_APY, source_metadata
        PASS  compound_usdc     (T1) missing strict: current_apy, SOURCE_ID, FALLBACK_APY, source_metadata
        ...
        PASS  gmx_btc_perp      (T2/research) missing strict: current_apy, FALLBACK_APY
        ...
    """
    registry = _get_registry()
    results = check_all()

    pass_count = sum(1 for r in results.values() if r.get("conforming"))
    fail_count = len(results) - pass_count

    lines: List[str] = [
        "=== SPA Adapter Conformance Report (MP-1393) ===",
        f"Total: {len(results)}  |  PASS: {pass_count}  |  FAIL: {fail_count}",
        "",
    ]

    for adapter_id, result in sorted(results.items()):
        status = "PASS" if result.get("conforming") else "FAIL"
        tier = registry.get(adapter_id, {}).get("tier", "?")
        research = "(research)" if registry.get(adapter_id, {}).get("research_only") else ""
        tier_label = f"{tier}{' ' + research if research else ''}"

        missing_strict = result.get("missing", [])
        missing_note = (
            f"missing strict: {', '.join(missing_strict)}"
            if missing_strict
            else "fully conformant"
        )

        lines.append(
            f"{status:<5} {adapter_id:<30} ({tier_label}) {missing_note}"
        )
        if not result.get("conforming"):
            lines.append(f"      note: {result.get('note', '')}")

    lines.append("")
    lines.append(
        "NOTE: PASS = practical interface satisfied (flexible check). "
        "'missing strict' lists spa_core/base.py BaseAdapter attrs not yet present."
    )
    return "\n".join(lines)
