"""Батарея прибора `_fixture_schema_gap`: контроль в ОБЕ стороны.

# LLM_FORBIDDEN

Заказ G697 п. 2 (ADR-698). Правило приёмки ADR-333: проба меряет ИСХОД, и у
неё есть контроль в обе стороны — класс находится там, где он есть, и НЕ
находится там, где его нет, с НАЗВАННЫМ звеном. Три исхода различены РАЗНЫМИ
сценами с НЕРАВНЫМИ счётами, иначе подмена одного исхода другим невидима
(урок #786).

Дат в фикстурах нет ВОВСЕ: предметом здесь является форма документа, и
календарь к ней отношения не имеет.
"""
from __future__ import annotations

import sys
import textwrap
import unittest
from pathlib import Path

from spa_core.tests import _fixture_schema_gap as gap


def _has_path(data, path: str) -> bool:
    """Правило шага 0-офис, приведённое ВХОДОМ.

    Это дословная копия `consume_office_reports._has_path`, и она здесь не
    вторым правилом, а МАТЕРИАЛОМ контроля: отдельный тест ниже доказывает,
    что прибор зовёт именно переданную функцию, а не считает «есть ли поле»
    сам. Для батареи важно лишь, что вход — спрашиваемый.
    """
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


class _Scene:
    """Одноразовое дерево тестов: каталог `t/` с написанными файлами."""

    def __init__(self, tmp: Path):
        self.root = tmp
        (self.root / "t").mkdir(parents=True, exist_ok=True)

    def write(self, name: str, body: str) -> None:
        (self.root / "t" / name).write_text(textwrap.dedent(body),
                                            encoding="utf-8")

    def measure(self, schema: dict, has_path=_has_path) -> gap.Census:
        return gap.measure(schema=schema, has_path=has_path,
                           root=str(self.root), test_dirs=("t",))


