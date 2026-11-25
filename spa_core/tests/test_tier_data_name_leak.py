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


#: Сцена ДВУХ передач: помощник отдаёт полученное ТРЕТЬЕМУ, и только тот
#: что-то с ним делает. Прежняя мера (ADR-1097) судила РОВНО первого
#: получателя и на эту сцену отвечала `local_only` — ИЗМЕРЕННЫЙ ноль.
_TWO_HOP = '''
NAMES = ("tier_curator", "other")


def _deep(bag):
{deep}


def _helper(items):
    return _deep(items)


def run():
    return _helper(NAMES)
'''

#: Та же сцена, но передач ТРИ — чтобы «мера видит два хопа» не прошло за
#: «мера идёт до конца дороги»: предел объявлен входом и обязан быть виден.
_THREE_HOP = '''
NAMES = ("tier_curator", "other")


def _deeper(sack):
{deeper}


def _deep(bag):
    return _deeper(bag)


def _helper(items):
    return _deep(items)


def run():
    return _helper(NAMES)
'''

_LEAKS = ('    for it in bag:\n'
          '        open("data/" + it + "_report.json").read()\n')
_LEAKS_DEEPER = ('    for it in sack:\n'
                 '        open("data/" + it + "_report.json").read()\n')


class ValueHandedFurtherThanOneHop(unittest.TestCase):
    """Предмет ADR-1098: ADR-1097 печатал `local_only`, не заглянув дальше.

    Замер 25.11 на живом дереве: `tier_touch.tier_touches` отдаёт свой параметр
    `modules` ТРЕТЬЕМУ помощнику (`_module_matches`) и конструктору `Touch`, а
    прежняя мера объявила про него «не утекает» (3 наблюдения `local_only`).
    Ответ совпал с правдой СЛУЧАЙНО: в получателя никто не смотрел.

    Контроль здесь двусторонний И ДИФФЕРЕНЦИАЛЬНЫЙ: одна и та же сцена при
    `max_hops=1` обязана дать ТРЕТИЙ ИСХОД (честная форма прежнего ответа), а
    при глубине по умолчанию — НАЙТИ члена класса.
    """

    def test_a_leak_two_hops_away_is_a_member(self):
        text = _TWO_HOP.format(deep=_LEAKS)
        self.assertEqual(verdict(text), leak.CLASS_VERDICT)

    def test_the_SAME_scene_at_one_hop_is_unmeasured_NOT_local_only(self):
        text = _TWO_HOP.format(deep=_LEAKS)
        flow = leak.data_name_flows(text, max_hops=1)[0]
        self.assertEqual(
            flow.verdict, leak.UNMEASURED,
            "глубина ADR-1097 обязана ПРИЗНАТЬ, что дальше не смотрела: "
            "`local_only` здесь был бы ИЗМЕРЕННЫМ нулём, которого никто не "
            f"мерил — получено {flow.verdict!r}: {flow.why}")
        self.assertIn("отдано ДАЛЬШЕ", flow.why)

    def test_a_harmless_second_hop_is_a_measured_zero(self):
        text = _TWO_HOP.format(deep='    return sorted(bag)\n')
        flow = leak.data_name_flows(text)[0]
        self.assertEqual(flow.verdict, "local_only")
        self.assertIn(
            "НИКОМУ не отдано", flow.why,
            "ИЗМЕРЕННЫЙ ноль обязан сказать, ЧТО именно измерено: отсутствие "
            "следующей передачи проверено обходом, а не предположено")

    def test_the_value_RENAMED_inside_the_receiver_is_still_followed(self):
        """Второй хоп обязан спрашивать ЗАМЫКАНИЕ тела, а не имя параметра.

        Спроси он имя параметра — переупаковка `rows = list(bag)` оборвала бы
        дорогу, и мера ответила бы `local_only`: дефект 1 первой редакции
        (ADR-1097), только на хоп дальше.
        """
        text = _TWO_HOP.format(deep='    rows = list(bag)\n'
                                    '    return _deeper(rows)\n') + (
            '\n\ndef _deeper(sack):\n'
            '    for it in sack:\n'
            '        open("data/" + it + "_report.json").read()\n')
        self.assertEqual(verdict(text), leak.CLASS_VERDICT)

    def test_the_third_outcome_NAMES_the_receiver_it_did_not_enter(self):
        text = _TWO_HOP.format(deep=_LEAKS)
        flow = leak.data_name_flows(text, max_hops=1)[0]
        self.assertIn(
            "_deep", flow.why,
            "«не измерено» без имени получателя нечем ни проверить, ни "
            f"довести до конца: {flow.why}")

    def test_a_leak_three_hops_away_is_a_member_at_the_default_depth(self):
        text = _THREE_HOP.format(deeper=_LEAKS_DEEPER)
        self.assertEqual(verdict(text), leak.CLASS_VERDICT)

    def test_the_SAME_scene_at_two_hops_is_unmeasured(self):
        text = _THREE_HOP.format(deeper=_LEAKS_DEEPER)
        flow = leak.data_name_flows(text, max_hops=2)[0]
        self.assertEqual(flow.verdict, leak.UNMEASURED,
                         "предел — ВХОД, и исчерпан он или нет, обязано быть "
                         f"видно: {flow.why}")

    def test_a_parameter_DEFAULT_also_walks_the_road_further(self):
        """Живая находка 25.11 пришла ИМЕННО этой дорогой.

        `tier_touch.TIER_CANON_MODULES` входит в чужое тело УМОЛЧАНИЕМ
        параметра, и это тело отдаёт полученное дальше. Суди умолчание одним
        вопросом «что делает ЭТО тело» — и класс снова прячется за словом
        `local_only`.
        """
        text = ('MODS = ("tier_curator", "other")\n'
                'def _deep(bag):\n'
                '    for it in bag:\n'
                '        open("data/" + it + "_report.json").read()\n'
                'def eat(x, mods=MODS):\n'
                '    return _deep(mods)\n')
        self.assertEqual(verdict(text), leak.CLASS_VERDICT)

    def test_the_depth_is_a_named_measurement_not_a_taste(self):
        self.assertGreaterEqual(
            leak.DEFAULT_MAX_HOPS, 2,
            "глубина 1 воспроизводит слепоту ADR-1097 — ответ о живой "
            "поверхности устанавливается на глубине 2")

    def test_a_budget_below_one_hop_refuses_instead_of_answering_clean(self):
        text = _TWO_HOP.format(deep=_LEAKS)
        with self.assertRaises(leak.TierDataNameLeakUnmeasured):
            leak.data_name_flows(text, max_hops=0)


