"""Контроли прибора #157 IOB (`scripts/edge_independent_observation_budget.py`).

Предмет прибора — ТРИ разных вопроса (арифметика · складки фикстуры · бюджет реальной панели),
поэтому у каждого свой контроль в ОБЕ стороны: сцена, где вердикт срабатывает, и сцена, где он
НЕ должен. Положительный контроль складок — синтетическая панель, на которой правило отбора
ПО ПОСТРОЕНИЮ угадывает; отрицательный — настоящая фикстура, где оно не угадывает ни разу.

# FROZEN-DATE-OK: fixture-subject — ДАТЫ здесь являются ПРЕДМЕТОМ: это окна кризисов
# детерминированной фикстуры (`aggressive_lab/fixtures.py`) и даты синтетических сцен, то есть
# входные данные. Понятия СВЕЖЕСТИ на пути прибора нет: у него нет ни одной двери к стенным
# часам (ни `now()`, ни `today()`), поэтому сдвиг календаря не меняет ни один вердикт.
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


def _load():
    spec = importlib.util.spec_from_file_location(
        "edge_independent_observation_budget",
        ROOT / "scripts" / "edge_independent_observation_budget.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


I = _load()
D = datetime.date


@pytest.fixture(scope="module")
def panel(tmp_path_factory):
    from spa_core.strategy_lab.aggressive_lab.fixtures import materialize
    return materialize(tmp_path_factory.mktemp("panel"))


@pytest.fixture(scope="module")
def report(panel):
    return I.build_report(panel, None)


# ── §0 прибор #153 ввозится, а не переписывается ──────────────────────────────────────────

def test_the_153_instrument_is_imported_and_no_second_copy_of_its_numbers():
    CRP = I.load_crp_module()
    assert CRP.ENTRY_TOLL_BPS == 96 and len(CRP.CRISIS_WINDOWS) == 3
    src = (ROOT / "scripts" / "edge_independent_observation_budget.py").read_text(encoding="utf-8")
    assert "ENTRY_TOLL_BPS =" not in src
    assert "TRAIN_END =" not in src
    assert "CRISIS_WINDOWS =" not in src


def test_toll_in_report_is_read_from_153(report):
    assert report["toll_bps"] == 96


# ── §1 арифметика ─────────────────────────────────────────────────────────────────────────

def test_exact_pair_chance_is_one_over_binomial():
    assert I.chance_exact_pair(5, 2) == pytest.approx(0.1)
    assert I.chance_exact_pair(10, 2) == pytest.approx(1 / 45)


def test_overlap_at_least_one_is_hypergeometric():
    # пара из 5: пересечение ≥1 = 1 − C(3,2)/C(5,2) = 0.7
    assert I.chance_overlap_at_least(5, 2, 1) == pytest.approx(0.7)
    # пересечение ≥2 = точная пара
    assert I.chance_overlap_at_least(5, 2, 2) == pytest.approx(I.chance_exact_pair(5, 2))
    # пересечение ≥0 — достоверно
    assert I.chance_overlap_at_least(5, 2, 0) == pytest.approx(1.0)


def test_expected_overlap_is_k_squared_over_n():
    assert I.expected_overlap(5, 2) == pytest.approx(0.8)


def test_min_folds_two_exact_hits_suffice_at_five_percent_but_one_does_not():
    # 0.1^1 = 0.10 ≥ 0.05 — удача ещё объясняет; 0.1^2 = 0.01 < 0.05
    assert I.min_folds_for_alpha(0.1, 0.05) == 2
    # пересечение ≥1 слишком дёшево: 0.7^n < 0.05 ⇒ n = 9
    assert I.min_folds_for_alpha(0.7, 0.05) == 9


def test_min_folds_boundary_is_strict():
    # ровно alpha НЕ достаточно: 0.05^1 = 0.05 ≥ 0.05 ⇒ нужно 2
    assert I.min_folds_for_alpha(0.05, 0.05) == 2


def test_arithmetic_rejects_impossible_pairs_and_bad_alpha():
    with pytest.raises(ValueError):
        I.chance_exact_pair(1, 2)
    with pytest.raises(ValueError):
        I.min_folds_for_alpha(1.0, 0.05)
    with pytest.raises(ValueError):
        I.min_folds_for_alpha(0.1, 1.5)


# ── §2 складки на фикстуре ─────────────────────────────────────────────────────────────────

def test_fixture_has_exactly_one_fold_per_crisis(report):
    f = report["fixture"]
    assert f["n_folds"] == f["n_crises"] == 3
    held = [x["held_out"] for x in f["folds"]]
    assert sorted(held) == sorted(["eth_crash_2024_08", "usde_unwind_2025_10", "rseth_depeg_2026_04"])


def test_each_fold_trains_without_its_held_out_crisis(report):
    for fold in report["fixture"]["folds"]:
        assert fold["held_out"] not in fold["train_crises"]
        assert len(fold["train_crises"]) == 2


def test_on_the_fixture_the_recovery_rule_never_hits_the_exact_pair(report):
    """Отрицательный контроль: #155 видел «отбор угадал» на ОДНОМ шве; под складками — 0 из 3."""
    f = report["fixture"]
    assert f["exact_hits"] == 0
    assert f["overlaps"] == [1, 1, 1]
    assert not report["verdict"]["fixture_rule_survives_loco"]


