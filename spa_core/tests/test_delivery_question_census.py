"""Приёмка переписи «производная мера без вопроса в момент доставки» (ADR-1127).

Каждая проба — сцена на ОДНОРАЗОВОМ дереве, и у каждой оси есть обратная
половина: проба, которая КРАСНЕЕТ при порванном звене с НАЗВАННЫМ звеном
(порядок `.claude/rules/acceptance.md` п. 3).

Сцена несёт НАСТОЯЩИЙ прибор набор-зависимости (`derived_artifact_census.py`
копируется из дерева): своей копии классификации у переписи нет, и сцена,
подменившая её заглушкой, мерила бы заглушку.

FROZEN-DATE-OK: no-dates — ни одна проба этого файла о сроке не судит, якоря
времени в сцене нет вовсе.
"""

from __future__ import annotations

import importlib.util
import pathlib
import shutil
import sys
import tempfile
import unittest

REPO = pathlib.Path(__file__).resolve().parents[2]
PROBER = REPO / "scripts" / "delivery_question_census.py"


def _load():
    spec = importlib.util.spec_from_file_location("_dqc_under_test", PROBER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


DQC = _load()


PUSHER = '''\
"""Дверь доставки сцены. Производитель называется ЗАГРУЗЧИКОМ, не гейтом."""
import pathlib

JUDGED_REL = "proj/sub/INDEX.md"


def _load_producer(base):
    "scripts/never_a_producer.py"
    return pathlib.Path(base) / "scripts" / "make_index.py"


def enforce_delivery_index_row(file_args):
    producer = _load_producer(pathlib.Path("."))
    return [producer, JUDGED_REL]


def guard_unrelated(file_args):
    return []
'''

REGISTER = '''\
# Реестр решений сцены

| № | Заголовок | Статус | Файл |
|---|---|---|---|
| ADR-001 | ADR-001 — Доставка не спрашивала, НАЗОВЁТ ли индекс строку | Accepted | [x](ADR-001-door.md) |
| ADR-002 | ADR-002 — что-то совсем другое, дверью не являющееся | Accepted | [x](ADR-002-other.md) |
'''

DOOR_ADR = """\
# ADR-001 — дверь сцены

Гейт — `enforce_delivery_index_row`, сторож — `test_index_row.py`.
"""

#: Сторож ДВЕРИ: перечисляет тот же каталог, что судит гейт ⇒ связка по каталогу.
GUARD_GATED = '''\
import pathlib
PROJ = pathlib.Path(__file__).resolve().parents[2] / "proj" / "sub"


def test_index_names_every_card():
    assert sorted(PROJ.glob("*.md")) is not None
'''

#: Сторож БЕЗ двери: перечисляет СВОЙ каталог, которого не судит ни один гейт.
GUARD_SUBJECT = '''\
import pathlib
OTHER = pathlib.Path(__file__).resolve().parents[2] / "other"


def test_other_set():
    assert sorted(OTHER.glob("*.md")) is not None
'''

#: Сторож, чей путь прибор не разберёт ⇒ третий исход.
GUARD_UNRESOLVED = '''\
import os
import pathlib


def test_unresolved(where=None):
    base = pathlib.Path(os.environ["SOMEWHERE_UNKNOWN"])
    assert sorted(base.glob("*.md")) is not None
'''


#: Сторож, у которого судимый путь стоит РОВНО докстрингом — и больше нигде.
#: Без исключения докстрингов он ложно вышел бы `gated` — мутация
#: «докстринги больше не исключаются» переживала сцену без этой половины.
GUARD_DOCSTRING_ONLY = '''\
"proj/sub/INDEX.md"
import pathlib
OTHER = pathlib.Path(__file__).resolve().parents[2] / "other"


def test_prose_is_not_a_reading():
    "proj/sub/INDEX.md"
    assert sorted(OTHER.glob("*.md")) is not None
'''


def _scene(tmp: pathlib.Path, *, pusher=PUSHER, register=REGISTER,
           door_adr=DOOR_ADR, guards=None) -> pathlib.Path:
    root = tmp / "scene"
    (root / "scripts").mkdir(parents=True)
    (root / "spa_core" / "tests").mkdir(parents=True)
    (root / "docs" / "decisions").mkdir(parents=True)
    (root / "proj" / "sub").mkdir(parents=True)
    (root / "other").mkdir()
    (root / "proj" / "sub" / "INDEX.md").write_text("x\n", encoding="utf-8")
    (root / "other" / "a.md").write_text("x\n", encoding="utf-8")
    if pusher is not None:
        (root / "push_to_github.py").write_text(pusher, encoding="utf-8")
    if register is not None:
        (root / "docs" / "decisions" / "INDEX.md").write_text(register, encoding="utf-8")
    if door_adr is not None:
        (root / "docs" / "decisions" / "ADR-001-door.md").write_text(door_adr, encoding="utf-8")
    (root / "scripts" / "make_index.py").write_text("X = 1\n", encoding="utf-8")
    # НАСТОЯЩИЙ прибор набор-зависимости — не заглушка
    shutil.copy2(REPO / "scripts" / "derived_artifact_census.py", root / "scripts")
    for name, body in (guards or {
        "test_index_row.py": GUARD_GATED,
        "test_other_shape.py": GUARD_SUBJECT,
    }).items():
        (root / "spa_core" / "tests" / name).write_text(body, encoding="utf-8")
    return root


class SceneMixin(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="dqc_"))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        # ввоз прибора из сцены не должен пережить сцену (урок ADR-1075:
        # подмена, пережившая сцену, вредит СОСЕДУ по процессу)
        self._modules = set(sys.modules)
        self._syspath = list(sys.path)
        self.addCleanup(self._restore)

    def _restore(self):
        for name in set(sys.modules) - self._modules:
            sys.modules.pop(name, None)
        sys.path[:] = self._syspath


