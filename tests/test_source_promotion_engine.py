"""
tests/test_source_promotion_engine.py

Tests for spa_core/backtesting/source_promotion_engine.py

40 tests covering:
  - State machine transition validation
  - promote() success / failure / wrong from_state
  - promotion_history() (full + filtered)
  - sources_needing_promotion() contents
  - promotion_roadmap() structure
  - Atomic log append
  - PromotionEvidence serialization / deserialization

MP-1319 / Sprint v9.35
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

# ─── path setup ───────────────────────────────────────────────────────────────
_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from spa_core.backtesting.source_pipeline import SourcePipeline, SourceState
from spa_core.backtesting.source_promotion_engine import (
    PromotionEvidence,
    SourcePromotionEngine,
)


# ─── helpers ──────────────────────────────────────────────────────────────────

def _make_evidence(
    source_id: str = "btc_usd_conc_liq",
    from_state: str = SourceState.SOURCE_NEEDED,
    to_state: str = SourceState.PENDING,
    promoted_by: str = "yurii",
    evidence_url: str = "https://defillama.com/protocol/test",
    data_period_start: str = "2023-01-01",
    data_period_end: str = "2026-06-01",
    notes: str = "test evidence",
) -> PromotionEvidence:
    return PromotionEvidence(
        source_id=source_id,
        from_state=from_state,
        to_state=to_state,
        promoted_by=promoted_by,
        evidence_url=evidence_url,
        data_period_start=data_period_start,
        data_period_end=data_period_end,
        notes=notes,
    )


def _make_engine_with_tmpdir() -> tuple[SourcePromotionEngine, Path]:
    """Create an engine backed by an isolated temp directory."""
    tmp = tempfile.mkdtemp()
    tmp_path = Path(tmp)
    pipeline = SourcePipeline(data_dir=tmp_path)
    engine = SourcePromotionEngine(pipeline=pipeline, data_dir=tmp_path)
    return engine, tmp_path


# ══════════════════════════════════════════════════════════════════════════════
# 1. validate_promotion — state machine rules
# ══════════════════════════════════════════════════════════════════════════════

class TestValidatePromotion(unittest.TestCase):

    def setUp(self):
        self.engine, _ = _make_engine_with_tmpdir()

    # Forward path
    def test_validate_source_needed_to_pending_true(self):
        self.assertTrue(
            self.engine.validate_promotion(SourceState.SOURCE_NEEDED, SourceState.PENDING)
        )

    def test_validate_pending_to_review_true(self):
        self.assertTrue(
            self.engine.validate_promotion(SourceState.PENDING, SourceState.REVIEW)
        )

    def test_validate_review_to_clean_included_true(self):
        self.assertTrue(
            self.engine.validate_promotion(SourceState.REVIEW, SourceState.CLEAN_INCLUDED)
        )

    # Proxy path
    def test_validate_manual_proxy_to_review_true(self):
        self.assertTrue(
            self.engine.validate_promotion(SourceState.MANUAL_PROXY, SourceState.REVIEW)
        )

    # Downgrade paths
    def test_validate_source_needed_to_research_only_true(self):
        self.assertTrue(
            self.engine.validate_promotion(SourceState.SOURCE_NEEDED, SourceState.RESEARCH_ONLY)
        )

    def test_validate_pending_to_research_only_true(self):
        self.assertTrue(
            self.engine.validate_promotion(SourceState.PENDING, SourceState.RESEARCH_ONLY)
        )

    def test_validate_review_to_research_only_true(self):
        self.assertTrue(
            self.engine.validate_promotion(SourceState.REVIEW, SourceState.RESEARCH_ONLY)
        )

    def test_validate_manual_proxy_to_research_only_true(self):
        self.assertTrue(
            self.engine.validate_promotion(SourceState.MANUAL_PROXY, SourceState.RESEARCH_ONLY)
        )

    def test_validate_clean_included_to_research_only_true(self):
        self.assertTrue(
            self.engine.validate_promotion(SourceState.CLEAN_INCLUDED, SourceState.RESEARCH_ONLY)
        )

    # Skip / invalid paths
    def test_validate_source_needed_to_clean_included_false(self):
        """Cannot skip PENDING and REVIEW."""
        self.assertFalse(
            self.engine.validate_promotion(SourceState.SOURCE_NEEDED, SourceState.CLEAN_INCLUDED)
        )

    def test_validate_source_needed_to_review_skip_false(self):
        """Cannot skip PENDING."""
        self.assertFalse(
            self.engine.validate_promotion(SourceState.SOURCE_NEEDED, SourceState.REVIEW)
        )

    def test_validate_pending_to_clean_included_skip_false(self):
        """Cannot skip REVIEW."""
        self.assertFalse(
            self.engine.validate_promotion(SourceState.PENDING, SourceState.CLEAN_INCLUDED)
        )

    def test_validate_manual_proxy_to_clean_included_false(self):
        """MANUAL_PROXY must go through REVIEW first."""
        self.assertFalse(
            self.engine.validate_promotion(SourceState.MANUAL_PROXY, SourceState.CLEAN_INCLUDED)
        )

    def test_validate_manual_proxy_to_pending_false(self):
        """Wrong path for manual proxy."""
        self.assertFalse(
            self.engine.validate_promotion(SourceState.MANUAL_PROXY, SourceState.PENDING)
        )


# ══════════════════════════════════════════════════════════════════════════════
# 2. promote() — success cases
# ══════════════════════════════════════════════════════════════════════════════

class TestPromoteSuccess(unittest.TestCase):

    def setUp(self):
        self.engine, self.tmpdir = _make_engine_with_tmpdir()

    def test_promote_returns_dict(self):
        ev = _make_evidence()
        result = self.engine.promote(ev)
        self.assertIsInstance(result, dict)

    def test_promote_success_is_true(self):
        ev = _make_evidence()
        result = self.engine.promote(ev)
        self.assertTrue(result["success"])

    def test_promote_success_blocked_by_is_none(self):
        ev = _make_evidence()
        result = self.engine.promote(ev)
        self.assertIsNone(result["blocked_by"])

    def test_promote_updates_pipeline_state(self):
        ev = _make_evidence(source_id="btc_usd_conc_liq")
        self.engine.promote(ev)
        new_state = self.engine._pipeline.state("btc_usd_conc_liq")
        self.assertEqual(new_state, SourceState.PENDING)

    def test_promote_appends_to_log(self):
        ev = _make_evidence()
        self.engine.promote(ev)
        history = self.engine.promotion_history()
        self.assertEqual(len(history), 1)

    def test_promote_returns_from_and_to_state(self):
        ev = _make_evidence(
            from_state=SourceState.SOURCE_NEEDED,
            to_state=SourceState.PENDING,
        )
        result = self.engine.promote(ev)
        self.assertEqual(result["from_state"], SourceState.SOURCE_NEEDED)
        self.assertEqual(result["to_state"], SourceState.PENDING)

    def test_promote_two_sequential_promotions(self):
        """Promote SOURCE_NEEDED → PENDING → REVIEW."""
        e1 = _make_evidence(
            source_id="btc_usd_conc_liq",
            from_state=SourceState.SOURCE_NEEDED,
            to_state=SourceState.PENDING,
        )
        e2 = _make_evidence(
            source_id="btc_usd_conc_liq",
            from_state=SourceState.PENDING,
            to_state=SourceState.REVIEW,
        )
        r1 = self.engine.promote(e1)
        r2 = self.engine.promote(e2)
        self.assertTrue(r1["success"])
        self.assertTrue(r2["success"])
        self.assertEqual(self.engine._pipeline.state("btc_usd_conc_liq"), SourceState.REVIEW)


# ══════════════════════════════════════════════════════════════════════════════
# 3. promote() — failure cases
# ══════════════════════════════════════════════════════════════════════════════

class TestPromoteFailures(unittest.TestCase):

    def setUp(self):
        self.engine, _ = _make_engine_with_tmpdir()

    def test_promote_invalid_transition_fails(self):
        """SOURCE_NEEDED → CLEAN_INCLUDED is invalid."""
        ev = _make_evidence(
            from_state=SourceState.SOURCE_NEEDED,
            to_state=SourceState.CLEAN_INCLUDED,
        )
        result = self.engine.promote(ev)
        self.assertFalse(result["success"])

    def test_promote_wrong_from_state_fails(self):
        """Evidence says PENDING but pipeline has SOURCE_NEEDED."""
        ev = _make_evidence(
            source_id="btc_usd_conc_liq",
            from_state=SourceState.PENDING,      # wrong — actual is SOURCE_NEEDED
            to_state=SourceState.REVIEW,
        )
        result = self.engine.promote(ev)
        self.assertFalse(result["success"])

    def test_promote_wrong_from_state_blocked_by_message(self):
        ev = _make_evidence(
            source_id="btc_usd_conc_liq",
            from_state=SourceState.PENDING,
            to_state=SourceState.REVIEW,
        )
        result = self.engine.promote(ev)
        self.assertIsNotNone(result["blocked_by"])
        self.assertIn("mismatch", result["blocked_by"])

    def test_promote_invalid_transition_blocked_by_message(self):
        ev = _make_evidence(
            from_state=SourceState.SOURCE_NEEDED,
            to_state=SourceState.CLEAN_INCLUDED,
        )
        result = self.engine.promote(ev)
        self.assertIsNotNone(result["blocked_by"])
        self.assertIn("Invalid transition", result["blocked_by"])

    def test_promote_failure_does_not_update_pipeline(self):
        """Failed promote must not change the pipeline state."""
        original = self.engine._pipeline.state("btc_usd_conc_liq")
        ev = _make_evidence(
            from_state=SourceState.SOURCE_NEEDED,
            to_state=SourceState.CLEAN_INCLUDED,
        )
        self.engine.promote(ev)
        self.assertEqual(self.engine._pipeline.state("btc_usd_conc_liq"), original)

    def test_promote_failure_does_not_append_log(self):
        """Failed promote must not write to the log."""
        ev = _make_evidence(
            from_state=SourceState.SOURCE_NEEDED,
            to_state=SourceState.CLEAN_INCLUDED,
        )
        self.engine.promote(ev)
        self.assertEqual(len(self.engine.promotion_history()), 0)


# ══════════════════════════════════════════════════════════════════════════════
# 4. promotion_history()
# ══════════════════════════════════════════════════════════════════════════════

class TestPromotionHistory(unittest.TestCase):

    def setUp(self):
        self.engine, _ = _make_engine_with_tmpdir()

    def test_history_empty_initially(self):
        self.assertEqual(self.engine.promotion_history(), [])

    def test_history_returns_list_of_dicts(self):
        ev = _make_evidence()
        self.engine.promote(ev)
        history = self.engine.promotion_history()
        self.assertIsInstance(history, list)
        self.assertIsInstance(history[0], dict)

    def test_history_filtered_by_source_id(self):
        ev1 = _make_evidence(source_id="btc_usd_conc_liq")
        ev2 = _make_evidence(
            source_id="rwa_conc_liq",
            from_state=SourceState.SOURCE_NEEDED,
            to_state=SourceState.PENDING,
        )
        self.engine.promote(ev1)
        self.engine.promote(ev2)
        filtered = self.engine.promotion_history(source_id="rwa_conc_liq")
        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered[0]["source_id"], "rwa_conc_liq")

    def test_history_filtered_returns_empty_for_unknown(self):
        ev = _make_evidence()
        self.engine.promote(ev)
        filtered = self.engine.promotion_history(source_id="no_such_source")
        self.assertEqual(filtered, [])

    def test_history_entry_has_expected_keys(self):
        ev = _make_evidence()
        self.engine.promote(ev)
        entry = self.engine.promotion_history()[0]
        for key in ("source_id", "from_state", "to_state", "promoted_by",
                    "evidence_url", "promoted_at"):
            self.assertIn(key, entry)

    def test_multiple_promotions_all_logged(self):
        ev1 = _make_evidence(source_id="btc_usd_conc_liq")
        ev2 = _make_evidence(source_id="rwa_conc_liq")
        self.engine.promote(ev1)
        self.engine.promote(ev2)
        self.assertEqual(len(self.engine.promotion_history()), 2)


# ══════════════════════════════════════════════════════════════════════════════
# 5. sources_needing_promotion()
# ══════════════════════════════════════════════════════════════════════════════

class TestSourcesNeedingPromotion(unittest.TestCase):

    def setUp(self):
        self.engine, _ = _make_engine_with_tmpdir()

    def test_contains_source_needed_sources(self):
        needing = self.engine.sources_needing_promotion()
        self.assertIn("btc_usd_conc_liq", needing)

    def test_contains_rs001_sources(self):
        needing = self.engine.sources_needing_promotion()
        self.assertIn("gmx_btc", needing)
        self.assertIn("gmx_eth", needing)

    def test_contains_rs002_sources(self):
        needing = self.engine.sources_needing_promotion()
        self.assertIn("rwa_conc_liq", needing)
        self.assertIn("trader_losses_vault", needing)

    def test_does_not_contain_clean_included(self):
        needing = self.engine.sources_needing_promotion()
        # aave_v3_usdc is CLEAN_INCLUDED
        self.assertNotIn("aave_v3_usdc", needing)

    def test_does_not_contain_research_only(self):
        needing = self.engine.sources_needing_promotion()
        # delta_neutral is RESEARCH_ONLY
        self.assertNotIn("delta_neutral", needing)

    def test_returns_list(self):
        self.assertIsInstance(self.engine.sources_needing_promotion(), list)

    def test_pending_sources_included(self):
        """PENDING sources also appear in sources_needing_promotion."""
        needing = self.engine.sources_needing_promotion()
        # morpho_steakhouse, yearn_v3_yvusdc, euler_v2_usdc are PENDING
        self.assertIn("morpho_steakhouse", needing)


# ══════════════════════════════════════════════════════════════════════════════
# 6. promotion_roadmap()
# ══════════════════════════════════════════════════════════════════════════════

class TestPromotionRoadmap(unittest.TestCase):

    def setUp(self):
        self.engine, _ = _make_engine_with_tmpdir()

    def test_roadmap_has_rs001_needs(self):
        roadmap = self.engine.promotion_roadmap()
        self.assertIn("rs001_needs", roadmap)

    def test_roadmap_has_rs002_needs(self):
        roadmap = self.engine.promotion_roadmap()
        self.assertIn("rs002_needs", roadmap)

    def test_roadmap_has_total_pending(self):
        roadmap = self.engine.promotion_roadmap()
        self.assertIn("total_pending", roadmap)
        self.assertIsInstance(roadmap["total_pending"], int)
        self.assertGreater(roadmap["total_pending"], 0)

    def test_roadmap_has_next_action(self):
        roadmap = self.engine.promotion_roadmap()
        self.assertIn("next_action", roadmap)
        self.assertIsInstance(roadmap["next_action"], str)
        self.assertGreater(len(roadmap["next_action"]), 0)

    def test_roadmap_rs001_needs_contains_gmx(self):
        roadmap = self.engine.promotion_roadmap()
        self.assertTrue(
            any("gmx" in s for s in roadmap["rs001_needs"]),
            msg=f"No gmx source in rs001_needs: {roadmap['rs001_needs']}"
        )

    def test_roadmap_rs002_needs_contains_btc_usd_conc_liq(self):
        roadmap = self.engine.promotion_roadmap()
        self.assertIn("btc_usd_conc_liq", roadmap["rs002_needs"])

    def test_roadmap_total_pending_equals_len_sources_needing(self):
        roadmap = self.engine.promotion_roadmap()
        needing = self.engine.sources_needing_promotion()
        self.assertEqual(roadmap["total_pending"], len(needing))


# ══════════════════════════════════════════════════════════════════════════════
# 7. PromotionEvidence serialization
# ══════════════════════════════════════════════════════════════════════════════

class TestPromotionEvidence(unittest.TestCase):

    def test_to_dict_returns_dict(self):
        ev = _make_evidence()
        d = ev.to_dict()
        self.assertIsInstance(d, dict)

    def test_to_dict_has_all_fields(self):
        ev = _make_evidence()
        d = ev.to_dict()
        for field in (
            "source_id", "from_state", "to_state", "promoted_by",
            "evidence_url", "data_period_start", "data_period_end",
            "notes", "promoted_at",
        ):
            self.assertIn(field, d)

    def test_from_dict_roundtrip(self):
        ev = _make_evidence()
        d = ev.to_dict()
        ev2 = PromotionEvidence.from_dict(d)
        self.assertEqual(ev.source_id, ev2.source_id)
        self.assertEqual(ev.from_state, ev2.from_state)
        self.assertEqual(ev.to_state, ev2.to_state)
        self.assertEqual(ev.promoted_by, ev2.promoted_by)
        self.assertEqual(ev.evidence_url, ev2.evidence_url)
        self.assertEqual(ev.notes, ev2.notes)

    def test_promoted_at_auto_set(self):
        ev = PromotionEvidence(
            source_id="x", from_state="source_needed", to_state="pending",
            promoted_by="yurii", evidence_url="", data_period_start="",
            data_period_end="",
        )
        self.assertNotEqual(ev.promoted_at, "")
        self.assertIn("T", ev.promoted_at)  # ISO format has "T"

    def test_notes_defaults_to_empty_string(self):
        ev = PromotionEvidence(
            source_id="x", from_state="source_needed", to_state="pending",
            promoted_by="yurii", evidence_url="", data_period_start="",
            data_period_end="",
        )
        self.assertEqual(ev.notes, "")


# ══════════════════════════════════════════════════════════════════════════════
# 8. Atomic log write
# ══════════════════════════════════════════════════════════════════════════════

class TestAtomicLogWrite(unittest.TestCase):

    def test_log_file_is_valid_json_after_promote(self):
        engine, tmpdir = _make_engine_with_tmpdir()
        ev = _make_evidence()
        engine.promote(ev)
        log_path = tmpdir / "source_promotion_log.json"
        self.assertTrue(log_path.exists())
        with open(log_path) as f:
            data = json.load(f)
        self.assertIn("entries", data)
        self.assertEqual(len(data["entries"]), 1)

    def test_log_no_tmp_files_left(self):
        """No stale .tmp files should remain after atomic write."""
        engine, tmpdir = _make_engine_with_tmpdir()
        ev = _make_evidence()
        engine.promote(ev)
        tmp_files = list(tmpdir.glob(".source_promotion_log_tmp_*.json"))
        self.assertEqual(len(tmp_files), 0)


if __name__ == "__main__":
    unittest.main()
