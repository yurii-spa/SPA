"""ADR-1006 — наблюдённый СПУТНИК статической оси `FOREIGN_PARAM` у прибора «реестр → бегун».

Прибор `scripts/registry_runner_write_census.py` печатал две статические величины —
`door_foreign_param` (дверь каталога есть, но НЕ у того имени, в которое бегун биндит контекст,
ось ADR-1005) и `default_reached_under_sandbox` («умолчание ДОСТИЖИМО от входа бегуна») — и ни
одна из них не утверждает, что модуль под бегуном что-то ПИШЕТ. Прочитанные как перечень записей,
они родили в заказе G995 п. 1 (а) ожидание «корзина бегуна 1 → 12, дерево 47 → 36»; наблюдение
ЭТОГО ЖЕ прибора (`--observe`) говорило обратное — ни один из 12 под бегуном не писал вовсе, — но
печаталось отдельным блоком и про это подмножество молчало.

Что держат эти тесты — по ИСХОДУ `foreign_observed`/`render`, а не по подстроке (ADR-333):

* предмет спутника — РОВНО `FOREIGN_PARAM`: `CONTEXT_PARAM`, `UNRESOLVED` и `NONE` в него не входят
  (иначе спутник отвечал бы про чужую ось);
* наблюдение видело запись ⇒ `WROTE`, и корзины названы; позван, записи нет ⇒ `SILENT`, и СТАТУС
  бегуна несётся рядом — именно он отличает «вошёл и промолчал» (`ok`) от «бегун не вошёл»
  (`unchecked`);
* **наблюдения не было ⇒ `UNMEASURED` у каждого модуля предмета, и это НЕ ноль** (инв. #17):
  текст говорит «НЕ ИЗМЕРЕНО N» с причиной, а вывод «переносить нечего» НЕ печатается;
* модуль, которого нет в результатах наблюдения, — тоже `UNMEASURED` со СВОЕЙ причиной, а не
  `SILENT`: «не наблюдали» и «наблюдали и тихо» — разные ответы;
* вывод «переносить дверью НЕЧЕГО» печатается ТОЛЬКО когда ненаблюдённых нет И писавших нет —
  при единственном писателе или единственном ненаблюдённом он молчит (контроль в обе стороны);
* пустая корзина (`{"tree_data": []}`) записью НЕ является — иначе «ключ есть» выдавалось бы за
  «писал»;
* три исхода суммируются в предмет, и словарь исходов — `FOREIGN_OBSERVED_OUTCOMES`, а не пара;
* живое дерево: предмет непуст, без наблюдения все его модули `UNMEASURED`, а `--json` несёт
  спутника всегда.

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


rrwc = _load(CENSUS_PATH, "spa_registry_runner_write_census_foreign_observed")


def _verdict(module: str, door: str, verdict: str = "WRITE_REACHABLE"):
    return rrwc.ModuleVerdict(
        module=module, tier="B", path=f"spa_core/analytics/{module}.py",
        registry_class=None, runner_target="class", entry="analyze",
        verdict=verdict, reads_context_data_dir=True, data_dir_door=door)


def _census(modules, code: int = 1):
    return rrwc.Census(
        root="/tmp/scene", modules=list(modules),
        runner=rrwc.RunnerSide(entry_methods=("analyze",), passes_data_dir=True,
                               runner_path="spa_core/analytics/signal_aggregator.py"),
        counts={"WRITE_REACHABLE": len(modules)},
        exposure={"door_foreign_param": sum(1 for m in modules
                                            if m.data_dir_door == "FOREIGN_PARAM")},
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


class ForeignObservedSubject(unittest.TestCase):
    """Предмет спутника — РОВНО `FOREIGN_PARAM`, ни одной чужой оси."""

    def test_only_foreign_param_is_the_subject(self):
        c = _census([_verdict("f_one", "FOREIGN_PARAM"),
                     _verdict("ctx_one", "CONTEXT_PARAM"),
                     _verdict("unres_one", "UNRESOLVED", verdict="NO_ENTRY"),
                     _verdict("none_one", "NONE")])
        fo = rrwc.foreign_observed(c, _obs([_res("f_one", "ok"), _res("ctx_one", "ok"),
                                            _res("unres_one", "unchecked"), _res("none_one", "ok")]))
        self.assertEqual(fo["subject"], 1)
        self.assertEqual([e["module"] for e in fo["per_module"]], ["f_one"])

    def test_empty_subject_prints_no_block(self):
        c = _census([_verdict("ctx_one", "CONTEXT_PARAM")], code=0)
        fo = rrwc.foreign_observed(c, None)
        self.assertEqual(fo["subject"], 0)
        self.assertNotIn("наблюдённый спутник", rrwc.render(c, None))

    def test_outcome_vocabulary_is_the_declared_triple(self):
        self.assertEqual(rrwc.FOREIGN_OBSERVED_OUTCOMES, ("WROTE", "SILENT", "UNMEASURED"))
        c = _census([_verdict("f_one", "FOREIGN_PARAM")])
        fo = rrwc.foreign_observed(c, _obs([_res("f_one", "ok")]))
        self.assertEqual(set(fo["outcomes"]), set(rrwc.FOREIGN_OBSERVED_OUTCOMES))
        self.assertEqual(sum(fo["outcomes"].values()), fo["subject"])


class ForeignObservedOutcomes(unittest.TestCase):
    """Три исхода различимы, и каждый несёт своё основание."""

    def test_observed_write_is_wrote_with_named_baskets(self):
        c = _census([_verdict("f_writer", "FOREIGN_PARAM")])
        fo = rrwc.foreign_observed(
            c, _obs([_res("f_writer", "ok", {"tree_data": ["drag_log.json"]})]))
        self.assertEqual(fo["outcomes"], {"WROTE": 1, "SILENT": 0, "UNMEASURED": 0})
        entry = fo["per_module"][0]
        self.assertEqual(entry["outcome"], "WROTE")
        self.assertEqual(entry["written"], {"tree_data": ["drag_log.json"]})
        self.assertIsNone(entry["reason"])

    def test_invoked_but_silent_carries_the_runner_status(self):
        """`ok` и `unchecked` — РАЗНЫЕ основания тишины, и оба обязаны быть видны."""
        c = _census([_verdict("f_quiet", "FOREIGN_PARAM"), _verdict("f_absent", "FOREIGN_PARAM")])
        fo = rrwc.foreign_observed(c, _obs([_res("f_quiet", "ok"), _res("f_absent", "unchecked")]))
        self.assertEqual(fo["outcomes"], {"WROTE": 0, "SILENT": 2, "UNMEASURED": 0})
        by = {e["module"]: e for e in fo["per_module"]}
        self.assertEqual(by["f_quiet"]["runner_status"], "ok")
        self.assertEqual(by["f_absent"]["runner_status"], "unchecked")

    def test_empty_basket_list_is_not_a_write(self):
        """`{"tree_data": []}` — ключ есть, записи нет: иначе «писал» выдавалось бы за наблюдение."""
        c = _census([_verdict("f_quiet", "FOREIGN_PARAM")])
        fo = rrwc.foreign_observed(c, _obs([_res("f_quiet", "ok", {"tree_data": []})]))
        self.assertEqual(fo["outcomes"]["WROTE"], 0)
        self.assertEqual(fo["per_module"][0]["outcome"], "SILENT")

    def test_no_observation_is_unmeasured_not_zero(self):
        """Инв. #17: наблюдения не было ⇒ у КАЖДОГО модуля предмета `UNMEASURED` с причиной."""
        c = _census([_verdict("f_one", "FOREIGN_PARAM"), _verdict("f_two", "FOREIGN_PARAM")])
        fo = rrwc.foreign_observed(c, None)
        self.assertEqual(fo["outcomes"], {"WROTE": 0, "SILENT": 0, "UNMEASURED": 2})
        self.assertIsNotNone(fo["unmeasured_reason"])
        for e in fo["per_module"]:
            self.assertEqual(e["outcome"], "UNMEASURED")
            self.assertEqual(e["reason"], fo["unmeasured_reason"])

    def test_module_missing_from_observation_is_unmeasured_with_its_own_reason(self):
        """«Не наблюдали этот модуль» ≠ «наблюдали и он промолчал»."""
        c = _census([_verdict("f_seen", "FOREIGN_PARAM"), _verdict("f_unseen", "FOREIGN_PARAM")])
        fo = rrwc.foreign_observed(c, _obs([_res("f_seen", "ok")]))
        self.assertEqual(fo["outcomes"], {"WROTE": 0, "SILENT": 1, "UNMEASURED": 1})
        by = {e["module"]: e for e in fo["per_module"]}
        self.assertEqual(by["f_unseen"]["outcome"], "UNMEASURED")
        self.assertIsNotNone(by["f_unseen"]["reason"])
        self.assertNotEqual(by["f_unseen"]["reason"], fo["unmeasured_reason"])
        self.assertIsNone(fo["unmeasured_reason"])


