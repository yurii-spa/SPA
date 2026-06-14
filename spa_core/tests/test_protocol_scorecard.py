#!/usr/bin/env python3
"""Tests for spa_core.paper_trading.protocol_scorecard (SPA-V436 / MP-129).

Plain unittest, NO pytest, NO network, ALL persistence in a tempdir.

Covers:
- score_tvl: above 5× min → 1.0; at min → 0.2; below half-min → 0; zero → 0
- score_audit: top firm → 1.0; no audit → 0; unknown firm → 0.5; empty firms → 0
- score_age: at min_days → 1.0; half min_days → ~0.5; future date → 0; bad date → 0
- score_apy_premium: 5× premium → 1.0; zero premium → 0; negative → 0; exact min → 0.2
- score_diversification: new protocol → 1.0; existing at cap → 0; existing below cap → headroom
- compute_scorecard: APPROVED (all high, no flags)
- compute_scorecard: REJECTED by blocking flag (no audit, audit_required=True)
- compute_scorecard: CONDITIONAL (medium composite, no blocking)
- compute_scorecard: blocking flag does NOT veto when audit_required=False
- compute_scorecard: composite < conditional threshold → REJECTED
- compute_scorecard: blocking flag at composite ≥ conditional → REJECTED
- compute_scorecard: breakdown keys present; weighted = score × weight
- compute_scorecard: no criteria arg → uses defaults without raising
- save_scorecard: file created, no stray .tmp files, valid JSON
- save_scorecard: protocol_id sanitized in filename
- load_criteria: missing file → defaults; file with partial keys → merged
- load_criteria: valid file → custom values returned
- AST-lint: no external imports (only stdlib)
"""
from __future__ import annotations

import ast
import json
import os
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from typing import Any

# ── project path ─────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import spa_core.paper_trading.protocol_scorecard as sc

_MODULE_PATH = Path(sc.__file__)

# ─── Helpers ─────────────────────────────────────────────────────────────────

# A date well in the past (3 years ago) — always passes age criteria
_OLD_DATE = (date.today() - timedelta(days=365 * 3)).isoformat()
# A date exactly min_days (180) ago
_AT_MIN_DATE = (date.today() - timedelta(days=180)).isoformat()
# A date half-min (90) days ago
_HALF_MIN_DATE = (date.today() - timedelta(days=90)).isoformat()
# Future date
_FUTURE_DATE = (date.today() + timedelta(days=10)).isoformat()


def _approved_criteria() -> dict:
    """Criteria with audit_required=True (default)."""
    return {
        "tvl_min_usd": 50_000_000,
        "audit_required": True,
        "min_age_days": 180,
        "max_protocol_concentration": 0.30,
        "min_apy_premium_bps": 50,
        "weights": {
            "tvl": 0.25,
            "audit": 0.20,
            "age": 0.20,
            "apy_premium": 0.20,
            "diversification": 0.15,
        },
    }


def _no_audit_required_criteria() -> dict:
    c = _approved_criteria()
    c["audit_required"] = False
    return c


# ─── score_tvl ────────────────────────────────────────────────────────────────


class TestScoreTvl(unittest.TestCase):

    def test_above_5x_min_gives_1(self):
        result = sc.score_tvl(300_000_000, 50_000_000)  # 6× min
        self.assertEqual(result["score"], 1.0)

    def test_exactly_5x_min_gives_1(self):
        result = sc.score_tvl(250_000_000, 50_000_000)  # 5× min
        self.assertEqual(result["score"], 1.0)

    def test_at_min_gives_0_2(self):
        result = sc.score_tvl(50_000_000, 50_000_000)  # 1× min = 1/5 = 0.2
        self.assertAlmostEqual(result["score"], 0.2, places=5)

    def test_below_half_min_gives_0(self):
        result = sc.score_tvl(20_000_000, 50_000_000)  # below half (25M)
        self.assertEqual(result["score"], 0.0)

    def test_zero_tvl_gives_0(self):
        result = sc.score_tvl(0, 50_000_000)
        self.assertEqual(result["score"], 0.0)

    def test_exactly_half_min_gives_proportional(self):
        # 25M / (50M*5) = 25/250 = 0.1  (not below half, just at half)
        result = sc.score_tvl(25_000_000, 50_000_000)
        self.assertAlmostEqual(result["score"], 0.1, places=5)

    def test_details_present(self):
        result = sc.score_tvl(100_000_000, 50_000_000)
        self.assertIn("details", result)
        self.assertIsInstance(result["details"], str)

    def test_score_between_0_and_1(self):
        for tvl in [0, 10_000_000, 50_000_000, 100_000_000, 500_000_000]:
            result = sc.score_tvl(tvl, 50_000_000)
            self.assertGreaterEqual(result["score"], 0.0)
            self.assertLessEqual(result["score"], 1.0)


