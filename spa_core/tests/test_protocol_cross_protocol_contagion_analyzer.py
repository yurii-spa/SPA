"""
Tests for MP-927 ProtocolCrossProtocolContagionAnalyzer.
Run: python3 -m unittest spa_core.tests.test_protocol_cross_protocol_contagion_analyzer
"""

import json
import os
import sys
import tempfile
import unittest

# Ensure repo root on path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from spa_core.analytics.protocol_cross_protocol_contagion_analyzer import (
    ProtocolCrossProtocolContagionAnalyzer,
    _contagion_label,
    _detect_cycles,
    FLAG_CIRCULAR_DEPENDENCY,
    FLAG_SINGLE_ORACLE_DEPENDENCY,
    FLAG_SYSTEMIC_EXPOSURE,
    FLAG_HIGH_EXPOSURE_RATIO,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_dep(
    protocol_name="Aave",
    dependency_type="liquidity",
    exposure_usd=100_000.0,
    critical=False,
) -> dict:
    return {
        "protocol_name": protocol_name,
        "dependency_type": dependency_type,
        "exposure_usd": exposure_usd,
        "critical": critical,
    }


def make_protocol(
    name="ProtA",
    tvl_usd=1_000_000.0,
    dependencies=None,
    protocol_type="lending",
    chain="ethereum",
    is_systemic=False,
) -> dict:
    return {
        "name": name,
        "tvl_usd": tvl_usd,
        "dependencies": dependencies or [],
        "protocol_type": protocol_type,
        "chain": chain,
        "is_systemic": is_systemic,
    }


class TestContagionLabel(unittest.TestCase):
    """Unit tests for _contagion_label helper."""

    def test_isolated_at_0(self):
        self.assertEqual(_contagion_label(0.0), "ISOLATED")

    def test_isolated_at_10(self):
        self.assertEqual(_contagion_label(10.0), "ISOLATED")

    def test_low_at_11(self):
        self.assertEqual(_contagion_label(11.0), "LOW")

    def test_low_at_30(self):
        self.assertEqual(_contagion_label(30.0), "LOW")

    def test_moderate_at_31(self):
        self.assertEqual(_contagion_label(31.0), "MODERATE")

    def test_moderate_at_50(self):
        self.assertEqual(_contagion_label(50.0), "MODERATE")

    def test_high_at_51(self):
        self.assertEqual(_contagion_label(51.0), "HIGH")

    def test_high_at_70(self):
        self.assertEqual(_contagion_label(70.0), "HIGH")

    def test_systemic_at_71(self):
        self.assertEqual(_contagion_label(71.0), "SYSTEMIC")

    def test_systemic_at_100(self):
        self.assertEqual(_contagion_label(100.0), "SYSTEMIC")


class TestDetectCycles(unittest.TestCase):
    """Unit tests for _detect_cycles helper."""

    def test_no_cycle_empty(self):
        self.assertEqual(_detect_cycles({}), set())

    def test_no_cycle_single_node(self):
        self.assertEqual(_detect_cycles({"A": []}), set())

    def test_no_cycle_chain(self):
        graph = {"A": ["B"], "B": ["C"], "C": []}
        self.assertEqual(_detect_cycles(graph), set())

    def test_simple_cycle_two_nodes(self):
        graph = {"A": ["B"], "B": ["A"]}
        result = _detect_cycles(graph)
        self.assertIn("A", result)
        self.assertIn("B", result)

    def test_three_node_cycle(self):
        graph = {"A": ["B"], "B": ["C"], "C": ["A"]}
        result = _detect_cycles(graph)
        self.assertIn("A", result)
        self.assertIn("B", result)
        self.assertIn("C", result)

    def test_no_cycle_dag(self):
        graph = {"A": ["B", "C"], "B": ["D"], "C": ["D"], "D": []}
        self.assertEqual(_detect_cycles(graph), set())

    def test_self_loop_treated_as_cycle(self):
        # A depends on itself
        graph = {"A": ["A"]}
        result = _detect_cycles(graph)
        self.assertIn("A", result)

    def test_external_dep_not_in_cycle_set(self):
        # A depends on External (not in graph)
        graph = {"A": ["External"]}
        result = _detect_cycles(graph)
        self.assertEqual(result, set())

    def test_cycle_isolated_from_non_cycle(self):
        graph = {"A": ["B"], "B": ["A"], "C": ["D"], "D": []}
        result = _detect_cycles(graph)
        self.assertIn("A", result)
        self.assertIn("B", result)
        self.assertNotIn("C", result)
        self.assertNotIn("D", result)


