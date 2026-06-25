"""
spa_core/tests/test_strategy_lab_paper.py — Strategy-Lab live paper service tests.

THE KEY TEST is restart-survival: tick a few times with injected fake MarketData (NO network),
persist, then construct a BRAND-NEW PaperService that reloads from disk, and assert state
continuity — equity is NOT reset to fresh capital, the time-series is preserved, last_tick is
restored, and a same-day re-tick does NOT double-accrue. We also cover fail-closed (a raising
fetch → safe-hold + recorded gap + no fabricated point) and kill-event persistence.

stdlib only. No network — a FakeMarketData yields canned MarketSnapshots.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
from pathlib import Path

import pytest

from spa_core.strategy_lab.base import InvalidDataError, MarketSnapshot
from spa_core.strategy_lab.paper import PaperService


# ── fakes ────────────────────────────────────────────────────────────────────────────────────
class FakeMarketData:
    """Injectable stand-in for MarketData. latest() returns a canned snapshot (no network)."""

    def __init__(self, snapshot=None, raise_on_latest=False):
        self._snap = snapshot
        self._raise = raise_on_latest

    def set_snapshot(self, snapshot):
        self._snap = snapshot

    def latest(self) -> MarketSnapshot:
        if self._raise:
            raise InvalidDataError("fake fetch failure")
        return self._snap


def _snapshot(date: str, eth=3000.0, funding=0.0002, ratio=1.03, restaking=0.04,
              defi_apy=0.045) -> MarketSnapshot:
    """A valid snapshot driving every strategy in the lab."""
    return MarketSnapshot(
        date=date,
        eth_price_usd=eth,
        funding_rate_8h=funding,
        lrt_price_usd={"eeth": eth * ratio},
        lrt_eth_ratio={"eeth": ratio},
        restaking_apy={"eeth": restaking},
        defi_apy={"stable_blend": defi_apy},
    )


def _captured_telegram():
    sent = []

    def _send(text: str) -> bool:
        sent.append(text)
        return True

    return sent, _send


def _make_service(tmp_path: Path, md, sent_send=None):
    return PaperService(
        market_data=md,
        state_dir=tmp_path,
        telegram_send=sent_send,
        alert_on_kill=True,
        alert_on_gap=True,
    )


# ── tests ──────────────────────────────────────────────────────────────────────────────────────
def test_tick_persists_state_and_series(tmp_path):
    md = FakeMarketData(_snapshot("2026-06-10"))
    svc = _make_service(tmp_path, md)
    status = svc.tick()

    assert status["gap"] is False
    assert status["n_strategies"] >= 6
    # every strategy has a state file + a series file with one point
    for sid in svc._strategies:
        assert (tmp_path / f"{sid}_state.json").exists()
        doc = json.loads((tmp_path / f"{sid}_series.json").read_text())
        assert len(doc["series"]) == 1
        assert doc["series"][0]["date"] == "2026-06-10"


def test_restart_survival(tmp_path):
    """KEY TEST: a new PaperService reloads persisted state — book continues, not zeroed."""
    md = FakeMarketData()

    # Tick three distinct days with the FIRST service.
    svc1 = _make_service(tmp_path, md)
    for i, d in enumerate(("2026-06-10", "2026-06-11", "2026-06-12")):
        md.set_snapshot(_snapshot(d, eth=3000.0 + i * 50))
        svc1.tick()

    equity_before = {sid: s.equity() for sid, s in svc1._strategies.items()}
    series_len_before = {
        sid: len(json.loads((tmp_path / f"{sid}_series.json").read_text())["series"])
        for sid in svc1._strategies
    }
    last_tick_before = dict(svc1._last_tick)

    # A baseline must have actually grown from its fresh capital (proves real accrual happened).
    assert svc1._strategies["rwa_floor"].equity() > 100000.0

    # Construct a BRAND-NEW service — restart-survival must restore, not re-init.
    svc2 = _make_service(tmp_path, md)
    for sid in svc2._strategies:
        # equity restored (NOT reset to fresh capital)
        assert svc2._strategies[sid].equity() == pytest.approx(equity_before[sid], rel=1e-9), sid
        # last_tick restored
        assert svc2._last_tick[sid] == last_tick_before[sid] == "2026-06-12", sid
        # series preserved
        cur = len(json.loads((tmp_path / f"{sid}_series.json").read_text())["series"])
        assert cur == series_len_before[sid], sid

    # Continuing on a NEW day advances from the restored state (series grows by exactly 1).
    md.set_snapshot(_snapshot("2026-06-13", eth=3200.0))
    svc2.tick()
    for sid in svc2._strategies:
        cur = len(json.loads((tmp_path / f"{sid}_series.json").read_text())["series"])
        assert cur == series_len_before[sid] + 1, sid


def test_idempotent_same_day_retick(tmp_path):
    """Re-ticking the SAME UTC day must not double-accrue (replays the single tick)."""
    md = FakeMarketData(_snapshot("2026-06-10"))
    svc = _make_service(tmp_path, md)

    svc.tick()
    equity_after_first = {sid: s.equity() for sid, s in svc._strategies.items()}

    # Tick again, same date — equity must be identical (no compounding) + series stays length 1.
    svc.tick()
    for sid, s in svc._strategies.items():
        assert s.equity() == pytest.approx(equity_after_first[sid], rel=1e-9), sid
        doc = json.loads((tmp_path / f"{sid}_series.json").read_text())
        assert len(doc["series"]) == 1, sid

    # Idempotency also survives a restart: reload then re-tick the same day → still no change.
    svc2 = _make_service(tmp_path, md)
    svc2.tick()
    for sid, s in svc2._strategies.items():
        assert s.equity() == pytest.approx(equity_after_first[sid], rel=1e-9), sid
        doc = json.loads((tmp_path / f"{sid}_series.json").read_text())
        assert len(doc["series"]) == 1, sid


def test_series_grows_one_point_per_distinct_day(tmp_path):
    """REGRESSION (P1): the forward series must APPEND one point per distinct market date and
    NOT duplicate on a same-date re-tick. The original bug left every series stuck at n=1 because
    the market date never advanced across hourly ticks — here we advance it explicitly and assert
    the track grows 1→2→3, while a same-date re-tick holds it flat."""
    md = FakeMarketData()
    svc = _make_service(tmp_path, md)

    def _series_len(sid):
        return len(json.loads((tmp_path / f"{sid}_series.json").read_text())["series"])

    def _series_dates(sid):
        return [p["date"] for p in json.loads((tmp_path / f"{sid}_series.json").read_text())["series"]]

    days = ("2026-06-10", "2026-06-11", "2026-06-12", "2026-06-13")
    for n, d in enumerate(days, start=1):
        md.set_snapshot(_snapshot(d, eth=3000.0 + n * 25))
        svc.tick()
        # one fresh point per distinct day → series length tracks the day count exactly
        for sid in svc._strategies:
            assert _series_len(sid) == n, (sid, d, n)
            assert _series_dates(sid) == list(days[:n]), sid
        # re-ticking the SAME day must NOT add a duplicate point (idempotent)
        svc.tick()
        for sid in svc._strategies:
            assert _series_len(sid) == n, (sid, "re-tick", d)
            assert _series_dates(sid)[-1] == d, sid

    # final track has exactly one dated point per distinct day, in order, no duplicates
    for sid in svc._strategies:
        dates = _series_dates(sid)
        assert dates == list(days), sid
        assert len(dates) == len(set(dates)), sid  # no duplicate dates


def test_real_market_data_refreshed_once_per_day(tmp_path):
    """The fix triggers a live-data refresh on the FIRST tick of each UTC day (so latest().date
    advances), and at most once per day (hourly ticks must not re-fetch the network 24×/day).
    We use a fake whose .refresh() advances the date it serves and counts its calls."""

    class RefreshingMarketData:
        """Stands in for the real MarketData: has a refresh() that advances the served date."""

        def __init__(self, dates):
            self._dates = list(dates)
            self._idx = -1
            self.refresh_calls = 0

        def refresh(self):
            self.refresh_calls += 1
            if self._idx < len(self._dates) - 1:
                self._idx += 1

        def latest(self):
            i = max(0, self._idx)
            return _snapshot(self._dates[i])

    md = RefreshingMarketData(["2026-06-10", "2026-06-11"])
    svc = _make_service(tmp_path, md)

    # First refresh of "day 1" → fetch fires, served date becomes 2026-06-10.
    svc._refresh_market_data_if_due("2026-06-10")
    assert md.refresh_calls == 1
    assert md.latest().date == "2026-06-10"

    # Same UTC day, more (hourly) ticks → NO additional fetch (network not hit 24×/day).
    svc._refresh_market_data_if_due("2026-06-10")
    svc._refresh_market_data_if_due("2026-06-10")
    assert md.refresh_calls == 1  # still one fetch for the whole day

    # A NEW UTC day → fetch fires again and the served date advances.
    svc._refresh_market_data_if_due("2026-06-11")
    assert md.refresh_calls == 2
    assert md.latest().date == "2026-06-11"


def test_fail_closed_on_raising_fetch(tmp_path):
    """A raising live fetch → safe-hold: no advance, gap recorded, no fabricated series point."""
    # First a good tick so there is a known prior state.
    md = FakeMarketData(_snapshot("2026-06-10"))
    sent, send = _captured_telegram()
    svc = _make_service(tmp_path, md, send)
    svc.tick()
    equity_before = {sid: s.equity() for sid, s in svc._strategies.items()}
    series_len_before = {
        sid: len(json.loads((tmp_path / f"{sid}_series.json").read_text())["series"])
        for sid in svc._strategies
    }

    # Now make the fetch raise.
    md._raise = True
    status = svc.tick()

    assert status["gap"] is True
    assert "fail" in status["gap_reason"].lower() or "fetch" in status["gap_reason"].lower()
    # no strategy advanced, no series point appended (no fabricated data)
    for sid, s in svc._strategies.items():
        assert s.equity() == pytest.approx(equity_before[sid], rel=1e-9), sid
        cur = len(json.loads((tmp_path / f"{sid}_series.json").read_text())["series"])
        assert cur == series_len_before[sid], sid
    # a gap alert fired via the injected telegram sender
    assert any("GAP" in m for m in sent)


def test_fail_closed_on_invalid_snapshot(tmp_path):
    """latest() returning a snapshot with no date → treated as a gap (fail-closed)."""
    md = FakeMarketData(MarketSnapshot(date=""))  # empty date == unusable
    svc = _make_service(tmp_path, md)
    status = svc.tick()
    assert status["gap"] is True


def test_kill_event_persisted_and_alerted(tmp_path):
    """A depeg crash kills variant_n → event written to kills.jsonl + a telegram alert fires."""
    md = FakeMarketData()
    sent, send = _captured_telegram()
    svc = _make_service(tmp_path, md, send)

    # Day 1: normal entry establishes the LRT/perp legs at ratio 1.03.
    md.set_snapshot(_snapshot("2026-06-10", ratio=1.03))
    svc.tick()

    # Day 2: ratio collapses well past variant_n's lrt_depeg_kill_pct (2%) → kill.
    md.set_snapshot(_snapshot("2026-06-11", ratio=0.90))
    svc.tick()

    kills_path = tmp_path / "kills.jsonl"
    assert kills_path.exists()
    events = [json.loads(ln) for ln in kills_path.read_text().splitlines() if ln.strip()]
    killed_ids = {e["strategy"] for e in events}
    assert "variant_n" in killed_ids
    assert any("KILL" in m for m in sent)

    # Status reflects the kill.
    status = svc.status()
    assert status["strategies"]["variant_n"]["killed"] is True


def test_status_runs_without_tick(tmp_path):
    """status() works on a fresh service (first run, no ticks) — used by --status CLI."""
    md = FakeMarketData(_snapshot("2026-06-10"))
    svc = _make_service(tmp_path, md)
    status = svc.status()
    assert status["n_strategies"] >= 6
    assert (tmp_path / "status.json").exists()
