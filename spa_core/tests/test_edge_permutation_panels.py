"""Контроли прибора #162 PERM (`scripts/edge_permutation_panels.py`).

Прибор отвечает «правило отбора не угадывает НИ НА ОДНОЙ из 120 панелей», и у такого ответа
есть ровно один способ быть ложным: прибор не умеет регистрировать попадание вообще. Поэтому
несущие проверки здесь — ПОЛОЖИТЕЛЬНЫЕ:

  • сцена, где правило угадывает пару ПО ПОСТРОЕНИЮ (две тихие книги и они же — наименьшие
    потери в каждом кризисе) ⇒ прибор обязан напечатать 3 попадания из 3;
  • боевой инвариантный ответ (одно различное значение на 120 панелях) обязан ПЕРЕСТАТЬ быть
    инвариантом, когда дрейфу возвращают вес (`--drift-scale`) — иначе инвариант есть свойство
    прибора, а не фикстуры.

Второй класс — ТРЕТИЙ ИСХОД (инв. #17): ничья на границе отбора, цензурированное восстановление
и отсутствие окна обязаны быть различимы, и ни одно из них не есть промах или ноль.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _ROOT / "scripts" / "edge_permutation_panels.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("edge_perm_under_test", _SCRIPT)
    assert spec and spec.loader, f"прибор не загружается: {_SCRIPT}"
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


perm = _load_module()
_fx = perm._fx
KEYS = ("eth_crash_2024_08", "usde_unwind_2025_10", "rseth_depeg_2026_04")


def _series(drift: float, hits: dict) -> list[dict]:
    """Ряд книги по ТОМУ ЖЕ генератору фикстуры — сцена не пишет свою арифметику."""
    return _fx._build_backtest_series({"daily_drift": drift, "window_hits": dict(hits)})


def _flat_hits(value: float) -> dict:
    return {k: value for k in KEYS}


# ── §0 состав панели ───────────────────────────────────────────────────────────────────────────
def test_books_are_the_five_with_a_backtest():
    books = perm.backtest_books()
    assert len(books) == 5
    assert "thin_new" not in books, "книга без бэктеста в складки входить не может"


def test_three_crises_make_three_folds():
    assert len(perm.crisis_keys()) == 3


def test_unknown_crisis_key_is_unmeasured():
    with pytest.raises(perm.Unmeasured):
        perm.crisis_bounds("нет_такого_кризиса")


# ── §1 перестановка панели ─────────────────────────────────────────────────────────────────────
def test_identity_permutation_reproduces_the_fixture_exactly():
    books = perm.backtest_books()
    panel = perm.permuted_panel(books, tuple(range(len(books))))
    for book in books:
        assert panel[book] == _fx._build_backtest_series(_fx._SPEC[book]), (
            "тождественная перестановка обязана дать РОВНО фикстуру")


def test_permutation_moves_the_crisis_vector_and_keeps_the_drift():
    books = perm.backtest_books()
    swapped = list(range(len(books)))
    swapped[0], swapped[1] = swapped[1], swapped[0]
    panel = perm.permuted_panel(books, swapped)
    donor = _fx._build_backtest_series(
        {"daily_drift": _fx._SPEC[books[0]]["daily_drift"],
         "window_hits": _fx._SPEC[books[1]]["window_hits"]})
    assert panel[books[0]] == donor, "книга обязана нести СВОЙ дрейф и ЧУЖИЕ потери"


def test_not_a_permutation_is_refused():
    books = perm.backtest_books()
    with pytest.raises(perm.Unmeasured):
        perm.permuted_panel(books, (0, 0, 1, 2, 3))


@pytest.mark.parametrize("scale", [0.0, -1.0])
def test_non_positive_drift_scale_is_refused(scale):
    books = perm.backtest_books()
    with pytest.raises(perm.Unmeasured):
        perm.permuted_panel(books, tuple(range(len(books))), scale)


# ── §2 отбор: ничья — это НЕ ИЗМЕРЕНО, а не алфавит ───────────────────────────────────────────
def test_lowest_two_are_picked():
    assert perm._pick_lowest({"a": 1.0, "b": 2.0, "c": 9.0}) == frozenset({"a", "b"})


def test_tie_at_the_selection_boundary_is_unmeasured():
    assert perm._pick_lowest({"a": 1.0, "b": 2.0, "c": 2.0}) is None, (
        "ничью нельзя разрывать по алфавиту: попадание стало бы свойством сортировки")


def test_tie_inside_the_picked_pair_still_picks():
    assert perm._pick_lowest({"a": 1.0, "b": 1.0, "c": 9.0}) == frozenset({"a", "b"})


def test_too_few_candidates_is_unmeasured():
    assert perm._pick_lowest({"a": 1.0, "b": 2.0}) is None, (
        "выбрать 2 из 2 — это не отбор, а переименование")


def test_censored_recovery_is_a_value_and_ties_with_another_censored():
    """`inf` — ЗНАЧЕНИЕ («не вернулась»), и две такие книги дают ничью, а не произвольную пару."""
    assert perm._pick_lowest({"a": float("inf"), "b": float("inf"), "c": 1.0}) is None


# ── §3 ряды: отсутствие наблюдения отличимо от нуля ───────────────────────────────────────────
def test_window_loss_without_the_window_is_none_not_zero():
    short = [{"date": "2024-07-01", "equity_usd": 100.0, "phase": "backtest"}]
    assert perm.window_loss(short, "rseth_depeg_2026_04") is None


def test_window_loss_is_the_trough_not_the_closing_mark():
    """Потеря окна — это ГЛУБИНА (минимум внутри), а не отметка на выходе из окна.

    Сцена различающая: книга проваливается на −10 % в середине окна и выходит из него на −1 %.
    Мера по закрытию объявила бы её почти целой — ровно то, за что инв. #8 требует показывать
    хвост, а не итог. Выжившая мутация «считать от последнего дня» (замер #162) закрыта здесь.
    """
    series = ([{"date": "2025-09-30", "equity_usd": 100.0}]
              + [{"date": f"2025-10-{d:02d}", "equity_usd": eq} for d, eq in
                 ((1, 100.0), (2, 95.0), (10, 90.0), (20, 95.0), (31, 99.0))])
    loss = perm.window_loss(series, "usde_unwind_2025_10")
    assert loss == pytest.approx(-0.10, abs=1e-9), (
        "мера по закрытию дала бы −0.01 и назвала провал мелким")


def test_window_loss_sign_is_negative_for_a_loss():
    series = _series(0.0, {"usde_unwind_2025_10": 0.10})
    loss = perm.window_loss(series, "usde_unwind_2025_10")
    assert loss is not None and loss < 0


def test_quiet_book_has_a_smaller_loss_than_a_loud_one():
    quiet = perm.window_loss(_series(0.0, {"usde_unwind_2025_10": 0.01}), "usde_unwind_2025_10")
    loud = perm.window_loss(_series(0.0, {"usde_unwind_2025_10": 0.25}), "usde_unwind_2025_10")
    assert quiet is not None and loud is not None and quiet > loud


def test_recovery_is_zero_when_the_book_never_went_below_its_peak():
    series = _series(0.001, {})            # дрейф без кризисных потерь
    assert perm.recovery_days(series, "usde_unwind_2025_10") == 0.0, (
        "«не уходила ниже пика» — измерено И равно нулю, это не пропуск")


def test_recovery_is_infinite_when_the_book_never_returns():
    series = _series(0.0, {"rseth_depeg_2026_04": 0.30})   # после окна роста нет
    assert perm.recovery_days(series, "rseth_depeg_2026_04") == float("inf")


def test_recovery_is_finite_when_the_book_climbs_back():
    series = _series(0.004, {"eth_crash_2024_08": 0.05})
    value = perm.recovery_days(series, "eth_crash_2024_08")
    assert value is not None and 0 < value < float("inf")


def test_recovery_without_pre_crisis_history_is_none():
    series = [p for p in _series(0.001, {"eth_crash_2024_08": 0.05})
              if p["date"] >= "2024-08-01"]
    assert perm.recovery_days(series, "eth_crash_2024_08") is None


def test_a_hole_in_the_series_does_not_become_a_zero_return():
    series = [{"date": "2024-07-01", "equity_usd": 100.0},
              {"date": "2024-07-02", "equity_usd": None},
              {"date": "2024-07-03", "equity_usd": 110.0}]
    assert perm.daily_returns(series) == [], (
        "пропуск разрывает ряд, а не печатает доход 0 % и прыжок +10 %")


# ── §4 ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: прибор УМЕЕТ регистрировать попадание ──────────────────────────
def _rigged_panel() -> dict:
    """Сцена, где правило угадывает ПО ПОСТРОЕНИЮ: две книги тихи и теряют меньше всех всегда."""
    return {
        "quiet_a": _series(0.0003, _flat_hits(0.002)),
        "quiet_b": _series(0.0003, _flat_hits(0.004)),
        "loud_c": _series(0.0003, {"eth_crash_2024_08": 0.10,
                                   "usde_unwind_2025_10": 0.12,
                                   "rseth_depeg_2026_04": 0.14}),
        "loud_d": _series(0.0003, {"eth_crash_2024_08": 0.16,
                                   "usde_unwind_2025_10": 0.18,
                                   "rseth_depeg_2026_04": 0.20}),
        "loud_e": _series(0.0003, {"eth_crash_2024_08": 0.22,
                                   "usde_unwind_2025_10": 0.24,
                                   "rseth_depeg_2026_04": 0.26}),
    }


def test_rigged_panel_is_guessed_in_all_three_folds():
    scores = perm.score_panel(_rigged_panel(), KEYS)
    assert scores["QUIET-N"] == {"hit": 3, "miss": 0, "unmeasured": 0}, (
        "прибор, не умеющий зарегистрировать попадание, отвечает о себе, а не о панели")
    assert scores["MES"]["hit"] >= 2


def test_rigged_panel_target_is_the_quiet_pair():
    assert perm.target_pair(_rigged_panel(), KEYS[0]) == frozenset({"quiet_a", "quiet_b"})


def test_rule_never_looks_into_the_held_out_window():
    """Если правило подсматривает в удержанный кризис, оно проверяет себя собой.

    Сцена: книга тиха ВЕЗДЕ, кроме удержанного окна, где она теряет больше всех. Правило по
    TRAIN обязано её ВЫБРАТЬ (она тихая на TRAIN), то есть промахнуться по цели.
    """
    panel = {
        "mole": _series(0.0003, {"eth_crash_2024_08": 0.001,
                                 "usde_unwind_2025_10": 0.001,
                                 "rseth_depeg_2026_04": 0.40}),
        "steady": _series(0.0003, _flat_hits(0.003)),
        "loud_c": _series(0.0003, _flat_hits(0.10)),
        "loud_d": _series(0.0003, _flat_hits(0.14)),
        "loud_e": _series(0.0003, _flat_hits(0.18)),
    }
    pick = perm.rule_quiet(panel, [KEYS[0], KEYS[1]], "rseth_depeg_2026_04")
    truth = perm.target_pair(panel, "rseth_depeg_2026_04")
    assert pick is not None and truth is not None
    assert "mole" in pick, "на TRAIN книга тиха — правило обязано её выбрать"
    assert "mole" not in truth, "в удержанном окне она теряет больше всех"
    assert pick != truth


def test_unmeasured_fold_is_not_counted_as_a_miss():
    """Панель из трёх одинаковых книг: цель — ничья, то есть НЕ ИЗМЕРЕНО, а не промах."""
    same = _series(0.0003, _flat_hits(0.05))
    panel = {"a": list(same), "b": list(same), "c": list(same)}
    scores = perm.score_panel(panel, KEYS)
    for rule in perm.RULES:
        assert scores[rule]["miss"] == 0
        assert scores[rule]["unmeasured"] == 3


# ── §5 нулевая гипотеза ────────────────────────────────────────────────────────────────────────
def test_null_share_matches_the_arithmetic_of_order_157():
    assert perm.null_probability(5, 3, 2) == pytest.approx(0.028, abs=1e-9)
    assert perm.null_probability(5, 1, 1) == pytest.approx(0.1, abs=1e-12)


def test_null_share_falls_as_more_folds_are_required():
    assert perm.null_probability(5, 3, 3) < perm.null_probability(5, 3, 2)


# ── §6 замер в целом: инвариант боевого ответа ПЕРЕСТАЁТ быть инвариантом под контролем ───────
def test_live_answer_is_invariant_across_every_permutation():
    res = perm.run(limit=None)
    assert res["panels"] == 120, "перестановок пяти книг ровно 5! = 120"
    assert res["distinct_hit_counts"]["QUIET-N"] == 1
    assert res["per_rule"]["QUIET-N"]["panels_with_min_hits"] == 0
    assert res["per_rule"]["QUIET-N"]["share"] == 0.0


def test_the_invariant_is_a_property_of_the_fixture_not_of_the_instrument():
    """НЕСУЩИЙ контроль: вернуть дрейфу вес — и ответ обязан ЗАШЕВЕЛИТЬСЯ."""
    res = perm.run(limit=None, drift_scale=10.0)
    assert res["distinct_hit_counts"]["MES"] > 1, (
        "прибор, чей ответ не меняется НИКОГДА, мерит себя")
    assert res["per_rule"]["MES"]["panels_with_min_hits"] > 0
    assert res["per_rule"]["CRP"]["panels_measured"] > 0, (
        "при ×1 CRP не измерим из-за ничьих `inf`; при ×10 он обязан заговорить")


def test_limit_keeps_the_real_panel_in_the_sample():
    res = perm.run(limit=5)
    assert res["panels"] == 5
    assert res["per_rule"]["QUIET-N"]["identity_panel"] is not None


def test_limit_below_one_is_unmeasured():
    with pytest.raises(perm.Unmeasured):
        perm.run(limit=0)


def test_fold_rate_is_none_when_nothing_was_measured():
    res = perm.run(limit=6)
    info = res["per_rule"]["CRP"]
    if info["folds_hit"] + info["folds_miss"] == 0:
        assert info["fold_hit_rate"] is None, "делить на ноль складок нельзя — это НЕ ИЗМЕРЕНО"
    else:
        assert 0.0 <= info["fold_hit_rate"] <= 1.0


def test_fold_rate_denominator_excludes_unmeasured_folds():
    """РАЗЛИЧАЮЩАЯ сцена для знаменателя: «не измерено» в нём занизило бы долю.

    `--drift-scale 40` — сцена, где у ОДНОГО правила есть и попадания, и неизмеримые складки
    одновременно (замер: CRP hit=3 · miss=20 · НЕ ИЗМЕРЕНО=13). Честная доля 3/23, подстановка
    дала бы 3/36 — и вывод «правило угадывает редко» оказался бы следствием слепоты прибора.
    """
    res = perm.run(limit=12, drift_scale=40.0)
    scenes = [i for i in res["per_rule"].values()
              if i["folds_hit"] > 0 and i["folds_unmeasured"] > 0]
    assert scenes, "сцена не обеспечила предпосылку: нужны и попадания, и НЕ ИЗМЕРЕНО"
    for info in scenes:
        honest = info["folds_hit"] / (info["folds_hit"] + info["folds_miss"])
        diluted = info["folds_hit"] / (info["folds_hit"] + info["folds_miss"]
                                       + info["folds_unmeasured"])
        assert info["fold_hit_rate"] == pytest.approx(honest, abs=1e-12)
        assert info["fold_hit_rate"] > diluted


# ── §7 CLI ─────────────────────────────────────────────────────────────────────────────────────
def test_cli_prints_the_measurement(capsys):
    assert perm.main(["--limit", "6"]) == 0
    out = capsys.readouterr().out
    assert "перестановочные панели" in out and "случайное ожидание" in out


def test_cli_json_carries_the_share(capsys):
    assert perm.main(["--limit", "6", "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["panels"] == 6 and "per_rule" in doc


def test_cli_returns_two_on_a_refused_input(capsys):
    assert perm.main(["--limit", "0"]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


def test_cli_explain_names_the_numbers_behind_a_tie(capsys):
    assert perm.main(["--limit", "2", "--explain"]) == 0
    out = capsys.readouterr().out
    assert "восстановление, дн" in out and "потеря в окне" in out


def test_cli_marks_a_non_live_drift_scale(capsys):
    assert perm.main(["--limit", "2", "--drift-scale", "10"]) == 0
    assert "КОНТРОЛЬНЫЙ, не боевой" in capsys.readouterr().out


def test_instrument_touches_no_data_dir(monkeypatch):
    """Предмет прибора — ФИКСТУРА: живой `data/` он не открывает вовсе."""
    opened: list[str] = []
    real_open = Path.open

    def spy(self, *a, **kw):           # noqa: ANN001
        opened.append(str(self))
        return real_open(self, *a, **kw)

    monkeypatch.setattr(Path, "open", spy)
    perm.run(limit=2)
    assert not [p for p in opened if "/data/" in p], f"прибор открыл data/: {opened[:3]}"
