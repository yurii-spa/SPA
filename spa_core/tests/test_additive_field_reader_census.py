"""Контроль переписи читателей аддитивного поля (ADR-856, класс ADR-851).

Каждый тест — контроль В ОБЕ СТОРОНЫ: проверка, никогда не видевшая настоящей
поломки, есть украшение (`.claude/rules/deployment.md`). Настоящая поломка
здесь одна и она НАБЛЮДАЛАСЬ: 28.10 на проде читатель живого урезания
ветвился по населению ЗАПИСЕЙ (`records`), а не по населению записей, НЕСУЩИХ
поле, и на 163 записях без поля сказал «это ЗАМЕР» вместо «шага не звали».

Время и личность процесса здесь не участвуют: прибор читает ДЕРЕВО, часов и
pid не спрашивает ни одной дверью.
"""

from __future__ import annotations

import ast
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import additive_field_reader_census as afc


def _scene(root: Path, rel: str, body: str) -> None:
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# --------------------------------------------------------------------------
# Поведенческая проба эталона: обе стороны на НАСТОЯЩЕЙ двери
# --------------------------------------------------------------------------
class ExemplarDriveTests(unittest.TestCase):

    def test_the_live_door_distinguishes_the_two_scenes(self):
        """Положительная сторона: сегодняшняя дверь (после ADR-851) различает."""
        got = afc.drive_exemplar()
        self.assertEqual(got["kind"], afc.DRIVE_DISTINGUISHES, got)
        self.assertNotEqual(got["scene_nobody_carries"]["outcome"],
                            got["scene_measured_zero"]["outcome"])
        # и различает ИМЕННО в ту сторону, которую требует инв. #17
        self.assertEqual(got["scene_nobody_carries"]["outcome"], "unmeasured")
        self.assertEqual(got["scene_measured_zero"]["outcome"], "measured_zero")

    def test_the_pre_adr851_reader_is_caught_as_conflating(self):
        """Отрицательная сторона — ДОСЛОВНАЯ авария 28.10.

        Дверь ветвится по ``records``, как это было до ADR-851. На сцене «поля
        не несёт ни одна запись» она обязана быть поймана: иначе проба не
        умеет видеть ту поломку, ради которой написана.
        """
        def pre_adr851(census):
            if census.get("records"):
                return "measured_zero", "урезаний не было ни на одной записи"
            return "unmeasured", "истории нет"

        got = afc.drive_exemplar(pre_adr851, door_name="pre-ADR-851")
        self.assertEqual(got["kind"], afc.DRIVE_CONFLATES, got)
        self.assertEqual(got["scene_nobody_carries"]["outcome"],
                         got["scene_measured_zero"]["outcome"])

    def test_a_door_that_raises_is_unmeasured_not_distinguishing(self):
        """Третий исход — ЗНАЧЕНИЕ: сломанная дверь не есть «различение живо»."""
        def broken(census):
            raise RuntimeError("дверь не отвечает")

        got = afc.drive_exemplar(broken, door_name="broken")
        self.assertEqual(got["kind"], afc.DRIVE_UNMEASURED, got)
        self.assertIn("RuntimeError", got["reason"])

    def test_the_two_scenes_differ_by_exactly_one_number(self):
        """Сцены обязаны отличаться РОВНО тем, у скольких записей есть поле."""
        nobody = afc._blank_census(163, 163)
        zero = afc._blank_census(163, 0)
        self.assertEqual(nobody["records"], zero["records"])
        differ = {k for k in set(nobody) | set(zero)
                  if nobody.get(k) != zero.get(k)}
        # `counts` производен от того же числа — он и ЕСТЬ носитель различия
        self.assertEqual(differ, {"records_without_field", "counts"})


