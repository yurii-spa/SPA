"""
spa_core/tests/test_strategy_registry.py

Tests for StrategyMeta and StrategyRegistry (spa_core/strategies/strategy_registry.py).

MP-1459 (v10.75) — Sprint 1 coverage expansion.

Run:
    python3 -m pytest spa_core/tests/test_strategy_registry.py -v
    python3 -m unittest spa_core/tests/test_strategy_registry.py
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spa_core.strategies.strategy_registry import (
    StrategyMeta,
    StrategyRegistry,
    VALID_TYPES,
    VALID_RISK_TIERS,
)
from spa_core.utils.errors import RegistryError


# ─── helpers ──────────────────────────────────────────────────────────────────

def _meta(
    id="test_strat",
    name="Test Strategy",
    stype="lending",
    tier="T1",
    apy_min=3.0,
    apy_max=6.0,
    max_dd=2.0,
    desc="A test strategy",
    module="spa_core.strategies.baseline",
    handler="BaselineStrategy",
    tags=None,
    enabled=True,
) -> StrategyMeta:
    return StrategyMeta(
        id=id,
        name=name,
        type=stype,
        risk_tier=tier,
        target_apy_min=apy_min,
        target_apy_max=apy_max,
        max_drawdown_pct=max_dd,
        description=desc,
        module=module,
        handler_class=handler,
        tags=tags or [],
        enabled=enabled,
    )


# ─── StrategyMeta Tests ───────────────────────────────────────────────────────

class TestStrategyMeta(unittest.TestCase):

    def test_valid_construction(self):
        m = _meta()
        self.assertEqual(m.id, "test_strat")
        self.assertEqual(m.name, "Test Strategy")
        self.assertEqual(m.type, "lending")
        self.assertEqual(m.risk_tier, "T1")
        self.assertAlmostEqual(m.target_apy_min, 3.0)
        self.assertAlmostEqual(m.target_apy_max, 6.0)
        self.assertTrue(m.enabled)

    def test_invalid_type_raises(self):
        with self.assertRaises(ValueError):
            _meta(stype="unknown_type")

    def test_invalid_tier_raises(self):
        with self.assertRaises(ValueError):
            _meta(tier="T4")

    def test_apy_min_gte_max_raises(self):
        with self.assertRaises(ValueError):
            _meta(apy_min=6.0, apy_max=3.0)

    def test_apy_min_eq_max_raises(self):
        with self.assertRaises(ValueError):
            _meta(apy_min=5.0, apy_max=5.0)

    def test_apy_midpoint(self):
        m = _meta(apy_min=4.0, apy_max=8.0)
        self.assertAlmostEqual(m.apy_midpoint, 6.0)

    def test_apy_midpoint_asymmetric(self):
        m = _meta(apy_min=1.0, apy_max=9.0)
        self.assertAlmostEqual(m.apy_midpoint, 5.0)

    def test_to_dict_returns_dict(self):
        m = _meta()
        d = m.to_dict()
        self.assertIsInstance(d, dict)
        self.assertEqual(d["id"], "test_strat")
        self.assertEqual(d["type"], "lending")
        self.assertEqual(d["risk_tier"], "T1")

    def test_to_dict_contains_all_fields(self):
        m = _meta(tags=["conservative", "t1"])
        d = m.to_dict()
        expected = {
            "id", "name", "type", "risk_tier",
            "target_apy_min", "target_apy_max", "max_drawdown_pct",
            "description", "module", "handler_class", "tags", "enabled",
        }
        self.assertEqual(set(d.keys()), expected)

    def test_all_valid_types_accepted(self):
        for stype in VALID_TYPES:
            m = _meta(stype=stype)
            self.assertEqual(m.type, stype)

    def test_all_valid_tiers_accepted(self):
        for tier in VALID_RISK_TIERS:
            m = _meta(tier=tier)
            self.assertEqual(m.risk_tier, tier)

    def test_tags_default_empty(self):
        m = _meta()
        self.assertEqual(m.tags, [])

    def test_tags_stored(self):
        m = _meta(tags=["yield", "stable"])
        self.assertIn("yield", m.tags)
        self.assertIn("stable", m.tags)

    def test_enabled_default_true(self):
        m = _meta()
        self.assertTrue(m.enabled)

    def test_disabled_stored(self):
        m = _meta(enabled=False)
        self.assertFalse(m.enabled)

    def test_max_drawdown_pct_stored(self):
        m = _meta(max_dd=5.0)
        self.assertAlmostEqual(m.max_drawdown_pct, 5.0)


# ─── StrategyRegistry Tests ───────────────────────────────────────────────────

class TestStrategyRegistry(unittest.TestCase):

    def _fresh_registry(self) -> StrategyRegistry:
        """Return an empty registry isolated from the global singleton."""
        return StrategyRegistry()

    def test_empty_registry_len(self):
        r = self._fresh_registry()
        self.assertEqual(len(r), 0)

    def test_register_adds_strategy(self):
        r = self._fresh_registry()
        m = _meta(id="s_a")
        r.register(m)
        self.assertEqual(len(r), 1)

    def test_get_existing(self):
        r = self._fresh_registry()
        m = _meta(id="s_a")
        r.register(m)
        self.assertIs(r.get("s_a"), m)

    def test_get_missing_returns_none(self):
        r = self._fresh_registry()
        self.assertIsNone(r.get("nonexistent"))

    def test_register_idempotent_same_object(self):
        r = self._fresh_registry()
        m = _meta(id="s_a")
        r.register(m)
        r.register(m)  # same object → should not raise
        self.assertEqual(len(r), 1)

    def test_register_duplicate_id_different_meta_raises(self):
        r = self._fresh_registry()
        m1 = _meta(id="s_a", name="Alpha")
        m2 = _meta(id="s_a", name="Beta")
        r.register(m1)
        with self.assertRaises(RegistryError):
            r.register(m2)

    def test_unregister_removes_strategy(self):
        r = self._fresh_registry()
        m = _meta(id="s_a")
        r.register(m)
        r.unregister("s_a")
        self.assertIsNone(r.get("s_a"))
        self.assertEqual(len(r), 0)

    def test_unregister_nonexistent_noop(self):
        r = self._fresh_registry()
        r.unregister("does_not_exist")  # should not raise

    def test_get_all_enabled_only(self):
        r = self._fresh_registry()
        r.register(_meta(id="s_active", enabled=True))
        r.register(_meta(id="s_disabled", enabled=False))
        all_enabled = r.get_all(enabled_only=True)
        self.assertIn("s_active", all_enabled)
        self.assertNotIn("s_disabled", all_enabled)

    def test_get_all_include_disabled(self):
        r = self._fresh_registry()
        r.register(_meta(id="s_active", enabled=True))
        r.register(_meta(id="s_disabled", enabled=False))
        all_strats = r.get_all(enabled_only=False)
        self.assertIn("s_active", all_strats)
        self.assertIn("s_disabled", all_strats)

    def test_as_list_returns_list(self):
        r = self._fresh_registry()
        r.register(_meta(id="s_a"))
        result = r.as_list()
        self.assertIsInstance(result, list)
        self.assertEqual(len(result), 1)

    def test_as_list_sorted_by_tier_then_apy(self):
        r = self._fresh_registry()
        r.register(_meta(id="t2_low",  tier="T2", apy_min=3.0, apy_max=6.0))
        r.register(_meta(id="t1_high", tier="T1", apy_min=5.0, apy_max=8.0))
        r.register(_meta(id="t1_low",  tier="T1", apy_min=2.0, apy_max=4.0))
        lst = r.as_list()
        ids = [s.id for s in lst]
        # T1 strategies must come before T2
        self.assertLess(ids.index("t1_low"), ids.index("t2_low"))
        self.assertLess(ids.index("t1_high"), ids.index("t2_low"))

    def test_get_by_tier_filters(self):
        r = self._fresh_registry()
        r.register(_meta(id="s_t1", tier="T1"))
        r.register(_meta(id="s_t2", tier="T2"))
        r.register(_meta(id="s_t3", tier="T3"))
        t1_list = r.get_by_tier("T1")
        self.assertEqual(len(t1_list), 1)
        self.assertEqual(t1_list[0].id, "s_t1")

    def test_get_by_tier_no_results(self):
        r = self._fresh_registry()
        r.register(_meta(id="s_t1", tier="T1"))
        self.assertEqual(r.get_by_tier("T3"), [])

    def test_get_by_type_filters(self):
        r = self._fresh_registry()
        r.register(_meta(id="s_lend", stype="lending"))
        r.register(_meta(id="s_lp",   stype="lp"))
        lend = r.get_by_type("lending")
        self.assertEqual(len(lend), 1)
        self.assertEqual(lend[0].id, "s_lend")

    def test_get_by_type_empty_when_no_match(self):
        r = self._fresh_registry()
        r.register(_meta(id="s_lend", stype="lending"))
        self.assertEqual(r.get_by_type("yield_loop"), [])

    def test_summary_structure(self):
        r = self._fresh_registry()
        r.register(_meta(id="s_a", tags=["x"]))
        s = r.summary()
        self.assertIsInstance(s, list)
        self.assertEqual(len(s), 1)
        entry = s[0]
        self.assertIn("id", entry)
        self.assertIn("name", entry)
        self.assertIn("type", entry)
        self.assertIn("risk_tier", entry)
        self.assertIn("target_apy_range", entry)
        self.assertIn("enabled", entry)
        self.assertIn("tags", entry)

    def test_repr_includes_count(self):
        r = self._fresh_registry()
        r.register(_meta(id="s_a"))
        r.register(_meta(id="s_b"))
        s = repr(r)
        self.assertIn("2", s)

    def test_multiple_tiers_and_types(self):
        r = self._fresh_registry()
        combos = [
            ("x1", "lending", "T1"),
            ("x2", "lp",      "T2"),
            ("x3", "yield_loop", "T3"),
            ("x4", "wrapped", "T1"),
        ]
        for sid, stype, tier in combos:
            r.register(_meta(id=sid, stype=stype, tier=tier))
        self.assertEqual(len(r), 4)
        self.assertEqual(len(r.get_by_tier("T1")), 2)
        self.assertEqual(len(r.get_by_type("lp")), 1)


if __name__ == "__main__":
    unittest.main()
