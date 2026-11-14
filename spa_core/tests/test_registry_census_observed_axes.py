"""ADR-1007 — наблюдённый спутник у КАЖДОЙ объявленной оси прибора «реестр → бегун».

ADR-1006 дал спутника ОДНОЙ оси (`door_foreign_param`): рядом со статическим счётом «дверь
каталога не у связанного имени» встал наблюдённый ответ «а писал ли под бегуном хоть один». Дефект,
однако, не принадлежал той оси — он принадлежит ФОРМЕ числа: «сколько модулей ДОСТИГАЮТ записи»
читается как «сколько модулей ПИШУТ», и у двух соседних осей того же прибора
(`default_reached_under_sandbox` 251 и `door_unresolved` 5) население этого прочтения не было
измерено вовсе (ADR-1006 § 6г, заказ G996 п. 1г).

Что держат эти тесты — по ИСХОДУ `axis_observed`/`observed_axes`/`render`, а не по подстроке
(ADR-333):

* **перечень осей — объявление**, а не выбор зова: `observed_axes` отвечает РОВНО об
  `OBSERVED_AXES`, неизвестная ось и неизвестное правило предмета — отказ `NotMeasured`
  (fail-CLOSED), а не пустой ответ;
* **предмет оси «умолчание достижимо» считает ТА ЖЕ дверь, которой его считает `measure()`**
  (`_exposed_under_sandbox`) — контроль в обе стороны: при `passes_data_dir=True` модуль
  `CONTEXT_PARAM` из предмета исключён, при `False` — включён. Вторая копия правила отвечала бы про
  другое население, чем печатаемый рядом счёт;
* **расхождение предмета с печатаемым счётом — третий исход** (`parity.agrees False`), отсутствие
  счёта в сводке — `None`, и в ОБОИХ случаях заработанный вывод НЕ печатается (инв. #17);
* три исхода различимы у любой оси: наблюдения не было ⇒ `UNMEASURED` у каждого модуля (не ноль);
  модуля нет в результатах ⇒ `UNMEASURED` со СВОЕЙ причиной;
* **`silent_by_status` отличает «вошёл и промолчал» (`ok`) от «бегун не вошёл» (`unchecked`)** и
  суммируется в `SILENT`: на оси в 251 модуль поимённый перечень обрезан, и без свёртки это
  различение пропало бы у самой крупной оси;
* вывод печатается только когда ЗАРАБОТАН: писавших нет ⇒ «ни один не писал»; писавшие есть ⇒
  называется ЗАЗОР «счёт минус записи»; ненаблюдённый хоть один ⇒ молчание;
* `foreign_observed` остаётся тем же ответом, что `axis_observed(..., "door_foreign_param")` —
  своего разбора у него больше нет;
* живое дерево: у КАЖДОЙ объявленной оси предмет равен своему счёту, а `--json` несёт спутника
  всех осей всегда — без наблюдения он несёт НЕ ИЗМЕРЕНО, а не нули.

Прод-`data/` ни одна сцена не трогает: наблюдение здесь не запускается — оно подаётся сценой.
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CENSUS_PATH = ROOT / "scripts" / "registry_runner_write_census.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rrwc = _load(CENSUS_PATH, "spa_registry_runner_write_census_observed_axes")


def _verdict(module: str, door: str = "NONE", verdict: str = "WRITE_REACHABLE"):
    return rrwc.ModuleVerdict(
        module=module, tier="B", path=f"spa_core/analytics/{module}.py",
        registry_class=None, runner_target="class", entry="analyze",
        verdict=verdict, reads_context_data_dir=door != "NONE", data_dir_door=door)


def _census(modules, *, passes_data_dir: bool = True, exposure=None, code: int = 1):
    """Сцена. `exposure` по умолчанию считается ТЕМИ ЖЕ правилами, что у `measure()`."""
    runner = rrwc.RunnerSide(entry_methods=("analyze",), passes_data_dir=passes_data_dir,
                             runner_path="spa_core/analytics/signal_aggregator.py")
    mods = list(modules)
    if exposure is None:
        exposure = {
            "door_foreign_param": sum(1 for m in mods if m.data_dir_door == "FOREIGN_PARAM"),
            "door_unresolved": sum(1 for m in mods if m.data_dir_door == "UNRESOLVED"),
            "default_reached_under_sandbox": sum(
                1 for m in mods if rrwc._exposed_under_sandbox(runner, m)),
        }
    return rrwc.Census(root="/tmp/scene", modules=mods, runner=runner,
                       counts={"WRITE_REACHABLE": len(mods)}, exposure=exposure,
                       blind_subset=None, code=code)


def _obs(results):
    """Минимальное наблюдение в той форме, в которой его отдаёт `observe()`."""
    return {"repo": "/tmp/scene_copy", "protocol": "aave_v3", "timeout": 3.0,
            "modules": len(results), "statuses": {}, "baskets": {},
            "writers": [r for r in results if any(r["written"].values())],
            "per_module": results, "elsewhere_in_tree": [], "parity": {},
            "observer_returncode": 0, "observer_stderr_tail": ""}


def _res(module: str, status: str, written=None):
    return {"module": module, "status": status, "written": written or {}}


class DeclaredAxes(unittest.TestCase):
    """Перечень осей — ОБЪЯВЛЕНИЕ, и вне него прибор отказывает, а не отвечает пустым."""

    def test_declared_axes_carry_description_rule_and_earned_tail(self):
        self.assertIn("door_foreign_param", rrwc.OBSERVED_AXES)
        self.assertIn("door_unresolved", rrwc.OBSERVED_AXES)
        self.assertIn("default_reached_under_sandbox", rrwc.OBSERVED_AXES)
        for axis, value in rrwc.OBSERVED_AXES.items():
            self.assertEqual(len(value), 3, f"ось {axis}: объявление не тройное")
            description, rule, tail = value
            self.assertTrue(description.strip(), f"ось {axis}: статика не названа")
            self.assertTrue(tail.strip(), f"ось {axis}: довесок вывода не назван")
            self.assertTrue(rule == "exposed" or rule.startswith("door:"),
                            f"ось {axis}: правило предмета `{rule}` не из объявленных форм")

    def test_observed_axes_answers_exactly_the_declared_set(self):
        c = _census([_verdict("f_one", "FOREIGN_PARAM")])
        self.assertEqual(set(rrwc.observed_axes(c, None)), set(rrwc.OBSERVED_AXES))

    def test_undeclared_axis_is_a_refusal_not_an_empty_answer(self):
        c = _census([_verdict("f_one", "FOREIGN_PARAM")])
        with self.assertRaises(rrwc.NotMeasured):
            rrwc.axis_observed(c, None, "door_context_param")

    def test_unknown_subject_rule_is_a_refusal(self):
        """Ось объявлена, а правило предмета прибору неизвестно ⇒ отказ, не «предмет пуст»."""
        c = _census([_verdict("f_one", "FOREIGN_PARAM")])
        saved = dict(rrwc.OBSERVED_AXES)
        rrwc.OBSERVED_AXES["door_invented"] = ("выдуманная ось", "по_настроению", "вывод")
        try:
            with self.assertRaises(rrwc.NotMeasured):
                rrwc.axis_observed(c, None, "door_invented")
        finally:
            rrwc.OBSERVED_AXES.clear()
            rrwc.OBSERVED_AXES.update(saved)

    def test_unknown_door_outcome_in_a_rule_is_a_refusal(self):
        c = _census([_verdict("f_one", "FOREIGN_PARAM")])
        saved = dict(rrwc.OBSERVED_AXES)
        rrwc.OBSERVED_AXES["door_invented"] = ("выдуманная ось", "door:НЕБЫВАЛЫЙ", "вывод")
        try:
            with self.assertRaises(rrwc.NotMeasured):
                rrwc.axis_observed(c, None, "door_invented")
        finally:
            rrwc.OBSERVED_AXES.clear()
            rrwc.OBSERVED_AXES.update(saved)


class AxisSubjectIsOneMeasureWithTheCount(unittest.TestCase):
    """Предмет оси и печатаемый рядом счёт — ОДНА мерка, и расхождение = НЕ ИЗМЕРЕНО."""

    def test_door_axes_pick_exactly_their_own_door(self):
        c = _census([_verdict("f_one", "FOREIGN_PARAM"), _verdict("u_one", "UNRESOLVED"),
                     _verdict("ctx_one", "CONTEXT_PARAM"), _verdict("none_one", "NONE")])
        self.assertEqual([e["module"] for e in
                          rrwc.axis_observed(c, None, "door_foreign_param")["per_module"]],
                         ["f_one"])
        self.assertEqual([e["module"] for e in
                          rrwc.axis_observed(c, None, "door_unresolved")["per_module"]],
                         ["u_one"])

    def test_exposed_axis_uses_the_same_door_as_measure_both_ways(self):
        """Контроль в обе стороны: закрытая дверь бегуна исключает `CONTEXT_PARAM`, открытая — нет."""
        mods = [_verdict("ctx_one", "CONTEXT_PARAM"), _verdict("f_one", "FOREIGN_PARAM"),
                _verdict("no_entry", "NONE", verdict="NO_ENTRY")]
        passing = _census(mods, passes_data_dir=True)
        self.assertEqual(
            [e["module"] for e in
             rrwc.axis_observed(passing, None, "default_reached_under_sandbox")["per_module"]],
            ["f_one"])
        not_passing = _census(mods, passes_data_dir=False)
        self.assertEqual(
            sorted(e["module"] for e in
                   rrwc.axis_observed(not_passing, None, "default_reached_under_sandbox")["per_module"]),
            ["ctx_one", "f_one"])

    def test_lying_exposure_count_is_unmeasured_and_kills_the_verdict(self):
        """Положительный контроль двух мерок: счёт говорит 9, предмет — 2 ⇒ вывод НЕ печатается."""
        c = _census([_verdict("f_a", "FOREIGN_PARAM"), _verdict("f_b", "FOREIGN_PARAM")],
                    exposure={"door_foreign_param": 9})
        fo = rrwc.axis_observed(c, _obs([_res("f_a", "ok"), _res("f_b", "ok")]),
                                "door_foreign_param")
        self.assertEqual(fo["parity"], {"exposure": 9, "subject": 2, "agrees": False})
        text = rrwc.render(c, _obs([_res("f_a", "ok"), _res("f_b", "ok")]))
        self.assertIn("НЕ ИЗМЕРЕНО: предмет оси", text)
        self.assertNotIn("переносить дверью в каталог", text)

    def test_missing_exposure_count_is_none_not_agreement(self):
        c = _census([_verdict("f_a", "FOREIGN_PARAM")], exposure={})
        fo = rrwc.axis_observed(c, _obs([_res("f_a", "ok")]), "door_foreign_param")
        self.assertIsNone(fo["parity"]["agrees"])
        self.assertIsNone(fo["parity"]["exposure"])
        self.assertNotIn("переносить дверью в каталог", rrwc.render(c, _obs([_res("f_a", "ok")])))


class ThreeOutcomesOnEveryAxis(unittest.TestCase):
    """Исходы и их основания одинаковы у любой оси, и «не мерили» нулём не считается."""

    def test_no_observation_is_unmeasured_on_the_new_axes(self):
        c = _census([_verdict("f_one", "FOREIGN_PARAM"), _verdict("u_one", "UNRESOLVED")])
        for axis in ("door_unresolved", "default_reached_under_sandbox"):
            fo = rrwc.axis_observed(c, None, axis)
            self.assertEqual(fo["outcomes"]["UNMEASURED"], fo["subject"], axis)
            self.assertEqual(fo["outcomes"]["WROTE"], 0, axis)
            self.assertEqual(fo["outcomes"]["SILENT"], 0, axis)
            self.assertIsNotNone(fo["unmeasured_reason"], axis)
            self.assertEqual(sum(fo["outcomes"].values()), fo["subject"], axis)

    def test_module_absent_from_observation_has_its_own_reason(self):
        c = _census([_verdict("u_seen", "UNRESOLVED"), _verdict("u_unseen", "UNRESOLVED")])
        fo = rrwc.axis_observed(c, _obs([_res("u_seen", "unchecked")]), "door_unresolved")
        by = {e["module"]: e for e in fo["per_module"]}
        self.assertEqual(by["u_unseen"]["outcome"], "UNMEASURED")
        self.assertIsNotNone(by["u_unseen"]["reason"])
        self.assertIsNone(fo["unmeasured_reason"])

    def test_empty_basket_is_not_a_write_on_the_exposed_axis(self):
        c = _census([_verdict("e_one", "NONE")])
        fo = rrwc.axis_observed(c, _obs([_res("e_one", "ok", {"tree_data": []})]),
                                "default_reached_under_sandbox")
        self.assertEqual(fo["outcomes"]["WROTE"], 0)
        self.assertEqual(fo["per_module"][0]["outcome"], "SILENT")

    def test_silent_by_status_separates_entered_from_not_entered(self):
        """«Вошёл и промолчал» и «бегун не вошёл» — разные основания тишины, и свёртка их держит."""
        c = _census([_verdict("a", "NONE"), _verdict("b", "NONE"), _verdict("c", "NONE")])
        fo = rrwc.axis_observed(
            c, _obs([_res("a", "ok"), _res("b", "unchecked"), _res("c", "unchecked")]),
            "default_reached_under_sandbox")
        self.assertEqual(fo["silent_by_status"], {"ok": 1, "unchecked": 2})
        self.assertEqual(sum(fo["silent_by_status"].values()), fo["outcomes"]["SILENT"])

    def test_writers_are_not_counted_in_silent_by_status(self):
        c = _census([_verdict("w", "NONE"), _verdict("q", "NONE")])
        fo = rrwc.axis_observed(
            c, _obs([_res("w", "ok", {"tree_data": ["x.json"]}), _res("q", "ok")]),
            "default_reached_under_sandbox")
        self.assertEqual(fo["outcomes"], {"WROTE": 1, "SILENT": 1, "UNMEASURED": 0})
        self.assertEqual(fo["silent_by_status"], {"ok": 1})


class EarnedVerdictOnEveryAxis(unittest.TestCase):
    """Вывод печатается только заработанным, и у писавших называется ЗАЗОР, а не «всё хорошо»."""

    def test_nothing_wrote_prints_the_axis_own_tail(self):
        c = _census([_verdict("u_a", "UNRESOLVED"), _verdict("u_b", "UNRESOLVED")])
        text = rrwc.render(c, _obs([_res("u_a", "unchecked"), _res("u_b", "unchecked")]))
        self.assertIn(rrwc.OBSERVED_AXES["door_unresolved"][2], text)

    def test_writers_make_the_gap_a_named_number(self):
        mods = [_verdict(f"m{i}", "NONE") for i in range(4)]
        c = _census(mods)
        obs = _obs([_res("m0", "ok", {"tree_data": ["a.json"]}), _res("m1", "ok"),
                    _res("m2", "ok"), _res("m3", "unchecked")])
        text = rrwc.render(c, obs)
        self.assertIn("писали 1 из 4", text)
        self.assertIn("БОЛЬШЕ числа наблюдённых записей на 3", text)
        self.assertNotIn(rrwc.OBSERVED_AXES["default_reached_under_sandbox"][2], text)

    def test_all_wrote_says_the_counts_agree(self):
        c = _census([_verdict("m0", "NONE"), _verdict("m1", "NONE")])
        obs = _obs([_res("m0", "ok", {"tree_data": ["a.json"]}),
                    _res("m1", "ok", {"cwd_data": ["b.json"]})])
        text = rrwc.render(c, obs)
        self.assertIn("писали 2 из 2", text)
        self.assertIn("совпал с числом наблюдённых записей", text)

    def test_one_unobserved_module_silences_both_verdicts(self):
        """Контроль в обе стороны: ненаблюдённый ⇒ ни «не писал», ни зазор."""
        c = _census([_verdict("m0", "NONE"), _verdict("m1", "NONE")])
        text = rrwc.render(c, _obs([_res("m0", "ok")]))
        self.assertNotIn(rrwc.OBSERVED_AXES["default_reached_under_sandbox"][2], text)
        self.assertNotIn("писали", text)

    def test_axis_block_is_absent_when_the_subject_is_empty(self):
        c = _census([_verdict("ctx_one", "CONTEXT_PARAM")], code=0)
        text = rrwc.render(c, None)
        self.assertNotIn("наблюдённый спутник", text)

    def test_long_axis_names_the_tail_it_did_not_print(self):
        mods = [_verdict(f"m{i}", "NONE") for i in range(45)]
        text = rrwc.render(_census(mods), None)
        self.assertIn("и ещё 5", text)
        self.assertIn("observed_axes.default_reached_under_sandbox", text)


class BackwardCompatibility(unittest.TestCase):
    """`foreign_observed` — тот же ответ, что у объявленной оси: второго разбора нет."""

    def test_foreign_observed_delegates_to_the_axis(self):
        c = _census([_verdict("f_a", "FOREIGN_PARAM"), _verdict("ctx", "CONTEXT_PARAM")])
        obs = _obs([_res("f_a", "ok"), _res("ctx", "ok")])
        self.assertEqual(rrwc.foreign_observed(c, obs),
                         rrwc.axis_observed(c, obs, "door_foreign_param"))

    def test_outcome_vocabulary_is_still_the_declared_triple(self):
        self.assertEqual(rrwc.FOREIGN_OBSERVED_OUTCOMES, ("WROTE", "SILENT", "UNMEASURED"))
        c = _census([_verdict("f_a", "FOREIGN_PARAM")])
        for axis in rrwc.OBSERVED_AXES:
            fo = rrwc.axis_observed(c, _obs([_res("f_a", "ok")]), axis)
            self.assertEqual(set(fo["outcomes"]), set(rrwc.FOREIGN_OBSERVED_OUTCOMES), axis)


class ObservedAxesOnTheLiveTree(unittest.TestCase):
    """Живое дерево: у КАЖДОЙ оси предмет равен своему счёту, и без наблюдения всё НЕ ИЗМЕРЕНО."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(subprocess.run(
            [sys.executable, str(CENSUS_PATH), "--repo-root", str(ROOT), "--json"],
            capture_output=True, text=True, check=False).stdout)

    def test_json_always_carries_every_declared_axis(self):
        self.assertIn("observed_axes", self.doc)
        self.assertEqual(set(self.doc["observed_axes"]), set(rrwc.OBSERVED_AXES))

    def test_live_subject_equals_its_own_count_on_every_axis(self):
        for axis, fo in self.doc["observed_axes"].items():
            self.assertEqual(fo["parity"]["agrees"], True, axis)
            self.assertEqual(fo["subject"], self.doc["exposure"][axis], axis)
            self.assertEqual(sum(fo["outcomes"].values()), fo["subject"], axis)

    def test_live_axes_are_not_empty(self):
        """Пустой предмет не держал бы ничего: оси должны быть населены на живом дереве."""
        for axis in rrwc.OBSERVED_AXES:
            self.assertGreater(self.doc["observed_axes"][axis]["subject"], 0, axis)

    def test_live_run_without_observation_is_unmeasured_everywhere(self):
        for axis, fo in self.doc["observed_axes"].items():
            self.assertEqual(fo["outcomes"]["UNMEASURED"], fo["subject"], axis)
            self.assertEqual(fo["silent_by_status"], {}, axis)
            self.assertIsNotNone(fo["unmeasured_reason"], axis)


if __name__ == "__main__":
    unittest.main()
