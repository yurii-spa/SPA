"""Батарея прибора `_office_declaration_doors`: контроль в ОБЕ стороны.

# LLM_FORBIDDEN

Заказ G698 п. 3 (ADR-704). Правило приёмки ADR-333: проба меряет ИСХОД, и у
неё есть контроль в обе стороны — класс находится там, где он есть, и НЕ
находится там, где его нет, с НАЗВАННЫМ звеном. Три исхода различены сценами с
НЕРАВНЫМИ счётами, иначе подмена одного исхода другим невидима (урок #786).

Дат в фикстурах нет ВОВСЕ: предметом здесь является форма объявления, и
календарь к ней отношения не имеет.
"""
from __future__ import annotations

import json
import textwrap
import unittest
from pathlib import Path

from spa_core.tests import _fixture_schema_gap as gap
from spa_core.tests import _office_declaration_doors as doors


def _has_path(data, path: str) -> bool:
    """Правило шага 0-офис, приведённое ВХОДОМ (дословная копия `_has_path`).

    Как и у соседа, это не второе правило, а МАТЕРИАЛ сцены: прибор получает
    его от офиса и своей версии не держит.
    """
    cur = data
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return False
        cur = cur[part]
    return True


class _Office:
    """Офис сцены: ровно те объявления и решатели, которые прибор спрашивает."""

    CONSUMER = "orchestrator_protocol"

    def __init__(self, *, read_schema=None, producer=None, ts_field=None,
                 ts_unit=None, tick=None, targets=None):
        self._READ_SCHEMA = read_schema or {}
        self._PRODUCER = producer if producer is not None else dict.fromkeys(
            self._READ_SCHEMA, "spa_core/x.py")
        self._TS_FIELD = ts_field or {}
        self._TS_UNIT = ts_unit or {}
        self._has_path = staticmethod(_has_path).__func__
        self._tick = tick or (lambda name, root: (1.0, f"schedule {name}"))
        self._targets = targets
        self.tick_calls: list[str] = []
        self.target_calls = 0

    def _producer_tick_hours(self, name, root):
        self.tick_calls.append(name)
        return self._tick(name, root)

    def office_targets(self, manifest, consumer=CONSUMER):
        self.target_calls += 1
        if self._targets is not None:
            return list(self._targets)
        return [a["path"] for a in manifest.get("artifacts", [])
                if a.get("status") == "active"
                and consumer in (a.get("consumers") or [])]


class _SceneCase(unittest.TestCase):
    """Одноразовое дерево: каталог тестов `t/` и конституция сцены."""

    def scene(self, files: dict[str, str], *, office: _Office,
              manifest: dict | None = None) -> doors.Doors:
        root = Path(self.enterContext(__import__("tempfile").TemporaryDirectory()))
        (root / "t").mkdir()
        for name, body in files.items():
            (root / "t" / name).write_text(textwrap.dedent(body), encoding="utf-8")
        if manifest is not None:
            (root / "architecture").mkdir(parents=True, exist_ok=True)
            (root / "architecture" / "manifest.json").write_text(
                json.dumps(manifest), encoding="utf-8")
        return doors.measure(office=office, root=str(root), test_dirs=("t",))


_DOC_WITHOUT_TS = """
    def test_x():
        _summarize_json("x.json", {"status": "OK"})
"""
_DOC_WITH_TS = """
    def test_x():
        _summarize_json("x.json", {"ts": "...", "status": "OK"})
"""


# ── 1. класс находится там, где он есть ──────────────────────────────────────

