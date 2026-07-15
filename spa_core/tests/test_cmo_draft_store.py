"""Tests for spa_core/cmo/draft_store.py and spa_core/cmo/pipeline.py."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from spa_core.cmo.draft_store import DraftStore, Draft
from spa_core.cmo.honesty_gate import GateResult
from spa_core.cmo.pipeline import run_pipeline
from spa_core.cmo.template_rewriter import rewrite


# ── fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture
def tmp_store(tmp_path):
    return DraftStore(drafts_dir=tmp_path / "drafts")


FACTS = {
    "n_evidenced_days": 22,
    "days_needed": 30,
    "cumulative_return_pct": 4.2,
    "max_drawdown_from_peak_pct": -1.8,
    "paper_apy_pct": 12.5,
    "nav_usd": 101200.0,
    "refusal_count": 7,
    "decision_count": 15,
}

DATE = "2026-07-15"


# ── DraftStore ─────────────────────────────────────────────────────────────────

class TestDraftStore:
    def test_save_returns_id(self, tmp_store):
        gate = GateResult(passed=True)
        did = tmp_store.save_draft(FACTS, "draft text", "fallback", gate, "template_v1", DATE)
        assert did.startswith("cmo_20260715_")

    def test_get_returns_draft(self, tmp_store):
        gate = GateResult(passed=True)
        did = tmp_store.save_draft(FACTS, "draft text", "fallback", gate, "template_v1", DATE)
        d = tmp_store.get_draft(did)
        assert isinstance(d, Draft)
        assert d.id == did
        assert d.status == "draft"

    def test_get_missing_returns_none(self, tmp_store):
        assert tmp_store.get_draft("nonexistent_id") is None

    def test_list_empty(self, tmp_store):
        assert tmp_store.list_drafts() == []

    def test_list_returns_all(self, tmp_store):
        gate = GateResult(passed=True)
        tmp_store.save_draft(FACTS, "t1", "f1", gate, "template_v1", "2026-07-14")
        tmp_store.save_draft(FACTS, "t2", "f2", gate, "template_v1", "2026-07-15")
        assert len(tmp_store.list_drafts()) == 2

    def test_list_filter_by_status(self, tmp_store):
        gate = GateResult(passed=True)
        did1 = tmp_store.save_draft(FACTS, "t1", "f1", gate, "template_v1", "2026-07-14")
        did2 = tmp_store.save_draft(FACTS, "t2", "f2", gate, "template_v1", "2026-07-15")
        tmp_store.approve(did1)
        pending = tmp_store.list_drafts(status="draft")
        assert len(pending) == 1
        assert pending[0].id == did2

    def test_id_increments_same_date(self, tmp_store):
        gate = GateResult(passed=True)
        id0 = tmp_store.save_draft(FACTS, "t1", "f1", gate, "template_v1", DATE)
        id1 = tmp_store.save_draft(FACTS, "t2", "f2", gate, "template_v1", DATE)
        assert id0.endswith("_000")
        assert id1.endswith("_001")

    def test_approve_changes_status(self, tmp_store):
        gate = GateResult(passed=True)
        did = tmp_store.save_draft(FACTS, "text", "fallback", gate, "template_v1", DATE)
        d = tmp_store.approve(did)
        assert d.status == "approved"
        assert d.approved_at is not None

    def test_approve_missing_raises(self, tmp_store):
        with pytest.raises(ValueError, match="not found"):
            tmp_store.approve("ghost_id")

    def test_approve_published_raises(self, tmp_store):
        gate = GateResult(passed=True)
        did = tmp_store.save_draft(FACTS, "text", "fallback", gate, "template_v1", DATE)
        tmp_store.approve(did)
        tmp_store.mark_published(did, published_to="/blog/test")
        with pytest.raises(ValueError, match="already published"):
            tmp_store.approve(did)

    def test_reject_changes_status(self, tmp_store):
        gate = GateResult(passed=True)
        did = tmp_store.save_draft(FACTS, "text", "fallback", gate, "template_v1", DATE)
        d = tmp_store.reject(did, reason="owner says no")
        assert d.status == "rejected"
        assert d.rejected_at is not None
        assert any("owner-rejected" in v for v in d.gate_violations)

    def test_reject_missing_raises(self, tmp_store):
        with pytest.raises(ValueError, match="not found"):
            tmp_store.reject("ghost_id")

    def test_mark_published_requires_approved(self, tmp_store):
        gate = GateResult(passed=True)
        did = tmp_store.save_draft(FACTS, "text", "fallback", gate, "template_v1", DATE)
        with pytest.raises(ValueError, match="must be approved"):
            tmp_store.mark_published(did, published_to="/blog/test")

    def test_mark_published_sets_fields(self, tmp_store):
        gate = GateResult(passed=True)
        did = tmp_store.save_draft(FACTS, "text", "fallback", gate, "template_v1", DATE)
        tmp_store.approve(did)
        d = tmp_store.mark_published(did, published_to="/blog/test-slug")
        assert d.status == "published"
        assert d.published_to == "/blog/test-slug"
        assert d.published_at is not None

    def test_write_is_atomic(self, tmp_store):
        """Verify no .tmp files linger after save."""
        gate = GateResult(passed=True)
        tmp_store.save_draft(FACTS, "text", "fallback", gate, "template_v1", DATE)
        tmp_files = list(tmp_store._dir.glob("*.tmp"))
        assert tmp_files == []

    def test_draft_persisted_as_valid_json(self, tmp_store):
        gate = GateResult(passed=True)
        did = tmp_store.save_draft(FACTS, "text", "fallback", gate, "template_v1", DATE)
        p = tmp_store._dir / f"{did}.json"
        data = json.loads(p.read_text())
        assert data["id"] == did
        assert data["status"] == "draft"


# ── template_rewriter ──────────────────────────────────────────────────────────

class TestTemplateRewriter:
    def test_rich_template_gate_passes(self):
        result = rewrite(FACTS, DATE)
        assert result["gate_passed"], result["gate_result"].violations

    def test_returns_all_keys(self):
        result = rewrite(FACTS, DATE)
        assert "gate_passed" in result
        assert "draft_text" in result
        assert "fallback_text" in result
        assert "gate_result" in result
        assert "rewrite_method" in result

    def test_rewrite_method_label(self):
        result = rewrite(FACTS, DATE)
        assert result["rewrite_method"] == "template_v1"

    def test_draft_contains_track_days(self):
        result = rewrite(FACTS, DATE)
        assert "22" in result["draft_text"]

    def test_draft_contains_cumulative_return(self):
        # Rich template uses cumulative_return_pct, not paper_apy_pct
        result = rewrite(FACTS, DATE)
        assert "4.2" in result["draft_text"]

    def test_draft_contains_disclaimer(self):
        draft = result = rewrite(FACTS, DATE)["draft_text"].lower()
        assert "not a guarantee" in draft or "not financial advice" in draft

    def test_fallback_always_gate_passes(self):
        result = rewrite({}, DATE)
        from spa_core.cmo.honesty_gate import check_draft
        gate = check_draft(result["fallback_text"], {})
        assert gate.passed, gate.violations

    def test_minimal_facts_no_crash(self):
        result = rewrite({}, DATE)
        assert isinstance(result["draft_text"], str)

    def test_refusal_only_template(self):
        facts = {"refusal_count": 5, "decision_count": 12}
        result = rewrite(facts, DATE)
        assert "5" in result["draft_text"]
        assert result["gate_passed"], result["gate_result"].violations


# ── pipeline ───────────────────────────────────────────────────────────────────

class TestPipeline:
    def test_run_pipeline_returns_dict(self, tmp_store):
        result = run_pipeline(FACTS, DATE, store=tmp_store)
        assert isinstance(result, dict)

    def test_run_pipeline_creates_draft(self, tmp_store):
        result = run_pipeline(FACTS, DATE, store=tmp_store)
        assert result["draft_id"].startswith("cmo_20260715_")
        assert result["status"] == "draft"

    def test_run_pipeline_gate_passed(self, tmp_store):
        result = run_pipeline(FACTS, DATE, store=tmp_store)
        assert result["gate_passed"]

    def test_run_pipeline_draft_stored(self, tmp_store):
        result = run_pipeline(FACTS, DATE, store=tmp_store)
        d = tmp_store.get_draft(result["draft_id"])
        assert d is not None
        assert d.gate_passed

    def test_run_pipeline_text_used_is_draft_when_passes(self, tmp_store):
        result = run_pipeline(FACTS, DATE, store=tmp_store)
        d = tmp_store.get_draft(result["draft_id"])
        assert result["text_used"] == d.draft_text

    def test_run_pipeline_empty_facts_falls_to_fallback(self, tmp_store):
        # Empty facts can still produce a passing fallback
        result = run_pipeline({}, DATE, store=tmp_store)
        assert result["status"] == "draft"

    def test_run_pipeline_idempotent_different_ids(self, tmp_store):
        r1 = run_pipeline(FACTS, DATE, store=tmp_store)
        r2 = run_pipeline(FACTS, DATE, store=tmp_store)
        assert r1["draft_id"] != r2["draft_id"]  # each run creates a new draft
