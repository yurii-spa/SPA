"""Tests for spa_core/strategy_lab/swarm/swarm_health.py (Swarm block 5 — immune layer)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.strategy_lab.swarm import swarm_health as sh

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


def _proof_line(payload: dict) -> str:
    rec = dict(payload)
    rec.setdefault("date", "2026-07-11")
    rec["prev_hash"] = "0" * 64
    rec["hash"] = hashlib.sha256((rec["prev_hash"] + json.dumps(rec, sort_keys=True)).encode()
                                 ).hexdigest()
    return json.dumps(rec, sort_keys=True) + "\n"


def _healthy_swarm(d: Path, age_h: float = 0.5) -> None:
    ts = (NOW - timedelta(hours=age_h)).isoformat()
    d.mkdir(parents=True, exist_ok=True)
    (d / "guardian_forward.json").write_text(json.dumps(
        {"as_of_utc": ts, "books": {"susde_dn": {"state": "ARMED"}}}))
    (d / "guardian_forward_proof.jsonl").write_text(_proof_line({"books": 1}))
    (d / "blend_forward.json").write_text(json.dumps({"as_of_utc": ts, "state": "WARMUP"}))
    (d / "blend_forward_proof.jsonl").write_text(_proof_line({"state": "WARMUP"}))
    (d / "funding_regime.json").write_text(json.dumps(
        {"as_of_utc": ts, "regime": "GREEN",
         "consumer_contract": "UNKNOWN must be treated as not-GREEN (fail-closed)."}))
    (d / "funding_regime_proof.jsonl").write_text(_proof_line({"regime": "GREEN"}))
    (d / "leverage_brain.json").write_text(json.dumps(
        {"as_of_utc": ts, "books": {
            "susde_dn": {"state": "RECOMMENDED", "leverage_reco": 1.5,
                         "levered_shape": False, "factors": {"depth_factor": 1.0}},
            "leverage_loop": {"state": "REFUSED_NO_DEPTH", "leverage_reco": None,
                              "levered_shape": True, "factors": {"depth_factor": None}}}}))
    (d / "leverage_brain_proof.jsonl").write_text(_proof_line({"recos": {}}))
    (d / "swarm_book.json").write_text(json.dumps(
        {"as_of_utc": ts, "equity": 100_000.0, "weights": {"susde_dn": 0.25}}))
    (d / "swarm_book_proof.jsonl").write_text(_proof_line({"equity": 100_000.0}))


def test_all_healthy_ok(tmp_path):
    _healthy_swarm(tmp_path)
    doc = sh.run_swarm_health(now=NOW, swarm_dir=tmp_path)
    assert doc["overall"] == "OK"
    assert all(o["ok"] for o in doc["organs"].values())


def test_missing_organ_warns_never_ran(tmp_path):
    _healthy_swarm(tmp_path)
    (tmp_path / "blend_forward.json").unlink()
    doc = sh.run_swarm_health(now=NOW, swarm_dir=tmp_path)
    assert doc["overall"] == "WARNING"
    assert "never ran" in doc["organs"]["blend_forward"]["detail"]


def test_stale_organ_warns(tmp_path):
    _healthy_swarm(tmp_path, age_h=sh.FRESH_HOURS + 1)
    doc = sh.run_swarm_health(now=NOW, swarm_dir=tmp_path)
    assert doc["overall"] == "WARNING"
    assert not doc["organs"]["guardian_forward"]["fresh"]


def test_tampered_proof_detected(tmp_path):
    _healthy_swarm(tmp_path)
    p = tmp_path / "funding_regime_proof.jsonl"
    rec = json.loads(p.read_text())
    rec["regime"] = "RED"  # mutate content without recomputing the hash
    p.write_text(json.dumps(rec, sort_keys=True) + "\n")
    doc = sh.run_swarm_health(now=NOW, swarm_dir=tmp_path)
    assert doc["overall"] == "WARNING"
    assert "MISMATCH" in doc["organs"]["funding_regime"]["proof"]["detail"]


def test_brain_refusal_invariant_violation_caught(tmp_path):
    """A levered book carrying a numeric reco WITHOUT depth must trip the immune layer."""
    _healthy_swarm(tmp_path)
    brain = json.loads((tmp_path / "leverage_brain.json").read_text())
    brain["books"]["leverage_loop"] = {
        "state": "RECOMMENDED", "leverage_reco": 4.0,  # the forbidden thing
        "levered_shape": True, "factors": {"depth_factor": None}}
    (tmp_path / "leverage_brain.json").write_text(json.dumps(brain))
    doc = sh.run_swarm_health(now=NOW, swarm_dir=tmp_path)
    assert doc["overall"] == "WARNING"
    assert "invariant broken" in doc["organs"]["leverage_brain"]["contract"]["detail"]


def test_unknown_regime_value_caught(tmp_path):
    _healthy_swarm(tmp_path)
    (tmp_path / "funding_regime.json").write_text(json.dumps(
        {"as_of_utc": NOW.isoformat(), "regime": "SUPER_GREEN",
         "consumer_contract": "not-GREEN fail-closed"}))
    doc = sh.run_swarm_health(now=NOW, swarm_dir=tmp_path)
    assert not doc["organs"]["funding_regime"]["contract"]["ok"]


def test_status_written(tmp_path):
    _healthy_swarm(tmp_path)
    sh.run_swarm_health(now=NOW, swarm_dir=tmp_path)
    saved = json.loads((tmp_path / sh.STATUS_NAME).read_text())
    assert saved["overall"] == "OK" and "fail-closed" in saved["note"]


def test_swarm_book_levered_weights_caught(tmp_path):
    """The book must never be levered: Σweights > 1 trips the immune layer."""
    _healthy_swarm(tmp_path)
    (tmp_path / "swarm_book.json").write_text(json.dumps(
        {"as_of_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
         "equity": 100_000.0, "weights": {"a": 0.8, "b": 0.6}}))
    doc = sh.run_swarm_health(now=datetime.now(timezone.utc), swarm_dir=tmp_path)
    assert doc["overall"] == "WARNING"
    assert "never be levered" in doc["organs"]["swarm_book"]["contract"]["detail"]
