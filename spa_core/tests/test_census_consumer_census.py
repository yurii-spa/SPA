"""Прибор «сколько потребителей у переписей и согласны ли они о `root`» (заказ #564).

Проверки устроены так, чтобы КАЖДАЯ могла покраснеть на настоящей поломке:

* положительный контроль воспроизводит дефект цикла #565 ДОСЛОВНО — форму зова
  храповика с обязательным ведущим подчёркиванием в имени приёмника;
* обратный контроль требует, чтобы на ПОЧИНЕННОЙ форме находки НЕ было: иначе
  находка висела бы над любым деревом и перестала бы что-либо означать;
* третий исход («не измерено») проверяется отдельно от нуля в обе стороны.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import json
import shutil
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import census_consumer_census as ccc

_TREE = Path(__file__).resolve().parents[2]

#: Форма зова храповика ДО поправки #565 — с обязательным `_` у приёмника.
_PRE_FIX_FORM = (
    r"from spa_core\.monitoring import (\w+)\n\s+_\w+ = \1\.run\(root=args\.root\)")

#: Форма после поправки.
_POST_FIX_FORM = r"\b(\w+)\.run\(root=args\.root\)"

_RATCHET_REL = Path("spa_core/tests/test_census_stage_root_contract.py")
_BRIDGE_REL = Path("spa_core/monitoring/findings_bridge.py")


def _skeleton(tree: Path, *, population_form: str) -> None:
    """Дерево-образец: НАСТОЯЩИЕ переписи и мост + храповик с заданной формой.

    Копируется весь `spa_core/monitoring` (замер читает только исходники и
    ничего не импортирует), иначе население переписей оказалось бы пустым и
    прибор честно ответил бы «не измерено» — верным ответом не на тот вопрос.
    """
    (tree / "spa_core").mkdir(parents=True, exist_ok=True)
    shutil.copytree(_TREE / "spa_core" / "monitoring",
                    tree / "spa_core" / "monitoring",
                    ignore=shutil.ignore_patterns("__pycache__"))
    (tree / "spa_core" / "tests").mkdir(parents=True, exist_ok=True)
    (tree / _RATCHET_REL).write_text(
        "import re\n"
        f'_CALL = re.compile(r"""{population_form}""")\n'
        "def stage_censuses():\n"
        "    return sorted(set(_CALL.findall(TEXT)))\n",
        encoding="utf-8")


_LIVE: dict = {}


def live_measure() -> dict:
    """Замер живого дерева — ОДИН раз на модуль.

    Скан дерева не зависит от вызывающего теста, а повторение его четырежды
    стоило набору 80 секунд. Кэш здесь не прячет состояние: входом замера
    является дерево, а оно в пределах прогона не меняется.
    """
    if "doc" not in _LIVE:
        _LIVE["doc"] = ccc.measure(_TREE)
    return _LIVE["doc"]


class PopulationIsRealAndNotEmpty(unittest.TestCase):

    def test_the_callee_population_of_the_live_tree_is_not_empty(self) -> None:
        """Ноль переписей = прибор отвечает не на тот вопрос, а не «чисто»."""
        doc = live_measure()
        self.assertGreaterEqual(doc["counts"]["callees"], 40, (
            f"переписей найдено {doc['counts']['callees']} — форма поиска "
            "(верхнеуровневый `run()` с параметром `root`) перестала работать"))

    def test_the_bridge_is_among_the_by_name_consumers(self) -> None:
        """Известный потребитель обязан находиться — иначе искатель слеп."""
        doc = live_measure()
        files = {s["file"] for s in doc["consumers"]["by_name"]}
        self.assertIn("spa_core/monitoring/findings_bridge.py", files,
                      "мост не найден среди зовущих — искатель по имени слеп")

    def test_every_consumer_class_is_reported_separately(self) -> None:
        """Классы разнородны; сведение их в одно число отвечало бы не на тот вопрос."""
        doc = live_measure()
        for key in ("by_name", "cli", "dynamic", "fleet"):
            self.assertIn(key, doc["consumers"], f"класс потребителя `{key}` пропал")


class TheMeasurementDoesNotReadTheDataDir(unittest.TestCase):
    """Ловушка заказа: вопрос о КОДЕ, ответ не смеет зависеть от диска."""

    def test_a_poisoned_data_dir_does_not_move_a_single_number(self) -> None:
        with TemporaryDirectory() as tmp:
            tree = Path(tmp)
            _skeleton(tree, population_form=_POST_FIX_FORM)
            clean = ccc.measure(tree)["counts"]
            (tree / "data").mkdir()
            for name in ("census_consumer_census.json", "house_view_gap.json"):
                (tree / "data" / name).write_text(
                    json.dumps({"counts": {"callees": 9999}}), encoding="utf-8")
            poisoned = ccc.measure(tree)["counts"]
            self.assertEqual(clean, poisoned, (
                "содержимое `data/` сдвинуло замер о КОДЕ — ответ зависит от "
                "того, что сегодня лежит на диске"))


class TheRatchetCoverageFinding(unittest.TestCase):

    def test_the_pre_fix_call_form_is_named_CRITICAL(self) -> None:
        """Положительный контроль: дефект #565 дословно.

        Храповик с обязательным ведущим подчёркиванием у приёмника охраняет
        подмножество, а выглядит полным. Проверка, никогда не видевшая этой
        поломки, была бы украшением.
        """
        with TemporaryDirectory() as tmp:
            tree = Path(tmp)
            _skeleton(tree, population_form=_PRE_FIX_FORM)
            doc = ccc.measure(tree)
            self.assertEqual(doc["status"], ccc.STATUS_CRITICAL,
                             "суженная форма зова объявлена здоровой")
            self.assertGreater(doc["counts"]["stage_unguarded"], 20, (
                "вне храповика названо подозрительно мало переписей — мера "
                f"считает не то: {doc['counts']}"))
            self.assertTrue(
                any("ВЕДУЩЕГО ПОДЧЁРКИВАНИЯ" in f for f in doc["findings"]),
                "находка не называет ПРИЧИНУ сужения — по такой не починишь")

    def test_the_post_fix_call_form_raises_no_finding(self) -> None:
        """Обратный контроль: на починенной форме находки НЕТ.

        Без него находка висела бы над любым деревом, и её появление
        перестало бы что-либо означать.
        """
        with TemporaryDirectory() as tmp:
            tree = Path(tmp)
            _skeleton(tree, population_form=_POST_FIX_FORM)
            doc = ccc.measure(tree)
            self.assertEqual(doc["counts"]["stage_unguarded"], 0, (
                "на полной форме зова прибор всё равно объявил дыру: "
                f"{doc['stage_ratchet']['unguarded']}"))
            self.assertNotEqual(doc["status"], ccc.STATUS_CRITICAL)

    def test_the_instruments_own_population_is_complete(self) -> None:
        """Сузь форму зова у ПРИБОРА — и «дыр нет» станет истинным по построению.

        `unguarded = by_call_form - under_ratchet`: если `by_call_form` усохнет,
        разность опустеет, и прибор объявит покрытие полным, ничего не измерив.
        Поэтому полнота его собственного населения — отдельное утверждение,
        а не следствие зелёного вердикта.
        """
        doc = live_measure()
        self.assertGreaterEqual(doc["counts"]["stage_by_call_form"], 45, (
            "прибор видит у ступени "
            f"{doc['counts']['stage_by_call_form']} переписи(ей) — его "
            "собственная форма зова сузилась, и вердикт «дыр нет» ничего "
            "не значит. Замер #565: 45"))

    def test_the_live_tree_is_covered_after_the_fix(self) -> None:
        """Живое дерево: класс закрыт, и это утверждение проверяемо здесь."""
        doc = live_measure()
        self.assertFalse(doc["stage_ratchet"]["under_ratchet_unmeasured"],
                         "население храповика не выведено — покрытие НЕ измерено")
        self.assertEqual(doc["stage_ratchet"]["unguarded"], [], (
            "перепись ступени осталась вне храповика контракта: "
            f"{doc['stage_ratchet']['unguarded']}"))


class TheThirdOutcomeIsNotZero(unittest.TestCase):

    def test_a_tree_without_monitoring_is_UNMEASURED_not_empty(self) -> None:
        with TemporaryDirectory() as tmp:
            doc = ccc.measure(Path(tmp))
            self.assertEqual(doc["status"], ccc.STATUS_UNMEASURED)
            self.assertEqual(doc["counts"]["unchecked"], 1)
            self.assertTrue(any("НЕ ИЗМЕРЕНО" in f for f in doc["findings"]))

    def test_a_missing_ratchet_file_is_None_not_an_empty_population(self) -> None:
        """`None` и `[]` — разные утверждения; второе значило бы «видит ноль»."""
        with TemporaryDirectory() as tmp:
            tree = Path(tmp)
            _skeleton(tree, population_form=_POST_FIX_FORM)
            (tree / _RATCHET_REL).unlink()
            self.assertIsNone(ccc.stage_population_under_ratchet(tree))
            doc = ccc.measure(tree)
            self.assertEqual(doc["status"], ccc.STATUS_UNMEASURED, (
                "исчезнувший храповик прочитан как «дыр нет» — fail-OPEN тише "
                "красного, и это ровно тот класс, ради которого прибор написан"))
            self.assertIsNone(doc["counts"]["stage_under_ratchet"])

    def test_a_form_that_is_not_a_literal_is_UNMEASURED(self) -> None:
        """Форма, собранная из переменных, статике не даётся — и это третий исход."""
        with TemporaryDirectory() as tmp:
            tree = Path(tmp)
            _skeleton(tree, population_form=_POST_FIX_FORM)
            (tree / _RATCHET_REL).write_text(
                "import re\n"
                "_PART = r'\\\\b(\\\\w+)'\n"
                "_CALL = re.compile(_PART + r'\\\\.run')\n"
                "def stage_censuses():\n"
                "    return sorted(set(_CALL.findall(TEXT)))\n",
                encoding="utf-8")
            self.assertIsNone(ccc.stage_population_under_ratchet(tree))

    def test_a_declared_but_unused_form_does_not_count_as_coverage(self) -> None:
        """Регулярка, объявленная и не питающая население, охраняет НОЛЬ.

        Сложить её с работающей значило бы изготовить покрытие из текста.
        """
        with TemporaryDirectory() as tmp:
            tree = Path(tmp)
            _skeleton(tree, population_form=_PRE_FIX_FORM)
            path = tree / _RATCHET_REL
            source = path.read_text(encoding="utf-8")
            # рядом кладём ПОЛНУЮ форму, но население по-прежнему питает суженная
            path.write_text(
                source.replace(
                    "def stage_censuses():",
                    f'_UNUSED = re.compile(r"""{_POST_FIX_FORM}""")\n'
                    "def stage_censuses():"),
                encoding="utf-8")
            doc = ccc.measure(tree)
            self.assertEqual(doc["status"], ccc.STATUS_CRITICAL, (
                "неиспользуемая полная форма зачтена как покрытие — прибор "
                "считает текст, а не то, что охраняется"))

    def test_unresolved_dynamic_sites_are_counted_apart_from_zero(self) -> None:
        doc = live_measure()
        self.assertGreater(doc["counts"]["dynamic_unresolved"], 0, (
            "`import_module(<переменная>)` в дереве есть, а прибор насчитал "
            "ноль — он растворил третий исход в отсутствии"))
        self.assertTrue(
            any(f.startswith("[НЕ ИЗМЕРЕНО]") and "import_module" in f
                for f in doc["findings"]),
            "нераспознанный динамический зов не назван вслух")


class TheUnprobeableClass(unittest.TestCase):
    """Перепись без параметра ``write`` платит за каждый замер настоящим файлом."""

    def test_the_class_is_named_and_not_silently_empty(self) -> None:
        doc = live_measure()
        self.assertIn("unprobeable_without_writing", doc)
        self.assertGreater(doc["counts"]["unprobeable_without_writing"], 0, (
            "класс объявлен пустым — либо все переписи получили `write`, и "
            "тогда это надо записать решением, либо разбор перестал работать"))

    def test_a_census_with_write_is_not_in_the_class(self) -> None:
        """Обратный контроль: иначе метка висела бы над каждой переписью."""
        doc = live_measure()
        self.assertNotIn("target_stability", doc["unprobeable_without_writing"],
                         "перепись С параметром `write` попала в класс")


class TheOrderOfTheReportIsTheOrderOfTheQuestion(unittest.TestCase):
    """Порядок строк отчёта — утверждение, а не оформление.

    Заказ #564 прямо потребовал НАСЕЛЕНИЕ первым результатом. А «72 места не
    измерены», встань оно первой строкой, прочлось бы как замер потребителей —
    тогда как означает прямо противоположное: часть населения посмотреть не
    удалось. Комментарий у ветки печати шага 0-офис ссылается на эту проверку.
    """

    def test_population_comes_before_the_third_outcome(self) -> None:
        doc = live_measure()
        findings = doc["findings"]
        first = findings[0]
        self.assertTrue(first.startswith("[ОТВЕТ]") and "переписей" in first,
                        f"первой строкой идёт не население, а: {first}")
        unmeasured = [i for i, f in enumerate(findings)
                      if f.startswith("[НЕ ИЗМЕРЕНО]")]
        answers = [i for i, f in enumerate(findings) if f.startswith("[ОТВЕТ]")]
        self.assertTrue(answers, "в отчёте нет ни одного [ОТВЕТ] — отвечать нечем")
        if unmeasured:
            self.assertGreater(min(unmeasured), max(answers), (
                "третий исход встал раньше ответов и прочтётся как замер "
                f"потребителей: {findings[min(unmeasured)]}"))

    def test_the_root_agreement_answer_is_present(self) -> None:
        doc = live_measure()
        self.assertTrue(
            any("под именем `root`" in f for f in doc["findings"]),
            "согласие о значении `root` — половина заказа — в отчёт не попало")


class TheAdvisoryContract(unittest.TestCase):

    def test_run_puts_its_artifact_under_root_data(self) -> None:
        """Контракт ADR-326 у самого прибора: `root` — КОРЕНЬ ДЕРЕВА."""
        with TemporaryDirectory() as tmp:
            tree = Path(tmp)
            _skeleton(tree, population_form=_POST_FIX_FORM)
            (tree / "data").mkdir()
            before = {p.name for p in tree.iterdir()}
            ccc.run(root=str(tree))
            strays = sorted(p.name for p in tree.iterdir()
                            if p.name not in before)
            self.assertEqual(strays, [], f"артефакт лёг в корень дерева: {strays}")
            self.assertTrue((tree / "data" / ccc.OUTPUT_FILENAME).exists())

    def test_an_explicit_data_dir_goes_by_its_own_name(self) -> None:
        """Одно имя на два смысла и было дефектом ADR-326."""
        with TemporaryDirectory() as tmp:
            tree = Path(tmp)
            _skeleton(tree, population_form=_POST_FIX_FORM)
            elsewhere = tree / "elsewhere"
            ccc.run(root=str(tree), data_dir=str(elsewhere))
            self.assertTrue((elsewhere / ccc.OUTPUT_FILENAME).exists())

    def test_write_false_touches_nothing(self) -> None:
        with TemporaryDirectory() as tmp:
            tree = Path(tmp)
            _skeleton(tree, population_form=_POST_FIX_FORM)
            before = {p.name for p in tree.iterdir()}
            ccc.run(root=str(tree), write=False)
            self.assertEqual({p.name for p in tree.iterdir()}, before)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
