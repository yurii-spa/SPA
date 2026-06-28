"""
spa_core/tests/test_captured_sleeves.py — WS-4.1 captured-paper promotion gate.

Pins the HONESTY contract: a sleeve is CAPTURED only when it genuinely passes validation
(PAPER_CANDIDATE in the promotion gate, is_advisory, real accruing forward track that passes
track_integrity); every other candidate gets an explicit NO_GO_* verdict + reason — never a
fabricated track. The advisory invariant is asserted; the go-live track is never read/written.

PURE / hermetic: injected promotion reports + in-memory series under a tmp data root. stdlib + pytest.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import json

import pytest

from spa_core.strategy_lab import captured_sleeves as cs


_FLOOR = 3.4


def _day(offset: int) -> str:
    return (datetime.date(2026, 6, 1) + datetime.timedelta(days=offset)).isoformat()


def _series(equities):
    return {"id": "x", "series": [
        {"date": _day(i), "ts": f"{_day(i)}T00:00:00+00:00", "equity_usd": float(e)}
        for i, e in enumerate(equities)]}


def _promotion(stage_by_id):
    return {"sleeves": [{"id": sid, "stage": stage, "reason": f"{stage} reason"}
                        for sid, stage in stage_by_id.items()]}


def _write_series(root, sid, doc):
    d = root / "strategy_lab_paper"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{sid}_series.json").write_text(json.dumps(doc))


# ── PROPERTY: a passing sleeve is captured; a failing one is an honest NO_GO ──────────────────
def test_paper_candidate_with_real_track_is_captured(tmp_path):
    _write_series(tmp_path, "rwa_sleeve", _series([100000.0, 100009.0, 100018.0, 100027.0]))
    _write_series(tmp_path, "eth_lst_neutral", {"id": "eth_lst_neutral", "series": []})
    prom = _promotion({"rwa_sleeve": "PAPER_CANDIDATE", "eth_lst_neutral": "REJECT"})
    idx = cs.build_captured_sleeves(data_dir=tmp_path, promotion_report=prom,
                                    floor_apy_pct=_FLOOR, write=True,
                                    now_iso="2026-06-28T00:00:00+00:00")
    assert idx["n_captured"] == 1
    assert idx["captured_ids"] == ["rwa_sleeve"]
    by = {r["id"]: r for r in idx["sleeves"]}
    assert by["rwa_sleeve"]["verdict"] == cs.CAPTURED
    assert by["rwa_sleeve"]["captured"] is True
    assert by["rwa_sleeve"]["nav_usd"] == 100027.0
    # the bounded captured book artifact was written
    book = tmp_path / "strategy_lab" / "captured" / "rwa_sleeve_captured.json"
    assert book.exists()
    bd = json.loads(book.read_text())
    assert bd["is_advisory"] is True and bd["separate_from_golive_track"] is True


def test_reject_sleeve_with_empty_track_is_insufficient(tmp_path):
    _write_series(tmp_path, "eth_lst_neutral", {"id": "eth_lst_neutral", "series": []})
    prom = _promotion({"eth_lst_neutral": "REJECT"})
    idx = cs.build_captured_sleeves(data_dir=tmp_path, promotion_report=prom,
                                    floor_apy_pct=_FLOOR, write=False)
    by = {r["id"]: r for r in idx["sleeves"]}
    assert by["eth_lst_neutral"]["verdict"] == cs.NO_GO_INSUFFICIENT
    assert by["eth_lst_neutral"]["captured"] is False
    # NO fabricated track numbers
    assert by["eth_lst_neutral"]["net_apy_pct"] is None


def test_real_track_but_not_paper_candidate_is_no_go_promotion(tmp_path):
    """A sleeve with a real accruing track that has NOT cleared the promotion gate → NO_GO_PROMOTION
    (honest: it has a track, but the gate did not pass it) — not captured."""
    _write_series(tmp_path, "rwa_sleeve", _series([100000.0, 100009.0, 100018.0]))
    prom = _promotion({"rwa_sleeve": "BACKTEST_PASS"})
    idx = cs.build_captured_sleeves(data_dir=tmp_path, promotion_report=prom,
                                    floor_apy_pct=_FLOOR, write=False)
    by = {r["id"]: r for r in idx["sleeves"]}
    assert by["rwa_sleeve"]["verdict"] == cs.NO_GO_PROMOTION
    assert by["rwa_sleeve"]["captured"] is False


def test_at_floor_flag_for_realized_floor_sleeve(tmp_path):
    """rwa_sleeve banks the floor → at_floor=True (credited as BASE yield, not an above-floor edge)."""
    # ~3.3% APY over 3 days → at or below the 3.4% floor
    _write_series(tmp_path, "rwa_sleeve", _series([100000.0, 100009.0, 100018.0, 100027.0]))
    prom = _promotion({"rwa_sleeve": "PAPER_CANDIDATE"})
    idx = cs.build_captured_sleeves(data_dir=tmp_path, promotion_report=prom,
                                    floor_apy_pct=_FLOOR, write=False)
    rwa = next(r for r in idx["sleeves"] if r["id"] == "rwa_sleeve")
    assert rwa["at_floor"] is True


# ── PROPERTY: the advisory invariant is asserted (never capture a live sleeve) ────────────────
def test_advisory_all_true_invariant(tmp_path):
    _write_series(tmp_path, "rwa_sleeve", _series([100000.0, 100009.0, 100018.0]))
    prom = _promotion({"rwa_sleeve": "PAPER_CANDIDATE"})
    idx = cs.build_captured_sleeves(data_dir=tmp_path, promotion_report=prom,
                                    floor_apy_pct=_FLOOR, write=False)
    assert idx["advisory_all_true"] is True


def test_non_advisory_sleeve_is_refused(tmp_path):
    """A series doc explicitly flagged is_advisory=False is REFUSED capture (fail-closed)."""
    doc = _series([100000.0, 100009.0, 100018.0])
    doc["id"] = "rwa_sleeve"
    doc["is_advisory"] = False
    _write_series(tmp_path, "rwa_sleeve", doc)
    prom = _promotion({"rwa_sleeve": "PAPER_CANDIDATE"})
    idx = cs.build_captured_sleeves(data_dir=tmp_path, promotion_report=prom,
                                    floor_apy_pct=_FLOOR, write=False)
    rwa = next(r for r in idx["sleeves"] if r["id"] == "rwa_sleeve")
    assert rwa["verdict"] == cs.NO_GO_NOT_ADVISORY
    assert rwa["captured"] is False


# ── RED-TEAM: a tampered / look-ahead forward series is REFUSED, never captured ───────────────
def test_redteam_lookahead_series_refused(tmp_path):
    future = (datetime.date.today() + datetime.timedelta(days=400)).isoformat()
    doc = {"id": "rwa_sleeve", "series": [
        {"date": "2026-06-25", "equity_usd": 100000.0},
        {"date": future, "equity_usd": 9_999_999.0}]}
    _write_series(tmp_path, "rwa_sleeve", doc)
    prom = _promotion({"rwa_sleeve": "PAPER_CANDIDATE"})
    idx = cs.build_captured_sleeves(data_dir=tmp_path, promotion_report=prom,
                                    floor_apy_pct=_FLOOR, write=False)
    rwa = next(r for r in idx["sleeves"] if r["id"] == "rwa_sleeve")
    assert rwa["verdict"] == cs.NO_GO_INTEGRITY
    assert rwa["captured"] is False
    assert rwa["integrity_reason"] == "future"


def test_redteam_duplicate_date_refused(tmp_path):
    doc = {"id": "rwa_sleeve", "series": [
        {"date": "2026-06-25", "equity_usd": 100000.0},
        {"date": "2026-06-25", "equity_usd": 500000.0}]}
    _write_series(tmp_path, "rwa_sleeve", doc)
    prom = _promotion({"rwa_sleeve": "PAPER_CANDIDATE"})
    idx = cs.build_captured_sleeves(data_dir=tmp_path, promotion_report=prom,
                                    floor_apy_pct=_FLOOR, write=False)
    rwa = next(r for r in idx["sleeves"] if r["id"] == "rwa_sleeve")
    assert rwa["verdict"] == cs.NO_GO_INTEGRITY


def test_flat_track_is_insufficient(tmp_path):
    """A perfectly flat (never-accrued) forward series is INSUFFICIENT_DATA, not a captured book."""
    _write_series(tmp_path, "rwa_sleeve", _series([100000.0, 100000.0, 100000.0]))
    prom = _promotion({"rwa_sleeve": "PAPER_CANDIDATE"})
    idx = cs.build_captured_sleeves(data_dir=tmp_path, promotion_report=prom,
                                    floor_apy_pct=_FLOOR, write=False)
    rwa = next(r for r in idx["sleeves"] if r["id"] == "rwa_sleeve")
    assert rwa["verdict"] == cs.NO_GO_INSUFFICIENT


# ── determinism + fail-CLOSED on missing promotion evidence ───────────────────────────────────
def test_deterministic(tmp_path):
    _write_series(tmp_path, "rwa_sleeve", _series([100000.0, 100009.0, 100018.0]))
    prom = _promotion({"rwa_sleeve": "PAPER_CANDIDATE"})
    a = cs.build_captured_sleeves(data_dir=tmp_path, promotion_report=prom, floor_apy_pct=_FLOOR,
                                  write=False, now_iso="2026-06-28T00:00:00+00:00")
    b = cs.build_captured_sleeves(data_dir=tmp_path, promotion_report=prom, floor_apy_pct=_FLOOR,
                                  write=False, now_iso="2026-06-28T00:00:00+00:00")
    assert a == b


def test_fail_closed_no_promotion_evidence(tmp_path):
    """No promotion sleeves → every candidate NO_GO_PROMOTION (never captured on absent evidence)."""
    _write_series(tmp_path, "rwa_sleeve", _series([100000.0, 100009.0, 100018.0]))
    idx = cs.build_captured_sleeves(data_dir=tmp_path, promotion_report={"sleeves": []},
                                    floor_apy_pct=_FLOOR, write=False)
    assert idx["n_captured"] == 0
    rwa = next(r for r in idx["sleeves"] if r["id"] == "rwa_sleeve")
    assert rwa["verdict"] == cs.NO_GO_PROMOTION
