# FROZEN-DATE-OK: injected-clock — build_ledger() принимает часы ВХОДОМ
# (`now_iso=`), а `days_remaining` считается как `DAYS_NEEDED - n`, то есть из
# СЧЁТА баров, не из календаря. Даты ниже — синтетические ярлыки баров в файле
# доходности, ни одно утверждение не сравнивает их с «сейчас». Проверено
# ЗАМЕРОМ, а не объявлено: под часами, сдвинутыми на +365 дней, весь файл даёт
# 9 passed. Якорь трека 2026-06-22 при этом ПРЕДМЕТ проверки — до-якорный
# прогрев и обратная засыпка обязаны исключаться именно по нему.
"""Tests for the Q2-18 evidenced-track ledger (spa_core/paper_trading/track_ledger.py).

Verifies: only EVIDENCED bars are counted (warmup/backfill excluded via the single segregation point),
drawdown-from-running-peak is computed correctly, the summary counts + days_remaining are right, and a
missing/malformed equity file yields an empty ledger fail-closed (never a fabricated day). Deterministic.
"""
import json
from unittest.mock import patch

import pytest

from spa_core.paper_trading import track_ledger as tl


def _bar(date, close, *, evidenced=True, source="cycle", daily_return_pct=0.0):
    b = {"date": date, "close_equity": close, "daily_return_pct": daily_return_pct,
         "evidenced": evidenced, "source": source}
    return b


def _equity_file(tmp_path, bars):
    p = tmp_path / "equity_curve_daily.json"
    p.write_text(json.dumps({"daily": bars}))
    return p


def test_only_evidenced_bars_counted(tmp_path):
    bars = [
        _bar("2026-06-08", 100000, evidenced=False, source="warmup"),   # pre-anchor warmup → excluded
        _bar("2026-06-22", 100150, daily_return_pct=0.15),               # evidenced
        _bar("2026-06-23", 100300, daily_return_pct=0.15),               # evidenced
        _bar("2026-06-24", 100200, evidenced=False, source="backfill"),  # backfill → excluded
    ]
    rep = tl.build_ledger(equity_path=_equity_file(tmp_path, bars), write=False)
    assert rep["n_evidenced_days"] == 2
    assert [r["date"] for r in rep["ledger"]] == ["2026-06-22", "2026-06-23"]
    assert rep["first_evidenced_date"] == "2026-06-22"
    assert rep["last_evidenced_date"] == "2026-06-23"


def test_drawdown_from_peak(tmp_path):
    # rises to 101000 then dips to 99990 → drawdown from peak = (99990/101000 - 1)*100 ≈ -1.0%
    bars = [
        _bar("2026-06-22", 100000),
        _bar("2026-06-23", 101000),
        _bar("2026-06-24", 99990),
    ]
    rep = tl.build_ledger(equity_path=_equity_file(tmp_path, bars), write=False)
    last = rep["ledger"][-1]
    assert last["drawdown_from_peak_pct"] == pytest.approx((99990 / 101000 - 1) * 100, abs=1e-3)
    assert rep["max_drawdown_from_peak_pct"] <= last["drawdown_from_peak_pct"] + 1e-9
    # cumulative return is vs the FIRST evidenced close
    assert last["cumulative_return_pct"] == pytest.approx((99990 / 100000 - 1) * 100, abs=1e-3)


def test_days_remaining_and_needed(tmp_path):
    bars = [_bar(f"2026-06-{22 + i:02d}", 100000 + i) for i in range(5)]
    rep = tl.build_ledger(equity_path=_equity_file(tmp_path, bars), write=False)
    assert rep["days_needed"] == tl.DAYS_NEEDED
    assert rep["n_evidenced_days"] == 5
    assert rep["days_remaining"] == tl.DAYS_NEEDED - 5


def test_missing_file_fail_closed(tmp_path):
    rep = tl.build_ledger(equity_path=tmp_path / "does_not_exist.json", write=False)
    assert rep["n_evidenced_days"] == 0
    assert rep["ledger"] == []
    assert rep["first_evidenced_date"] is None
    assert rep["cumulative_return_pct"] == 0.0


