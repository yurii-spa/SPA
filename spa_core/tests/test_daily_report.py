"""Tests for MP-102: spa_core/reporting/daily_report.py.

All sources are written into a tmp data dir — fully deterministic, no network.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from spa_core.reporting import daily_report as dr

NOW = datetime(2026, 6, 11, 8, 0, tzinfo=timezone.utc)
DATE = "2026-06-10"  # «вчера» относительно NOW


# ─── Fixtures ────────────────────────────────────────────────────────────────


def _write(tmp_path, name, obj):
    (tmp_path / name).write_text(json.dumps(obj), encoding="utf-8")


def _seed(tmp_path, *, golive_ready=False, with_risk=True):
    _write(
        tmp_path,
        dr.EQUITY_FILENAME,
        {
            "source": "cycle_runner",
            "is_demo": False,
            "summary": {"total_return_pct": 0.0101},
            "daily": [
                {
                    "date": "2026-06-09",
                    "open_equity": 100000.0,
                    "close_equity": 100000.0,
                    "daily_return_pct": 0.0,
                    "cumulative_return_pct": 0.0,
                    "positions": {"aave_v3": 50000.0},
                },
                {
                    "date": DATE,
                    "open_equity": 100000.0,
                    "close_equity": 100010.09,
                    "daily_return_pct": 0.010089,
                    "cumulative_return_pct": 0.010089,
                    "positions": {
                        "aave_v3": 40000.0,
                        "morpho_blue": 20000.0,
                        "yearn_v3": 14000.0,
                    },
                },
            ],
        },
    )
    _write(
        tmp_path,
        dr.STATUS_FILENAME,
        {
            "is_demo": False,
            "days_running": 22,
            "current_equity": 100010.09,
            "current_positions": {"aave_v3": 40000.0, "maple": 9000.0},
        },
    )
    _write(tmp_path, dr.GOLIVE_FILENAME, {"ready": golive_ready, "checks": {}})
    if with_risk:
        _write(
            tmp_path,
            dr.RISK_SCORES_FILENAME,
            {
                "scores": [
                    {"protocol": "Aave V3", "slug": "aave-v3", "grade": "A"},
                    {"protocol": "Morpho Blue", "slug": "morpho-blue", "grade": "B"},
                ]
            },
        )


# ─── Tests ───────────────────────────────────────────────────────────────────


def test_basic_report_fields(tmp_path):
    _seed(tmp_path)
    r = dr.generate_daily_report(DATE, data_dir=tmp_path, now=NOW)
    assert r["date"] == DATE
    assert r["is_demo"] is False
    assert r["equity_usd"] == pytest.approx(100010.09)
    assert r["daily_pnl_usd"] == pytest.approx(10.09)
    assert r["daily_pnl_pct"] == pytest.approx(0.010089)
    assert r["total_return_pct"] == pytest.approx(0.010089)
    assert r["days_running"] == 22
    # Позиции берутся из бара отчётной даты, не из status.
    assert r["top_protocol"] == "aave_v3"
    assert r["active_adapters"] == ["aave_v3", "morpho_blue", "yearn_v3"]
    assert r["golive_status"] == "PRE-LIVE"
    assert r["risk_summary"] == {"aave_v3": "A", "morpho_blue": "B"}


def test_default_date_is_yesterday(tmp_path):
    _seed(tmp_path)
    r = dr.generate_daily_report(data_dir=tmp_path, now=NOW)
    assert r["date"] == DATE  # NOW = 2026-06-11 → вчера = 2026-06-10


def test_report_file_written_atomically(tmp_path):
    _seed(tmp_path)
    r = dr.generate_daily_report(DATE, data_dir=tmp_path, now=NOW)
    out = tmp_path / f"daily_report_{DATE}.json"
    assert out.exists()
    assert json.loads(out.read_text(encoding="utf-8")) == r
    # Никаких tmp-огрызков после атомарной записи.
    assert not list(tmp_path.glob("*.tmp"))


def test_write_false_writes_nothing(tmp_path):
    _seed(tmp_path)
    dr.generate_daily_report(DATE, data_dir=tmp_path, now=NOW, write=False)
    assert not (tmp_path / f"daily_report_{DATE}.json").exists()


def test_golive_ready_maps_to_ready(tmp_path):
    _seed(tmp_path, golive_ready=True)
    r = dr.generate_daily_report(DATE, data_dir=tmp_path, now=NOW)
    assert r["golive_status"] == "READY"


def test_missing_risk_scores_gives_empty_summary(tmp_path):
    _seed(tmp_path, with_risk=False)
    r = dr.generate_daily_report(DATE, data_dir=tmp_path, now=NOW)
    assert r["risk_summary"] == {}


def test_missing_equity_bar_degrades_gracefully(tmp_path):
    _seed(tmp_path)
    r = dr.generate_daily_report("2026-06-08", data_dir=tmp_path, now=NOW)
    assert r["equity_usd"] is None
    assert r["daily_pnl_usd"] is None
    assert r["daily_pnl_pct"] is None
    # total_return падает обратно на summary.
    assert r["total_return_pct"] == pytest.approx(0.0101)
    # Позиции — fallback на paper_trading_status.
    assert r["top_protocol"] == "aave_v3"
    assert r["active_adapters"] == ["aave_v3", "maple"]


def test_empty_data_dir_never_raises(tmp_path):
    r = dr.generate_daily_report(DATE, data_dir=tmp_path, now=NOW)
    assert r["equity_usd"] is None
    assert r["total_return_pct"] is None
    assert r["top_protocol"] is None
    assert r["active_adapters"] == []
    assert r["risk_summary"] == {}
    assert r["golive_status"] == "PRE-LIVE"
    assert (tmp_path / f"daily_report_{DATE}.json").exists()


def test_invalid_date_raises_value_error(tmp_path):
    with pytest.raises(ValueError):
        dr.generate_daily_report("10-06-2026", data_dir=tmp_path, now=NOW)


def test_cycle_runner_writes_daily_report(tmp_path):
    """MP-102 integration: run_cycle() → daily_report_{today}.json появился."""
    from spa_core.paper_trading import cycle_runner as cr

    apy = {"aave_v3": 4.0, "morpho_blue": 5.0, "yearn_v3": 3.0}
    target = {"aave_v3": 40000.0, "morpho_blue": 20000.0, "yearn_v3": 14000.0}

    def orch_fn(data_dir):
        return SimpleNamespace(
            adapters=[
                {
                    "protocol": p,
                    "apy_pct": a,
                    "tvl_usd": 1e7,
                    "tier": "T1" if p == "aave_v3" else "T2",
                    "status": "ok",
                }
                for p, a in apy.items()
            ],
            status="ok",
        )

    allocator = SimpleNamespace(
        allocate=lambda: SimpleNamespace(
            target_usd=dict(target),
            expected_apy_pct=3.0,
            model_used="risk_adjusted",
            strategy_loop_active=False,
        )
    )
    now = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)
    result = cr.run_cycle(
        data_dir=tmp_path,
        now=now,
        orchestrator_fn=orch_fn,
        allocator=allocator,
        risk_scorer_fn=lambda d: None,
    )
    assert result.status == "ok"
    out = tmp_path / "daily_report_2026-06-10.json"
    assert out.exists()
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["date"] == "2026-06-10"
    assert report["equity_usd"] == pytest.approx(result.current_equity, abs=0.01)
    assert report["top_protocol"] == "aave_v3"


def test_cycle_runner_report_failure_is_failsafe(tmp_path, monkeypatch, caplog):
    """Исключение в отчёте → WARNING, run_cycle не падает (MP-102 fail-safe)."""
    import logging

    from spa_core.paper_trading import cycle_runner as cr
    from spa_core.reporting import daily_report as drmod

    def boom(*a, **kw):
        raise RuntimeError("boom")

    monkeypatch.setattr(drmod, "generate_daily_report", boom)

    def orch_fn(data_dir):
        return SimpleNamespace(
            adapters=[
                {"protocol": "aave_v3", "apy_pct": 4.0, "tvl_usd": 1e7,
                 "tier": "T1", "status": "ok"}
            ],
            status="ok",
        )

    allocator = SimpleNamespace(
        allocate=lambda: SimpleNamespace(
            target_usd={"aave_v3": 40000.0},
            expected_apy_pct=4.0,
            model_used="risk_adjusted",
            strategy_loop_active=False,
        )
    )
    with caplog.at_level(logging.WARNING, logger="spa.cycle_runner"):
        result = cr.run_cycle(
            data_dir=tmp_path,
            now=datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc),
            orchestrator_fn=orch_fn,
            allocator=allocator,
            risk_scorer_fn=lambda d: None,
        )
    assert result.status == "ok"
    assert any("daily report generation failed" in r.message for r in caplog.records)
    assert not (tmp_path / "daily_report_2026-06-10.json").exists()