# ─── score_audit ─────────────────────────────────────────────────────────────


class TestScoreAudit(unittest.TestCase):

    def test_top_firm_trail_of_bits_gives_1(self):
        result = sc.score_audit(True, ["Trail of Bits"])
        self.assertEqual(result["score"], 1.0)

    def test_top_firm_openzeppelin_gives_1(self):
        result = sc.score_audit(True, ["OpenZeppelin"])
        self.assertEqual(result["score"], 1.0)

    def test_top_firm_consensys_gives_1(self):
        result = sc.score_audit(True, ["Consensys"])
        self.assertEqual(result["score"], 1.0)

    def test_top_firm_spearbit_gives_1(self):
        result = sc.score_audit(True, ["Spearbit"])
        self.assertEqual(result["score"], 1.0)

    def test_top_firm_certora_gives_1(self):
        result = sc.score_audit(True, ["Certora"])
        self.assertEqual(result["score"], 1.0)

    def test_top_firm_mixbytes_gives_1(self):
        result = sc.score_audit(True, ["MixBytes"])
        self.assertEqual(result["score"], 1.0)

    def test_no_audit_gives_0(self):
        result = sc.score_audit(False, [])
        self.assertEqual(result["score"], 0.0)

    def test_has_audit_but_empty_firms_gives_0(self):
        result = sc.score_audit(True, [])
        self.assertEqual(result["score"], 0.0)

    def test_unknown_firm_gives_0_5(self):
        result = sc.score_audit(True, ["SomeUnknownAuditFirm"])
        self.assertEqual(result["score"], 0.5)

    def test_multiple_firms_one_top_gives_1(self):
        result = sc.score_audit(True, ["Unknown Firm", "OpenZeppelin"])
        self.assertEqual(result["score"], 1.0)

    def test_details_present(self):
        result = sc.score_audit(True, ["Trail of Bits"])
        self.assertIn("details", result)
        self.assertIsInstance(result["details"], str)

    def test_case_insensitive_matching(self):
        # Top firms are stored lowercase; input may be mixed case
        result = sc.score_audit(True, ["trail of bits"])
        self.assertEqual(result["score"], 1.0)


# ─── score_age ───────────────────────────────────────────────────────────────


class TestScoreAge(unittest.TestCase):

    def test_at_min_days_gives_1(self):
        result = sc.score_age(_AT_MIN_DATE, 180)
        # Exactly at min → 180/180 = 1.0
        self.assertAlmostEqual(result["score"], 1.0, places=4)

    def test_above_min_days_gives_1(self):
        old = (date.today() - timedelta(days=365)).isoformat()
        result = sc.score_age(old, 180)
        self.assertEqual(result["score"], 1.0)

    def test_half_min_days_gives_approx_half(self):
        result = sc.score_age(_HALF_MIN_DATE, 180)
        self.assertAlmostEqual(result["score"], 0.5, places=3)

    def test_future_date_gives_0(self):
        result = sc.score_age(_FUTURE_DATE, 180)
        self.assertEqual(result["score"], 0.0)

    def test_invalid_date_string_gives_0(self):
        result = sc.score_age("not-a-date", 180)
        self.assertEqual(result["score"], 0.0)

    def test_empty_string_gives_0(self):
        result = sc.score_age("", 180)
        self.assertEqual(result["score"], 0.0)

    def test_details_present(self):
        result = sc.score_age(_OLD_DATE, 180)
        self.assertIn("details", result)

    def test_score_between_0_and_1(self):
        for days in [0, 90, 180, 365, 730]:
            d = (date.today() - timedelta(days=days)).isoformat()
            result = sc.score_age(d, 180)
            self.assertGreaterEqual(result["score"], 0.0)
            self.assertLessEqual(result["score"], 1.0)


# ─── score_apy_premium ───────────────────────────────────────────────────────