class TheClassIsFoundWhereItIs(_SceneCase):

    def test_a_declared_ts_field_the_fixture_does_not_carry(self):
        d = self.scene({"test_a.py": _DOC_WITHOUT_TS},
                       office=_Office(ts_field={"x.json": "ts"}))
        door = d["ts_field_declared"]
        self.assertEqual(len(door.population), 1, doors.report(d))
        self.assertEqual(door.population[0][1], "x.json")
        self.assertIn("ts", door.population[0][2])
        self.assertEqual(door.strength, doors.DECLARED)

    def test_the_default_generated_at_is_a_SEPARATE_door(self):
        """Объявления нет — утверждение другое, и счёт у него СВОЙ."""
        d = self.scene({"test_a.py": _DOC_WITHOUT_TS},
                       office=_Office(read_schema={"x.json": ("status",)}))
        self.assertEqual(len(d["ts_field_declared"].population), 0)
        self.assertEqual(len(d["ts_field_default"].population), 1)
        self.assertEqual(d["ts_field_default"].strength, doors.DEFAULTED)
        # Счёты НЕРАВНЫ: подмена одной двери другой была бы видна.
        self.assertNotEqual(len(d["ts_field_declared"].population),
                            len(d["ts_field_default"].population))

    def test_an_artifact_with_a_schema_but_no_declared_producer(self):
        d = self.scene({}, office=_Office(read_schema={"x.json": ("status",)},
                                          producer={}))
        door = d["producer"]
        self.assertEqual(len(door.population), 1, door)
        self.assertEqual(door.operand, doors.ARTIFACTS)
        self.assertEqual(door.operand_size, 1)

    def test_an_office_artifact_whose_tick_is_not_measurable(self):
        office = _Office(tick=lambda name, root: (None, "адрес не найден"))
        d = self.scene({}, office=office, manifest={"artifacts": [
            {"path": "data/x.json", "status": "active",
             "consumers": ["orchestrator_protocol"]}]})
        door = d["manifest"]
        self.assertEqual(len(door.population), 1, door)
        self.assertIn("адрес не найден", door.population[0][2])


# ── 2. и НЕ находится там, где его нет ───────────────────────────────────────

class TheClassIsNotFoundWhereItIsNot(_SceneCase):

    def test_a_fixture_that_carries_the_declared_field(self):
        d = self.scene({"test_a.py": _DOC_WITH_TS},
                       office=_Office(ts_field={"x.json": "ts"}))
        door = d["ts_field_declared"]
        self.assertEqual(door.population, ())
        self.assertTrue(door.measured_zero, door)

    def test_an_artifact_outside_the_subject_is_not_population(self):
        """Имя разрешено, объявления о нём нет — стеречь нечего."""
        d = self.scene({"test_a.py": _DOC_WITHOUT_TS},
                       office=_Office(ts_field={"other.json": "ts"}))
        self.assertEqual(d["ts_field_declared"].population, ())
        self.assertEqual(d["ts_field_declared"].operand_size, 0)

    def test_every_declared_producer_means_a_measured_zero(self):
        d = self.scene({}, office=_Office(read_schema={"x.json": ("status",)}))
        self.assertEqual(d["producer"].population, ())
        self.assertTrue(d["producer"].measured_zero)


# ── 3. третий исход — СВОЙ ответ, а не ноль населения ────────────────────────

class TheThirdOutcomeIsItsOwnAnswer(_SceneCase):

    def test_no_site_feeds_the_subject_is_not_clean(self):
        d = self.scene({}, office=_Office(ts_field={"x.json": "ts"},
                                          ts_unit={"x.json": "epoch_seconds"}))
        door = d["ts_unit"]
        self.assertEqual(door.population, ())
        self.assertFalse(door.measured_zero, door)
        self.assertEqual([why for _, why in door.third], [doors.NO_SITE])

    def test_the_unit_itself_is_a_limit_of_the_instrument(self):
        """Площадка есть, а значения листа в скелете нет ПО ПОСТРОЕНИЮ."""
        d = self.scene({"test_a.py": _DOC_WITH_TS},
                       office=_Office(ts_field={"x.json": "ts"},
                                      ts_unit={"x.json": "epoch_seconds"}))
        door = d["ts_unit"]
        self.assertEqual(door.operand_size, 1)
        self.assertEqual([why for _, why in door.third], [doors.NO_VALUE])

    def test_an_unreadable_constitution_leaves_the_door_unmeasured(self):
        d = self.scene({}, office=_Office())
        door = d["manifest"]
        self.assertEqual(door.population, ())
        self.assertEqual(door.operand_size, 0)
        self.assertFalse(door.measured_zero, door)
        self.assertTrue(any("манифест не прочитан" in why
                            for _, why in door.third), door.third)


