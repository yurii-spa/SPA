"""Батарея переписи родов числа «APY» (ADR-953, приказ владельца «Portfolio CIO» §5).

Каждая проверка — положительный контроль: воспроизводит настоящее состояние,
измеренное 2026-11-08 на живом `data/`, и КРАСНЕЕТ, если ось перестанет его
видеть. У каждой оси контроль в ОБЕ стороны: находка названа И ноль находок
напечатан числом (инв. #17 — «измерено и равно нулю» отличимо от «не измерено»).

Литеральных дат в файле нет ВОВСЕ, и это не упущение: у прибора нет ни одной
двери к часам — ни своей, ни через подпроцесс (§ «ИНЪЕКЦИЯ ЧАСОВ КОНЧАЕТСЯ НА
ГРАНИЦЕ ПОДПРОЦЕССА» в `.claude/rules/deployment.md`). Предмет переписи —
ИМЕНА и ЗНАМЕНАТЕЛИ, у них срока годности не существует.
"""
from __future__ import annotations

import dataclasses

import pytest

from spa_core.analytics import apy_kinds
from spa_core.analytics.apy_name_census import RATE_TOLERANCE_PP, measure
from spa_core.analytics.portfolio_volatility_tracker import RING_BUFFER_SIZE
from spa_core.analytics.report_sections import SECTION_NAMES, build_report_sections


# ---------------------------------------------------------------------------
# Сцена: замер живого data/ 2026-11-08 (книга $95 000 из NAV $101 985,10)
# ---------------------------------------------------------------------------

_BOOK = [
    ("compound_v3", 40000.0, 3.6963),
    ("fluid_fusdc", 20000.0, 5.0800),
    ("maple", 20000.0, 5.0682),
    ("morpho_blue_base", 10000.0, 6.1565),
    ("aave_v3", 5000.0, 3.5187),
]
_NAV = 101985.10


def _annual() -> float:
    return sum(usd * r / 100.0 for _, usd, r in _BOOK)


def _attribution(**over):
    deployed = sum(usd for _, usd, _ in _BOOK)
    sec = {
        "status": "OK",
        "engine": "yield_attribution_tracker",
        "total_allocated_usd": deployed,
        "effective_apy_pct": round(_annual() / deployed * 100.0, 4),
        "contributions": [
            {"adapter_id": a, "allocated_usd": usd, "apy_pct": r}
            for a, usd, r in _BOOK
        ],
        "apy_unknown": [],
        "top_by_apy": "morpho_blue_base",
    }
    sec.update(over)
    return sec


def _volatility(n_readings: int = 170, mean_pct: float = 4.8842):
    return {
        "status": "OK",
        "engine": "portfolio_volatility_tracker",
        "n_readings": n_readings,
        "mean_apy_pct": mean_pct,
        "vol_7d_pp": 0.148,
    }


def _health():
    return {
        "status": "OK",
        "engine": "adapter_health_scorecard",
        "adapters": [
            # `components/apy` — БАЛЛ 0…100, а не ставка: ровно то имя, которое
            # обещает ставку, не являясь ею.
            {"adapter_id": "compound_v3", "apy_pct": 3.6963,
             "apy_vol_7d_pp": 0.8495, "components": {"apy": 79.79}},
            {"adapter_id": "aave_v3", "apy_pct": 3.5187,
             "apy_vol_7d_pp": None, "components": {"apy": 49.3}},
        ],
    }


def _sections(**over):
    s = {
        "yield_attribution_tracker": _attribution(),
        "portfolio_volatility_tracker": _volatility(),
        "adapter_health_scorecard": _health(),
    }
    s.update(over)
    return s


def _bar(apy_today: float | None = 4.2165, evidenced: bool = True, date: str = "d0"):
    bar = {"date": date, "equity": _NAV, "evidenced": evidenced}
    if apy_today is not None:
        bar["apy_today"] = apy_today
        bar["apy_expected_pct"] = apy_today
    return bar


def _equity(bars=None, n_evidenced: int = RING_BUFFER_SIZE):
    """Трек, у которого хвост длиной кольца ПОЛНОСТЬЮ доказан."""
    if bars is None:
        bars = [_bar(date=f"d{i}") for i in range(n_evidenced)]
    return {"daily": bars}


# ---------------------------------------------------------------------------
# Ось 0: мерка выдерживает свою же мерку
# ---------------------------------------------------------------------------