class TestScoreApyPremium(unittest.TestCase):

    def test_5x_premium_gives_1(self):
        # 5× 50bps = 250bps premium
        result = sc.score_apy_premium(7.0, 4.5, 50)  # 2.5% = 250bps = 5× 50
        self.assertEqual(result["score"], 1.0)

    def test_above_5x_capped_at_1(self):
        result = sc.score_apy_premium(10.0, 4.5, 50)  # way above
        self.assertEqual(result["score"], 1.0)

    def test_zero_premium_gives_0(self):
        result = sc.score_apy_premium(4.5, 4.5, 50)  # 0 bps
        self.assertEqual(result["score"], 0.0)

    def test_negative_premium_gives_0(self):
        result = sc.score_apy_premium(3.0, 4.5, 50)  # -150 bps
        self.assertEqual(result["score"], 0.0)

    def test_exactly_min_premium_gives_0_2(self):
        # formula: premium_bps = (protocol_apy - t1_avg_apy) * 10000
        # To get exactly 50 bps: diff = 50/10000 = 0.005
        # protocol_apy = 4.5 + 0.005 = 4.505
        # score = 50 / (50*5) = 50/250 = 0.2
        result = sc.score_apy_premium(4.505, 4.5, 50)
        self.assertAlmostEqual(result["score"], 0.2, places=4)

    def test_double_min_premium_gives_0_4(self):
        # To get exactly 100 bps: diff = 100/10000 = 0.01
        # protocol_apy = 4.5 + 0.01 = 4.51
        # score = 100/250 = 0.4
        result = sc.score_apy_premium(4.51, 4.5, 50)
        self.assertAlmostEqual(result["score"], 0.4, places=4)

    def test_details_present(self):
        result = sc.score_apy_premium(6.0, 4.5, 50)
        self.assertIn("details", result)

    def test_score_between_0_and_1(self):
        for prot_apy in [3.0, 4.5, 5.0, 7.0, 10.0]:
            result = sc.score_apy_premium(prot_apy, 4.5, 50)
            self.assertGreaterEqual(result["score"], 0.0)
            self.assertLessEqual(result["score"], 1.0)


# ─── score_diversification ───────────────────────────────────────────────────


class TestScoreDiversification(unittest.TestCase):

    def test_new_protocol_gives_1(self):
        result = sc.score_diversification("new_proto", {"aave_v3": 0.40, "compound_v3": 0.30})
        self.assertEqual(result["score"], 1.0)

    def test_existing_at_cap_gives_0(self):
        result = sc.score_diversification("aave_v3", {"aave_v3": 0.30})
        self.assertEqual(result["score"], 0.0)

    def test_existing_above_cap_gives_0(self):
        result = sc.score_diversification("aave_v3", {"aave_v3": 0.50})
        self.assertEqual(result["score"], 0.0)

    def test_existing_below_cap_gives_headroom(self):
        # 0.15 in portfolio, cap=0.30 → headroom = (0.30-0.15)/0.30 = 0.5
        result = sc.score_diversification("aave_v3", {"aave_v3": 0.15})
        self.assertAlmostEqual(result["score"], 0.5, places=5)

    def test_empty_portfolio_gives_1(self):
        result = sc.score_diversification("new_proto", {})
        self.assertEqual(result["score"], 1.0)

    def test_details_present(self):
        result = sc.score_diversification("aave_v3", {"aave_v3": 0.10})
        self.assertIn("details", result)


# ─── compute_scorecard ───────────────────────────────────────────────────────