class TestVerdictsAreDistinguishable(SceneMixin):
    def test_gated_and_subject_are_told_apart(self):
        root = _scene(self.tmp)
        report = DQC.measure(root)
        verdicts = {g["path"]: g["verdict"] for g in report["guards"]}
        self.assertEqual(verdicts.get("spa_core/tests/test_index_row.py"), DQC.GATED)
        self.assertEqual(verdicts.get("spa_core/tests/test_other_shape.py"), DQC.SUBJECT)
        self.assertEqual(report["code"], 1, "предмет непуст ⇒ код 1")

    def test_no_subject_gives_code_zero(self):
        root = _scene(self.tmp, guards={"test_index_row.py": GUARD_GATED})
        report = DQC.measure(root)
        self.assertEqual(report["counts"].get(DQC.SUBJECT, 0), 0)
        self.assertEqual(report["code"], 0)

    def test_unresolved_guard_is_a_third_outcome_not_a_subject(self):
        root = _scene(self.tmp, guards={
            "test_index_row.py": GUARD_GATED,
            "test_fog.py": GUARD_UNRESOLVED,
        })
        report = DQC.measure(root)
        fog = [g for g in report["guards"] if g["path"].endswith("test_fog.py")]
        self.assertTrue(fog, "сторож с неразобранным путём обязан быть НАЗВАН")
        self.assertEqual(fog[0]["verdict"], DQC.UNMEASURED)
        self.assertIn("unresolved", fog[0]["reason"])

    def test_bracket_is_printed_and_counts_unmeasured_in(self):
        root = _scene(self.tmp, guards={
            "test_index_row.py": GUARD_GATED,
            "test_other_shape.py": GUARD_SUBJECT,
            "test_fog.py": GUARD_UNRESOLVED,
        })
        report = DQC.measure(root)
        text = DQC.render(report, names=False, limit=0)
        subject = report["counts"].get(DQC.SUBJECT, 0)
        unmeasured = report["counts"].get(DQC.UNMEASURED, 0)
        self.assertGreater(unmeasured, 0)
        self.assertIn(f"ВИЛКА {subject} … {subject + unmeasured}", text)


class TestTiesAreMeasuredNotGuessed(SceneMixin):
    def test_one_hop_through_the_loader_is_required(self):
        """Производитель назван ЗАГРУЗЧИКОМ. Без хопа дверь его не видит."""
        root = _scene(self.tmp)
        doors = DQC.delivery_doors(root)
        self.assertIn("make_index.py", doors["enforce_delivery_index_row"]["producers"])

    def test_docstring_mention_is_not_a_reading(self):
        """`scripts/never_a_producer.py` назван ТОЛЬКО в докстринге загрузчика."""
        root = _scene(self.tmp)
        doors = DQC.delivery_doors(root)
        producers = doors["enforce_delivery_index_row"]["producers"]
        self.assertNotIn("never_a_producer.py", producers)

    def test_docstring_mention_in_a_guard_is_not_a_tie(self):
        """Судимый путь в ПРОЗЕ сторожа связкой не является."""
        root = _scene(self.tmp, guards={
            "test_index_row.py": GUARD_GATED,
            "test_prose.py": GUARD_DOCSTRING_ONLY,
        })
        report = DQC.measure(root)
        verdicts = {g["path"]: g["verdict"] for g in report["guards"]}
        self.assertEqual(verdicts.get("spa_core/tests/test_prose.py"), DQC.SUBJECT)

    def test_directory_tie_is_equality_not_nesting(self):
        """Сторож, перечисляющий РОДИТЕЛЯ судимого каталога, двери НЕ имеет."""
        # РОДИТЕЛЬ судимого каталога, а не корень дерева: мутация
        # «связка стала вложенностью» на корне НЕ ловится — `proj/sub`
        # с точки не начинается, и сцена её пережила (замер #1273).
        nested = '''\
import pathlib
WIDE = pathlib.Path(__file__).resolve().parents[2] / "proj"


def test_wide():
    assert sorted(WIDE.glob("*/*.md")) is not None
'''
        root = _scene(self.tmp, guards={
            "test_index_row.py": GUARD_GATED,
            "test_wide.py": nested,
        })
        report = DQC.measure(root)
        verdicts = {g["path"]: g["verdict"] for g in report["guards"]}
        self.assertEqual(verdicts.get("spa_core/tests/test_wide.py"), DQC.SUBJECT)

    def test_gate_prefix_is_not_only_enforce_delivery(self):
        """`guard_*` — тоже дверь: соглашение об имени полнотой не является."""
        root = _scene(self.tmp)
        doors = DQC.delivery_doors(root)
        self.assertIn("guard_unrelated", doors)