def test_fixture_mean_overlap_is_printed_next_to_chance(report):
    f = report["fixture"]
    assert f["mean_overlap"] == pytest.approx(1.0)
    assert f["expected_overlap_by_chance"] == pytest.approx(0.8)


def test_verdict_names_the_needed_and_available_fold_counts(report):
    v = report["verdict"]
    assert v["folds_needed_all_exact_hits_at_alpha"] == 2
    assert v["fixture_folds_available"] == 3
    assert "ОДНИМ швом" in v["answer"]


def _synthetic_panel(tmp_path: Path, hits: dict, drifts: dict) -> Path:
    """Панель, где скорость восстановления ПО ПОСТРОЕНИЮ предсказывает потери: те же две книги
    теряют меньше всех в каждом кризисе и восстанавливаются быстрее всех."""
    CRP = I.load_crp_module()
    start, end = D(2024, 7, 1), D(2026, 5, 31)
    for book, loss_by_crisis in hits.items():
        eq = 100_000.0
        rows = []
        d = start
        while d <= end:
            hit = 0.0
            for c in CRP.CRISIS_WINDOWS:
                if c["from"] <= d <= c["to"]:
                    span = (c["to"] - c["from"]).days + 1
                    hit = loss_by_crisis[c["key"]] / span
            eq *= 1.0 + drifts[book] - hit
            rows.append({"date": d.isoformat(), "equity_usd": round(eq, 4), "phase": "backtest"})
            d += datetime.timedelta(days=1)
        bd = tmp_path / book
        bd.mkdir()
        (bd / "realized_series.jsonl").write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    return tmp_path


def test_positive_control_a_rule_that_truly_predicts_hits_every_fold(tmp_path, monkeypatch):
    """Прибор ОБЯЗАН уметь сказать «попало»: иначе ноль на фикстуре — свойство прибора."""
    CRP = I.load_crp_module()
    books = ["a_fast", "b_fast", "c_slow", "d_slow", "e_slow"]
    hits = {}
    for b in books:
        small = b.endswith("_fast")
        hits[b] = {c["key"]: (0.005 if small else 0.15) for c in CRP.CRISIS_WINDOWS}
    drifts = {b: (0.0006 if b.endswith("_fast") else 0.0002) for b in books}
    panel = _synthetic_panel(tmp_path, hits, drifts)
    monkeypatch.setattr(CRP, "ELIGIBLE_BOOKS", books)
    series_map = {b: CRP.load_backtest_series(panel, b) for b in books}
    folds = I.loco_folds(CRP, series_map, list(CRP.CRISIS_WINDOWS))
    assert len(folds) == 3
    assert all(f["exact_hit"] for f in folds)
    assert all(sorted(f["chosen_by_train_velocity"]) == ["a_fast", "b_fast"] for f in folds)


def test_loco_refuses_when_a_held_out_window_is_missing_from_a_series():
    CRP = I.load_crp_module()
    short = [(D(2024, 7, 1) + datetime.timedelta(days=i), 100_000.0 + i) for i in range(20)]
    with pytest.raises(I.Unmeasured):
        I.loco_folds(CRP, {"x": short, "y": short}, list(CRP.CRISIS_WINDOWS))


def test_crisis_loss_is_peak_before_window_to_trough_inside():
    ser = [(D(2024, 7, 30), 100.0), (D(2024, 7, 31), 110.0), (D(2024, 8, 5), 99.0),
           (D(2024, 8, 20), 88.0), (D(2024, 9, 1), 120.0)]
    c = {"key": "w", "from": D(2024, 8, 1), "to": D(2024, 8, 31)}
    assert I.crisis_loss(ser, c) == pytest.approx(0.2)
    assert I.crisis_loss(ser[2:], c) is None  # нет дня ДО окна


def test_rank_top_treats_infinite_velocity_as_the_fastest():
    assert I.rank_top({"a": float("inf"), "b": 5.0, "c": 1.0}, 2, highest=True) == ["a", "b"]
    assert I.rank_top({"a": 0.3, "b": 0.1, "c": 0.2}, 2, highest=False) == ["b", "c"]


# ── §3 бюджет реальной панели ─────────────────────────────────────────────────────────────