# ── 4. освобождение СОСЕДА этой двери не закрывает ───────────────────────────

class TheNeighboursExemptionDoesNotSilenceThisDoor(_SceneCase):

    def test_a_marked_site_stays_in_the_population_and_is_counted(self):
        d = self.scene({"test_a.py": """
            def test_x():
                _summarize_json("x.json", {"status": "OK"})  # SCHEMA-GAP-OK: про другое
        """}, office=_Office(read_schema={"x.json": ("status",)}))
        door = d["ts_field_default"]
        self.assertEqual(len(door.population), 1, door)
        self.assertEqual(len(door.exempt_at_the_neighbour), 1, door)

    def test_an_unmarked_site_is_not_counted_as_exempt(self):
        d = self.scene({"test_a.py": _DOC_WITHOUT_TS},
                       office=_Office(read_schema={"x.json": ("status",)}))
        door = d["ts_field_default"]
        self.assertEqual(len(door.population), 1, door)
        self.assertEqual(door.exempt_at_the_neighbour, ())


# ── 5. вердикт берётся у РЕШАТЕЛЯ офиса, а не у копии правила ────────────────

class TheVerdictComesFromTheOfficesOwnResolver(_SceneCase):

    def test_an_artifact_absent_from_the_manifest_is_judged_by_the_resolver(self):
        """Решатель сказал «такт измерен» — прибор не спорит с ним своим разбором.

        Сцена нарочно противоречива: артефакт в `artifacts[]` ЕСТЬ (иначе он не
        попал бы в операнд), а объявления о производителе у него нет вовсе.
        Если бы прибор искал такт сам, он нашёл бы пробел; он спрашивает
        офис — и печатает ЕГО ответ.
        """
        office = _Office(tick=lambda name, root: (24.0, "schedule — у офиса"))
        d = self.scene({}, office=office, manifest={"artifacts": [
            {"path": "data/sub/x.json", "status": "active",
             "consumers": ["orchestrator_protocol"]}]})
        self.assertEqual(d["manifest"].population, ())
        self.assertEqual(office.tick_calls, ["x.json"])

    def test_the_operand_is_the_offices_own_target_rule(self):
        office = _Office(targets=["data/only_this.json"])
        d = self.scene({}, office=office, manifest={"artifacts": [
            {"path": "data/a.json", "status": "active",
             "consumers": ["orchestrator_protocol"]},
            {"path": "data/b.json", "status": "active",
             "consumers": ["orchestrator_protocol"]}]})
        self.assertEqual(office.target_calls, 1)
        self.assertEqual(d.targets, 1)
        self.assertEqual(office.tick_calls, ["only_this.json"])

    def test_the_operand_names_artifacts_declared_elsewhere_than_data(self):
        office = _Office()
        d = self.scene({}, office=office, manifest={"artifacts": [
            {"path": "data/flat.json", "status": "active",
             "consumers": ["orchestrator_protocol"]},
            {"path": "data/sub/deep.json", "status": "active",
             "consumers": ["orchestrator_protocol"]},
            {"path": "docs/A.md", "status": "active",
             "consumers": ["orchestrator_protocol"]}]})
        self.assertEqual(d.addressed_elsewhere,
                         ("data/sub/deep.json", "docs/A.md"))


# ── 6. контракт прибора пришпилен ДОСЛОВНО ──────────────────────────────────