class ForeignObservedRender(unittest.TestCase):
    """Текст несёт три числа всегда, а ВЫВОД — только когда он заработан."""

    def test_text_names_three_outcomes_and_the_cause_when_unobserved(self):
        c = _census([_verdict("f_one", "FOREIGN_PARAM")])
        text = rrwc.render(c, None)
        self.assertIn("НЕ ИЗМЕРЕНО 1", text)
        self.assertIn("--observe", text)
        self.assertNotIn("переносить дверью в каталог", text)

    def test_verdict_nothing_to_move_fires_only_when_earned(self):
        """Контроль в обе стороны: один писатель ИЛИ один ненаблюдённый — и вывода нет."""
        quiet = _census([_verdict("f_a", "FOREIGN_PARAM"), _verdict("f_b", "FOREIGN_PARAM")])
        earned = rrwc.render(quiet, _obs([_res("f_a", "ok"), _res("f_b", "unchecked")]))
        self.assertIn("переносить дверью в каталог", earned)

        with_writer = rrwc.render(quiet, _obs([
            _res("f_a", "ok", {"runner_dir": ["a_log.json"]}), _res("f_b", "ok")]))
        self.assertNotIn("переносить дверью в каталог", with_writer)

        with_gap = rrwc.render(quiet, _obs([_res("f_a", "ok")]))
        self.assertNotIn("переносить дверью в каталог", with_gap)

    def test_text_names_the_basket_of_a_writer(self):
        c = _census([_verdict("f_writer", "FOREIGN_PARAM")])
        text = rrwc.render(c, _obs([_res("f_writer", "ok", {"runner_dir": ["w_log.json"]})]))
        self.assertIn("f_writer: WROTE", text)
        self.assertIn("w_log.json", text)


