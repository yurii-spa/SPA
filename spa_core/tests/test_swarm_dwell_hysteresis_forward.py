"""Tests for spa_core/strategy_lab/swarm/dwell_hysteresis_forward.py (idea #36 control, forward).

Every latch test is a positive control on the rule itself; the no-backtest tests are class-Y1
protection by construction (backtest rows must be UNREPRESENTABLE in this book, not just unused).
"""
# FROZEN-DATE-OK: the dates here are pure panel-axis labels — the module compares an explicit
# `as_of` against panel dates only (no wall clock, no TTL/window vs now anywhere), and every
# test passes `as_of` explicitly, so nothing in this file can rot as the calendar moves.
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from spa_core.strategy_lab.swarm import dwell_hysteresis_forward as dh


# ── fixtures: synthetic 10-book forward panel ──────────────────────────────────────────────────
def _dates(n: int, start_day: int = 1) -> list[str]:
    assert n + start_day - 1 <= 61
    out = []
    for d in range(start_day, start_day + n):
        if d <= 30:
            out.append(f"2026-06-{d:02d}")
        else:
            out.append(f"2026-07-{d - 30:02d}")
    return out


def _write_book(panel_dir: Path, book: str, rows: list[tuple[str, float, str]]) -> None:
    """rows: (date, mtm_today_pct, phase)."""
    path = panel_dir / book / "realized_series.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as fh:
        for date, mtm, phase in rows:
            fh.write(json.dumps({"date": date, "mtm_today_pct": mtm, "phase": phase,
                                 "equity_usd": 100_000.0, "is_advisory": True}) + "\n")


def _build_panel(tmp_path: Path, n_days: int, mtm_pct: float = 0.02,
                 backtest_prefix: bool = True) -> Path:
    """All 10 expected books, `n_days` forward rows each (+ noisy backtest bars to ignore)."""
    panel_dir = tmp_path / "aggressive_lab"
    ds = _dates(n_days)
    for book in dh.EXPECTED_BOOKS:
        rows: list[tuple[str, float, str]] = []
        if backtest_prefix:
            rows += [("2026-01-01", -35.0, "backtest"), ("2026-01-02", 40.0, "backtest")]
        rows += [(d, mtm_pct, "forward") for d in ds]
        _write_book(panel_dir, book, rows)
    return panel_dir


# ── the latch rule itself (synthetic, unit level) ──────────────────────────────────────────────
def test_latch_reenters_only_after_two_consecutive_up_days():
    # signal fires once (day 2) and clears; +1 day alone, and +1 then − day, must NOT re-enter
    rets = [0.01, 0.01, -0.05, 0.01, -0.01, 0.01, 0.01, 0.01]
    defend = [False, False, True, False, False, False, False, False]
    w = dh.overlay_weights(rets, defend, dh.DWELL_K)
    #        d0   d1   d2(out) d3    d4    d5    d6    d7(2 up days confirmed through t-1)
    assert w == [1.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]
    # the flag-only baseline came straight back on day 3 — the latch is what held out d3..d6
    assert dh.overlay_weights(rets, defend, None) == [1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 1.0, 1.0]


def test_latch_one_up_day_then_down_stays_out():
    rets = [0.01, -0.04, 0.02, -0.01, 0.02, -0.01, 0.02, 0.02, 0.01]
    defend = [False, True, False, False, False, False, False, False, False]
    w = dh.overlay_weights(rets, defend, dh.DWELL_K)
    # up/down alternation never yields 2 consecutive up days until d7 (r5? no: r6,r7 > 0 → d8 in)
    assert w == [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0]


def test_latch_live_trigger_rearms_despite_two_up_days():
    rets = [0.01, -0.03, 0.01, 0.01, 0.01]
    defend = [False, True, True, True, True]  # trigger still asserted on the release day
    w = dh.overlay_weights(rets, defend, dh.DWELL_K)
    assert w == [1.0, 0.0, 0.0, 0.0, 0.0]  # an up-print never overrules a live trigger


def test_latch_requires_evidence_k_below_one_refused():
    with pytest.raises(ValueError):
        dh.overlay_weights([0.01], [False], 0)


def test_latch_is_causal_shock_moves_exposure_next_day_only():
    # identical prefixes, shock on day i: weights through day i must be identical
    calm = [0.001] * 40
    shocked = list(calm)
    shocked[35] = -0.10
    d_calm = dh.sig_ecdr(calm)
    d_shk = dh.sig_ecdr(shocked)
    w_calm = dh.overlay_weights(calm, d_calm, dh.DWELL_K)
    w_shk = dh.overlay_weights(shocked, d_shk, dh.DWELL_K)
    assert w_calm[:36] == w_shk[:36]  # day 35 itself unmoved — decided from t-1 info


