# FROZEN-DATE-OK: injected-clock — якорь NOW привязан именем и УЕЗЖАЕТ аргументом
# `now=` в `blind_axes_state()` / `measure()`; отметки файлов сцены ставятся
# `os.utime` от ТОГО ЖЕ якоря, поэтому закреплены ОБЕ стороны сравнения срока и
# календарь хоста в вердикт не попадает (`.claude/rules/deployment.md`, приём №1).
"""Батарея §10/§11 приказа владельца «Portfolio CIO» (ADR-954).

Каждая проверка воспроизводит форму вреда, а не «покрывает строку». Главные —
те, что краснеют на fail-OPEN: слепота, напечатанная как оптимизм.
"""
from __future__ import annotations

import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from spa_core.analytics import apy_expectation as ax
from spa_core.analytics import apy_kinds
from spa_core.analytics.apy_name_census import measure as census

#: Якорь сцены. Обе стороны любого сравнения срока происходят ОТ НЕГО.
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def _series(values, start=None):
    """[(дата, ставка)] с датами, выведенными ОТ ЯКОРЯ, а не из литералов."""
    first = (start or NOW) - timedelta(days=len(values))
    return [((first + timedelta(days=i)).date().isoformat(), v)
            for i, v in enumerate(values)]


def _write(path: Path, doc, now=NOW, age_h=0.0):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    ts = (now - timedelta(hours=age_h)).timestamp()
    os.utime(path, (ts, ts))


# ───────────────────────────── объявление ──────────────────────────────────

class TestDeclaration:
    def test_real_declaration_holds_its_own_contract(self):
        assert ax.validate() == []
        assert apy_kinds.validate() == []

    def test_weights_that_do_not_sum_to_one_are_named(self, monkeypatch):
        # Положительный контроль: persistence_factor перестал бы быть долей,
        # и «1.2» читалось бы как «устойчивее, чем всегда».
        monkeypatch.setattr(ax, "WEIGHT_DURATION", 0.5)
        assert any("не 1.0" in p for p in ax.validate())

    def test_short_window_not_shorter_than_long_is_named(self, monkeypatch):
        monkeypatch.setattr(ax, "SHORT_WINDOW", ax.LONG_WINDOW)
        assert any("не короче долгого" in p for p in ax.validate())

    def test_blind_axis_without_a_reason_is_not_a_declaration(self, monkeypatch):
        broken = ({"axis": "x", "owner_words": "x", "source": None,
                   "consumer": None, "why": "   "},)
        monkeypatch.setattr(ax, "BLIND_AXES", broken)
        assert any("причина слепоты не названа" in p for p in ax.validate())

    def test_negative_haircut_coefficient_is_named(self, monkeypatch):
        # Разброс, УМЕНЬШАЮЩИЙ haircut, есть ровно инверсия замысла §11.
        monkeypatch.setattr(ax, "HAIRCUT_VOL_COEF", -1.0)
        assert any("отрицателен" in p for p in ax.validate())


class TestForwardKindCarriesNoEvidenceLabel:
    """§11 «Displayed APY != Expected APY» живёт ПОЛЯМИ рода, а не прозой."""

    def test_expected_kind_is_forward(self):
        k = apy_kinds.KINDS["position_rate_expected_conservative"]
        assert k.horizon == "forward"
        assert k.evidence == "not_applicable"
        assert k.owner_term == "Conservative Expected APY"

    def test_displayed_and_expected_are_different_kinds(self):
        declared = apy_kinds.PATH_KINDS
        disp = declared["sections/conservative_expected_apy/opportunities[]/displayed_apy_pct"]
        exp = declared["sections/conservative_expected_apy/"
                       "opportunities[]/conservative_expected_apy_pct"]
        assert disp != exp
        assert apy_kinds.KINDS[disp].horizon == "backward"
        assert apy_kinds.KINDS[exp].horizon == "forward"

    def test_forward_kind_claiming_evidence_is_refused(self, monkeypatch):
        # Положительный контроль поправки C2 ADR-580: выведенное моделью число,
        # носящее метку замера, и есть тот дефект, ради которого C2 написана.
        broken = replace(apy_kinds.KINDS["position_rate_expected_conservative"],
                         evidence="evidenced_only")
        monkeypatch.setitem(apy_kinds.KINDS,
                            "position_rate_expected_conservative", broken)
        assert any("метку замера носить не вправе" in p
                   for p in apy_kinds.validate())

    def test_unknown_horizon_is_refused(self, monkeypatch):
        broken = replace(apy_kinds.KINDS["position_rate"], horizon="sideways")
        monkeypatch.setitem(apy_kinds.KINDS, "position_rate", broken)
        assert any("вне HORIZONS" in p for p in apy_kinds.validate())


