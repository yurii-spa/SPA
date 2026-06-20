"""
Tests for MP-933 ProtocolAirdropEligibilityOptimizer
Run: python3 -m unittest spa_core.tests.test_protocol_airdrop_eligibility_optimizer -v
"""

import json
import os
import sys
import unittest
import tempfile

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from spa_core.analytics.protocol_airdrop_eligibility_optimizer import (
    ProtocolAirdropEligibilityOptimizer,
    _atomic_log,
    _clamp,
    _compute_program_eligibility,
    _compute_wallet_flags,
    _compute_wallet_result,
    _eligibility_label,
    OG_USER_DAYS_AGO,
    POWER_USER_TX_MIN,
    POWER_USER_VOL_MIN,
    MULTI_CHAIN_MIN,
    GOVERNANCE_VOTES_MIN,
    SYBIL_TX_MAX,
)

NO_LOG = {"write_log": False}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _wallet(
    address="0xABC",
    protocols_interacted=None,
    tx_count_total=200,
    unique_days_active=30,
    volume_usd_total=50_000.0,
    earliest_interaction_days_ago=180,
    nft_count=2,
    governance_votes_count=0,
    bridged_chains=None,
    referrals_count=0,
) -> dict:
    if protocols_interacted is None:
        protocols_interacted = ["Uniswap", "Aave"]
    if bridged_chains is None:
        bridged_chains = ["Ethereum"]
    return {
        "address": address,
        "protocols_interacted": protocols_interacted,
        "tx_count_total": tx_count_total,
        "unique_days_active": unique_days_active,
        "volume_usd_total": volume_usd_total,
        "earliest_interaction_days_ago": earliest_interaction_days_ago,
        "nft_count": nft_count,
        "governance_votes_count": governance_votes_count,
        "bridged_chains": bridged_chains,
        "referrals_count": referrals_count,
    }


def _program(
    name="TestDrop",
    token_symbol="TDR",
    token_price_usd=1.0,
    base_allocation_tokens=1000.0,
    criteria=None,
) -> dict:
    if criteria is None:
        criteria = {}
    return {
        "name": name,
        "token_symbol": token_symbol,
        "token_price_usd": token_price_usd,
        "base_allocation_tokens": base_allocation_tokens,
        "criteria": criteria,
    }


def _config_with(programs=None):
    cfg = dict(NO_LOG)
    cfg["airdrop_programs"] = programs or []
    return cfg


# ===========================================================================
# 1. _clamp
# ===========================================================================
class TestClamp(unittest.TestCase):
    def test_below_lo(self):
        self.assertEqual(_clamp(-5.0), 0.0)

    def test_above_hi(self):
        self.assertEqual(_clamp(105.0), 100.0)

    def test_within(self):
        self.assertEqual(_clamp(60.0), 60.0)

    def test_at_lo(self):
        self.assertEqual(_clamp(0.0), 0.0)

    def test_at_hi(self):
        self.assertEqual(_clamp(100.0), 100.0)


# ===========================================================================
# 2. _eligibility_label
# ===========================================================================
class TestEligibilityLabel(unittest.TestCase):
    def test_highly_eligible(self):
        self.assertEqual(_eligibility_label(80.0), "HIGHLY_ELIGIBLE")

    def test_highly_eligible_above(self):
        self.assertEqual(_eligibility_label(95.0), "HIGHLY_ELIGIBLE")

    def test_eligible(self):
        self.assertEqual(_eligibility_label(60.0), "ELIGIBLE")

    def test_partial(self):
        self.assertEqual(_eligibility_label(40.0), "PARTIAL")

    def test_low_chance(self):
        self.assertEqual(_eligibility_label(20.0), "LOW_CHANCE")

    def test_ineligible(self):
        self.assertEqual(_eligibility_label(0.0), "INELIGIBLE")

    def test_ineligible_near_zero(self):
        self.assertEqual(_eligibility_label(10.0), "INELIGIBLE")

    def test_eligible_borderline(self):
        # 79.9 → ELIGIBLE (< 80)
        self.assertEqual(_eligibility_label(79.9), "ELIGIBLE")


