"""Батарея пробы приёмки `rnd_carve_out_narrows_the_class` (ADR-792).

Карточка `inbox-storozh-r-d-isklyucheniya-upersya-v-poro` требует различать два
исхода, которые сторож вычета до 23.10 путал: «правило расширили до любого
упоминания в `docs/`» и «R&D-класс вырос». Проба обязана отвечать на ПЕРВЫЙ
вопрос и быть безразличной ко второму.

**Почему батарея гоняет настоящую пробу, а не повторяет её логику.** Повтор
проверял бы собственную копию правила; здесь каждый случай зовёт
`card_acceptance.run_probe` — ровно ту дверь, которой пользуется шаг 0-офис, —
и судит по ВЕРДИКТУ.

**Почему каждая мутация меняет ПРАВИЛО, а не текст дерева.** Во всех случаях
ниже тексты `docs/` и состав `scripts/` остаются БАЙТОВО теми же, а меняется
только состав реестров-продуктов. Поэтому смена вердикта доказывает, что проба
судит по правилу, а не по тому, что где-то написано нужное слово (ADR-333:
проба не имеет права проходить подстрокой).
"""
from __future__ import annotations

import ast
import inspect
import pathlib
import shutil
import tempfile
import unittest
from unittest import mock

from spa_core.monitoring import card_acceptance as ca
from spa_core.tests import _unwired
from spa_core.tests.test_unwired_registry_evidence import _fake_repo

PROBE = "rnd_carve_out_narrows_the_class"