def test_out_path_override_writes_there_not_to_real_data_dir(tmp_path, monkeypatch):
    # Regression: build_ledger() used to always write to the module-level _OUT
    # (the real data/track_ledger.json) regardless of equity_path — a caller
    # sandboxing INPUT via equity_path could still silently write the REAL
    # track. Guard against the real data/track_ledger.json ever being touched
    # by this test by monkeypatching _OUT to a path that must stay untouched.
    sentinel = tmp_path / "must_not_be_written.json"
    monkeypatch.setattr(tl, "_OUT", sentinel)

    bars = [_bar("2026-06-22", 100000)]
    equity_p = _equity_file(tmp_path, bars)
    real_out = tmp_path / "sandbox_out" / "track_ledger.json"
    real_out.parent.mkdir()

    tl.build_ledger(equity_path=equity_p, out_path=real_out, write=True)

    assert real_out.exists()
    assert not sentinel.exists()


def test_deterministic(tmp_path):
    bars = [_bar("2026-06-22", 100000), _bar("2026-06-23", 100200)]
    p = _equity_file(tmp_path, bars)
    assert tl.build_ledger(equity_path=p, write=False) == tl.build_ledger(equity_path=p, write=False)


# ── Wiring into the daily cycle (Q2-18 step 7 in _run_smart_modules) ───────────
#
# Found orphaned 2026-08-29/30: build_ledger() reads the SAME primitive
# golive_checker uses, but nothing called it — data/track_ledger.json sat
# frozen at n_evidenced_days=19 (2026-07-10) for 7 weeks while the real
# evidenced count moved to 68. These tests guard the wiring itself, not the
# ledger math (already covered above) — a regression here would silently
# orphan the module again.

class TestWiredIntoSmartModules:
    def test_run_smart_modules_writes_track_ledger(self, tmp_path):
        from spa_core.paper_trading.cycle_runner import _run_smart_modules

        bars = [_bar("2026-06-22", 100000), _bar("2026-06-23", 100300)]
        _equity_file(tmp_path, bars)

        _run_smart_modules(data_dir=str(tmp_path), send_telegram=False)

        out = tmp_path / "track_ledger.json"
        assert out.exists()
        written = json.loads(out.read_text())
        assert written["n_evidenced_days"] == 2
        assert written["generated_at"] is not None  # main()'s own None-timestamp bug not repeated here

    def test_build_ledger_failure_does_not_crash_remaining_steps(self, tmp_path):
        # Same fail-safe contract as every other MP-* step in this function:
        # a raise inside track_ledger must be swallowed, not propagate.
        from spa_core.paper_trading.cycle_runner import _run_smart_modules

        bars = [_bar("2026-06-22", 100000)]
        _equity_file(tmp_path, bars)

        with patch(
            "spa_core.paper_trading.track_ledger.build_ledger",
            side_effect=RuntimeError("boom"),
        ):
            _run_smart_modules(data_dir=str(tmp_path), send_telegram=False)  # must not raise

        assert not (tmp_path / "track_ledger.json").exists()

    def test_run_smart_modules_passes_the_right_equity_path(self, tmp_path):
        # Regression guard for a plausible mistake: pointing at the wrong
        # data_dir (e.g. the default `data/` instead of the cycle's own dir)
        # would silently read someone else's track.
        from spa_core.paper_trading.cycle_runner import _run_smart_modules

        bars = [_bar("2026-06-22", 100000), _bar("2026-06-23", 100100), _bar("2026-06-24", 100400)]
        _equity_file(tmp_path, bars)

        _run_smart_modules(data_dir=str(tmp_path), send_telegram=False)

        written = json.loads((tmp_path / "track_ledger.json").read_text())
        assert written["n_evidenced_days"] == 3
        assert written["last_evidenced_date"] == "2026-06-24"