# ===========================================================================
# 3. _compute_wallet_flags — OG_USER
# ===========================================================================
class TestFlagsOgUser(unittest.TestCase):
    def test_og_user_exactly_threshold(self):
        w = _wallet(earliest_interaction_days_ago=OG_USER_DAYS_AGO)
        self.assertIn("OG_USER", _compute_wallet_flags(w))

    def test_og_user_above_threshold(self):
        w = _wallet(earliest_interaction_days_ago=500)
        self.assertIn("OG_USER", _compute_wallet_flags(w))

    def test_not_og_user_below_threshold(self):
        w = _wallet(earliest_interaction_days_ago=364)
        self.assertNotIn("OG_USER", _compute_wallet_flags(w))


# ===========================================================================
# 4. _compute_wallet_flags — POWER_USER
# ===========================================================================
class TestFlagsPowerUser(unittest.TestCase):
    def test_power_user_both_thresholds(self):
        w = _wallet(
            tx_count_total=POWER_USER_TX_MIN,
            volume_usd_total=POWER_USER_VOL_MIN,
        )
        self.assertIn("POWER_USER", _compute_wallet_flags(w))

    def test_power_user_above_both(self):
        w = _wallet(tx_count_total=1000, volume_usd_total=500_000.0)
        self.assertIn("POWER_USER", _compute_wallet_flags(w))

    def test_not_power_user_low_tx(self):
        w = _wallet(tx_count_total=100, volume_usd_total=POWER_USER_VOL_MIN)
        self.assertNotIn("POWER_USER", _compute_wallet_flags(w))

    def test_not_power_user_low_vol(self):
        w = _wallet(tx_count_total=POWER_USER_TX_MIN, volume_usd_total=50_000.0)
        self.assertNotIn("POWER_USER", _compute_wallet_flags(w))


# ===========================================================================
# 5. _compute_wallet_flags — MULTI_CHAIN
# ===========================================================================
class TestFlagsMultiChain(unittest.TestCase):
    def test_multi_chain_two_chains(self):
        w = _wallet(bridged_chains=["Ethereum", "Arbitrum"])
        self.assertIn("MULTI_CHAIN", _compute_wallet_flags(w))

    def test_multi_chain_many_chains(self):
        w = _wallet(bridged_chains=["Ethereum", "Arbitrum", "Optimism", "Base"])
        self.assertIn("MULTI_CHAIN", _compute_wallet_flags(w))

    def test_not_multi_chain_single(self):
        w = _wallet(bridged_chains=["Ethereum"])
        self.assertNotIn("MULTI_CHAIN", _compute_wallet_flags(w))

    def test_not_multi_chain_empty(self):
        w = _wallet(bridged_chains=[])
        self.assertNotIn("MULTI_CHAIN", _compute_wallet_flags(w))


# ===========================================================================
# 6. _compute_wallet_flags — GOVERNANCE_PARTICIPANT
# ===========================================================================
class TestFlagsGovernance(unittest.TestCase):
    def test_governance_one_vote(self):
        w = _wallet(governance_votes_count=1)
        self.assertIn("GOVERNANCE_PARTICIPANT", _compute_wallet_flags(w))

    def test_governance_many_votes(self):
        w = _wallet(governance_votes_count=50)
        self.assertIn("GOVERNANCE_PARTICIPANT", _compute_wallet_flags(w))

    def test_no_governance_zero_votes(self):
        w = _wallet(governance_votes_count=0)
        self.assertNotIn("GOVERNANCE_PARTICIPANT", _compute_wallet_flags(w))


# ===========================================================================
# 7. _compute_wallet_flags — SYBIL_RISK
# ===========================================================================
class TestFlagsSybilRisk(unittest.TestCase):
    def test_sybil_risk_few_tx_one_day(self):
        w = _wallet(tx_count_total=5, unique_days_active=1)
        self.assertIn("SYBIL_RISK", _compute_wallet_flags(w))

    def test_sybil_risk_at_max_tx(self):
        w = _wallet(tx_count_total=SYBIL_TX_MAX, unique_days_active=1)
        self.assertIn("SYBIL_RISK", _compute_wallet_flags(w))

    def test_no_sybil_many_tx(self):
        w = _wallet(tx_count_total=100, unique_days_active=1)
        self.assertNotIn("SYBIL_RISK", _compute_wallet_flags(w))

    def test_no_sybil_many_days(self):
        w = _wallet(tx_count_total=5, unique_days_active=30)
        self.assertNotIn("SYBIL_RISK", _compute_wallet_flags(w))

    def test_no_sybil_zero_tx(self):
        w = _wallet(tx_count_total=0, unique_days_active=1)
        self.assertNotIn("SYBIL_RISK", _compute_wallet_flags(w))


