"""spa_core/tests/test_owner_blockers.py — Q1-9 owner-only go-live blocker tracker.

Covers spa_core/execution/owner_blockers.py — the deterministic procurement tracker for
the FOUR gates the code cannot satisfy (custody / audit / legal / track_days).

PURE / no network / deterministic / fail-CLOSED. Exercised against a hermetic temp data
dir with injected golive_status.json + owner_blockers_evidence.json. Proves:

  • the 4 canonical gates are always present,
  • track_days is auto-derived HONESTLY from golive (in_progress <30, satisfied >=30),
  • audit/legal are owner-asserted only — no evidence ⇒ open; the code NEVER fabricates
    'satisfied' for them,
  • an owner CANNOT sign past the track gate (track_days ignores owner overrides),
  • a bogus/garbage status in the evidence file fails CLOSED to 'open',
  • the report is deterministic (same inputs → identical gates modulo generated_at).
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

from spa_core.execution import owner_blockers as ob


def _seed(tmp: Path, evidenced_days, evidence: dict | None = None) -> None:
    (tmp / "golive_status.json").write_text(
        json.dumps({"real_track_days": evidenced_days, "min_track_days": 30}),
        encoding="utf-8",
    )
    if evidence is not None:
        (tmp / "owner_blockers_evidence.json").write_text(
            json.dumps(evidence), encoding="utf-8"
        )


def _gate(report: dict, gid: str) -> dict:
    return next(g for g in report["gates"] if g["id"] == gid)


def test_four_canonical_gates_present(tmp_path):
    _seed(tmp_path, 20)
    r = ob.build(tmp_path)
    ids = {g["id"] for g in r["gates"]}
    assert ids == {"custody", "audit", "legal", "track_days"}
    assert r["total"] == 4


def test_track_days_auto_in_progress(tmp_path):
    _seed(tmp_path, 20)
    r = ob.build(tmp_path)
    td = _gate(r, "track_days")
    assert td["status"] == "in_progress"
    assert td["evidenced_days"] == 20
    assert td["days_remaining"] == 10
    assert td["source"].startswith("auto:")


def test_track_days_auto_satisfied_at_30(tmp_path):
    _seed(tmp_path, 30)
    r = ob.build(tmp_path)
    td = _gate(r, "track_days")
    assert td["status"] == "satisfied"
    assert td["days_remaining"] == 0


def test_audit_legal_open_without_evidence(tmp_path):
    _seed(tmp_path, 20)
    r = ob.build(tmp_path)
    assert _gate(r, "audit")["status"] == "open"
    assert _gate(r, "legal")["status"] == "open"


def test_owner_can_assert_audit_satisfied(tmp_path):
    _seed(tmp_path, 20, {"audit": {"status": "satisfied", "note": "Firm X signed 2026-07",
                                    "evidence_url": "https://x/report"}})
    r = ob.build(tmp_path)
    a = _gate(r, "audit")
    assert a["status"] == "satisfied"
    assert a["note"] == "Firm X signed 2026-07"
    assert a["evidence_url"] == "https://x/report"


def test_owner_cannot_sign_past_track_gate(tmp_path):
    # Owner asserts satisfied on track_days — code must IGNORE it (time-only gate).
    _seed(tmp_path, 20, {"track_days": {"status": "satisfied"}})
    r = ob.build(tmp_path)
    assert _gate(r, "track_days")["status"] == "in_progress"


def test_garbage_status_fails_closed_to_open(tmp_path):
    _seed(tmp_path, 20, {"audit": {"status": "totally_done_trust_me"}})
    r = ob.build(tmp_path)
    assert _gate(r, "audit")["status"] == "open"


def test_deterministic(tmp_path):
    _seed(tmp_path, 25, {"legal": {"status": "in_progress"}})
    a = ob.build(tmp_path)
    b = ob.build(tmp_path)
    strip = lambda r: [{k: v for k, v in g.items()} for g in r["gates"]]
    assert strip(a) == strip(b)


def test_missing_golive_fails_closed(tmp_path):
    # No golive_status.json at all — track_days must not crash; reports open honestly.
    r = ob.build(tmp_path)
    td = _gate(r, "track_days")
    assert td["status"] == "open"
    assert r["all_satisfied"] is False