def test_drawdown_episode_counts_only_depth_at_or_above_the_toll():
    ser = [(D(2025, 1, 1), 100.0), (D(2025, 1, 2), 99.5), (D(2025, 1, 3), 100.5),   # 50 bp — нет
           (D(2025, 1, 4), 98.0), (D(2025, 1, 5), 97.0), (D(2025, 1, 6), 101.0)]     # 348 bp — да
    eps = I.drawdown_episodes(ser, 0.0096)
    assert len(eps) == 1
    assert eps[0]["start"] == D(2025, 1, 4) and eps[0]["end"] == D(2025, 1, 6)
    assert eps[0]["depth"] == pytest.approx((100.5 - 97.0) / 100.5)
    assert eps[0]["new_lows"] == [D(2025, 1, 4), D(2025, 1, 5)]


def test_an_open_episode_is_reported_with_end_none_not_dropped():
    ser = [(D(2025, 1, 1), 100.0), (D(2025, 1, 2), 90.0), (D(2025, 1, 3), 91.0)]
    eps = I.drawdown_episodes(ser, 0.0096)
    assert len(eps) == 1 and eps[0]["end"] is None


def test_joint_episode_requires_coincident_new_lows_not_merely_being_under_water():
    """Открытая просадка одной книги длиной в год НЕ склеивает панель в один кризис."""
    long_open = [{"start": D(2025, 1, 1), "end": None, "depth": 0.5,
                  "new_lows": [D(2025, 1, 1), D(2025, 1, 2)]}]
    b = [{"start": D(2025, 6, 1), "end": D(2025, 7, 1), "depth": 0.05,
          "new_lows": [D(2025, 6, 1), D(2025, 6, 3)]}]
    c = [{"start": D(2025, 6, 2), "end": D(2025, 7, 1), "depth": 0.05,
          "new_lows": [D(2025, 6, 2)]}]
    joint = I.joint_episodes({"open": long_open, "b": b, "c": c})
    # январь: только одна книга углублялась ⇒ не совместный; июнь: b и c вместе ⇒ один
    assert len(joint) == 1
    assert joint[0]["books"] == ["b", "c"]
    assert joint[0]["start"] == D(2025, 6, 1) and joint[0]["end"] == D(2025, 6, 3)


def test_joint_episodes_split_on_the_gap():
    b = [{"start": D(2025, 1, 1), "end": None, "depth": 0.1,
          "new_lows": [D(2025, 1, 1), D(2025, 3, 1)]}]
    c = [{"start": D(2025, 1, 1), "end": None, "depth": 0.1,
          "new_lows": [D(2025, 1, 2), D(2025, 3, 2)]}]
    joint = I.joint_episodes({"b": b, "c": c}, gap_days=7)
    assert len(joint) == 2


def test_panel_section_reads_only_the_backtest_phase(tmp_path):
    bd = tmp_path / "book"
    bd.mkdir()
    rows = [{"date": "2025-01-01", "equity_usd": 100.0, "phase": "backtest"},
            {"date": "2025-01-02", "equity_usd": 90.0, "phase": "backtest"},
            {"date": "2025-01-03", "equity_usd": 50.0, "phase": "forward"}]   # forward — не читается
    (bd / "realized_series.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    p = I.panel_section(tmp_path, 96.0)
    assert p["books"] == ["book"]
    assert p["block_span"]["book"][2] == 2
    assert p["episodes_per_book"]["book"] == 1
    assert p["n_joint_episodes"] == 0        # одна книга — совместным не бывает


def test_panel_section_refuses_an_unreadable_dir_and_an_empty_block(tmp_path):
    with pytest.raises(I.Unmeasured):
        I.panel_section(tmp_path / "nope", 96.0)
    bd = tmp_path / "b"
    bd.mkdir()
    (bd / "realized_series.jsonl").write_text(
        json.dumps({"date": "2025-01-01", "equity_usd": 1.0, "phase": "forward"}) + "\n")
    with pytest.raises(I.Unmeasured):
        I.panel_section(tmp_path, 96.0)


# ── §4 CLI: три исхода различимы ──────────────────────────────────────────────────────────

def test_cli_exit_2_when_fixture_dir_is_unreadable(tmp_path, capsys):
    rc = I.main(["--fixture-dir", str(tmp_path / "missing")])
    assert rc == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


def test_cli_json_carries_the_three_sections_and_verdict(panel, capsys):
    rc = I.main(["--fixture-dir", str(panel), "--json"])
    assert rc == 0
    doc = json.loads(capsys.readouterr().out)
    assert set(doc) >= {"arithmetic", "fixture", "panel", "verdict", "is_advisory", "outside_riskpolicy"}
    assert doc["panel"] is None                    # панель не названа ⇒ не измерена, не ноль
    assert doc["is_advisory"] is True and doc["outside_riskpolicy"] is True


def test_cli_human_output_says_panel_unmeasured_when_not_named(panel, capsys):
    rc = I.main(["--fixture-dir", str(panel)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "НЕ ИЗМЕРЕНО — каталог не назван" in out
    assert "точных попаданий 0 из 3" in out
