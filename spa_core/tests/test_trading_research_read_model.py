"""trading_lab_view() — RM-TRUTH-01 C1 / ADR-590 item 7.

Hermetic, like test_trading_research.py: a real forward tick builds the engine's own files in a
tmp dir, which are then COPIED read-only into a second tmp dir — the read model is only ever
exercised against that second, untouched copy, never the dir the tick wrote into and never any
live data/.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

from spa_core.trading_research import evidence as ev
from spa_core.trading_research import forward as fw
from spa_core.trading_research import strategies as st
from spa_core.trading_research.market_data import HOUR_MS, FIRST_1H_MS
from spa_core.trading_research.read_model import (MEASURED, MEASURED_ZERO, NOT_ENOUGH_HISTORY,
                                                   NOT_MEASURED, trading_lab_view)

from .test_trading_research import FakeExchange, synth


def _ro_copy(src: Path, dst: Path) -> Path:
    dst.mkdir(parents=True, exist_ok=True)
    for f in src.iterdir():
        if f.is_file():
            shutil.copy2(f, dst / f.name)
            os.chmod(dst / f.name, stat.S_IRUSR | stat.S_IRGRP)
    return dst


def _build_engine_dir(tmp_path: Path, monkeypatch, *, n_candidates=2) -> tuple[Path, int, int]:
    live_dir = tmp_path / "live"
    monkeypatch.setenv("SPA_TRADING_DATA_DIR", str(live_dir))
    bars = synth(6000, t0=FIRST_1H_MS)
    ex = FakeExchange(bars)
    one = [c for c in st.registry() if c.timeframe == "1h" and c.exec_model == "spot_long"][:n_candidates]
    monkeypatch.setattr(fw, "registry", lambda: one)
    monkeypatch.setattr(fw, "by_id", lambda: {c.id: c for c in one})
    monkeypatch.setattr(fw.bt, "registry", lambda: one)
    reg_at = bars[5000].open_time + 30 * 60_000
    fw.tick(now_ms=reg_at, http=ex)
    later = bars[5030].open_time + HOUR_MS + 120_000
    fw.tick(now_ms=later, http=ex)
    ro_dir = _ro_copy(live_dir, tmp_path / "ro_copy")
    return ro_dir, reg_at, later


def test_view_against_a_read_only_copy_reports_a_healthy_fresh_engine(tmp_path, monkeypatch):
    ro_dir, reg_at, later = _build_engine_dir(tmp_path, monkeypatch)
    view = trading_lab_view(ro_dir, now_ms=later + 5 * 60_000)
    assert view["engine_health"]["value"] == "HEALTHY"
    assert view["evidence_integrity"]["value"] == "VERIFIED"
    assert view["strategies_researched"]["value"] == 2
    assert view["backtests"]["value"]["count"] == 2
    assert view["oos_contamination_D2"]["value"] is False       # fix B: oos_end_ms is published
    assert view["live_capital"]["value"] == 0 and view["live_capital"]["state"] == MEASURED_ZERO
    assert view["data_gaps"]["state"] == MEASURED
    # nothing in this module ever wrote to the read-only copy
    for name in ("status.json", "backtest.json", "evidence.db", "market.db"):
        p = ro_dir / name
        if p.exists():
            assert not (p.stat().st_mode & stat.S_IWUSR)


def test_view_is_honestly_not_measured_for_an_empty_directory(tmp_path):
    empty = tmp_path / "nothing_here"
    empty.mkdir()
    view = trading_lab_view(empty, now_ms=1_700_000_000_000)
    assert view["engine_health"]["value"] is None and view["engine_health"]["state"] == NOT_MEASURED
    assert view["strategies_researched"]["value"] is None and view["strategies_researched"]["state"] == NOT_MEASURED
    assert view["forward_paper_active"]["value"] is None
    assert view["related_products"]["state"] == NOT_MEASURED       # never fetched, never assumed
    # inv #17: the third outcome is NAMED, not just "value is None" — every NOT_MEASURED cell
    # carries a non-empty Russian reason string explaining WHICH observation is missing and why.
    not_measured = {k: c for k, c in view.items() if c["state"] == NOT_MEASURED}
    assert len(not_measured) == 21, sorted(not_measured)  # defect #2 regression: all 21 fields
    for k, c in not_measured.items():
        assert isinstance(c.get("reason"), str) and c["reason"].strip(), (k, c)


# ── Defect #1 (RM-TRUTH-01 Wave 2 integrator finding): `data_dir` must be the canonical repo
# data/ dir, like every other Director OS v2 read model takes — not the engine's own
# .../trading_research subdirectory, which earlier callers had to know to append themselves. ──

def test_repo_data_dir_is_the_canonical_argument(tmp_path, monkeypatch):
    """Passing the PARENT of trading_research (what company_truth.py and every sibling read
    model take) must resolve to the engine's state dir automatically — this is the exact call
    shape that used to silently return NOT_MEASURED for all 21 fields (defect #1)."""
    ro_engine_dir, reg_at, later = _build_engine_dir(tmp_path, monkeypatch)
    repo_data = tmp_path / "repo_data"
    repo_data.mkdir()
    ro_copy = _ro_copy(ro_engine_dir, repo_data / "trading_research")
    view = trading_lab_view(repo_data, now_ms=later + 5 * 60_000)
    assert view["engine_health"]["value"] == "HEALTHY"
    assert view["strategies_researched"]["value"] == 2
    assert view["strategies_researched"]["state"] == MEASURED


def test_direct_trading_research_dir_still_works_backward_compat(tmp_path, monkeypatch):
    """The OLD contract — `data_dir` IS the trading_research dir, detected by the presence of
    evidence.db right inside it — must keep working: callers already updated to this file's
    earlier revision are not broken by the new canonical argument."""
    ro_dir, reg_at, later = _build_engine_dir(tmp_path, monkeypatch)
    view = trading_lab_view(ro_dir, now_ms=later + 5 * 60_000)
    assert view["engine_health"]["value"] == "HEALTHY"
    assert view["strategies_researched"]["value"] == 2


def test_a_data_dir_with_no_trading_research_subdir_is_honestly_not_measured(tmp_path, monkeypatch):
    """Positive control for the resolution itself: a parent dir whose child is NOT named
    trading_research (so the resolved path genuinely does not exist) must not coincidentally
    read anything — proves the earlier green result above is the resolution working, not luck."""
    ro_engine_dir, reg_at, later = _build_engine_dir(tmp_path, monkeypatch)
    decoy_parent = tmp_path / "decoy_parent"
    decoy_parent.mkdir()
    _ro_copy(ro_engine_dir, decoy_parent / "not_trading_research")
    view = trading_lab_view(decoy_parent, now_ms=later + 5 * 60_000)
    assert view["engine_health"]["state"] == NOT_MEASURED
    assert view["strategies_researched"]["state"] == NOT_MEASURED
    assert "trading_research" in view["strategies_researched"]["reason"]


def test_against_a_read_only_copy_of_the_live_production_ledger(tmp_path):
    """Verify the canonical (repo data/) argument against a real COPY of the live, append-only
    production evidence.db/status.json/backtest.json — never the live files themselves, and
    never written to. This is the exact scenario the integrator's finding described: the repo
    data/ dir, not .../trading_research, as the argument."""
    live_src = Path.home() / "Documents" / "SPA_Claude" / "data" / "trading_research"
    needed = ("evidence.db", "status.json", "backtest.json")
    if not all((live_src / f).is_file() for f in needed):
        import pytest
        pytest.skip(f"NOT MEASURED — live ledger copy unavailable at {live_src} ({needed})")
    repo_data = tmp_path / "repo_data"
    dst = repo_data / "trading_research"
    dst.mkdir(parents=True)
    for f in needed:
        shutil.copy2(live_src / f, dst / f)
        os.chmod(dst / f, stat.S_IRUSR | stat.S_IRGRP)
    status = json.loads((dst / "status.json").read_text())
    gen_ms = status["generated_at_ms"]
    view = trading_lab_view(repo_data, now_ms=gen_ms + 60_000)
    assert view["strategies_researched"]["value"] == 138
    assert view["strategies_researched"]["state"] == MEASURED
    assert view["forward_paper_active"]["value"] == 5
    assert view["forward_paper_active"]["state"] == MEASURED
    # nothing in this module ever wrote to the copy (let alone the live files it was copied from)
    for f in needed:
        assert not (dst / f).stat().st_mode & stat.S_IWUSR


def test_view_never_opens_the_copy_for_writing(tmp_path, monkeypatch):
    """A read-only connection must not even attempt the schema-creation DDL that ev.connect() runs
    — this is what proves the module is really using mode=ro and not silently falling back to a
    writable connection that happens to work because the tables already exist."""
    ro_dir, reg_at, later = _build_engine_dir(tmp_path, monkeypatch)
    before = (ro_dir / "evidence.db").read_bytes()
    trading_lab_view(ro_dir, now_ms=later + 60_000)
    after = (ro_dir / "evidence.db").read_bytes()
    assert before == after


def test_performance_windows_are_not_enough_history_below_maturity(tmp_path, monkeypatch):
    ro_dir, reg_at, later = _build_engine_dir(tmp_path, monkeypatch)
    view = trading_lab_view(ro_dir, now_ms=later + 60_000)
    fwd_ids = list(view["latest_btc_signal_forward"]["value"])
    if not fwd_ids:
        return  # synthetic noise did not qualify this run; covered deterministically below instead
    for cid in fwd_ids:
        assert view["performance_7d"]["value"][cid].get("state") == NOT_ENOUGH_HISTORY
        assert view["performance_30d"]["value"][cid].get("state") == NOT_ENOUGH_HISTORY


def test_performance_window_matures_past_the_threshold(tmp_path):
    """Deterministic version of the maturity gating — hand-built evidence, no reliance on whether
    synthetic noise happens to qualify a candidate this run."""
    live = tmp_path / "live"
    live.mkdir()
    c = ev.connect(live / "evidence.db")
    cid = "cand1"
    T0 = 1_700_000_000_000 - (1_700_000_000_000 % (24 * 3_600_000))
    ev.register(c, cid, "h1", {"family": "x", "timeframe": "1D", "exec_model": "spot_long"},
               now_ms=T0, code_version="v")
    for frm, to in ((None, "DISCOVERED"), ("DISCOVERED", "BACKTESTING"),
                    ("BACKTESTING", "BACKTEST_QUALIFIED"), ("BACKTEST_QUALIFIED", "FORWARD_PAPER")):
        ev.append_event(c, cid, frm, to, "r", {}, actor="t", now_ms=T0)
    day_ms = 24 * 3_600_000
    for i in range(1, 11):                                        # 10 daily bars ⇒ 9-day span
        row = {k: None for k in ev.OBS_FIELDS} | {
            "candidate_id": cid, "asset": "BTC", "timeframe": "1D", "bar_open_time": T0 + i * day_ms,
            "bar_close_time": T0 + (i + 1) * day_ms, "signal_ts_ms": T0 + (i + 1) * day_ms,
            "late": 0, "gap_bars": 0, "bar_open": 1.0, "bar_close": 1.0, "position_before": 1,
            "fill_cost": 0.0, "funding": 0.0, "position_held": 1, "equity": 1.0 + 0.01 * i, "target": 1,
            "action": "HOLD", "book_state": "{}", "assumptions": "{}", "data_ref": "r", "code_version": "v"}
        ev.append_observation(c, row)
    c.commit()
    status = {"generated_at_ms": T0 + 11 * day_ms, "ok": True, "evidence_verified": True,
             "live_capital_usd": 0, "backtest_qualified": 1}
    (live / "status.json").write_text(json.dumps(status))
    (live / "backtest.json").write_text(json.dumps({"manifest": {"oos_end_ms": T0}, "results": []}))
    view = trading_lab_view(live, now_ms=T0 + 11 * day_ms)
    perf7 = view["performance_7d"]["value"][cid]
    assert perf7.get("state") != NOT_ENOUGH_HISTORY and "net_return" in perf7
    assert view["performance_30d"]["value"][cid]["state"] == NOT_ENOUGH_HISTORY   # 9 days < 30