# ── the signal (warm-up fail-closed) ───────────────────────────────────────────────────────────
def test_signal_disarmed_before_slow_window():
    rets = [-0.05] * dh.ECDR_SLOW  # brutal decline, but not enough history
    assert dh.sig_ecdr(rets) == [False] * dh.ECDR_SLOW


def test_signal_fires_on_sustained_decline_after_warmup():
    rets = [0.001] * 40 + [-0.02] * 15
    flags = dh.sig_ecdr(rets)
    assert not any(flags[:dh.ECDR_SLOW])
    assert any(flags)  # the slow exit signal does fire once the trend is measurable


def test_params_pinned_to_registry_entry_36():
    # #36's numbers exist for ecdr#23(10/30)+dwell(k=2) ONLY; a silent change is a new experiment
    assert (dh.ECDR_FAST, dh.ECDR_SLOW, dh.DWELL_K) == (10, 30, 2)


# ── POSITIVE CONTROL: latch removed ⇒ identical to baseline through the FULL pipeline ──────────
def test_latch_removed_pipeline_equals_baseline_exactly():
    import random
    rng = random.Random(36)
    dates = _dates(60)
    panel = {b: {d: rng.uniform(-0.03, 0.03) for d in dates} for b in dh.EXPECTED_BOOKS}
    no_latch = {b: dh.overlay_weights([panel[b][d] for d in dates],
                                      dh.sig_ecdr([panel[b][d] for d in dates]), None)
                for b in panel}
    base_w = dh._arm_weights(dates, panel, None)
    assert no_latch == base_w
    arms = dh.compute_arms(dates, panel)
    eq_no_latch = dh._portfolio_equity(dates, panel, no_latch)
    assert round(eq_no_latch[-1], 2) == arms["baseline"]["equity_usd"]
    # …and the control is not vacuous: with the latch ON the dwell arm actually differs here
    assert arms["dwell"]["equity_usd"] != arms["baseline"]["equity_usd"]


def test_warmup_all_arms_equal_by_construction():
    dates = _dates(20)  # < ECDR_SLOW: signal disarmed, latch has nothing to hold
    panel = {b: {d: (-0.01 if i % 3 else 0.02) for i, d in enumerate(dates)}
             for b in dh.EXPECTED_BOOKS}
    arms = dh.compute_arms(dates, panel)
    assert (arms["raw"]["equity_usd"] == arms["baseline"]["equity_usd"]
            == arms["dwell"]["equity_usd"])
    assert arms["dwell"]["books_out_today"] == [] and arms["dwell"]["latched_out_today"] == []


# ── forward tick: fail-closed, append-only, idempotent, hash-chained ───────────────────────────
def test_tick_tracking_writes_book_line_and_status(tmp_path):
    panel_dir = _build_panel(tmp_path, 5)
    out_dir = tmp_path / "swarm"
    doc = dh.run_forward_tick(panel_dir, out_dir, as_of=_dates(5)[-1])
    assert doc["state"] == "TRACKING" and doc["book_appended"] is True
    assert doc["is_advisory"] is True and doc["outside_riskpolicy"] is True
    assert doc["signal_armed"] is False  # 5 days < 30 — honestly disarmed
    lines = [json.loads(l) for l in (out_dir / dh.BOOK_NAME).read_text().splitlines()]
    assert len(lines) == 1
    row = lines[0]
    assert row["status"] == "tracking" and row["phase"] == "forward"
    assert row["is_advisory"] is True and row["outside_riskpolicy"] is True
    assert row["arms"]["dwell"]["equity_usd"] > 0
    status = json.loads((out_dir / dh.STATUS_NAME).read_text())
    assert status["state"] == "TRACKING"


def test_tick_no_feed_for_day_is_no_data_not_invention(tmp_path):
    panel_dir = _build_panel(tmp_path, 5)
    out_dir = tmp_path / "swarm"
    doc = dh.run_forward_tick(panel_dir, out_dir, as_of="2026-07-15")  # beyond the panel
    assert doc["state"] == "NO_DATA" and doc["book_appended"] is True
    row = json.loads((out_dir / dh.BOOK_NAME).read_text().splitlines()[-1])
    assert row["status"] == "no_data" and row["date"] == "2026-07-15"
    assert "arms" not in row  # no invented numbers on a day with no live feed
    assert doc["last_feed_date"] == _dates(5)[-1]


