"""
test_d_riskwire_health.py — WS1.5 d_riskwire health domain (property + red-team + smoke).

The domain is fail-CLOSED: a missing / stale / invalid RISKWIRE snapshot → WARNING (never silent-OK),
and the no-fork check fires if RISKWIRE ever diverges from a seed. All checks read-only.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.monitoring.system_health_monitor import SystemHealthMonitor, OK, WARNING
from spa_core.riskwire import (
    ExitLiquidityBySize, RISKWIRE_CLASS_LABELS, RiskWireClass, RiskWireMeasurement,
    RiskWireRefusal, SubjectKind,
)
from spa_core.riskwire import proof


def _mk(sid, kind, cls, native, seed_hash, refusal=None, exits=()):
    return RiskWireMeasurement(
        subject_id=sid, kind=kind, display_name=sid.split("::")[-1], risk_class=cls,
        risk_class_label=RISKWIRE_CLASS_LABELS[cls], native_verdict=native, refusal=refusal,
        exit_liquidity_by_size=list(exits), liquidation_nav=None, structural_haircut=None,
        total_haircut=None, seed="dfb", seed_proof_hash=seed_hash, as_of="2026-06-30",
        flagged=False, flag_reason=None, provenance="dfb:seed", prev_hash="")


def _now_iso():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _write_day30(data_dir: Path, *, generated_at=None):
    """Write a WS1.3-shaped day-30 review (state + review_hash) to data_dir/riskwire/."""
    rw = data_dir / "riskwire"
    rw.mkdir(parents=True, exist_ok=True)
    review = {
        "schema": "day30-review-v1", "model": "day30_review", "llm_forbidden": True,
        "deterministic": True, "generated_at": generated_at or _now_iso(),
        "state": "TRACK_MATURING", "ready_for_review": False, "min_track_days": 30,
        "day30_artifact": {"schema": "day30-v1", "generated_at": _now_iso(), "proof_hash": "e" * 64},
    }
    review["review_hash"] = proof.compute_review_hash(review)
    (rw / "day30_review.json").write_text(json.dumps(review, indent=1))
    return review


def _write_clean(data_dir: Path, *, pool_class="A"):
    ms = [
        _mk("pool::aave_v3-usdc", SubjectKind.POOL, RiskWireClass(pool_class), pool_class, "a" * 64,
            refusal=RiskWireRefusal("SAFE", "clean", False)),
        _mk("pool::ezeth-pt", SubjectKind.POOL, RiskWireClass.D, "D", "b" * 64,
            refusal=RiskWireRefusal("REFUSE", "veto", True)),
    ]
    proof.write_measurements(ms, generated_at=_now_iso(), as_of="2026-06-30", data_dir=data_dir)
    _write_day30(data_dir)


def _run(data_dir: Path):
    m = SystemHealthMonitor(data_dir=str(data_dir))
    return {c.id: c for c in m.check_d_riskwire()}


# ── SMOKE: clean dataset → all four checks OK ─────────────────────────────────────────────────────
def test_d_riskwire_all_ok(tmp_path):
    _write_clean(tmp_path)
    r = _run(tmp_path)
    assert set(r) == {"d_riskwire.measurements.fresh", "d_riskwire.day30.fresh",
                      "d_riskwire.proof.valid", "d_riskwire.no_fork"}
    assert all(c.status == OK for c in r.values()), {k: v.status for k, v in r.items()}


# ── PROPERTY: fail-CLOSED on missing artifacts ────────────────────────────────────────────────────
def test_missing_measurements_is_warning_not_ok(tmp_path):
    # write only day30, no measurements
    _write_day30(tmp_path)
    r = _run(tmp_path)
    assert r["d_riskwire.measurements.fresh"].status == WARNING
    assert r["d_riskwire.proof.valid"].status == WARNING   # verify_all fail-CLOSED on missing


def test_missing_day30_is_warning(tmp_path):
    ms = [_mk("pool::x", SubjectKind.POOL, RiskWireClass.A, "A", "a" * 64)]
    proof.write_measurements(ms, generated_at=_now_iso(), as_of="2026-06-30", data_dir=tmp_path)
    r = _run(tmp_path)
    assert r["d_riskwire.day30.fresh"].status == WARNING


def test_totally_empty_all_warning(tmp_path):
    r = _run(tmp_path)
    assert all(c.status == WARNING for c in r.values())


# ── RED-TEAM: stale snapshot → WARNING ────────────────────────────────────────────────────────────
def test_stale_measurements_warns(tmp_path):
    _write_clean(tmp_path)
    p = tmp_path / "riskwire" / "measurements.json"
    doc = json.loads(p.read_text())
    doc["generated_at"] = "2020-01-01T00:00:00+00:00"   # ancient → stale (but artifact_hash recomputes
    # so proof stays valid; freshness is the failing gate) — re-seal so proof.valid still passes
    resealed = proof.seal_artifact({k: v for k, v in doc.items()
                                    if k not in ("head_hash", "artifact_hash")}, "measurements")
    p.write_text(json.dumps(resealed, indent=1))
    r = _run(tmp_path)
    assert r["d_riskwire.measurements.fresh"].status == WARNING
    assert r["d_riskwire.proof.valid"].status == OK       # only freshness failed, not the proof


# ── RED-TEAM: tampered snapshot → proof.valid WARNING ─────────────────────────────────────────────
def test_tampered_snapshot_proof_warns(tmp_path):
    _write_clean(tmp_path)
    p = tmp_path / "riskwire" / "measurements.json"
    doc = json.loads(p.read_text())
    doc["measurements"][1]["risk_class"] = "A"            # forge toxic ezeth-pt → safe, don't re-hash
    p.write_text(json.dumps(doc, indent=1))
    r = _run(tmp_path)
    assert r["d_riskwire.proof.valid"].status == WARNING


# ── RED-TEAM: NO-FORK check fires on divergence from a seed ────────────────────────────────────────
def test_no_fork_fires_on_seed_divergence(tmp_path):
    """Plant a DFB seed snapshot that DISAGREES with RISKWIRE's risk_class for the same pool → WARNING."""
    _write_clean(tmp_path, pool_class="A")
    dfb_dir = tmp_path / "dfb"
    dfb_dir.mkdir(parents=True, exist_ok=True)
    # seed says the same pool is class D — RISKWIRE says A → a FORK.
    (dfb_dir / "pools.json").write_text(json.dumps({
        "generated_at": _now_iso(), "n_pools": 1,
        "pools": [{"pool_id": "aave_v3-usdc", "risk_class": "D"}],
    }))
    r = _run(tmp_path)
    assert r["d_riskwire.no_fork"].status == WARNING
    assert "NO-FORK VIOLATION" in r["d_riskwire.no_fork"].title


