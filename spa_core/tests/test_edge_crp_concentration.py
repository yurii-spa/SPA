"""Контроли прибора #155 CRPC (`scripts/edge_crp_concentration.py`).

Предмет прибора — ДВА разных вопроса (порог и атрибуция), поэтому у каждого свой контроль
в ОБЕ стороны: сцена, где вердикт срабатывает, и сцена, где он НЕ должен.

# FROZEN-DATE-OK: fixture-subject — ДАТЫ здесь являются ПРЕДМЕТОМ: это шов TRAIN/TEST и
# окна кризисов детерминированной фикстуры (`aggressive_lab/fixtures.py`), то есть входные
# данные сцены. Понятия СВЕЖЕСТИ на пути прибора нет ни одного: у него нет ни одной двери
# к стенным часам (ни `now()`, ни `today()`), поэтому инъектировать нечего, и сдвиг
# календаря не меняет ни один его вердикт. Форма №3 `.claude/rules/deployment.md`.
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
        "edge_crp_concentration", ROOT / "scripts" / "edge_crp_concentration.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


C = _load()


@pytest.fixture(scope="module")
def panel(tmp_path_factory):
    from spa_core.strategy_lab.aggressive_lab.fixtures import materialize
    return materialize(tmp_path_factory.mktemp("panel"))


@pytest.fixture(scope="module")
def report(panel):
    return C.build_report(panel)


# ── §1 прибор #153 ввозится, а не переписывается ─────────────────────────────────────────

def test_the_153_instrument_is_imported_not_reimplemented():
    """Шов, пошлина и симулятор портфеля живут в ОДНОЙ копии — у прибора #153."""
    CRP = C.load_crp_module()
    assert CRP.ENTRY_TOLL_BPS == 96
    assert CRP.TRAIN_END == datetime.date(2025, 6, 30)
    assert hasattr(CRP, "run_portfolio") and hasattr(CRP, "crp_report")
    # и у #155 своей копии этих чисел НЕТ
    src = (ROOT / "scripts" / "edge_crp_concentration.py").read_text(encoding="utf-8")
    assert "ENTRY_TOLL_BPS =" not in src
    assert "TRAIN_END =" not in src


def test_report_uses_the_toll_from_153(report):
    assert report["toll_bps"] == 96


def test_the_toll_is_not_merely_DECLARED_it_REACHES_the_numbers(panel, report):
    """Объявление пошлины не есть её применение.

    Контроль поставлен после выжившего мутанта (обнуление `toll_bps` в вызове симулятора
    не меняло ни одной проверки): мерка, у которой сверяется только ОБЪЯВЛЕНИЕ, — это
    половина двери. Здесь сверяется ЭФФЕКТ: бесплатный вход обязан дать ставку ВЫШЕ."""
    CRP = C.load_crp_module()
    series_map = {b: CRP.load_backtest_series(panel, b) for b in report["books"]}
    w = report["allocations"]["TOP2-50/50"]
    paid = CRP.run_portfolio(series_map, w, datetime.date(2024, 7, 1),
                             datetime.date(2026, 5, 31), toll_bps=report["toll_bps"])
    free = CRP.run_portfolio(series_map, w, datetime.date(2024, 7, 1),
                             datetime.date(2026, 5, 31), toll_bps=0.0)
    assert free[0] > paid[0], (free, paid)
    # и напечатанные числа отчёта — именно ПЛАТНАЯ ветка, а не бесплатная
    assert abs(report["results"]["FULL 843 дня"]["TOP2-50/50"][0] - paid[0]) < 1e-9
    assert abs(report["results"]["FULL 843 дня"]["TOP2-50/50"][0] - free[0]) > 1e-6


# ── §2 пол RWA ЧИТАЕТСЯ, а не объявляется третьей копией ─────────────────────────────────

def test_the_rwa_floor_is_read_from_an_existing_constant():
    val, src = C.measured_rwa_floor_pct()
    assert val is not None, src
    assert 3.0 < val < 3.6, val                 # измеренный пол, а не константа заказа
    assert "edge_cash_sleeve_frontier.py" in src


def test_the_order_floor_and_the_measured_floor_are_BOTH_reported(report):
    """Расхождение мерок называется вслух, а не сглаживается в одно число."""
    assert report["floor_order_pct"] == 3.4
    assert report["floor_measured_pct"] != report["floor_order_pct"]


# ── §3 раскладки: пять, и каждая отвечает на свой вопрос ─────────────────────────────────

def test_all_five_allocations_are_built_and_normalised(report):
    allocs = report["allocations"]
    assert set(allocs) == {"EW-5", "CRP-5", "TOP2-50/50",
                           "EW-4 (без variant_d)", "CRP-4 (без variant_d)"}
    for name, w in allocs.items():
        assert abs(sum(w.values()) - 1.0) < 1e-9, (name, w)


def test_the_attribution_controls_EXCLUDE_variant_d(report):
    for key in ("EW-4 (без variant_d)", "CRP-4 (без variant_d)"):
        assert "variant_d" not in report["allocations"][key]


def test_top2_allocation_is_exactly_the_pair_the_order_named(report):
    assert sorted(report["allocations"]["TOP2-50/50"]) == sorted(["susde_dn", "points_farm"])
    assert set(report["allocations"]["TOP2-50/50"].values()) == {0.5}


def test_the_measured_train_top2_is_printed_next_to_the_order_pair(report):
    """Если замер однажды разойдётся с заказом, запись обязана это УЗНАТЬ, а не скрыть."""
    assert sorted(report["top2_measured"]) == sorted(report["top2_order"])


