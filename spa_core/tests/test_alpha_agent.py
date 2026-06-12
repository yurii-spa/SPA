"""Tests for spa_core/agents/alpha_agent.py (MP-304).

Covers: scoring components, risk flag detection, diversification bonus,
fail-safe behavior, output file content, no stray .tmp files.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from spa_core.agents.alpha_agent import (
    AlphaScore,
    _compute_risk_flags,
    _score_apy,
    _score_exit,
    _score_tier_bonus,
    _score_tvl,
    _score_diversification,
    generate_rationale_with_llm,
    get_top_candidates,
    run_alpha_scan,
    score_candidate,
)


class TestTvlScore(unittest.TestCase):
    """tvl_score: >$100M → 30, >$50M → 20, >$10M → 10, else 0."""

    def test_above_100m(self):
        self.assertEqual(_score_tvl(150_000_000), 30)

    def test_exactly_100m(self):
        # >$100M means strictly greater than 100M
        self.assertEqual(_score_tvl(100_000_001), 30)

    def test_at_100m(self):
        # exactly 100M is NOT >100M → falls through to >50M check
        self.assertEqual(_score_tvl(100_000_000), 20)

    def test_between_50m_and_100m(self):
        self.assertEqual(_score_tvl(75_000_000), 20)

    def test_exactly_50m(self):
        self.assertEqual(_score_tvl(50_000_000), 10)

    def test_between_10m_and_50m(self):
        self.assertEqual(_score_tvl(25_000_000), 10)

    def test_exactly_10m(self):
        self.assertEqual(_score_tvl(10_000_000), 0)

    def test_below_10m(self):
        self.assertEqual(_score_tvl(1_000_000), 0)

    def test_zero_tvl(self):
        self.assertEqual(_score_tvl(0), 0)


class TestApyScore(unittest.TestCase):
    """apy_score: 5-10% → 20, 3-5% → 10, >10% → 5 (sanity cap), else 0."""

    def test_good_band_5_to_10(self):
        self.assertEqual(_score_apy(7.0), 20)

    def test_good_band_lower_bound_inclusive(self):
        self.assertEqual(_score_apy(5.0), 20)

    def test_good_band_upper_bound_inclusive(self):
        self.assertEqual(_score_apy(10.0), 20)

    def test_medium_band_3_to_5(self):
        self.assertEqual(_score_apy(4.0), 10)

    def test_medium_band_lower_bound(self):
        self.assertEqual(_score_apy(3.0), 10)

    def test_above_10_sanity_cap(self):
        self.assertEqual(_score_apy(15.0), 5)

    def test_above_20_still_sanity_cap(self):
        self.assertEqual(_score_apy(25.0), 5)

    def test_below_3(self):
        self.assertEqual(_score_apy(2.0), 0)

    def test_zero_apy(self):
        self.assertEqual(_score_apy(0.0), 0)

    def test_negative_apy(self):
        self.assertEqual(_score_apy(-1.0), 0)


class TestExitScore(unittest.TestCase):
    """exit_score: instant (0h) → 20, <24h → 15, <168h → 5, else 0, None → 0."""

    def test_instant(self):
        self.assertEqual(_score_exit(0.0), 20)

    def test_less_than_24h(self):
        self.assertEqual(_score_exit(12.0), 15)

    def test_between_24h_and_168h(self):
        self.assertEqual(_score_exit(72.0), 5)

    def test_exactly_24h(self):
        self.assertEqual(_score_exit(24.0), 5)

    def test_above_168h(self):
        self.assertEqual(_score_exit(200.0), 0)

    def test_exactly_168h(self):
        self.assertEqual(_score_exit(168.0), 0)

    def test_none_exit_latency(self):
        self.assertEqual(_score_exit(None), 0)


class TestTierBonus(unittest.TestCase):
    """tier_bonus: T2 → 15, T3 → 10, "candidate" → 10."""

    def test_t2(self):
        self.assertEqual(_score_tier_bonus("T2"), 15)

    def test_t3(self):
        self.assertEqual(_score_tier_bonus("T3"), 10)

    def test_candidate(self):
        self.assertEqual(_score_tier_bonus("candidate"), 10)

    def test_t1(self):
        # T1 is already active — no bonus defined → falls to default
        self.assertEqual(_score_tier_bonus("T1"), 10)


class TestDiversificationBonus(unittest.TestCase):
    """diversification_bonus: not in active_protocols → 15, already active → 0."""

    def test_not_active(self):
        active = ["aave_v3", "compound_v3"]
        self.assertEqual(_score_diversification("spark-protocol", active), 15)

    def test_exactly_active(self):
        active = ["aave_v3", "compound_v3"]
        self.assertEqual(_score_diversification("aave_v3", active), 0)

    def test_substring_match_active(self):
        active = ["morpho_blue"]
        # "morpho-blue" should match "morpho_blue" via substring
        self.assertEqual(_score_diversification("morpho-blue", active), 0)

    def test_empty_active(self):
        self.assertEqual(_score_diversification("any-protocol", []), 15)

    def test_case_insensitive(self):
        active = ["AAVE_V3"]
        self.assertEqual(_score_diversification("aave_v3", active), 0)


class TestRiskFlags(unittest.TestCase):
    """risk_flags determined from protocol/symbol/tvl/exit."""

    def test_credit_risk_flag(self):
        flags = _compute_risk_flags("credit-protocol", "USDC", 50_000_000, None)
        self.assertIn("credit_risk", flags)

    def test_peg_risk_in_protocol(self):
        flags = _compute_risk_flags("peg-stability-module", "USDC", 50_000_000, None)
        self.assertIn("peg_risk", flags)

    def test_peg_risk_in_symbol(self):
        flags = _compute_risk_flags("some-protocol", "USDC-peg", 50_000_000, None)
        self.assertIn("peg_risk", flags)

    def test_low_liquidity(self):
        flags = _compute_risk_flags("some-protocol", "USDC", 5_000_000, None)
        self.assertIn("low_liquidity", flags)

    def test_high_exit_latency(self):
        flags = _compute_risk_flags("some-protocol", "USDC", 50_000_000, 100.0)
        self.assertIn("high_exit_latency", flags)

    def test_no_flags_clean_protocol(self):
        flags = _compute_risk_flags("spark-lending", "USDC", 200_000_000, 12.0)
        self.assertEqual(flags, [])

    def test_multiple_flags(self):
        # credit_risk + low_liquidity + high_exit_latency
        flags = _compute_risk_flags("credit-market", "USDC", 1_000_000, 100.0)
        self.assertIn("credit_risk", flags)
        self.assertIn("low_liquidity", flags)
        self.assertIn("high_exit_latency", flags)


class TestScoreCandidate(unittest.TestCase):
    """score_candidate integrates all components correctly."""

    def _make_candidate(self, **kwargs) -> dict:
        defaults = {
            "protocol": "test-protocol",
            "symbol": "USDC",
            "chain": "ethereum",
            "apy_pct": 6.0,
            "tvl_usd": 120_000_000,
            "suggested_tier": "candidate",
        }
        defaults.update(kwargs)
        return defaults

    def test_high_tvl_good_apy_returns_high_score(self):
        cand = self._make_candidate(tvl_usd=120_000_000, apy_pct=7.0)
        result = score_candidate(cand, active_protocols=[])
        # tvl=30 + apy=20 + exit=0 (None) + tier=10 + div=15 = 75
        self.assertEqual(result.tvl_score, 30)
        self.assertEqual(result.apy_score, 20)
        self.assertEqual(result.diversification_bonus, 15)
        self.assertGreaterEqual(result.score, 70)

    def test_low_tvl_gives_low_score(self):
        cand = self._make_candidate(tvl_usd=1_000_000, apy_pct=5.0)
        result = score_candidate(cand, active_protocols=[])
        self.assertEqual(result.tvl_score, 0)
        self.assertIn("low_liquidity", result.risk_flags)

    def test_already_active_loses_diversification_bonus(self):
        cand = self._make_candidate(protocol="aave-v3", tvl_usd=120_000_000)
        result_no_active = score_candidate(cand, active_protocols=[])
        result_active = score_candidate(cand, active_protocols=["aave-v3"])
        self.assertEqual(result_no_active.diversification_bonus, 15)
        self.assertEqual(result_active.diversification_bonus, 0)
        self.assertEqual(result_no_active.score - result_active.score, 15)

    def test_score_clamped_to_100(self):
        cand = self._make_candidate(tvl_usd=200_000_000, apy_pct=7.0, exit_latency_hours=0.0)
        result = score_candidate(cand, active_protocols=[])
        self.assertLessEqual(result.score, 100)
        self.assertGreaterEqual(result.score, 0)

    def test_suggested_tier_always_candidate(self):
        cand = self._make_candidate()
        result = score_candidate(cand, active_protocols=[])
        self.assertEqual(result.suggested_tier, "candidate")

    def test_rationale_generated(self):
        cand = self._make_candidate(tvl_usd=100_000_000, apy_pct=6.0)
        result = score_candidate(cand, active_protocols=[])
        self.assertIsInstance(result.rationale, str)
        self.assertGreater(len(result.rationale), 10)

    def test_high_apy_sanity_cap(self):
        cand = self._make_candidate(apy_pct=25.0)
        result = score_candidate(cand, active_protocols=[])
        self.assertEqual(result.apy_score, 5)

    def test_exit_latency_scoring(self):
        cand_instant = self._make_candidate(exit_latency_hours=0.0)
        cand_day = self._make_candidate(exit_latency_hours=12.0)
        cand_slow = self._make_candidate(exit_latency_hours=200.0)
        r_instant = score_candidate(cand_instant, [])
        r_day = score_candidate(cand_day, [])
        r_slow = score_candidate(cand_slow, [])
        self.assertEqual(r_instant.exit_score, 20)
        self.assertEqual(r_day.exit_score, 15)
        self.assertEqual(r_slow.exit_score, 0)


class TestGenerateRationale(unittest.TestCase):
    """generate_rationale_with_llm: deterministic fallback and LLM path."""

    def test_deterministic_template(self):
        candidate = {
            "name": "TestProto",
            "protocol_id": "test-proto",
            "score": 75,
            "tvl_usd": 50_000_000.0,
            "apy_pct": 6.5,
            "risk_flags": ["low_liquidity"],
        }
        rationale = generate_rationale_with_llm(candidate, llm_fn=None)
        self.assertIn("TestProto", rationale)
        self.assertIn("75/100", rationale)
        self.assertIn("6.50%", rationale)
        self.assertIn("low_liquidity", rationale)

    def test_llm_fn_called(self):
        candidate = {"name": "T", "score": 50, "tvl_usd": 0, "apy_pct": 0, "risk_flags": []}
        called = []

        def mock_llm(c):
            called.append(c)
            return "LLM rationale"

        result = generate_rationale_with_llm(candidate, llm_fn=mock_llm)
        self.assertEqual(result, "LLM rationale")
        self.assertEqual(len(called), 1)

    def test_llm_fn_failure_falls_back(self):
        candidate = {
            "name": "TestProto",
            "protocol_id": "test-proto",
            "score": 50,
            "tvl_usd": 10_000_000.0,
            "apy_pct": 5.0,
            "risk_flags": [],
        }

        def failing_llm(c):
            raise RuntimeError("LLM unavailable")

        result = generate_rationale_with_llm(candidate, llm_fn=failing_llm)
        # Must fall back to deterministic template, not raise
        self.assertIn("TestProto", result)


class TestRunAlphaScan(unittest.TestCase):
    """run_alpha_scan: file writes, fail-safe, content checks."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write_json(self, filename: str, obj):
        (self.data_dir / filename).write_text(
            json.dumps(obj, indent=2), encoding="utf-8"
        )

    def _make_candidate_registry(self, n: int = 3) -> dict:
        candidates = []
        for i in range(n):
            candidates.append({
                "protocol": f"proto-{i}",
                "symbol": "USDC",
                "chain": "ethereum",
                "apy_pct": 5.0 + i,
                "tvl_usd": 50_000_000 * (i + 1),
                "suggested_tier": "candidate",
            })
        return {"status": "ok", "candidates": candidates}

    def test_writes_alpha_candidates_json(self):
        self._write_json("candidate_registry.json", self._make_candidate_registry())
        run_alpha_scan(data_dir=self.data_dir)
        out = self.data_dir / "alpha_candidates.json"
        self.assertTrue(out.exists(), "alpha_candidates.json should be written")

    def test_output_contains_note_about_adr(self):
        self._write_json("candidate_registry.json", self._make_candidate_registry())
        result = run_alpha_scan(data_dir=self.data_dir)
        note = result.get("note", "")
        self.assertIn("ADR", note, "note must mention ADR/human review")

    def test_top_5_limit(self):
        self._write_json("candidate_registry.json", self._make_candidate_registry(n=10))
        result = run_alpha_scan(data_dir=self.data_dir)
        self.assertLessEqual(len(result["candidates"]), 5)

    def test_fail_safe_empty_files(self):
        # No source files at all — should not raise
        result = run_alpha_scan(data_dir=self.data_dir)
        self.assertIsInstance(result, dict)
        self.assertEqual(result["candidates"], [])

    def test_fail_safe_missing_candidate_file(self):
        # Only orchestrator status, no candidate_registry
        self._write_json("adapter_orchestrator_status.json", {"adapters": []})
        result = run_alpha_scan(data_dir=self.data_dir)
        self.assertIsInstance(result, dict)

    def test_no_stray_tmp_files(self):
        self._write_json("candidate_registry.json", self._make_candidate_registry())
        run_alpha_scan(data_dir=self.data_dir)
        tmp_files = list(self.data_dir.glob("*.tmp"))
        self.assertEqual(len(tmp_files), 0, f"Stray .tmp files found: {tmp_files}")

    def test_already_active_filtered(self):
        self._write_json("candidate_registry.json", self._make_candidate_registry(n=3))
        self._write_json("adapter_orchestrator_status.json", {
            "adapters": [{"protocol": "proto-0"}]
        })
        result = run_alpha_scan(data_dir=self.data_dir)
        # proto-0 should have lower diversification_bonus
        candidates = result["candidates"]
        if candidates:
            proto0 = next((c for c in candidates if c["protocol_id"] == "proto-0"), None)
            if proto0:
                self.assertEqual(proto0["diversification_bonus"], 0)

    def test_already_active_in_output(self):
        self._write_json("candidate_registry.json", self._make_candidate_registry(n=2))
        self._write_json("adapter_orchestrator_status.json", {
            "adapters": [{"protocol": "proto-0"}, {"protocol": "proto-1"}]
        })
        result = run_alpha_scan(data_dir=self.data_dir)
        self.assertIn("already_active", result)
        self.assertIsInstance(result["already_active"], list)

    def test_scan_basis_field(self):
        result = run_alpha_scan(data_dir=self.data_dir)
        self.assertIn("scan_basis", result)
        self.assertIn("candidate_registry", result["scan_basis"])

    def test_generated_at_field(self):
        result = run_alpha_scan(data_dir=self.data_dir)
        self.assertIn("generated_at", result)
        # Should be a valid ISO datetime string
        ts = result["generated_at"]
        self.assertIn("T", ts)


