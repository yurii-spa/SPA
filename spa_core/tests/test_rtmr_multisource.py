"""RTMR (ADR-053) S10.3a multi-source quorum tests — fail-closed cross-validation."""
from __future__ import annotations

import unittest

from spa_core.monitoring.sensors import _multisource as M


class TestQuorum(unittest.TestCase):
    def test_agreement_returns_median_ok(self) -> None:
        r = M.quorum({"a": 1.000, "b": 1.001, "c": 0.999}, min_quorum=3, max_spread=0.02)
        self.assertTrue(r.ok)
        self.assertAlmostEqual(r.value, 1.000, places=3)
        self.assertEqual(r.n_fresh, 3)

    def test_too_few_sources_not_ok(self) -> None:
        r = M.quorum({"a": 1.0, "b": 1.0}, min_quorum=3)
        self.assertFalse(r.ok)
        self.assertIsNone(r.value)
        self.assertIn("quorum", r.reason)

    def test_disagreement_not_ok(self) -> None:
        # one source way off → split feed is itself a risk, never averaged away
        r = M.quorum({"a": 1.00, "b": 1.00, "c": 1.10}, min_quorum=3, max_spread=0.02)
        self.assertFalse(r.ok)
        self.assertIsNone(r.value)
        self.assertIn("disagree", r.reason)

    def test_median_robust_to_outlier_within_tolerance(self) -> None:
        r = M.quorum({"a": 1.000, "b": 1.001, "c": 1.002, "d": 1.0015}, min_quorum=3, max_spread=0.02)
        self.assertTrue(r.ok)

    def test_empty_not_ok(self) -> None:
        r = M.quorum({}, min_quorum=3)
        self.assertFalse(r.ok)
        self.assertEqual(r.n_fresh, 0)


class TestCollect(unittest.TestCase):
    def test_raising_and_none_providers_dropped(self) -> None:
        def good():
            return 1.0
        def raises():
            raise RuntimeError("down")
        def none():
            return None
        def naninf():
            return float("inf")
        got = M.collect({"good": good, "raises": raises, "none": none, "inf": naninf})
        self.assertEqual(got, {"good": 1.0})  # only the finite one survives

    def test_quorum_from_end_to_end(self) -> None:
        providers = {n: (lambda v=v: v) for n, v in {"a": 1.0, "b": 1.001, "c": 0.999}.items()}
        r = M.quorum_from(providers, min_quorum=3, max_spread=0.02)
        self.assertTrue(r.ok)

    def test_quorum_from_failclosed_when_sources_die(self) -> None:
        def dead():
            raise RuntimeError("x")
        providers = {"a": lambda: 1.0, "b": dead, "c": dead}
        r = M.quorum_from(providers, min_quorum=3)
        self.assertFalse(r.ok)  # only 1 fresh < quorum 3


if __name__ == "__main__":
    unittest.main()
