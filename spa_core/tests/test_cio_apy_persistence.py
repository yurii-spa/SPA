# FROZEN-DATE-OK: injected-clock — все отметки сцен происходят от ЯКОРЯ
# `ANCHOR` (и `stamp` в тесте про `now=`), и якорь передаётся аргументом в
# `positive_control(anchor=...)`, `mod._scene(anchor=...)`, `mod.run(now=...)`.
# Настоящих часов эти тесты не спрашивают ни разу: закреплены обе стороны —
# и вход прибора, и отметки ряда, — поэтому календарь их не двигает.
"""Сторож прибора §49 «Persistence» (`cio_apy_persistence`).

Каждый тест — ЗВЕНО контура, и у каждого звена контроль в обе стороны: на целом
контуре прибор зелен, на порванном звене краснеет, и звено НАЗВАНО. Проверок
вида «в модуле есть функция» здесь нет: они зеленеют на сломанном приборе.

**Ни одной литеральной даты.** Все сцены строятся от ЯКОРЯ, который передаётся
аргументом (`positive_control(anchor=...)`, `_series(...)`), поэтому календарь
эти тесты не ломает и пометка `FROZEN-DATE-OK` им не нужна — часы здесь не
окружение, а вход.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

import pytest

from spa_core.backtesting.tier1.cost_model import SLIPPAGE_BPS_STABLE
from spa_core.monitoring import cio_apy_persistence as mod

ANCHOR = dt.date(2000, 1, 20)  # якорь-СЦЕНА, не «сегодня»: свежесть здесь не предмет


def _series(key: str, pre: float, day: float, post: float, *,
            anchor: dt.date = ANCHOR, gap: bool = False) -> dict:
    return mod._scene(anchor, key, pre, day, post, gap=gap)


def _noisy_base(anchor: dt.date = ANCHOR) -> dict:
    """База с ОДНИМ выбросом: медиана низкая, максимум высокий.

    Эта сцена и есть причина, по которой база считается медианой. Первая
    редакция батареи её не имела — все базы были ровные, поэтому `median`
    совпадал с `max`, и мутация «медиана → максимум» переживала прогон. Замер
    мутациями нашёл слабость МОЕЙ батареи, а не прибора.
    """
    series = mod._scene(anchor, "p", 3.0, 6.0, 3.0)
    series["p"][(anchor - dt.timedelta(days=1)).isoformat()] = 6.4
    return series


def _noisy_forward(anchor: dt.date = ANCHOR) -> dict:
    """Окно ПОСЛЕ входа с одним выбросом: медиана низкая, максимум высокий.

    Та же слабость батареи с другой стороны: ровное окно вперёд делало
    `median` и `max` неразличимыми, и мутация `base_fwd = max(fwd)` тоже
    переживала прогон.
    """
    series = mod._scene(anchor, "p", 3.0, 6.0, 3.0)
    series["p"][(anchor + dt.timedelta(days=1)).isoformat()] = 6.4
    return series

def _leg(protocol: str = "p", usd: float = 10_000.0,
         anchor: dt.date = ANCHOR) -> dict:
    return {"date": anchor.isoformat(), "trade_id": "T1",
            "protocol": protocol, "entered_usd": usd}


def _verdict(series: dict, leg: dict | None = None, **kw) -> str:
    leg = leg or _leg()
    return mod.classify_leg(leg, series, mod.series_window(series), **kw)["verdict"]


def _tree(tmp_path: Path, events: list[dict], series: dict) -> Path:
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / "data" / "audit_trail.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n", encoding="utf-8")
    (tmp_path / "data" / "apy_series_daily.json").write_text(
        json.dumps({"series": {k: sorted(v.items()) for k, v in series.items()}}),
        encoding="utf-8")
    return tmp_path


def _move(protocol: str = "p", before: float = 0.0, after: float = 10_000.0,
          anchor: dt.date = ANCHOR, trade_id: str = "T1") -> dict:
    return {"event_type": mod.EVENT_EXECUTED,
            "timestamp": f"{anchor.isoformat()}T06:00:00+00:00",
            "data": {"trade_id": trade_id,
                     "from_allocation": {protocol: before},
                     "to_allocation": {protocol: after}}}


# ─── положительный контроль самого прибора ───────────────────────────────────

class TestPositiveControl:
    def test_control_passes_on_intact_instrument(self):
        control = mod.positive_control(anchor=ANCHOR)
        failed = [c["name"] for c in control["checks"] if not c["passed"]]
        assert control["passed"], f"контроль не прошёл: {failed}"

    def test_control_covers_every_verdict_it_claims(self):
        """Контроль обязан щупать КАЖДЫЙ исход, иначе он украшение."""
        got = {c["expected"] for c in mod.positive_control(anchor=ANCHOR)["checks"]}
        for verdict in (mod.VERDICT_REVERTED, mod.VERDICT_HELD,
                        mod.VERDICT_NO_SPIKE, mod.UNMEASURED_KEY_ABSENT,
                        mod.UNMEASURED_DAY_GAP, mod.UNMEASURED_BEFORE,
                        mod.BELOW_MATERIAL):
            assert verdict in got, f"контроль не щупает исход {verdict}"

    def test_control_is_red_when_spike_detection_is_broken(self, monkeypatch):
        """Порванное звено: всплеск перестал опознаваться — контроль краснеет."""
        monkeypatch.setattr(mod, "SPIKE_REL", 1_000.0)
        control = mod.positive_control(anchor=ANCHOR)
        assert not control["passed"]
        assert any(c["expected"] == mod.VERDICT_REVERTED and not c["passed"]
                   for c in control["checks"])

    def test_control_is_red_when_revert_detection_is_broken(self, monkeypatch):
        """Порванное звено: откат перестал опознаваться.

        Ослепляющее направление — ТРЕБОВАТЬ полного отката (`1.0`): всплеск,
        откатившийся ровно до своей базы, перестаёт считаться испарившимся.
        Обратное направление (`0.0`) прибор НЕ слепит, а делает
        сверхчувствительным, и контроль на нём молчал бы по праву.
        """
        monkeypatch.setattr(mod, "REVERT_FRAC", 1.0)
        control = mod.positive_control(anchor=ANCHOR)
        assert not control["passed"]

    def test_threshold_has_no_second_copy_in_the_signature(self, monkeypatch):
        """Умолчание в подписи было бы ВТОРОЙ копией порога.

        Первая редакция прибора писала `spike_rel: float = SPIKE_REL`. Такое
        умолчание вычисляется при определении функции, поэтому правка
        объявленной константы на поведение не влияла вовсе — и оба контроля
        мутации молчали. Этот тест и есть тот храповик: он краснеет, если
        копия вернётся.
        """
        monkeypatch.setattr(mod, "SPIKE_REL", 1_000.0)
        assert _verdict(_series("p", 3.0, 6.0, 3.0)) == mod.VERDICT_NO_SPIKE
        monkeypatch.setattr(mod, "SPIKE_REL", 1.15)
        monkeypatch.setattr(mod, "REVERT_FRAC", 1.0)
        assert _verdict(_series("p", 3.0, 6.0, 3.0)) == mod.VERDICT_HELD

    def test_control_is_red_when_absent_key_is_read_as_no_spike(self, monkeypatch):
        """Порванное звено: «ключа нет» смешано с «повода не было» (инв. #17)."""
        real = mod.classify_leg

        def blind(leg, series, window, **kw):
            row = real(leg, series, window, **kw)
            if row["verdict"] == mod.UNMEASURED_KEY_ABSENT:
                row["verdict"] = mod.VERDICT_NO_SPIKE
            return row

        monkeypatch.setattr(mod, "classify_leg", blind)
        control = mod.positive_control(anchor=ANCHOR)
        assert not control["passed"]


# ─── вердикт одной ноги ──────────────────────────────────────────────────────

class TestClassify:
    def test_spike_that_evaporates_is_the_finding(self):
        assert _verdict(_series("p", 3.0, 6.0, 3.0)) == mod.VERDICT_REVERTED

    def test_spike_that_holds_is_not_a_finding(self):
        assert _verdict(_series("p", 3.0, 6.0, 6.0)) == mod.VERDICT_HELD

    def test_flat_rate_is_an_observation_not_an_absence(self):
        assert _verdict(_series("p", 3.0, 3.0, 3.0)) == mod.VERDICT_NO_SPIKE

    def test_relative_jump_without_absolute_one_is_noise(self):
        """1,15 от 0,20 % = 0,03 pp — шум фида, а не повод двигать капитал."""
        assert _verdict(_series("p", 0.20, 0.26, 0.20)) == mod.VERDICT_NO_SPIKE

    def test_absolute_jump_without_relative_one_is_noise(self):
        """+0,4 pp на ставке 30 % — дрожь, а не всплеск."""
        assert _verdict(_series("p", 30.0, 30.4, 30.0)) == mod.VERDICT_NO_SPIKE

    def test_missing_key_is_unmeasured_with_a_named_reason(self):
        row = mod.classify_leg(_leg("p"), _series("other", 3.0, 6.0, 3.0),
                               mod.series_window(_series("other", 3.0, 6.0, 3.0)))
        assert row["verdict"] == mod.UNMEASURED_KEY_ABSENT
        assert row["why"] and "ключа" in row["why"]

    def test_day_gap_inside_window_is_unmeasured_not_no_spike(self):
        assert _verdict(_series("p", 3.0, 6.0, 3.0, gap=True)) == mod.UNMEASURED_DAY_GAP

    def test_date_before_series_is_its_own_outcome(self):
        series = _series("p", 3.0, 6.0, 3.0)
        early = _leg(anchor=ANCHOR - dt.timedelta(days=mod.PRE_DAYS + 1))
        assert _verdict(series, early) == mod.UNMEASURED_BEFORE

    def test_date_after_series_is_its_own_outcome(self):
        series = _series("p", 3.0, 6.0, 3.0)
        late = _leg(anchor=ANCHOR + dt.timedelta(days=mod.FWD_DAYS + 1))
        assert _verdict(series, late) == mod.UNMEASURED_AFTER

    def test_short_forward_window_is_unmeasured_not_held(self):
        """Повод ещё не наблюдён — это НЕ «удержался»."""
        series = _series("p", 3.0, 6.0, 3.0)
        per_day = series["p"]
        for i in range(1, mod.FWD_DAYS + 1):
            per_day.pop((ANCHOR + dt.timedelta(days=i)).isoformat(), None)
        per_day[(ANCHOR + dt.timedelta(days=1)).isoformat()] = 3.0
        assert _verdict(series) == mod.UNMEASURED_SHORT_FWD

    def test_short_history_is_unmeasured_not_spike(self):
        series = _series("p", 3.0, 6.0, 3.0)
        per_day = series["p"]
        for i in range(1, mod.PRE_DAYS + 1):
            per_day.pop((ANCHOR - dt.timedelta(days=i)).isoformat(), None)
        per_day[(ANCHOR - dt.timedelta(days=1)).isoformat()] = 3.0
        assert _verdict(series) == mod.UNMEASURED_SHORT_PRE

    def test_sub_material_leg_is_excluded_with_a_reason(self):
        row = mod.classify_leg(_leg(usd=mod.MATERIAL_ENTRY_USD - 1.0),
                               _series("p", 3.0, 6.0, 3.0),
                               mod.series_window(_series("p", 3.0, 6.0, 3.0)))
        assert row["verdict"] == mod.BELOW_MATERIAL
        assert row["why"]

    def test_thresholds_are_inputs_not_environment(self):
        """Порог — аргумент: иначе чувствительность нельзя было бы измерить."""
        series = _series("p", 3.0, 6.0, 4.0)
        assert _verdict(series, revert_frac=0.30) == mod.VERDICT_REVERTED
        assert _verdict(series, revert_frac=0.90) == mod.VERDICT_HELD

    def test_base_is_a_median_so_one_outlier_cannot_hide_a_spike(self):
        """Выброс в базе не должен ослеплять прибор — потому база медиана."""
        assert _verdict(_noisy_base()) == mod.VERDICT_REVERTED

    def test_forward_base_is_a_median_so_one_rebound_day_is_not_persistence(self):
        """Один отскок в окне вперёд — не «повод удержался»."""
        assert _verdict(_noisy_forward()) == mod.VERDICT_REVERTED

    def test_max_as_forward_base_would_hide_the_finding(self, monkeypatch):
        """Контроль с другой стороны: максимум вперёд объявил бы всплеск живым."""
        import statistics as _st
        calls = {"n": 0}

        def median_then_max(values):
            calls["n"] += 1
            return _st.median(values) if calls["n"] == 1 else max(values)

        monkeypatch.setattr(mod.statistics, "median", median_then_max)
        assert _verdict(_noisy_forward()) == mod.VERDICT_HELD

    def test_max_as_base_would_hide_the_finding(self, monkeypatch):
        """Контроль выбора медианы с ДРУГОЙ стороны: максимум прячет находку."""
        import statistics as _st
        monkeypatch.setattr(mod.statistics, "median",
                            lambda values: max(values) if values else _st.median(values))
        assert _verdict(_noisy_base()) == mod.VERDICT_NO_SPIKE

    def test_cost_comes_from_the_shared_model_not_a_retyped_literal(self):
        row = mod.classify_leg(_leg(usd=40_000.0), _series("p", 3.0, 6.0, 3.0),
                               mod.series_window(_series("p", 3.0, 6.0, 3.0)))
        assert row["cost_usd"] == round(40_000.0 * SLIPPAGE_BPS_STABLE / 1e4, 2)


# ─── население ───────────────────────────────────────────────────────────────

class TestPopulation:
    def test_exit_is_not_an_entry(self):
        assert mod.entered_legs([_move(before=20_000.0, after=5_000.0)]) == []

    def test_entry_amount_is_the_delta_not_the_target(self):
        legs = mod.entered_legs([_move(before=5_000.0, after=12_000.0)])
        assert [l["entered_usd"] for l in legs] == [7_000.0]

    def test_proposal_is_not_population(self, tmp_path):
        """Предложение, не доехавшее до книги, денег не двигало."""
        proposal = {"event_type": "allocation_proposal",
                    "timestamp": f"{ANCHOR.isoformat()}T06:00:00+00:00",
                    "data": {"target_usd": {"p": 40_000.0}}}
        tree = _tree(tmp_path, [proposal], _series("p", 3.0, 6.0, 3.0))
        with pytest.raises(mod.NotMeasured):
            mod.load_trail(tree)


# ─── третий исход у прибора целиком ──────────────────────────────────────────

class TestThirdOutcome:
    def test_absent_trail_is_unmeasured_not_clean(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "apy_series_daily.json").write_text(
            json.dumps({"series": {"p": [[ANCHOR.isoformat(), 3.0]]}}), encoding="utf-8")
        out = mod.run(tmp_path, write=False)
        assert out["measured"] is False
        assert out["doc"]["status"] == "UNMEASURED"
        assert "audit_trail" in out["doc"]["reason"]

    def test_absent_series_is_unmeasured_not_clean(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "audit_trail.jsonl").write_text(
            json.dumps(_move()) + "\n", encoding="utf-8")
        out = mod.run(tmp_path, write=False)
        assert out["doc"]["status"] == "UNMEASURED"
        assert "apy_series_daily" in out["doc"]["reason"]

    def test_empty_series_is_unmeasured_not_zero_findings(self, tmp_path):
        """`protocol_history: {}` соседа — ровно эта форма; пустота не «чисто»."""
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "audit_trail.jsonl").write_text(
            json.dumps(_move()) + "\n", encoding="utf-8")
        (tmp_path / "data" / "apy_series_daily.json").write_text(
            json.dumps({"series": {}}), encoding="utf-8")
        assert mod.run(tmp_path, write=False)["doc"]["status"] == "UNMEASURED"

    def test_unparseable_series_is_unmeasured(self, tmp_path):
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "audit_trail.jsonl").write_text(
            json.dumps(_move()) + "\n", encoding="utf-8")
        (tmp_path / "data" / "apy_series_daily.json").write_text("{", encoding="utf-8")
        assert mod.run(tmp_path, write=False)["doc"]["status"] == "UNMEASURED"

    def test_unmeasured_exits_nonzero(self, tmp_path, capsys):
        assert mod.main(["--root", str(tmp_path), "--no-write"]) == 2
        assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out

    def test_finding_exits_one_and_clean_exits_zero(self, tmp_path):
        found = _tree(tmp_path / "found", [_move(after=40_000.0)],
                      _series("p", 3.0, 6.0, 3.0))
        assert mod.main(["--root", str(found), "--no-write"]) == 1
        clean = _tree(tmp_path / "clean", [_move(after=40_000.0)],
                      _series("p", 3.0, 3.0, 3.0))
        assert mod.main(["--root", str(clean), "--no-write"]) == 0