class TestGetTopCandidates(unittest.TestCase):
    """get_top_candidates: returns AlphaScore list sorted by score."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.data_dir = Path(self.tmpdir)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_returns_list_of_alpha_scores(self):
        candidates = [
            {"protocol": f"p{i}", "symbol": "USDC", "apy_pct": 5.0, "tvl_usd": 50_000_000}
            for i in range(3)
        ]
        (self.data_dir / "candidate_registry.json").write_text(
            json.dumps({"candidates": candidates}), encoding="utf-8"
        )
        result = get_top_candidates(n=3, data_dir=self.data_dir)
        self.assertIsInstance(result, list)
        for item in result:
            self.assertIsInstance(item, AlphaScore)

    def test_empty_returns_empty(self):
        result = get_top_candidates(n=5, data_dir=self.data_dir)
        self.assertEqual(result, [])

    def test_sorted_by_score_desc(self):
        candidates = [
            {"protocol": "low-tvl", "symbol": "USDC", "apy_pct": 5.0, "tvl_usd": 1_000_000},
            {"protocol": "high-tvl", "symbol": "USDC", "apy_pct": 7.0, "tvl_usd": 200_000_000},
        ]
        (self.data_dir / "candidate_registry.json").write_text(
            json.dumps({"candidates": candidates}), encoding="utf-8"
        )
        result = get_top_candidates(n=2, data_dir=self.data_dir)
        if len(result) >= 2:
            self.assertGreaterEqual(result[0].score, result[1].score)


if __name__ == "__main__":
    unittest.main()