# ===========================================================================
# 8. _compute_wallet_flags — combined
# ===========================================================================
class TestFlagsCombined(unittest.TestCase):
    def test_all_positive_flags(self):
        w = _wallet(
            earliest_interaction_days_ago=400,
            tx_count_total=1000,
            volume_usd_total=200_000.0,
            bridged_chains=["Ethereum", "Arbitrum", "Optimism"],
            governance_votes_count=5,
        )
        flags = _compute_wallet_flags(w)
        for expected in ["OG_USER", "POWER_USER", "MULTI_CHAIN", "GOVERNANCE_PARTICIPANT"]:
            self.assertIn(expected, flags)

    def test_returns_list(self):
        w = _wallet()
        self.assertIsInstance(_compute_wallet_flags(w), list)

    def test_empty_flags_for_new_wallet(self):
        w = _wallet(
            earliest_interaction_days_ago=10,
            tx_count_total=50,
            volume_usd_total=1_000.0,
            bridged_chains=["Ethereum"],
            governance_votes_count=0,
            unique_days_active=5,
        )
        flags = _compute_wallet_flags(w)
        self.assertEqual(flags, [])


# ===========================================================================
# 9. _compute_program_eligibility — no criteria (default eligible)
# ===========================================================================
class TestProgramNoCriteria(unittest.TestCase):
    def test_no_criteria_high_score(self):
        w = _wallet()
        p = _program(criteria={})
        result = _compute_program_eligibility(w, p)
        self.assertGreaterEqual(result["eligibility_score"], 60.0)

    def test_no_criteria_completion_100(self):
        w = _wallet()
        p = _program(criteria={})
        result = _compute_program_eligibility(w, p)
        self.assertAlmostEqual(result["completion_pct"], 100.0)

    def test_no_criteria_no_missing(self):
        w = _wallet()
        p = _program(criteria={})
        result = _compute_program_eligibility(w, p)
        self.assertEqual(result["missing_criteria"], [])


# ===========================================================================
# 10. _compute_program_eligibility — min_tx_count criterion
# ===========================================================================
class TestProgramTxCriterion(unittest.TestCase):
    def test_tx_fully_met(self):
        w = _wallet(tx_count_total=500)
        p = _program(criteria={"min_tx_count": 200})
        result = _compute_program_eligibility(w, p)
        self.assertNotIn("tx", " ".join(result["missing_criteria"]).lower())

    def test_tx_partially_met(self):
        w = _wallet(tx_count_total=100)
        p = _program(criteria={"min_tx_count": 200})
        result = _compute_program_eligibility(w, p)
        # Should have missing criteria mentioning txs
        self.assertTrue(any("tx" in c.lower() for c in result["missing_criteria"]))

    def test_tx_not_met_reduces_score(self):
        w_full = _wallet(tx_count_total=500)
        w_none = _wallet(tx_count_total=0)
        p = _program(criteria={"min_tx_count": 500})
        full = _compute_program_eligibility(w_full, p)
        none_ = _compute_program_eligibility(w_none, p)
        self.assertGreater(full["eligibility_score"], none_["eligibility_score"])


# ===========================================================================
# 11. _compute_program_eligibility — min_volume_usd criterion
# ===========================================================================
class TestProgramVolumeCriterion(unittest.TestCase):
    def test_volume_fully_met(self):
        w = _wallet(volume_usd_total=200_000.0)
        p = _program(criteria={"min_volume_usd": 100_000.0})
        result = _compute_program_eligibility(w, p)
        self.assertFalse(any("volume" in c.lower() for c in result["missing_criteria"]))

    def test_volume_not_met_has_missing(self):
        w = _wallet(volume_usd_total=10_000.0)
        p = _program(criteria={"min_volume_usd": 100_000.0})
        result = _compute_program_eligibility(w, p)
        self.assertTrue(any("volume" in c.lower() for c in result["missing_criteria"]))