class TestDeclarationHoldsItsOwnContract:

    def test_declaration_is_clean(self):
        assert apy_kinds.validate() == []

    def test_every_rate_names_denominator_and_window(self):
        for name, k in apy_kinds.KINDS.items():
            if k.is_rate:
                assert k.denominator is not None, name
                assert k.window is not None, name

    def test_validate_catches_a_rate_without_a_denominator(self, monkeypatch):
        """Контроль: сломай объявление — `validate` обязан НАЗВАТЬ это."""
        broken = dataclasses.replace(
            apy_kinds.KINDS["portfolio_rate_on_nav"], denominator=None)
        monkeypatch.setitem(apy_kinds.KINDS, "portfolio_rate_on_nav", broken)
        problems = apy_kinds.validate()
        assert any("ставка без знаменателя" in p for p in problems), problems

    def test_validate_catches_a_non_rate_carrying_a_denominator(self, monkeypatch):
        broken = dataclasses.replace(
            apy_kinds.KINDS["health_subscore"], denominator="nav")
        monkeypatch.setitem(apy_kinds.KINDS, "health_subscore", broken)
        assert any("знаменателя у неставки не существует" in p
                   for p in apy_kinds.validate())

    def test_validate_catches_a_path_pointing_at_a_missing_kind(self, monkeypatch):
        monkeypatch.setitem(apy_kinds.PATH_KINDS, "sections/x/apy_pct", "no_such_kind")
        assert any("которого нет в KINDS" in p for p in apy_kinds.validate())

    def test_broken_declaration_measures_NOTHING_ELSE(self, monkeypatch):
        """Сломанная мерка ⇒ вердикт НЕ ИЗМЕРЕНО, и ни одна ось не отвечает.

        Иначе прибор доложил бы «находок 0» по мерке, которой нет.
        """
        broken = dataclasses.replace(
            apy_kinds.KINDS["position_rate"], meaning="  ")
        monkeypatch.setitem(apy_kinds.KINDS, "position_rate", broken)
        rep = measure(_equity(), _sections())
        assert rep["verdict"] == "UNMEASURED"
        assert "findings" not in rep
        assert "parity" not in rep


# ---------------------------------------------------------------------------
# Ось 1: НЕОБЪЯВЛЕННОЕ
# ---------------------------------------------------------------------------

class TestUndeclaredAxis:

    def test_todays_surface_is_fully_declared_and_zero_is_PRINTED(self):
        rep = measure(_equity(), _sections())
        assert rep["undeclared"] == []
        assert rep["paths_found"] == rep["paths_declared"] > 0

    def test_a_new_apy_number_without_a_kind_is_a_finding(self):
        """Контроль: число родилось — рода нет ⇒ fail-CLOSED, путь НАЗВАН."""
        rep = measure(_equity(), _sections(
            new_engine={"status": "OK", "engine": "new_engine",
                        "blended_apy_pct": 7.5}))
        paths = [u["path"] for u in rep["undeclared"]]
        assert "sections/new_engine/blended_apy_pct" in paths
        assert any("НЕОБЪЯВЛЕННЫХ путей 1" in f for f in rep["findings"])

    def test_no_apy_numbers_at_all_is_UNMEASURED_not_zero(self):
        rep = measure({"daily": [{"date": "d", "equity": _NAV}]}, {})
        assert rep["verdict"] == "UNMEASURED"
        assert any("не о нуле" in u for u in rep["unmeasured"])

    def test_non_numeric_apy_names_are_NOT_judged_by_kind(self):
        """`apy_unknown` (список), `top_by_apy` (строка), `apy_vol_7d_pp: None`.

        Судить их родом нечего — но молчать о них нельзя, иначе «не число»
        стало бы неотличимо от «числа нет».
        """
        rep = measure(_equity(), _sections())
        paths = {d["path"]: d["type"] for d in rep["non_numeric_names"]}
        assert paths["sections/yield_attribution_tracker/apy_unknown"] == "list"
        assert paths["sections/yield_attribution_tracker/top_by_apy"] == "str"
        assert ("наблюдения нет"
                in paths["sections/adapter_health_scorecard/adapters[]/apy_vol_7d_pp"])
        assert rep["undeclared"] == []


# ---------------------------------------------------------------------------
# Ось 2: ОДИН ПРЕДМЕТ — НЕСКОЛЬКО ЧИСЕЛ
# ---------------------------------------------------------------------------

