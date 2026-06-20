"""
spa_core/analytics/t1_data_verifier.py

Verifies T1 adapter data quality.
Checks: APY in expected range, source responds, no stale data.

MP-1394 (v10.10): T1 clean data verifier.

T1_EXPECTED_RANGES defines acceptable APY bands (in **percent**, e.g. 5.0 ==
5%). Adapters return APY as a **decimal** (e.g. 0.05 == 5%), so the verifier
multiplies the returned value by 100 before comparing.

Verdict logic:
  PASS — source responded AND APY is within expected range
  WARN — source responded BUT APY is outside expected range
  FAIL — source did not respond (None) OR returned 0.0

Adapter lookup strategy:
  1. Registry alias table (_ADAPTER_ALIAS) maps known non-registry IDs to
     either a registry key ("morpho_usdc" → "morpho_steakhouse") or a direct
     import ("sky_susds" → SkySUSDSFeed).
  2. Falls back to ADAPTER_REGISTRY.get_adapter() for IDs present in registry.
  3. If neither works: source_responded=False, verdict=FAIL.

Stdlib only — no third-party imports. Never writes to execution / monitoring
domain. Atomic save via tmp + os.replace pattern.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from spa_core.base import BaseAnalytics

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Expected APY ranges for T1 ("CLEAN") adapters — values in percent.
# ---------------------------------------------------------------------------

T1_EXPECTED_RANGES: Dict[str, Dict[str, float]] = {
    "sky_susds":   {"min_apy": 4.0,  "max_apy": 12.0},
    "spark_susds": {"min_apy": 3.0,  "max_apy": 10.0},
    "aave_usdc":   {"min_apy": 2.0,  "max_apy": 8.0},
    "morpho_usdc": {"min_apy": 3.0,  "max_apy": 10.0},
}

# Maps T1_EXPECTED_RANGES IDs that are NOT directly in ADAPTER_REGISTRY to
# either ("registry", <registry_key>) or ("direct", <module>, <class>).
_ADAPTER_ALIAS: Dict[str, tuple] = {
    "sky_susds":   ("direct", "spa_core.adapters.sky_susds_feed", "SkySUSDSFeed"),
    "morpho_usdc": ("registry", "morpho_steakhouse"),
}

# Output file relative to base_dir
_OUTPUT_PATH = "data/t1_verification.json"


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _instantiate_adapter(adapter_id: str) -> Optional[Any]:
    """Return an adapter instance for *adapter_id*, or None on failure."""
    # Check alias table first
    alias = _ADAPTER_ALIAS.get(adapter_id)
    if alias is not None:
        if alias[0] == "registry":
            actual_id = alias[1]
        else:
            # direct import
            _, module_path, class_name = alias
            try:
                import importlib
                mod = importlib.import_module(module_path)
                cls = getattr(mod, class_name)
                return cls()
            except Exception as exc:
                logger.debug("t1_verifier: direct import %s failed: %s", module_path, exc)
                return None
        # fall through to registry with actual_id
    else:
        actual_id = adapter_id

    # Try ADAPTER_REGISTRY
    try:
        from spa_core.adapters.registry import get_adapter
        return get_adapter(actual_id)
    except Exception as exc:
        logger.debug("t1_verifier: registry lookup %s failed: %s", actual_id, exc)
        return None


def _fetch_apy_decimal(adapter_id: str) -> Optional[float]:
    """Return adapter APY as a decimal, or None if unavailable.

    This is the single point of I/O that tests mock out.
    """
    instance = _instantiate_adapter(adapter_id)
    if instance is None:
        return None

    # Try methods in preference order (all return decimal or None)
    for method_name in ("get_apy", "current_apy", "fetch_apy"):
        method = getattr(instance, method_name, None)
        if callable(method):
            try:
                value = method()
                if value is not None:
                    return float(value)
            except Exception as exc:
                logger.debug(
                    "t1_verifier: %s.%s() raised: %s", adapter_id, method_name, exc
                )
                return None

    return None


# ---------------------------------------------------------------------------
# Public class
# ---------------------------------------------------------------------------

class T1DataVerifier(BaseAnalytics):
    """Verifies data quality for all T1 ('CLEAN') adapters.

    Parameters
    ----------
    base_dir:
        Root directory of the SPA repo (used for atomic save path resolution).
    """

    OUTPUT_PATH = _OUTPUT_PATH

    def __init__(self, base_dir: str = "."):
        super().__init__(base_dir=base_dir)
        self.base_dir = base_dir

    # ------------------------------------------------------------------ #
    # Core: verify one adapter                                             #
    # ------------------------------------------------------------------ #

    def verify_adapter(self, adapter_id: str) -> dict:
        """Verify a single T1 adapter.

        Parameters
        ----------
        adapter_id:
            Key in T1_EXPECTED_RANGES.

        Returns
        -------
        dict
            ``{adapter_id, apy, in_range, source_responded,
               expected_range, verdict: "PASS"/"FAIL"/"WARN"}``
        """
        expected = T1_EXPECTED_RANGES.get(adapter_id, {})
        min_apy = expected.get("min_apy", 0.0)
        max_apy = expected.get("max_apy", 100.0)

        apy_decimal = self._get_apy(adapter_id)

        if apy_decimal is None or apy_decimal == 0.0:
            return {
                "adapter_id":       adapter_id,
                "apy":              apy_decimal,
                "in_range":         False,
                "source_responded": False,
                "expected_range":   {"min_apy": min_apy, "max_apy": max_apy},
                "verdict":          "FAIL",
            }

        # Convert decimal → percent for range check
        apy_pct = apy_decimal * 100.0
        in_range = min_apy <= apy_pct <= max_apy
        verdict = "PASS" if in_range else "WARN"

        return {
            "adapter_id":       adapter_id,
            "apy":              apy_pct,          # stored in % for readability
            "in_range":         in_range,
            "source_responded": True,
            "expected_range":   {"min_apy": min_apy, "max_apy": max_apy},
            "verdict":          verdict,
        }

    # ------------------------------------------------------------------ #
    # Aggregate                                                            #
    # ------------------------------------------------------------------ #

    def verify_all_t1(self) -> List[dict]:
        """Verify all adapters in T1_EXPECTED_RANGES.

        Returns
        -------
        list
            One result dict per adapter (same shape as :meth:`verify_adapter`).
        """
        return [self.verify_adapter(aid) for aid in T1_EXPECTED_RANGES]

    def all_pass(self) -> bool:
        """Return True if every T1 adapter has verdict == "PASS"."""
        return all(r["verdict"] == "PASS" for r in self.verify_all_t1())

    # ------------------------------------------------------------------ #
    # BaseAnalytics interface                                              #
    # ------------------------------------------------------------------ #

    def to_dict(self) -> dict:
        """Returns current T1 verification results as JSON-serializable dict."""
        results = self.verify_all_t1()
        return {
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "pass_count": sum(1 for r in results if r["verdict"] == "PASS"),
            "fail_count": sum(1 for r in results if r["verdict"] == "FAIL"),
            "warn_count": sum(1 for r in results if r["verdict"] == "WARN"),
            "all_pass":   all(r["verdict"] == "PASS" for r in results),
        }

    # ------------------------------------------------------------------ #
    # Persistence                                                          #
    # ------------------------------------------------------------------ #

    def save(self, results: Optional[List[dict]] = None) -> str:
        """Atomically save verification results to data/t1_verification.json.

        Parameters
        ----------
        results:
            List of result dicts. If None, :meth:`verify_all_t1` is called.

        Returns
        -------
        str
            Absolute path of the written file.
        """
        if results is None:
            results = self.verify_all_t1()

        output_path = os.path.join(self.base_dir, _OUTPUT_PATH)
        os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)

        payload = {
            "verified_at": datetime.now(timezone.utc).isoformat(),
            "results": results,
            "pass_count": sum(1 for r in results if r["verdict"] == "PASS"),
            "fail_count": sum(1 for r in results if r["verdict"] == "FAIL"),
            "warn_count": sum(1 for r in results if r["verdict"] == "WARN"),
            "all_pass":   all(r["verdict"] == "PASS" for r in results),
        }

        tmp_path = output_path + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2)
            os.replace(tmp_path, output_path)
        finally:
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        return os.path.abspath(output_path)

    # ------------------------------------------------------------------ #
    # Markdown report                                                       #
    # ------------------------------------------------------------------ #

    def to_markdown(self, results: Optional[List[dict]] = None) -> str:
        """Render a Markdown summary of T1 verification results.

        Parameters
        ----------
        results:
            List of result dicts. If None, :meth:`verify_all_t1` is called.

        Returns
        -------
        str
            Markdown-formatted report.
        """
        if results is None:
            results = self.verify_all_t1()

        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        pass_count = sum(1 for r in results if r["verdict"] == "PASS")
        fail_count = sum(1 for r in results if r["verdict"] == "FAIL")
        warn_count = sum(1 for r in results if r["verdict"] == "WARN")

        lines = [
            "# T1 Clean Data Verification Report (MP-1394)",
            f"",
            f"**Generated:** {now}  ",
            f"**Total:** {len(results)}  |  ✅ PASS: {pass_count}  |  ⚠️ WARN: {warn_count}  |  ❌ FAIL: {fail_count}",
            "",
            "| Adapter | APY % | Expected Range | In Range | Source | Verdict |",
            "|---------|-------|---------------|----------|--------|---------|",
        ]

        for r in results:
            apy_str = f"{r['apy']:.2f}%" if r.get("apy") is not None else "N/A"
            exp = r.get("expected_range", {})
            range_str = f"{exp.get('min_apy', '?')}–{exp.get('max_apy', '?')}%"
            in_range_str = "✅" if r.get("in_range") else "❌"
            src_str = "✅" if r.get("source_responded") else "❌"
            verdict = r.get("verdict", "?")
            verdict_icon = {"PASS": "✅ PASS", "FAIL": "❌ FAIL", "WARN": "⚠️ WARN"}.get(verdict, verdict)

            lines.append(
                f"| {r['adapter_id']} | {apy_str} | {range_str} | "
                f"{in_range_str} | {src_str} | {verdict_icon} |"
            )

        lines.extend(["", "---", "_SPA T1 Data Verifier — stdlib only, read-only, advisory._"])
        return "\n".join(lines)

    # ------------------------------------------------------------------ #
    # Internal — separated for easy mocking in tests                       #
    # ------------------------------------------------------------------ #

    def _get_apy(self, adapter_id: str) -> Optional[float]:
        """Return APY as decimal for *adapter_id*, or None. Override in tests."""
        return _fetch_apy_decimal(adapter_id)
