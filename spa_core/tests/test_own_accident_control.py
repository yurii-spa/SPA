#!/usr/bin/env python3
"""Приёмка переписи «прибор, не видящий своей аварии» (заказ G921 п. 2).

Положительный контроль у этой переписи обязан быть ОСОБЫМ, и причина названа
её же предметом: перепись, умеющая отвечать ТОЛЬКО «видит», отвечала бы о СВОЁМ
ОХВАТЕ под видом ответа о приборах — буквально тот дефект, который она ищет.
Поэтому первая проверка ниже предъявляет ей **заведомо слепой прибор** и
требует вердикта ``blind``; вторая — заведомо зрячий, и требует ``sees``.

Второй класс проверок — ОТКАЗЫ, и каждый из них есть НАСТОЯЩАЯ ошибка этого же
цикла, а не придуманная:

* **вакуумная примета.** Сцена манифеста объявляла приметой аварии подстроку
  ``ADR-``, которой манифест полон; сцена «применилась», не возмутив ничего, и
  перепись объявила исправный прибор СЛЕПЫМ. Теперь примета, присутствующая в
  СЕГОДНЯШНИХ байтах, — отказ (``unmeasured``), а не подтверждение.
* **сигнал не того рода.** У той же сцены ключом стояло ``on_prose``, а перенос
  привязки ``both → field_bypassed`` его НЕ двигает. Число ушедшее ВНИЗ или не
  туда — третий исход, а не «слеп».
* **восстановление в неразрешимой форме.** Сцена #567 выражала путь соседа через
  имя ``REPO_ROOT``, которого в том файле НЕТ, — утверждение не попадало в
  население ВОВСЕ. Байты, равные сегодняшним, и примета, не появившаяся в
  восстановленных байтах, — отказы.

Ошибка переписи идёт в сторону НАХОДКИ (ложно объявить исправный прибор слепым),
поэтому у каждой сцены обязанность доказать, что она возмутила ИМЕННО
объявленное, лежит на СЦЕНЕ, а не на читателе отчёта.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

_ROOT = pathlib.Path(__file__).resolve().parents[2]


from spa_core.tests import _own_accident_control as C


def _scene_repo(tmp: str, instrument_body: str) -> pathlib.Path:
    """Одноразовый репозиторий сцены: прибор + файл, в который вернётся авария.

    Имя ветки объявлено входом (`git init -b`): умолчание `init.defaultBranch`
    есть свойство ХОСТА (`.claude/rules/deployment.md` § GIT-ОКРУЖЕНИЕ).
    """
    root = pathlib.Path(tmp) / "repo"
    (root / "scripts").mkdir(parents=True)
    (root / "scripts" / "probe.py").write_text(instrument_body, encoding="utf-8")
    (root / "subject.py").write_text("VALUE = 'fixed'\n", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(root)],
                   capture_output=True, check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "t@t"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "t"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "-A"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "scene"],
                   capture_output=True, check=True)
    return root


#: Зрячий прибор: СЧИТАЕТ приметы аварии в дереве и докладывает число.
SIGHTED = (
    "import json,pathlib,sys\n"
    "root=pathlib.Path(sys.argv[1])\n"
    "n=sum(p.read_text().count('BOOM') for p in root.rglob('*.py'))\n"
    "print(json.dumps({'bomb': n}))\n"
)

#: Слепой прибор: разбирает ОДНУ функцию и аварии за её границей не видит.
#: Он не сломан — он отвечает о СВОЁМ ОХВАТЕ, и это предмет класса.
BLIND_TOOL = (
    "import json\n"
    "print(json.dumps({'bomb': 0}))\n"
)


#: Прибор, который ОТВЕЧАЕТ о чистом дереве и УМИРАЕТ об аварии. Три исхода
#: обязаны быть различимы на КАЖДОЙ из двух сторон замера, а не на одной.
DIES_ON_THE_ACCIDENT = (
    "import json,pathlib,sys\n"
    "root=pathlib.Path(sys.argv[1])\n"
    # Себя прибор не считает: сам его текст несёт буквы аварии, и без отсечки
    # он умирал бы и о ЧИСТОМ дереве — то есть мерил бы себя (замер этого цикла).
    "n=sum(p.read_text().count('BOOM') for p in root.rglob('*.py')\n"
    "      if 'scripts/' not in str(p.relative_to(root)))\n"
    "sys.exit(3) if n else print(json.dumps({'bomb': 0}))\n"
)

#: Прибор, который ПОДМЕНЯЕТ путь под собой — каталогом вместо файла. Это не
#: выдумка: замер ADR-886 нашёл тест, правивший исходники НА МЕСТЕ, и дерево
#: доставки сутки держало байты, которых никто не писал.
REPLACES_THE_PATH = (
    "import json,pathlib,shutil,sys\n"
    "root=pathlib.Path(sys.argv[1])\n"
    "p=root/'subject.py'\n"
    "p.unlink(); p.mkdir()\n"
    "print(json.dumps({'bomb': 1}))\n"
)


def _scene(name: str) -> C.Scene:
    return C.Scene(
        name=name,
        instrument="scripts/probe.py",
        accident="сцена приёмки: авария — буквы BOOM в subject.py",
        rod=C.CONSTRUCTED,
        edits=(C.Edit("subject.py", ("text", "VALUE = 'BOOM'\n")),),
        probe=(sys.executable, "{root}/scripts/probe.py", "{root}"),
        signal_key="bomb",
        marker_present="BOOM",
    )


class ThePositiveControlIsABlindInstrument(unittest.TestCase):
    """Перепись обязана УМЕТЬ сказать «слеп» — иначе она отвечает о себе."""

    def test_a_blind_instrument_is_named_the_subject_of_the_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, BLIND_TOOL)
            doc = C.measure(str(root), scenes=(_scene("blind_tool"),))
        row = doc["rows"][0]
        self.assertEqual(row["outcome"], C.BLIND, row.get("reason"))
        self.assertEqual(doc["counts"][C.BLIND], 1)
        self.assertEqual(doc["counts_sum"], doc["population"])

    def test_a_sighted_instrument_is_named_sighted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            doc = C.measure(str(root), scenes=(_scene("sighted_tool"),))
        row = doc["rows"][0]
        self.assertEqual(row["outcome"], C.SEES, row.get("reason"))
        self.assertEqual(row["delta"], 1)

    def test_the_two_verdicts_come_from_the_same_scene(self) -> None:
        """Та же сцена, другой прибор — вердикты ПРОТИВОПОЛОЖНЫ.

        Без этого «слеп» мог бы оказаться свойством сцены, а не прибора.
        """
        verdicts = []
        for body in (BLIND_TOOL, SIGHTED):
            with tempfile.TemporaryDirectory() as tmp:
                root = _scene_repo(tmp, body)
                doc = C.measure(str(root), scenes=(_scene("same_scene"),))
            verdicts.append(doc["rows"][0]["outcome"])
        self.assertEqual(verdicts, [C.BLIND, C.SEES])


class TheSceneMustProveItRestoredTheAccident(unittest.TestCase):
    """Каждый отказ здесь — НАСТОЯЩАЯ ошибка цикла #1049, а не выдуманная."""

    def test_a_marker_already_present_today_is_refused_as_vacuous(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            scene = C.dataclasses.replace(_scene("vacuous"), marker_present="VALUE")
            doc = C.measure(str(root), scenes=(scene,))
        row = doc["rows"][0]
        self.assertEqual(row["outcome"], C.UNMEASURED)
        self.assertIn("ВАКУУМНАЯ", row["reason"])

    def test_a_marker_absent_from_the_restored_bytes_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            scene = C.dataclasses.replace(_scene("no_marker"),
                                          marker_present="НЕТ-ТАКОГО")
            doc = C.measure(str(root), scenes=(scene,))
        self.assertEqual(doc["rows"][0]["outcome"], C.UNMEASURED)
        self.assertIn("НЕТ приметы аварии", doc["rows"][0]["reason"])

    def test_bytes_equal_to_todays_are_refused_not_counted_as_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            scene = C.dataclasses.replace(
                _scene("noop"),
                edits=(C.Edit("subject.py", ("text", "VALUE = 'fixed'\n")),),
                marker_present=None)
            doc = C.measure(str(root), scenes=(scene,))
        row = doc["rows"][0]
        self.assertEqual(row["outcome"], C.UNMEASURED)
        self.assertIn("РАВНЫ сегодняшним", row["reason"])

    def test_a_signal_moving_down_is_unmeasured_not_blind(self) -> None:
        """Число, ушедшее ВНИЗ, значит «сцена возмутила не то» (инв. #17)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            (root / "subject.py").write_text("VALUE = 'BOOM BOOM'\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "commit", "-am", "two"],
                           capture_output=True, check=True)
            # Примета здесь СНЯТА намеренно: в этой сцене авария есть и в
            # базовых байтах, поэтому примета была бы вакуумной и отказ по ней
            # случился бы РАНЬШЕ — а предмет этой проверки ветка «ушло вниз».
            scene = C.dataclasses.replace(
                _scene("down"),
                edits=(C.Edit("subject.py", ("text", "VALUE = 'BOOM'\n")),),
                marker_present=None)
            doc = C.measure(str(root), scenes=(scene,))
        row = doc["rows"][0]
        self.assertEqual(row["outcome"], C.UNMEASURED)
        self.assertIn("УПАЛО", row["reason"])

    def test_a_substitution_that_is_not_unique_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            (root / "subject.py").write_text("A = 1\nA = 1\n", encoding="utf-8")
            subprocess.run(["git", "-C", str(root), "commit", "-am", "twice"],
                           capture_output=True, check=True)
            scene = C.dataclasses.replace(
                _scene("ambiguous"),
                edits=(C.Edit("subject.py", ("sub", "A = 1", "A = 'BOOM'")),))
            doc = C.measure(str(root), scenes=(scene,))
        row = doc["rows"][0]
        self.assertEqual(row["outcome"], C.UNMEASURED)
        self.assertIn("раз(а), а не один", row["reason"])


class TheFixMarkerIsTheOtherDirectionOfTheSameProof(unittest.TestCase):
    """`marker_absent` — вторая половина доказательства, и у неё свои два отказа.

    Поднят ВЫЖИВШИМ мутантом: снятие отказа «приметы починки в сегодняшних
    байтах нет» не краснило НИ ОДНОЙ проверки, то есть половина доказательства
    была не измерена (урок «выживший мутант прячет ПОЛОВИНУ двери»).
    """

    def test_a_fix_marker_still_present_after_restore_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            scene = C.dataclasses.replace(
                _scene("fix_left"),
                edits=(C.Edit("subject.py", ("text", "VALUE = 'fixed BOOM'\n")),),
                marker_present=None, marker_absent="fixed")
            doc = C.measure(str(root), scenes=(scene,))
        row = doc["rows"][0]
        self.assertEqual(row["outcome"], C.UNMEASURED)
        self.assertIn("ОСТАЛАСЬ примета починки", row["reason"])

    def test_a_fix_marker_absent_today_is_refused_as_nothing_to_remove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            scene = C.dataclasses.replace(
                _scene("nothing_to_remove"),
                marker_present=None, marker_absent="НЕТ-ТАКОЙ-ПОЧИНКИ")
            doc = C.measure(str(root), scenes=(scene,))
        row = doc["rows"][0]
        self.assertEqual(row["outcome"], C.UNMEASURED)
        self.assertIn("ОТСУТСТВУЕТ", row["reason"])

    def test_a_removed_fix_marker_lets_the_verdict_through(self) -> None:
        """Обратная сторона: примета починки СНЯТА — вердикт выдаётся."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            scene = C.dataclasses.replace(
                _scene("fix_removed"), marker_present="BOOM", marker_absent="fixed")
            doc = C.measure(str(root), scenes=(scene,))
        self.assertEqual(doc["rows"][0]["outcome"], C.SEES)