class TestAnalyzerBasic(unittest.TestCase):
    """Integration tests for ProtocolCrossProtocolContagionAnalyzer.analyze()."""

    def setUp(self):
        self.analyzer = ProtocolCrossProtocolContagionAnalyzer()
        self.tmpdir = tempfile.mkdtemp()

    def _run(self, protocols, config=None):
        return self.analyzer.analyze(
            protocols, config or {}, data_dir=self.tmpdir, dry_run=True
        )

    def test_result_has_protocols_key(self):
        result = self._run([make_protocol()])
        self.assertIn("protocols", result)

    def test_result_has_aggregates_key(self):
        result = self._run([make_protocol()])
        self.assertIn("aggregates", result)

    def test_protocol_name_in_result(self):
        result = self._run([make_protocol(name="Aave")])
        self.assertIn("Aave", result["protocols"])

    def test_per_protocol_result_keys(self):
        result = self._run([make_protocol()])
        pr = result["protocols"]["ProtA"]
        for key in ["in_degree", "out_degree", "contagion_risk_score",
                    "systemic_importance_score", "contagion_label", "flags"]:
            self.assertIn(key, pr)

    def test_aggregate_keys_present(self):
        result = self._run([make_protocol()])
        for key in ["most_systemic", "most_isolated", "highest_contagion_risk",
                    "total_critical_dependencies", "systemic_count", "protocol_count"]:
            self.assertIn(key, result["aggregates"])

    def test_isolated_protocol_in_degree_0(self):
        result = self._run([make_protocol()])
        self.assertEqual(result["protocols"]["ProtA"]["in_degree"], 0)

    def test_isolated_protocol_out_degree_0(self):
        result = self._run([make_protocol()])
        self.assertEqual(result["protocols"]["ProtA"]["out_degree"], 0)

    def test_isolated_contagion_score_0(self):
        result = self._run([make_protocol()])
        self.assertEqual(result["protocols"]["ProtA"]["contagion_risk_score"], 0.0)

    def test_isolated_label(self):
        result = self._run([make_protocol()])
        self.assertEqual(result["protocols"]["ProtA"]["contagion_label"], "ISOLATED")

    def test_empty_protocols_result(self):
        result = self._run([])
        self.assertEqual(result["protocols"], {})

    def test_empty_protocols_aggregates(self):
        result = self._run([])
        agg = result["aggregates"]
        self.assertIsNone(agg["most_systemic"])
        self.assertIsNone(agg["most_isolated"])
        self.assertIsNone(agg["highest_contagion_risk"])
        self.assertEqual(agg["protocol_count"], 0)

    def test_protocol_count_matches(self):
        protocols = [make_protocol(name=f"P{i}") for i in range(4)]
        result = self._run(protocols)
        self.assertEqual(result["aggregates"]["protocol_count"], 4)