class TheNextHopIsJudgedByITSOwnModule(unittest.TestCase):
    """Второй хоп обязан спрашивать ввозы ТОГО модуля, где лежит получатель.

    Спроси он ввозы ПЕРВОГО модуля — помощник чужого модуля, зовущий своего
    соседа, читался бы как неразрешимый, и утечка спряталась бы за третьим
    исходом. Это дословно дефект 3 первой редакции меры (ADR-1097), только на
    хоп дальше.
    """

    _MAIN = ('from helpers import eat\n'
             'NAMES = ("tier_curator", "other")\n'
             'def run():\n'
             '    return eat(NAMES)\n')
    _HELPERS = ('from deeper import dig\n'
                'def eat(items):\n'
                '    return dig(items)\n')

    def test_a_leak_behind_TWO_imports_is_a_member(self):
        deeper = ('def dig(bag):\n'
                  '    for it in bag:\n'
                  '        open("data/" + it + "_report.json").read()\n')
        got = verdict(self._MAIN, resolve=_resolver(helpers=self._HELPERS,
                                                    deeper=deeper))
        self.assertEqual(got, leak.CLASS_VERDICT)

    def test_the_same_road_with_a_harmless_end_is_a_measured_zero(self):
        deeper = 'def dig(bag):\n    return sorted(bag)\n'
        got = verdict(self._MAIN, resolve=_resolver(helpers=self._HELPERS,
                                                    deeper=deeper))
        self.assertEqual(got, "local_only")

    def test_the_THIRD_hop_needs_the_SECOND_module_imports(self):
        """Различающая сцена: утечка лежит за ТРЕТЬИМ модулем.

        Дорога из двух модулей М08 не убивает — её последнее звено есть сама
        дверь, и чьи ввозы спрашивал предыдущий хоп, на вердикт не влияет.
        Сцена-близнец с ТРЕМЯ модулями отличается от неё РОВНО тем звеном,
        которое мерит: `sink` разрешается только ввозами `deeper`. Мутация
        «спрашивать ввозы первого модуля» на первой сцене ВЫЖИЛА и была дырой
        СЦЕНЫ, а не кода (мутационный прогон #1243, M08).
        """
        deeper = ('from deepest import sink\n'
                  'def dig(bag):\n'
                  '    return sink(bag)\n')
        deepest = ('def sink(sack):\n'
                   '    for it in sack:\n'
                   '        open("data/" + it + "_report.json").read()\n')
        got = verdict(self._MAIN, resolve=_resolver(helpers=self._HELPERS,
                                                    deeper=deeper,
                                                    deepest=deepest))
        self.assertEqual(got, leak.CLASS_VERDICT)

    def test_an_unreadable_second_module_is_unmeasured_not_clean(self):
        flow = leak.data_name_flows(
            self._MAIN, resolve=_resolver(helpers=self._HELPERS))[0]
        self.assertEqual(flow.verdict, leak.UNMEASURED,
                         f"исходника второго хопа нет — выдумать его поведение "
                         f"нечем: {flow.why}")


