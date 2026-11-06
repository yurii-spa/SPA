"""Контроли прибора #154 FMP (`scripts/edge_frozen_mark_provenance.py`).

Каждый тест — ПОЛОЖИТЕЛЬНЫЙ или ОТРИЦАТЕЛЬНЫЙ контроль на один род вердикта: прибор,
который умеет только говорить «это не наблюдение», украшение. Поэтому у каждого рода
здесь есть сцена, где он СРАБАТЫВАЕТ, и сцена, где он МОЛЧИТ.

# FROZEN-DATE-OK: injected-clock — даты сцен являются ПРЕДМЕТОМ (это содержимое
# forward-блока), а момент замера передаётся прибору ВХОДОМ `now=NOW` / `--now`; ни одна
# проверка здесь не спрашивает календарь у стенных часов.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import datetime
import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime.date(2026, 11, 6)          # момент замера — ВХОД прибора, а не окружение
SCENE_START = datetime.date(2026, 8, 5)   # предмет: первая дата forward-блока сцены


def _load():
    spec = importlib.util.spec_from_file_location(
        "edge_frozen_mark_provenance", ROOT / "scripts" / "edge_frozen_mark_provenance.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


FMP = _load()


# ── помощники сцены ───────────────────────────────────────────────────────────────────────

def _rows(marks, *, sources=None, start=SCENE_START, drop_key=False):
    """marks[i] — значение mtm_today_pct дня i; sources[i] — его mtm_source (None ⇒ null)."""
    out = []
    for i, m in enumerate(marks):
        d = (start + datetime.timedelta(days=i)).isoformat()
        row = {"date": d, "phase": "forward", "equity_usd": 100_000.0 + i,
               "mtm_source": (sources[i] if sources else None)}
        if not drop_key:
            row["mtm_today_pct"] = m
        out.append(row)
    return out


def _write_book(root: Path, book: str, rows, *, backtest_rows=0):
    d = root / book
    d.mkdir(parents=True, exist_ok=True)
    lines = []
    for i in range(backtest_rows):
        lines.append(json.dumps({"date": f"2024-07-{i+1:02d}", "phase": "backtest",
                                 "equity_usd": 100_000.0, "mtm_today_pct": 0.5,
                                 "mtm_source": "realized_backtest_series"}))
    lines += [json.dumps(r) for r in rows]
    (d / "realized_series.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


# ── §1 роды вердикта: у каждого своя сцена, и они НЕ взаимозаменяемы ─────────────────────

def test_source_null_everywhere_is_NO_MARK_not_a_measured_zero():
    c = FMP.classify_series(_rows([0.0] * 20))
    assert c["verdict"] == FMP.NO_MARK
    assert c["n_declared"] == 0 and c["n_no_mark"] == 20
    assert c["measurable"] is False


def test_declared_source_over_an_all_zero_series_is_its_OWN_verdict():
    """Это и есть дефект: провенанс ОБЪЯВЛЕН, а разность день-к-дню тождественно нулевая."""
    c = FMP.classify_series(_rows([0.0] * 20, sources=["realized_backtest_series"] * 20))
    assert c["verdict"] == FMP.DECLARED_ALL_ZERO
    assert c["n_declared"] == 20 and c["n_declared_zero"] == 20
    # и он НЕ сливается с «марки нет»
    assert c["verdict"] != FMP.NO_MARK


def test_declared_constant_nonzero_level_is_not_an_observation():
    """Уровень, применённый повторно, печатает НЕнулевые числа и выглядит живее всех."""
    c = FMP.classify_series(_rows([0.021092] * 20, sources=["realized_backtest_series"] * 20))
    assert c["verdict"] == FMP.DECLARED_CONSTANT
    assert c["n_declared_nonzero"] == 20
    assert c["distinct_declared"] == 1


def test_a_REAL_daily_path_is_called_an_OBSERVATION_the_control_in_the_other_direction():
    marks = [round(0.01 * (i + 1) - 0.1, 6) for i in range(30)]   # 30 различных значений
    c = FMP.classify_series(_rows(marks, sources=["realized_backtest_series"] * 30))
    assert c["verdict"] == FMP.OBSERVED, c
    assert c["measurable"] is True
    assert c["distinct_fraction"] == 1.0


def test_absent_field_is_a_THIRD_OUTCOME_never_a_zero():
    c = FMP.classify_series(_rows([0.0] * 20, drop_key=True))
    assert c["verdict"] == FMP.FIELD_ABSENT
    assert c["n_declared"] is None          # не 0: ничего не измерено
    assert c["n_declared_zero"] is None


def test_unreadable_series_is_not_an_empty_series():
    assert FMP.classify_series(None, unreadable_reason="x")["verdict"] == "x"
    assert FMP.classify_series(None)["verdict"] == FMP.UNREADABLE
    assert FMP.classify_series([])["verdict"] == FMP.NO_FORWARD_ROWS


def test_a_series_shorter_than_the_declared_minimum_refuses_to_judge_constancy():
    short = FMP.MIN_ROWS_FOR_CONSTANCY_VERDICT - 1
    c = FMP.classify_series(_rows([0.5] * short, sources=["s"] * short))
    assert c["verdict"] == FMP.TOO_SHORT


def test_every_verdict_name_is_registered():
    """Новый род без регистрации — немой вердикт, который читатель не отличит от прочих."""
    for rows in ([], None, _rows([0.0] * 20), _rows([0.0] * 20, sources=["s"] * 20),
                 _rows([0.1] * 20, sources=["s"] * 20), _rows([0.0] * 20, drop_key=True)):
        assert FMP.classify_series(rows)["verdict"] in FMP.VERDICTS


# ── §2 однодневная экскурсия: отпечаток ШАГА, а не пути ──────────────────────────────────

def test_single_day_excursion_is_detected():
    marks = [0.021092] * 10 + [-5.243446] + [0.021092] * 10
    c = FMP.classify_series(_rows(marks, sources=["realized_backtest_series"] * 21))
    assert c["n_single_day_excursions"] == 1
    e = c["single_day_excursions"][0]
    assert e["value"] == -5.243446 and e["baseline"] == 0.021092


def test_a_monotone_real_path_has_NO_excursions_negative_control():
    marks = [round(0.001 * i, 6) for i in range(20)]
    c = FMP.classify_series(_rows(marks, sources=["s"] * 20))
    assert c["n_single_day_excursions"] == 0


def test_a_step_that_does_NOT_return_is_not_an_excursion():
    marks = [0.01] * 10 + [0.02] * 10
    c = FMP.classify_series(_rows(marks, sources=["s"] * 20))
    assert c["n_single_day_excursions"] == 0
    assert len(c["change_points"]) == 1


# ── §3 общий шаг: порог ОБЪЯВЛЕН и соблюдается ───────────────────────────────────────────

def _census_of(books: dict) -> dict:
    return {"books": {b: FMP.classify_series(r) for b, r in books.items()}}


def test_three_books_changing_on_one_day_is_a_shared_step():
    marks = [0.01] * 5 + [-1.0] + [0.01] * 5
    cen = _census_of({f"b{i}": _rows(marks, sources=["s"] * 11) for i in range(3)})
    steps = FMP.shared_step_days(cen)
    assert steps and steps[0]["n_books"] == 3
    assert len(steps[0]["reverted_next_change"]) == 3


def test_two_books_is_BELOW_the_declared_threshold_and_is_not_reported():
    assert FMP.SHARED_STEP_MIN_BOOKS == 3
    marks = [0.01] * 5 + [-1.0] + [0.01] * 5
    cen = _census_of({f"b{i}": _rows(marks, sources=["s"] * 11) for i in range(2)})
    assert FMP.shared_step_days(cen) == []


def test_books_changing_on_DIFFERENT_days_are_not_a_shared_step():
    cen = _census_of({
        f"b{i}": _rows([0.01] * (3 + i) + [-1.0] + [0.01] * (7 - i), sources=["s"] * 11)
        for i in range(3)})
    assert FMP.shared_step_days(cen) == []


# ── §4 перепись: отказ, а не ноль ────────────────────────────────────────────────────────

def test_census_REFUSES_when_not_a_single_book_is_readable(tmp_path):
    with pytest.raises(FMP.Unmeasured):
        FMP.mark_source_census(tmp_path / "nothing", books=["a", "b"])


def test_census_counts_observed_books_and_names_them(tmp_path):
    _write_book(tmp_path, "alive", _rows([round(0.01 * i, 6) for i in range(20)],
                                         sources=["s"] * 20), backtest_rows=3)
    _write_book(tmp_path, "frozen", _rows([0.0] * 20, sources=["s"] * 20))
    cen = FMP.mark_source_census(tmp_path, books=["alive", "frozen", "missing"])
    # «missing» в число ПРОЧИТАННЫХ не входит — и это третий исход, а не нулевая книга
    assert cen["n_read"] == 2
    assert cen["observed_books"] == ["alive"]
    assert cen["n_observed"] == 1
    assert cen["books"]["missing"]["verdict"].startswith("НЕ ИЗМЕРЕНО")
    # backtest-строки в forward-перепись не попадают
    assert cen["books"]["alive"]["n_rows"] == 20


def test_forward_filter_ignores_backtest_rows(tmp_path):
    _write_book(tmp_path, "b", _rows([0.0] * 12), backtest_rows=50)
    rows, reason = FMP.read_forward_rows(tmp_path, "b")
    assert reason == "" and len(rows) == 12


def test_a_book_with_only_backtest_rows_is_NO_FORWARD_ROWS_not_unreadable(tmp_path):
    _write_book(tmp_path, "b", [], backtest_rows=5)
    rows, reason = FMP.read_forward_rows(tmp_path, "b")
    assert rows == [] and reason == FMP.NO_FORWARD_ROWS


def test_a_malformed_line_makes_the_book_UNREADABLE_not_empty(tmp_path):
    d = tmp_path / "b"
    d.mkdir(parents=True)
    (d / "realized_series.jsonl").write_text('{"phase": "forward"\n', encoding="utf-8")
    rows, reason = FMP.read_forward_rows(tmp_path, "b")
    assert rows is None and reason.startswith(FMP.UNREADABLE)


# ── §5 момент замера — ВХОД, а не стенные часы (ADR-897) ─────────────────────────────────

def test_parse_now_accepts_the_injected_moment():
    assert FMP.parse_now("2026-11-06") == NOW


def test_parse_now_REFUSES_an_unparseable_value_instead_of_falling_back_to_the_clock():
    for bad in ("", "вчера", "2026-13-40", None.__class__.__name__):
        with pytest.raises(FMP.Unmeasured):
            FMP.parse_now(bad)


def test_parse_now_without_an_argument_is_the_wall_clock_and_that_is_the_DEFAULT_only():
    assert FMP.parse_now(None) == datetime.datetime.now(datetime.timezone.utc).date()


def test_staleness_is_measured_against_the_INJECTED_now(tmp_path):
    ds = tmp_path / "pendle_pt_history.json"
    ds.write_text(json.dumps({
        "markets": {"M": {"kind": "stable_synth",
                          "series": [{"date": "2026-07-05", "implied_yield": 0.05},
                                     {"date": "2026-07-04", "implied_yield": 0.05}]}}}),
        encoding="utf-8")
    st = FMP.mark_input_staleness(NOW, ds)
    assert st["measured"] is True
    assert st["last"] == "2026-07-05"
    assert st["stale_days_vs_now"] == (NOW - datetime.date(2026, 7, 5)).days
    # и он ДВИГАЕТСЯ вместе с переданным моментом — то есть вход действительно доходит
    later = FMP.mark_input_staleness(NOW + datetime.timedelta(days=10), ds)
    assert later["stale_days_vs_now"] == st["stale_days_vs_now"] + 10


def test_a_missing_dataset_is_a_THIRD_OUTCOME_not_a_fresh_one(tmp_path):
    st = FMP.mark_input_staleness(NOW, tmp_path / "absent.json")
    assert st["measured"] is False
    assert "НЕ ИЗМЕРЕНО" in st["reason"]
    assert "stale_days_vs_now" not in st


def test_a_dataset_without_dated_points_is_a_THIRD_OUTCOME(tmp_path):
    ds = tmp_path / "d.json"
    ds.write_text(json.dumps({"markets": {"M": {"kind": "stable_synth", "series": []}}}),
                  encoding="utf-8")
    st = FMP.mark_input_staleness(NOW, ds)
    assert st["measured"] is False and "НЕ ИЗМЕРЕНО" in st["reason"]


# ── §6 exit_nav (второй вопрос заказа) ───────────────────────────────────────────────────

def test_exit_nav_absence_is_reported_with_the_neighbours_that_DO_exist(tmp_path):
    (tmp_path / "data" / "rates_desk").mkdir(parents=True)
    (tmp_path / "data" / "rates_desk" / "exit_nav.json").write_text("{}", encoding="utf-8")
    panel = tmp_path / "data" / "aggressive_lab"
    panel.mkdir(parents=True)
    e = FMP.exit_nav_presence(tmp_path, panel)
    assert e["panel_exit_nav_exists"] is False
    assert e["neighbours_that_exist"] == ["data/rates_desk/exit_nav.json"]


def test_exit_nav_presence_is_reported_when_the_file_IS_there(tmp_path):
    panel = tmp_path / "data" / "aggressive_lab"
    panel.mkdir(parents=True)
    (panel / "exit_nav.json").write_text("{}", encoding="utf-8")
    assert FMP.exit_nav_presence(tmp_path, panel)["panel_exit_nav_exists"] is True


# ── §7 причина, названная МЕХАНИЗМОМ кода ────────────────────────────────────────────────

def test_code_causes_names_the_anchor_that_the_harness_does_NOT_persist():
    """Претензия о РЕАЛЬНОМ дереве: якорь `_entry_eth` в сохраняемом наборе отсутствует.

    Если харнесс однажды начнёт его сохранять, этот тест покраснеет — и это ВЕРНО:
    вывод записи #154 перестанет быть правдой, и запись обязана это узнать."""
    cz = FMP.code_causes(None)
    ed = cz["books"]["eth_directional"]
    assert "_entry_eth" in ed["anchors"]
    assert ed["anchors_not_persisted"] == ["_entry_eth"]
    assert ed["anchors_not_persisted_read_by_mark"] == ["_entry_eth"]