# ─────────────────────────────── §10 ───────────────────────────────────────

class TestPersistence:
    def test_too_few_observations_is_unmeasured_not_full_confidence(self):
        """ГЛАВНЫЙ контроль: короткий ряд обязан дать None, а НЕ 1.0.

        1.0 здесь напечатал бы слепоту как оптимизм и поднял ожидание на всю
        ставку стимулов — ошибка в опасную сторону.
        """
        rec = ax.persistence(_series([5.0] * (ax.MIN_OBSERVATIONS - 1)))
        assert rec["factor"] is None
        assert "минимуме" in rec["unmeasured"]

    def test_flat_series_is_measured_and_fully_persistent(self):
        rec = ax.persistence(_series([5.0] * 40))
        assert rec["factor"] == 1.0
        assert rec["vol_pp"] == 0.0            # измерено И равно нулю
        assert rec["observations_at_or_above_mean"] == ax.LONG_WINDOW

    def test_spike_today_lowers_the_factor_against_the_same_history(self):
        flat = ax.persistence(_series([5.0] * 40))
        spiked = ax.persistence(_series([5.0] * 39 + [15.0]))
        assert spiked["factor"] < flat["factor"]
        assert spiked["excess_over_mean_share"] > 0.0

    def test_dispersion_alone_lowers_the_factor(self):
        calm = ax.persistence(_series([5.0] * 40))
        noisy = ax.persistence(_series([3.0, 7.0] * 20))
        assert noisy["vol_pp"] > calm["vol_pp"]
        assert noisy["factor"] < calm["factor"]

    def test_non_positive_long_mean_is_unmeasured_not_zero(self):
        rec = ax.persistence(_series([0.0] * 40))
        assert rec["factor"] is None
        assert "не положительно" in rec["unmeasured"]

    def test_factor_never_leaves_the_unit_interval(self):
        for vals in ([5.0] * 40, [3.0, 7.0] * 20, [1.0] + [9.0] * 39,
                     list(range(1, 41))):
            f = ax.persistence(_series([float(v) for v in vals]))["factor"]
            assert f is None or 0.0 <= f <= 1.0


# ─────────────────────────────── §11 ───────────────────────────────────────

class TestConservativeExpected:
    def test_unmeasured_composition_refuses_instead_of_assuming_pure_base(self):
        """ГЛАВНЫЙ контроль fail-CLOSED: «вся ставка базовая» запрещено.

        Такая подстановка утверждала бы НУЛЕВОЙ риск истечения стимулов у
        протокола, состав ставки которого никто не измерил.
        """
        v, why = ax.conservative_expected(None, None, 1.0, 0.0,
                                          composition_unmeasured="пул не разрешён")
        assert v is None
        assert "нулевой" in why

    def test_measured_composition_produces_a_number(self):
        v, why = ax.conservative_expected(4.0, 2.0, 0.5, 0.5)
        assert why == ""
        assert v == pytest.approx(4.0 + 2.0 * 0.5 - 0.5)

    def test_unmeasured_persistence_refuses(self):
        v, why = ax.conservative_expected(4.0, 2.0, None, 0.5)
        assert v is None and "устойчивость не измерена" in why

    def test_expectation_grows_with_persistence(self):
        low, _ = ax.conservative_expected(4.0, 2.0, 0.1, 0.5)
        high, _ = ax.conservative_expected(4.0, 2.0, 0.9, 0.5)
        assert high > low

    def test_haircut_cannot_push_the_expectation_below_zero(self):
        v, _ = ax.conservative_expected(1.0, 0.0, 1.0, 99.0)
        assert v == 0.0


# ──────────────────── слепые оси §10: четыре исхода ────────────────────────