class TestRegisterIsTheCompletenessDoor(SceneMixin):
    def test_register_names_the_door_and_the_control_passes(self):
        root = _scene(self.tmp)
        report = DQC.measure(root)
        self.assertIn("ADR-001", report["register_doors"])
        self.assertNotIn("ADR-002", report["register_doors"],
                         "строка не про дверь доставки в перечень попасть не вправе")
        self.assertEqual(report["control"]["ADR-001"], {"test_index_row.py": DQC.GATED})

    def test_broken_tie_refuses_instead_of_naming_a_number(self):
        """Реестр назвал сторожа, а связка его `gated` не делает ⇒ ОТКАЗ."""
        root = _scene(self.tmp, door_adr=DOOR_ADR.replace(
            "test_index_row.py", "test_other_shape.py"))
        with self.assertRaises(DQC.NotMeasured) as caught:
            DQC.measure(root)
        self.assertIn("test_other_shape.py", str(caught.exception))
        self.assertIn("связка", str(caught.exception))

    def test_register_without_a_single_door_row_refuses(self):
        root = _scene(self.tmp, register=REGISTER.replace(
            "Доставка не спрашивала, НАЗОВЁТ ли индекс строку", "обычное решение"))
        with self.assertRaises(DQC.NotMeasured) as caught:
            DQC.measure(root)
        self.assertIn("НИ ОДНОЙ двери", str(caught.exception))

    def test_gate_named_by_register_but_living_elsewhere_is_named_not_refused(self):
        root = _scene(self.tmp, door_adr=DOOR_ADR + "\nЕщё гейт: `enforce_in_another_module`.\n")
        report = DQC.measure(root)
        self.assertIn("enforce_in_another_module",
                      report["gates_named_by_register_but_elsewhere"])
        self.assertIn("enforce_in_another_module", DQC.render(report, False, 0))

    def test_door_adr_naming_no_guard_says_so(self):
        root = _scene(self.tmp, door_adr="# ADR-001\n\nГейт `enforce_delivery_index_row`.\n")
        report = DQC.measure(root)
        self.assertIn("не называет ни одного сторожа", report["control"]["ADR-001"])


class TestRefusalsAreLoud(SceneMixin):
    def test_missing_pusher_refuses(self):
        root = _scene(self.tmp, pusher=None)
        with self.assertRaises(DQC.NotMeasured) as caught:
            DQC.measure(root)
        self.assertIn("ни одной двери доставки", str(caught.exception))

    def test_pusher_without_a_gate_refuses(self):
        root = _scene(self.tmp, pusher="X = 1\n")
        with self.assertRaises(DQC.NotMeasured) as caught:
            DQC.measure(root)
        self.assertIn("ни одного", str(caught.exception))

    def test_unparsable_pusher_refuses(self):
        root = _scene(self.tmp, pusher="def broken(:\n")
        with self.assertRaises(DQC.NotMeasured) as caught:
            DQC.measure(root)
        self.assertIn("не разобрана", str(caught.exception))

    def test_missing_prober_refuses_instead_of_returning_zero(self):
        root = _scene(self.tmp)
        (root / "scripts" / "derived_artifact_census.py").unlink()
        with self.assertRaises(DQC.NotMeasured) as caught:
            DQC.measure(root)
        self.assertIn("не ввезён", str(caught.exception))

    def test_missing_register_refuses(self):
        root = _scene(self.tmp, register=None)
        with self.assertRaises(DQC.NotMeasured) as caught:
            DQC.measure(root)
        self.assertIn("НИ ОДНОЙ двери", str(caught.exception))

    def test_cli_returns_two_on_not_measured(self):
        root = _scene(self.tmp, pusher=None)
        self.assertEqual(DQC.main(["--repo-root", str(root)]), 2)

    def test_cli_prints_the_chosen_tree(self):
        root = _scene(self.tmp)
        report = DQC.measure(root)
        self.assertIn(str(root), DQC.render(report, False, 0))


class TestLiveTreeIsAnswerable(unittest.TestCase):
    """Живое дерево отвечает, и ответ — не ноль по построению."""

    def test_repo_is_measured_and_control_holds(self):
        report = DQC.measure(REPO)
        self.assertGreaterEqual(len(report["register_doors"]), 5,
                                "реестр обязан называть не меньше пяти дверей")
        self.assertTrue(report["counts"].get(DQC.GATED),
                        "хотя бы одна мера обязана быть под дверью")
        broken = {n: v for n, v in report["control"].items()
                  if isinstance(v, dict) and DQC.GATED not in v.values()}
        self.assertFalse(broken, f"связка сломана у {sorted(broken)}")


if __name__ == "__main__":
    unittest.main()
