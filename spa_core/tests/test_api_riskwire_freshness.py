"""
test_api_riskwire_freshness.py — /api/riskwire/proof must separate INTEGRITY from CURRENCY.

Why this exists (real incident, 2026-07-29): data/riskwire/measurements.json had not been rewritten
since 2026-07-01 (693h) because nothing schedules spa_core.riskwire.facade.build_and_write — yet the
public "check us" index answered `all_verified: true` with no freshness verdict at all. A verified
hash chain over a 29-day-old snapshot is honest about integrity and silent about age; an outsider
reading only `verified` would take an old measurement for today's risk.

Contract asserted here:
  * `verified` (chain re-derives) and `stale` (older than budget) are INDEPENDENT — a fresh artifact
    can be tampered, a pristine artifact can be ancient, and the index must say both.
  * the staleness budget is the SAME constant `d_riskwire.*` grades with (system_health_monitor) —
    the public surface and the internal health report may never disagree about the same file.
  * fail-CLOSED: missing artifact / absent / unparseable `generated_at` ⇒ stale:true (never a
    fabricated "current").

Hermetic: every artifact is written into tmp_path and `generated_at` is stamped RELATIVE to now, so
the assertions hold at any wall-clock time without freezing the clock. No live data/, no network.

    python3 -m pytest spa_core/tests/test_api_riskwire_freshness.py -q
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from spa_core.api import server
from spa_core.api.routers import riskwire as rw_router
from spa_core.monitoring.system_health_monitor import (
    RISKWIRE_DAY30_FRESH_D,
    RISKWIRE_MEASUREMENTS_FRESH_H,
)
from spa_core.riskwire import (RISKWIRE_CLASS_LABELS, RiskWireClass, RiskWireMeasurement,
                               RiskWireRefusal, SubjectKind)
from spa_core.riskwire import proof


def _ago(hours: float) -> str:
    """ISO timestamp `hours` in the past — relative so the test never depends on today's date."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _mk(sid, cls, seed_hash):
    return RiskWireMeasurement(
        subject_id=sid, kind=SubjectKind.POOL, display_name=sid.split("::")[-1], risk_class=cls,
        risk_class_label=RISKWIRE_CLASS_LABELS[cls], native_verdict=cls.value,
        refusal=RiskWireRefusal("SAFE", "clean", False), exit_liquidity_by_size=[],
        liquidation_nav=None, structural_haircut=None, total_haircut=None, seed="dfb",
        seed_proof_hash=seed_hash, as_of="2026-06-30", flagged=False, flag_reason=None,
        provenance="dfb:seed", prev_hash="")


def _write_measurements(tmp_path, generated_at: str) -> None:
    proof.write_measurements([_mk("pool::a", RiskWireClass.A, "a" * 64),
                              _mk("pool::b", RiskWireClass.D, "b" * 64)],
                             generated_at=generated_at, as_of="2026-06-30", data_dir=tmp_path)


def _write_day30(tmp_path, generated_at: str) -> None:
    rw = tmp_path / "riskwire"
    rw.mkdir(parents=True, exist_ok=True)
    review = {
        "schema": "day30-review-v1", "generated_at": generated_at,
        "state": "TRACK_MATURING", "ready_for_review": False,
        "day30_artifact": {"schema": "day30-v1", "generated_at": generated_at,
                           "proof_hash": "e" * 64},
    }
    review["review_hash"] = proof.compute_review_hash(review)
    (rw / "day30_review.json").write_text(json.dumps(review, indent=1))


def _index(tmp_path, monkeypatch) -> dict:
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        r = c.get("/api/riskwire/proof")
        assert r.status_code == 200
        return r.json()


# ── 1. fresh artifacts read fresh ──────────────────────────────────────────────────────────────────
def test_fresh_artifacts_not_stale(tmp_path, monkeypatch):
    _write_measurements(tmp_path, _ago(1))
    _write_day30(tmp_path, _ago(1))
    body = _index(tmp_path, monkeypatch)

    assert body["all_verified"] is True
    assert body["any_stale"] is False
    for name in ("measurements", "day30_review"):
        art = body["artifacts"][name]
        assert art["stale"] is False, name
        assert 0.0 <= art["age_hours"] <= 2.0, name


# ── 2. THE REGRESSION: verified but ancient must not read as current ───────────────────────────────
def test_verified_but_ancient_measurements_reported_stale(tmp_path, monkeypatch):
    """The 2026-07-29 shape exactly: an untampered, perfectly-verifying 693h-old snapshot."""
    _write_measurements(tmp_path, _ago(693))
    _write_day30(tmp_path, _ago(1))
    body = _index(tmp_path, monkeypatch)

    m = body["artifacts"]["measurements"]
    assert m["verified"] is True          # integrity is genuinely intact — we do NOT fake a failure
    assert m["stale"] is True             # ...and currency is separately, honestly refused
    assert m["age_hours"] == pytest.approx(693.0, abs=1.0)
    assert body["all_verified"] is True   # the integrity verdict is NOT contaminated by age
    assert body["any_stale"] is True      # ...but the index refuses to look clean


