"""Studio OS Core (ADR-495) — registry, Context Pack, decision seam, search, handoff, + the CONTINUITY
gate: a fresh worker given ONLY the Context Pack must be able to answer the 8 project questions.

Hermetic: decision/handoff tests use tmp dirs and never touch canon.
"""
import pytest

from spa_core.studio_os import context, registry, research, search
from spa_core.studio_os import decisions as D
from spa_core.studio_os import handoff as H


def test_registry_valid_and_has_three_projects():
    assert registry.validate() == []
    ids = registry.project_ids()
    assert {"studio-os", "earn-defi-product", "investment-engine"} <= set(ids)
    inv = registry.get_project("investment-engine")
    # boundary preserved: engine owns financial truth, studio-os does not copy it
    assert "financial truth" in inv["boundary"].lower()


# ── CONTINUITY GATE — the 8 questions a fresh worker must answer from the Context Pack alone ──
def test_fresh_session_continuity():
    p = context.build_context_pack("earn-defi-product")

    def has(section):
        v = p.get(section, {}).get("value")
        assert v not in (None, "", [], {}), f"context pack cannot answer: {section}"
        assert p[section].get("provenance"), f"{section} has no provenance"
        return v

    has("purpose")                 # 1. what are we building
    has("work")                    # 2. what is implemented / in flight
    has("boundaries")              # 3. architecture boundaries
    nxt = has("next_recommended_work")   # 4/8. highest-priority + next worker
    has("accepted_decisions")      # 5. important decisions
    dnr = has("do_not_redesign")   # 6. what NOT to redesign
    has("last_handoff")            # 7. last completed work (structured or newest journal)
    # boundaries must name the financial-truth ownership; do-not-redesign must protect RiskPolicy + shell
    assert "financial truth" in p["boundaries"]["value"].lower()
    assert any("RiskPolicy" in x for x in dnr)
    assert isinstance(nxt, str) and nxt


def test_decision_seam_proposed_then_owner_accepts(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "DECISIONS", tmp_path / "decisions")
    monkeypatch.setattr(D, "DRAFTS", tmp_path / "decisions" / "drafts")
    r = D.propose_decision(project_id="studio-os", problem="test problem",
                           decision="test decision", now_iso="2026-09-28T00:00:00Z")
    assert r["status"] == "PROPOSED" and r["draft_id"].startswith("DRAFT-")
    # accept REFUSES without owner confirmation
    assert D.accept_decision(r["draft_id"])["ok"] is False
    acc = D.accept_decision(r["draft_id"], owner_confirmed=True, now_iso="2026-09-28T00:00:00Z")
    assert acc["ok"] and acc["status"] == "ACCEPTED" and acc["adr_id"].startswith("ADR-")
    # the draft is consumed and a numbered ADR exists with ACCEPTED status
    assert not (D.DRAFTS / f"{r['draft_id']}.md").exists()
    body = (tmp_path / "decisions" / f"{acc['adr_id']}-{r['draft_id'].replace('DRAFT-', '')}.md").read_text()
    assert "ACCEPTED" in body and "test decision" in body


def test_search_finds_cross_object_history():
    idx = search.build_index()
    assert len(idx) > 50
    # a concept introduced this project must be recoverable
    assert search.search("Position Passport", index=idx), "search cannot recover Position Passport"
    # a core decision must resolve to a decision object
    kill = search.search("kill switch", index=idx)
    assert any(r["type"] == "decision" for r in kill)
    # the canonical-repo ADR is findable
    assert any("494" in r["id"] for r in search.search("canonical repository", index=idx))


def test_decision_lifecycle_owner_gated(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "DECISIONS", tmp_path / "decisions")
    monkeypatch.setattr(D, "DRAFTS", tmp_path / "decisions" / "drafts")
    r = D.propose_decision(project_id="studio-os", problem="p", decision="d", now_iso="2026-09-28T00:00:00Z")
    D.mark_owner_review(r["draft_id"])
    assert D.list_drafts()[0]["status"] == "OWNER_REVIEW"
    # reject requires owner confirmation
    assert D.reject_decision(r["draft_id"])["ok"] is False
    rej = D.reject_decision(r["draft_id"], reason="not now", owner_confirmed=True, now_iso="2026-09-28T00:00:00Z")
    assert rej["ok"] and rej["status"] == "REJECTED"
    assert "PROPOSED" in D.STATUSES and "SUPERSEDED" in D.STATUSES and "REJECTED" in D.STATUSES


