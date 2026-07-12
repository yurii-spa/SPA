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


def test_readiness_owner_blockers_rich_tracker():
    # Q1-9: the richer per-gate procurement tracker (status open/in_progress/satisfied)
    # must be served alongside the flat list, with the 4 canonical gates each carrying a
    # valid status. Guards against a regression that drops the field back to the flat list.
    d = R.readiness()
    assert "owner_blockers" in d, "richer owner_blockers tracker must be served"
    ob = d["owner_blockers"]
    gates = ob["gates"]
    ids = {g["id"] for g in gates}
    assert {"custody", "audit", "legal", "track_days"} <= ids
    for g in gates:
        assert g["status"] in ("open", "in_progress", "satisfied"), g
    # open_count / total are consistent with the gate list (fallback sets them too)
    assert ob["total"] == len(gates)
    # track_days is the one gate the code auto-derives; it must never be fabricated 'satisfied'
    # without ≥30 evidenced days — with the live artifact it is open or in_progress pre-go-live.
    td = next(g for g in gates if g["id"] == "track_days")
    assert td["status"] in ("open", "in_progress", "satisfied")


def test_readiness_fails_closed_when_artifacts_absent(monkeypatch, tmp_path):
    # Point the loader at an empty dir → every artifact is absent → honest nulls,
    # never a fabricated pass.
    monkeypatch.setattr(R, "_DATA", tmp_path)
    d = R.readiness()
    assert d["governance_defenses"]["fired"] is None
    assert d["go_live_gate"]["passed"] is None
    # the owner-only blockers + reproduce commands are still surfaced honestly
    assert len(d["owner_only_blockers"]) >= 4
    # Q1-9: with data/owner_blockers.json absent the richer tracker falls back to the
    # static 4-gate catalogue (never a 500, never fabricated progress).
    ob = d["owner_blockers"]
    assert ob["total"] == len(ob["gates"]) >= 4
    assert {"custody", "audit", "legal", "track_days"} <= {g["id"] for g in ob["gates"]}


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