class TestBlindAxes:
    def _axes(self, source, consumer=None):
        return ({"axis": "tvl_trend", "owner_words": "TVL trend",
                 "source": source, "consumer": consumer,
                 "why": "ряда TVL не пишет никто"},)

    def test_missing_file_and_empty_file_are_different_states(self, tmp_path,
                                                              monkeypatch):
        monkeypatch.setattr(ax, "BLIND_AXES", self._axes("t.json"))
        gone = ax.blind_axes_state(tmp_path, now=NOW)[0]
        assert gone["state"] == "blind_no_data"
        _write(tmp_path / "t.json", [], now=NOW)
        empty = ax.blind_axes_state(tmp_path, now=NOW)[0]
        assert empty["state"] == "blind_empty"
        assert "ПУСТ" in empty["detail"]

    def test_no_source_is_its_own_state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(ax, "BLIND_AXES", self._axes(None))
        assert ax.blind_axes_state(tmp_path, now=NOW)[0]["state"] == "blind_no_source"

    def test_the_clock_is_an_input_and_both_scenes_answer_oppositely(
            self, tmp_path, monkeypatch):
        """ОДИН файл, ДВА якоря, ПРОТИВОПОЛОЖНЫЕ ответы.

        Сдвинут только `now`; байты и отметка файла не тронуты. Если бы срок
        спрашивался у стенных часов, оба ответа совпали бы — и тест стал бы
        будильником (`.claude/rules/deployment.md`, приём №1).
        """
        monkeypatch.setattr(ax, "BLIND_AXES", self._axes("t.json", consumer="c"))
        _write(tmp_path / "t.json", [{"x": 1}], now=NOW, age_h=0.0)
        fresh = ax.blind_axes_state(tmp_path, now=NOW)[0]
        later = NOW + timedelta(hours=ax.BLIND_SOURCE_MAX_AGE_H + 1.0)
        stale = ax.blind_axes_state(tmp_path, now=later)[0]
        assert fresh["state"] == "credited"
        assert stale["state"] == "blind_stale"
        assert "при пределе" in stale["detail"]

    def test_data_without_a_consumer_is_not_credited(self, tmp_path, monkeypatch):
        """Данные пришли, формула их НЕ читает ⇒ кредита нет.

        Иначе haircut упал бы в день появления файла, а ожидание выросло БЕЗ
        новой информации — ложное усиление (урок ADR-940).
        """
        monkeypatch.setattr(ax, "BLIND_AXES", self._axes("t.json", consumer=None))
        _write(tmp_path / "t.json", [{"x": 1}], now=NOW)
        rec = ax.blind_axes_state(tmp_path, now=NOW)[0]
        assert rec["state"] == "blind_no_consumer"
        assert "потребителя в формуле нет" in rec["detail"]

    def test_arriving_data_does_not_lower_the_haircut_by_itself(self, tmp_path,
                                                               monkeypatch):
        """Та же мысль, но МЕРОЙ: haircut обязан совпасть до и после прихода данных."""
        monkeypatch.setattr(ax, "BLIND_AXES", self._axes("t.json", consumer=None))
        _scene(tmp_path, series={"a": [5.0] * 40}, base=4.0, reward=1.0)
        _write(tmp_path / "t.json", [], now=NOW)
        before = ax.measure(tmp_path, now=NOW)["haircut_from_blind_axes_pp"]
        _write(tmp_path / "t.json", [{"x": 1}], now=NOW)
        after = ax.measure(tmp_path, now=NOW)["haircut_from_blind_axes_pp"]
        assert before == after > 0.0


# ───────────────────────── сцена и сквозной прогон ─────────────────────────

def _scene(root: Path, series, base, reward, composition_unmeasured=None,
           now=NOW):
    adapters = {}
    for aid, vals in series.items():
        a = {"display_name": aid, "live_apy": vals[-1], "apy": vals[-1],
             "apy_base": base, "apy_reward": reward, "tier": 1}
        if composition_unmeasured:
            a["apy_composition_unmeasured"] = composition_unmeasured
            a["apy_base"] = None
            a["apy_reward"] = None
        adapters[aid] = a
    _write(root / "adapter_status.json", {"adapters": adapters}, now=now)
    _write(root / "apy_series_daily.json",
           {"series": {aid: [list(p) for p in _series(vals)]
                       for aid, vals in series.items()}}, now=now)
    return adapters


