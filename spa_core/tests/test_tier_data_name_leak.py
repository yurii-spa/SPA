"""Сторож меры «имя-данные, дошедшее до диска окольно» (ADR-1097, заказ G1080 п. 2).

Мера отвечает на вопрос, который ADR-1096 назвал НЕ ИЗМЕРЕННЫМ про себя: роль
вхождения решает НЕПОСРЕДСТВЕННЫЙ родитель узла, поэтому голое имя, отданное
чужому помощнику, прежняя мера видеть не могла по построению.

**У каждой сцены контроль в ОБЕ стороны.** Мера, зелёная всегда, прошла бы
«класс пуст» и ничего бы этим не сказала: ноль есть НАБЛЮДЕНИЕ только когда
живая сцена С утечкой даёт члена. Поэтому положительных контролей здесь два —
местный помощник и помощник ЗА ввозом (один хоп), — и каждый отрицательный
контроль отличается от своего положительного РОВНО тем звеном, которое мерит.

**Три дефекта МОЕЙ ЖЕ первой редакции закреплены дословно** (замер 25.11): она
спрашивала ОДНО имя и объявила `local_only` два модуля, у которых привязка
отдаётся наружу; её модульное замыкание спускалось в тела функций и объявляло
получателем `str.endswith`; приём значения в контейнер (`rows.append`) читался
как неразрешимый получатель. Каждый дефект шёл в ОПАСНУЮ сторону — «не
утекает» либо «НЕ ИЗМЕРЕНО» вместо названного ответа, — и каждый ловится
отдельной сценой ниже.
"""
from __future__ import annotations

import pathlib
import unittest

from spa_core.monitoring import tier_data_name_leak as leak
from spa_core.monitoring import tier_report_consumption as trc

REPO = pathlib.Path(__file__).resolve().parents[2]

#: Сцена-основа: голое имя элементом кортежа и привязка, отданная помощнику.
#: Все положительные и отрицательные контроли — ВАРИАНТЫ этой сцены, чтобы
#: разница между «утекает» и «не утекает» была РОВНО в теле помощника.
_SCENE = '''
NAMES = ("tier_curator", "other")


def _helper(items):
{body}


def run():
    return _helper(NAMES)
'''


def scene(body: str) -> str:
    return _SCENE.format(body=body)


def _resolver(**modules):
    """Разрешитель одного хопа: имя модуля → исходник. `None` = НЕ ИЗМЕРЕНО."""
    def resolve(name: str):
        return modules.get(name)
    return resolve


def verdict(text: str, **kw) -> str:
    flows = leak.data_name_flows(text, **kw)
    assert len(flows) == 1, f"ожидалось одно вхождение-данные, получено {flows}"
    return flows[0].verdict


class PositiveControls(unittest.TestCase):
    """Утечка ЕСТЬ — мера обязана её НАЙТИ. Без этого ноль ничего не значит."""

    def test_a_local_helper_that_assembles_the_report_path_is_a_member(self):
        text = scene('    for it in items:\n'
                     '        p = "data/" + it + "_report.json"\n'
                     '        open(p).read()\n')
        flows = leak.data_name_flows(text)
        self.assertEqual(flows[0].verdict, leak.CLASS_VERDICT)
        self.assertTrue(flows[0].is_member)

    def test_a_helper_BEHIND_AN_IMPORT_is_a_member_too(self):
        """Один хоп: получатель живёт в ЧУЖОМ модуле и разрешается `resolve`."""
        text = ('from spa_core.helpers import eat\n'
                'NAMES = ("tier_curator",)\n'
                'def run():\n'
                '    return eat(NAMES)\n')
        foreign = ('def eat(items):\n'
                   '    for it in items:\n'
                   '        open("data/" + it + "_report.json").read()\n')
        got = leak.data_name_flows(
            text, resolve=_resolver(**{"spa_core.helpers": foreign}))
        self.assertEqual(got[0].verdict, leak.CLASS_VERDICT)
        self.assertEqual(got[0].hop, "import:spa_core.helpers")

    def test_the_report_token_alone_is_enough_without_assembly(self):
        text = scene('    open("data/tier_curator_report.json").read()\n'
                     '    return items\n')
        self.assertEqual(verdict(text), leak.CLASS_VERDICT)