def test_code_causes_names_the_anchor_that_blinds_the_KILL_gate():
    cz = FMP.code_causes(None)
    ln = cz["books"]["lrt_neutral"]
    assert ln["anchors_not_persisted"] == ["_entry_ratio"]
    assert ln["anchors_not_persisted_read_by_kill"] == ["_entry_ratio"]


def test_a_book_with_every_anchor_persisted_is_reported_CLEAN_negative_control():
    cz = FMP.code_causes(None)
    for sid in ("susde_dn", "pendle_yt_susde", "leverage_loop", "levered_restaking"):
        assert cz["books"][sid]["anchors_not_persisted"] == [], sid


def test_a_pure_accrual_book_is_reported_as_having_no_mark_hook_at_all():
    cz = FMP.code_causes(None)
    assert cz["books"]["points_farm"]["has_mark_hook"] is False
    assert cz["books"]["susde_dn"]["has_mark_hook"] is True


def test_code_causes_reads_the_kill_reason_from_the_state_when_given_one():
    state = {"books": {"lp_eth_stable": {"killed": True, "kill_reason": "fail-closed: x"}}}
    cz = FMP.code_causes(state)
    assert cz["books"]["lp_eth_stable"]["killed_in_state"] is True
    assert cz["books"]["lp_eth_stable"]["kill_reason_in_state"] == "fail-closed: x"
    # а книга, которой в состоянии нет, получает None, а не False
    assert cz["books"]["susde_dn"]["killed_in_state"] is None