class TestMeasure:
    def test_missing_input_is_unmeasured_not_zero_opportunities(self, tmp_path):
        rep = ax.measure(tmp_path, now=NOW)
        assert rep["status"] == "SKIPPED"
        assert rep["verdict"] == "UNMEASURED"
        assert any("файла нет" in u for u in rep["unmeasured"])
        assert "opportunities" not in rep

    def test_empty_adapter_registry_is_unmeasured(self, tmp_path):
        _write(tmp_path / "adapter_status.json", {"adapters": {}}, now=NOW)
        _write(tmp_path / "apy_series_daily.json", {"series": {}}, now=NOW)
        rep = ax.measure(tmp_path, now=NOW)
        assert rep["verdict"] == "UNMEASURED"
        assert any("неразличимы" in u for u in rep["unmeasured"])

    def test_unmeasured_composition_is_counted_not_silently_dropped(self, tmp_path):
        _scene(tmp_path, {"a": [5.0] * 40}, base=None, reward=None,
               composition_unmeasured="пул не разрешён")
        rep = ax.measure(tmp_path, now=NOW)
        assert rep["counts"]["adapters"] == 1
        assert rep["counts"]["expected_measured"] == 0
        assert rep["counts"]["expected_unmeasured"] == 1
        assert rep["opportunities"][0]["conservative_expected_apy_pct"] is None
        assert rep["opportunities"][0]["expected_unmeasured"]

    def test_full_scene_produces_expectation_below_displayed(self, tmp_path):
        _scene(tmp_path, {"a": [5.0] * 40}, base=4.0, reward=1.0)
        rep = ax.measure(tmp_path, now=NOW)
        row = rep["opportunities"][0]
        assert row["persistence_factor"] == 1.0
        # §11 дословно: ожидание не есть напечатанное число.
        assert row["conservative_expected_apy_pct"] < row["displayed_apy_pct"]
        assert row["gap_pp"] > 0.0
        assert rep["counts"]["expected_equals_displayed"] == 0

    def test_dispersion_raises_the_haircut_not_lowers_it(self, tmp_path):
        """Дыра покрытия, найденная мутацией: знак вклада разброса.

        Обратный знак («разброс УМЕНЬШАЕТ haircut») — инверсия всего замысла
        §11: самая дёргающаяся ставка получала бы САМОЕ щедрое ожидание. Ни
        одна прежняя проверка этого не ловила, потому что сравнивала число с
        самим собой, а не ДВА разных ряда между собой.
        """
        _scene(tmp_path, {"calm": [5.0] * 40, "noisy": [3.0, 7.0] * 20},
               base=4.0, reward=1.0)
        rows = {r["adapter_id"]: r for r in ax.measure(tmp_path, now=NOW)["opportunities"]}
        calm, noisy = rows["calm"], rows["noisy"]
        assert noisy["apy_vol_30d_pp"] > calm["apy_vol_30d_pp"]
        assert noisy["uncertainty_haircut_pp"] > calm["uncertainty_haircut_pp"]
        # и ниже haircut слепых осей не опускается НИКОГДА (разброс только добавляет)
        base_haircut = ax.measure(tmp_path, now=NOW)["haircut_from_blind_axes_pp"]
        assert calm["uncertainty_haircut_pp"] >= base_haircut

    def test_adapter_without_series_is_named_not_dropped(self, tmp_path):
        adapters = _scene(tmp_path, {"a": [5.0] * 40}, base=4.0, reward=1.0)
        adapters["b"] = dict(adapters["a"])
        _write(tmp_path / "adapter_status.json", {"adapters": adapters}, now=NOW)
        rep = ax.measure(tmp_path, now=NOW)
        assert rep["counts"]["adapters_without_series"] == 1
        assert rep["adapters_without_series"] == ["b"]
        assert any(r["adapter_id"] == "b" and r["persistence_unmeasured"]
                   for r in rep["opportunities"])

    def test_broken_declaration_stops_the_section(self, tmp_path, monkeypatch):
        _scene(tmp_path, {"a": [5.0] * 40}, base=4.0, reward=1.0)
        monkeypatch.setattr(ax, "WEIGHT_DURATION", 0.9)
        rep = ax.measure(tmp_path, now=NOW)
        assert rep["verdict"] == "UNMEASURED"
        assert "opportunities" not in rep


