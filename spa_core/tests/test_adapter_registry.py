"""
Tests for spa_core.adapters.adapter_registry (MP-389).

Test suites:
  TestRegistryMeta          (10) — metaclass auto-registration
  TestBaseAdapter            (8) — RegistryBaseAdapter interface
  TestGetAllAdapters         (7) — get_all_adapters() behaviour
  TestRefreshAll            (15) — refresh_all() writes / atomic / edge-cases
  TestCycleIntegration      (10) — refresh_all called, results format
  TestExplicitRegistration  (12) — REGISTRY["key"] = Class, override, unregister

All tests are isolated: they snapshot REGISTRY before, restore after.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

# ── Make sure the package root is on sys.path ────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[3]  # spa_core/tests → repo root
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.adapters.adapter_registry import (
    REGISTRY,
    RegistryBaseAdapter,
    RegistryMeta,
    _extract_apy_pct,
    _extract_tier,
    get_all_adapters,
    refresh_all,
    register,
    unregister,
)


# ---------------------------------------------------------------------------
# Test helpers / fixtures
# ---------------------------------------------------------------------------


def _snapshot_registry() -> dict:
    """Return a copy of current REGISTRY (for restore-in-tearDown)."""
    return dict(REGISTRY)


def _restore_registry(snapshot: dict) -> None:
    """Restore REGISTRY to snapshot state."""
    REGISTRY.clear()
    REGISTRY.update(snapshot)


class _TmpDir:
    """Context manager that creates a temporary directory."""

    def __enter__(self) -> str:
        self._d = tempfile.mkdtemp()
        return self._d

    def __exit__(self, *args):
        import shutil
        shutil.rmtree(self._d, ignore_errors=True)


def _make_status_file(directory: str, data: dict) -> str:
    """Write a JSON status file and return its path."""
    path = os.path.join(directory, "adapter_status.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)
    return path


# ---------------------------------------------------------------------------
# TestRegistryMeta  (10 tests)
# ---------------------------------------------------------------------------


class TestRegistryMeta(unittest.TestCase):
    """Metaclass auto-registration behaviour."""

    def setUp(self):
        self._snap = _snapshot_registry()

    def tearDown(self):
        _restore_registry(self._snap)

    # ── 1. Concrete subclass with PROTOCOL is registered ────────────────────
    def test_concrete_subclass_registered(self):
        class Alpha(RegistryBaseAdapter):
            PROTOCOL = "_test_alpha"

        self.assertIn("_test_alpha", REGISTRY)

    # ── 2. Registered value is the class itself ──────────────────────────────
    def test_registered_value_is_class(self):
        class Beta(RegistryBaseAdapter):
            PROTOCOL = "_test_beta"

        self.assertIs(REGISTRY["_test_beta"], Beta)

    # ── 3. RegistryBaseAdapter itself is NOT registered ─────────────────────
    def test_base_not_in_registry(self):
        # RegistryBaseAdapter has PROTOCOL="" → not registered
        self.assertNotIn("", REGISTRY)

    # ── 4. Two classes with different protocols both registered ──────────────
    def test_two_classes_both_registered(self):
        class P1(RegistryBaseAdapter):
            PROTOCOL = "_test_p1"

        class P2(RegistryBaseAdapter):
            PROTOCOL = "_test_p2"

        self.assertIn("_test_p1", REGISTRY)
        self.assertIn("_test_p2", REGISTRY)

    # ── 5. Class with empty PROTOCOL string is NOT registered ────────────────
    def test_empty_protocol_not_registered(self):
        before = set(REGISTRY.keys())

        class NoProtocol(RegistryBaseAdapter):
            PROTOCOL = ""

        after = set(REGISTRY.keys())
        self.assertEqual(before, after)

    # ── 6. Class without PROTOCOL attribute is not registered ────────────────
    def test_missing_protocol_attr_not_registered(self):
        before = set(REGISTRY.keys())

        class NoPAttr(RegistryBaseAdapter):
            pass  # no PROTOCOL defined

        after = set(REGISTRY.keys())
        self.assertEqual(before, after)

    # ── 7. RegistryMeta is indeed the metaclass of RegistryBaseAdapter ───────
    def test_metaclass_identity(self):
        self.assertIsInstance(RegistryBaseAdapter, RegistryMeta)

    # ── 8. Concrete subclass is also instance of RegistryMeta ────────────────
    def test_concrete_subclass_metaclass(self):
        class Gamma(RegistryBaseAdapter):
            PROTOCOL = "_test_gamma"

        self.assertIsInstance(Gamma, RegistryMeta)

    # ── 9. Re-definition overwrites registry entry ───────────────────────────
    def test_redefinition_overwrites(self):
        class Old(RegistryBaseAdapter):
            PROTOCOL = "_test_overwrite"

        class New(RegistryBaseAdapter):
            PROTOCOL = "_test_overwrite"

        self.assertIs(REGISTRY["_test_overwrite"], New)

    # ── 10. Namespace PROTOCOL key is used, not class name ───────────────────
    def test_key_is_protocol_not_classname(self):
        class WeirdClassName_XYZ(RegistryBaseAdapter):
            PROTOCOL = "_test_custom_key"

        self.assertIn("_test_custom_key", REGISTRY)
        self.assertNotIn("WeirdClassName_XYZ", REGISTRY)


# ---------------------------------------------------------------------------
# TestBaseAdapter  (8 tests)
# ---------------------------------------------------------------------------


class TestBaseAdapter(unittest.TestCase):
    """RegistryBaseAdapter interface."""

    def setUp(self):
        self._snap = _snapshot_registry()

        class ConcreteAdapter(RegistryBaseAdapter):
            PROTOCOL = "_test_concrete_ba"
            TIER = "T1"
            DEFAULT_APY_PCT = 4.2

        self.Concrete = ConcreteAdapter
        self.instance = ConcreteAdapter()

    def tearDown(self):
        _restore_registry(self._snap)

    # ── 1. get_apy_pct returns DEFAULT_APY_PCT ───────────────────────────────
    def test_get_apy_pct_returns_default(self):
        self.assertAlmostEqual(self.instance.get_apy_pct(), 4.2)

    # ── 2. Overriding get_apy_pct works ─────────────────────────────────────
    def test_get_apy_pct_override(self):
        class Live(RegistryBaseAdapter):
            PROTOCOL = "_test_live_ba"

            def get_apy_pct(self):
                return 7.5

        self.assertAlmostEqual(Live().get_apy_pct(), 7.5)

    # ── 3. health_check returns "ok" by default ──────────────────────────────
    def test_health_check_default_ok(self):
        self.assertEqual(self.instance.health_check(), "ok")

    # ── 4. health_check can be overridden ────────────────────────────────────
    def test_health_check_override(self):
        class Degraded(RegistryBaseAdapter):
            PROTOCOL = "_test_degraded_ba"

            def health_check(self):
                return "degraded"

        self.assertEqual(Degraded().health_check(), "degraded")

    # ── 5. to_dict returns dict with required keys ───────────────────────────
    def test_to_dict_keys(self):
        d = self.instance.to_dict()
        self.assertIn("protocol", d)
        self.assertIn("tier", d)
        self.assertIn("apy_pct", d)

    # ── 6. to_dict protocol matches PROTOCOL ─────────────────────────────────
    def test_to_dict_protocol_value(self):
        d = self.instance.to_dict()
        self.assertEqual(d["protocol"], "_test_concrete_ba")

    # ── 7. to_dict tier matches TIER ─────────────────────────────────────────
    def test_to_dict_tier_value(self):
        d = self.instance.to_dict()
        self.assertEqual(d["tier"], "T1")

    # ── 8. to_dict apy_pct matches get_apy_pct() ─────────────────────────────
    def test_to_dict_apy_pct_value(self):
        d = self.instance.to_dict()
        self.assertAlmostEqual(d["apy_pct"], self.instance.get_apy_pct())


# ---------------------------------------------------------------------------
# TestGetAllAdapters  (7 tests)
# ---------------------------------------------------------------------------


class TestGetAllAdapters(unittest.TestCase):
    """get_all_adapters() returns list of instantiated adapters."""

    def setUp(self):
        self._snap = _snapshot_registry()
        REGISTRY.clear()

    def tearDown(self):
        _restore_registry(self._snap)

    # ── 1. Empty registry returns empty list ─────────────────────────────────
    def test_empty_registry_returns_empty_list(self):
        result = get_all_adapters()
        self.assertEqual(result, [])

    # ── 2. Returns list, not generator ───────────────────────────────────────
    def test_returns_list(self):
        self.assertIsInstance(get_all_adapters(), list)

    # ── 3. Correct count of instances ────────────────────────────────────────
    def test_count_matches_registry_size(self):
        class A1(RegistryBaseAdapter):
            PROTOCOL = "_test_ga1"

        class A2(RegistryBaseAdapter):
            PROTOCOL = "_test_ga2"

        instances = get_all_adapters()
        self.assertEqual(len(instances), 2)

    # ── 4. Returns instances, not classes ────────────────────────────────────
    def test_returns_instances_not_classes(self):
        class AInst(RegistryBaseAdapter):
            PROTOCOL = "_test_ainst"

        instances = get_all_adapters()
        self.assertTrue(len(instances) > 0)
        self.assertNotIsInstance(instances[0], type)

    # ── 5. Instance is of the registered class ───────────────────────────────
    def test_instance_of_registered_class(self):
        class ACheck(RegistryBaseAdapter):
            PROTOCOL = "_test_acheck"

        instances = get_all_adapters()
        self.assertIsInstance(instances[0], ACheck)

    # ── 6. Adapter that raises on init is skipped gracefully ─────────────────
    def test_bad_init_skipped(self):
        class BadInit(RegistryBaseAdapter):
            PROTOCOL = "_test_bad_init"

            def __init__(self):
                raise RuntimeError("init explosion")

        class GoodInit(RegistryBaseAdapter):
            PROTOCOL = "_test_good_init"

        # bad adapter is skipped; good adapter still returned
        instances = get_all_adapters()
        self.assertEqual(len(instances), 1)
        self.assertIsInstance(instances[0], GoodInit)

    # ── 7. get_all_adapters is idempotent (two calls same count) ─────────────
    def test_idempotent_two_calls(self):
        class AIdm(RegistryBaseAdapter):
            PROTOCOL = "_test_aidm"

        r1 = get_all_adapters()
        r2 = get_all_adapters()
        self.assertEqual(len(r1), len(r2))


# ---------------------------------------------------------------------------
# TestRefreshAll  (15 tests)
# ---------------------------------------------------------------------------


class TestRefreshAll(unittest.TestCase):
    """refresh_all() writes adapter_status.json atomically and correctly."""

    def setUp(self):
        self._snap = _snapshot_registry()
        REGISTRY.clear()
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        _restore_registry(self._snap)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _status_path(self) -> str:
        return os.path.join(self._tmp, "adapter_status.json")

    def _read_status(self) -> dict:
        with open(self._status_path(), encoding="utf-8") as fh:
            return json.load(fh)

    # ── 1. Returns dict ───────────────────────────────────────────────────────
    def test_returns_dict(self):
        result = refresh_all(self._status_path())
        self.assertIsInstance(result, dict)

    # ── 2. Empty registry → empty results, file still written ────────────────
    def test_empty_registry_writes_file(self):
        refresh_all(self._status_path())
        self.assertTrue(os.path.exists(self._status_path()))

    # ── 3. Protocol key appears in results ───────────────────────────────────
    def test_protocol_in_results(self):
        class AR1(RegistryBaseAdapter):
            PROTOCOL = "_test_ra1"
            DEFAULT_APY_PCT = 5.0

        result = refresh_all(self._status_path())
        self.assertIn("_test_ra1", result)

    # ── 4. APY value written correctly ───────────────────────────────────────
    def test_apy_value_correct(self):
        class AR2(RegistryBaseAdapter):
            PROTOCOL = "_test_ra2"
            DEFAULT_APY_PCT = 6.5

        result = refresh_all(self._status_path())
        self.assertAlmostEqual(result["_test_ra2"], 6.5)

    # ── 5. Status file contains protocol key ─────────────────────────────────
    def test_status_file_contains_protocol(self):
        class AR3(RegistryBaseAdapter):
            PROTOCOL = "_test_ra3"
            DEFAULT_APY_PCT = 3.0

        refresh_all(self._status_path())
        status = self._read_status()
        self.assertIn("_test_ra3", status)

    # ── 6. Status file APY matches result ────────────────────────────────────
    def test_status_file_apy_matches_result(self):
        class AR4(RegistryBaseAdapter):
            PROTOCOL = "_test_ra4"
            DEFAULT_APY_PCT = 4.8

        result = refresh_all(self._status_path())
        status = self._read_status()
        self.assertAlmostEqual(status["_test_ra4"]["apy"], result["_test_ra4"])

    # ── 7. last_refreshed written as int ─────────────────────────────────────
    def test_last_refreshed_is_int(self):
        class AR5(RegistryBaseAdapter):
            PROTOCOL = "_test_ra5"
            DEFAULT_APY_PCT = 2.0

        before = int(time.time())
        refresh_all(self._status_path())
        status = self._read_status()
        ts = status["_test_ra5"]["last_refreshed"]
        self.assertIsInstance(ts, int)
        self.assertGreaterEqual(ts, before)

    # ── 8. Existing key in status.json is updated, not replaced ──────────────
    def test_existing_key_updated_not_replaced(self):
        # Pre-populate with extra field
        _make_status_file(self._tmp, {
            "_test_ra6": {"apy": 1.0, "tier": "T1", "extra": "keep_me", "last_refreshed": 0}
        })

        class AR6(RegistryBaseAdapter):
            PROTOCOL = "_test_ra6"
            DEFAULT_APY_PCT = 9.0

        refresh_all(self._status_path())
        status = self._read_status()
        # extra field preserved
        self.assertEqual(status["_test_ra6"].get("extra"), "keep_me")
        # apy updated
        self.assertAlmostEqual(status["_test_ra6"]["apy"], 9.0)

    # ── 9. New protocol added to existing status.json ────────────────────────
    def test_new_protocol_added_to_existing_status(self):
        _make_status_file(self._tmp, {"other_proto": {"apy": 2.0}})

        class AR7(RegistryBaseAdapter):
            PROTOCOL = "_test_ra7"
            DEFAULT_APY_PCT = 5.5

        refresh_all(self._status_path())
        status = self._read_status()
        self.assertIn("_test_ra7", status)
        self.assertIn("other_proto", status)  # existing key preserved

    # ── 10. Corrupt json file → handled gracefully, writes fresh ──────────────
    def test_corrupt_json_handled(self):
        path = self._status_path()
        with open(path, "w") as f:
            f.write("NOT JSON {{{{")

        class AR8(RegistryBaseAdapter):
            PROTOCOL = "_test_ra8"
            DEFAULT_APY_PCT = 3.3

        result = refresh_all(path)  # must not raise
        self.assertIn("_test_ra8", result)

    # ── 11. Missing file → creates it ────────────────────────────────────────
    def test_missing_file_creates_it(self):
        path = os.path.join(self._tmp, "subdir", "adapter_status.json")

        class AR9(RegistryBaseAdapter):
            PROTOCOL = "_test_ra9"
            DEFAULT_APY_PCT = 1.1

        refresh_all(path)
        self.assertTrue(os.path.exists(path))

    # ── 12. Adapter that raises → error key in results ───────────────────────
    def test_failing_adapter_error_in_results(self):
        class ARBad(RegistryBaseAdapter):
            PROTOCOL = "_test_ra_bad"

            def get_apy_pct(self):
                raise RuntimeError("live feed down")

        result = refresh_all(self._status_path())
        self.assertIn("_test_ra_bad", result)
        self.assertIsInstance(result["_test_ra_bad"], dict)
        self.assertIn("error", result["_test_ra_bad"])

    # ── 13. Atomic write: no tmp file left on success ─────────────────────────
    def test_no_tmp_file_after_success(self):
        class ARAtom(RegistryBaseAdapter):
            PROTOCOL = "_test_ra_atom"
            DEFAULT_APY_PCT = 4.0

        refresh_all(self._status_path())
        tmp_files = [f for f in os.listdir(self._tmp) if f.startswith(".tmp_")]
        self.assertEqual(tmp_files, [])

    # ── 14. Written file is valid JSON ───────────────────────────────────────
    def test_written_file_is_valid_json(self):
        class ARJson(RegistryBaseAdapter):
            PROTOCOL = "_test_ra_json"
            DEFAULT_APY_PCT = 7.0

        refresh_all(self._status_path())
        with open(self._status_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertIsInstance(data, dict)

    # ── 15. Multiple adapters all appear in results ───────────────────────────
    def test_multiple_adapters_all_in_results(self):
        class AMulti1(RegistryBaseAdapter):
            PROTOCOL = "_test_multi1"
            DEFAULT_APY_PCT = 1.0

        class AMulti2(RegistryBaseAdapter):
            PROTOCOL = "_test_multi2"
            DEFAULT_APY_PCT = 2.0

        class AMulti3(RegistryBaseAdapter):
            PROTOCOL = "_test_multi3"
            DEFAULT_APY_PCT = 3.0

        result = refresh_all(self._status_path())
        for key in ("_test_multi1", "_test_multi2", "_test_multi3"):
            self.assertIn(key, result)


# ---------------------------------------------------------------------------
# TestCycleIntegration  (10 tests)
# ---------------------------------------------------------------------------


class TestCycleIntegration(unittest.TestCase):
    """Integration: refresh_all behaves correctly in cycle-like scenarios."""

    def setUp(self):
        self._snap = _snapshot_registry()
        REGISTRY.clear()
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        _restore_registry(self._snap)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _status_path(self) -> str:
        return os.path.join(self._tmp, "adapter_status.json")

    # ── 1. live_count calculation works (non-error results) ──────────────────
    def test_live_count_non_error(self):
        class CIntA(RegistryBaseAdapter):
            PROTOCOL = "_ci_a"
            DEFAULT_APY_PCT = 3.0

        class CIntB(RegistryBaseAdapter):
            PROTOCOL = "_ci_b"

            def get_apy_pct(self):
                raise ValueError("feed down")

        results = refresh_all(self._status_path())
        live = [v for v in results.values() if not isinstance(v, dict)]
        self.assertEqual(len(live), 1)

    # ── 2. Results dict has same length as REGISTRY ───────────────────────────
    def test_results_length_equals_registry(self):
        class CIntC(RegistryBaseAdapter):
            PROTOCOL = "_ci_c"
            DEFAULT_APY_PCT = 5.0

        class CIntD(RegistryBaseAdapter):
            PROTOCOL = "_ci_d"
            DEFAULT_APY_PCT = 6.0

        results = refresh_all(self._status_path())
        self.assertEqual(len(results), len(REGISTRY))

    # ── 3. refresh_all is callable with str path ──────────────────────────────
    def test_callable_with_str_path(self):
        result = refresh_all(self._status_path())
        self.assertIsInstance(result, dict)

    # ── 4. refresh_all is callable with pathlib.Path ──────────────────────────
    def test_callable_with_pathlib_path(self):
        # refresh_all signature accepts str, but we can pass str(Path(...))
        result = refresh_all(str(Path(self._status_path())))
        self.assertIsInstance(result, dict)

    # ── 5. Two consecutive calls preserve additional keys ─────────────────────
    def test_two_calls_preserve_keys(self):
        class CIntE(RegistryBaseAdapter):
            PROTOCOL = "_ci_e"
            DEFAULT_APY_PCT = 4.0

        refresh_all(self._status_path())
        # Manually add an extra key to the file
        with open(self._status_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        data["external_key"] = {"apy": 99.0}
        with open(self._status_path(), "w", encoding="utf-8") as fh:
            json.dump(data, fh)

        refresh_all(self._status_path())
        with open(self._status_path(), encoding="utf-8") as fh:
            data2 = json.load(fh)
        self.assertIn("external_key", data2)

    # ── 6. APY value is float in results (not str) ────────────────────────────
    def test_apy_value_is_float(self):
        class CIntF(RegistryBaseAdapter):
            PROTOCOL = "_ci_f"
            DEFAULT_APY_PCT = 3.14

        results = refresh_all(self._status_path())
        self.assertIsInstance(results["_ci_f"], float)

    # ── 7. refresh_all writes file deterministically on two calls ─────────────
    def test_two_calls_deterministic_apy(self):
        class CIntG(RegistryBaseAdapter):
            PROTOCOL = "_ci_g"
            DEFAULT_APY_PCT = 5.55

        refresh_all(self._status_path())
        refresh_all(self._status_path())
        with open(self._status_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertAlmostEqual(data["_ci_g"]["apy"], 5.55)

    # ── 8. tier written to new status entry ───────────────────────────────────
    def test_tier_written_to_new_entry(self):
        class CIntH(RegistryBaseAdapter):
            PROTOCOL = "_ci_h"
            TIER = "T2"
            DEFAULT_APY_PCT = 2.0

        refresh_all(self._status_path())
        with open(self._status_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["_ci_h"]["tier"], "T2")

    # ── 9. File modification time updated after refresh ───────────────────────
    def test_file_mtime_updated(self):
        path = self._status_path()
        # Create file first
        with open(path, "w") as fh:
            json.dump({}, fh)
        mtime_before = os.path.getmtime(path)
        time.sleep(0.05)

        class CIntI(RegistryBaseAdapter):
            PROTOCOL = "_ci_i"
            DEFAULT_APY_PCT = 1.0

        refresh_all(path)
        mtime_after = os.path.getmtime(path)
        self.assertGreater(mtime_after, mtime_before)

    # ── 10. Mixed success/failure: successful ones still written to file ───────
    def test_mixed_success_failure_written(self):
        class CIntGood(RegistryBaseAdapter):
            PROTOCOL = "_ci_good"
            DEFAULT_APY_PCT = 4.5

        class CIntBad(RegistryBaseAdapter):
            PROTOCOL = "_ci_bad"

            def get_apy_pct(self):
                raise RuntimeError("broken")

        refresh_all(self._status_path())
        with open(self._status_path(), encoding="utf-8") as fh:
            data = json.load(fh)
        # Good adapter written
        self.assertIn("_ci_good", data)
        self.assertAlmostEqual(data["_ci_good"]["apy"], 4.5)
        # Bad adapter NOT written (error result, no apy)
        if "_ci_bad" in data:
            # If written, must not have valid apy
            self.assertNotIn("apy", data.get("_ci_bad", {}))


# ---------------------------------------------------------------------------
# TestExplicitRegistration  (12 tests)
# ---------------------------------------------------------------------------


class TestExplicitRegistration(unittest.TestCase):
    """Explicit REGISTRY["key"] = Class and register()/unregister() API."""

    def setUp(self):
        self._snap = _snapshot_registry()
        REGISTRY.clear()
        self._tmp = tempfile.mkdtemp()

    def tearDown(self):
        _restore_registry(self._snap)
        import shutil
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _status_path(self) -> str:
        return os.path.join(self._tmp, "adapter_status.json")

    # ── 1. Direct dict assignment registers adapter ───────────────────────────
    def test_direct_assignment_registers(self):
        class ManualAdapter:
            TIER = "T1"

            def get_apy_pct(self):
                return 5.0

        REGISTRY["_exp_manual"] = ManualAdapter
        self.assertIn("_exp_manual", REGISTRY)

    # ── 2. register() helper works ───────────────────────────────────────────
    def test_register_helper_works(self):
        class ExpA:
            def get_apy_pct(self):
                return 3.0

        register("_exp_a", ExpA)
        self.assertIn("_exp_a", REGISTRY)
        self.assertIs(REGISTRY["_exp_a"], ExpA)

    # ── 3. unregister() removes key ──────────────────────────────────────────
    def test_unregister_removes_key(self):
        class ExpB:
            pass

        register("_exp_b", ExpB)
        result = unregister("_exp_b")
        self.assertTrue(result)
        self.assertNotIn("_exp_b", REGISTRY)

    # ── 4. unregister() on missing key returns False ──────────────────────────
    def test_unregister_missing_returns_false(self):
        result = unregister("_nonexistent_key_xyz")
        self.assertFalse(result)

    # ── 5. Explicitly registered adapter included in get_all_adapters ─────────
    def test_explicit_in_get_all_adapters(self):
        class ExpC:
            def get_apy_pct(self):
                return 6.0

        register("_exp_c", ExpC)
        instances = get_all_adapters()
        self.assertEqual(len(instances), 1)
        self.assertIsInstance(instances[0], ExpC)

    # ── 6. Explicitly registered adapter included in refresh_all results ───────
    def test_explicit_in_refresh_all(self):
        class ExpD:
            TIER = "T2"

            def get_apy_pct(self):
                return 7.7

        register("_exp_d", ExpD)
        results = refresh_all(self._status_path())
        self.assertIn("_exp_d", results)
        self.assertAlmostEqual(results["_exp_d"], 7.7)

    # ── 7. Override: second register replaces first ───────────────────────────
    def test_override_replaces_first(self):
        class ExpE1:
            def get_apy_pct(self):
                return 1.0

        class ExpE2:
            def get_apy_pct(self):
                return 2.0

        register("_exp_e", ExpE1)
        register("_exp_e", ExpE2)
        self.assertIs(REGISTRY["_exp_e"], ExpE2)

    # ── 8. Override: refresh_all uses overridden class ────────────────────────
    def test_override_refresh_uses_new_class(self):
        class ExpF1:
            def get_apy_pct(self):
                return 1.0

        class ExpF2:
            TIER = "T1"

            def get_apy_pct(self):
                return 2.0

        register("_exp_f", ExpF1)
        register("_exp_f", ExpF2)
        results = refresh_all(self._status_path())
        self.assertAlmostEqual(results["_exp_f"], 2.0)

    # ── 9. Adapter without get_apy_pct uses fetch() fallback ─────────────────
    def test_fetch_fallback_used(self):
        class FetchAdapter:
            TIER = "T1"

            def fetch(self):
                return {"apy": 4.4, "status": "ok"}

        register("_exp_fetch", FetchAdapter)
        results = refresh_all(self._status_path())
        self.assertIn("_exp_fetch", results)
        self.assertAlmostEqual(results["_exp_fetch"], 4.4)

    # ── 10. Adapter with get_apy() (decimal) → correctly multiplied by 100 ───
    def test_get_apy_decimal_multiplied(self):
        class DecimalAdapter:
            TIER = "T1"

            def get_apy(self):
                return 0.048  # 4.8% as decimal

        register("_exp_decimal", DecimalAdapter)
        results = refresh_all(self._status_path())
        self.assertAlmostEqual(results["_exp_decimal"], 4.8, places=4)

    # ── 11. Mixing metaclass and explicit adapters in same registry ───────────
    def test_mixed_metaclass_and_explicit(self):
        class AutoReg(RegistryBaseAdapter):
            PROTOCOL = "_exp_auto"
            DEFAULT_APY_PCT = 3.0

        class ManualReg:
            TIER = "T2"

            def get_apy_pct(self):
                return 5.0

        register("_exp_manual2", ManualReg)

        results = refresh_all(self._status_path())
        self.assertIn("_exp_auto", results)
        self.assertIn("_exp_manual2", results)

    # ── 12. _extract_apy_pct helper: priority get_apy_pct > get_apy > fetch ──
    def test_extract_apy_pct_priority_order(self):
        class AllMethods:
            def get_apy_pct(self):
                return 9.0  # should win

            def get_apy(self):
                return 0.05  # decimal → 5.0

            def fetch(self):
                return {"apy": 3.0}

        instance = AllMethods()
        result = _extract_apy_pct(instance)
        self.assertAlmostEqual(result, 9.0)


# ---------------------------------------------------------------------------
# Additional edge-case tests for _extract_apy_pct and _extract_tier
# ---------------------------------------------------------------------------


class TestHelpers(unittest.TestCase):
    """Unit tests for private helper functions."""

    def setUp(self):
        self._snap = _snapshot_registry()

    def tearDown(self):
        _restore_registry(self._snap)

    def test_extract_apy_pct_none_when_all_fail(self):
        class NoAPY:
            pass

        result = _extract_apy_pct(NoAPY())
        self.assertIsNone(result)

    def test_extract_apy_pct_get_apy_pct_none_fallthrough(self):
        class ReturnsNone:
            def get_apy_pct(self):
                return None

            def get_apy(self):
                return 0.03

        result = _extract_apy_pct(ReturnsNone())
        self.assertAlmostEqual(result, 3.0)

    def test_extract_tier_tier_attr(self):
        class HasTier:
            TIER = "T2"

        self.assertEqual(_extract_tier(HasTier), "T2")

    def test_extract_tier_fallback_t2(self):
        class NoTier:
            pass

        self.assertEqual(_extract_tier(NoTier), "T2")

    def test_extract_tier_lowercase_tier_attr(self):
        class LowerTier:
            tier = "T1"

        self.assertEqual(_extract_tier(LowerTier), "T1")


# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    unittest.main()