class TestInOutDegree(unittest.TestCase):
    """Tests for in_degree and out_degree computation."""

    def setUp(self):
        self.analyzer = ProtocolCrossProtocolContagionAnalyzer()
        self.tmpdir = tempfile.mkdtemp()

    def _run(self, protocols, config=None):
        return self.analyzer.analyze(
            protocols, config or {}, data_dir=self.tmpdir, dry_run=True
        )

    def test_out_degree_one_dep(self):
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertEqual(result["protocols"]["A"]["out_degree"], 1)

    def test_out_degree_three_deps(self):
        protocols = [
            make_protocol(name="A", dependencies=[
                make_dep(protocol_name="B"),
                make_dep(protocol_name="C"),
                make_dep(protocol_name="D"),
            ]),
            make_protocol(name="B"),
            make_protocol(name="C"),
            make_protocol(name="D"),
        ]
        result = self._run(protocols)
        self.assertEqual(result["protocols"]["A"]["out_degree"], 3)

    def test_in_degree_one_dependent(self):
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertEqual(result["protocols"]["B"]["in_degree"], 1)

    def test_in_degree_two_dependents(self):
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="C")]),
            make_protocol(name="B", dependencies=[make_dep(protocol_name="C")]),
            make_protocol(name="C"),
        ]
        result = self._run(protocols)
        self.assertEqual(result["protocols"]["C"]["in_degree"], 2)

    def test_in_degree_zero_for_leaf(self):
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertEqual(result["protocols"]["A"]["in_degree"], 0)

    def test_chain_degrees(self):
        # A→B→C→D
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="B", dependencies=[make_dep(protocol_name="C")]),
            make_protocol(name="C", dependencies=[make_dep(protocol_name="D")]),
            make_protocol(name="D"),
        ]
        result = self._run(protocols)
        self.assertEqual(result["protocols"]["D"]["in_degree"], 1)
        self.assertEqual(result["protocols"]["A"]["in_degree"], 0)
        self.assertEqual(result["protocols"]["B"]["out_degree"], 1)