class TestOneSubjectManyNumbersAxis:

    def test_three_book_rates_are_named_with_their_spread(self):
        """Замер 08.11: 4.2165 (NAV) · 4.5260 (размещённое) · 4.8842 (среднее)."""
        rep = measure(_equity(), _sections())
        assert rep["book_rate_values"] == [4.2165, 4.526, 4.8842]
        assert rep["book_rate_spread_pp"] == pytest.approx(0.6677, abs=1e-4)
        assert any("ОДИН ПРЕДМЕТ — 3 ЧИСЛА" in f for f in rep["findings"])
        assert "знаменател" in rep["book_rate_spread_reason"]

    def test_each_book_rate_carries_denominator_and_window(self):
        rep = measure(_equity(), _sections())
        for r in rep["book_rates"]:
            assert r["denominator"] in ("nav", "deployed"), r
            assert r["window"], r

    def test_a_single_book_rate_prints_zero_spread_and_NO_finding(self):
        """Другая сторона: одно число ⇒ разброса нет, и это ЧИСЛО, не молчание."""
        bars = [_bar(apy_today=None, date=f"d{i}") for i in range(3)]
        rep = measure(_equity(bars=bars),
                      {"yield_attribution_tracker": _attribution()})
        assert len(rep["book_rate_values"]) == 1
        assert rep["book_rate_spread_pp"] == 0.0
        assert not any("ОДИН ПРЕДМЕТ" in f for f in rep["findings"])


# ---------------------------------------------------------------------------
# Ось 3: ПАРИТЕТ С КНИГОЙ (перекрёстная — цикл против аналитики)
# ---------------------------------------------------------------------------

class TestParityAxis:

    def test_both_denominators_recomputed_from_the_book(self):
        rep = measure(_equity(), _sections())
        p = rep["parity"]
        assert p["deployed_usd"] == pytest.approx(95000.0)
        assert p["nav_usd"] == pytest.approx(_NAV)
        assert p["recomputed_on_deployed_pct"] == pytest.approx(4.526, abs=1e-3)
        assert p["recomputed_on_nav_pct"] == pytest.approx(4.2161, abs=1e-3)
        assert p["cash_drag_pp"] == pytest.approx(0.31, abs=1e-3)
        assert all(c["verdict"] == "ok" for c in p["checks"]), p["checks"]
        assert not any("ПАРИТЕТ" in f for f in rep["findings"])

    def test_a_printed_rate_that_contradicts_the_book_is_a_finding(self):
        """Контроль: производитель сменил знаменатель молча."""
        rep = measure(_equity(), _sections(
            yield_attribution_tracker=_attribution(effective_apy_pct=6.89)))
        bad = [c for c in rep["parity"]["checks"] if c["verdict"] == "MISMATCH"]
        assert len(bad) == 1, rep["parity"]["checks"]
        assert bad[0]["delta_pp"] == pytest.approx(2.364, abs=1e-3)
        assert any("ПАРИТЕТ" in f for f in rep["findings"])

    def test_a_cross_producer_mismatch_on_nav_is_a_finding(self):
        """`apy_today` пишет ЦИКЛ, книгу — аналитика; их никто не сверял."""
        rep = measure(_equity(bars=[_bar(apy_today=9.99)]), _sections())
        bad = [c for c in rep["parity"]["checks"] if c["verdict"] == "MISMATCH"]
        assert {c["path"] for c in bad} == {
            "equity_curve_daily/daily[]/apy_today",
            "equity_curve_daily/daily[]/apy_expected_pct",
        }

    def test_rounding_alone_never_trips_parity(self):
        shifted = round(_annual() / _NAV * 100.0 + RATE_TOLERANCE_PP / 2.0, 4)
        rep = measure(_equity(bars=[_bar(apy_today=shifted)]), _sections())
        assert all(c["verdict"] == "ok" for c in rep["parity"]["checks"])

    def test_unreadable_book_is_UNMEASURED_not_a_fabricated_parity(self):
        rep = measure(_equity(), _sections(
            yield_attribution_tracker={"status": "SKIPPED",
                                       "engine": "yield_attribution_tracker",
                                       "reason": "нет позиций"}))
        assert "unmeasured" in rep["parity"]
        assert "checks" not in rep["parity"]
        assert any("паритет не измерен" in u for u in rep["unmeasured"])

    def test_zero_deployed_is_UNMEASURED_not_a_zero_rate(self):
        rep = measure(_equity(), _sections(
            yield_attribution_tracker=_attribution(
                contributions=[{"adapter_id": "x", "allocated_usd": 0.0,
                                "apy_pct": 5.0}])))
        assert "ставки у нуля не существует" in rep["parity"]["unmeasured"]

    def test_position_without_a_number_refuses_the_whole_book(self):
        rep = measure(_equity(), _sections(
            yield_attribution_tracker=_attribution(
                contributions=[{"adapter_id": "x", "allocated_usd": 100.0,
                                "apy_pct": None}])))
        assert "unmeasured" in rep["parity"]