# ===========================================================================
# 12. _compute_program_eligibility — required_protocols criterion
# ===========================================================================
class TestProgramProtocolsCriterion(unittest.TestCase):
    def test_all_protocols_met(self):
        w = _wallet(protocols_interacted=["Uniswap", "Aave", "Compound"])
        p = _program(criteria={"required_protocols": ["Uniswap", "Aave"]})
        result = _compute_program_eligibility(w, p)
        self.assertFalse(
            any("interact" in c.lower() for c in result["missing_criteria"])
        )

    def test_missing_protocol(self):
        w = _wallet(protocols_interacted=["Uniswap"])
        p = _program(criteria={"required_protocols": ["Uniswap", "Aave"]})
        result = _compute_program_eligibility(w, p)
        self.assertTrue(
            any("interact" in c.lower() for c in result["missing_criteria"])
        )

    def test_empty_required_protocols(self):
        w = _wallet(protocols_interacted=[])
        p = _program(criteria={"required_protocols": []})
        result = _compute_program_eligibility(w, p)
        self.assertAlmostEqual(result["completion_pct"], 100.0)


# ===========================================================================
# 13. _compute_program_eligibility — governance votes criterion
# ===========================================================================
class TestProgramGovernanceCriterion(unittest.TestCase):
    def test_governance_met(self):
        w = _wallet(governance_votes_count=5)
        p = _program(criteria={"min_governance_votes": 3})
        result = _compute_program_eligibility(w, p)
        self.assertFalse(
            any("vote" in c.lower() for c in result["missing_criteria"])
        )

    def test_governance_not_met(self):
        w = _wallet(governance_votes_count=0)
        p = _program(criteria={"min_governance_votes": 3})
        result = _compute_program_eligibility(w, p)
        self.assertTrue(
            any("vote" in c.lower() for c in result["missing_criteria"])
        )


# ===========================================================================
# 14. _compute_program_eligibility — chains bridged criterion
# ===========================================================================
class TestProgramChainsCriterion(unittest.TestCase):
    def test_chains_met(self):
        w = _wallet(bridged_chains=["Ethereum", "Arbitrum", "Optimism"])
        p = _program(criteria={"min_chains_bridged": 2})
        result = _compute_program_eligibility(w, p)
        self.assertFalse(
            any("chain" in c.lower() for c in result["missing_criteria"])
        )

    def test_chains_not_met(self):
        w = _wallet(bridged_chains=["Ethereum"])
        p = _program(criteria={"min_chains_bridged": 3})
        result = _compute_program_eligibility(w, p)
        self.assertTrue(
            any("chain" in c.lower() for c in result["missing_criteria"])
        )


# ===========================================================================
# 15. _compute_program_eligibility — NFT criterion
# ===========================================================================
class TestProgramNftCriterion(unittest.TestCase):
    def test_nft_met(self):
        w = _wallet(nft_count=5)
        p = _program(criteria={"min_nft_count": 3})
        result = _compute_program_eligibility(w, p)
        self.assertFalse(
            any("nft" in c.lower() for c in result["missing_criteria"])
        )

    def test_nft_not_met(self):
        w = _wallet(nft_count=0)
        p = _program(criteria={"min_nft_count": 5})
        result = _compute_program_eligibility(w, p)
        self.assertTrue(
            any("nft" in c.lower() for c in result["missing_criteria"])
        )


# ===========================================================================
# 16. _compute_program_eligibility — eligibility_score range and label
# ===========================================================================
class TestProgramScoreRange(unittest.TestCase):
    def test_score_in_range(self):
        w = _wallet()
        p = _program(criteria={"min_tx_count": 100})
        result = _compute_program_eligibility(w, p)
        self.assertGreaterEqual(result["eligibility_score"], 0.0)
        self.assertLessEqual(result["eligibility_score"], 100.0)

    def test_label_valid(self):
        valid = {"HIGHLY_ELIGIBLE", "ELIGIBLE", "PARTIAL", "LOW_CHANCE", "INELIGIBLE"}
        w = _wallet()
        p = _program(criteria={"min_tx_count": 100})
        result = _compute_program_eligibility(w, p)
        self.assertIn(result["opportunity_label"], valid)

    def test_all_criteria_met_high_score(self):
        w = _wallet(
            tx_count_total=1000,
            volume_usd_total=500_000.0,
            unique_days_active=90,
            protocols_interacted=["Uniswap", "Aave"],
            governance_votes_count=10,
            bridged_chains=["Eth", "Arb"],
            nft_count=10,
        )
        p = _program(criteria={
            "min_tx_count": 100,
            "min_volume_usd": 10_000.0,
            "min_unique_days": 10,
            "required_protocols": ["Uniswap"],
            "min_governance_votes": 1,
            "min_chains_bridged": 2,
            "min_nft_count": 1,
        })
        result = _compute_program_eligibility(w, p)
        self.assertGreaterEqual(result["eligibility_score"], 80.0)

    def test_no_criteria_met_low_score(self):
        w = _wallet(tx_count_total=0, volume_usd_total=0.0)
        p = _program(criteria={"min_tx_count": 1000, "min_volume_usd": 1_000_000.0})
        result = _compute_program_eligibility(w, p)
        self.assertLess(result["eligibility_score"], 50.0)