def test_no_fork_ok_when_seed_agrees(tmp_path):
    _write_clean(tmp_path, pool_class="A")
    dfb_dir = tmp_path / "dfb"
    dfb_dir.mkdir(parents=True, exist_ok=True)
    (dfb_dir / "pools.json").write_text(json.dumps({
        "generated_at": _now_iso(), "n_pools": 2,
        "pools": [{"pool_id": "aave_v3-usdc", "risk_class": "A"},
                  {"pool_id": "ezeth-pt", "risk_class": "D"}],
    }))
    r = _run(tmp_path)
    assert r["d_riskwire.no_fork"].status == OK


def test_no_fork_warns_when_seed_anchor_missing(tmp_path):
    """A pool measurement with an EMPTY seed_proof_hash = RISKWIRE graded independently → WARNING."""
    ms = [_mk("pool::x", SubjectKind.POOL, RiskWireClass.A, "A", "")]   # empty anchor
    proof.write_measurements(ms, generated_at=_now_iso(), as_of="2026-06-30", data_dir=tmp_path)
    _write_day30(tmp_path)
    r = _run(tmp_path)
    assert r["d_riskwire.no_fork"].status == WARNING


# ── SMOKE: the domain is registered + surfaced in collect() ───────────────────────────────────────
def test_d_riskwire_in_collect(tmp_path):
    _write_clean(tmp_path)
    m = SystemHealthMonitor(data_dir=str(tmp_path))
    rep = m.collect()
    assert "d_riskwire" in rep["domains"]
    ids = {c["id"] for c in rep["checks"] if c["id"].startswith("d_riskwire")}
    assert ids == {"d_riskwire.measurements.fresh", "d_riskwire.day30.fresh",
                   "d_riskwire.proof.valid", "d_riskwire.no_fork"}