def test_tick_missing_book_is_no_data_fail_closed(tmp_path):
    panel_dir = _build_panel(tmp_path, 5)
    # one expected book loses its forward rows entirely (file gone)
    (panel_dir / "susde_dn" / "realized_series.jsonl").unlink()
    doc = dh.run_forward_tick(panel_dir, tmp_path / "swarm", as_of=_dates(5)[-1])
    assert doc["state"] == "NO_DATA" and "susde_dn" in doc["missing_books"]
    row = json.loads((tmp_path / "swarm" / dh.BOOK_NAME).read_text().splitlines()[-1])
    assert row["status"] == "no_data" and "arms" not in row


def test_tick_idempotent_per_day_and_appends_next_day(tmp_path):
    panel_dir = _build_panel(tmp_path, 6)
    out_dir = tmp_path / "swarm"
    ds = _dates(6)
    d1 = dh.run_forward_tick(panel_dir, out_dir, as_of=ds[4])
    d2 = dh.run_forward_tick(panel_dir, out_dir, as_of=ds[4])  # same day again
    assert d1["book_appended"] is True and d2["book_appended"] is False
    assert len((out_dir / dh.BOOK_NAME).read_text().splitlines()) == 1
    d3 = dh.run_forward_tick(panel_dir, out_dir, as_of=ds[5])
    assert d3["book_appended"] is True
    lines = [json.loads(l) for l in (out_dir / dh.BOOK_NAME).read_text().splitlines()]
    assert [r["date"] for r in lines] == [ds[4], ds[5]]


def test_tick_refuses_out_of_order_append(tmp_path):
    panel_dir = _build_panel(tmp_path, 6)
    out_dir = tmp_path / "swarm"
    ds = _dates(6)
    dh.run_forward_tick(panel_dir, out_dir, as_of=ds[5])
    doc = dh.run_forward_tick(panel_dir, out_dir, as_of=ds[2])  # older day after a newer line
    assert doc["state"] == "REFUSED_OUT_OF_ORDER" and doc["book_appended"] is False
    assert len((out_dir / dh.BOOK_NAME).read_text().splitlines()) == 1


def test_book_hash_chain_is_valid_and_links_across_days(tmp_path):
    panel_dir = _build_panel(tmp_path, 6)
    out_dir = tmp_path / "swarm"
    for d in _dates(6)[3:]:
        dh.run_forward_tick(panel_dir, out_dir, as_of=d)
    prev = "0" * 64
    lines = (out_dir / dh.BOOK_NAME).read_text().splitlines()
    assert len(lines) == 3
    for line in lines:
        rec = json.loads(line)
        assert rec["prev_hash"] == prev
        body = dict(rec)
        claimed = body.pop("hash")
        assert claimed == hashlib.sha256(
            (prev + json.dumps(body, sort_keys=True)).encode()).hexdigest()
        prev = claimed


# ── NO BACKTEST MODE — class-Y1 protection by construction ─────────────────────────────────────
def test_loader_backtest_rows_are_unrepresentable(tmp_path):
    panel_dir = tmp_path / "aggressive_lab"
    _write_book(panel_dir, "susde_dn", [
        ("2026-05-01", -80.0, "backtest"),   # phase-glue phantom day
        ("2026-06-01", 0.5, "forward"),
    ])
    series = dh._load_forward_returns(panel_dir / "susde_dn" / "realized_series.jsonl")
    assert series == {"2026-06-01": pytest.approx(0.005)}


def test_backtest_only_book_yields_no_track_ever(tmp_path):
    panel_dir = tmp_path / "aggressive_lab"
    for book in dh.EXPECTED_BOOKS:  # 853-row backtest histories, zero forward rows
        _write_book(panel_dir, book, [(d, 1.0, "backtest") for d in _dates(20)])
    doc = dh.run_forward_tick(panel_dir, tmp_path / "swarm", as_of=_dates(20)[-1])
    assert doc["state"] == "NO_DATA"
    assert sorted(doc["missing_books"]) == sorted(dh.EXPECTED_BOOKS)
    row = json.loads((tmp_path / "swarm" / dh.BOOK_NAME).read_text().splitlines()[-1])
    assert row["status"] == "no_data"  # a backtest can never masquerade as forward track


def test_module_exposes_no_backtest_or_replay_entry_point():
    public = [n for n in dir(dh) if not n.startswith("_")]
    assert not [n for n in public if "backtest" in n.lower() or "replay" in n.lower()]
    # main() takes no arguments at all — there is no mode to select
    import inspect
    assert inspect.signature(dh.main).parameters == {}
    # and the module never even reads argparse/sys.argv (no hidden CLI mode)
    src = Path(dh.__file__).read_text()
    assert "argparse" not in src and "sys.argv" not in src