# ===========================================================================
# 17. _compute_program_eligibility — token estimates
# ===========================================================================
class TestProgramTokenEstimates(unittest.TestCase):
    def test_estimated_tokens_positive(self):
        w = _wallet()
        p = _program(base_allocation_tokens=1000.0)
        result = _compute_program_eligibility(w, p)
        self.assertGreaterEqual(result["estimated_tokens"], 0.0)

    def test_estimated_usd_uses_price(self):
        w = _wallet()
        p = _program(criteria={}, base_allocation_tokens=1000.0, token_price_usd=2.0)
        result = _compute_program_eligibility(w, p)
        # estimated_usd should be ~ estimated_tokens * 2
        self.assertAlmostEqual(
            result["estimated_usd_value"],
            result["estimated_tokens"] * 2.0,
            places=1,
        )

    def test_power_user_bonus_higher_tokens(self):
        w_normal = _wallet(tx_count_total=50, volume_usd_total=1_000.0)
        w_power = _wallet(tx_count_total=600, volume_usd_total=200_000.0)
        p = _program(criteria={})
        r_normal = _compute_program_eligibility(w_normal, p)
        r_power = _compute_program_eligibility(w_power, p)
        self.assertGreater(r_power["estimated_tokens"], r_normal["estimated_tokens"])


# ===========================================================================
# 18. _compute_program_eligibility — result structure
# ===========================================================================
class TestProgramResultStructure(unittest.TestCase):
    def test_required_keys(self):
        w = _wallet()
        p = _program()
        result = _compute_program_eligibility(w, p)
        for k in [
            "program", "token_symbol", "eligibility_score",
            "opportunity_label", "estimated_tokens", "estimated_usd_value",
            "completion_pct", "missing_criteria",
        ]:
            self.assertIn(k, result, msg=f"Missing key: {k}")

    def test_missing_criteria_is_list(self):
        w = _wallet()
        p = _program()
        result = _compute_program_eligibility(w, p)
        self.assertIsInstance(result["missing_criteria"], list)

    def test_program_name_passed_through(self):
        w = _wallet()
        p = _program(name="ArbitrumDrop")
        result = _compute_program_eligibility(w, p)
        self.assertEqual(result["program"], "ArbitrumDrop")

    def test_token_symbol_passed_through(self):
        w = _wallet()
        p = _program(token_symbol="ARB")
        result = _compute_program_eligibility(w, p)
        self.assertEqual(result["token_symbol"], "ARB")