class TheTreeIsReturnedByteForByte(unittest.TestCase):
    def test_the_tree_is_byte_identical_after_every_scene(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            before = (root / "subject.py").read_bytes()
            C.measure(str(root), scenes=(_scene("restore"),))
            self.assertEqual((root / "subject.py").read_bytes(), before)
            self.assertEqual(
                subprocess.run(["git", "-C", str(root), "status", "--porcelain"],
                               capture_output=True, text=True).stdout, "")

    def test_a_created_file_is_removed_again(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            scene = C.dataclasses.replace(
                _scene("created"),
                edits=(C.Edit("fresh.py", ("text", "X = 'BOOM'\n")),),
                creates=("fresh.py",))
            doc = C.measure(str(root), scenes=(scene,))
            self.assertEqual(doc["rows"][0]["outcome"], C.SEES)
            self.assertFalse((root / "fresh.py").exists())

    def test_a_restore_that_cannot_be_verified_fails_loudly(self) -> None:
        """Прогон подменил путь под прибором — отказ НАЗЫВАЕТ файл.

        Поднят ВЫЖИВШИМ мутантом: снятие побайтовой сверки возврата не краснило
        ничего. «Дерево осталось изменённым» обязано быть сказано вслух: именно
        таким молчанием ADR-886 увёз на `main` файл, сломанный синтаксически.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, REPLACES_THE_PATH)
            with self.assertRaises(C.Refused) as caught:
                C.measure(str(root), scenes=(_scene("path_replaced"),))
            msg = str(caught.exception)
            self.assertIn("НЕ ВЕРНУЛИСЬ побайтово", msg)
            self.assertIn("subject.py", msg)
            # Неудачная ЗАПИСЬ названа отдельно от разошедшегося sha: это две
            # разные двери к одному наблюдению, и диагноз у них разный. Без этой
            # строки мутант «неудачная запись проглатывается» ВЫЖИВАЛ.
            self.assertIn("запись не удалась", msg)
            # «НЕ ПРОЧИТАН» — ТРЕТИЙ исход, а не «файла нет» (инв. #17). Без этой
            # строки мутант «нечитаемый возврат подменяется пустотой» ВЫЖИВАЛ, а
            # у сцены, СОЗДАЮЩЕЙ файл, такая подмена сравнялась бы с `None` и
            # «дерево изменено» прошло бы молча.
            self.assertIn("НЕ ПРОЧИТАН", msg)
            # окно снято даже на этом пути: иначе следующий прогон отказал бы по
            # НАСЛЕДСТВУ, а не по настоящей причине
            self.assertFalse((root / C.WINDOW_REL).exists())

    def test_the_window_record_is_removed_after_a_verified_restore(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            C.measure(str(root), scenes=(_scene("window"),))
            self.assertFalse((root / C.WINDOW_REL).exists())


class TheRefusalsBeforeTheFirstEdit(unittest.TestCase):
    def test_the_prod_tree_is_refused_by_name(self) -> None:
        with self.assertRaises(C.Refused) as caught:
            C.guard_tree(pathlib.Path(C.PROD_ROOT))
        self.assertIn("ПРОД-дерево", str(caught.exception))

    def test_the_tools_own_tree_is_refused(self) -> None:
        with self.assertRaises(C.Refused) as caught:
            C.guard_tree(_ROOT)
        self.assertIn("дерево САМОГО прибора", str(caught.exception))

    def test_a_dirty_tree_is_refused_because_the_restore_is_unprovable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            (root / "subject.py").write_text("dirty\n", encoding="utf-8")
            with self.assertRaises(C.Refused) as caught:
                C.guard_tree(root)
        self.assertIn("незакоммиченных", str(caught.exception))

    def test_a_dirty_path_under_data_does_not_refuse(self) -> None:
        """`data/` грязно в КАЖДОМ дереве — там живёт состояние (п. 4 правила)."""
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            (root / "data").mkdir()
            (root / "data" / "live.json").write_text("{}", encoding="utf-8")
            C.guard_tree(root)  # отказа быть НЕ должно

    def test_an_open_window_from_a_dead_run_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            C._open_window(root, "наследство мёртвого прогона")
            with self.assertRaises(C.Refused) as caught:
                C.guard_tree(root)
        self.assertIn("ОТКРЫТО окно", str(caught.exception))

    def test_a_tree_without_git_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain = pathlib.Path(tmp) / "plain"
            plain.mkdir()
            with self.assertRaises(C.Refused) as caught:
                C.guard_tree(plain)
        self.assertIn("рабочим деревом git", str(caught.exception))


class TheRosterAndTheOutcomes(unittest.TestCase):
    def test_the_outcome_set_is_closed_and_the_sum_equals_the_population(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            doc = C.measure(str(root),
                            scenes=(_scene("a"), C.dataclasses.replace(
                                _scene("b"), marker_present="VALUE")))
        self.assertEqual(sorted(doc["counts"]), sorted(C.OUTCOMES))
        self.assertEqual(doc["counts_sum"], doc["population"])
        self.assertEqual(doc["population"], 2)

    def test_every_declared_scene_names_its_instrument_its_accident_and_its_rod(self) -> None:
        for s in C._scenes():
            with self.subTest(scene=s.name):
                self.assertTrue((_ROOT / s.instrument).exists(),
                                f"{s.name}: прибора {s.instrument} в дереве нет")
                self.assertIn(s.rod, C.RODS)
                self.assertGreater(len(s.accident), 80,
                                   "авария обязана быть НАЗВАНА, а не помянута")
                self.assertTrue(s.marker_present or s.marker_absent,
                                f"{s.name}: у сцены нет ни одной приметы аварии — "
                                "доказать, что возмущено объявленное, будет нечем")

    def test_an_unknown_scene_name_is_refused_not_silently_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            with self.assertRaises(C.Refused):
                C.measure(str(root), only=["нет-такой-сцены"],
                          scenes=(_scene("a"),))

    def test_the_report_says_aloud_what_sees_does_not_prove(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, SIGHTED)
            doc = C.measure(str(root), scenes=(_scene("a"),))
        text = "\n".join(C.report(doc))
        self.assertIn("ВОССТАНОВЛЕННУЮ форму", text)
        self.assertIn("НЕПОЛН", doc["roster_is_not_complete"])


class TheInstrumentDoesNotAnswer(unittest.TestCase):
    def test_an_instrument_that_crashes_is_unmeasured_not_clean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, "import sys\nsys.exit(3)\n")
            doc = C.measure(str(root), scenes=(_scene("crash"),))
        row = doc["rows"][0]
        self.assertEqual(row["outcome"], C.UNMEASURED)
        self.assertIn("о ЧИСТОМ дереве прибор не ответил", row["reason"])

    def test_an_instrument_that_dies_only_on_the_accident_is_unmeasured(self) -> None:
        """Третий исход обязан быть различим на ОБЕИХ сторонах замера.

        Поднят ВЫЖИВШИМ мутантом: снятие ветки «о дереве с аварией прибор не
        ответил» не краснило ничего — сторона «после» была не измерена, и
        молчание прибора прочиталось бы как «число не изменилось», то есть как
        СЛЕПОТА. Ошибка шла в сторону находки.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, DIES_ON_THE_ACCIDENT)
            doc = C.measure(str(root), scenes=(_scene("dies_after"),))
        row = doc["rows"][0]
        self.assertEqual(row["outcome"], C.UNMEASURED)
        self.assertIn("о дереве с аварией прибор не ответил", row["reason"])
        self.assertTrue(row["base"]["answered"])

    def test_an_instrument_without_the_declared_number_is_unmeasured(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = _scene_repo(tmp, "import json\nprint(json.dumps({'other': 1}))\n")
            doc = C.measure(str(root), scenes=(_scene("nokey"),))
        self.assertEqual(doc["rows"][0]["outcome"], C.UNMEASURED)
        self.assertIn("объявленного числа", doc["rows"][0]["reason"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