class TheContractIsPinnedLiterally(unittest.TestCase):

    def test_the_set_of_doors_is_an_equality_not_a_membership(self):
        """Новая дверь обязана быть объявлена, исчезнувшая — краснеет."""
        self.assertEqual(set(doors.DOOR_KEYS),
                         {"ts_field_declared", "ts_field_default", "ts_unit",
                          "producer", "manifest"})

    def test_the_report_prints_a_line_for_every_door(self):
        office = _Office(read_schema={"x.json": ("status",)})
        census = doors.Doors(doors={
            k: doors.Door(name=k, claim="", strength=doors.DECLARED,
                          operand=doors.SITES, operand_size=1,
                          subject_artifacts=1)
            for k in doors.DOOR_KEYS})
        text = "\n".join(doors.report(census))
        for key in doors.DOOR_KEYS:
            self.assertIn(f"[ДВЕРЬ {key}]", text)
        self.assertIn("[ОПЕРАНД]", text)
        self.assertEqual(office.tick_calls, [])

    def test_the_site_resolution_has_a_single_home(self):
        """Прибор зовёт разбор СОСЕДА, а не свою копию (урок ADR-502)."""
        source = Path(doors.__file__).read_text(encoding="utf-8")
        self.assertIn("gap.measure", source)
        self.assertNotIn("ast.walk", source)


# ── 7. ЖИВОЕ дерево: ответ заказа G698 п. 3 ─────────────────────────────────

class TheLiveAnswerOfTheOrder(unittest.TestCase):
    """Замер на этом репозитории. Потолки могут только УМЕНЬШАТЬСЯ.

    Дописывать в потолок, чтобы погасить падение, ЗАПРЕЩЕНО (инв. #16) —
    честные выходы те же, что у соседа: дать фикстуре значение либо назвать
    площадку предметом СВОЕЙ двери с причиной.
    """

    #: Население двери `ts_field_default` на 2026-10-12 (ADR-704): 16 площадок,
    #: из них 11 несут пометку соседней двери, выданную под ДРУГУЮ причину.
    #: Утверждение здесь слабее, чем у объявленных дверей, и это сказано вслух
    #: в справке прибора: `generated_at` никто не объявлял.
    DEFAULT_CEILING = 16

    @classmethod
    def setUpClass(cls):
        import importlib
        cls.office = importlib.import_module("scripts.consume_office_reports")
        cls.root = str(Path(__file__).resolve().parents[2])
        cls.doors = doors.measure(office=cls.office, root=cls.root)

    def test_every_office_artifact_has_a_measurable_producer_tick(self):
        """13 из 133 были «не объявлены в конституции» ЛОЖНО (ADR-704)."""
        door = self.doors["manifest"]
        self.assertTrue(door.operand_size > 100,
                        f"операнд НЕ ИЗМЕРЕН: {door.operand_size} · {door.third}")
        self.assertEqual(door.population, (),
                         f"такт НЕ ИЗМЕРИМ у {len(door.population)} из "
                         f"{door.operand_size}: {door.population[:3]}")

    def test_the_declared_ts_field_is_carried_by_every_site(self):
        door = self.doors["ts_field_declared"]
        self.assertTrue(door.measured_zero,
                        f"население {len(door.population)}: {door.population}")

    def test_every_artifact_with_a_schema_declares_its_producer(self):
        door = self.doors["producer"]
        self.assertTrue(door.measured_zero,
                        f"население {len(door.population)}: {door.population}")

    def test_the_default_ts_door_does_not_grow(self):
        door = self.doors["ts_field_default"]
        self.assertLessEqual(
            len(door.population), self.DEFAULT_CEILING,
            f"площадок без отметки времени стало больше потолка "
            f"{self.DEFAULT_CEILING}: {door.population}")

    def test_the_unit_door_says_why_it_is_unmeasured(self):
        """Ноль при пустом операнде обязан НАЗЫВАТЬ причину, а не молчать."""
        door = self.doors["ts_unit"]
        if door.operand_size == 0:
            self.assertEqual([why for _, why in door.third], [doors.NO_SITE])
        else:
            self.assertTrue(all(why == doors.NO_VALUE for _, why in door.third),
                            door.third)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