# ── §8 CLI: код возврата различает «ответил» и «НЕ ИЗМЕРЕНО» ─────────────────────────────

def test_cli_returns_0_on_a_readable_scene(tmp_path, capsys):
    panel = tmp_path / "data" / "aggressive_lab"
    for b in FMP.PANEL_BOOKS:
        _write_book(panel, b, _rows([0.0] * 15, sources=["s"] * 15))
    rc = FMP.main(["--data-dir", str(panel), "--repo-root", str(tmp_path),
                   "--now", "2026-11-06", "--no-causes", "--no-staleness"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "ПЕРЕПИСЬ ИСТОЧНИКА МАРКИ" in out
    assert "НАБЛЮДЕНИЙ дневного пути среди 10 книг: 0" in out


def test_cli_returns_2_when_nothing_is_readable(tmp_path, capsys):
    rc = FMP.main(["--data-dir", str(tmp_path / "void"), "--repo-root", str(tmp_path),
                   "--now", "2026-11-06", "--no-causes", "--no-staleness"])
    assert rc == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


def test_cli_returns_2_on_an_unparseable_now(tmp_path):
    assert FMP.main(["--data-dir", str(tmp_path), "--repo-root", str(tmp_path),
                     "--now", "позавчера", "--no-causes", "--no-staleness"]) == 2


def test_cli_json_output_is_machine_readable(tmp_path, capsys):
    panel = tmp_path / "data" / "aggressive_lab"
    _write_book(panel, "susde_dn", _rows([0.0] * 15, sources=["s"] * 15))
    rc = FMP.main(["--data-dir", str(panel), "--repo-root", str(tmp_path),
                   "--now", "2026-11-06", "--no-causes", "--no-staleness", "--json"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["census"]["books"]["susde_dn"]["verdict"] == FMP.DECLARED_ALL_ZERO
    assert doc["now"] == "2026-11-06"


# ── §9 объявления прибора не дрейфуют молча ──────────────────────────────────────────────

def test_the_declared_threshold_is_the_one_the_verdict_uses():
    """Порог — объявление, а не вкус: сдвинь его, и вердикт обязан поехать за ним."""
    marks = [0.1, 0.2] * 10          # доля различных = 2/20 = 0.1
    c = FMP.classify_series(_rows(marks, sources=["s"] * 20))
    assert c["distinct_fraction"] == pytest.approx(0.1)
    assert c["verdict"] == FMP.DECLARED_CONSTANT
    marks2 = [round(i / 100, 6) for i in range(20)]
    assert FMP.classify_series(_rows(marks2, sources=["s"] * 20))["verdict"] == FMP.OBSERVED


def test_panel_books_list_matches_the_live_roster():
    """Книга, появившаяся в ростере и НЕ попавшая в перепись, — молчаливая дыра замера."""
    from spa_core.strategy_lab.aggressive_lab import roster as R
    assert sorted(FMP.PANEL_BOOKS) == sorted(R.roster_ids())
