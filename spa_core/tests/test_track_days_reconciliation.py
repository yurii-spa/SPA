#!/usr/bin/env python3
"""Track-days reconciliation (Architect T2).

ONE honest track-days number must flow to every surface — no drift, no hardcoded
counts. The canonical source is the EVIDENCED count produced by
``golive_checker`` (``GoLiveResult.real_track_days`` → ``golive_status.json``),
NOT the padded calendar ``days_running`` in ``paper_trading_status.json``.

These tests pin the contract that the value golive_checker computes is exactly
what every consumer (``/api/health-public``, ``/api/ssot/facts``, the
SYSTEM_BRIEFING builder) exposes — derived from the same source, never the
inflated ``days_running``, and fail-CLOSED when the source is missing.
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from spa_core.paper_trading.golive_checker import GoLiveChecker
from spa_core.governance import ssot as _ssot
import spa_core.api.server as _server


# ─── fixtures ────────────────────────────────────────────────────────────────


def _write(p: Path, obj) -> None:
    p.write_text(json.dumps(obj), encoding="utf-8")


@pytest.fixture
def synthetic_track(tmp_path: pytest.TempPathFactory):
    """A data/ dir whose equity curve has N evidenced bars + extra padding.

    Evidenced bars carry ``evidenced: true``; a flat-rate backfill bar carries
    ``evidenced: false`` (must NOT be counted). days_running is deliberately
    inflated to prove no surface reads it as the track length.
    """
    data_dir = Path(tmp_path) / "data"
    data_dir.mkdir()
    anchor = date(2026, 6, 22)
    n_evidenced = 5

    daily = []
    # one pre-anchor warmup bar (excluded)
    daily.append({"date": "2026-06-10", "is_warmup": True, "close_equity": 100000.0})
    # n evidenced bars from the anchor
    for i in range(n_evidenced):
        d = anchor + timedelta(days=i)
        daily.append(
            {
                "date": d.isoformat(),
                "evidenced": True,
                "source": "cycle",
                "close_equity": 100000.0 + i,
            }
        )
    # one flat-rate backfill bar AFTER the evidenced run (excluded)
    daily.append(
        {
            "date": (anchor + timedelta(days=n_evidenced)).isoformat(),
            "evidenced": False,
            "source": "backfill",
            "close_equity": 100100.0,
        }
    )

    _write(
        data_dir / "equity_curve_daily.json",
        {"is_demo": False, "summary": {"real_days": n_evidenced}, "daily": daily},
    )
    # Inflated calendar day count — the padded value no surface may surface.
    _write(
        data_dir / "paper_trading_status.json",
        {"is_demo": False, "days_running": 17, "current_equity": 100100.0,
         "apy_today_pct": 3.6, "total_return_pct": 0.1, "last_cycle_ts": "now"},
    )
    return data_dir, n_evidenced


# ─── canonical source ────────────────────────────────────────────────────────


def test_golive_checker_counts_only_evidenced(synthetic_track):
    data_dir, n = synthetic_track
    res = GoLiveChecker(data_dir=str(data_dir), home_dir=str(data_dir)).check(write=True)
    # 5 evidenced, not 7 bars and not 17 days_running.
    assert res.real_track_days == n
    written = json.loads((data_dir / "golive_status.json").read_text())
    assert written["real_track_days"] == n


# ─── every surface == canonical ──────────────────────────────────────────────


def test_ssot_facts_track_days_is_evidenced_not_days_running(synthetic_track, monkeypatch):
    data_dir, n = synthetic_track
    GoLiveChecker(data_dir=str(data_dir), home_dir=str(data_dir)).check(write=True)
    facts = _ssot.key_facts(data_dir=str(data_dir))
    assert facts["track_days"] == n, "SSOT track_days must be the evidenced count"
    assert facts["real_track_days"] == n
    # The inflated days_running must NOT leak into track_days.
    assert facts["track_days"] != 17


def test_health_public_exposes_evidenced_count(synthetic_track, monkeypatch):
    data_dir, n = synthetic_track
    GoLiveChecker(data_dir=str(data_dir), home_dir=str(data_dir)).check(write=True)
    # Point the server's data loader at the synthetic data dir.
    monkeypatch.setattr(_server, "_DATA_DIR", Path(data_dir), raising=False)
    monkeypatch.setattr(_server, "_get_live_portfolio", lambda: None, raising=False)
    out = _server.get_health_public()
    assert out["real_track_days"] == n
    assert out["track_days"] == n
    # Raw padded value retained only for transparency, never as the headline.
    assert out["days_running_raw"] == 17


def test_all_surfaces_agree_on_one_number(synthetic_track, monkeypatch):
    """golive_checker == /api/health-public == /api/ssot/facts (one number)."""
    data_dir, n = synthetic_track
    res = GoLiveChecker(data_dir=str(data_dir), home_dir=str(data_dir)).check(write=True)
    facts = _ssot.key_facts(data_dir=str(data_dir))
    monkeypatch.setattr(_server, "_DATA_DIR", Path(data_dir), raising=False)
    monkeypatch.setattr(_server, "_get_live_portfolio", lambda: None, raising=False)
    health = _server.get_health_public()
    assert (
        res.real_track_days
        == facts["track_days"]
        == facts["real_track_days"]
        == health["real_track_days"]
        == health["track_days"]
        == n
    )


# ─── fail-CLOSED ─────────────────────────────────────────────────────────────


def test_health_public_fail_closed_when_golive_missing(tmp_path, monkeypatch):
    """No golive_status.json → expose None, never the inflated days_running."""
    data_dir = Path(tmp_path) / "data"
    data_dir.mkdir()
    _write(
        data_dir / "paper_trading_status.json",
        {"is_demo": False, "days_running": 17, "current_equity": 100000.0},
    )
    monkeypatch.setattr(_server, "_DATA_DIR", Path(data_dir), raising=False)
    monkeypatch.setattr(_server, "_get_live_portfolio", lambda: None, raising=False)
    out = _server.get_health_public()
    assert out["real_track_days"] is None
    assert out["track_days"] is None
    # Crucially: it must NOT silently fall back to the padded 17.
    assert out["track_days"] != 17


def test_live_golive_status_matches_checker():
    """On the real data dir, the persisted golive_status agrees with the checker.

    The persisted ``golive_status.json`` is a daily snapshot (owner-gated, committed),
    while the checker re-derives the evidenced count LIVE from the cycle logs. Between
    cycle runs the live checker can legitimately be one (or more) evidenced day AHEAD
    of the last-written snapshot — that is honest forward drift, not a defect.

    The lie this guards against is the OPPOSITE: a snapshot INFLATED above what the
    checker can actually evidence (the historical "padded 17/30" bug). So we assert
    the snapshot is never greater than the live count (never padded) and that the two
    only ever differ by benign snapshot lag.
    """
    repo = Path(__file__).resolve().parents[2]
    status_path = repo / "data" / "golive_status.json"
    if not status_path.is_file():
        pytest.skip("no live golive_status.json")
    persisted = json.loads(status_path.read_text())["real_track_days"]
    live = GoLiveChecker().check(write=False).real_track_days
    # Never inflated: the committed snapshot must not claim MORE evidenced days than
    # the checker can independently re-derive from the cycle logs.
    assert persisted <= live, (
        f"persisted real_track_days={persisted} exceeds live checker={live} — "
        "the snapshot is padded above the evidenced reality"
    )
    # Only ever benign forward lag (a snapshot is at most a couple of cycles stale).
    assert live - persisted <= 2, (
        f"snapshot lags the live checker by {live - persisted} days — "
        "regenerate golive_status.json (owner-gated)"
    )