class TestContagionScores(unittest.TestCase):
    """Tests for contagion and systemic importance scores."""

    def setUp(self):
        self.analyzer = ProtocolCrossProtocolContagionAnalyzer()
        self.tmpdir = tempfile.mkdtemp()

    def _run(self, protocols, config=None):
        return self.analyzer.analyze(
            protocols, config or {}, data_dir=self.tmpdir, dry_run=True
        )

    def test_contagion_score_from_critical_dep(self):
        # C depends on B critically → B's contagion_risk_score = 1*20 = 20
        protocols = [
            make_protocol(name="C", dependencies=[make_dep(protocol_name="B", critical=True)]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertAlmostEqual(result["protocols"]["B"]["contagion_risk_score"], 20.0)

    def test_contagion_score_from_noncritical_dep(self):
        # C depends on B non-critically → B's score = 1*10 = 10
        protocols = [
            make_protocol(name="C", dependencies=[make_dep(protocol_name="B", critical=False)]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertAlmostEqual(result["protocols"]["B"]["contagion_risk_score"], 10.0)

    def test_contagion_score_two_critical_dependents(self):
        # A and C both critically depend on B → B's score = 2*20 = 40
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B", critical=True)]),
            make_protocol(name="C", dependencies=[make_dep(protocol_name="B", critical=True)]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertAlmostEqual(result["protocols"]["B"]["contagion_risk_score"], 40.0)

    def test_contagion_score_capped_at_100(self):
        # 6 critical deps → 6*20=120 → capped at 100
        protocols = [
            make_protocol(name=f"Dep{i}",
                          dependencies=[make_dep(protocol_name="Hub", critical=True)])
            for i in range(6)
        ] + [make_protocol(name="Hub")]
        result = self._run(protocols)
        self.assertEqual(result["protocols"]["Hub"]["contagion_risk_score"], 100.0)

    def test_systemic_importance_from_flag(self):
        # is_systemic=True with in_degree=0 → score=50
        protocols = [make_protocol(name="A", is_systemic=True)]
        result = self._run(protocols)
        self.assertAlmostEqual(result["protocols"]["A"]["systemic_importance_score"], 50.0)

    def test_systemic_importance_from_indegree(self):
        # is_systemic=False, in_degree=1 → score=10
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="B", is_systemic=False),
        ]
        result = self._run(protocols)
        self.assertAlmostEqual(result["protocols"]["B"]["systemic_importance_score"], 10.0)

    def test_systemic_importance_both_flag_and_indegree(self):
        # is_systemic=True, in_degree=2 → score = min(100, 50+20) = 70
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="Hub")]),
            make_protocol(name="B", dependencies=[make_dep(protocol_name="Hub")]),
            make_protocol(name="Hub", is_systemic=True),
        ]
        result = self._run(protocols)
        self.assertAlmostEqual(result["protocols"]["Hub"]["systemic_importance_score"], 70.0)

    def test_systemic_importance_capped_at_100(self):
        # is_systemic=True (50) + many in_degrees
        protocols = [
            make_protocol(name=f"D{i}", dependencies=[make_dep(protocol_name="Hub")])
            for i in range(10)
        ] + [make_protocol(name="Hub", is_systemic=True)]
        result = self._run(protocols)
        self.assertEqual(result["protocols"]["Hub"]["systemic_importance_score"], 100.0)

    def test_contagion_label_isolated(self):
        result = self._run([make_protocol(name="P")])
        self.assertEqual(result["protocols"]["P"]["contagion_label"], "ISOLATED")

    def test_contagion_label_low(self):
        # in_degree=1, non-critical → score=10, ISOLATED; non-critical=2 → 20, LOW
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="C", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        # B's score = 2*10=20 → LOW
        self.assertEqual(result["protocols"]["B"]["contagion_label"], "LOW")

    def test_contagion_label_moderate(self):
        # 2 critical → 2*20=40 → LOW; 3 critical → 3*20=60 → HIGH
        # 1 critical + 2 noncritical = 20+20=40, LOW
        # need > 30: 2 critical = 40 -> MODERATE? 40>30 yes -> MODERATE
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B", critical=True)]),
            make_protocol(name="C", dependencies=[make_dep(protocol_name="B", critical=True)]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        # 40 → MODERATE
        self.assertEqual(result["protocols"]["B"]["contagion_label"], "MODERATE")

    def test_contagion_label_high(self):
        # 3 critical → 3*20=60 → HIGH (51-70)
        protocols = [
            make_protocol(name=f"D{i}", dependencies=[make_dep(protocol_name="Hub", critical=True)])
            for i in range(3)
        ] + [make_protocol(name="Hub")]
        result = self._run(protocols)
        self.assertEqual(result["protocols"]["Hub"]["contagion_label"], "HIGH")

    def test_contagion_label_systemic(self):
        # 4 critical → 4*20=80 → SYSTEMIC (>70)
        protocols = [
            make_protocol(name=f"D{i}", dependencies=[make_dep(protocol_name="Hub", critical=True)])
            for i in range(4)
        ] + [make_protocol(name="Hub")]
        result = self._run(protocols)
        self.assertEqual(result["protocols"]["Hub"]["contagion_label"], "SYSTEMIC")


class TestFlags(unittest.TestCase):
    """Tests for protocol-level flag detection."""

    def setUp(self):
        self.analyzer = ProtocolCrossProtocolContagionAnalyzer()
        self.tmpdir = tempfile.mkdtemp()

    def _run(self, protocols, config=None):
        return self.analyzer.analyze(
            protocols, config or {}, data_dir=self.tmpdir, dry_run=True
        )

    def test_circular_dependency_two_nodes(self):
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="B", dependencies=[make_dep(protocol_name="A")]),
        ]
        result = self._run(protocols)
        self.assertIn(FLAG_CIRCULAR_DEPENDENCY, result["protocols"]["A"]["flags"])
        self.assertIn(FLAG_CIRCULAR_DEPENDENCY, result["protocols"]["B"]["flags"])

    def test_no_circular_dependency(self):
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertNotIn(FLAG_CIRCULAR_DEPENDENCY, result["protocols"]["A"]["flags"])
        self.assertNotIn(FLAG_CIRCULAR_DEPENDENCY, result["protocols"]["B"]["flags"])

    def test_circular_dependency_three_node_cycle(self):
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="B", dependencies=[make_dep(protocol_name="C")]),
            make_protocol(name="C", dependencies=[make_dep(protocol_name="A")]),
        ]
        result = self._run(protocols)
        for name in ["A", "B", "C"]:
            self.assertIn(FLAG_CIRCULAR_DEPENDENCY, result["protocols"][name]["flags"])

    def test_single_oracle_dependency_all_oracle(self):
        protocols = [
            make_protocol(name="A", dependencies=[
                make_dep(protocol_name="B", dependency_type="oracle"),
                make_dep(protocol_name="C", dependency_type="oracle"),
            ]),
            make_protocol(name="B"),
            make_protocol(name="C"),
        ]
        result = self._run(protocols)
        self.assertIn(FLAG_SINGLE_ORACLE_DEPENDENCY, result["protocols"]["A"]["flags"])

    def test_no_single_oracle_dependency_mixed(self):
        protocols = [
            make_protocol(name="A", dependencies=[
                make_dep(protocol_name="B", dependency_type="oracle"),
                make_dep(protocol_name="C", dependency_type="liquidity"),
            ]),
            make_protocol(name="B"),
            make_protocol(name="C"),
        ]
        result = self._run(protocols)
        self.assertNotIn(FLAG_SINGLE_ORACLE_DEPENDENCY, result["protocols"]["A"]["flags"])

    def test_no_single_oracle_dependency_no_deps(self):
        result = self._run([make_protocol(name="A")])
        self.assertNotIn(FLAG_SINGLE_ORACLE_DEPENDENCY, result["protocols"]["A"]["flags"])

    def test_systemic_exposure_flag(self):
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="B", is_systemic=True),
        ]
        result = self._run(protocols)
        self.assertIn(FLAG_SYSTEMIC_EXPOSURE, result["protocols"]["A"]["flags"])

    def test_no_systemic_exposure_flag(self):
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="B", is_systemic=False),
        ]
        result = self._run(protocols)
        self.assertNotIn(FLAG_SYSTEMIC_EXPOSURE, result["protocols"]["A"]["flags"])

    def test_high_exposure_ratio_flag(self):
        # TVL=100k, exposure=60k → ratio=0.6 > 0.5 → flag
        protocols = [
            make_protocol(name="A", tvl_usd=100_000.0, dependencies=[
                make_dep(protocol_name="B", exposure_usd=60_000.0)
            ]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertIn(FLAG_HIGH_EXPOSURE_RATIO, result["protocols"]["A"]["flags"])

    def test_no_high_exposure_ratio(self):
        # TVL=100k, exposure=40k → ratio=0.4 ≤ 0.5 → no flag
        protocols = [
            make_protocol(name="A", tvl_usd=100_000.0, dependencies=[
                make_dep(protocol_name="B", exposure_usd=40_000.0)
            ]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertNotIn(FLAG_HIGH_EXPOSURE_RATIO, result["protocols"]["A"]["flags"])

    def test_high_exposure_ratio_boundary_exactly_50pct(self):
        # exactly 50% → NOT above → no flag
        protocols = [
            make_protocol(name="A", tvl_usd=100_000.0, dependencies=[
                make_dep(protocol_name="B", exposure_usd=50_000.0)
            ]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertNotIn(FLAG_HIGH_EXPOSURE_RATIO, result["protocols"]["A"]["flags"])

    def test_high_exposure_ratio_custom_threshold(self):
        # TVL=100k, exposure=30k → ratio=0.3; custom threshold=0.25 → flag
        protocols = [
            make_protocol(name="A", tvl_usd=100_000.0, dependencies=[
                make_dep(protocol_name="B", exposure_usd=30_000.0)
            ]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols, config={"exposure_ratio_threshold": 0.25})
        self.assertIn(FLAG_HIGH_EXPOSURE_RATIO, result["protocols"]["A"]["flags"])

    def test_all_flags_at_once(self):
        # A depends on B (oracle) + B depends on A (circular) + B is_systemic + exposure > 50%
        protocols = [
            make_protocol(name="A", tvl_usd=100_000.0, dependencies=[
                make_dep(protocol_name="B", dependency_type="oracle",
                         exposure_usd=60_000.0, critical=False)
            ]),
            make_protocol(name="B", tvl_usd=200_000.0,
                          is_systemic=True,
                          dependencies=[make_dep(protocol_name="A")]),
        ]
        result = self._run(protocols)
        a_flags = result["protocols"]["A"]["flags"]
        self.assertIn(FLAG_CIRCULAR_DEPENDENCY, a_flags)
        self.assertIn(FLAG_SINGLE_ORACLE_DEPENDENCY, a_flags)
        self.assertIn(FLAG_SYSTEMIC_EXPOSURE, a_flags)
        self.assertIn(FLAG_HIGH_EXPOSURE_RATIO, a_flags)

    def test_no_flags_for_clean_protocol(self):
        result = self._run([make_protocol(name="Clean")])
        self.assertEqual(result["protocols"]["Clean"]["flags"], [])

    def test_tvl_zero_with_exposure_gives_high_ratio_flag(self):
        protocols = [
            make_protocol(name="A", tvl_usd=0.0, dependencies=[
                make_dep(protocol_name="B", exposure_usd=100.0)
            ]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertIn(FLAG_HIGH_EXPOSURE_RATIO, result["protocols"]["A"]["flags"])

    def test_tvl_zero_no_exposure_no_flag(self):
        protocols = [
            make_protocol(name="A", tvl_usd=0.0, dependencies=[
                make_dep(protocol_name="B", exposure_usd=0.0)
            ]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertNotIn(FLAG_HIGH_EXPOSURE_RATIO, result["protocols"]["A"]["flags"])


class TestAggregates(unittest.TestCase):
    """Tests for cross-protocol aggregate statistics."""

    def setUp(self):
        self.analyzer = ProtocolCrossProtocolContagionAnalyzer()
        self.tmpdir = tempfile.mkdtemp()

    def _run(self, protocols, config=None):
        return self.analyzer.analyze(
            protocols, config or {}, data_dir=self.tmpdir, dry_run=True
        )

    def test_most_systemic(self):
        protocols = [
            make_protocol(name="A", is_systemic=True),
            make_protocol(name="B", is_systemic=False),
        ]
        result = self._run(protocols)
        self.assertEqual(result["aggregates"]["most_systemic"], "A")

    def test_most_isolated(self):
        protocols = [
            make_protocol(name="A"),  # no deps → score=0
            make_protocol(name="B", dependencies=[make_dep(protocol_name="A")]),
            make_protocol(name="C", dependencies=[
                make_dep(protocol_name="A", critical=True),
                make_dep(protocol_name="B", critical=True),
            ]),
        ]
        result = self._run(protocols)
        # C has 0 in_degree → ISOLATED? No, A has in_degree>0. C is the one with no one depending on it.
        # most_isolated = lowest contagion_risk_score
        # C has no one depending on it → in_degree=0 → score=0
        # A has B+C depending on it → score=20+10=30? Let's check
        # A: B(noncritical)=10, C(critical)=20 → in_degree=2, score=30
        # B: C(critical)=20 → in_degree=1, score=20
        # C: nobody depends on it → score=0
        self.assertEqual(result["aggregates"]["most_isolated"], "C")

    def test_highest_contagion_risk(self):
        protocols = [
            make_protocol(name="A"),
            make_protocol(name="B"),
            make_protocol(name="C", dependencies=[make_dep(protocol_name="A", critical=True)]),
            make_protocol(name="D", dependencies=[make_dep(protocol_name="A", critical=True)]),
        ]
        result = self._run(protocols)
        # A: 2 critical dependents → 2*20=40
        # B: 0 → 0
        # C,D: 0 → 0
        self.assertEqual(result["aggregates"]["highest_contagion_risk"], "A")

    def test_total_critical_dependencies(self):
        protocols = [
            make_protocol(name="A", dependencies=[
                make_dep(protocol_name="B", critical=True),
                make_dep(protocol_name="C", critical=False),
            ]),
            make_protocol(name="D", dependencies=[
                make_dep(protocol_name="B", critical=True),
            ]),
            make_protocol(name="B"),
            make_protocol(name="C"),
        ]
        result = self._run(protocols)
        self.assertEqual(result["aggregates"]["total_critical_dependencies"], 2)

    def test_systemic_count(self):
        protocols = [
            make_protocol(name="A", is_systemic=True),
            make_protocol(name="B", is_systemic=True),
            make_protocol(name="C", is_systemic=False),
        ]
        result = self._run(protocols)
        self.assertEqual(result["aggregates"]["systemic_count"], 2)

    def test_systemic_count_zero(self):
        protocols = [make_protocol(name="A"), make_protocol(name="B")]
        result = self._run(protocols)
        self.assertEqual(result["aggregates"]["systemic_count"], 0)

    def test_total_critical_deps_zero(self):
        protocols = [
            make_protocol(name="A", dependencies=[
                make_dep(protocol_name="B", critical=False),
            ]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertEqual(result["aggregates"]["total_critical_dependencies"], 0)

    def test_protocol_count_correct(self):
        protocols = [make_protocol(name=f"P{i}") for i in range(7)]
        result = self._run(protocols)
        self.assertEqual(result["aggregates"]["protocol_count"], 7)


class TestLogBehavior(unittest.TestCase):
    """Tests for ring-buffer log write behavior."""

    def setUp(self):
        self.analyzer = ProtocolCrossProtocolContagionAnalyzer()
        self.tmpdir = tempfile.mkdtemp()

    def _log_path(self):
        return os.path.join(self.tmpdir, "contagion_risk_log.json")

    def _run(self, protocols=None, dry_run=False):
        return self.analyzer.analyze(
            protocols or [make_protocol()], {}, data_dir=self.tmpdir, dry_run=dry_run
        )

    def test_log_file_created_on_run(self):
        self._run(dry_run=False)
        self.assertTrue(os.path.exists(self._log_path()))

    def test_log_file_is_list(self):
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIsInstance(data, list)

    def test_log_accumulates_entries(self):
        self._run(dry_run=False)
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 2)

    def test_log_entry_has_timestamp(self):
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIn("timestamp", data[0])

    def test_log_entry_has_protocol_count(self):
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIn("protocol_count", data[0])

    def test_log_entry_has_systemic_count(self):
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIn("systemic_count", data[0])

    def test_log_entry_has_most_systemic(self):
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIn("most_systemic", data[0])

    def test_dry_run_no_log_file(self):
        self._run(dry_run=True)
        self.assertFalse(os.path.exists(self._log_path()))

    def test_ring_buffer_cap_100(self):
        for _ in range(110):
            self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertLessEqual(len(data), 100)

    def test_ring_buffer_oldest_dropped(self):
        for _ in range(101):
            self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertEqual(len(data), 100)

    def test_log_entry_has_total_critical_deps(self):
        self._run(dry_run=False)
        with open(self._log_path()) as f:
            data = json.load(f)
        self.assertIn("total_critical_dependencies", data[0])


class TestEdgeCases(unittest.TestCase):
    """Edge case and misc tests."""

    def setUp(self):
        self.analyzer = ProtocolCrossProtocolContagionAnalyzer()
        self.tmpdir = tempfile.mkdtemp()

    def _run(self, protocols, config=None):
        return self.analyzer.analyze(
            protocols, config or {}, data_dir=self.tmpdir, dry_run=True
        )

    def test_result_is_dict(self):
        result = self._run([make_protocol()])
        self.assertIsInstance(result, dict)

    def test_flags_is_list(self):
        result = self._run([make_protocol()])
        self.assertIsInstance(result["protocols"]["ProtA"]["flags"], list)

    def test_contagion_score_is_float(self):
        result = self._run([make_protocol()])
        score = result["protocols"]["ProtA"]["contagion_risk_score"]
        self.assertIsInstance(score, float)

    def test_contagion_label_is_string(self):
        result = self._run([make_protocol()])
        label = result["protocols"]["ProtA"]["contagion_label"]
        self.assertIsInstance(label, str)

    def test_dependency_on_external_protocol_not_in_list(self):
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="ExternalXYZ")]),
        ]
        # Should not crash, ExternalXYZ not in result
        result = self._run(protocols)
        self.assertIn("A", result["protocols"])
        self.assertNotIn("ExternalXYZ", result["protocols"])

    def test_out_degree_zero_no_deps(self):
        result = self._run([make_protocol(name="Solo")])
        self.assertEqual(result["protocols"]["Solo"]["out_degree"], 0)

    def test_in_degree_is_int(self):
        result = self._run([make_protocol()])
        self.assertIsInstance(result["protocols"]["ProtA"]["in_degree"], int)

    def test_out_degree_is_int(self):
        result = self._run([make_protocol()])
        self.assertIsInstance(result["protocols"]["ProtA"]["out_degree"], int)

    def test_star_topology_hub_high_indegree(self):
        # Hub: 5 spokes depend on it
        protocols = [
            make_protocol(name=f"Spoke{i}", dependencies=[make_dep(protocol_name="Hub")])
            for i in range(5)
        ] + [make_protocol(name="Hub")]
        result = self._run(protocols)
        self.assertEqual(result["protocols"]["Hub"]["in_degree"], 5)

    def test_chain_topology_head_no_indegree(self):
        # A → B → C → D, A is head
        protocols = [
            make_protocol(name="A", dependencies=[make_dep(protocol_name="B")]),
            make_protocol(name="B", dependencies=[make_dep(protocol_name="C")]),
            make_protocol(name="C", dependencies=[make_dep(protocol_name="D")]),
            make_protocol(name="D"),
        ]
        result = self._run(protocols)
        self.assertEqual(result["protocols"]["A"]["in_degree"], 0)
        self.assertEqual(result["protocols"]["D"]["in_degree"], 1)

    def test_config_empty_uses_defaults(self):
        result = self._run([make_protocol()], config={})
        self.assertIn("protocols", result)

    def test_single_oracle_dep_one_dep(self):
        protocols = [
            make_protocol(name="A", dependencies=[
                make_dep(protocol_name="B", dependency_type="oracle")
            ]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertIn(FLAG_SINGLE_ORACLE_DEPENDENCY, result["protocols"]["A"]["flags"])

    def test_collateral_dep_type_no_oracle_flag(self):
        protocols = [
            make_protocol(name="A", dependencies=[
                make_dep(protocol_name="B", dependency_type="collateral")
            ]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertNotIn(FLAG_SINGLE_ORACLE_DEPENDENCY, result["protocols"]["A"]["flags"])

    def test_governance_dep_type_no_oracle_flag(self):
        protocols = [
            make_protocol(name="A", dependencies=[
                make_dep(protocol_name="B", dependency_type="governance")
            ]),
            make_protocol(name="B"),
        ]
        result = self._run(protocols)
        self.assertNotIn(FLAG_SINGLE_ORACLE_DEPENDENCY, result["protocols"]["A"]["flags"])

    def test_single_protocol_no_deps(self):
        result = self._run([make_protocol(name="Lone")])
        agg = result["aggregates"]
        self.assertEqual(agg["most_systemic"], "Lone")
        self.assertEqual(agg["most_isolated"], "Lone")

    def test_both_systemic_higher_wins(self):
        protocols = [
            make_protocol(name="A", is_systemic=True),   # score=50
            make_protocol(name="B", is_systemic=True,
                          dependencies=[]),  # also score=50, tie → first max
        ]
        # Hub is A depends on by nobody, B same → both score=50, aggregate picks one
        result = self._run(protocols)
        self.assertIn(result["aggregates"]["most_systemic"], ["A", "B"])


if __name__ == "__main__":
    unittest.main()