def test_day30_uses_its_own_wider_budget(tmp_path, monkeypatch):
    """day30_review is a weekly-ish artifact: an age that is STALE for measurements is FRESH for it —
    the two budgets must not be collapsed into one."""
    age = RISKWIRE_MEASUREMENTS_FRESH_H + 10.0     # 40h: past measurements' 30h, inside day30's 192h
    assert age < RISKWIRE_DAY30_FRESH_D * 24.0
    _write_measurements(tmp_path, _ago(age))
    _write_day30(tmp_path, _ago(age))
    body = _index(tmp_path, monkeypatch)

    assert body["artifacts"]["measurements"]["stale"] is True
    assert body["artifacts"]["day30_review"]["stale"] is False
    assert body["any_stale"] is True


# ── 3. the budget is the health monitor's, not a private copy ──────────────────────────────────────
def test_budget_is_the_health_monitor_constant(tmp_path, monkeypatch):
    body_budgets = {
        "measurements": RISKWIRE_MEASUREMENTS_FRESH_H,
        "day30_review": RISKWIRE_DAY30_FRESH_D * 24.0,
    }
    _write_measurements(tmp_path, _ago(1))
    _write_day30(tmp_path, _ago(1))
    body = _index(tmp_path, monkeypatch)
    for name, expected in body_budgets.items():
        assert body["artifacts"][name]["fresh_within_hours"] == expected, name


def test_budget_change_moves_the_public_verdict(tmp_path, monkeypatch):
    """No forked threshold: retune the monitor's constant and this surface follows in the same run."""
    _write_measurements(tmp_path, _ago(5))
    _write_day30(tmp_path, _ago(5))
    assert _index(tmp_path, monkeypatch)["artifacts"]["measurements"]["stale"] is False

    monkeypatch.setattr(
        "spa_core.monitoring.system_health_monitor.RISKWIRE_MEASUREMENTS_FRESH_H", 1.0)
    body = _index(tmp_path, monkeypatch)
    assert body["artifacts"]["measurements"]["stale"] is True
    assert body["artifacts"]["measurements"]["fresh_within_hours"] == 1.0


# ── 4. fail-CLOSED on every way currency can be unprovable ─────────────────────────────────────────
def test_missing_artifact_is_stale_not_silent(tmp_path, monkeypatch):
    body = _index(tmp_path, monkeypatch)          # empty data dir
    for name in ("measurements", "day30_review"):
        art = body["artifacts"][name]
        assert art["present"] is False
        assert art["stale"] is True               # absent cannot be current
        assert art["age_hours"] is None
    assert body["any_stale"] is True
    assert body["all_verified"] is False


@pytest.mark.parametrize("bad_ts", [None, "", "not-a-timestamp", 12345])
def test_unparseable_generated_at_is_stale(tmp_path, monkeypatch, bad_ts):
    """An artifact whose timestamp we cannot read is NOT assumed fresh (that would be the fabricated
    pass this whole surface exists to prevent)."""
    _write_measurements(tmp_path, _ago(1))
    _write_day30(tmp_path, _ago(1))
    p = tmp_path / "riskwire" / "measurements.json"
    doc = json.loads(p.read_text())
    if bad_ts is None:
        doc.pop("generated_at", None)
    else:
        doc["generated_at"] = bad_ts
    p.write_text(json.dumps(doc, indent=1))

    m = _index(tmp_path, monkeypatch)["artifacts"]["measurements"]
    assert m["stale"] is True
    assert m["age_hours"] is None


def test_fresh_but_tampered_is_verified_false_and_stale_false(tmp_path, monkeypatch):
    """The other diagonal: age and integrity are independent axes, so a FRESH forgery still fails
    `verified` and must not be excused by its freshness."""
    _write_measurements(tmp_path, _ago(1))
    _write_day30(tmp_path, _ago(1))
    p = tmp_path / "riskwire" / "measurements.json"
    doc = json.loads(p.read_text())
    doc["measurements"][1]["risk_class"] = "A"     # forge toxic → safe, no re-hash
    p.write_text(json.dumps(doc, indent=1))

    body = _index(tmp_path, monkeypatch)
    m = body["artifacts"]["measurements"]
    assert m["verified"] is False
    assert m["stale"] is False
    assert body["all_verified"] is False
    assert body["any_stale"] is False


# ── 5. the disclaimer says it in words, not only in flags ──────────────────────────────────────────
def test_disclaimer_separates_verified_from_current(tmp_path, monkeypatch):
    _write_measurements(tmp_path, _ago(1))
    _write_day30(tmp_path, _ago(1))
    text = _index(tmp_path, monkeypatch)["disclaimer"]
    assert "CURRENT" in text and "stale" in text


# ── 6. read-only: the surface never rewrites the artifacts it grades ───────────────────────────────
def test_index_writes_nothing(tmp_path, monkeypatch):
    _write_measurements(tmp_path, _ago(693))
    _write_day30(tmp_path, _ago(693))
    before = {p.name: p.read_bytes() for p in (tmp_path / "riskwire").glob("*.json")}
    _index(tmp_path, monkeypatch)
    after = {p.name: p.read_bytes() for p in (tmp_path / "riskwire").glob("*.json")}
    assert before == after, "the proof surface must never re-mint the artifact it reports on"


def test_helper_is_pure_on_arbitrary_docs():
    """_freshness never raises on a hostile wrapper (the router must not 500 on a corrupt file)."""
    for doc in ({}, {"generated_at": None}, {"generated_at": []}, {"generated_at": "2026-13-45"}):
        out = rw_router._freshness("measurements", doc)
        assert out["stale"] is True and out["age_hours"] is None