class NegativeControls(unittest.TestCase):
    """Утечки НЕТ — мера обязана молчать, и молчать с НАЗВАННОЙ причиной."""

    def test_a_helper_that_touches_nothing_is_local_only(self):
        text = scene('    return sorted(items)\n')
        self.assertEqual(verdict(text), "local_only")

    def test_reaching_a_DIFFERENT_file_is_not_the_class(self):
        """Мера УЖЕ файловой системы: чужой путь членом класса не делает."""
        text = scene('    for it in items:\n'
                     '        open("data/" + it + "_cadence.json").read()\n')
        flows = leak.data_name_flows(text)
        self.assertEqual(flows[0].verdict, "reaches_fs")
        self.assertFalse(flows[0].is_member,
                         "мера стала шире класса — ровно дефект, который "
                         "ADR-1096 чинил у прежней подстроки")

    def test_matching_a_path_without_opening_it_is_the_near_miss(self):
        text = scene('    for it in items:\n'
                     '        if it in path:\n'
                     '            return it\n'
                     '    return None\n')
        flows = leak.data_name_flows(text)
        self.assertEqual(flows[0].verdict, "selects_path")
        self.assertFalse(flows[0].is_member)


class ThirdOutcome(unittest.TestCase):
    """«НЕ ИЗМЕРЕНО» отличимо от «не утекает» — инв. #17."""

    def test_an_unresolved_foreign_receiver_is_unmeasured_not_clean(self):
        text = ('from spa_core.helpers import eat\n'
                'NAMES = ("tier_curator",)\n'
                'def run():\n'
                '    return eat(NAMES)\n')
        flows = leak.data_name_flows(text, resolve=None)
        self.assertEqual(flows[0].verdict, leak.UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНО", flows[0].why)
        self.assertEqual(leak.unmeasured(flows), flows)

    def test_unparsed_source_raises_instead_of_answering_clean(self):
        with self.assertRaises(leak.TierDataNameLeakUnmeasured):
            leak.data_name_flows('NAMES = ("tier_curator",\n')

    def test_measured_zero_and_unmeasured_differ_by_exactly_one_field(self):
        """Две сцены, отличающиеся РОВНО разрешимостью получателя."""
        foreign = 'def eat(items):\n    return sorted(items)\n'
        text = ('from spa_core.helpers import eat\n'
                'NAMES = ("tier_curator",)\n'
                'def run():\n'
                '    return eat(NAMES)\n')
        measured = leak.data_name_flows(
            text, resolve=_resolver(**{"spa_core.helpers": foreign}))
        unmeasured = leak.data_name_flows(text, resolve=None)
        self.assertEqual(measured[0].verdict, "local_only")
        self.assertEqual(unmeasured[0].verdict, leak.UNMEASURED)


class ClosureDefectsOfMyFirstEdition(unittest.TestCase):
    """Три дефекта первой редакции меры — дословно, каждый своей сценой."""

    def test_a_value_unpacked_from_items_is_still_followed(self):
        """Дефект 1: `EVENT_ARTIFACT_FRAGMENTS` отдавался через `.items()`."""
        text = ('FRAG = {"Tier change": ("tier_curator",)}\n'
                'def _eat(fragments):\n'
                '    for fr in fragments:\n'
                '        open("data/" + fr + "_report.json").read()\n'
                'def run():\n'
                '    for event, fragments in FRAG.items():\n'
                '        _eat(fragments)\n')
        flows = leak.data_name_flows(text)
        self.assertEqual(flows[0].verdict, leak.CLASS_VERDICT,
                         "распаковка `.items()` снова рвёт поток — вернулся "
                         "ложный `local_only` замера 25.11")

    def test_a_parameter_DEFAULT_is_a_handover_too(self):
        """Дефект 1б: `TIER_CANON_MODULES` входит в функцию УМОЛЧАНИЕМ."""
        text = ('MODS = ("tier_curator",)\n'
                'def eat(x, mods=MODS):\n'
                '    for m in mods:\n'
                '        open("data/" + m + "_report.json").read()\n')
        flows = leak.data_name_flows(text)
        self.assertEqual(flows[0].verdict, leak.CLASS_VERDICT)
        self.assertEqual(flows[0].hop, "local:default")

    def test_a_method_OF_THE_VALUE_is_not_a_receiver(self):
        """Дефект 2: `mod.endswith(...)` объявлялся неразрешимым получателем."""
        text = ('MODS = ("tier_curator",)\n'
                'def run(dotted):\n'
                '    for mod in MODS:\n'
                '        if dotted.endswith("." + mod):\n'
                '            return mod\n'
                '    return None\n')
        flows = leak.data_name_flows(text)
        self.assertNotEqual(flows[0].verdict, leak.UNMEASURED,
                            "метод самого значения снова читается как чужой "
                            "помощник — третий исход прячет настоящий ответ")

    def test_admission_into_a_container_continues_the_flow(self):
        """Дефект 3: `rows.append(x)` читался как неразрешимый получатель."""
        text = ('NAMES = ("tier_curator",)\n'
                'def _eat(bag):\n'
                '    open("data/" + bag[0] + "_report.json").read()\n'
                'def run():\n'
                '    rows = []\n'
                '    for n in NAMES:\n'
                '        rows.append(n)\n'
                '    return _eat(rows)\n')
        flows = leak.data_name_flows(text)
        self.assertEqual(flows[0].verdict, leak.CLASS_VERDICT,
                         "приём в контейнер снова рвёт поток")

    def test_a_shaping_call_is_not_a_receiver_but_keeps_the_flow(self):
        text = ('NAMES = {"tier_curator": 1}\n'
                'def _eat(bag):\n'
                '    open("data/tier_curator_report.json").read()\n'
                '    return bag\n'
                'def run():\n'
                '    frozen = frozenset(NAMES)\n'
                '    return _eat(frozen)\n')
        flows = leak.data_name_flows(text)
        self.assertEqual(flows[0].verdict, leak.CLASS_VERDICT,
                         "`frozenset(NAMES)` снова объявлен получателем — "
                         "продолжение потока спрятано за третьим исходом")


class TheMeasureHasOneDoor(unittest.TestCase):
    """Своей копии правила ролей у меры нет — иначе она разошлась бы с ADR-1096."""

    def test_the_role_rule_is_imported_not_copied(self):
        text = (REPO / "spa_core" / "monitoring"
                / "tier_data_name_leak.py").read_text(encoding="utf-8")
        self.assertIn("from spa_core.monitoring.tier_report_consumption import", text)
        self.assertNotIn("_DATA_CONTAINERS = (", text,
                         "мера завела СВОЮ копию правила «что есть данные» — "
                         "разойдись она с ADR-1096, роли стало бы две")

    def test_the_class_is_exactly_one_verdict(self):
        self.assertEqual(leak.CLASS_VERDICT, "reaches_report")
        for other in ("reaches_fs", "selects_path", "local_only", leak.UNMEASURED):
            flow = leak.Flow("tier_curator", 1, "X", other, "—")
            self.assertFalse(flow.is_member,
                             f"вердикт {other} стал членом класса — мера "
                             f"перестала быть УЖЕ файловой системы")


class LiveCensus(unittest.TestCase):
    """Живой замер населения. Пустая поверхность — НЕ «чисто», а НЕ ИЗМЕРЕНО."""

    @staticmethod
    def _resolve(module: str):
        for candidate in (REPO / (module.replace(".", "/") + ".py"),
                          REPO / module.replace(".", "/") / "__init__.py"):
            if candidate.is_file():
                return candidate.read_text(encoding="utf-8")
        return None

    def _surface(self):
        out = []
        for path in sorted((REPO / "spa_core").rglob("*.py")):
            rel = str(path.relative_to(REPO))
            if "/tests/" in rel or path.name.startswith("test_"):
                continue
            try:
                src = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            if trc.MODULE_TOKEN not in src:
                continue
            try:
                found = trc.mentions(src)
            except trc.TierReportConsumptionUnmeasured:
                continue
            if not any(m.kind == "data" for m in found):
                continue
            if trc.consumes_report(src):
                continue
            out.append((rel, src))
        return out

    def test_the_surface_is_not_vacuous(self):
        surface = self._surface()
        self.assertGreaterEqual(
            len(surface), 1,
            "поверхность класса ПУСТА — судить о населении нечем; это НЕ "
            "ИЗМЕРЕНО (инв. #17), а не «членов нет»")

    def test_no_member_of_the_class_lives_in_the_tree(self):
        found = []
        for rel, src in self._surface():
            for flow in leak.data_name_flows(src, resolve=self._resolve):
                if flow.is_member:
                    found.append(f"{rel}:{flow.line} {flow.why}")
        self.assertEqual(
            found, [],
            "появился модуль, отдающий голое имя куратора помощнику, который "
            "добирается до ОТЧЁТА: сторож `test_tier_curator` его не увидит "
            "по построению (ADR-1096 судит непосредственного родителя), и "
            "советательный отчёт получил бы читателя молча:\n  "
            + "\n  ".join(found))


class StdlibMethodIsALeafButADoorIsNot(unittest.TestCase):
    """Вычет метода-листа обязан различать строку и дверь файловой системы."""

    def test_a_string_method_receiving_the_value_is_a_leaf(self):
        text = ('MODS = ("tier_curator",)\n'
                'def run(dotted):\n'
                '    for mod in MODS:\n'
                '        if dotted.endswith("." + mod):\n'
                '            return mod\n'
                '    return None\n')
        self.assertNotEqual(leak.data_name_flows(text)[0].verdict, leak.UNMEASURED)

    def test_a_filesystem_METHOD_is_NOT_excused_by_that_deduction(self):
        """Обратная сторона того же вычета: `write_text` обязан остаться виден."""
        text = ('from pathlib import Path\n'
                'MODS = ("tier_curator",)\n'
                'def run(out):\n'
                '    for mod in MODS:\n'
                '        out.write_text(mod)\n')
        flows = leak.data_name_flows(text)
        self.assertEqual(flows[0].verdict, "reaches_fs",
                         "дверь файловой системы попала под вычет метода-листа "
                         "— вычет снял с учёта саму утечку")


class TheBuiltinDeductionKeepsTheDoor(unittest.TestCase):
    """Вычет встроенных имён обязан НЕ снимать с учёта `open`."""

    def test_open_is_not_excused_by_the_builtin_deduction(self):
        self.assertIn("open", leak.FS_DOORS)
        self.assertNotIn("open", leak._BUILTIN_LEAVES,
                         "`open` попал в вычет встроенных — вычет снял с учёта "
                         "единственную встроенную дверь файловой системы")

    def test_the_builtin_list_is_measured_not_handwritten(self):
        """Перечень снят у интерпретатора: `sum`/`min`/`any` там уже есть."""
        for name in ("sum", "min", "max", "any", "all", "frozenset", "sorted"):
            self.assertIn(name, leak._BUILTIN_LEAVES,
                          f"{name} пришлось бы дописывать руками — вернулась "
                          f"форма «белый список имён»")

    def test_a_builtin_shaping_call_does_not_hide_a_leak_behind_it(self):
        text = ('NAMES = ("tier_curator",)\n'
                'def _eat(bag):\n'
                '    open("data/" + bag[0] + "_report.json").read()\n'
                'def run():\n'
                '    return _eat(sorted(NAMES))\n')
        self.assertEqual(leak.data_name_flows(text)[0].verdict,
                         leak.CLASS_VERDICT)


class ADirectCallArgument(unittest.TestCase):
    """Контейнер, переданный зову НА МЕСТЕ: привязки нет, судится получатель.

    Ветка не имела ни одной сцены до 25.11 и звала снятую функцию — то есть
    падала бы `NameError` на первом же таком модуле. Нашёл её `pyflakes`, а не
    тест; дыра покрытия закрыта в ОБЕ стороны.
    """

    def test_a_literal_handed_straight_to_a_leaking_helper_is_a_member(self):
        text = ('def _eat(items):\n'
                '    for it in items:\n'
                '        open("data/" + it + "_report.json").read()\n'
                'def run():\n'
                '    return _eat(("tier_curator", "other"))\n')
        flows = leak.data_name_flows(text)
        self.assertEqual(flows[0].verdict, leak.CLASS_VERDICT)
        self.assertIsNone(flows[0].binding,
                          "у литерала на месте привязки быть не может")

    def test_a_literal_handed_straight_to_a_harmless_helper_is_not(self):
        text = ('def _eat(items):\n'
                '    return sorted(items)\n'
                'def run():\n'
                '    return _eat(("tier_curator", "other"))\n')
        self.assertEqual(leak.data_name_flows(text)[0].verdict, "local_only")

    def test_an_unresolved_direct_receiver_is_unmeasured(self):
        text = ('from spa_core.helpers import eat\n'
                'def run():\n'
                '    return eat(("tier_curator",))\n')
        self.assertEqual(leak.data_name_flows(text, resolve=None)[0].verdict,
                         leak.UNMEASURED)
