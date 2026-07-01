"""Tests for the WS1.1 track-continuity self-heal (2026-07-01).

Pins the incident fix: a git reset to a stale committed ``equity_curve_daily.json``
dropped the genuinely-evidenced 2026-06-27/28/29 bars, and the daily append path
(which only ever writes TODAY onto the last bar) left a permanent hole that froze
real_track_days. The self-heal must:

  * DETECT a day with real cycle-log evidence (header + MP-416 equity line) but no
    equity bar, and RECOVER it from the log's recorded equity (verbatim);
  * REFUSE a day with no log / no header / no MP-416 line (fail-CLOSED — never
    fabricate a bar for a day without evidence);
  * be idempotent (no gap → no-op) and never drop/mutate a prior evidenced bar;
  * repair a base-drift bar (real yield accrued off a clobbered prior close)
    while PRESERVING its real daily_yield.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest

from spa_core.paper_trading import track_self_heal as sh
from spa_core.paper_trading.track_evidence import evidenced_dates

PAPER_START = date(2026, 6, 10)


# ─── helpers ──────────────────────────────────────────────────────────────────


def _write_cycle_log(
    logs_dir: Path,
    d: date,
    *,
    header: bool = True,
    equity: float | None = None,
    apy: float = 4.0,
) -> None:
    logs_dir.mkdir(parents=True, exist_ok=True)
    path = logs_dir / f"daily_cycle_{d.strftime('%Y%m%d')}.log"
    lines = []
    if header:
        lines.append(
            f"[{d.isoformat()}T06:00:01Z] Starting daily paper cycle (cycle_runner)"
        )
    lines.append("INFO spa.cycle_runner: some work")
    if equity is not None:
        lines.append(
            "INFO spa.cycle_runner: MP-416 evidence recorded: "
            f"date={d.isoformat()} apy={apy:.4f}% equity={equity:.2f}"
        )
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _bar(d: str, open_eq: float, close_eq: float, **extra) -> dict:
    b = {
        "date": d,
        "open_equity": open_eq,
        "close_equity": close_eq,
        "equity": close_eq,
        "daily_yield_usd": round(close_eq - open_eq, 4),
        "source": "cycle",
        "evidenced": True,
    }
    b.update(extra)
    return b


def _write_equity(data_dir: Path, daily: list[dict]) -> Path:
    data_dir.mkdir(parents=True, exist_ok=True)
    p = data_dir / "equity_curve_daily.json"
    doc = {
        "generated_at": "2026-06-30T00:00:00+00:00",
        "source": "cycle_runner",
        "is_demo": False,
        "summary": {},
        "daily": daily,
    }
    p.write_text(json.dumps(doc), encoding="utf-8")
    return p


# ─── log parsing (the evidence source) ──────────────────────────────────────────


def test_parse_cycle_log_equity_reads_recorded_value(tmp_path):
    logs = tmp_path / "logs"
    _write_cycle_log(logs, date(2026, 6, 27), equity=100201.66, apy=4.1656)
    got = sh.parse_cycle_log_equity(date(2026, 6, 27), logs)
    assert got == (100201.66, 4.1656)


def test_parse_takes_last_matching_line_for_that_date(tmp_path):
    """A log can hold several same-day runs — take the LAST recorded value."""
    logs = tmp_path / "logs"
    logs.mkdir()
    p = logs / "daily_cycle_20260627.log"
    p.write_text(
        "[2026-06-27T06:00:01Z] Starting daily paper cycle (cycle_runner)\n"
        "INFO spa.cycle_runner: MP-416 evidence recorded: date=2026-06-27 apy=3.0% equity=100199.26\n"
        "INFO spa.cycle_runner: MP-416 evidence recorded: date=2026-06-27 apy=4.1656% equity=100201.66\n",
        encoding="utf-8",
    )
    assert sh.parse_cycle_log_equity(date(2026, 6, 27), logs) == (100201.66, 4.1656)


def test_parse_ignores_other_dates_in_same_log(tmp_path):
    """A day-N log carrying a late day-(N-1) run must not cross-attribute."""
    logs = tmp_path / "logs"
    logs.mkdir()
    p = logs / "daily_cycle_20260630.log"
    p.write_text(
        "[2026-06-29T23:48Z] Starting daily paper cycle (cycle_runner)\n"
        "INFO spa.cycle_runner: MP-416 evidence recorded: date=2026-06-29 apy=3.0% equity=999.99\n"
        "INFO spa.cycle_runner: MP-416 evidence recorded: date=2026-06-30 apy=3.28% equity=100199.22\n",
        encoding="utf-8",
    )
    assert sh.parse_cycle_log_equity(date(2026, 6, 30), logs) == (100199.22, 3.28)


def test_parse_refuses_no_header(tmp_path):
    logs = tmp_path / "logs"
    _write_cycle_log(logs, date(2026, 6, 27), header=False, equity=100201.66)
    assert sh.parse_cycle_log_equity(date(2026, 6, 27), logs) is None


def test_parse_refuses_no_mp416_line(tmp_path):
    logs = tmp_path / "logs"
    _write_cycle_log(logs, date(2026, 6, 27), header=True, equity=None)
    assert sh.parse_cycle_log_equity(date(2026, 6, 27), logs) is None


def test_parse_refuses_missing_log(tmp_path):
    logs = tmp_path / "logs"
    logs.mkdir()
    assert sh.parse_cycle_log_equity(date(2026, 6, 27), logs) is None


# ─── detection ──────────────────────────────────────────────────────────────────


def test_detect_finds_missing_but_evidenced_day(tmp_path):
    logs = tmp_path / "logs"
    _write_cycle_log(logs, date(2026, 6, 26), equity=100190.22)
    _write_cycle_log(logs, date(2026, 6, 27), equity=100201.66)  # missing from curve
    doc = {"daily": [_bar("2026-06-26", 100180.31, 100190.22)]}
    missing = sh.detect_missing_evidenced_days(
        doc, logs_dir=logs, today=date(2026, 6, 30)
    )
    assert missing == ["2026-06-27"]


def test_detect_refuses_day_with_no_log(tmp_path):
    """RED-TEAM: a gap-day with NO cycle log is never a recovery candidate."""
    logs = tmp_path / "logs"
    _write_cycle_log(logs, date(2026, 6, 26), equity=100190.22)
    # 2026-06-27 has NO log at all.
    doc = {"daily": [_bar("2026-06-26", 100180.31, 100190.22)]}
    missing = sh.detect_missing_evidenced_days(
        doc, logs_dir=logs, today=date(2026, 6, 30)
    )
    assert missing == []


def test_detect_ignores_future_dated_log(tmp_path):
    logs = tmp_path / "logs"
    _write_cycle_log(logs, date(2026, 7, 5), equity=100300.0)  # future vs today
    doc = {"daily": [_bar("2026-06-26", 100180.31, 100190.22)]}
    missing = sh.detect_missing_evidenced_days(
        doc, logs_dir=logs, today=date(2026, 6, 30)
    )
    assert missing == []


# ─── recovery (the incident) ────────────────────────────────────────────────────


def test_heal_recovers_three_dropped_days_from_logs(tmp_path):
    """The exact incident: 06-27/28/29 dropped, recovered from real logs."""
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    for d, eq, apy in [
        (date(2026, 6, 26), 100190.22, 3.61),
        (date(2026, 6, 27), 100201.66, 4.1656),
        (date(2026, 6, 28), 100212.99, 4.1289),
        (date(2026, 6, 29), 100224.36, 4.1394),
    ]:
        _write_cycle_log(logs, d, equity=eq, apy=apy)
    # Curve has ONLY 06-26 (the stale-restore state).
    epath = _write_equity(data, [_bar("2026-06-26", 100180.31, 100190.22)])

    rep = sh.heal_track(
        equity_path=epath, logs_dir=logs, today=date(2026, 6, 30), apply=True
    )
    assert rep["healed"] == ["2026-06-27", "2026-06-28", "2026-06-29"]
    assert rep["evidenced_before"] == 1
    assert rep["evidenced_after"] == 4
    assert rep["applied"] is True

    doc = json.loads(epath.read_text())
    by = {b["date"]: b for b in doc["daily"]}
    # Recovered CLOSE equity matches the log verbatim (no fabrication).
    assert by["2026-06-27"]["close_equity"] == 100201.66
    assert by["2026-06-28"]["close_equity"] == 100212.99
    assert by["2026-06-29"]["close_equity"] == 100224.36
    # Provenance stamped.
    assert by["2026-06-27"]["recovered_from"] == "self_heal"
    assert by["2026-06-27"]["evidenced"] is True
    # Continuous chain: each open == prior close.
    assert by["2026-06-27"]["open_equity"] == 100190.22
    assert by["2026-06-28"]["open_equity"] == 100201.66
    assert by["2026-06-29"]["open_equity"] == 100212.99


def test_heal_no_fabrication_for_no_log_gap(tmp_path):
    """RED-TEAM: feed a fake gap-day with NO log → self-heal REFUSES it."""
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    _write_cycle_log(logs, date(2026, 6, 26), equity=100190.22)
    # 06-27 has NO log. 06-28 DOES.
    _write_cycle_log(logs, date(2026, 6, 28), equity=100212.99)
    epath = _write_equity(data, [_bar("2026-06-26", 100180.31, 100190.22)])

    rep = sh.heal_track(
        equity_path=epath, logs_dir=logs, today=date(2026, 6, 30), apply=True
    )
    doc = json.loads(epath.read_text())
    dates = {b["date"] for b in doc["daily"]}
    # 06-28 recovered (real log), 06-27 NEVER fabricated.
    assert "2026-06-28" in rep["healed"]
    assert "2026-06-27" not in rep["healed"]
    assert "2026-06-27" not in dates


def test_heal_is_idempotent_noop_when_continuous(tmp_path):
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    _write_cycle_log(logs, date(2026, 6, 26), equity=100190.22)
    _write_cycle_log(logs, date(2026, 6, 27), equity=100201.66)
    epath = _write_equity(
        data,
        [
            _bar("2026-06-26", 100180.31, 100190.22),
            _bar("2026-06-27", 100190.22, 100201.66, recovered_from="self_heal"),
        ],
    )
    rep = sh.heal_track(
        equity_path=epath, logs_dir=logs, today=date(2026, 6, 30), apply=True
    )
    assert rep["healed"] == []
    assert rep["repaired"] == []
    assert rep["applied"] is False


def test_heal_never_drops_prior_evidenced_bars(tmp_path):
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    for d, eq in [
        (date(2026, 6, 25), 100180.31),
        (date(2026, 6, 26), 100190.22),
        (date(2026, 6, 27), 100201.66),
    ]:
        _write_cycle_log(logs, d, equity=eq)
    epath = _write_equity(
        data,
        [
            _bar("2026-06-25", 100170.4, 100180.31),
            _bar("2026-06-26", 100180.31, 100190.22),
            # 06-27 dropped
        ],
    )
    sh.heal_track(equity_path=epath, logs_dir=logs, today=date(2026, 6, 30), apply=True)
    doc = json.loads(epath.read_text())
    dates = [b["date"] for b in doc["daily"]]
    assert dates == ["2026-06-25", "2026-06-26", "2026-06-27"]  # nothing lost


# ─── continuity repair (base-drift from a stale-restore) ────────────────────────


def test_repair_rechains_base_drift_preserving_yield(tmp_path):
    """The exact 06-30 pattern: a dropped day is recovered AND the downstream
    drifted bar (real yield accrued off a CLOBBERED prior close) is re-chained.

    Repair is scoped to bars STRICTLY AFTER a recovered day — so this mirrors the
    incident where 06-29 was recovered and 06-30 (which had accrued off the stale
    base) is then re-continuous'd, its real yield preserved.
    """
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    _write_cycle_log(logs, date(2026, 6, 28), equity=100212.99)
    _write_cycle_log(logs, date(2026, 6, 29), equity=100224.36)  # recovered
    _write_cycle_log(logs, date(2026, 6, 30), equity=100199.22, apy=3.28)
    # Curve: 06-28 present, 06-29 DROPPED, 06-30 accrued off the stale 100212.99
    # base (its open drifted); yield 8.9971 is REAL.
    epath = _write_equity(
        data,
        [
            _bar("2026-06-28", 100201.66, 100212.99),
            _bar(
                "2026-06-30", 100212.99, 100221.99,
                daily_yield_usd=8.9971, apy_today=3.28,
            ),
        ],
    )
    rep = sh.heal_track(
        equity_path=epath, logs_dir=logs, today=date(2026, 6, 30), apply=True
    )
    assert rep["healed"] == ["2026-06-29"]
    assert rep["repaired"] == ["2026-06-30"]
    doc = json.loads(epath.read_text())
    b30 = {b["date"]: b for b in doc["daily"]}["2026-06-30"]
    # Base re-chained off the TRUE recovered 06-29 close; real yield preserved.
    assert b30["open_equity"] == 100224.36
    assert b30["daily_yield_usd"] == 8.9971
    assert b30["close_equity"] == round(100224.36 + 8.9971, 2)  # 100233.36
    assert b30.get("continuity_repaired") is True


def test_repair_never_touches_untouched_track(tmp_path):
    """SAFETY: with NO recovered day, a drifted evidenced bar is NEVER re-chained.

    Absent a recovery the self-heal leaves an existing real bar byte-for-byte
    (a bare discontinuity is left for the cycle's own continuity guard to HALT
    on, honestly) — it never silently rewrites the go-live track's history.
    """
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    # Both days present + logged → nothing to RECOVER; 06-30 open drifts, but with
    # no recovery the repair must NOT fire.
    _write_cycle_log(logs, date(2026, 6, 29), equity=100224.36)
    _write_cycle_log(logs, date(2026, 6, 30), equity=100199.22, apy=3.28)
    epath = _write_equity(
        data,
        [
            _bar("2026-06-29", 100212.99, 100224.36),
            _bar("2026-06-30", 100190.22, 100199.22, daily_yield_usd=8.9971),
        ],
    )
    rep = sh.heal_track(
        equity_path=epath, logs_dir=logs, today=date(2026, 6, 30), apply=True
    )
    assert rep["healed"] == []
    assert rep["repaired"] == []
    assert rep["applied"] is False
    doc = json.loads(epath.read_text())
    b30 = {b["date"]: b for b in doc["daily"]}["2026-06-30"]
    # Untouched: the drifted bar is preserved byte-for-byte.
    assert b30["open_equity"] == 100190.22
    assert b30["close_equity"] == 100199.22


# ─── root-cause simulation: the stale-restore in a sandbox ──────────────────────


def test_stale_restore_incident_then_heal_end_to_end(tmp_path):
    """Reproduce the ROOT CAUSE in a sandbox and prove the heal fixes it.

    Simulate: a good curve (06-22..06-29 evidenced) is CLOBBERED by a stale
    committed copy (only 06-22..06-26), then a later cycle appends 06-30 onto the
    stale tail. The self-heal must recover 06-27/28/29 and re-continuous the track.
    """
    logs = tmp_path / "logs"
    data = tmp_path / "data"
    equities = {
        date(2026, 6, 22): 100150.66, date(2026, 6, 23): 100165.61,
        date(2026, 6, 24): 100170.40, date(2026, 6, 25): 100180.31,
        date(2026, 6, 26): 100190.22, date(2026, 6, 27): 100201.66,
        date(2026, 6, 28): 100212.99, date(2026, 6, 29): 100224.36,
        date(2026, 6, 30): 100199.22,
    }
    for d, eq in equities.items():
        _write_cycle_log(logs, d, equity=eq)

    # STALE-RESTORE state: only through 06-26, plus a 06-30 bar appended onto the
    # stale base (open drifted, yield real) — exactly what the incident produced.
    prev = 100134.79
    stale = []
    for d in [date(2026, 6, 22), date(2026, 6, 23), date(2026, 6, 24),
              date(2026, 6, 25), date(2026, 6, 26)]:
        stale.append(_bar(d.isoformat(), prev, equities[d]))
        prev = equities[d]
    stale.append(
        _bar("2026-06-30", 100190.22, 100199.22, daily_yield_usd=8.9971, apy_today=3.28)
    )
    epath = _write_equity(data, stale)

    before = evidenced_dates(json.loads(epath.read_text())["daily"],
                             paper_start=PAPER_START, today=date(2026, 6, 30))
    assert "2026-06-27" not in before and len(before) == 6

    rep = sh.heal_track(
        equity_path=epath, logs_dir=logs, today=date(2026, 6, 30), apply=True
    )
    doc = json.loads(epath.read_text())
    after = evidenced_dates(doc["daily"], paper_start=PAPER_START, today=date(2026, 6, 30))

    # Continuous 06-22..06-30, 9 evidenced days.
    assert after == [
        "2026-06-22", "2026-06-23", "2026-06-24", "2026-06-25", "2026-06-26",
        "2026-06-27", "2026-06-28", "2026-06-29", "2026-06-30",
    ]
    assert sorted(rep["healed"]) == ["2026-06-27", "2026-06-28", "2026-06-29"]
    # Fully continuous chain: every evidenced open == prior evidenced close.
    ev = [b for b in doc["daily"] if b.get("evidenced")]
    for prev_b, cur_b in zip(ev, ev[1:]):
        assert abs(cur_b["open_equity"] - prev_b["close_equity"]) <= 0.02


def test_heal_missing_file_is_noop(tmp_path):
    rep = sh.heal_track(
        equity_path=tmp_path / "data" / "nope.json",
        logs_dir=tmp_path / "logs",
        today=date(2026, 6, 30),
        apply=True,
    )
    assert rep["healed"] == []
    assert rep["applied"] is False
