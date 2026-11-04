"""Храповик ОБЪЯВЛЕНИЯ класса «литерал соседа на ЖИВОМ корне» (ADR-919, G907 п. 2).

Класс мерит ТОЛЬКО дифференциальный прогон
``spa_core.tests._literal_neighbour_door --differential`` (две стороны по
несколько минут каждая, плюс канарейка). В наборе, который обязан проходить
за минуты, ему места нет — поэтому здесь живёт не замер, а **объявление**
замера, и храповик спрашивает у него три вопроса:

1. объявление читается, схема та, и перечень членов НЕ ДОПИСАН рукой —
   у каждого члена стои́т ``measured_in``;
2. каждый названный член ещё СУЩЕСТВУЕТ в дереве: файл на месте и имя теста
   в нём найдено разбором (не подстрокой — подстрока краснеет от ЖИВОГО
   ключа, дословный урок ADR-916 C);
3. **поверхность ДЕРЕВА совпадает с поверхностью ОБЪЯВЛЕНИЯ** — это и есть
   ТАКТ класса (ADR-920, заказ G908 п. 6): объявление перестаёт отвечать не
   когда сдвинулся календарь, а когда сдвинулась поверхность. Дешёвая дверь
   стоит **24.6 с** против ~23 мин у дифференциала (замер 04.11), поэтому
   такт живёт ЗДЕСЬ и срабатывает механизмом, а не памятью автора: за 30 дней
   до 04.11 в набор пришло 359 новых тест-файлов. Вопрос задаётся ПЛОЩАДКАМ,
   а не файлам: за то же окно перечень файлов не изменился (3 и 3), а площадок
   стало 8 → 4, и исчезнувший ключ — ровно бомба ADR-916;
4. потолок равен длине перечня, и потолок живёт ТОЛЬКО в объявлении.
   Своя копия числа в коде есть ровно тот СЧЁТНЫЙ потолок, который
   устаревает НА ДЕНЬ СВОЕЙ ДОСТАВКИ (ADR-912): на коммите, которым он
   приехал, прибор давал уже другое число.

**Почему это храповик, а не замер.** Отсутствие ИМЁН у класса ADR-905
заставило цикл #1018 заплатить за сторону «ДО» дважды (97 мин против 0).
Объявление — это то, чем следующий цикл берёт сторону ДО бесплатно.

**«Пустое объявление» и «класс пуст» — РАЗНЫЕ утверждения.** Второе
доказывается прибором, а не пустым файлом, и храповик их различает.

Читатель объявления ЕДИНСТВЕННЫЙ (:func:`load_declaration`,
:func:`verdict_for_member`): проба приёмки
``literal_neighbour_class_declaration_holds`` зовёт ИХ ЖЕ, иначе проба и
храповик судили бы РАЗНЫЕ файлы под одним именем.
"""

from __future__ import annotations

import ast
import json
import unittest
from pathlib import Path

from spa_core.tests import _literal_neighbour_door as door

#: Объявление класса — замер с датой и sha, а не константа.
DECLARATION = Path(__file__).resolve().parent / "literal_neighbour_class_baseline.json"

#: Корень дерева, в котором проверяется существование члена.
REPO_ROOT = Path(__file__).resolve().parents[2]

#: Исходы разбора члена. Третий — НЕ «член в порядке».
PRESENT = "present"
FILE_GONE = "file_gone"
NAME_GONE = "name_gone"
UNREADABLE = "unreadable"


def load_declaration(path: Path | None = None) -> dict:
    """Единственный читатель объявления. Схема не та ⇒ исключение, не догадка."""
    target = path or DECLARATION
    doc = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(doc, dict):
        raise ValueError(f"объявление не словарь: {type(doc).__name__}")
    for key in ("order", "members", "member_count", "upper_bound",
                "surface_files", "surface_count", "canary",
                # Такт поверхности (ADR-920). Объявление без этих полей о
                # площадках не отвечало — и обязано сказать это прямо, а не
                # пройти схему и молчать.
                "surface_sites", "surface_site_count",
                "surface_sha", "surface_measured_at"):
        if key not in doc:
            raise ValueError(f"в объявлении нет поля {key!r}")
    return doc