# --------------------------------------------------------------------------
# Ось БЛОКОВ: найден тот, кто публикует ДВА населения, и только он
# --------------------------------------------------------------------------
class BlockDiscoveryTests(unittest.TestCase):

    def test_a_block_publishing_both_populations_is_found(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scene(root, "spa_core/x.py",
                   "def measure():\n"
                   "    return {'records': 3, 'records_without_field': 3}\n")
            blocks, unparsed = afc.find_blocks(root)
            self.assertEqual(unparsed, [])
            self.assertEqual(len(blocks), 1, blocks)
            self.assertEqual(blocks[0]["producer"], "measure")
            self.assertEqual(blocks[0]["all_keys"], ["records"])
            self.assertEqual(blocks[0]["without_keys"], ["records_without_field"])

    def test_a_block_publishing_only_one_population_is_not_in_the_class(self):
        """Обратная сторона: без развилки у читателя предмета нет вовсе."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scene(root, "spa_core/only_all.py",
                   "def measure():\n    return {'records': 3, 'counts': {}}\n")
            _scene(root, "spa_core/only_without.py",
                   "def measure():\n    return {'records_without_field': 3}\n")
            blocks, _ = afc.find_blocks(root)
            self.assertEqual(blocks, [])

    def test_tests_and_the_instrument_itself_are_outside_the_population(self):
        """Прибор, меряющий свою фикстуру, прибавил бы к классу себя."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            body = ("def measure():\n"
                    "    return {'records': 1, 'records_without_field': 1}\n")
            _scene(root, "spa_core/tests/test_x.py", body)
            _scene(root, afc.SELF_PATH, body)
            _scene(root, "docs/not_python.py", body)       # не в ROOTS
            blocks, _ = afc.find_blocks(root)
            self.assertEqual(blocks, [])

    def test_an_unparsable_file_is_unmeasured_not_silently_dropped(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scene(root, "spa_core/broken.py", "def measure(:\n")
            blocks, unparsed = afc.find_blocks(root)
            self.assertEqual(blocks, [])
            self.assertEqual(len(unparsed), 1, unparsed)
            self.assertEqual(unparsed[0]["file"], "spa_core/broken.py")
            self.assertIn("SyntaxError", unparsed[0]["reason"])


# --------------------------------------------------------------------------
# Ось ЧИТАТЕЛЕЙ: на каком населении стои́т вердикт
# --------------------------------------------------------------------------
class ReaderDiscoveryTests(unittest.TestCase):

    PRODUCER = ("def measure():\n"
                "    return {'records': 3, 'records_without_field': 3}\n")

    def test_a_reader_of_both_populations_is_named_reads_both(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scene(root, "spa_core/p.py", self.PRODUCER)
            _scene(root, "spa_core/r.py",
                   "def report(c):\n"
                   "    return c.get('records'), c.get('records_without_field')\n")
            blocks, _ = afc.find_blocks(root)
            pairs, _ = afc.find_readers(root, blocks)
            self.assertEqual(len(pairs), 1, pairs)
            self.assertEqual(pairs[0]["outcome"], afc.READS_BOTH)
            self.assertEqual(pairs[0]["reads_all"], ["records"])

    def test_a_reader_of_the_absence_number_only_passes_no_verdict_on_all(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scene(root, "spa_core/p.py", self.PRODUCER)
            _scene(root, "spa_core/r.py",
                   "def report(c):\n    return c.get('records_without_field')\n")
            blocks, _ = afc.find_blocks(root)
            pairs, _ = afc.find_readers(root, blocks)
            self.assertEqual(len(pairs), 1, pairs)
            self.assertEqual(pairs[0]["outcome"], afc.READS_WITHOUT_ONLY)
            self.assertEqual(pairs[0]["reads_all"], [])

    def test_the_producer_is_not_counted_as_its_own_reader(self):
        """Производитель это число ПИШЕТ — зачесть его в читатели значило бы
        объявить третий исход доехавшим до вердикта там, где читателя нет."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scene(root, "spa_core/p.py",
                   "def measure():\n"
                   "    out = {'records': 3, 'records_without_field': 3}\n"
                   "    return out.get('records_without_field') and out\n")
            blocks, _ = afc.find_blocks(root)
            pairs, _ = afc.find_readers(root, blocks)
            self.assertEqual(pairs, [])

    def test_the_observed_form_of_reading_is_seen_too(self):
        """`observed(doc, key)` — честная форма чтения (инв. #17); читатель,
        собранный на ней, по `.get` найден НЕ был бы."""
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scene(root, "spa_core/p.py", self.PRODUCER)
            _scene(root, "spa_core/r.py",
                   "from spa_core.utils.observation import observed\n"
                   "def report(c):\n"
                   "    return (observed(c, 'records'),\n"
                   "            observed(c, 'records_without_field'))\n")
            blocks, _ = afc.find_blocks(root)
            pairs, _ = afc.find_readers(root, blocks)
            self.assertEqual(len(pairs), 1, pairs)
            self.assertEqual(pairs[0]["outcome"], afc.READS_BOTH)

    def test_a_block_whose_absence_number_nobody_reads_is_reported(self):
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            _scene(root, "spa_core/p.py", self.PRODUCER)
            report = afc.run_census(root)
            self.assertEqual(report["pair_count"], 0)
            self.assertEqual(len(report["blocks_with_no_reader"]), 1)
            self.assertEqual(report["blocks_with_no_reader"][0]["producer"],
                             "measure")
            # и ОБРАТНАЯ сторона: появился читатель ⇒ блок уходит из находки
            _scene(root, "spa_core/r.py",
                   "def report(c):\n    return c.get('records_without_field')\n")
            again = afc.run_census(root)
            self.assertEqual(again["blocks_with_no_reader"], [])


# --------------------------------------------------------------------------
# Честность самого отчёта
# --------------------------------------------------------------------------
class ReportHonestyTests(unittest.TestCase):

    def test_the_unattributable_axis_is_a_named_third_outcome_not_a_zero(self):
        """Главное свойство прибора: он НЕ печатает нуля там, где не мерил.

        Первая редакция строила пару от ключа отсутствия, и исход «читает
        только население „все“» был НЕДОСТИЖИМ по построению — прибор сказал бы
        «не может — 0». Это ровно тот false-zero, против которого прибор и
        написан, поэтому ось объявлена НЕ ИЗМЕРЕННОЙ явно.
        """
        report = afc.run_census(Path(__file__).resolve().parents[2])
        axis = report["reader_axis_not_measured"]
        self.assertIn("question", axis)
        self.assertIn("what_would_close_it", axis)
        self.assertNotIn("cannot_distinguish", report["counts"])
        text = "\n".join(afc.format_report(report))
        self.assertIn("НЕ ИЗМЕРЕНО (ось, не строка)", text)

    def test_the_live_tree_reproduces_the_exemplar_block(self):
        """Положительный контроль на ЖИВОМ дереве: эталон класса — в населении.

        Замер, не находящий собственного эталона, отвечает не на тот вопрос
        (урок #563, `bounded_window_census`).
        """
        report = afc.run_census(Path(__file__).resolve().parents[2])
        exemplars = [b for b in report["blocks"]
                     if b["file"] == "spa_core/paper_trading/shadow_trigger_eval.py"
                     and "records_without_field" in b["without_keys"]]
        self.assertEqual(len(exemplars), 1, report["blocks"])
        self.assertEqual(exemplars[0]["producer"], "live_trim_census")
        readers = [p for p in report["pairs"]
                   if p["without_key"] == "records_without_field"]
        self.assertTrue(readers, "у эталона обязан быть найден читатель")
        self.assertTrue(any(p["reader"] == "format_live_trim" for p in readers),
                        readers)

    def test_the_summary_never_claims_clean_when_the_exemplar_is_unmeasured(self):
        report = {"measured": True, "block_count": 1, "pair_count": 0,
                  "counts": {afc.READS_BOTH: 0, afc.READS_WITHOUT_ONLY: 0,
                             afc.PAIR_UNMEASURED: 0},
                  "blocks": [], "pairs": [], "blocks_with_no_reader": [],
                  "unparsed": [],
                  "exemplar": {"kind": afc.DRIVE_UNMEASURED, "reason": "дверь молчит"},
                  "reader_axis_not_measured": {"question": "q", "why": "w",
                                               "what_would_close_it": "c"}}
        text = "\n".join(afc.format_report(report))
        self.assertIn("эталон класса НЕ ИЗМЕРЕН", text)
        self.assertIn("это НЕ «различение живо»", text)

    def test_the_cli_separates_measured_from_broken_from_unmeasured(self):
        """Три кода возврата различимы — иначе «не измерено» сольётся с «чисто»."""
        src = Path(afc.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        main = next(n for n in ast.walk(tree)
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        codes = {n.value.value for n in ast.walk(main)
                 if isinstance(n, ast.Return) and isinstance(n.value, ast.Constant)}
        self.assertEqual(codes, {0, 1, 2}, codes)


# --------------------------------------------------------------------------
# Проба приёмки: ТРИ вердикта различимы, и каждый проверен
# --------------------------------------------------------------------------
class AcceptanceProbeTests(unittest.TestCase):
    """Мутации 12–14 замера #974 выжили ровно потому, что этого класса не было:
    батарея гоняла прибор и ни разу не спрашивала ПРОБУ. Проба — единственная
    поверхность, по которой очередь судит, сделана ли работа, поэтому её
    вердикты обязаны быть проверены все три, а не выведены из прибора.
    """

    def setUp(self):
        from spa_core.monitoring import card_acceptance as ca
        self.ca = ca
        self.probe = ca.PROBES["additive_field_reader_distinguishes"]
        self._saved = afc.drive_exemplar

    def tearDown(self):
        afc.drive_exemplar = self._saved

    def test_the_probe_is_registered_under_its_declared_name(self):
        self.assertIn("additive_field_reader_distinguishes", self.ca.PROBES)

    def test_the_live_tree_satisfies_the_probe(self):
        verdict, detail = self.probe(None)
        self.assertEqual(verdict, self.ca.SATISFIED, detail)
        self.assertIn("НЕ ИЗМЕРЕННОЙ", detail)

    def test_a_conflating_exemplar_is_not_satisfied(self):
        """Дословная авария 28.10: дверь отвечает одно и то же на обе сцены."""
        afc.drive_exemplar = lambda *a, **k: {
            "kind": afc.DRIVE_CONFLATES, "door": "fake",
            "scene_nobody_carries": {"outcome": "measured_zero", "reason": "r"},
            "scene_measured_zero": {"outcome": "measured_zero", "reason": "r"},
        }
        verdict, detail = self.probe(None)
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, detail)
        self.assertIn("одно и то же", detail)

    def test_an_unmeasured_exemplar_is_unmeasured_not_satisfied(self):
        """Третий вердикт — СВОЙ: про предмет не измерено ничего."""
        afc.drive_exemplar = lambda *a, **k: {
            "kind": afc.DRIVE_UNMEASURED, "reason": "дверь не ввозится"}
        verdict, detail = self.probe(None)
        self.assertEqual(verdict, self.ca.UNMEASURED, detail)
        self.assertIn("дверь не ввозится", detail)

    def test_a_difference_in_the_wrong_direction_is_not_satisfied(self):
        """Различие есть, но перевёрнутое: сцена БЕЗ поля объявлена замером нуля.

        Без этой проверки проба зеленела бы на двери, которая различает исходы
        и путает их МЕСТАМИ, — то есть на ровно той неправде, что была в проде.
        """
        afc.drive_exemplar = lambda *a, **k: {
            "kind": afc.DRIVE_DISTINGUISHES, "door": "flipped",
            "scene_nobody_carries": {"outcome": "measured_zero", "reason": "r"},
            "scene_measured_zero": {"outcome": "unmeasured", "reason": "r"},
        }
        verdict, detail = self.probe(None)
        self.assertEqual(verdict, self.ca.NOT_SATISFIED, detail)
        self.assertIn("НЕ в ту сторону", detail)

    def test_three_verdicts_of_the_probe_are_distinguishable(self):
        """Контроль над контролем: три исхода пробы — три РАЗНЫХ значения."""
        self.assertEqual(
            len({self.ca.SATISFIED, self.ca.NOT_SATISFIED, self.ca.UNMEASURED}), 3)


if __name__ == "__main__":
    unittest.main()
