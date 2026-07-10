"""Q2-3 + Q2-9 hardening: pin the readiness surface + the campaign-attribution
analytics endpoints so the money-path-adjacent honest surfaces don't silently
regress. Direct-call unit tests (no ASGI lifespan) — fast + side-effect-free
(analytics writes are redirected to a temp log)."""
from spa_core.api.routers import readiness as R
from spa_core.api.routers import analytics as A


def test_readiness_shape_and_owner_blockers():
    d = R.readiness()
    assert {"governance_defenses", "go_live_gate", "owner_only_blockers", "reproduce", "honest"} <= set(d)
    # governance defenses come from the reproducible artifact (11/11 when fresh)
    assert "fired" in d["governance_defenses"] and "total" in d["governance_defenses"]
    # the honest owner-only blockers are always present (custody/audit/legal/track)
    ids = {b["id"] for b in d["owner_only_blockers"]}
    assert {"custody", "audit", "legal", "track_days"} <= ids
    assert d["reproduce"]["proof_chain"].startswith("python3 scripts/verify_spa.py")
    assert "capital" in d["honest"].lower() or "owner-only" in d["honest"].lower()


def test_readiness_fails_closed_when_artifacts_absent(monkeypatch, tmp_path):
    # Point the loader at an empty dir → every artifact is absent → honest nulls,
    # never a fabricated pass.
    monkeypatch.setattr(R, "_DATA", tmp_path)
    d = R.readiness()
    assert d["governance_defenses"]["fired"] is None
    assert d["go_live_gate"]["passed"] is None
    # the owner-only blockers + reproduce commands are still surfaced honestly
    assert len(d["owner_only_blockers"]) >= 4


def test_analytics_records_utm_campaign(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "_LOG", tmp_path / "analytics.jsonl")
    A.record_event(A.Event(page="/packages", event="view", utm_source="defi-checkup", utm_campaign="depeg"))
    s = A.summary()
    assert "top_campaigns" in s
    assert any(c["campaign"] == "defi-checkup:depeg" and c["hits"] >= 1 for c in s["top_campaigns"])


def test_analytics_without_utm_has_no_campaign(monkeypatch, tmp_path):
    monkeypatch.setattr(A, "_LOG", tmp_path / "a2.jsonl")
    A.record_event(A.Event(page="/", event="view"))
    s = A.summary()
    assert s["top_campaigns"] == []