class TestTheProbeOnASyntheticTree(unittest.TestCase):
    """Целый контур и каждое порванное звено — поимённо."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        _fake_repo(self.root)
        self.addCleanup(self._tmp.cleanup)

    def _probe(self):
        return ca.run_probe(PROBE, repo_root=str(self.root))

    #: Фраза ВТОРОЙ ноги (контрфакта). Живая поломка обязана доложиться ПЕРВОЙ.
    _COUNTERFACTUAL_MARK = "двигается от САМОГО ФАКТА"

    def _reported_by_the_live_leg(self, why):
        """Поломка НАЗВАНА живой ногой, а не приехала через контрфакт.

        Найдено МУТАЦИЕЙ (прогон №1, ADR-792): подмена отображения исходов
        `BROKEN → SATISFIED` ВЫЖИЛА, потому что отказ всё равно возвращался —
        но уже второй ногой и с её формулировкой. Вердикт при этом совпадал, и
        мои контроли различить два пути не могли: каждый проверял лишь, что
        нужная подстрока где-то есть, а она есть и внутри сообщения контрфакта.
        Утверждение «кто доложил» делает отображение исходов проверяемым.
        """
        self.assertNotIn(self._COUNTERFACTUAL_MARK, why,
                         "о живой поломке доложил КОНТРФАКТ, а не своя нога — "
                         "значит отображение исходов пробы ничем не закреплено")

    def test_the_intact_contour_is_satisfied(self):
        """Положительный контроль: правило цело ⇒ критерий выполнен."""
        verdict, why = self._probe()
        self.assertEqual(verdict, ca.SATISFIED, why)
        self.assertIn("разрыв 1", why)

    def test_link_the_rule_widened_to_all_of_docs(self):
        """Звено 1: правило = «любое упоминание в docs/» ⇒ НЕ ВЫПОЛНЕН.

        Сцена собрана так, чтобы изолировать ИМЕННО это звено: летописи в ней
        нет (иначе первым сработало бы звено 2 — см. соседний случай), а
        `scripts/alone.py` назван обычной запиской `docs/NOTE.md`. Тексты при
        мутации не меняются ни на байт — меняется ТОЛЬКО состав реестров,
        поэтому смена вердикта доказывает, что судит правило.
        """
        (self.root / "docs" / "journal" / "2026-W33.md").unlink()
        (self.root / "docs" / "NOTE.md").write_text(
            "записка: scripts/alone.py когда-то считали полезным\n", encoding="utf-8")
        before, why_before = self._probe()
        self.assertEqual(before, ca.SATISFIED, why_before)
        every_doc = tuple(sorted(p.relative_to(self.root)
                                 for p in (self.root / "docs").rglob("*") if p.is_file()))
        with mock.patch.object(_unwired, "_PRODUCT_REGISTRIES", every_doc):
            verdict, why = self._probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("перестал сужать класс", why)
        self._reported_by_the_live_leg(why)

    def test_link_the_journal_became_evidence(self):
        """Звено 2: летопись внесена в реестры ⇒ НЕ ВЫПОЛНЕН, с ИМЕНЕМ скрипта."""
        widened = _unwired._PRODUCT_REGISTRIES + (
            pathlib.Path("docs") / "journal" / "2026-W33.md",)
        with mock.patch.object(_unwired, "_PRODUCT_REGISTRIES", widened):
            verdict, why = self._probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("journal_only", why)
        self.assertIn("летопись", why)
        self._reported_by_the_live_leg(why)

    def test_link_the_watch_has_no_wards_left(self):
        """Звено 3: прощены ВСЕ ⇒ вердикт храповика ничего не значит.

        Реестр R&D дописан так, что называет каждый скрипт без вызывающего;
        тогда подопечных не остаётся, и это отдельная поломка, а не «разрыв пуст».
        """
        (self.root / "docs" / "DYNAMIC_LEVERAGE_GUARDIAN.md").write_text(
            "### Идея #99 — scripts/measured.py, scripts/alone.py, "
            "scripts/journal_only.py\n", encoding="utf-8")
        verdict, why = self._probe()
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("без подопечных", why)
        self._reported_by_the_live_leg(why)

    def test_third_outcome_no_docs_tree(self):
        """Инв. #17: `docs/` нет ⇒ НЕ ИЗМЕРЕНО, а не «выполнен» и не «не выполнен».

        Причина обязана называть ИМЕННО отсутствие каталога: «каталога нет» и «в
        каталоге нет читаемых файлов» — два разных третьих исхода, и схлопнуть
        их значило бы снять один из двух отказов молча.
        """
        shutil.rmtree(self.root / "docs")
        verdict, why = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("каталога", why)

    def test_third_outcome_no_entrypoints(self):
        """Инв. #17: точек входа нет ⇒ НЕ ИЗМЕРЕНО (пустое население зеленит всё)."""
        for p in (self.root / "scripts").glob("*.py"):
            p.unlink()
        verdict, why = self._probe()
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("точек входа", why)

    def test_the_journal_is_a_subtree_not_a_substring(self):
        """`docs/journalism.md` — НЕ летопись, и это решает путь, а не подстрока.

        Подстрочная проверка («в пути есть `journal`») объявила бы летописью
        любой соседний каталог, и скрипт, названный обычной запиской, числился
        бы «упомянутым только в летописи» — то есть нога 2 судила бы не о том.
        """
        (self.root / "docs" / "journalism.md").write_text(
            "обзор: scripts/alone.py\n", encoding="utf-8")
        got = _unwired.carve_out_audit(self.root)
        self.assertIn("alone", got["rejected_rule_excused"])
        self.assertNotIn("alone", got["journal_only"])

    def test_an_argument_is_refused_out_loud(self):
        """Пофайловой формы у критерия нет: аргумент отвергается, а не глотается."""
        verdict, why = ca.run_probe(f"{PROBE}:alone", repo_root=str(self.root))
        self.assertEqual(verdict, ca.UNMEASURED, why)
        self.assertIn("не принимает аргумента", why)