class TestCensusJudgesTheNewSection:
    """Проводка: каждое apy-именованное число секции ОБЪЯВЛЕНО.

    Это не украшение: перепись `apy_name_census` краснеет на необъявленное
    fail-CLOSED, поэтому новое поле, добавленное мимо `apy_kinds`, найдётся
    сторожем, а не читателем отчёта.
    """

    def _sections(self, tmp_path):
        _scene(tmp_path, {"a": [5.0] * 40, "b": [3.0, 7.0] * 20},
               base=4.0, reward=1.0)
        return {"conservative_expected_apy": ax.measure(tmp_path, now=NOW)}

    def test_every_apy_named_number_of_the_section_is_declared(self, tmp_path):
        rep = census({"daily": []}, self._sections(tmp_path))
        assert rep["undeclared"] == [], rep["undeclared"]
        assert rep["paths_found"] >= 7

    def test_an_undeclared_new_field_reddens(self, tmp_path):
        sections = self._sections(tmp_path)
        assert census({"daily": []}, sections)["undeclared"] == []
        # То же дерево, добавлено ОДНО необъявленное поле ⇒ вердикт меняется.
        sections["conservative_expected_apy"]["opportunities"][0]["smart_apy_pct"] = 9.9
        rep = census({"daily": []}, sections)
        assert [u["path"] for u in rep["undeclared"]] == [
            "sections/conservative_expected_apy/opportunities[]/smart_apy_pct"]

    def test_the_new_section_adds_no_book_rate(self, tmp_path):
        """Ось «один предмет — несколько чисел» судит ставки КНИГИ.

        Ожидание — число о ПОЗИЦИИ и о БУДУЩЕМ; попади оно в ту ось, перепись
        сравнила бы разнородное и напечатала ложное расхождение.
        """
        rep = census({"daily": []}, self._sections(tmp_path))
        assert rep["book_rates"] == []
        for path, name in apy_kinds.PATH_KINDS.items():
            if path.startswith("sections/conservative_expected_apy/"):
                assert apy_kinds.KINDS[name].subject == "position", path


class TestSectionIsWiredIntoTheCycle:
    """Дыра покрытия, найденная мутацией: «прибор написан и не позван».

    Батарея целиком звала `measure()` напрямую, поэтому снятие секции из
    перечня отчёта НЕ КРАСНИЛО ни одного имени: числа §10/§11 не производились
    бы ни одним циклом, а тесты оставались зелёными. Это ровно тот класс, что
    `.claude/rules/acceptance.md` называет «модуль есть, тесты зелёные ≠
    работает», и измеряется он только через настоящую сборку отчёта.
    """

    def test_section_is_named_in_the_report_registry(self):
        from spa_core.analytics.report_sections import SECTION_NAMES
        assert "conservative_expected_apy" in SECTION_NAMES

    def test_section_is_built_before_the_census_that_judges_it(self):
        from spa_core.analytics.report_sections import SECTION_NAMES
        names = list(SECTION_NAMES)
        assert names.index("conservative_expected_apy") < names.index("apy_name_census")

    def test_real_report_build_produces_the_section_and_the_census_declares_it(
            self, tmp_path):
        from spa_core.analytics.report_sections import build_report_sections

        _scene(tmp_path, {"a": [5.0] * 40, "b": [3.0, 7.0] * 20},
               base=4.0, reward=1.0)
        sections = build_report_sections(tmp_path, {"daily": []})
        sec = sections.get("conservative_expected_apy")
        assert sec is not None, "секция не построена настоящей сборкой отчёта"
        assert sec.get("status") == "OK", sec
        assert sec["counts"]["expected_measured"] == 2
        # и перепись родов ТОГО ЖЕ прогона судит её числа, а не чужие
        judged = sections["apy_name_census"]
        assert judged.get("undeclared") == [], judged.get("undeclared")
        assert any(p.startswith("sections/conservative_expected_apy/")
                   for p in apy_kinds.PATH_KINDS)