# ---------------------------------------------------------------------------
# Ось 4: ОКНО И ОСНОВАНИЕ
# ---------------------------------------------------------------------------

class TestWindowAndEvidenceAxis:

    def test_offered_population_larger_than_the_ring_is_a_finding(self):
        """Замер 08.11: рядом со средним напечатано 170, кольцо — 90."""
        rep = measure(_equity(), _sections(
            portfolio_volatility_tracker=_volatility(n_readings=RING_BUFFER_SIZE * 2)))
        assert rep["window"]["window_bars"] == RING_BUFFER_SIZE
        assert rep["window"]["population_matches_window"] is False
        assert any("ОКНО НЕ НАЗВАНО" in f for f in rep["findings"])

    def test_population_inside_the_ring_is_NO_finding(self):
        rep = measure(_equity(), _sections(
            portfolio_volatility_tracker=_volatility(n_readings=RING_BUFFER_SIZE)))
        assert rep["window"]["population_matches_window"] is True
        assert not any("ОКНО НЕ НАЗВАНО" in f for f in rep["findings"])

    def test_missing_population_is_UNMEASURED_not_zero(self):
        vol = _volatility()
        vol.pop("n_readings")
        rep = measure(_equity(), _sections(portfolio_volatility_tracker=vol))
        assert "offered_unmeasured" in rep["window"]
        assert any("нет n_readings" in u for u in rep["unmeasured"])

    def test_unevidenced_bars_inside_the_window_are_a_finding(self):
        """ADR-580 C2: разогрев и реконструкция не несут метку замера."""
        bars = ([_bar(apy_today=3.9431, evidenced=False, date=f"w{i}")
                 for i in range(5)]
                + [_bar(date=f"d{i}") for i in range(RING_BUFFER_SIZE - 5)])
        rep = measure(_equity(bars=bars), _sections())
        assert rep["window"]["unevidenced_in_window"] == 5
        assert any("ОСНОВАНИЕ" in f for f in rep["findings"])

    def test_a_fully_evidenced_window_PRINTS_zero(self):
        rep = measure(_equity(), _sections())
        assert rep["window"]["bars_in_window"] == RING_BUFFER_SIZE
        assert rep["window"]["unevidenced_in_window"] == 0
        assert not any("ОСНОВАНИЕ" in f for f in rep["findings"])

    def test_unevidenced_bars_OUTSIDE_the_window_do_not_count(self):
        """Окно решает ПРОИЗВОДИТЕЛЬ: бар вне кольца среднего не касается."""
        bars = ([_bar(apy_today=3.9431, evidenced=False, date=f"w{i}")
                 for i in range(32)]
                + [_bar(date=f"d{i}") for i in range(RING_BUFFER_SIZE)])
        rep = measure(_equity(bars=bars), _sections())
        assert rep["window"]["unevidenced_in_window"] == 0

    def test_no_time_mean_printed_means_no_window_question(self):
        rep = measure(_equity(), {"yield_attribution_tracker": _attribution()})
        assert "не существует" in rep["window"]["unmeasured"]


# ---------------------------------------------------------------------------
# Проводка: у переписи есть НАСТОЯЩИЙ вызывающий, и он зовёт её ПОСЛЕ соседей
# ---------------------------------------------------------------------------

class TestWiring:

    def test_census_is_a_declared_section(self):
        assert SECTION_NAMES[-1] == "apy_name_census"

    def test_cycle_builds_the_census_and_it_sees_its_siblings(self, tmp_path):
        (tmp_path / "current_positions.json").write_text(
            '{"positions": {"compound_v3": 40000.0}}', encoding="utf-8")
        (tmp_path / "adapter_status.json").write_text(
            '{"adapters": {"compound_v3": {"apy_pct": 3.6963, "tvl_usd": 1.0e9,'
            ' "tier": "T1", "chain": "ethereum"}}}', encoding="utf-8")
        sections = build_report_sections(tmp_path, _equity())
        sec = sections["apy_name_census"]
        assert sec["engine"] == "apy_name_census"
        assert sec["status"] in ("OK", "SKIPPED")
        # Видит СОСЕДА: ставка книги из секции атрибуции попала в перепись.
        assert sec.get("book_rates") is not None

    def test_empty_data_dir_gives_SKIPPED_with_a_named_reason(self, tmp_path):
        sections = build_report_sections(tmp_path, {})
        sec = sections["apy_name_census"]
        assert sec["status"] == "SKIPPED"
        assert sec["reason"]
        assert sec["verdict"] == "UNMEASURED"