# ── §4 порог: вердикт на TEST и на TRAIN — РАЗНЫЕ вопросы ────────────────────────────────

def test_the_order_question_is_answered_on_TEST_not_only_on_TRAIN(report):
    res = report["results"]
    assert "TRAIN 2024-07..2025-06" in res and "TEST 2025-07..2026-05" in res
    top2_test = res["TEST 2025-07..2026-05"]["TOP2-50/50"]
    top2_train = res["TRAIN 2024-07..2025-06"]["TOP2-50/50"]
    assert top2_train[0] > report["floor_order_pct"]
    assert top2_test[0] > report["floor_order_pct"]        # ответ заказа: ДА, на OOS тоже


def test_the_tail_is_reported_next_to_every_rate(report):
    for pname, res in report["results"].items():
        for aname, triple in res.items():
            apy, dd, cal = triple
            assert isinstance(apy, float) and isinstance(dd, float), (pname, aname)
            assert dd >= 0.0, (pname, aname, dd)


def test_equal_weight_five_is_BELOW_the_floor_on_test_the_control_in_the_other_direction(report):
    """Прибор умеет сказать «НИЖЕ порога»: иначе вердикт «ВЫШЕ» ничего не значит."""
    assert report["results"]["TEST 2025-07..2026-05"]["EW-5"][0] < report["floor_order_pct"]


# ── §5 атрибуция: исключение и отбор измеряются ОТДЕЛЬНО ────────────────────────────────

def test_selection_and_exclusion_are_separable_and_both_positive_on_test(report):
    res = report["results"]["TEST 2025-07..2026-05"]
    ew5 = res["EW-5"][0]
    crp5 = res["CRP-5"][0]
    ew4 = res["EW-4 (без variant_d)"][0]
    crp4 = res["CRP-4 (без variant_d)"][0]
    exclusion = ew4 - ew5
    selection = crp4 - ew4
    assert exclusion > 0, exclusion
    assert selection > 0, selection
    # заказ спрашивал именно это: отбор НЕ сводится к снятию веса с variant_d
    assert selection > exclusion, (selection, exclusion)
    assert abs((crp5 - ew5) - (exclusion + selection)) < 3.0   # разложение сходится


# ── §6 контроль против черри-пика ────────────────────────────────────────────────────────

def test_every_pair_is_swept_not_only_the_one_the_order_named(report):
    pairs = report["pairs"]
    assert len(pairs) == 10                       # C(5,2)
    assert all(len(p["pair"]) == 2 for p in pairs)


def test_the_train_chosen_pair_is_compared_against_all_the_others(report):
    tkey = "TEST 2025-07..2026-05"
    fl = report["floor_order_pct"]
    above = [p for p in report["pairs"] if p[tkey][0] > fl]
    assert len(above) == 1, [p["pair"] for p in above]
    assert sorted(above[0]["pair"]) == sorted(report["top2_order"])


def test_velocity_rank_is_reported_so_the_pick_can_be_rechecked(report):
    rank = report["velocity_rank"]
    assert rank[:2] == ["points_farm", "susde_dn"]
    assert rank[-1] == "variant_d"


# ── §7 третий исход: отказ, а не ноль ────────────────────────────────────────────────────

def test_build_report_REFUSES_on_an_empty_panel_with_a_NAMED_cause(tmp_path):
    """Трассировка наружу исходом не является: вызывающий не отличит её от поломки прибора."""
    with pytest.raises(C.Unmeasured) as e:
        C.build_report(tmp_path / "void")
    assert "не прочитана" in str(e.value)


def test_build_report_REFUSES_when_a_book_series_is_empty(panel, tmp_path):
    import shutil
    dst = tmp_path / "panel"
    shutil.copytree(panel, dst)
    (dst / "susde_dn" / "realized_series.jsonl").write_text("", encoding="utf-8")
    with pytest.raises(C.Unmeasured) as e:
        C.build_report(dst)
    assert "susde_dn" in str(e.value)


def test_load_crp_module_REFUSES_a_missing_instrument(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "_MODULE_ROOT", tmp_path)
    with pytest.raises(C.Unmeasured):
        C.load_crp_module()


def test_measured_floor_is_a_THIRD_OUTCOME_when_unreadable(monkeypatch, tmp_path):
    monkeypatch.setattr(C, "_MODULE_ROOT", tmp_path)
    val, src = C.measured_rwa_floor_pct()
    assert val is None and "НЕ ИЗМЕРЕНО" in src


# ── §8 CLI ───────────────────────────────────────────────────────────────────────────────

def test_cli_returns_0_and_prints_the_order_verdict(panel, capsys):
    assert C.main(["--data-dir", str(panel)]) == 0
    out = capsys.readouterr().out
    assert "ИСПОЛНЕНИЕ ЗАКАЗА" in out
    assert "ЧЕРРИ-ПИКА" in out
    assert "incentive_decay" in out          # предупреждение о классе D напечатано
    assert "[bt" in out                       # числа помечены бэктестовыми


def test_cli_returns_2_on_an_unreadable_panel(tmp_path, capsys):
    assert C.main(["--data-dir", str(tmp_path / "void")]) == 2
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().err


def test_cli_json_is_machine_readable(panel, capsys):
    assert C.main(["--data-dir", str(panel), "--json"]) == 0
    doc = json.loads(capsys.readouterr().out)
    assert doc["order"] == "#153 п. 2"
    assert doc["evidence_level"].startswith("L0")