# ─── свод и отчёт ────────────────────────────────────────────────────────────

class TestReport:
    def _doc(self, tmp_path, **kw) -> dict:
        tree = _tree(tmp_path, [_move(after=40_000.0)], _series("p", 3.0, 6.0, 3.0))
        return mod.run(tree, write=False, **kw)["doc"]

    def test_status_names_the_finding_not_the_hole(self, tmp_path):
        assert self._doc(tmp_path)["status"] == "WARN"

    def test_hole_is_printed_even_when_a_finding_exists(self, tmp_path):
        """Названная дыра и названная находка печатаются ОБЕ, вердикт — старшая."""
        events = [_move(after=40_000.0),
                  _move(protocol="unknown", after=50_000.0, trade_id="T2")]
        tree = _tree(tmp_path, events, _series("p", 3.0, 6.0, 3.0))
        doc = mod.run(tree, write=False)["doc"]
        assert doc["status"] == "WARN"
        lines = "\n".join(mod.report(doc))
        assert "[НЕ ИЗМЕРЕНО]" in lines and "[ВХОД НА ВСПЛЕСКЕ]" in lines

    def test_sensitivity_covers_the_whole_declared_grid(self, tmp_path):
        grid = self._doc(tmp_path)["sensitivity"]
        assert len(grid) == len(mod.SENSITIVITY_REL) * len(mod.SENSITIVITY_REVERT)

    def test_sensitivity_is_monotone_in_revert_fraction(self, tmp_path):
        """Строже требование к откату ⇒ находок не больше. Иначе прибор врёт."""
        grid = self._doc(tmp_path)["sensitivity"]
        for rel in mod.SENSITIVITY_REL:
            row = [g["legs"] for g in grid if g["spike_rel"] == rel]
            assert row == sorted(row, reverse=True), row

    def test_report_declares_what_it_does_not_prove(self, tmp_path):
        doc = self._doc(tmp_path)
        assert doc["what_it_does_not_prove"]
        assert "НЕ ДОКЛАДЫВАЕТ" in "\n".join(mod.report(doc))

    def test_report_refuses_to_print_counts_when_control_failed(self, tmp_path,
                                                               monkeypatch):
        doc = self._doc(tmp_path)
        doc["positive_control"] = {"passed": False,
                                   "checks": [{"name": "звено", "passed": False}]}
        lines = "\n".join(mod.report(doc))
        assert "счёт не читать" in lines
        assert "[ВХОД НА ВСПЛЕСКЕ]" not in lines

    def test_absent_tally_is_printed_as_unmeasured_not_as_zero(self, tmp_path):
        """Инв. #17 у печати: «поля нет» ≠ «находок ноль»."""
        doc = self._doc(tmp_path)
        doc.pop("counts")
        lines = "\n".join(mod.report(doc))
        assert "[НЕ ИЗМЕРЕНО]" in lines
        assert "ИСПАРИЛСЯ 0" not in lines

    def test_now_is_an_input(self, tmp_path):
        stamp = dt.datetime(2001, 2, 3, tzinfo=dt.timezone.utc)
        assert self._doc(tmp_path, now=stamp)["generated_at"] == stamp.isoformat()

    def test_artifact_carries_every_field_the_office_requires(self, tmp_path):
        """Схема читается У ОФИСА, а не перепечатывается здесь.

        Перечень полей, набранный в тесте руками, есть вторая копия контракта:
        он остался бы зелёным ровно в том случае, когда офис попросил поле,
        которого прибор не кладёт. Поэтому список берётся из `_READ_SCHEMA`
        самого читателя.
        """
        import importlib.util
        import sys

        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "_office_for_test", root / "scripts" / "consume_office_reports.py")
        office = importlib.util.module_from_spec(spec)
        sys.modules["_office_for_test"] = office
        spec.loader.exec_module(office)
        required = office._READ_SCHEMA.get(mod.ARTIFACT)
        assert required, f"офис не объявил схему для {mod.ARTIFACT}"
        doc = self._doc(tmp_path)
        for path in required:
            node = doc
            for part in path.split("."):
                assert isinstance(node, dict) and part in node, f"{path} ({part})"
                node = node[part]

    def test_office_declares_this_producer(self):
        """Артефакт без объявленного производителя офис не проверяет вовсе."""
        import importlib.util
        import sys

        root = Path(__file__).resolve().parents[2]
        spec = importlib.util.spec_from_file_location(
            "_office_for_test2", root / "scripts" / "consume_office_reports.py")
        office = importlib.util.module_from_spec(spec)
        sys.modules["_office_for_test2"] = office
        spec.loader.exec_module(office)
        assert office._PRODUCER.get(mod.ARTIFACT) == mod.PRODUCER

    def test_cost_is_declared_a_lower_bound_and_gas_unmeasured(self, tmp_path):
        model = self._doc(tmp_path)["cost_model"]
        assert model["gas"] == "НЕ ИЗМЕРЕН"
        assert model["slippage_bps"] == SLIPPAGE_BPS_STABLE
