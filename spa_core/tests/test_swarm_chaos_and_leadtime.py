"""Tests for chaos_drill.py (block 5b) and leadtime_evidence.py (tier-port S2)."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.strategy_lab.swarm import chaos_drill as cd
from spa_core.strategy_lab.swarm import leadtime_evidence as le
from spa_core.strategy_lab.swarm import swarm_health as sh

NOW = datetime(2026, 7, 11, 12, 0, tzinfo=timezone.utc)


# ── chaos drill ────────────────────────────────────────────────────────────────────────────────
def _proof_line(payload: dict) -> str:
    rec = dict(payload)
    rec.setdefault("date", "2026-07-11")
    rec["prev_hash"] = "0" * 64
    rec["hash"] = hashlib.sha256((rec["prev_hash"] + json.dumps(rec, sort_keys=True)).encode()
                                 ).hexdigest()
    return json.dumps(rec, sort_keys=True) + "\n"


def _healthy_swarm(d: Path) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    d.mkdir(parents=True, exist_ok=True)
    (d / "guardian_forward.json").write_text(json.dumps(
        {"as_of_utc": ts, "books": {"b": {"state": "ARMED"}}}))
    (d / "guardian_forward_proof.jsonl").write_text(_proof_line({"books": 1}))
    (d / "blend_forward.json").write_text(json.dumps({"as_of_utc": ts, "state": "WARMUP"}))
    (d / "blend_forward_proof.jsonl").write_text(_proof_line({"state": "WARMUP"}))
    (d / "funding_regime.json").write_text(json.dumps(
        {"as_of_utc": ts, "regime": "GREEN",
         "consumer_contract": "UNKNOWN must be treated as not-GREEN (fail-closed)."}))
    (d / "funding_regime_proof.jsonl").write_text(_proof_line({"regime": "GREEN"}))
    (d / "leverage_brain.json").write_text(json.dumps(
        {"as_of_utc": ts, "books": {"x": {"state": "RECOMMENDED", "leverage_reco": 1.5,
                                          "levered_shape": False,
                                          "factors": {"depth_factor": 1.0}}}}))
    (d / "leverage_brain_proof.jsonl").write_text(_proof_line({"recos": {}}))
    (d / "swarm_book.json").write_text(json.dumps(
        {"as_of_utc": ts, "equity": 100_000.0, "weights": {"b": 0.25}}))
    (d / "swarm_book_proof.jsonl").write_text(_proof_line({"equity": 100_000.0}))
    (d / "eyc_allocator.json").write_text(json.dumps(
        {"as_of_utc": ts, "state": "SCORED", "venues": {"v": {}},
         "algorithm": {"authority": "NONE — shadow only"}}))
    (d / "eyc_allocator_proof.jsonl").write_text(_proof_line({"state": "SCORED"}))


def test_chaos_drill_all_scenarios_caught(tmp_path):
    _healthy_swarm(tmp_path / "swarm")
    doc = cd.run_chaos_drill(swarm_dir=tmp_path / "swarm", out_dir=tmp_path / "out")
    assert doc["all_ok"] is True
    assert len(doc["scenarios"]) == len(cd.SCENARIOS) + 1  # + control
    saved = json.loads((tmp_path / "out" / cd.STATUS_NAME).read_text())
    assert saved["all_ok"] is True


def test_chaos_drill_degraded_control_is_a_finding(tmp_path):
    (tmp_path / "swarm").mkdir()  # empty live dir → control cannot be OK
    doc = cd.run_chaos_drill(swarm_dir=tmp_path / "swarm", out_dir=tmp_path / "out")
    assert doc["all_ok"] is False
    assert doc["scenarios"][0]["scenario"] == "control" and doc["scenarios"][0]["ok"] is False


def test_chaos_drill_never_mutates_live(tmp_path):
    live = tmp_path / "swarm"
    _healthy_swarm(live)
    before = {p.name: p.read_bytes() for p in live.iterdir()}
    cd.run_chaos_drill(swarm_dir=live, out_dir=tmp_path / "out")
    after = {p.name: p.read_bytes() for p in live.iterdir()}
    assert before == after  # sandbox-only, live untouched


# ── lead-time evidence ─────────────────────────────────────────────────────────────────────────
def _track(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "track.json"
    p.write_text(json.dumps({"daily": rows}))
    return p


def _guardian(tmp_path: Path, derisk_dates: list[str]) -> Path:
    p = tmp_path / "guardian.json"
    p.write_text(json.dumps({"shadow": {"live_track": {
        "derisk_events": [{"date": d, "action": "DERISK"} for d in derisk_dates]}}}))
    return p


def _day(i: int) -> str:
    return (datetime(2026, 6, 1) + timedelta(days=i)).date().isoformat()


def test_episode_detection_thresholds():
    rows = [{"date": _day(0), "close_equity": 100000.0, "daily_return_pct": 0.01},
            {"date": _day(1), "close_equity": 97500.0, "daily_return_pct": -2.5},   # DL01
            {"date": _day(2), "close_equity": 94000.0, "daily_return_pct": -3.59},  # DL01 + SOFT (dd −6%)
            {"date": _day(3), "close_equity": 89000.0, "daily_return_pct": -5.32}]  # DL01 + HARD (dd −11%)
    eps = le.detect_episodes(rows)
    kinds = {(e["date"], e["kind"]) for e in eps}
    assert (_day(1), "DL01_LIKE") in kinds
    assert (_day(2), "SOFT_LIKE") in kinds
    assert (_day(3), "HARD_LIKE") in kinds
    assert not any(k == "SOFT_LIKE" and d == _day(3) for d, k in kinds)  # HARD supersedes SOFT


def test_led_episode_scored(tmp_path):
    rows = ([{"date": _day(i), "close_equity": 100000.0, "daily_return_pct": 0.0}
             for i in range(5)]
            + [{"date": _day(5), "close_equity": 97000.0, "daily_return_pct": -3.0}])
    doc = le.run_leadtime_evidence(
        live_track_path=_track(tmp_path, rows),
        guardian_path=_guardian(tmp_path, [_day(3)]),  # DERISK 2 days before the loss
        out_dir=tmp_path)
    assert doc["state"] == "EVIDENCE"
    ep = doc["episodes"][0]
    assert ep["verdict"] == "LED" and ep["lead_days"] == 2
    assert doc["score"]["led"] == 1 and doc["score"]["false_alarms"] == 0


def test_missed_episode_and_false_alarm(tmp_path):
    rows = ([{"date": _day(i), "close_equity": 100000.0, "daily_return_pct": 0.0}
             for i in range(30)]
            + [{"date": _day(30), "close_equity": 97000.0, "daily_return_pct": -3.0}])
    doc = le.run_leadtime_evidence(
        live_track_path=_track(tmp_path, rows),
        guardian_path=_guardian(tmp_path, [_day(2)]),  # alarm 28 days before → NOT lead, false
        out_dir=tmp_path)
    assert doc["episodes"][0]["verdict"] == "MISSED"
    assert doc["false_alarms"] == [_day(2)]


def test_young_alarm_pending_not_false(tmp_path):
    rows = [{"date": _day(i), "close_equity": 100000.0, "daily_return_pct": 0.0}
            for i in range(20)]
    doc = le.run_leadtime_evidence(
        live_track_path=_track(tmp_path, rows),
        guardian_path=_guardian(tmp_path, [_day(15)]),  # only 4 days old — can't judge yet
        out_dir=tmp_path)
    assert doc["pending_alarms"] == [_day(15)]
    assert doc["false_alarms"] == []


def test_calm_track_no_events_yet(tmp_path):
    rows = [{"date": _day(i), "close_equity": 100000.0 + i, "daily_return_pct": 0.001}
            for i in range(40)]
    doc = le.run_leadtime_evidence(
        live_track_path=_track(tmp_path, rows),
        guardian_path=_guardian(tmp_path, []),
        out_dir=tmp_path)
    assert doc["state"] == "NO_EVENTS_YET" and doc["score"]["episodes"] == 0


def test_no_track_fail_closed(tmp_path):
    doc = le.run_leadtime_evidence(
        live_track_path=tmp_path / "missing.json",
        guardian_path=tmp_path / "missing2.json",
        out_dir=tmp_path)
    assert doc["state"] == "NO_TRACK"