def test_tick_forward_window_ignores_backtest_dates(tmp_path):
    panel_dir = _build_panel(tmp_path, 5, backtest_prefix=True)
    doc = dh.run_forward_tick(panel_dir, tmp_path / "swarm", as_of=_dates(5)[-1])
    assert doc["state"] == "TRACKING"
    assert doc["window"]["start"] == _dates(5)[0]  # 2026-01 backtest bars never enter the window
    assert doc["common_days"] == 5


# ═══════════════════════════════════════════════════════════════════════════
# Требование владельца 2026-08-08 (карточка `own-rnd-duty-is-concentration-adr055`,
# подтверждено вместе с вариантом A): каждое плечо обязано писать фактическую
# концентрацию и долю времени «выключено» КАЖДЫЙ ДЕНЬ.
#
# Зачем: через 30 дней форварда без этих двух чисел нельзя отличить эффект
# правила от премии за размер позиций. Замер #46 (2026-08-08) показал, что
# разница между потолками 20/25/30 % — целиком размен «доходность против
# хвоста», поэтому без концентрации в логе форвардный результат не читается.
# ═══════════════════════════════════════════════════════════════════════════

def _arms_fixture():
    dates = _dates(40)
    # Панель хранит ДНЕВНУЮ доходность в процентах (mtm_today_pct), а не NAV.
    # NAV-подобные значения дали бы +100 %/день и OverflowError в годовом
    # пересчёте — свойство метрики, не предмет теста.
    panel = {
        "book_a": {d: 0.02 for d in dates},
        "book_b": {d: (-0.01 if i % 3 else 0.03) for i, d in enumerate(dates)},
        "book_c": {d: 0.01 for d in dates},
    }
    return dh.compute_arms(dates, panel)


def test_every_arm_reports_concentration():
    for arm, view in _arms_fixture().items():
        assert "concentration_pct" in view, f"плечо {arm} не пишет концентрацию"


def test_every_arm_reports_duty_out():
    for arm, view in _arms_fixture().items():
        assert "duty_out_pct" in view, f"плечо {arm} не пишет долю «выключено»"


def test_raw_arm_is_never_out_and_says_so():
    """Контроль в обратную сторону: у raw доля «выключено» обязана быть 0."""
    raw = _arms_fixture()["raw"]
    assert raw["duty_out_pct"] == 0.0
    assert raw["concentration_pct"] == pytest.approx(100.0 / 3, abs=0.01)


def test_values_are_in_percent_not_fraction():
    """Единицы — проценты. Дробь 0.33 вместо 33 % читалась бы как «всё хорошо»."""
    for arm, view in _arms_fixture().items():
        c = view["concentration_pct"]
        if c is not None:
            assert c > 1.0, f"{arm}: концентрация похожа на долю, а не на проценты"
            assert c <= 100.0 + 1e-9


def test_all_books_out_gives_none_not_zero():
    """Все книги выключены ⇒ None. «Ноль процентов» — другое утверждение."""
    assert dh._largest_position_pct({"a": [0.0], "b": [0.0]}, ["a", "b"], -1) is None


def test_duty_counts_book_days_not_days():
    """Доля считается по книго-дням: одна книга вне рынка из трёх = 33 %, не 100 %."""
    w = {"a": [0.0, 0.0], "b": [1.0, 1.0], "c": [1.0, 1.0]}
    assert dh._duty_out_pct(w, ["a", "b", "c"], 2) == pytest.approx(100.0 / 3, abs=0.01)


# ── оборот рядом с доходностью (задание по записи #48) ────────────────────────

def test_every_arm_reports_turnover_per_year():
    """Без оборота нельзя сказать, не съеден ли эдж издержками — а у #36 он и так
    net-of-cost НИЖЕ raw (17.62 % против 17.94 %)."""
    for arm, view in _arms_fixture().items():
        assert "turnover_per_year" in view, f"плечо {arm} не пишет оборот за год"


def test_raw_arm_turns_over_nothing():
    """Контроль в обратную сторону: у raw оборот обязан быть 0, а не отсутствовать."""
    assert _arms_fixture()["raw"]["turnover_per_year"] == 0.0


def test_turnover_counts_moved_capital_not_switches():
    """Σ|Δw|, а НЕ число переключений: одна книга из двух, вышедшая один раз за 365 дней."""
    w = {"a": [1.0] * 365, "b": [1.0] + [0.0] * 364}
    assert dh._turnover_per_year(w, ["a", "b"], 365) == pytest.approx(1.0, abs=1e-6)


def test_turnover_needs_two_days_to_exist():
    assert dh._turnover_per_year({"a": [1.0]}, ["a"], 1) is None