#: Исходы вопроса о такте — ПЕРЕЭКСПОРТ прибора, не своя копия строк.
#: Читатель пробы приёмки берёт их отсюда: литерал `"OK"` у него и был бы тем
#: вторым экземпляром, из-за которого вопрос разошёлся (ADR-912).
TACT_FORM_OK = door.TACT_FORM_OK
TACT_FORM_ABSENT = door.TACT_FORM_ABSENT
TACT_FORM_UNMEASURED = door.TACT_FORM_UNMEASURED


def tact_verdict(declaration: dict | None = None,
                 root: Path | None = None) -> dict:
    """Назвало ли объявление ТАКТ — ЕДИНСТВЕННЫМ читателем этого вопроса.

    Сторож объявления и проба приёмки обязаны судить ОДНО утверждение: до
    ADR-920/заказа G909 п. 2 у них были свои копии вопроса, и копии
    РАСХОДИЛИСЬ — сторож требовал событие при пустом ``max_age_h``, а проба
    непустой ``max_age_h``; одно и то же объявление было у одной копии верным,
    а у другой «без такта». Сам вопрос живёт в ПРИБОРЕ
    (:func:`spa_core.tests._literal_neighbour_door.tact_form`), здесь —
    только проводка, как у :func:`verdict_for_member`.
    """
    doc = declaration if declaration is not None else load_declaration()
    return door.tact_form(doc, root or REPO_ROOT)


def _test_names(path: Path) -> set[str]:
    """Имена тестов файла — РАЗБОРОМ. Подстрока краснела бы от живого ключа."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.ClassDef):
            names.add(node.name)
    return names


def verdict_for_member(member: dict, root: Path | None = None) -> tuple[str, str]:
    """Член объявления ещё в дереве? Три исхода, и ни один не ноль."""
    base = root or REPO_ROOT
    nodeid = str(member.get("nodeid") or "")
    rel = str(member.get("file") or nodeid.split("::")[0])
    path = base / rel
    if not path.is_file():
        return FILE_GONE, f"файла нет в дереве: {rel}"
    try:
        names = _test_names(path)
    except (OSError, SyntaxError, UnicodeDecodeError) as exc:
        return UNREADABLE, f"{rel}: {type(exc).__name__}: {exc}"
    wanted = [p for p in nodeid.split("::")[1:] if p]
    missing = [p for p in wanted if p.split("[")[0] not in names]
    if missing:
        return NAME_GONE, (f"{rel}: имён нет в разборе файла: "
                           f"{', '.join(missing)}")
    return PRESENT, f"{nodeid} на месте"


class LiteralNeighbourClassDeclarationTest(unittest.TestCase):
    """Объявление класса держится — и это проверяется, а не заявляется."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = load_declaration()

    def test_the_declaration_names_its_order_and_its_measurement(self):
        self.assertEqual(self.doc["order"], "G907.2")
        self.assertTrue(self.doc.get("sha"), "объявление не назвало коммит")
        self.assertTrue(self.doc.get("measured_at"),
                        "объявление не назвало момент замера")

    def test_the_scene_of_the_measurement_is_the_instrument_scene(self):
        """Объявление, снятое ЧУЖОЙ сценой, говорит о другом возмущении."""
        self.assertEqual(self.doc.get("scene"), door.GROWN_REL)

    def test_the_canary_of_the_measurement_shifted_the_population(self):
        """Замер, снятый при НЕсдвинутом населении, есть ответ о приборе."""
        canary = self.doc.get("canary") or {}
        self.assertGreaterEqual(int(canary.get("delta", 0)), 1, canary)

    def test_every_member_names_the_measurement_that_found_it(self):
        """Имя без `measured_in` дописано рукой — инв. #16 на уровне данных."""
        naked = [m.get("nodeid", "<без имени>") for m in self.doc["members"]
                 if not m.get("measured_in")]
        self.assertEqual(naked, [], naked)

    def test_every_member_still_exists_in_the_tree(self):
        for member in self.doc["members"]:
            got, detail = verdict_for_member(member)
            self.assertEqual(got, PRESENT, detail)

    def test_the_surface_is_declared_and_still_exists(self):
        """Поверхность — ВТОРОЕ число, и его тоже можно потерять молча."""
        self.assertEqual(self.doc["surface_count"],
                         len(self.doc["surface_files"]))
        for rel in self.doc["surface_files"]:
            self.assertTrue((REPO_ROOT / rel).is_file(), rel)

    def test_the_ceiling_equals_the_list_and_lives_only_here(self):
        """Потолок в коде был бы вторым его экземпляром (ADR-912)."""
        self.assertEqual(self.doc["upper_bound"], len(self.doc["members"]))
        self.assertEqual(self.doc["member_count"], len(self.doc["members"]))

    def test_member_files_agree_with_the_member_names(self):
        """Два перечня одного замера обязаны сходиться — иначе объявление
        отвечает двумя разными числами на один вопрос."""
        from_names = sorted({m["nodeid"].split("::")[0]
                             for m in self.doc["members"]})
        self.assertEqual(sorted(self.doc.get("member_files") or []), from_names)