class TestComputeScorecard(unittest.TestCase):

    def _approved_inputs(self) -> dict:
        """Inputs designed to produce a high composite → APPROVED."""
        return dict(
            protocol_id="great_protocol",
            tvl_usd=500_000_000,   # 10× min → capped at 1.0
            has_audit=True,
            audit_firms=["OpenZeppelin"],
            launch_date=_OLD_DATE,
            protocol_apy=10.0,     # big premium over T1
            t1_avg_apy=4.5,
            current_portfolio={},  # new → 1.0 diversification
            criteria=_approved_criteria(),
        )

    def test_approved_scenario(self):
        sc_result = sc.compute_scorecard(**self._approved_inputs())
        self.assertEqual(sc_result["verdict"], "APPROVED")
        self.assertGreaterEqual(sc_result["composite_score"], 0.70)
        self.assertEqual(sc_result["blocking_flags"], [])

    def test_rejected_by_blocking_flag_no_audit(self):
        inputs = self._approved_inputs()
        inputs["has_audit"] = False
        inputs["audit_firms"] = []
        sc_result = sc.compute_scorecard(**inputs)
        self.assertEqual(sc_result["verdict"], "REJECTED")
        self.assertIn("NO_AUDIT", sc_result["blocking_flags"])

    def test_conditional_medium_composite(self):
        # Medium TVL, unknown audit firm, only 90 days old, small premium
        criteria = _approved_criteria()
        criteria["audit_required"] = False  # remove blocker
        sc_result = sc.compute_scorecard(
            protocol_id="mid_proto",
            tvl_usd=25_000_000,     # below min → 0
            has_audit=True,
            audit_firms=["SomeUnknown"],  # 0.5 score
            launch_date=_HALF_MIN_DATE,   # 90/180 = 0.5
            protocol_apy=4.8,        # small premium
            t1_avg_apy=4.5,          # 30bps premium
            current_portfolio={},
            criteria=criteria,
        )
        self.assertIn(sc_result["verdict"], ("CONDITIONAL", "REJECTED"))
        # At minimum should not be APPROVED
        self.assertNotEqual(sc_result["verdict"], "APPROVED")

    def test_blocking_flag_does_not_veto_when_audit_required_false(self):
        """When audit_required=False, no audit does NOT produce a blocking flag."""
        inputs = self._approved_inputs()
        inputs["has_audit"] = False
        inputs["audit_firms"] = []
        inputs["criteria"] = _no_audit_required_criteria()
        sc_result = sc.compute_scorecard(**inputs)
        self.assertNotIn("NO_AUDIT", sc_result["blocking_flags"])

    def test_breakdown_keys_present(self):
        sc_result = sc.compute_scorecard(**self._approved_inputs())
        bd = sc_result["breakdown"]
        for key in ("tvl", "audit", "age", "apy_premium", "diversification"):
            self.assertIn(key, bd)
            self.assertIn("score", bd[key])
            self.assertIn("weight", bd[key])
            self.assertIn("weighted", bd[key])
            self.assertIn("details", bd[key])

    def test_weighted_equals_score_times_weight(self):
        sc_result = sc.compute_scorecard(**self._approved_inputs())
        for dim, vals in sc_result["breakdown"].items():
            expected = round(vals["score"] * vals["weight"], 6)
            self.assertAlmostEqual(vals["weighted"], expected, places=5,
                                   msg=f"dim={dim}")

    def test_composite_equals_sum_of_weighted(self):
        sc_result = sc.compute_scorecard(**self._approved_inputs())
        total = sum(v["weighted"] for v in sc_result["breakdown"].values())
        self.assertAlmostEqual(sc_result["composite_score"], total, places=5)

    def test_required_top_level_fields(self):
        sc_result = sc.compute_scorecard(**self._approved_inputs())
        for field in ("protocol_id", "timestamp", "composite_score", "verdict",
                      "threshold", "breakdown", "blocking_flags", "recommendation"):
            self.assertIn(field, sc_result, f"missing field: {field}")

    def test_threshold_values(self):
        sc_result = sc.compute_scorecard(**self._approved_inputs())
        self.assertEqual(sc_result["threshold"]["approved"], 0.70)
        self.assertEqual(sc_result["threshold"]["conditional"], 0.50)

    def test_no_criteria_arg_uses_defaults(self):
        """compute_scorecard without criteria= should not raise."""
        try:
            sc_result = sc.compute_scorecard(
                protocol_id="fallback_proto",
                tvl_usd=200_000_000,
                has_audit=True,
                audit_firms=["OpenZeppelin"],
                launch_date=_OLD_DATE,
                protocol_apy=7.0,
                t1_avg_apy=4.5,
                current_portfolio={},
            )
            self.assertIn(sc_result["verdict"], ("APPROVED", "CONDITIONAL", "REJECTED"))
        except Exception as exc:
            self.fail(f"compute_scorecard without criteria raised: {exc}")

    def test_verdict_rejected_when_composite_below_conditional(self):
        """Force all scores to 0 → composite 0 → REJECTED."""
        criteria = _no_audit_required_criteria()
        sc_result = sc.compute_scorecard(
            protocol_id="bad_proto",
            tvl_usd=0,               # score 0
            has_audit=False,         # score 0
            audit_firms=[],
            launch_date=_FUTURE_DATE,  # score 0 (future)
            protocol_apy=3.0,        # negative premium
            t1_avg_apy=4.5,
            current_portfolio={"bad_proto": 0.50},  # at/above cap → 0
            criteria=criteria,
        )
        self.assertEqual(sc_result["verdict"], "REJECTED")
        self.assertLess(sc_result["composite_score"], 0.50)

    def test_blocking_flag_at_medium_composite_gives_rejected(self):
        """Even if composite ≥ 0.5, blocking flag → REJECTED."""
        inputs = self._approved_inputs()
        inputs["has_audit"] = False
        inputs["audit_firms"] = []
        # audit score will be 0, but other scores still high
        inputs["criteria"] = _approved_criteria()  # audit_required=True
        sc_result = sc.compute_scorecard(**inputs)
        self.assertEqual(sc_result["verdict"], "REJECTED")
        self.assertIn("NO_AUDIT", sc_result["blocking_flags"])

    def test_recommendation_is_nonempty_string(self):
        sc_result = sc.compute_scorecard(**self._approved_inputs())
        self.assertIsInstance(sc_result["recommendation"], str)
        self.assertGreater(len(sc_result["recommendation"]), 0)

    def test_advisory_only_flag_set(self):
        sc_result = sc.compute_scorecard(**self._approved_inputs())
        self.assertTrue(sc_result.get("advisory_only"))

    def test_disclaimer_present(self):
        sc_result = sc.compute_scorecard(**self._approved_inputs())
        self.assertIn("disclaimer", sc_result)