def test_task_link_overlay_travels(tmp_path, monkeypatch):
    """A task can travel Idea/Research→Decision→Task→Commit→Handoff→Result via the link OVERLAY —
    keyed by the EXISTING task id, not a second task model. Never a guessed relationship."""
    from spa_core.studio_os import links as LK
    monkeypatch.setattr(LK, "LINKS_DIR", tmp_path / "task_links")
    monkeypatch.setattr(LK, "LEGACY_JSON", tmp_path / "none.json")
    r = LK.record_link("inbox-check-morpho", origin="EXPLICIT", project_id="earn-defi-product",
                       source="telegram_text", decision_refs=["ADR-495"], research_refs=["12_gnosis_safe_guide"],
                       implementation_commit="ea9bb538", handoff_ref="data/studio_handoffs.jsonl", outcome="done")
    assert r["ok"]
    lk = LK.get_link("inbox-check-morpho")
    assert lk["project_id"] == "earn-defi-product"
    assert lk["decision_refs"] == ["ADR-495"] and lk["research_refs"] == ["12_gnosis_safe_guide"]
    assert lk["implementation_commit"] == "ea9bb538" and lk["outcome"] == "done"
    # only known FIELDS (+ the _origins/provenance overlay meta) are stored — no lifecycle/state
    assert set(lk) <= set(LK.FIELDS) | {"_origins", "provenance"}
    # fuzzy lookup by a work-item id that contains the card stem still resolves
    assert LK.get_link("wi-x-inbox-check-morpho-y")["project_id"] == "earn-defi-product"


def test_research_orphans_are_classified_not_guessed():
    m = research.build_research_model()
    classes = {i["orphan_class"] for i in m["items"] if i["status"] == "ORPHAN"}
    # heuristic-honest labels (ADR-497): LIKELY_* not asserted-fact; only in-text markers are DERIVED
    assert classes <= {"LIKELY_STANDALONE", "LIKELY_MISSING_LINK", "OBSOLETE", "UNKNOWN"}
    for i in m["items"]:
        if i["status"] == "ORPHAN":
            assert i["orphan_reason"] and i["orphan_confidence"] in ("HEURISTIC", "DERIVED", "UNKNOWN"), i["id"]
    assert "orphan_breakdown" in m


def test_linkage_never_swallows_failure(tmp_path, monkeypatch):
    """Canonical relationship persistence surfaces LINKAGE_WRITE_FAILED, never silent `except: pass`."""
    from spa_core.studio_os import links as LK
    # point the registry at a path whose parent cannot be created (a file, not a dir) → write fails
    bad = tmp_path / "afile"
    bad.write_text("x")
    monkeypatch.setattr(LK, "LINKS_DIR", bad / "sub")
    r = LK.record_link("t1", origin="EXPLICIT", project_id="studio-os")
    assert r["ok"] is False and r["error"] == "LINKAGE_WRITE_FAILED"


def test_linkage_origin_is_typed(tmp_path, monkeypatch):
    from spa_core.studio_os import links as LK
    monkeypatch.setattr(LK, "LINKS_DIR", tmp_path / "task_links")
    LK.record_link("wi-1", origin="EXPLICIT", project_id="earn-defi-product", decision_refs=["ADR-495"])
    lk = LK.get_link("wi-1")
    assert lk["_origins"]["project_id"] == "EXPLICIT" and lk["decision_refs"] == ["ADR-495"]


def test_repo_status_reports_three_trees():
    from spa_core.studio_os.repo_status import status
    s = status()
    assert s["candidate"]["sha"], "candidate SHA missing"
    assert s["candidate"]["state_vs_canonical"] in ("IN_SYNC", "AHEAD", "BEHIND", "DIVERGED", "UNKNOWN")
    assert "promotion_path" in s and "ADR-494" in s["policy"]


def test_handoff_roundtrip(tmp_path, monkeypatch):
    # per-session files (ADR-497) — no shared append file → no parallel-branch merge hotspot
    monkeypatch.setattr(H, "HANDOFF_DIR", tmp_path / "handoffs")
    monkeypatch.setattr(H, "LEGACY_LEDGER", tmp_path / "none.jsonl")
    r = H.write_handoff("studio-os", now_iso="2026-09-28T00:00:00Z", requested="x", done="y",
                        next_action="z", owner_action=None)
    assert r["ok"] and (tmp_path / "handoffs").is_dir()
    last = H.last_handoff("studio-os")
    assert last["done"] == "y" and last["next_action"] == "z"
    # outcomes only — no chain-of-thought field is stored
    assert set(last) <= {"project_id", "ts", *H.FIELDS}
    # two sessions → two DIFFERENT files (concurrency-safe), not one appended file
    H.write_handoff("studio-os", now_iso="2026-09-28T01:00:00Z", done="second")
    assert len(list((tmp_path / "handoffs").glob("*.json"))) == 2


if __name__ == "__main__":
    import sys
    sys.exit(pytest.main([__file__, "-q"]))