class VerdictForMemberTest(unittest.TestCase):
    """Половины контроля читателя: он обязан находить и обязан промахиваться."""

    def test_a_present_name_is_present(self):
        got, detail = verdict_for_member(
            {"nodeid": "spa_core/tests/test_literal_neighbour_class_ratchet.py"
                       "::VerdictForMemberTest::test_a_present_name_is_present"})
        self.assertEqual(got, PRESENT, detail)

    def test_a_missing_file_is_named_not_passed(self):
        got, _ = verdict_for_member({"nodeid": "spa_core/tests/t_nope.py::x"})
        self.assertEqual(got, FILE_GONE)

    def test_a_missing_name_is_named_not_passed(self):
        got, _ = verdict_for_member(
            {"nodeid": "spa_core/tests/test_literal_neighbour_class_ratchet.py"
                       "::nobody_wrote_this_name"})
        self.assertEqual(got, NAME_GONE)

    def test_an_unparsable_file_is_the_third_outcome(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.py").write_text("def x(:\n", encoding="utf-8")
            got, detail = verdict_for_member({"nodeid": "broken.py::x"},
                                             root=root)
        self.assertEqual(got, UNREADABLE, detail)


class SurfaceTactTest(unittest.TestCase):
    """ТАКТ класса (ADR-920): объявление перестаёт отвечать, когда сдвинулась
    ПОВЕРХНОСТЬ, а не когда сдвинулся календарь.

    Дорогую половину (дифференциал, ~23 мин на сторону) здесь мерить нельзя —
    поэтому у неё объявление. Дешёвую (обход AST, замер 04.11 — **24.6 с**)
    мерить ЗДЕСЬ можно, и именно это делает такт механизмом, а не надеждой:
    «перемеряет тронувший поверхность» работало только пока кто-то знал, что
    тронул её. За 30 дней до 04.11 в набор пришло **359** новых тест-файлов —
    тронуть поверхность может любой из них, и ни один автор об этом классе не
    знает.
    """

    @classmethod
    def setUpClass(cls) -> None:
        cls.doc = load_declaration()
        cls.surface = door.measure_surface(REPO_ROOT)

    def test_the_surface_of_today_agrees_with_the_declaration(self):
        """Расхождение НАЗЫВАЕТСЯ ключами, а не числом.

        Красный здесь означает ровно одно: поверхность сдвинулась, и дорогую
        половину (``--differential``) надо перемерить — объявление о новых
        площадках не отвечало НИКОГДА. Это НЕ «понизить тест»: заметать
        расхождение дописыванием в объявление рукой запрещено (инв. #16),
        объявление пишет ПРИБОР (``--declare-surface`` / ``--declare``).
        """
        tact = door.surface_divergence(self.doc, self.surface)
        self.assertEqual(
            tact["status"], door.TACT_AGREES,
            "поверхность класса разошлась с объявлением — перемерить "
            "`python3 -m spa_core.tests._literal_neighbour_door "
            "--surface-tact spa_core/tests/literal_neighbour_class_baseline.json`"
            f"\n    появились: {tact.get('appeared')}"
            f"\n    исчезли:   {tact.get('vanished')}"
            f"\n    кратность: {tact.get('recounted')}"
            f"\n    причина НЕ ИЗМЕРЕНО: {tact.get('unmeasured_class')} "
            f"{tact.get('reason')}")

    def test_the_declaration_names_its_own_surface_measurement(self):
        """У дешёвой половины СВОИ sha и момент — цена замеров разная в ~56 раз,
        и общий момент утверждал бы, что дорогая половина перемерена тогда же."""
        self.assertTrue(self.doc.get("surface_sha"),
                        "дешёвая половина не назвала коммит")
        self.assertTrue(self.doc.get("surface_measured_at"),
                        "дешёвая половина не назвала момент")

    def test_the_declaration_names_its_tact_by_reader_and_trigger(self):
        """Такт обязан быть НАЗВАН, иначе он снова исчезнет молча.

        Вопрос задаётся ЕДИНСТВЕННОЙ дверью (:func:`tact_verdict` → прибор):
        своя копия здесь и была тем дефектом, который заказ G909 п. 2 велел
        решить — сторож требовал одного, проба приёмки другого, и одно
        объявление было у них одновременно верным и «без такта».

        ``max_age_h`` объявлен ``None`` НАМЕРЕННО, и рядом названа причина:
        ADR-920 измерил, что календарь отвечает на другой вопрос. «Поля нет»
        и «поле объявлено пустым с причиной» — разные утверждения (инв. #17),
        и дверь проверяет именно второе."""
        got = tact_verdict(self.doc)
        self.assertEqual(got["status"], door.TACT_FORM_OK, got)
        self.assertEqual(got["form"], door.TACT_FORM_TRIGGER, got)
        # Читатель такта — НАСТОЯЩИЙ (разбором файла, а не подстрокой): это
        # дословный урок ADR-918, где названный сборщик не существовал.
        self.assertEqual(got["reader_check"], "verified", got)
        self.assertIn("SurfaceTactTest", got["reader"])

    def test_the_declared_site_count_equals_the_declared_sites(self):
        """Второй экземпляр числа в том же файле — тот же счётный потолок."""
        self.assertEqual(
            self.doc["surface_site_count"],
            sum(int(r["count"]) for r in self.doc["surface_sites"]))

    def test_the_declared_sites_agree_with_the_declared_files(self):
        """Два перечня одной поверхности обязаны сходиться."""
        from_sites = sorted({r["file"] for r in self.doc["surface_sites"]})
        self.assertEqual(sorted(self.doc["surface_files"]), from_sites)


class SurfaceDivergenceControlsTest(unittest.TestCase):
    """Половины контроля такта: он обязан НАХОДИТЬ и обязан ПРОМАХИВАТЬСЯ.

    Такт, который только находит, через неделю отключат; такт, который только
    промахивается, — украшение (`.claude/rules/deployment.md`, § «Проверка
    сторожа сторожей»).
    """

    @staticmethod
    def _surface(sites: list[dict]) -> dict:
        """Замер поверхности из площадок — форма ровно та, что у прибора."""
        files: dict[str, dict] = {}
        for site in sites:
            entry = files.setdefault(site["file"],
                                     {"file": site["file"], "sites": []})
            entry["sites"].append({"line": site.get("line", 1),
                                   "callee": site["callee"],
                                   "declared": site["declared"],
                                   "door": door.DOOR_LITERAL_LIVE})
        return {"status": "MEASURED", "files": list(files.values()),
                "counts": {"on_live_root": len(files),
                           "sites_on_live_root": len(sites), "unmeasured": 0}}

    SITE = {"file": "spa_core/tests/test_a.py", "callee": "step",
            "declared": [7], "line": 10}

    def _declaration(self, sites: list[dict]) -> dict:
        surf = self._surface(sites)
        return {"members": [],
                **door.surface_half(surf, sha="deadbeef", measured_at="now")}

    def test_an_unchanged_surface_agrees(self):
        doc = self._declaration([self.SITE])
        got = door.surface_divergence(doc, self._surface([self.SITE]))
        self.assertEqual(got["status"], door.TACT_AGREES, got)

    def test_a_new_site_is_found_and_named(self):
        """Ровно авария ADR-916 на один шаг вперёд: площадка, которой в
        объявлении не было, обязана быть НАЗВАНА, а не посчитана."""
        doc = self._declaration([self.SITE])
        extra = {**self.SITE, "callee": "another_step", "line": 99}
        got = door.surface_divergence(doc, self._surface([self.SITE, extra]))
        self.assertEqual(got["status"], door.TACT_DIVERGED, got)
        self.assertEqual(
            got["appeared"],
            ["spa_core/tests/test_a.py::another_step(7) ×1"], got)
        self.assertEqual(got["vanished"], [], got)

    def test_a_moved_line_does_NOT_diverge(self):
        """Несущая половина контроля: ключ БЕЗ строки.

        Включи ``lineno`` в ключ — и такт краснел бы от любой правки выше
        площадки, то есть сам стал бы тем литералом, устаревающим молча,
        против которого написан. Проверяется ПРОМАХ, а не находка."""
        doc = self._declaration([self.SITE])
        moved = {**self.SITE, "line": 1_000}
        got = door.surface_divergence(doc, self._surface([moved]))
        self.assertEqual(got["status"], door.TACT_AGREES, got)

    def test_a_changed_multiplicity_is_found(self):
        """Замер 04.11: за 30 дней ОДНА площадка сменила кратность 5 → 1 при
        НЕИЗМЕННОМ перечне файлов. Перечень без кратности это пропустил бы."""
        doc = self._declaration([self.SITE] * 5)
        got = door.surface_divergence(doc, self._surface([self.SITE]))
        self.assertEqual(got["status"], door.TACT_DIVERGED, got)
        self.assertEqual(got["recounted"],
                         ["spa_core/tests/test_a.py::step(7): 5 → 1"], got)
        self.assertEqual(got["declared_site_count"], 5, got)
        self.assertEqual(got["measured_site_count"], 1, got)

    def test_a_vanished_site_is_found_and_named(self):
        doc = self._declaration([self.SITE])
        got = door.surface_divergence(doc, self._surface([]))
        self.assertEqual(got["status"], door.TACT_DIVERGED, got)
        self.assertEqual(got["vanished"],
                         ["spa_core/tests/test_a.py::step(7) ×1"], got)

    def test_a_declaration_without_sites_is_UNMEASURED_not_agreement(self):
        """Третий исход (инв. #17): объявление старше такта о площадках не
        отвечало. Назвать это «совпало» значило бы выдать «не измерено» за
        чистый ответ — ровно дефект `pyflakes` из правила доставки."""
        got = door.surface_divergence({"members": []},
                                      self._surface([self.SITE]))
        self.assertEqual(got["status"], door.TACT_UNMEASURED, got)
        self.assertEqual(got["unmeasured_class"], "declaration_has_no_sites")

    def test_an_unmeasured_surface_is_UNMEASURED_not_agreement(self):
        doc = self._declaration([self.SITE])
        got = door.surface_divergence(
            doc, {"status": "UNMEASURED", "unmeasured_class": "test_dir_absent",
                  "reason": "каталога нет"})
        self.assertEqual(got["status"], door.TACT_UNMEASURED, got)
        self.assertEqual(got["unmeasured_class"], "surface_not_measured")
        self.assertIn("каталога нет", got["reason"])

    def test_sites_that_are_not_on_a_live_root_are_not_surface(self):
        """Литерал СВОЕЙ сцены предметом не является (ADR-919 § 2): население
        задаёт сама сцена, и оно не дрейфует."""
        surf = self._surface([self.SITE])
        surf["files"][0]["sites"][0]["door"] = door.DOOR_LITERAL_SCENE
        self.assertEqual(door.surface_sites(surf), [])

    def test_a_declaration_whose_sites_field_is_not_a_list_is_UNMEASURED(self):
        got = door.surface_divergence({"members": [], "surface_sites": 4},
                                      self._surface([self.SITE]))
        self.assertEqual(got["status"], door.TACT_UNMEASURED, got)
        self.assertEqual(got["unmeasured_class"],
                         "declaration_sites_not_a_list")


class TactFormControlsTest(unittest.TestCase):
    """Контроли ЕДИНСТВЕННОЙ двери вопроса о такте (ADR-920, заказ G909 п. 2).

    Половин две, и вторая важнее первой. Дверь обязана **НАХОДИТЬ** записку
    (названное событие, которого в приборе нет; читатель, которого нет в
    дереве; триггер без якорей сверки) — и обязана **ПРОМАХИВАТЬСЯ** по
    законному календарному такту: правка, сделанная ради формы `trigger`, не
    имеет права объявить форму `max_age_h` поломкой. У класса ADR-913
    поверхность живёт НЕ в дереве, спросить её из набора нельзя, и календарь
    для него — единственный доступный вопрос.
    """

    #: Якоря сверки, без которых триггеру не с чем сравнивать.
    ANCHORS = {"surface_sha": "deadbeefcafe",
               "surface_measured_at": "2026-11-04T00:00:00Z",
               "surface_sites": []}

    #: Читатель, существующий в дереве ПО ПОСТРОЕНИЮ: это сам этот класс.
    LIVE_READER = ("spa_core/tests/test_literal_neighbour_class_ratchet.py"
                   "::TactFormControlsTest")

    def _doc(self, tact, **extra) -> dict:
        doc = dict(self.ANCHORS)
        doc["tact"] = tact
        doc.update(extra)
        return doc

    # --- ПРОМАХ: законные формы такта остаются законными ------------------ #

    def test_the_trigger_form_is_accepted_and_named(self):
        got = tact_verdict(self._doc(
            {"reader": self.LIVE_READER, "trigger": "surface_divergence",
             "max_age_h": None,
             "max_age_h_rejected_because": "ADR-920: класс меняется от "
                                           "правки дерева"}))
        self.assertEqual(got["status"], TACT_FORM_OK, got)
        self.assertEqual(got["form"], door.TACT_FORM_TRIGGER, got)
        self.assertEqual(got["reader_check"], "verified", got)

    def test_the_calendar_form_stays_legal(self):
        """Правка ради триггера не вправе объявить календарь поломкой.

        Читатель здесь назван свободным именем шага цикла — и это НЕ
        подделка: существование такого читателя дверь проверить не может и
        говорит об этом вслух (``unverifiable_form``), вместо того чтобы
        выдать непроверенное за проверенное.
        """
        got = tact_verdict(self._doc({"reader": "шаг 0-офис",
                                      "max_age_h": 192}))
        self.assertEqual(got["status"], TACT_FORM_OK, got)
        self.assertEqual(got["form"], door.TACT_FORM_CALENDAR, got)
        self.assertEqual(got["reader_check"], "unverifiable_form", got)
        self.assertIn("НЕ ПРОВЕРЕН", got["reason"])

    # --- НАХОДКА: каждое порванное звено НАЗВАНО -------------------------- #

    def test_no_tact_at_all_is_absent(self):
        got = tact_verdict({})
        self.assertEqual(got["status"], TACT_FORM_ABSENT, got)
        self.assertIn("`tact`", got["reason"])

    def test_a_tact_without_a_reader_is_absent(self):
        got = tact_verdict(self._doc({"trigger": "surface_divergence"}))
        self.assertEqual(got["status"], TACT_FORM_ABSENT, got)
        self.assertIn("ЧИТАТЕЛЯ", got["reason"])

    def test_neither_form_is_absent_not_agreement(self):
        got = tact_verdict(self._doc({"reader": self.LIVE_READER}))
        self.assertEqual(got["status"], TACT_FORM_ABSENT, got)
        self.assertIn("НИ события", got["reason"])

    def test_a_trigger_that_is_not_a_door_of_the_instrument_is_absent(self):
        """Событие, названное словом, которого в приборе нет, — записка."""
        got = tact_verdict(self._doc(
            {"reader": self.LIVE_READER, "trigger": "kogda_nastroenie",
             "max_age_h_rejected_because": "причина названа"}))
        self.assertEqual(got["status"], TACT_FORM_ABSENT, got)
        self.assertIn("дверью прибора не является", got["reason"])

    def test_a_trigger_without_its_own_anchors_is_absent(self):
        """Триггеру без ``surface_sha``/``surface_sites`` сверять НЕ С ЧЕМ."""
        doc = self._doc({"reader": self.LIVE_READER,
                         "trigger": "surface_divergence",
                         "max_age_h_rejected_because": "причина названа"})
        doc.pop("surface_sha")
        doc.pop("surface_sites")
        got = tact_verdict(doc)
        self.assertEqual(got["status"], TACT_FORM_ABSENT, got)
        self.assertIn("surface_sha", got["reason"])
        self.assertIn("surface_sites", got["reason"])

    def test_a_calendar_rejected_without_a_price_is_absent(self):
        """«Поля нет» и «поле объявлено пустым С ПРИЧИНОЙ» — разные вещи."""
        got = tact_verdict(self._doc(
            {"reader": self.LIVE_READER, "trigger": "surface_divergence",
             "max_age_h": None}))
        self.assertEqual(got["status"], TACT_FORM_ABSENT, got)
        self.assertIn("БЕЗ названной цены", got["reason"])

    def test_a_reader_whose_file_is_gone_is_absent_not_verified(self):
        """Дословный урок ADR-918: названный читатель, которого нет."""
        got = tact_verdict(self._doc(
            {"reader": "spa_core/tests/t_nikogda_ne_bylo.py::Reader",
             "max_age_h": 192}))
        self.assertEqual(got["status"], TACT_FORM_ABSENT, got)
        self.assertEqual(got["reader_check"], "missing", got)

    def test_a_reader_name_absent_from_a_live_file_is_absent(self):
        got = tact_verdict(self._doc(
            {"reader": ("spa_core/tests/"
                        "test_literal_neighbour_class_ratchet.py::NetTakogo"),
             "trigger": "surface_divergence",
             "max_age_h_rejected_because": "причина названа"}))
        self.assertEqual(got["status"], TACT_FORM_ABSENT, got)
        self.assertIn("разбором не найдено", got["reason"])

    def test_an_unparsable_reader_file_is_the_third_outcome(self):
        """Третий исход (инв. #17): судить нечем ≠ «такта нет»."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "broken.py").write_text("def (:\n", encoding="utf-8")
            got = tact_verdict(self._doc({"reader": "broken.py::Reader",
                                          "max_age_h": 192}), root=root)
        self.assertEqual(got["status"], TACT_FORM_UNMEASURED, got)
        self.assertEqual(got["reader_check"], "unparsable", got)
        self.assertIn("SyntaxError", got["reason"])


if __name__ == "__main__":                               # pragma: no cover
    unittest.main()