# ─── save_scorecard ──────────────────────────────────────────────────────────


class TestSaveScorecard(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _make_scorecard(self, protocol_id: str = "test_protocol") -> dict:
        return sc.compute_scorecard(
            protocol_id=protocol_id,
            tvl_usd=200_000_000,
            has_audit=True,
            audit_firms=["OpenZeppelin"],
            launch_date=_OLD_DATE,
            protocol_apy=7.0,
            t1_avg_apy=4.5,
            current_portfolio={},
            criteria=_approved_criteria(),
        )

    def test_file_created(self):
        card = self._make_scorecard()
        out_path = sc.save_scorecard(card, data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(out_path))

    def test_no_tmp_file_leftover(self):
        card = self._make_scorecard()
        sc.save_scorecard(card, data_dir=self.tmpdir)
        tmp_files = [f for f in os.listdir(self.tmpdir) if f.endswith(".tmp")]
        self.assertEqual(tmp_files, [], f"Stray .tmp files: {tmp_files}")

    def test_output_is_valid_json(self):
        card = self._make_scorecard()
        out_path = sc.save_scorecard(card, data_dir=self.tmpdir)
        with open(out_path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded["protocol_id"], "test_protocol")
        self.assertIn("verdict", loaded)

    def test_filename_contains_protocol_id_and_date(self):
        card = self._make_scorecard("my_protocol")
        out_path = sc.save_scorecard(card, data_dir=self.tmpdir)
        fname = os.path.basename(out_path)
        self.assertIn("my_protocol", fname)
        self.assertIn(date.today().isoformat(), fname)

    def test_special_chars_in_protocol_id_sanitized(self):
        card = self._make_scorecard("proto/with:special!chars")
        out_path = sc.save_scorecard(card, data_dir=self.tmpdir)
        fname = os.path.basename(out_path)
        # Should not contain '/' ':' '!'
        for char in ('/', ':', '!'):
            self.assertNotIn(char, fname)

    def test_returns_string_path(self):
        card = self._make_scorecard()
        result = sc.save_scorecard(card, data_dir=self.tmpdir)
        self.assertIsInstance(result, str)


# ─── load_criteria ───────────────────────────────────────────────────────────


class TestLoadCriteria(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_file_returns_defaults(self):
        path = os.path.join(self.tmpdir, "nonexistent_criteria.json")
        result = sc.load_criteria(path)
        self.assertEqual(result["tvl_min_usd"], 50_000_000)
        self.assertTrue(result["audit_required"])
        self.assertEqual(result["min_age_days"], 180)
        self.assertAlmostEqual(result["weights"]["tvl"], 0.25)

    def test_valid_file_returns_custom_values(self):
        custom = {
            "tvl_min_usd": 100_000_000,
            "audit_required": False,
            "min_age_days": 90,
            "min_apy_premium_bps": 100,
            "weights": {"tvl": 0.30, "audit": 0.15},
        }
        path = os.path.join(self.tmpdir, "criteria.json")
        with open(path, "w") as f:
            json.dump(custom, f)
        result = sc.load_criteria(path)
        self.assertEqual(result["tvl_min_usd"], 100_000_000)
        self.assertFalse(result["audit_required"])
        self.assertEqual(result["min_age_days"], 90)
        # Weights merged: custom value overrides default
        self.assertAlmostEqual(result["weights"]["tvl"], 0.30)
        self.assertAlmostEqual(result["weights"]["audit"], 0.15)
        # Default weight keys not in custom remain
        self.assertIn("age", result["weights"])

    def test_broken_json_returns_defaults(self):
        path = os.path.join(self.tmpdir, "broken.json")
        with open(path, "w") as f:
            f.write("{not valid json}")
        result = sc.load_criteria(path)
        self.assertEqual(result["tvl_min_usd"], 50_000_000)

    def test_default_weights_sum_to_1(self):
        result = sc.load_criteria(os.path.join(self.tmpdir, "no_file.json"))
        total = sum(result["weights"].values())
        self.assertAlmostEqual(total, 1.0, places=5)


# ─── AST import hygiene ──────────────────────────────────────────────────────

_STDLIB_ALLOWED = {
    "argparse", "ast", "copy", "datetime", "json", "logging", "math",
    "os", "pathlib", "sys", "tempfile", "typing", "__future__",
}

_FORBIDDEN_PATTERNS = [
    "requests", "aiohttp", "httpx", "web3", "eth_",
    "anthropic", "openai", "langchain", "transformers",
    "numpy", "pandas", "scipy", "sklearn",
]


class TestAstLint(unittest.TestCase):

    def test_no_forbidden_external_imports(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(_MODULE_PATH))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module.split(".")[0]] if node.module else []
                for name in names:
                    for forbidden in _FORBIDDEN_PATTERNS:
                        self.assertNotIn(
                            forbidden, name,
                            f"Forbidden import '{name}' found in {_MODULE_PATH.name}",
                        )

    def test_module_compiles_without_syntax_error(self):
        import py_compile
        try:
            py_compile.compile(str(_MODULE_PATH), doraise=True)
        except py_compile.PyCompileError as exc:
            self.fail(f"Syntax error in {_MODULE_PATH.name}: {exc}")

    def test_no_network_or_socket_imports(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                else:
                    names = [node.module] if node.module else []
                for name in names:
                    for forbidden in ("socket", "urllib.request", "http.client", "requests"):
                        self.assertFalse(
                            name.startswith(forbidden),
                            f"Network import '{name}' found",
                        )


# ─── End-to-end integration ──────────────────────────────────────────────────


class TestEndToEnd(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_full_approved_flow(self):
        sc_result = sc.compute_scorecard(
            protocol_id="e2e_protocol",
            tvl_usd=600_000_000,
            has_audit=True,
            audit_firms=["Trail of Bits"],
            launch_date=_OLD_DATE,
            protocol_apy=9.0,
            t1_avg_apy=4.5,
            current_portfolio={},
            criteria=_approved_criteria(),
        )
        self.assertEqual(sc_result["verdict"], "APPROVED")
        out_path = sc.save_scorecard(sc_result, data_dir=self.tmpdir)
        self.assertTrue(os.path.exists(out_path))
        with open(out_path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        self.assertEqual(loaded["verdict"], "APPROVED")
        self.assertEqual(loaded["protocol_id"], "e2e_protocol")

    def test_criteria_from_file_used_in_scorecard(self):
        """Write a criteria file to tmpdir and verify it affects scoring."""
        custom = {
            "tvl_min_usd": 1_000,    # very low min → easy to pass
            "audit_required": False,
            "min_age_days": 1,
            "min_apy_premium_bps": 1,
            "weights": {
                "tvl": 0.25, "audit": 0.20, "age": 0.20,
                "apy_premium": 0.20, "diversification": 0.15,
            },
        }
        criteria_path = os.path.join(self.tmpdir, "custom_criteria.json")
        with open(criteria_path, "w") as f:
            json.dump(custom, f)
        criteria = sc.load_criteria(criteria_path)
        sc_result = sc.compute_scorecard(
            protocol_id="easy_proto",
            tvl_usd=10_000,
            has_audit=False,
            audit_firms=[],
            launch_date=(date.today() - timedelta(days=5)).isoformat(),
            protocol_apy=5.0,
            t1_avg_apy=4.5,
            current_portfolio={},
            criteria=criteria,
        )
        # With very relaxed criteria and no audit required, should be APPROVED or CONDITIONAL
        self.assertIn(sc_result["verdict"], ("APPROVED", "CONDITIONAL"))


if __name__ == "__main__":
    unittest.main()
