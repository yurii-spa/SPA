"""
tests/test_spa_public_api.py

MP-1383 (v9.99) — Public API acceptance tests for spa_core v10.0.

25 tests verifying:
- clean import
- VERSION / VERSION_TUPLE
- __all__ completeness
- callable utils not None
- error hierarchy
- ADAPTER_REGISTRY is a dict
- BacktestGate can be instantiated

Stdlib only — no external dependencies.
"""

import sys
import unittest
import importlib


class TestSpaImport(unittest.TestCase):
    """T-001  Clean import"""

    def test_import_no_exception(self):
        """import spa_core must not raise any exception."""
        # Already imported by the time this runs; re-import to be explicit.
        import spa_core  # noqa: F401


class TestSpaVersion(unittest.TestCase):
    """T-002/003/004/024/025  Version fields"""

    def setUp(self):
        import spa_core
        self.mod = spa_core

    def test_version_string(self):
        """spa_core.VERSION must equal '10.0.0'."""
        self.assertEqual(self.mod.VERSION, "10.0.0")

    def test_version_tuple(self):
        """spa_core.VERSION_TUPLE must equal (10, 0, 0)."""
        self.assertEqual(self.mod.VERSION_TUPLE, (10, 0, 0))

    def test_version_tuple_type(self):
        """spa_core.VERSION_TUPLE must be a tuple."""
        self.assertIsInstance(self.mod.VERSION_TUPLE, tuple)

    def test_dunder_version(self):
        """spa_core.__version__ must equal '10.0.0'."""
        self.assertEqual(self.mod.__version__, "10.0.0")

    def test_version_module_direct(self):
        """spa_core.version.VERSION must equal '10.0.0'."""
        import spa_core.version as v
        self.assertEqual(v.VERSION, "10.0.0")


class TestSpaDunderAll(unittest.TestCase):
    """T-005/014  __all__ completeness"""

    def setUp(self):
        import spa_core
        self.all = spa_core.__all__

    def test_all_contains_backtest_gate(self):
        self.assertIn("BacktestGate", self.all)

    def test_all_contains_pit_engine(self):
        self.assertIn("PITEngine", self.all)

    def test_all_contains_rs001(self):
        self.assertIn("RS001LiveAPYEngine", self.all)

    def test_all_contains_rs002(self):
        self.assertIn("RS002LiveAPYEngine", self.all)

    def test_all_contains_atomic_save(self):
        self.assertIn("atomic_save", self.all)

    def test_all_contains_atomic_load(self):
        self.assertIn("atomic_load", self.all)

    def test_all_contains_spa_error(self):
        self.assertIn("SPAError", self.all)

    def test_all_contains_gate_error(self):
        self.assertIn("GateError", self.all)

    def test_all_contains_source_error(self):
        self.assertIn("SourceError", self.all)

    def test_all_contains_adapter_registry(self):
        self.assertIn("ADAPTER_REGISTRY", self.all)

    def test_all_contains_version(self):
        self.assertIn("VERSION", self.all)

    def test_all_contains_version_tuple(self):
        self.assertIn("VERSION_TUPLE", self.all)


class TestSpaUtils(unittest.TestCase):
    """T-015/018  Utils not None and callable"""

    def setUp(self):
        import spa_core
        self.mod = spa_core

    def test_atomic_save_not_none(self):
        self.assertIsNotNone(self.mod.atomic_save)

    def test_atomic_save_callable(self):
        self.assertTrue(callable(self.mod.atomic_save))

    def test_atomic_load_not_none(self):
        self.assertIsNotNone(self.mod.atomic_load)

    def test_atomic_load_callable(self):
        self.assertTrue(callable(self.mod.atomic_load))


class TestSpaErrors(unittest.TestCase):
    """T-019/021  Error hierarchy"""

    def setUp(self):
        import spa_core
        self.mod = spa_core

    def test_spa_error_not_none(self):
        """spa_core.SPAError must not be None."""
        self.assertIsNotNone(self.mod.SPAError)

    def test_gate_error_subclass_of_spa_error(self):
        """GateError must be a subclass of SPAError."""
        self.assertTrue(issubclass(self.mod.GateError, self.mod.SPAError))

    def test_source_error_subclass_of_spa_error(self):
        """SourceError must be a subclass of SPAError."""
        self.assertTrue(issubclass(self.mod.SourceError, self.mod.SPAError))

    def test_spa_error_is_exception(self):
        """SPAError must be a subclass of Exception."""
        self.assertTrue(issubclass(self.mod.SPAError, Exception))


class TestSpaAdapterRegistry(unittest.TestCase):
    """T-022  ADAPTER_REGISTRY is a dict"""

    def test_adapter_registry_is_dict(self):
        import spa_core
        self.assertIsInstance(spa_core.ADAPTER_REGISTRY, dict)


class TestSpaBacktestGate(unittest.TestCase):
    """T-023  BacktestGate can be instantiated"""

    def test_backtest_gate_not_none(self):
        import spa_core
        self.assertIsNotNone(spa_core.BacktestGate)

    def test_backtest_gate_instantiation(self):
        """BacktestGate() must be instantiable (no required live-data args)."""
        import spa_core
        gate = spa_core.BacktestGate()
        self.assertIsNotNone(gate)


if __name__ == "__main__":
    unittest.main(verbosity=2)