# ===========================================================================
# 19. _compute_wallet_result
# ===========================================================================
class TestComputeWalletResult(unittest.TestCase):
    def test_address_preserved(self):
        w = _wallet(address="0xDEAD")
        result = _compute_wallet_result(w, [], {})
        self.assertEqual(result["address"], "0xDEAD")

    def test_no_programs_zero_total_usd(self):
        w = _wallet()
        result = _compute_wallet_result(w, [], {})
        self.assertAlmostEqual(result["total_estimated_usd"], 0.0)

    def test_no_programs_no_top_opportunity(self):
        w = _wallet()
        result = _compute_wallet_result(w, [], {})
        self.assertIsNone(result["top_opportunity"])

    def test_single_program_top_opportunity(self):
        w = _wallet()
        p = _program(name="Drop1")
        result = _compute_wallet_result(w, [p], {})
        self.assertEqual(result["top_opportunity"], "Drop1")

    def test_best_program_is_top_opportunity(self):
        w = _wallet()
        p1 = _program(name="LowDrop",  base_allocation_tokens=100.0, token_price_usd=1.0)
        p2 = _program(name="HighDrop", base_allocation_tokens=10_000.0, token_price_usd=5.0)
        result = _compute_wallet_result(w, [p1, p2], {})
        self.assertEqual(result["top_opportunity"], "HighDrop")

    def test_total_usd_is_sum(self):
        w = _wallet(tx_count_total=0, volume_usd_total=0.0)
        p1 = _program(name="A", criteria={}, base_allocation_tokens=0.0, token_price_usd=1.0)
        p2 = _program(name="B", criteria={}, base_allocation_tokens=0.0, token_price_usd=1.0)
        result = _compute_wallet_result(w, [p1, p2], {})
        self.assertAlmostEqual(
            result["total_estimated_usd"],
            sum(pr["estimated_usd_value"] for pr in result["airdrop_programs"]),
        )

    def test_completion_roadmap_sorted(self):
        w = _wallet(tx_count_total=10, volume_usd_total=100.0)
        p = _program(criteria={"min_tx_count": 500, "min_volume_usd": 1_000_000.0})
        result = _compute_wallet_result(w, [p], {})
        roadmap = result["completion_roadmap"]
        self.assertEqual(roadmap, sorted(roadmap))

    def test_completion_roadmap_deduplicated(self):
        w = _wallet(tx_count_total=10)
        p1 = _program(name="A", criteria={"min_tx_count": 500})
        p2 = _program(name="B", criteria={"min_tx_count": 500})
        result = _compute_wallet_result(w, [p1, p2], {})
        # Same missing criterion from both programs should appear only once
        self.assertEqual(
            len(result["completion_roadmap"]),
            len(set(result["completion_roadmap"])),
        )

    def test_flags_present(self):
        w = _wallet(earliest_interaction_days_ago=400)
        result = _compute_wallet_result(w, [], {})
        self.assertIn("OG_USER", result["flags"])

    def test_airdrop_programs_key_present(self):
        w = _wallet()
        result = _compute_wallet_result(w, [_program()], {})
        self.assertIn("airdrop_programs", result)


