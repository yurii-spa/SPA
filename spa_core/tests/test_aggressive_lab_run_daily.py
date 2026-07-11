"""Regression tests for the aggressive_lab Lane-1 accrual entry `run_daily`.

Guards the 2026-07-06 "frozen track" root bug: the live tick MUST build the REAL feeds
(_real_history_feeds) — a bare PaperService() defaults to empty feeds and fail-closes every
restaking/ratio book (leverage_loop + levered_restaking stuck at 0 days). These tests assert
the WIRING without ever persisting to the live paper state (PaperService is spied/replaced).
"""
from spa_core.strategy_lab.aggressive_lab import run
from spa_core.strategy_lab.aggressive_lab.feeds import AggressiveFeeds


def test_run_daily_passes_real_feeds_not_empty(monkeypatch):
    captured = {}

    class SpyService:
        def __init__(self, feeds=None, **kw):
            captured["feeds"] = feeds

        def tick(self, as_of=None):
            captured["as_of"] = as_of
            return {"spy": True}

    # A light fake standing in for the real (network) feeds — carries a steth restaking series
    # so we can assert the restaking books' data actually reaches the service.
    fake = AggressiveFeeds(restaking_series={"steth": {"2026-07-11": 0.022}})
    monkeypatch.setattr(run, "PaperService", SpyService)
    monkeypatch.setattr(run, "_real_history_feeds", lambda: fake)

    out = run.run_daily("2026-07-11")
    assert out == {"spy": True}
    # THE guard: the service got the REAL feeds object, not a bare empty AggressiveFeeds().
    assert captured["feeds"] is fake
    assert "steth" in (captured["feeds"]._restaking or {}), "restaking series must reach the tick"
    assert captured["as_of"] == "2026-07-11"


def test_main_paper_branch_routes_through_run_daily(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(run, "run_daily", lambda: calls.__setitem__("n", calls["n"] + 1) or {"ok": True})
    monkeypatch.setattr(run, "run_real_backtest", lambda: {"bt": True})
    # paper-only mode → exactly one run_daily call (no divergent PaperService construction)
    assert run.main(["paper"]) == 0
    assert calls["n"] == 1


def test_runner_resolves_run_daily_first():
    # The standing daily runner's FIRST accrual candidate is 'run:run_daily'. It must now
    # resolve (previously missing → runner fell to the empty-feeds cls().tick() freeze path).
    from spa_core.strategy_lab import aggressive_lab_runner as R

    fn = R._resolve(R._ACCRUAL_CANDIDATES)
    assert fn is not None
    assert getattr(fn, "__name__", "") == "run_daily"
    assert fn is run.run_daily