class ForeignObservedOnTheLiveTree(unittest.TestCase):
    """Живое дерево: предмет непуст, и без наблюдения прибор о нём НЕ ИЗМЕРЕНО, а не нуль."""

    @classmethod
    def setUpClass(cls):
        cls.doc = json.loads(subprocess.run(
            [sys.executable, str(CENSUS_PATH), "--repo-root", str(ROOT), "--json"],
            capture_output=True, text=True, check=False).stdout)

    def test_json_always_carries_the_companion(self):
        self.assertIn("foreign_observed", self.doc)
        fo = self.doc["foreign_observed"]
        self.assertEqual(set(fo["outcomes"]), set(rrwc.FOREIGN_OBSERVED_OUTCOMES))
        self.assertEqual(sum(fo["outcomes"].values()), fo["subject"])

    def test_live_subject_matches_the_static_axis(self):
        fo = self.doc["foreign_observed"]
        self.assertEqual(fo["subject"], self.doc["exposure"]["door_foreign_param"])
        self.assertGreater(fo["subject"], 0, "предмет пуст — сцена живого дерева ничего не держит")

    def test_live_run_without_observation_answers_unmeasured(self):
        fo = self.doc["foreign_observed"]
        self.assertEqual(fo["outcomes"]["UNMEASURED"], fo["subject"])
        self.assertEqual(fo["outcomes"]["WROTE"], 0)
        self.assertEqual(fo["outcomes"]["SILENT"], 0)
        self.assertIsNotNone(fo["unmeasured_reason"])


if __name__ == "__main__":
    unittest.main()
