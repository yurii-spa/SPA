"""
Tests for the Rates-Desk LIVE paper forward-track surface — GET /api/rates-desk/track.

The credibility/distribution artifact: the validated FixedCarry sleeve runs live in paper (no capital)
via com.spa.rates_desk_paper, accruing a verifiable FORWARD track. The endpoint serves that growing
record from data/rates_desk/paper/ (status.json + {sleeve}_series.json):

  - it returns the track shape (sleeve_id, started_at, days, current_equity, cumulative_return_pct,
    daily_series[], last_tick, is_advisory),
  - it is graceful when no track exists yet (empty, never a 500),
  - is_advisory is ALWAYS true (advisory research, not the go-live track, not real capital).

Run:
    python -m pytest spa_core/tests/test_rates_desk_track_api.py -q
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# ── Path setup ─────────────────────────────────────────────────────────────────
_HERE = Path(__file__).resolve().parent
_SPA_CORE = _HERE.parent
_PROJECT_ROOT = _SPA_CORE.parent
for _p in [str(_SPA_CORE), str(_PROJECT_ROOT)]:
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest

pytest.importorskip(
    "fastapi", reason="fastapi optional dep not installed — API suite skipped"
)
from fastapi.testclient import TestClient  # noqa: E402

import spa_core.api.server as server  # noqa: E402


# ── Helpers ─────────────────────────────────────────────────────────────────────
def _write_track(data_dir: Path, series: list, *, equity_now=None, last_tick=None, gap=False) -> None:
    """Write a status.json + {sleeve}_series.json pair into data/rates_desk/paper/."""
    paper = data_dir / "rates_desk" / "paper"
    paper.mkdir(parents=True, exist_ok=True)
    last = series[-1] if series else {}
    (paper / "rates_desk_fixed_carry_series.json").write_text(
        json.dumps({
            "id": "rates_desk_fixed_carry",
            "series": series,
            "generated_at": "2026-06-26T00:00:00+00:00",
        }),
        encoding="utf-8",
    )
    (paper / "status.json").write_text(
        json.dumps({
            "generated_at": "2026-06-26T00:00:00+00:00",
            "date": last.get("date"),
            "gap": gap,
            "gap_reason": "",
            "sleeve": {
                "id": "rates_desk_fixed_carry",
                "name": "Rates Desk — Fixed Carry (PT to maturity)",
                "is_advisory": True,
                "mandate": "stable",
                "equity_usd": equity_now if equity_now is not None else last.get("equity_usd"),
                "net_apy_pct": last.get("net_apy_pct", 0.0),
                "open_books": last.get("open_books", 0),
                "closed_books": last.get("closed_books", 0),
                "last_tick": last_tick if last_tick is not None else last.get("date"),
            },
        }),
        encoding="utf-8",
    )


def _pt(date: str, equity: float) -> dict:
    return {
        "date": date, "ts": date + "T00:00:00+00:00",
        "equity_usd": equity, "net_apy_pct": 0.0,
        "open_books": 0, "closed_books": 0, "approvals": 0, "refusals": 2,
    }


@pytest.fixture()
def track_client(tmp_path, monkeypatch):
    """TestClient with the server's data dir redirected to a hermetic tmp dir."""
    monkeypatch.setattr(server, "_DATA_DIR", tmp_path)
    with TestClient(server.app, raise_server_exceptions=True) as c:
        yield c, tmp_path


# ── Tests ────────────────────────────────────────────────────────────────────────
def test_track_returns_shape(track_client):
    """A live track: 200 + the full track shape, days/cumulative return derived from the series."""
    client, data_dir = track_client
    _write_track(data_dir, [
        _pt("2026-06-25", 100000.0),
        _pt("2026-06-26", 100050.0),
    ], last_tick="2026-06-26")

    r = client.get("/api/rates-desk/track")
    assert r.status_code == 200
    d = r.json()
    assert d["sleeve_id"] == "rates_desk_fixed_carry"
    assert d["started_at"] == "2026-06-25"
    assert d["days"] == 2
    assert d["current_equity"] == 100050.0
    # 100050 / 100000 - 1 = +0.05%
    assert d["cumulative_return_pct"] == pytest.approx(0.05)
    assert d["last_tick"] == "2026-06-26"
    assert d["is_advisory"] is True
    # daily_series carries date + equity/nav per point.
    assert isinstance(d["daily_series"], list) and len(d["daily_series"]) == 2
    p0 = d["daily_series"][0]
    assert p0["date"] == "2026-06-25"
    assert p0["equity"] == 100000.0
    assert p0["nav"] == 100000.0


def test_track_early_single_day(track_client):
    """An EARLY track (just started this sprint): one day so far, honest days=1, return 0."""
    client, data_dir = track_client
    _write_track(data_dir, [_pt("2026-06-25", 100000.0)])
    d = client.get("/api/rates-desk/track").json()
    assert d["days"] == 1
    assert d["started_at"] == "2026-06-25"
    assert d["cumulative_return_pct"] == pytest.approx(0.0)
    assert d["is_advisory"] is True


def test_track_graceful_when_no_track(track_client):
    """No track files at all: empty track (days 0, empty series), never a 500."""
    client, _ = track_client  # tmp_path has no rates_desk/paper/
    r = client.get("/api/rates-desk/track")
    assert r.status_code == 200
    d = r.json()
    assert d["days"] == 0
    assert d["started_at"] is None
    assert d["daily_series"] == []
    assert d["cumulative_return_pct"] is None
    # advisory flag is ALWAYS present and true, even with no track.
    assert d["is_advisory"] is True
    assert d["sleeve_id"] == "rates_desk_fixed_carry"


def test_track_advisory_flag_always_true(track_client):
    """is_advisory is true whether the track is rich, early, or empty — never live capital."""
    client, data_dir = track_client
    # Even if some upstream wrote is_advisory differently, the endpoint asserts advisory=True.
    _write_track(data_dir, [_pt("2026-06-25", 100000.0), _pt("2026-06-26", 99950.0)])
    d = client.get("/api/rates-desk/track").json()
    assert d["is_advisory"] is True
    # a drawdown is reported honestly (negative cumulative return).
    assert d["cumulative_return_pct"] == pytest.approx(-0.05)