class _SceneCase(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        self.scene = _Scene(Path(self._tmp.name))
        self.addCleanup(self._tmp.cleanup)


class TheClassIsFoundWhereItIs(_SceneCase):
    """Прямая сторона: объявленный путь, которого фикстура не несёт."""

    def test_a_flat_declared_key_absent_from_the_fixture_is_the_population(self):
        self.scene.write("test_a.py", '''
            def t():
                doc = {"status": "CLEAN"}
                return office._summarize_json("data/a.json", doc)
        ''')
        census = self.scene.measure({"a.json": ("status", "counts")})
        self.assertEqual(len(census.population), 1, census.sites)
        self.assertEqual(census.population[0].missing, ("counts",))
        self.assertEqual(census.pairs, 1)

    def test_a_nested_declared_path_absent_under_a_present_parent_is_found(self):
        """`counts` есть, `counts.day_axis` нет — именно этим платили четыре цикла."""
        self.scene.write("test_b.py", '''
            def t():
                doc = {"counts": {"lists_total": 3}}
                return office._summarize_json("data/b.json", doc)
        ''')
        census = self.scene.measure(
            {"b.json": ("counts.lists_total", "counts.day_axis")})
        self.assertEqual([s.missing for s in census.population],
                         [("counts.day_axis",)])

    def test_the_document_is_followed_through_a_helper_of_the_same_file(self):
        """Документ почти никогда не стои́т в аргументе литералом."""
        self.scene.write("test_c.py", '''
            def _doc():
                return {"status": "CLEAN"}

            def t():
                return office._summarize_json("data/c.json", _doc())
        ''')
        census = self.scene.measure({"c.json": ("status", "order")})
        self.assertEqual([s.missing for s in census.population], [("order",)])

    def test_the_document_is_followed_through_a_method_of_the_same_class(self):
        self.scene.write("test_d.py", '''
            class S:
                def _doc(self):
                    return {"status": "CLEAN"}

                def t(self):
                    return office._summarize_json("data/d.json", self._doc())
        ''')
        census = self.scene.measure({"d.json": ("status", "order")})
        self.assertEqual([s.missing for s in census.population], [("order",)])

    def test_the_key_of_the_ratchet_is_file_and_artifact_not_the_line(self):
        """Два вызова одного артефакта из файла — ОДИН ключ, а не два."""
        self.scene.write("test_e.py", '''
            def t():
                office._summarize_json("data/e.json", {"status": 1})
                office._summarize_json("data/e.json", {"status": 2})
        ''')
        census = self.scene.measure({"e.json": ("status", "order")})
        self.assertEqual(census.by_key(), {"t/test_e.py::e.json": 1})
        self.assertEqual(len(census.population), 2,
                         "площадок две, а ключ один — это РАЗНЫЕ числа")


class TheClassIsNotFoundWhereItIsNot(_SceneCase):
    """Обратная сторона: каждое звено порвано по отдельности и НАЗВАНО."""

    def test_a_fixture_carrying_every_declared_path_is_not_population(self):
        self.scene.write("test_f.py", '''
            def t():
                doc = {"status": "CLEAN", "counts": {"day_axis": {}}}
                return office._summarize_json("data/f.json", doc)
        ''')
        census = self.scene.measure(
            {"f.json": ("status", "counts", "counts.day_axis")})
        self.assertEqual(census.population, [])
        self.assertEqual(len(census.sites), 1, "площадка обязана быть ЗАМЕРЕНА")

    def test_a_declared_path_present_only_in_one_branch_counts_as_carried(self):
        """Объединение присваиваний, а не пересечение: иначе отрицательный
        контроль («документ БЕЗ раздела») объявлялся бы находкой."""
        self.scene.write("test_g.py", '''
            def t(flag):
                counts = {"a": 1}
                if flag:
                    counts = {"a": 1, "b": 2}
                return office._summarize_json("data/g.json", {"counts": counts})
        ''')
        census = self.scene.measure({"g.json": ("counts.a", "counts.b")})
        self.assertEqual(census.population, [])

    def test_a_deliberate_removal_declared_by_a_MARKER_is_an_exemption(self):
        """Намеренное снятие раздела выходит из класса ПОМЕТКОЙ, а не слепотой.

        ИЗМЕНЁН НАМЕРЕННО, цикл #849 (ADR-705, заказ G699 п. 3), инв. #16.
        Прежде этот тест пришпиливал обратное утверждение —
        «`doc["counts"].pop(...)` населением НЕ является», дословное правило
        ADR-698 («копия с мутациями считается той же фикстурой»). Заказ
        потребовал замерить ЦЕНУ этого правила, и она измерена: у ТРЁХ
        площадок живого дерева вердикт от него неверен — у двух объявленный
        путь до двери не доезжает вовсе (`del drifted["house_view"]
        ["top_opportunities"]`, `doc["counts"].pop("candidate_kind")`), у
        третьей, наоборот, обвинение было ЛОЖНЫМ (зовущие дописывают раздел
        присваиванием по ключу). Поэтому проверка УСИЛЕНА, а не ослаблена:
        площадка класса теперь ВИДНА, и честный выход из него — тот же, что у
        остальных 30 освобождений: пометка с причиной. Слепота давала тот же
        зелёный вердикт, только без причины и без следа.
        """
        self.scene.write("test_h.py", '''
            def _doc():
                return {"counts": {"day_axis": {}}}

            def t():
                doc = _doc()
                # SCHEMA-GAP-OK: предмет сцены — отсутствие раздела
                doc["counts"].pop("day_axis")
                return office._summarize_json("data/h.json", doc)
        ''')
        census = self.scene.measure({"h.json": ("counts.day_axis",)})
        self.assertEqual(census.population, [])
        self.assertEqual(len(census.exempt), 1, "освобождение обязано СЧИТАТЬСЯ")

    def test_the_same_removal_WITHOUT_a_marker_is_the_population(self):
        """Обратная сторона той же правки: без причины это население."""
        self.scene.write("test_h2.py", '''
            def _doc():
                return {"counts": {"day_axis": {}}}

            def t():
                doc = _doc()
                doc["counts"].pop("day_axis")
                return office._summarize_json("data/h2.json", doc)
        ''')
        census = self.scene.measure({"h2.json": ("counts.day_axis",)})
        self.assertEqual([s.missing for s in census.population],
                         [("counts.day_axis",)])

    def test_a_copy_of_the_fixture_is_the_same_fixture(self):
        self.scene.write("test_i.py", '''
            import copy
            BASE = {"status": "CLEAN", "order": 1}

            def t():
                degraded = copy.deepcopy(BASE)
                degraded["status"] = "STALE"
                return office._summarize_json("data/i.json", degraded)
        ''')
        census = self.scene.measure({"i.json": ("status", "order")})
        self.assertEqual(census.population, [])

    def test_a_dict_comprehension_resolves_to_its_base(self):
        self.scene.write("test_j.py", '''
            BASE = {"status": "CLEAN", "order": 1}

            def t():
                noden = {k: v for k, v in BASE.items() if k != "order"}
                return office._summarize_json("data/j.json", noden)
        ''')
        census = self.scene.measure({"j.json": ("status", "order")})
        self.assertEqual(census.population, [])

    def test_a_star_spread_carries_the_base(self):
        self.scene.write("test_k.py", '''
            BASE = {"status": "CLEAN", "order": 1}

            def t():
                return office._summarize_json("data/k.json", {**BASE, "x": 2})
        ''')
        census = self.scene.measure({"k.json": ("status", "order")})
        self.assertEqual(census.population, [])

    def test_an_artifact_the_schema_does_not_declare_is_out_of_subject(self):
        """Не объявлено ⇒ стеречь нечего. Это НЕ находка и НЕ «не измерено»."""
        self.scene.write("test_l.py", '''
            def t():
                return office._summarize_json("data/stranger.json", {"x": 1})
        ''')
        census = self.scene.measure({"l.json": ("status",)})
        self.assertEqual(census.population, [])
        self.assertEqual(census.unmeasured, [])
        self.assertEqual([row[2] for row in census.out_of_subject],
                         ["stranger.json"])

    def test_a_file_without_the_door_is_not_scanned_at_all(self):
        self.scene.write("test_m.py", '''
            def t():
                doc = {"status": "CLEAN"}
                return doc
        ''')
        census = self.scene.measure({"m.json": ("status", "order")})
        self.assertEqual(census.files_scanned, 0)
        self.assertEqual(census.population, [])


class TheThirdOutcomeIsItsOwnAnswer(_SceneCase):
    """НЕ ИЗМЕРЕНО не сворачивается ни в находку, ни в чистоту (инв. #17)."""

    def test_an_unresolvable_artifact_name_is_named_not_counted_as_clean(self):
        self.scene.write("test_n.py", '''
            def t(name):
                return office._summarize_json(name, {"x": 1})
        ''')
        census = self.scene.measure({"n.json": ("status",)})
        self.assertEqual(census.population, [])
        self.assertEqual([row[1] for row in census.unmeasured],
                         ["artifact_name_unresolved"])

    def test_an_unresolvable_document_is_named_not_counted_as_clean(self):
        self.scene.write("test_o.py", '''
            def t(report):
                return office._summarize_json("data/o.json", report)
        ''')
        census = self.scene.measure({"o.json": ("status",)})
        self.assertEqual(census.population, [])
        # Причина НАЗВАНА точнее, чем «имя не связано»: имя есть ПАРАМЕТР, а
        # вызовов у его функции нет ни одного, и спросить у вызывающего не у
        # кого (ADR-699). Два разных отказа — две разных причины.
        self.assertEqual([row[1] for row in census.unmeasured],
                         ["doc_unresolved:param_no_call_site"])

    def test_a_name_that_is_neither_assigned_nor_a_parameter_stays_unbound(self):
        """Обратная сторона предыдущего: «не параметр» — своя причина."""
        self.scene.write("test_o2.py", '''
            def t():
                return office._summarize_json("data/o2.json", report)
        ''')
        census = self.scene.measure({"o2.json": ("status",)})
        self.assertEqual(census.population, [])
        self.assertEqual([row[1] for row in census.unmeasured],
                         ["doc_unresolved:name_unbound"])

    def test_a_document_built_by_a_call_is_a_FOURTH_outcome_not_unmeasured(self):
        """Документ собрал прогон производителя — у класса тут нет предмета."""
        self.scene.write("test_p.py", '''
            import producer

            def t():
                return office._summarize_json("data/p.json",
                                              producer.run(write=False)["doc"])
        ''')
        census = self.scene.measure({"p.json": ("status",)})
        self.assertEqual(census.population, [])
        self.assertEqual(census.unmeasured, [],
                         "«собран вызовом» — не слабость разбора")
        self.assertEqual([row[1] for row in census.built_by_call],
                         ["call_unresolved"])

    def test_an_unparsed_file_is_reported_as_unmeasured_with_the_reason(self):
        (self.scene.root / "t" / "test_q.py").write_text(
            "def t(:\n    office._summarize_json('data/q.json', {})\n",
            encoding="utf-8")
        census = self.scene.measure({"q.json": ("status",)})
        self.assertEqual(census.files_scanned, 1)
        self.assertEqual(census.population, [])
        self.assertEqual(len(census.unmeasured), 1)
        self.assertTrue(census.unmeasured[0][1].startswith("file_unparsed:"),
                        census.unmeasured)

    def test_the_three_outcomes_have_UNEQUAL_tallies_in_one_scene(self):
        """Равные счёты сделали бы подмену исхода невидимой (урок #786)."""
        self.scene.write("test_r.py", '''
            import producer

            def t(name, report):
                office._summarize_json("data/r.json", {"status": 1})
                office._summarize_json("data/r.json", {"order": 1})
                office._summarize_json("data/r.json", {"x": 1})
                office._summarize_json(name, {"status": 1})
                office._summarize_json("data/stranger.json", {"status": 1})
                office._summarize_json("data/stranger2.json", {"status": 1})
                office._summarize_json("data/r.json", report)
                office._summarize_json("data/r.json", producer.run()["doc"])
        ''')
        census = self.scene.measure({"r.json": ("status", "order")})
        self.assertEqual(len(census.population), 3)
        self.assertEqual(len(census.out_of_subject), 2)
        self.assertEqual(len(census.unmeasured), 2)
        self.assertEqual(len(census.built_by_call), 1)


class TheExemptionIsVisibleAndCounted(_SceneCase):
    """Намеренно куцый документ выходит из класса ПОМЕТКОЙ С ПРИЧИНОЙ."""

    def test_a_marker_with_a_reason_takes_the_site_out_of_the_population(self):
        self.scene.write("test_s.py", '''
            def t():
                # SCHEMA-GAP-OK: предмет сцены — ветка третьего исхода
                doc = {"status": "UNMEASURED"}
                return office._summarize_json("data/s.json", doc)
        ''')
        census = self.scene.measure({"s.json": ("status", "order")})
        self.assertEqual(census.population, [])
        self.assertEqual([s.exempt_reason for s in census.exempt],
                         ["предмет сцены — ветка третьего исхода"])
        self.assertEqual(census.by_key(), {})

    def test_a_marker_WITHOUT_a_reason_is_not_an_exemption(self):
        """Записка не есть объявление: причина — его часть."""
        self.scene.write("test_t.py", '''
            def t():
                # SCHEMA-GAP-OK
                doc = {"status": "UNMEASURED"}
                return office._summarize_json("data/t.json", doc)
        ''')
        census = self.scene.measure({"t.json": ("status", "order")})
        self.assertEqual(len(census.population), 1)
        self.assertEqual([row[0] for row in census.marker_without_reason],
                         ["t/test_t.py"])

    def test_the_marker_in_a_docstring_is_NOT_seen(self):
        """Урок #829: пометка обязана быть `#`-комментарием."""
        self.scene.write("test_u.py", '''
            def t():
                """SCHEMA-GAP-OK: это докстринг, а не объявление."""
                return office._summarize_json("data/u.json", {"status": 1})
        ''')
        census = self.scene.measure({"u.json": ("status", "order")})
        self.assertEqual(len(census.population), 1)
        self.assertEqual(census.exempt, [])

    def test_a_marker_in_a_neighbour_function_does_not_free_this_site(self):
        """Освобождение действует в СВОЕЙ функции, а не во всём файле."""
        self.scene.write("test_v.py", '''
            def neighbour():
                # SCHEMA-GAP-OK: предмет соседней сцены
                return office._summarize_json("data/v.json", {"status": 1})

            def t():
                return office._summarize_json("data/v.json", {"status": 1})
        ''')
        census = self.scene.measure({"v.json": ("status", "order")})
        self.assertEqual(len(census.population), 1)
        self.assertEqual(len(census.exempt), 1)


class TheRuleOfWhatCountsAsPresentArrivesAsInput(_SceneCase):
    """Второй копии правила «ЕСТЬ ли поле» в приборе нет."""

    def test_the_passed_predicate_is_the_one_actually_asked(self):
        self.scene.write("test_w.py", '''
            def t():
                return office._summarize_json("data/w.json", {"status": 1})
        ''')
        schema = {"w.json": ("status", "order", "counts")}
        all_present = self.scene.measure(schema, has_path=lambda d, p: True)
        none_present = self.scene.measure(schema, has_path=lambda d, p: False)
        self.assertEqual(all_present.population, [],
                         "прибор считает наличие сам — правило не входом")
        self.assertEqual(none_present.pairs, 3)

    def test_the_schema_arrives_as_input_too(self):
        """Перечень артефактов не пересчитывается прибором (урок ADR-697)."""
        self.scene.write("test_x.py", '''
            def t():
                return office._summarize_json("data/x.json", {"status": 1})
        ''')
        self.assertEqual(self.scene.measure({}).out_of_subject,
                         [("t/test_x.py", 3, "x.json")])


class TheArtifactNameIsResolvedByValueNotByGuess(_SceneCase):
    """Имя артефакта берётся у НАСТОЯЩЕГО модуля, а не угадывается."""

    def setUp(self) -> None:
        super().setUp()
        (self.scene.root / "c842mod.py").write_text(
            'ARTIFACT = "data/y.json"\n', encoding="utf-8")
        sys.path.insert(0, str(self.scene.root))
        self.addCleanup(lambda: sys.path.remove(str(self.scene.root)))
        sys.modules.pop("c842mod", None)
        self.addCleanup(lambda: sys.modules.pop("c842mod", None))

    def test_a_module_constant_is_resolved_by_importing_that_module(self):
        self.scene.write("test_y.py", '''
            import c842mod

            def t():
                return office._summarize_json(c842mod.ARTIFACT, {"status": 1})
        ''')
        census = self.scene.measure({"y.json": ("status", "order")})
        self.assertEqual([s.artifact for s in census.population], ["y.json"])

    def test_an_f_string_over_a_module_constant_is_resolved(self):
        (self.scene.root / "c842mod.py").write_text(
            'ARTIFACT = "y.json"\n', encoding="utf-8")
        self.scene.write("test_z.py", '''
            import c842mod as M

            def t():
                return office._summarize_json(f"data/{M.ARTIFACT}",
                                              {"status": 1})
        ''')
        census = self.scene.measure({"y.json": ("status", "order")})
        self.assertEqual([s.artifact for s in census.population], ["y.json"])

    def test_a_constant_of_an_UNIMPORTED_name_is_not_guessed(self):
        """Догадка по каталогу уже рождала выдуманную находку (урок #774)."""
        self.scene.write("test_zz.py", '''
            def t():
                return office._summarize_json(stranger.ARTIFACT, {"status": 1})
        ''')
        census = self.scene.measure({"y.json": ("status", "order")})
        self.assertEqual(census.population, [])
        self.assertEqual([row[1] for row in census.unmeasured],
                         ["artifact_name_unresolved"])


class TheContractIsPinnedLiterally(unittest.TestCase):
    """Строки контракта пришпилены (урок #819: дописывающий мутант их не убьёт)."""

    def test_the_door_is_the_office_reader(self):
        self.assertEqual(gap.DOOR, "_summarize_json")

    def test_the_depth_limit_is_declared_and_finite(self):
        self.assertEqual(gap.MAX_DEPTH, 12)

    def test_the_default_test_dirs_are_the_prescribed_three(self):
        self.assertEqual(gap.DEFAULT_TEST_DIRS,
                         ("spa_core/tests", "tests", "scripts/tests"))

    def test_the_reasons_that_mean_built_by_a_call_are_named(self):
        """Пин РАСШИРЕН заказом G699 п. 2 — это усиление, а не ослабление.

        Обоснование (инв. #16 требует его в теле изменения): две причины
        ДОБАВЛЕНЫ, ни одна не убрана и ни одна не переименована. Прежний набор
        целиком входит в новый, поэтому ни один прежний исход не сменил
        корзину. Новые причины отвечают формам, которых до этого хода у меры
        не было вовсе: `receiver_not_self` — отказ одолжить одноимённый метод
        неизвестному получателю, `self_outside_class` — `self.f()` вне класса.
        Пин остаётся РАВЕНСТВОМ, а не вхождением: вырасти набору молча
        по-прежнему нельзя.

        **Пин расширен ВТОРОЙ раз — ADR-835 (цикл #958), и обоснование то же
        по форме, но НЕ по следствию.** Добавлена одна причина
        (`unpacked_from_call`), ни одна не убрана и ни одна не переименована;
        прежний набор целиком входит в новый. Форма, которой у меры не было:
        `doc, root, d = _measured(tmp)` — имя связано РАСПАКОВКОЙ, и до этого
        хода `_assigns_of` не записывал его вовсе, поэтому
        `spa_core/tests/test_slo_data_dir_named.py:271` отвечал `name_unbound`
        и лежал в «НЕ ИЗМЕРЕНО».

        Почему это НЕ послабление, хотя площадка покидает «НЕ ИЗМЕРЕНО».
        Вердикт у неё НЕ меняется — она как не входила в население
        («путей не хватает»), так и не входит. Меняется ВЕДРО, и у двух вёдер
        разная цена: `unmeasured` ограничен потолком `unmeasured_max`,
        поднимать который запрещено, а «документ собрал ВЫЗОВ» — свой исход
        по построению (словаря-фикстуры там нет). Площадка в чужом ведре
        тратила бы запас охвата, которого мера не теряла, то есть прятала бы
        НАСТОЯЩУЮ потерю охвата за своей. Обратная сторона закреплена
        отдельно: правая часть, вызовом НЕ являющаяся, даёт
        `unpacked_unresolved` и остаётся в «НЕ ИЗМЕРЕНО».
        """
        self.assertEqual(sorted(gap._BUILT_BY_CALL),
                         ["call_unresolved", "helper_returns_no_dict",
                          "receiver_not_self", "self_outside_class",
                          "unpacked_from_call"])

    def test_the_depth_limit_is_its_own_outcome_not_an_absence(self):
        """Упёрлись в предел ⇒ причина, а не «полей нет»."""
        flow = gap._ModuleFlow.__new__(gap._ModuleFlow)
        self.assertEqual(flow.skeleton(None, depth=gap.MAX_DEPTH + 1),
                         (None, "depth_limit"))


class TheRatchetRedensOnTheRealIncident(_SceneCase):
    """Положительный контроль: авария #832/#834/#837/#841, воспроизведённая.

    Каждый из четырёх циклов объявлял новый раздел в `_READ_SCHEMA` и не давал
    ему ЗНАЧЕНИЯ в фикстуре соседа. Сверка обязана покраснеть именно на этом
    и НЕ краснеть на починке.
    """

    def _scene(self) -> None:
        self.scene.write("test_neighbour.py", '''
            def _doc():
                return {"counts": {"lists_total": 3, "day_axis": {}}}

            def t():
                return office._summarize_json("data/census.json", _doc())
        ''')

    def test_a_newly_declared_section_without_a_fixture_value_reddens(self):
        self._scene()
        before = self.scene.measure(
            {"census.json": ("counts.lists_total", "counts.day_axis")})
        self.assertEqual(gap.compare(before, {}), [],
                         "фикстура несёт всё объявленное — краснеть нечему")

        after = self.scene.measure(
            {"census.json": ("counts.lists_total", "counts.day_axis",
                             "counts.constant_operand")})
        report = gap.compare(after, {})
        self.assertEqual(len(report), 1, report)
        self.assertIn("counts.constant_operand", report[0])
        self.assertIn("НОВЫЙ t/test_neighbour.py::census.json: 1", report[0])

    def test_a_key_that_GREW_against_the_baseline_is_named_as_grown(self):
        self._scene()
        census = self.scene.measure(
            {"census.json": ("counts.a", "counts.b", "counts.c")})
        report = gap.compare(census, {"t/test_neighbour.py::census.json": 1})
        self.assertEqual(len(report), 1, report)
        self.assertIn("ВЫРОС t/test_neighbour.py::census.json: 1 \u2192 3",
                      report[0])

    def test_a_key_that_SHRANK_is_silent_because_the_base_may_only_fall(self):
        self._scene()
        census = self.scene.measure({"census.json": ("counts.a",)})
        self.assertEqual(
            gap.compare(census, {"t/test_neighbour.py::census.json": 9}), [])

    def test_a_key_that_VANISHED_is_silent_too(self):
        self._scene()
        census = self.scene.measure(
            {"census.json": ("counts.lists_total", "counts.day_axis")})
        self.assertEqual(
            gap.compare(census, {"t/test_neighbour.py::census.json": 4}), [])

    def test_the_cure_by_fixture_value_closes_the_finding(self):
        """Обратная сторона: дали фикстуре значение — сверка молчит."""
        self.scene.write("test_neighbour.py", '''
            def _doc():
                return {"counts": {"lists_total": 3, "day_axis": {},
                                   "constant_operand": {}}}

            def t():
                return office._summarize_json("data/census.json", _doc())
        ''')
        census = self.scene.measure(
            {"census.json": ("counts.lists_total", "counts.day_axis",
                             "counts.constant_operand")})
        self.assertEqual(gap.compare(census, {}), [])


class NamesAreBoundByScopeNotByTheFile(_SceneCase):
    """ADR-699: прежняя редакция связывала имена обходом ВСЕГО файла.

    Вред у формы двусторонний, и каждая сторона здесь — отдельная сцена,
    воспроизводящая НАСТОЯЩУЮ аварию замера #842.
    """

    _SCHEMA = {"z.json": ("status", "counts.total")}

    def test_a_rich_sibling_does_not_take_the_blame_for_a_poor_neighbour(self):
        """ЛОЖНАЯ НАХОДКА: три площадки `_health.json` числились «не несёт 7 из 7»,
        а их настоящая фикстура несёт все семь — документ приехал из ЧУЖОЙ функции.
        """
        self.scene.write("test_z1.py", '''
            def rich():
                doc = {"status": "CLEAN", "counts": {"total": 1}}
                return office._summarize_json("data/z.json", doc)

            def poor():
                doc = {"status": "CLEAN"}
                return doc
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [],
                         "богатая площадка обвинена документом соседней функции")
        self.assertEqual(len(census.sites), 1, census.sites)

    def test_a_poor_site_does_not_borrow_the_keys_of_a_rich_sibling(self):
        """СКРЫТЫЙ ПРОБЕЛ: обратная сторона той же формы — сосед ОДАЛЖИВАЛ ключи,
        и настоящий пробел не находился вовсе (так прятались `note`,
        `closure_drift`, `history.*`, `verdict`).
        """
        self.scene.write("test_z2.py", '''
            def poor():
                doc = {"status": "CLEAN"}
                return office._summarize_json("data/z.json", doc)

            def rich():
                doc = {"status": "CLEAN", "counts": {"total": 1}}
                return doc
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.total",)],
                         "пробел площадки погашен ключами соседней функции")

    def test_a_name_assigned_in_a_class_body_is_not_visible_in_a_method(self):
        """Правило берётся у ЯЗЫКА: голое имя из тела класса в методе — `NameError`.

        Считать его видимым значило бы вернуть то же одалживание под другим
        именем.
        """
        self.scene.write("test_z3.py", '''
            class S:
                doc = {"status": "CLEAN", "counts": {"total": 1}}

                def t(self):
                    return office._summarize_json("data/z.json", doc)
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [])
        self.assertEqual([row[1] for row in census.unmeasured],
                         ["doc_unresolved:name_unbound"])

    def test_a_local_assignment_shadows_the_module_level_name(self):
        """Своя область ПЕРЕКРЫВАЕТ модульную — как в языке, а не складывается."""
        self.scene.write("test_z4.py", '''
            doc = {"status": "CLEAN", "counts": {"total": 1}}

            def t():
                doc = {"status": "CLEAN"}
                return office._summarize_json("data/z.json", doc)
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.total",)],
                         "локальное имя не перекрыло модульное")

    def test_the_module_level_name_is_still_visible_when_not_shadowed(self):
        """Обратный контроль: область не ОТРЕЗАЕТ лишнего."""
        self.scene.write("test_z5.py", '''
            DOC = {"status": "CLEAN", "counts": {"total": 1}}

            def t():
                return office._summarize_json("data/z.json", DOC)
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [], census.sites)
        self.assertEqual(len(census.sites), 1)

    def test_a_helper_return_is_resolved_in_the_scope_of_the_HELPER(self):
        """Та же граница с другой стороны: `return doc` принадлежит помощнику.

        Форма взята с живого места — `_health_with_house_view` строит документ
        в своём локальном `doc`, которого у сцены нет вовсе.
        """
        self.scene.write("test_z6.py", '''
            REAL = {"status": "CLEAN", "counts": {"total": 1}}

            def _build():
                doc = dict(REAL)
                return doc

            def t():
                doc = {"status": "CLEAN"}
                return office._summarize_json("data/z.json", _build())
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [],
                         "документ помощника подменён локальным именем сцены")


class BranchesAreUnitedDEEPLY(_SceneCase):
    """ADR-699: плоский `dict.update` СТИРАЛ раздел соседней ветки.

    Вопрос меры — «несёт ли путь ХОТЬ ОДНА ветка», и ответ не вправе зависеть
    от порядка ветвей. Обе сцены ниже отличаются ТОЛЬКО порядком.
    """

    _SCHEMA = {"m.json": ("counts.total", "counts.day_axis")}

    def test_a_poor_branch_does_not_erase_a_rich_branch(self):
        self.scene.write("test_m1.py", '''
            def t(flag):
                doc = {"counts": {"total": 1, "day_axis": {}}}
                doc = {"counts": {}}
                return office._summarize_json("data/m.json", doc)
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [],
                         "ветка с пустым разделом стёрла богатую")

    def test_the_answer_does_not_depend_on_the_order_of_branches(self):
        self.scene.write("test_m2.py", '''
            def t(flag):
                doc = {"counts": {}}
                doc = {"counts": {"total": 1, "day_axis": {}}}
                return office._summarize_json("data/m.json", doc)
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [])

    def test_a_path_no_branch_carries_is_still_found(self):
        """Обратная сторона: глубокое слияние не ослепляет меру."""
        self.scene.write("test_m3.py", '''
            def t(flag):
                doc = {"counts": {}}
                doc = {"counts": {"total": 1}}
                return office._summarize_json("data/m.json", doc)
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.day_axis",)])


class TheValueOfAParameterIsAskedOfTheCaller(_SceneCase):
    """Заказ G698 п. 2: документ приходит ПАРАМЕТРОМ, и решает вызывающий."""

    _SCHEMA = {"k.json": ("status", "counts.total")}

    def test_the_argument_at_the_call_site_resolves_the_parameter(self):
        self.scene.write("test_k1.py", '''
            def _render(doc):
                return office._summarize_json("data/k.json", doc)

            def t():
                return _render({"status": "CLEAN"})
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.total",)])

    def test_self_does_not_shift_the_argument_of_a_method(self):
        """Смещение читается из ФОРМЫ вызова, а не угадывается."""
        self.scene.write("test_k2.py", '''
            class S:
                def _render(self, doc):
                    return office._summarize_json("data/k.json", doc)

                def t(self):
                    return self._render({"status": "CLEAN"})
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.total",)])

    def test_several_callers_are_united_so_one_carrying_branch_is_enough(self):
        self.scene.write("test_k3.py", '''
            def _render(doc):
                return office._summarize_json("data/k.json", doc)

            def t1():
                return _render({"status": "CLEAN"})

            def t2():
                return _render({"status": "CLEAN", "counts": {"total": 1}})
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [], census.sites)

    def test_the_argument_is_resolved_in_the_scope_of_the_CALLER(self):
        """Аргумент написан у вызывающего — связывать его именами помощника
        значило бы повторить одалживание, против которого введена область."""
        self.scene.write("test_k4.py", '''
            def _render(doc):
                payload = {"status": "CLEAN"}
                return office._summarize_json("data/k.json", doc)

            def t():
                payload = {"status": "CLEAN", "counts": {"total": 1}}
                return _render(payload)
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [],
                         "аргумент связан именем ПОМОЩНИКА, а не вызывающего")

    def test_a_keyword_argument_binds_the_parameter_by_name(self):
        self.scene.write("test_k5.py", '''
            def _render(doc):
                return office._summarize_json("data/k.json", doc)

            def t():
                return _render(doc={"status": "CLEAN"})
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.total",)])

    def test_a_starred_argument_is_not_guessed(self):
        """`_render(*args)` параметра не связывает — и это НЕ «полей нет»."""
        self.scene.write("test_k6.py", '''
            def _render(doc):
                return office._summarize_json("data/k.json", doc)

            def t(args):
                return _render(*args)
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [])
        self.assertEqual([row[1] for row in census.unmeasured],
                         ["doc_unresolved:param_not_bound_at_call"])

    def test_passing_the_parameter_onward_is_not_called_a_cycle(self):
        """Петля ищется по ПАРЕ «область × имя»: у локального имени вызывающего
        то же написание, что у параметра помощника, и проверка по одному имени
        объявляла бы петлёй обычную передачу аргумента."""
        self.scene.write("test_k7.py", '''
            def _render(doc):
                return office._summarize_json("data/k.json", doc)

            def t():
                doc = {"status": "CLEAN"}
                return _render(doc)
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.total",)])
        self.assertEqual(census.unmeasured, [])


class TheStdlibCopyIdiomIsTheSameFixture(_SceneCase):
    """`json.loads(json.dumps(X))` — тот же идиом глубокой копии, что `deepcopy`,
    только написанный stdlib-ом (инв. #4). Не узнав его, мера теряла площадку."""

    _SCHEMA = {"j.json": ("status", "counts.total")}

    def test_a_json_round_trip_resolves_to_the_copied_fixture(self):
        self.scene.write("test_j1.py", '''
            import json

            REAL = {"status": "CLEAN", "counts": {"total": 1}}

            def t():
                doc = json.loads(json.dumps(REAL))
                return office._summarize_json("data/j.json", doc)
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [], census.sites)

    def test_a_round_trip_of_a_POOR_fixture_is_still_found(self):
        """Обратная сторона: идиом не ослепляет меру."""
        self.scene.write("test_j2.py", '''
            import json

            REAL = {"status": "CLEAN"}

            def t():
                doc = json.loads(json.dumps(REAL))
                return office._summarize_json("data/j.json", doc)
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.total",)])

    def test_a_foreign_loads_is_not_mistaken_for_the_idiom(self):
        """`json.loads(<строка>)` копией фикстуры НЕ является.

        Исход тут ЧЕТВЁРТЫЙ, а не «НЕ ИЗМЕРЕНО»: документ собрал ВЫЗОВ, и
        фикстуры, которой можно объявить поле, в этом месте нет вовсе.
        """
        self.scene.write("test_j3.py", '''
            import json

            def t(raw):
                doc = json.loads(raw)
                return office._summarize_json("data/j.json", doc)
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [])
        self.assertEqual(census.unmeasured, [])
        self.assertEqual([row[1] for row in census.built_by_call],
                         ["call_unresolved"])


class DefinitionsAreResolvedByOwnerNotByName(_SceneCase):
    """Заказ G699 п. 2: ВТОРОЕ объединение того же рода — по ИМЕНИ функции.

    ADR-699 развёл присваивания по ОБЛАСТИ, но определения остались в плоском
    наборе `funcs[имя]`, а вызовы — в плоском `calls[имя]`. Одноимённые методы
    разных классов одалживали друг другу возвраты и места зова ровно так же,
    как это делали присваивания до #843.

    Каждая сцена здесь — контроль в ОБЕ стороны: куцая площадка не оправдана
    богатой однофамилицей И богатая не обвинена за куцую; наследование при
    этом не потеряно, а неизвестный получатель НАЗВАН, а не одолжен.
    """

    _SCHEMA = {"z.json": ("status", "counts.total")}

    # --- дверь первая: разрешение ЗОВОМОГО (`funcs`) ----------------------

    def test_a_poor_method_is_not_exonerated_by_a_rich_namesake(self):
        """Настоящая форма вреда: `_doc` определён в файле ТРИЖДЫ.

        Замер #844 на `test_list_day_axis.py`: каждый из 16 зовов `self._doc()`
        и `self._rows()` получал по 2–3 определения вместо одного. Там вердикт
        не сменился лишь потому, что две одолживавшие однофамилицы сами
        разрешались в НОЛЬ ключей, — то есть класс латентный, а не пустой.
        """
        self.scene.write("test_z20.py", '''
            class Poor:
                def _doc(self):
                    return {"status": "CLEAN"}

                def t(self):
                    return office._summarize_json("data/z.json", self._doc())

            class Rich:
                def _doc(self):
                    return {"status": "CLEAN", "counts": {"total": 1}}
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.total",)],
                         "пробел площадки погашен возвратом ОДНОИМЁННОГО "
                         "метода чужого класса")

    def test_a_rich_method_is_not_blamed_for_a_poor_namesake(self):
        """Обратная сторона: исправление не смещает вину на соседа."""
        self.scene.write("test_z21.py", '''
            class Rich:
                def _doc(self):
                    return {"status": "CLEAN", "counts": {"total": 1}}

                def t(self):
                    return office._summarize_json("data/z.json", self._doc())

            class Poor:
                def _doc(self):
                    return {"status": "CLEAN"}
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [], census.sites)
        self.assertEqual(len(census.sites), 1, census.sites)

    def test_a_method_inherited_from_an_in_file_base_is_still_resolved(self):
        """Охват не куплен слепотой: база, объявленная В ФАЙЛЕ, разрешается.

        Строгое «только свой класс» потеряло бы сцену-потомка, и это была бы
        та же потеря зрения, которой ADR-699 избежал.
        """
        self.scene.write("test_z22.py", '''
            class Base:
                def _doc(self):
                    return {"status": "CLEAN"}

            class Child(Base):
                def t(self):
                    return office._summarize_json("data/z.json", self._doc())
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.total",)],
                         "метод базы того же файла не найден — площадка "
                         "выпала из населения вместо того, чтобы мериться")

    def test_a_base_outside_the_file_is_the_FOURTH_outcome_not_a_gap(self):
        """База вне файла (`unittest.TestCase`) честно не находится."""
        self.scene.write("test_z23.py", '''
            import unittest

            class S(unittest.TestCase):
                def t(self):
                    return office._summarize_json("data/z.json", self._doc())
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [])
        self.assertEqual(census.unmeasured, [])
        self.assertEqual([row[1] for row in census.built_by_call],
                         ["call_unresolved"])

    def test_a_bare_name_does_not_see_a_method_of_the_same_name(self):
        """Правило берётся у ЯЗЫКА: метод голым именем не виден (`NameError`)."""
        self.scene.write("test_z24.py", '''
            class S:
                def _doc(self):
                    return {"status": "CLEAN", "counts": {"total": 1}}

            def t():
                return office._summarize_json("data/z.json", _doc())
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [])
        self.assertEqual([row[1] for row in census.built_by_call],
                         ["call_unresolved"],
                         "голое имя одолжило себе МЕТОД чужого класса")

    def test_a_free_function_is_still_seen_by_a_bare_name(self):
        """Обратная сторона: свободная функция голым именем видна."""
        self.scene.write("test_z25.py", '''
            def _doc():
                return {"status": "CLEAN"}

            def t():
                return office._summarize_json("data/z.json", _doc())
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.total",)])

    def test_an_unknown_receiver_is_NAMED_not_lent_a_namesake(self):
        """`other.f()` — тип получателя статике не дан.

        Одолжить ему любой одноимённый метод файла значило бы вернуть вред
        под другим именем. Исход назван ДОСЛОВНО, чтобы цена считалась.
        """
        self.scene.write("test_z26.py", '''
            class Rich:
                def _doc(self):
                    return {"status": "CLEAN", "counts": {"total": 1}}

            def t(other):
                return office._summarize_json("data/z.json", other._doc())
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(census.population, [])
        self.assertEqual(census.unmeasured, [])
        self.assertEqual([row[1] for row in census.built_by_call],
                         ["receiver_not_self"])

    # --- дверь вторая: разрешение ВЫЗЫВАЮЩЕГО (`calls`) -------------------

    def test_a_parameter_is_resolved_from_the_callers_of_ITS_OWN_definition(self):
        """То же объединение у ВТОРОЙ двери — её заказ G699 п. 2 не называл.

        `_from_callers` спрашивал `calls[имя помощника]`, поэтому у помощника,
        определённого в файле дважды, параметр разрешался аргументами вызовов
        ОБОИХ. Поверхность формы в наборе — `setUp×7`, `tearDown×6`, `_doc×3`.
        """
        self.scene.write("test_z27.py", '''
            class Poor:
                def _render(self, doc):
                    return office._summarize_json("data/z.json", doc)

                def t(self):
                    return self._render({"status": "CLEAN"})

            class Rich:
                def _render(self, doc):
                    return office._summarize_json("data/z.json", doc)

                def t(self):
                    return self._render({"status": "CLEAN",
                                         "counts": {"total": 1}})
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual(sorted(s.missing for s in census.population),
                         [("counts.total",)],
                         "параметр куцего помощника разрешён аргументами "
                         "вызовов ОДНОИМЁННОГО помощника чужого класса")
        self.assertEqual(len(census.sites), 2, census.sites)

    def test_a_parameter_still_resolves_when_the_helper_is_unique(self):
        """Обратная сторона: заслуга G698 п. 2 не отменена исправлением."""
        self.scene.write("test_z28.py", '''
            class S:
                def _render(self, doc):
                    return office._summarize_json("data/z.json", doc)

                def t(self):
                    return self._render({"status": "CLEAN"})
        ''')
        census = self.scene.measure(self._SCHEMA)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.total",)],
                         "параметр единственного помощника перестал "
                         "разрешаться у вызывающего")

    def test_the_reasons_of_the_two_new_outcomes_are_pinned_VERBATIM(self):
        """Причины — строки контракта: их читает шаг 0-офис и этот набор.

        Пришпилены дословно, потому что `_BUILT_BY_CALL` сверяется ПО СТРОКЕ,
        и переименование молча перевело бы исход в «НЕ ИЗМЕРЕНО».
        """
        self.assertIn("receiver_not_self", gap._BUILT_BY_CALL)
        self.assertIn("self_outside_class", gap._BUILT_BY_CALL)
        self.assertIn("call_unresolved", gap._BUILT_BY_CALL)
        self.assertIn("helper_returns_no_dict", gap._BUILT_BY_CALL)


class ANestedContainerBuiltByACallIsNotAnAbsentPath(_SceneCase):
    """Заказ G699 п. 1 / ADR-701: ЧЕТВЁРТАЯ форма объединения — вложенность.

    ADR-699 связал имена ОБЛАСТЬЮ, ADR-700 развёл определения и вызовы по
    ВЛАДЕЛЬЦУ. Осталась дверь, которой не было названо ни одной: документ
    разрешён до словаря, а его ВЛОЖЕННЫЙ контейнер собран вызовом. Разбор
    ставит там `LEAF`, и `has_path(doc, "counts.x")` отвечает `False` — не
    потому, что фикстура ключа не несёт, а потому что заглянуть внутрь не
    удалось. Замер #845: 34 пары из 199 (ключ
    `test_list_candidate_readers.py::list_identity_census.json`, 17 путей на
    двух площадках) были обвинены ЛОЖНО — и именно там фикстура несёт пути
    НАСТОЯЩИМ помощником производителя (`census.tally(ROWS)`), то есть
    обвинение падало на самую честную форму фикстуры из возможных.
    """

    SCHEMA = {"q.json": ("status", "counts.lists_total", "counts.day_axis")}

    BY_CALL = '''
        import producer

        def t():
            counts = producer.tally(ROWS)
            return office._summarize_json("data/q.json", {
                "status": "FINDING", "counts": counts})
    '''

    def test_an_unresolved_nested_container_is_a_named_third_outcome(self):
        self.scene.write("test_q.py", self.BY_CALL)
        census = self.scene.measure(self.SCHEMA)
        # НЕ население: путей, которых фикстура не несёт, здесь не измерено.
        self.assertEqual(census.population, [])
        # И НЕ «НЕ ИЗМЕРЕНО» двери: документ-то разрешён, площадка есть.
        self.assertEqual(census.unmeasured, [])
        paths = sorted(row[2] for row in census.nested_unresolved)
        self.assertEqual(paths, ["counts.day_axis", "counts.lists_total"])

    def test_the_outcome_names_the_container_where_resolution_stopped(self):
        """Причина обязана быть действенной: назван РОДИТЕЛЬ, а не просто путь."""
        self.scene.write("test_q.py", self.BY_CALL)
        census = self.scene.measure(self.SCHEMA)
        # Утверждение о НАСЕЛЕНИИ стои́т первым нарочно: оно выразимо в ОБЕИХ
        # редакциях прибора, поэтому на прежнем операнде этот контроль краснеет
        # ПОВЕДЕНЧЕСКИ, а не падает об отсутствующее поле исхода.
        self.assertEqual(census.population, [])
        self.assertEqual({row[3] for row in census.nested_unresolved},
                         {"counts"})
        self.assertEqual({row[1] for row in census.nested_unresolved},
                         {"q.json"})

    def test_a_nested_literal_that_really_lacks_the_key_is_STILL_population(self):
        """ОБРАТНЫЙ КОНТРОЛЬ: раскрытый контейнер судится как прежде.

        Без этой проверки новый исход был бы лазейкой: «вложено ⇒ не мой
        предмет» сняло бы класс целиком, а он измерен и живой.
        """
        self.scene.write("test_q.py", '''
            def t():
                return office._summarize_json("data/q.json", {
                    "status": "FINDING", "counts": {"lists_total": 3}})
        ''')
        census = self.scene.measure(self.SCHEMA)
        self.assertEqual(census.nested_unresolved, [])
        self.assertEqual([s.missing for s in census.population],
                         [("counts.day_axis",)])

    def test_an_absent_top_level_container_is_population_not_unresolved(self):
        """«Контейнера нет вовсе» и «контейнер не раскрыт» — разные ответы."""
        self.scene.write("test_q.py", '''
            def t():
                return office._summarize_json("data/q.json", {"status": "OK"})
        ''')
        census = self.scene.measure(self.SCHEMA)
        self.assertEqual(census.nested_unresolved, [])
        self.assertEqual([s.missing for s in census.population],
                         [("counts.lists_total", "counts.day_axis")])

    def test_a_resolved_nested_container_loses_no_coverage(self):
        """Исправление не куплено слепотой: несомый путь по-прежнему несом."""
        self.scene.write("test_q.py", '''
            def t():
                return office._summarize_json("data/q.json", {
                    "status": "OK",
                    "counts": {"lists_total": 3, "day_axis": {"status": "OK"}}})
        ''')
        census = self.scene.measure(self.SCHEMA)
        self.assertEqual(census.population, [])
        self.assertEqual(census.nested_unresolved, [])
        self.assertEqual(census.unmeasured, [])
        self.assertEqual(len(census.sites), 1)

    def test_the_container_is_asked_of_the_OFFICE_rule_not_re_implemented(self):
        """Правило «ЕСТЬ ли поле» остаётся ОДНО — чужое, приведённое входом.

        Новый исход лишь классифицирует УЖЕ полученный отрицательный ответ.
        Контроль: подменяем правило на «всё есть» — и тогда отрицательных
        ответов нет вовсе, значит и третьего исхода быть не может.
        """
        self.scene.write("test_q.py", self.BY_CALL)
        census = self.scene.measure(self.SCHEMA,
                                    has_path=lambda doc, path: True)
        self.assertEqual(census.nested_unresolved, [])
        self.assertEqual(census.population, [])


class TheMutationAfterTheCopyIsTheDocumentAtTheDoor(_SceneCase):
    """Заказ G699 п. 3: `del d[k]` после копии отдаёт двери ДРУГОЙ документ.

    Копия фикстуры есть та же фикстура (ADR-698) — и это верно про
    ПРОИСХОЖДЕНИЕ. Но вопрос меры не «откуда документ», а «несёт ли он
    объявленный путь У ДВЕРИ», и отвечает на него документ ПОСЛЕ мутаций.
    Класс измерен подстановкой в сам прибор (`model_mutation=`), и каждая
    сцена ниже рвёт ОДНО звено.
    """

    def test_a_removal_above_the_door_is_seen(self):
        self.scene.write("test_m1.py", '''
            BASE = {"counts": {"a": 1, "b": 2}}

            def t():
                doc = dict(BASE)
                del doc["counts"]
                return office._summarize_json("data/m1.json", doc)
        ''')
        census = self.scene.measure({"m1.json": ("counts.a",)})
        self.assertEqual([s.missing for s in census.population],
                         [("counts.a",)])
        self.assertEqual(len(census.mutated), 1, "форма обязана СЧИТАТЬСЯ")

    def test_a_removal_BELOW_the_door_does_not_touch_it(self):
        """Порядок — часть вопроса: ниже вызова мутация документа не меняет."""
        self.scene.write("test_m2.py", '''
            BASE = {"counts": {"a": 1}}

            def t():
                doc = dict(BASE)
                out = office._summarize_json("data/m2.json", doc)
                del doc["counts"]
                return out
        ''')
        census = self.scene.measure({"m2.json": ("counts.a",)})
        self.assertEqual(census.population, [])
        self.assertEqual(census.mutated, [], "мутация ниже двери НЕ применена")

    def test_a_nested_pop_is_followed_to_its_depth(self):
        self.scene.write("test_m3.py", '''
            BASE = {"counts": {"a": 1, "b": 2}}

            def t():
                doc = dict(BASE)
                doc["counts"].pop("b")
                return office._summarize_json("data/m3.json", doc)
        ''')
        census = self.scene.measure({"m3.json": ("counts.a", "counts.b")})
        self.assertEqual([s.missing for s in census.population],
                         [("counts.b",)], "снят ровно ОДИН путь, не раздел")

    def test_an_ADDED_key_is_not_an_accusation(self):
        """Вторая сторона той же формы — промах в сторону НАХОДКИ.

        Прибор видел только базу, поэтому раздел, дописанный площадкой
        присваиванием по ключу, числился ненесомым, то есть обвинение было
        ЛОЖНЫМ. На живом дереве такое одно (`test_outcomes_completeness.py`),
        и освобождение там оказалось выдано ровно под эту ошибку.
        """
        self.scene.write("test_m4.py", '''
            BASE = {"status": "CLEAN"}

            def t():
                doc = dict(BASE)
                doc["counts"] = {"a": 1}
                return office._summarize_json("data/m4.json", doc)
        ''')
        census = self.scene.measure({"m4.json": ("status", "counts.a")})
        self.assertEqual(census.population, [])

    def test_a_resolvable_update_carries_what_it_adds(self):
        self.scene.write("test_m5.py", '''
            BASE = {"status": "CLEAN"}
            MORE = {"counts": {"a": 1}}

            def t():
                doc = dict(BASE)
                doc.update(MORE)
                return office._summarize_json("data/m5.json", doc)
        ''')
        census = self.scene.measure({"m5.json": ("status", "counts.a")})
        self.assertEqual(census.population, [])

    def test_a_setdefault_adds_the_key_it_names(self):
        self.scene.write("test_m6.py", '''
            BASE = {"status": "CLEAN"}

            def t():
                doc = dict(BASE)
                doc.setdefault("counts", {"a": 1})
                return office._summarize_json("data/m6.json", doc)
        ''')
        census = self.scene.measure({"m6.json": ("counts.a",)})
        self.assertEqual(census.population, [])

    def test_a_module_level_mutation_applies_even_if_written_BELOW(self):
        """Уровень модуля исполняется на ИМПОРТЕ — раньше любой сцены, и номер
        строки тут ничего не решает."""
        self.scene.write("test_m7.py", '''
            BASE = {"counts": {"a": 1}}

            def t():
                return office._summarize_json("data/m7.json", BASE)

            del BASE["counts"]
        ''')
        census = self.scene.measure({"m7.json": ("counts.a",)})
        self.assertEqual([s.missing for s in census.population],
                         [("counts.a",)])

    def test_a_mutation_in_the_HELPER_body_counts_before_its_return(self):
        """Порядок считается до ТОЧКИ ВЫХОДА значения, а не до строки двери.

        Привязка к строке площадки объявила бы «чужой областью» 19 площадок
        живого дерева, у которых мутация стои́т в том же теле, что и
        присваивание, — первая редакция этого замера так и ошиблась.
        """
        self.scene.write("test_m8.py", '''
            BASE = {"counts": {"a": 1}}

            def _doc():
                doc = dict(BASE)
                del doc["counts"]
                return doc

            def t():
                return office._summarize_json("data/m8.json", _doc())
        ''')
        census = self.scene.measure({"m8.json": ("counts.a",)})
        self.assertEqual([s.missing for s in census.population],
                         [("counts.a",)])

    def test_a_removal_after_the_FIRST_return_leaves_that_branch_carrying(self):
        """Объединение ветвей — правило ВСЕЙ меры, и мутация его не отменяет."""
        self.scene.write("test_m9.py", '''
            BASE = {"counts": {"a": 1}}

            def _doc(flag):
                doc = dict(BASE)
                if flag:
                    return doc
                del doc["counts"]
                return doc

            def t():
                return office._summarize_json("data/m9.json", _doc(True))
        ''')
        census = self.scene.measure({"m9.json": ("counts.a",)})
        self.assertEqual(census.population, [])

    def test_the_mutation_of_one_site_does_not_leak_into_its_neighbour(self):
        """Копия своя: правка скелета на месте задела бы соседнюю площадку."""
        self.scene.write("test_m10.py", '''
            BASE = {"counts": {"a": 1}}

            def t_poor():
                doc = dict(BASE)
                del doc["counts"]
                return office._summarize_json("data/m10.json", doc)

            def t_rich():
                return office._summarize_json("data/m10.json", dict(BASE))
        ''')
        census = self.scene.measure({"m10.json": ("counts.a",)})
        self.assertEqual(len(census.sites), 2)
        self.assertEqual(sorted(s.missing for s in census.sites),
                         [(), ("counts.a",)])

    def test_a_module_level_mutation_does_not_reach_a_SHADOWING_local(self):
        """Имя, связанное в теле, затеняет модульное — и его мутацию тоже.

        То же правило, по которому `scope_to` затеняет присваивания: иначе
        мера применила бы к документу площадки ЧУЖУЮ правку, а это ровно
        одалживание, против которого ADR-699 и вводил области.
        """
        self.scene.write("test_m11.py", '''
            BASE = {"counts": {"a": 1}}
            del BASE["counts"]

            def t():
                BASE = {"counts": {"a": 1}}
                return office._summarize_json("data/m11.json", BASE)
        ''')
        census = self.scene.measure({"m11.json": ("counts.a",)})
        self.assertEqual(census.population, [])
        self.assertEqual(census.mutated, [], "чужая мутация НЕ применена")


class TheUnmodellableMutationIsItsOwnOutcome(_SceneCase):
    """Чего статике не дано — третий исход, а не «чисто» и не население.

    Инвариант #17 дословно: измерено · измерено и равно нулю · НЕ ИЗМЕРЕНО
    обязаны быть различимы. Мутация, которой статике не дано, делает документ
    у двери неизвестным, и вердикта о нём не существует.
    """

    def _only_outcome(self, census) -> str:
        self.assertEqual(census.sites, [], "площадка не вправе быть замерена")
        self.assertEqual(len(census.mutation_unmodelled), 1)
        return census.mutation_unmodelled[0][2][0]

    def test_a_mutation_under_a_BRANCH_is_not_applied_and_not_ignored(self):
        self.scene.write("test_u1.py", '''
            BASE = {"counts": {"a": 1}}

            def t(flag):
                doc = dict(BASE)
                if flag:
                    del doc["counts"]
                return office._summarize_json("data/u1.json", doc)
        ''')
        census = self.scene.measure({"u1.json": ("counts.a",)})
        self.assertIn("conditional", self._only_outcome(census))

    def test_a_removal_by_a_NON_LITERAL_key_is_not_guessed(self):
        self.scene.write("test_u2.py", '''
            BASE = {"counts": {"a": 1}}

            def t(which):
                doc = dict(BASE)
                del doc[which]
                return office._summarize_json("data/u2.json", doc)
        ''')
        census = self.scene.measure({"u2.json": ("counts.a",)})
        self.assertIn("key_not_literal", self._only_outcome(census))

    def test_clearing_the_whole_document_is_its_own_reason(self):
        self.scene.write("test_u3.py", '''
            BASE = {"counts": {"a": 1}}

            def t():
                doc = dict(BASE)
                doc.clear()
                return office._summarize_json("data/u3.json", doc)
        ''')
        census = self.scene.measure({"u3.json": ("counts.a",)})
        self.assertIn("whole_doc", self._only_outcome(census))

    def test_an_update_whose_VALUE_is_unresolved_is_unmeasured(self):
        """Самый населённый исход живого дерева: 14 площадок из 18.

        `doc.update(over)` с `over` из `**kwargs` может и дописать раздел, и
        ЗАТЕРЕТЬ вложенный контейнер листом — обе стороны статике не даны.
        """
        self.scene.write("test_u4.py", '''
            BASE = {"counts": {"a": 1}}

            def _doc(**over):
                doc = dict(BASE)
                doc.update(over)
                return doc

            def t():
                return office._summarize_json("data/u4.json", _doc(x=1))
        ''')
        census = self.scene.measure({"u4.json": ("counts.a",)})
        self.assertIn("value_unresolved", self._only_outcome(census))

    def test_a_removal_under_an_UNRESOLVED_parent_is_unmeasured(self):
        self.scene.write("test_u5.py", '''
            import json

            def t(raw):
                doc = {"counts": json.loads(raw)}
                doc["counts"].pop("a")
                return office._summarize_json("data/u5.json", doc)
        ''')
        census = self.scene.measure({"u5.json": ("counts.a",)})
        self.assertIn("parent_not_resolved", self._only_outcome(census))

    def test_the_outcomes_of_the_door_have_UNEQUAL_tallies(self):
        """Равные счёты сделали бы подмену ИМЕНИ исхода невидимой (урок #786)."""
        self.scene.write("test_u6.py", '''
            BASE = {"counts": {"a": 1}}

            def t_seen():
                doc = dict(BASE)
                del doc["counts"]
                return office._summarize_json("data/u6.json", doc)

            def t_blind(which):
                doc = dict(BASE)
                del doc[which]
                return office._summarize_json("data/u6.json", doc)

            def t_blind2(flag):
                doc = dict(BASE)
                if flag:
                    doc.clear()
                return office._summarize_json("data/u6.json", doc)

            def t_clean():
                return office._summarize_json("data/u6.json", dict(BASE))
        ''')
        census = self.scene.measure({"u6.json": ("counts.a",)})
        self.assertEqual(len(census.population), 1)
        self.assertEqual(len(census.mutated), 1)
        self.assertEqual(len(census.mutation_unmodelled), 2)
        self.assertEqual(len(census.sites), 2)


class TheMutationModelArrivesAsAnInput(_SceneCase):
    """Цена измерена ПОДСТАНОВКОЙ в дверь, а не второй копией разбора.

    Положительный контроль самого МЕТОДА: на одной и той же сцене прибор
    обязан дать ДВА разных ответа — иначе «разница ответов есть население»
    было бы заявлением, а не замером (тот же приём, что `drop_shadowed=` у
    ADR-702 и `rounds=` у ADR-703).
    """

    SCENE = '''
        BASE = {"counts": {"a": 1}}

        def t():
            doc = dict(BASE)
            del doc["counts"]
            return office._summarize_json("data/in.json", doc)
    '''

    def setUp(self) -> None:
        super().setUp()
        self.scene.write("test_in.py", self.SCENE)
        self.schema = {"in.json": ("counts.a",)}

    def _run(self, **kw):
        return gap.measure(schema=self.schema, has_path=_has_path,
                           root=str(self.scene.root), test_dirs=("t",), **kw)

    def test_the_door_closed_reproduces_the_OLD_answer(self):
        census = self._run(model_mutation=False)
        self.assertEqual(census.population, [])
        self.assertEqual(census.mutated, [])

    def test_the_door_open_is_the_NEW_answer(self):
        census = self._run(model_mutation=True)
        self.assertEqual([s.missing for s in census.population],
                         [("counts.a",)])

    def test_the_default_is_the_HONEST_one(self):
        """Умолчание — модель ВКЛЮЧЕНА: иначе прибор отвечал бы о документе,
        которого у двери нет (решение ADR-705)."""
        self.assertEqual([s.missing for s in self._run().population],
                         [("counts.a",)])


class ANameBoundByUnpackingHasItsOwnBucket(_SceneCase):
    """ADR-835 (цикл #958): распаковка кортежа — не «разбор не справился».

    Площадка `spa_core/tests/test_slo_data_dir_named.py:271` отвечала
    `name_unbound` и лежала в «НЕ ИЗМЕРЕНО» только потому, что `_assigns_of`
    записывал одни цели-`Name`. Вердикт о населении от этого не менялся —
    менялось ВЕДРО, а у вёдер разная цена: «НЕ ИЗМЕРЕНО» ограничено потолком,
    который поднимать запрещено.

    Каждая проверка ниже судит через НАСТОЯЩУЮ точку входа (`gap.measure`), а
    не через внутреннюю функцию: урок #144.
    """

    SCHEMA = {"y.json": ("status", "order")}

    def test_a_document_unpacked_from_a_call_is_BUILT_BY_A_CALL(self):
        self.scene.write("test_unpack_call.py", '''
            def t():
                doc, root, extra = _measured(tmp)
                return office._summarize_json("y.json", doc)
        ''')
        census = self.scene.measure(self.SCHEMA)
        self.assertEqual(census.population, [])
        self.assertEqual(census.unmeasured, [],
                         "распаковка из вызова снова числится «не измерено»")
        self.assertEqual([why for _where, why in census.built_by_call],
                         ["unpacked_from_call"])

    def test_a_document_unpacked_from_something_ELSE_stays_UNMEASURED(self):
        """Обратная сторона: ведро решает ПРАВАЯ ЧАСТЬ, а не сама распаковка.

        Без этого плеча поправка была бы лазейкой наружу: распакуй что угодно
        — и объявленный путь перестанет стеречь кто-либо.
        """
        self.scene.write("test_unpack_other.py", '''
            def t():
                doc, rest = PAIR
                return office._summarize_json("y.json", doc)
        ''')
        census = self.scene.measure(self.SCHEMA)
        self.assertEqual(census.population, [])
        self.assertEqual(census.built_by_call, [])
        self.assertEqual([why for _where, why in census.unmeasured],
                         ["doc_unresolved:unpacked_unresolved"])

    def test_two_literals_unpacked_side_by_side_are_resolved_ELEMENTWISE(self):
        """Усиление, а не послабление: такую фикстуру прибор раньше НЕ ВИДЕЛ.

        Найденная нехватка пути — настоящая: `order` не несёт первый элемент,
        и именно он доезжает до двери.
        """
        self.scene.write("test_unpack_pair.py", '''
            def t():
                doc, other = {"status": 1}, {"order": 2}
                return office._summarize_json("y.json", doc)
        ''')
        census = self.scene.measure(self.SCHEMA)
        self.assertEqual(census.unmeasured, [])
        self.assertEqual([s.missing for s in census.population], [("order",)])

    def test_a_starred_target_is_not_guessed(self):
        """`a, *rest = …` связывает `rest` СПИСКОМ, а не элементом.

        Выдать список за документ значило бы угадать; имя остаётся несвязанным
        и площадка — честно НЕ ИЗМЕРЕННОЙ.
        """
        self.scene.write("test_unpack_star.py", '''
            def t():
                head, *doc = _measured(tmp)
                return office._summarize_json("y.json", doc)
        ''')
        census = self.scene.measure(self.SCHEMA)
        self.assertEqual(census.population, [])
        self.assertEqual(census.built_by_call, [])
        self.assertEqual([why for _where, why in census.unmeasured],
                         ["doc_unresolved:name_unbound"])