# ===========================================================================
# 20. _atomic_log
# ===========================================================================
class TestAtomicLog(unittest.TestCase):
    def test_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "test_log.json")
            _atomic_log({"x": 1}, p)
            self.assertTrue(os.path.exists(p))

    def test_entry_written(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            _atomic_log({"v": 42}, p)
            with open(p) as f:
                data = json.load(f)
            self.assertEqual(data[0]["v"], 42)

    def test_ring_buffer_cap(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            for i in range(110):
                _atomic_log({"i": i}, p, max_entries=100)
            with open(p) as f:
                data = json.load(f)
            self.assertLessEqual(len(data), 100)

    def test_ring_buffer_latest_kept(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            for i in range(110):
                _atomic_log({"i": i}, p, max_entries=100)
            with open(p) as f:
                data = json.load(f)
            self.assertEqual(data[-1]["i"], 109)

    def test_multiple_appends(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "log.json")
            _atomic_log({"n": 1}, p)
            _atomic_log({"n": 2}, p)
            _atomic_log({"n": 3}, p)
            with open(p) as f:
                data = json.load(f)
            self.assertEqual(len(data), 3)


# ===========================================================================
# 21. ProtocolAirdropEligibilityOptimizer — instantiation
# ===========================================================================
class TestOptimizerInstantiation(unittest.TestCase):
    def test_instantiation(self):
        o = ProtocolAirdropEligibilityOptimizer()
        self.assertIsNotNone(o)

    def test_has_optimize_method(self):
        o = ProtocolAirdropEligibilityOptimizer()
        self.assertTrue(callable(getattr(o, "optimize", None)))


# ===========================================================================
# 22. ProtocolAirdropEligibilityOptimizer.optimize — empty wallets
# ===========================================================================
class TestOptimizeEmpty(unittest.TestCase):
    def setUp(self):
        self.o = ProtocolAirdropEligibilityOptimizer()

    def test_empty_status_ok(self):
        r = self.o.optimize([], NO_LOG)
        self.assertEqual(r["status"], "ok")

    def test_empty_count_zero(self):
        r = self.o.optimize([], NO_LOG)
        self.assertEqual(r["wallets_analyzed"], 0)

    def test_empty_wallets_list(self):
        r = self.o.optimize([], NO_LOG)
        self.assertEqual(r["wallets"], [])

    def test_empty_has_timestamp(self):
        r = self.o.optimize([], NO_LOG)
        self.assertIn("timestamp", r)

    def test_empty_programs_evaluated(self):
        r = self.o.optimize([], _config_with(programs=[_program()]))
        self.assertEqual(r["programs_evaluated"], 1)


# ===========================================================================
# 23. ProtocolAirdropEligibilityOptimizer.optimize — single wallet
# ===========================================================================
class TestOptimizeSingleWallet(unittest.TestCase):
    def setUp(self):
        self.o = ProtocolAirdropEligibilityOptimizer()

    def test_single_wallet_count(self):
        r = self.o.optimize([_wallet()], NO_LOG)
        self.assertEqual(r["wallets_analyzed"], 1)

    def test_single_wallet_address_preserved(self):
        r = self.o.optimize([_wallet(address="0xFEED")], NO_LOG)
        self.assertEqual(r["wallets"][0]["address"], "0xFEED")

    def test_single_wallet_no_programs(self):
        r = self.o.optimize([_wallet()], _config_with(programs=[]))
        self.assertAlmostEqual(r["wallets"][0]["total_estimated_usd"], 0.0)

    def test_single_wallet_with_program(self):
        p = _program(criteria={})
        r = self.o.optimize([_wallet()], _config_with(programs=[p]))
        self.assertEqual(len(r["wallets"][0]["airdrop_programs"]), 1)

    def test_single_wallet_flags(self):
        w = _wallet(earliest_interaction_days_ago=400)
        r = self.o.optimize([w], NO_LOG)
        self.assertIn("OG_USER", r["wallets"][0]["flags"])


# ===========================================================================
# 24. ProtocolAirdropEligibilityOptimizer.optimize — multiple wallets
# ===========================================================================
class TestOptimizeMultipleWallets(unittest.TestCase):
    def setUp(self):
        self.o = ProtocolAirdropEligibilityOptimizer()

    def test_multiple_wallets_count(self):
        wallets = [_wallet(address=f"0x{i:03d}") for i in range(5)]
        r = self.o.optimize(wallets, NO_LOG)
        self.assertEqual(r["wallets_analyzed"], 5)

    def test_multiple_wallets_different_addresses(self):
        wallets = [
            _wallet(address="0xAAA"),
            _wallet(address="0xBBB"),
        ]
        r = self.o.optimize(wallets, NO_LOG)
        addresses = [w["address"] for w in r["wallets"]]
        self.assertIn("0xAAA", addresses)
        self.assertIn("0xBBB", addresses)

    def test_programs_evaluated_count(self):
        wallets = [_wallet()]
        programs = [_program(name=f"Drop{i}") for i in range(3)]
        r = self.o.optimize(wallets, _config_with(programs=programs))
        self.assertEqual(r["programs_evaluated"], 3)


# ===========================================================================
# 25. Log behaviour in optimize
# ===========================================================================
class TestOptimizeLogBehaviour(unittest.TestCase):
    def setUp(self):
        self.o = ProtocolAirdropEligibilityOptimizer()

    def test_no_log_does_not_create_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            self.o.optimize([], {"write_log": False, "log_path": path})
            self.assertFalse(os.path.exists(path))

    def test_write_log_creates_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "log.json")
            self.o.optimize([], {"write_log": True, "log_path": path})
            self.assertTrue(os.path.exists(path))

    def test_none_config_defaults(self):
        r = self.o.optimize([], None)
        self.assertEqual(r["status"], "ok")


# ===========================================================================
# 26. Opportunity labels coverage
# ===========================================================================
class TestOpportunityLabels(unittest.TestCase):
    def setUp(self):
        self.o = ProtocolAirdropEligibilityOptimizer()

    def _get_label(self, wallet, criteria):
        p = _program(criteria=criteria)
        r = self.o.optimize([wallet], _config_with(programs=[p]))
        return r["wallets"][0]["airdrop_programs"][0]["opportunity_label"]

    def test_highly_eligible_label(self):
        w = _wallet(tx_count_total=5000, volume_usd_total=999_999.0)
        label = self._get_label(w, {"min_tx_count": 10})
        self.assertEqual(label, "HIGHLY_ELIGIBLE")

    def test_ineligible_label(self):
        w = _wallet(tx_count_total=0)
        label = self._get_label(
            w,
            {"min_tx_count": 10_000, "min_volume_usd": 10_000_000.0},
        )
        self.assertIn(label, {"INELIGIBLE", "LOW_CHANCE", "PARTIAL"})


# ===========================================================================
# 27. Timestamp format
# ===========================================================================
class TestTimestamp(unittest.TestCase):
    def test_timestamp_format(self):
        o = ProtocolAirdropEligibilityOptimizer()
        r = o.optimize([], NO_LOG)
        self.assertRegex(r["timestamp"], r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z")


if __name__ == "__main__":
    unittest.main()