class TestTheCounterfactualLeg(unittest.TestCase):
    """Вторая нога пробы — ДОСЛОВНЫЙ критерий карточки.

    «Новый `scripts/edge_*.py` с записью в реестре не краснит сторожа». Нога
    спрашивает это контрфактом у того же судьи, и доказательство её нужности —
    судья с утверждением о НАСЕЛЕНИИ: на живом правиле он молчит, а от одного
    нового замера краснеет. Ровно так вёл себя сторож до ADR-792.
    """

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self._tmp.name)
        _fake_repo(self.root)
        self.addCleanup(self._tmp.cleanup)

    def test_a_judge_that_counts_population_is_caught_by_the_counterfactual(self):
        """Судья с ДОЛЕЙ: живой вердикт зелёный, контрфакт красный ⇒ НЕ ВЫПОЛНЕН."""
        def ratio_judge(got):
            if not got.get("measured"):
                return _unwired.CARVE_OUT_UNMEASURED, got.get("reason", "")
            if len(got["excused"]) >= len(got["raw"]) / 2:
                return _unwired.CARVE_OUT_BROKEN, (
                    f"вычет забрал {len(got['excused'])} из {len(got['raw'])}")
            return _unwired.CARVE_OUT_OK, "доля вычета ниже половины"

        with mock.patch.object(_unwired, "carve_out_verdict", ratio_judge):
            # сначала убедимся, что на ЖИВОМ замере такой судья молчит
            live = ratio_judge(_unwired.carve_out_audit(self.root))
            self.assertEqual(live[0], _unwired.CARVE_OUT_OK, live[1])
            verdict, why = ca.run_probe(PROBE, repo_root=str(self.root))
        self.assertEqual(verdict, ca.NOT_SATISFIED, why)
        self.assertIn("двигается от САМОГО ФАКТА нового R&D-замера", why)

    def test_the_counterfactual_adds_the_script_in_all_three_roles(self):
        """Контрфакт честен: новый замер входит в `raw`, вычет и отвергнутое правило.

        Пропусти он одну роль — и контрфакт изображал бы не новый R&D-замер, а
        что-то другое; тогда зелёная нога ничего не значила бы.
        """
        got = _unwired.carve_out_audit(self.root)
        after = _unwired.carve_out_with_one_more_rnd_record(got)
        self.assertEqual(len(after["raw"]), len(got["raw"]) + 1)
        self.assertEqual(len(after["excused"]), len(got["excused"]) + 1)
        self.assertEqual(len(after["rejected_rule_excused"]),
                         len(got["rejected_rule_excused"]) + 1)
        self.assertEqual(after["watched"], got["watched"])
        self.assertEqual(after["narrowed"], got["narrowed"])
        self.assertEqual(after["journal_only_excused"], got["journal_only_excused"])

    def test_the_counterfactual_keeps_the_unmeasured_outcome(self):
        """НЕ ИЗМЕРЕНО контрфактом не превращается в измеренное (инв. #17)."""
        shutil.rmtree(self.root / "docs")
        got = _unwired.carve_out_audit(self.root)
        self.assertFalse(got["measured"])
        after = _unwired.carve_out_with_one_more_rnd_record(got)
        self.assertFalse(after["measured"])
        self.assertEqual(_unwired.carve_out_verdict(after)[0],
                         _unwired.CARVE_OUT_UNMEASURED)


class TestTheProbeIsWiredHonestly(unittest.TestCase):
    """Две вещи, без которых вердикт пробы был бы вердиктом о ДРУГОМ дереве."""

    def test_the_probe_declares_the_tree_as_an_input(self):
        """`repo_root` обязан быть ОБЪЯВЛЕН входом, иначе инъекция — половинная.

        `run_probe` доводит дерево только до проб, назвавших его в сигнатуре.
        Проба, читающая своё дерево молча, ответила бы на вопрос о рабочей копии,
        выдав его за ответ о стенде (`.claude/rules/deployment.md`).
        """
        self.assertEqual(ca.probe_tree_inputs(PROBE), ("repo_root",))

    def test_the_probe_is_registered(self):
        self.assertIn(PROBE, ca.PROBES)

    def test_the_probe_does_not_keep_a_second_copy_of_the_legs(self):
        """Ноги судит `_unwired.carve_out_verdict`, и это проверено РАЗБОРОМ.

        Вторая копия ног разошлась бы со сторожем молча, и «критерий карточки
        выполнен» стало бы вердиктом другого правила (класс ADR-522). Проверка
        по AST, а не подстрокой: подстрока нашлась бы и в этом докстринге.
        """
        tree = ast.parse(inspect.getsource(ca.PROBES[PROBE]))
        called = {
            node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        }
        self.assertIn("carve_out_verdict", called,
                      "проба не зовёт общего судью — значит судит своей копией ног")


if __name__ == "__main__":
    unittest.main()