class TheRoadStopsWithoutLying(unittest.TestCase):
    """Дорога, у которой нет конца, обязана СКАЗАТЬ это, а не замкнуться."""

    def test_a_cycle_of_handovers_is_unmeasured_with_a_named_cause(self):
        text = ('NAMES = ("tier_curator",)\n'
                'def _a(bag):\n'
                '    return _b(bag)\n'
                'def _b(bag):\n'
                '    return _a(bag)\n'
                'def run():\n'
                '    return _a(NAMES)\n')
        flow = leak.data_name_flows(text)[0]
        self.assertEqual(flow.verdict, leak.UNMEASURED)
        self.assertIn("ЦИКЛ передач", flow.why)

    def test_an_unresolvable_PARAM_of_the_next_receiver_is_unmeasured(self):
        """Получатель разрешён, а КАКОЙ его параметр принял значение — нет.

        Третий исход здесь обязан быть своим: мера нашла тело, но не нашла в
        нём величину, и судить это тело ей нечем. `local_only` был бы
        ИЗМЕРЕННЫМ нулём про область, которую она не прочла. Мутация M05 прогона
        #1243 выжила ровно потому, что такой сцены не было.
        """
        text = _TWO_HOP.format(deep='    return _third(0, bag)\n') + (
            '\n\ndef _third(a):\n'
            '    return a\n')
        flow = leak.data_name_flows(text)[0]
        self.assertEqual(flow.verdict, leak.UNMEASURED)
        self.assertIn("параметр получателя", flow.why)

    def test_a_constructor_of_an_unresolvable_class_is_unmeasured(self):
        """Живая находка 25.11: `Touch(hit, …)` в `tier_touch`.

        Класс телом-функцией не является, разрешать его нечем, и что он делает
        с полученной величиной — вопрос ДРУГОГО класса (`self.writer.save(x)`,
        ADR-1097). Назвать это `local_only` значило бы объявить измеренным то,
        чего мера не видела.
        """
        text = _TWO_HOP.format(deep='    return Box(bag)\n')
        flow = leak.data_name_flows(text)[0]
        self.assertEqual(flow.verdict, leak.UNMEASURED)
        self.assertIn("НЕ РАЗРЕШЁН", flow.why)


class TheLiveThirdOutcomeIsNamed(unittest.TestCase):
    """«НЕ ИЗМЕРЕНО» на живом дереве обязано быть НАЗВАННЫМ, а не числом.

    ADR-1097 объявил по этой поверхности «НЕ ИЗМЕРЕНО 0». Замер ADR-1098 на
    той же поверхности той же дверью даёт **1**, и ноль был следствием
    глубины, а не свойством дерева. Сторож держит не число (оно будет меняться
    вместе с деревом), а ФОРМУ ответа: у каждого третьего исхода назван и
    получатель, и причина.
    """

    def test_every_live_unmeasured_flow_names_its_cause(self):
        silent = []
        for rel, src in LiveCensus()._surface():
            for flow in leak.data_name_flows(src,
                                             resolve=LiveCensus._resolve):
                if flow.verdict != leak.UNMEASURED:
                    continue
                if not flow.why or "НЕ ИЗМЕРЕНО" not in flow.why:
                    silent.append(f"{rel}:{flow.line} {flow.why!r}")
        self.assertEqual(
            silent, [],
            "третий исход без названной причины неотличим от «не утекает» "
            "(инв. #17):\n  " + "\n  ".join(silent))
