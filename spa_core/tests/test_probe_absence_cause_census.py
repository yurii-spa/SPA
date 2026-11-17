"""Батарея прибора `spa_core/monitoring/probe_absence_cause_census.py` (ADR-1042).

# LLM_FORBIDDEN

Заказ **G1030 п. 3** требует РАЗБИТЬ 46 членов класса ADR-1041 по причинам и
мерить это ЗАСЕВОМ, а не чтением глазами. Заказ **G1030 п. 2** требует, чтобы
калибровка любого такого замера была ДВУСТОРОННЕЙ — известные члены И известные
НЕ-члены, — потому что ошибка автора бывает в обе стороны.

Батарея устроена по тому же правилу и на двух уровнях:

* сцены ниже — положительные контроли КАЖДОГО звена: канонический засев
  ОБЯЗАН менять исход, а каждый дефектный (снимающий ровно один конъюнкт
  формы) — НЕ менять, и снятый конъюнкт назван в самом тесте;
* `TheLiveTreeIsMeasuredAndKnownMembersAreShown` зовёт прибор о ЖИВОМ дереве и
  предъявляет ему известных членов, названных НЕ из его ответа — то есть сам
  прибор не становится новым членом класса, который мерит (ADR-1041), пробой,
  а не умолчанием.

Литеральных дат в файле нет ни одной: о свежести прибор не судит, и дверей к
календарю у него нет по построению.
"""
from __future__ import annotations

import ast
import json
import pathlib
import sys
import tempfile
import textwrap
import unittest

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.monitoring import known_member_probe_census as km  # noqa: E402
from spa_core.monitoring import probe_absence_cause_census as pac  # noqa: E402

_SUBJECT = "spa_core/monitoring/thing_census.py"
_BATTERY = "spa_core/tests/test_thing_census.py"
_BASELINE = "spa_core/tests/probe_absence_cause_baseline.json"
_SIBLING_BASELINE = "spa_core/tests/known_member_probe_baseline.json"

#: Прибор сцены: объявляет два ярлыка исхода и читает AST — форма поверхности
#: `_population_verdict_surface`. Корень приходит аргументом.
_INSTRUMENT = '''
import ast
GOOD = "good"
BAD = "bad"

def measure(root):
    return {"population": [], "declared_outside_form": []}
'''


def _tree(files: dict[str, str]) -> pathlib.Path:
    """Одноразовое дерево сцены. Живым корнем НЕ является и им не выдаётся."""
    root = pathlib.Path(tempfile.mkdtemp())
    for rel, body in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(textwrap.dedent(body), encoding="utf-8")
    return root


def _battery_importing(body: str) -> str:
    return ("import pathlib\n"
            "from spa_core.monitoring import thing_census\n\n" + textwrap.dedent(body))


class TheSeedFormIsAPositiveControl(unittest.TestCase):
    """Канонический засев МЕНЯЕТ исход. Не менял бы — мерить было бы нечем."""

    def setUp(self):
        self.root = _tree({
            _SUBJECT: _INSTRUMENT,
            _BATTERY: _battery_importing('''
                def test_something_unrelated():
                    value = 2 + 2
                    assert value == 4
            '''),
        })

    def test_the_canonical_seed_flips_the_outcome(self):
        got = pac.trial(self.root, _SUBJECT, _BATTERY, pac.SEED_CANONICAL)
        self.assertTrue(got.flipped, got.reason)
        self.assertEqual(pac.BY_MODULE, got.door)
        self.assertEqual(km.ITEM_PATH, got.probe_form)

    def test_the_door_of_the_seed_is_READ_at_the_battery_not_invented(self):
        source = (self.root / _BATTERY).read_text(encoding="utf-8")
        door, why = pac.seed_door(source, _SUBJECT)
        self.assertEqual(pac.BY_MODULE, door)
        self.assertIn("thing_census", why)

    def test_a_battery_that_binds_nothing_is_UNMEASURED_not_probe_absent(self):
        root = _tree({
            _SUBJECT: _INSTRUMENT,
            _BATTERY: "def test_nothing():\n    assert True\n",
        })
        source = (root / _BATTERY).read_text(encoding="utf-8")
        door, why = pac.seed_door(source, _SUBJECT)
        self.assertIsNone(door)
        self.assertIn("засев составить нечем", why)
        got = pac.trial(root, _SUBJECT, _BATTERY, pac.SEED_CANONICAL)
        self.assertIsNone(got.flipped)
        self.assertIsNotNone(got.reason)

    def test_the_named_function_door_is_recognised(self):
        root = _tree({
            _SUBJECT: _INSTRUMENT,
            _BATTERY: ("import pathlib\n"
                       "from spa_core.monitoring.thing_census import measure\n\n"
                       "def test_unrelated():\n    assert True\n"),
        })
        source = (root / _BATTERY).read_text(encoding="utf-8")
        self.assertEqual(pac.BY_FUNC, pac.seed_door(source, _SUBJECT)[0])
        self.assertTrue(pac.trial(root, _SUBJECT, _BATTERY,
                                  pac.SEED_CANONICAL).flipped)

    def test_the_path_door_is_recognised_and_the_seed_names_the_root(self):
        root = _tree({
            _SUBJECT: _INSTRUMENT,
            _BATTERY: ("import pathlib\n\n"
                       "def test_unrelated():\n"
                       f"    where = {_SUBJECT!r}\n"
                       "    assert where\n"),
        })
        source = (root / _BATTERY).read_text(encoding="utf-8")
        self.assertEqual(pac.BY_PATH, pac.seed_door(source, _SUBJECT)[0])
        self.assertTrue(pac.trial(root, _SUBJECT, _BATTERY,
                                  pac.SEED_CANONICAL).flipped)


class EachDefectiveSeedDropsExactlyOneConjunct(unittest.TestCase):
    """Отрицательный контроль по КАЖДОМУ конъюнкту формы, конъюнкт назван."""

    def setUp(self):
        self.root = _tree({
            _SUBJECT: _INSTRUMENT,
            _BATTERY: _battery_importing('''
                def test_something_unrelated():
                    value = 2 + 2
                    assert value == 4
            '''),
        })

    def test_a_disposable_root_does_not_count_as_a_live_call(self):
        got = pac.trial(self.root, _SUBJECT, _BATTERY, pac.SEED_NO_LIVE)
        self.assertFalse(got.flipped, pac.DROPPED_CONJUNCT[pac.SEED_NO_LIVE])

    def test_comparing_the_answer_with_itself_shows_no_known_member(self):
        got = pac.trial(self.root, _SUBJECT, _BATTERY, pac.SEED_NO_MEMBER)
        self.assertFalse(got.flipped, pac.DROPPED_CONJUNCT[pac.SEED_NO_MEMBER])

    def test_a_claim_without_any_call_to_the_instrument_does_not_flip(self):
        got = pac.trial(self.root, _SUBJECT, _BATTERY, pac.SEED_NO_CALL)
        self.assertFalse(got.flipped, pac.DROPPED_CONJUNCT[pac.SEED_NO_CALL])

    def test_every_declared_seed_is_tried_and_the_list_is_closed(self):
        self.assertEqual(set(pac.SEEDS),
                         {pac.SEED_CANONICAL} | set(pac.DEFECTIVE_SEEDS))
        for seed in pac.SEEDS:
            self.assertIn(seed, pac.DROPPED_CONJUNCT)


class TheShortcutAgreesWithTheFullDoor(unittest.TestCase):
    """Засев мерится читателем одной батареи — и ПОЛНАЯ перепись согласна.

    Без этого контроля короткий путь отвечал бы на свой вопрос: `trial` зовёт
    `probes_in_battery`, а население соседа считает `measure`, которая сперва
    ещё и ИЩЕТ батареи. Расхождение этих двух было бы ровно тем дефектом
    «доказательство слабее вызова», о котором G1030 п. 4.
    """

    def test_the_full_census_changes_verdict_exactly_where_the_trial_says(self):
        files = {
            _SUBJECT: _INSTRUMENT,
            _BATTERY: _battery_importing('''
                def test_something_unrelated():
                    value = 2 + 2
                    assert value == 4
            '''),
        }
        root = _tree(files)
        before = km.measure(root, [_SUBJECT])
        self.assertEqual(km.NO_PROBE, before.rows[0].outcome)
        got = pac.trial(root, _SUBJECT, _BATTERY, pac.SEED_CANONICAL)
        self.assertTrue(got.flipped, got.reason)
        source = (root / _BATTERY).read_text(encoding="utf-8")
        (root / _BATTERY).write_text(
            source + pac.seed_text(source, _SUBJECT, pac.BY_MODULE,
                                   pac.SEED_CANONICAL), encoding="utf-8")
        after = km.measure(root, [_SUBJECT])
        self.assertEqual(km.HAS_PROBE, after.rows[0].outcome)


class TheSecondAxisMeasuresTheBatterysOwnMaterial(unittest.TestCase):
    """ДИСТАНЦИЯ: живой зов в тесте уже есть, нет только имени члена."""

    def test_a_test_with_a_live_call_is_ONE_CLAIM_away_and_is_NAMED(self):
        root = _tree({
            _SUBJECT: _INSTRUMENT,
            _BATTERY: _battery_importing('''
                def test_the_instrument_answers_on_the_live_tree():
                    root = pathlib.Path(__file__).resolve().parents[2]
                    answer = thing_census.measure(root)
                    assert answer["population"] == []
            '''),
        })
        got = pac.claim_trial(root, _SUBJECT, _BATTERY)
        self.assertTrue(got.flipped, got.reason)
        self.assertEqual("test_the_instrument_answers_on_the_live_tree",
                         got.probe_test)

    def test_a_battery_without_any_live_call_is_NO_LIVE_CALL(self):
        root = _tree({
            _SUBJECT: _INSTRUMENT,
            _BATTERY: _battery_importing('''
                def test_the_instrument_answers_on_a_disposable_tree():
                    import tempfile
                    with tempfile.TemporaryDirectory() as tmp:
                        answer = thing_census.measure(tmp)
                        assert answer["population"] == []
            '''),
        })
        got = pac.claim_trial(root, _SUBJECT, _BATTERY)
        self.assertFalse(got.flipped, got.reason)
        self.assertIn("живого зова нет", got.reason)

    def test_a_test_binding_no_names_is_UNMEASURED_not_NO_LIVE_CALL(self):
        root = _tree({
            _SUBJECT: _INSTRUMENT,
            _BATTERY: _battery_importing('''
                def test_binds_nothing():
                    assert True
            '''),
        })
        got = pac.claim_trial(root, _SUBJECT, _BATTERY)
        self.assertIsNone(got.flipped)
        self.assertIn("дописать утверждение некуда", got.reason)

    def test_the_claim_is_inserted_at_the_end_of_the_function_body(self):
        source = _battery_importing('''
            def test_one():
                root = pathlib.Path(__file__)
                assert root

            def test_two():
                other = 1
                assert other
        ''')
        tree = ast.parse(source)
        lines = source.splitlines()
        first = [n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "test_one"][0]
        after, claim = pac.claim_only_text(first, lines)
        self.assertTrue(claim.startswith("    assert "))
        self.assertIn("root", claim)
        seeded = "\n".join(lines[:after] + [claim] + lines[after:])
        ast.parse(seeded)                      # вставка не ломает разбор
        bodies = {n.name: len(n.body) for n in ast.walk(ast.parse(seeded))
                  if isinstance(n, ast.FunctionDef)}
        self.assertEqual(3, bodies["test_one"])
        self.assertEqual(2, bodies["test_two"])

    def test_the_insertion_goes_bottom_up_so_claims_do_not_drift(self):
        source = _battery_importing('''
            def test_one():
                a = 1
                assert a

            def test_two():
                b = 2
                assert b
        ''')
        tree = ast.parse(source)
        tests = sorted([n for n in ast.walk(tree)
                        if isinstance(n, ast.FunctionDef)
                        and n.name.startswith("test_")], key=lambda n: n.lineno)
        seeded = pac._seed_claims(source, tests)
        bodies = {n.name: [ast.unparse(s) for s in n.body]
                  for n in ast.walk(ast.parse(seeded))
                  if isinstance(n, ast.FunctionDef)}
        self.assertIn("a", bodies["test_one"][-1])
        self.assertIn("b", bodies["test_two"][-1])


class TheOutcomeOfARowIsDecidedByNamedPrecedence(unittest.TestCase):
    """Старшинство исходов НАЗВАНО и проверено по каждой ступени."""

    @staticmethod
    def _t(seed, flipped, reason=None):
        return pac.SeedTrial(battery=_BATTERY, seed=seed, door=pac.BY_MODULE,
                             flipped=flipped, reason=reason)

    def test_a_loose_detector_outranks_its_own_verdict(self):
        outcome, why = pac._verdict([self._t(pac.SEED_CANONICAL, True),
                                     self._t(pac.SEED_NO_LIVE, True)])
        self.assertEqual(pac.DETECTOR_LOOSE, outcome)
        self.assertIn(pac.DROPPED_CONJUNCT[pac.SEED_NO_LIVE], why)

    def test_a_canonical_seed_that_never_flips_is_detector_blind(self):
        outcome, why = pac._verdict([self._t(pac.SEED_CANONICAL, False)])
        self.assertEqual(pac.DETECTOR_BLIND, outcome)
        self.assertIn("не достаёт", why)

    def test_a_canonical_seed_never_measured_is_UNMEASURED_with_a_reason(self):
        outcome, why = pac._verdict(
            [self._t(pac.SEED_CANONICAL, None, "батарея не прочитана")])
        self.assertEqual(pac.UNMEASURED, outcome)
        self.assertIn("батарея не прочитана", why)

    def test_a_clean_flip_is_probe_absent(self):
        outcome, why = pac._verdict([self._t(pac.SEED_CANONICAL, True),
                                     self._t(pac.SEED_NO_LIVE, False),
                                     self._t(pac.SEED_NO_MEMBER, False),
                                     self._t(pac.SEED_NO_CALL, False)])
        self.assertEqual(pac.PROBE_ABSENT, outcome)
        self.assertIsNone(why)

    def test_the_precedence_is_declared_and_covers_every_outcome(self):
        self.assertEqual(set(pac.OUTCOMES), set(pac.PRECEDENCE))


class CalibrationRefusesInsteadOfPrintingANumber(unittest.TestCase):
    """Калибровка опровергнута ⇒ отказ, а не число (G1030 п. 2)."""

    def test_a_lost_known_flip_member_REFUSES_the_measurement(self):
        root = _tree({_SUBJECT: _INSTRUMENT, _BATTERY: "def test_x():\n    pass\n"})
        saved = dict(pac.CALIBRATION_FLIP)
        try:
            pac.CALIBRATION_FLIP.clear()
            pac.CALIBRATION_FLIP[_SUBJECT] = "сцена: батарея прибор НЕ ввозит"
            with self.assertRaises(pac.Refused) as caught:
                pac.calibrated_measure(root, [_SUBJECT])
            self.assertIn("КАЛИБРОВКА ОПРОВЕРГЛА", str(caught.exception))
        finally:
            pac.CALIBRATION_FLIP.clear()
            pac.CALIBRATION_FLIP.update(saved)

    def test_an_empty_subject_list_REFUSES_rather_than_printing_zero(self):
        with self.assertRaises(pac.Refused):
            pac.measure(_REPO, [])

    def test_every_calibration_member_names_its_reason(self):
        for rel, why in pac.CALIBRATION_FLIP.items():
            self.assertTrue(why.strip(), rel)
            self.assertTrue((_REPO / rel).exists(), rel)


class TheLiveTreeIsMeasuredAndKnownMembersAreShown(unittest.TestCase):
    """ЖИВОЕ дерево + ИЗВЕСТНЫЕ члены, названные НЕ из ответа прибора.

    Проба, без которой этот прибор сам был бы новым членом класса ADR-1041.
    Известные члены берутся У ИСТОЧНИКА — объявления соседа
    (`known_member_probe_baseline.json`), — а не копией перечня и не ответом
    прибора: копии нечем состариться вместе с источником.

    **Литерала пути ни одного члена в этом файле НЕТ намеренно, и это замер, а
    не вкус.** Батарея, назвавшая путь прибора строкой, СТАНОВИТСЯ его слабой
    дверью (`DOOR_PATH`), то есть файл менял бы ответ соседа о члене того самого
    класса, который мерит. Замерено этим циклом: с двумя литералами ярлык двери
    `delivery_name_loss` менялся `module` → `module+path`. Исход при этом не
    менялся, но ось дверей — да, и такой прибор о классе судил бы, стоя в нём.

    Замер дорогой и идёт ОДИН раз на класс: ответ о классе даёт только класс,
    подмножество отвечало бы на свой вопрос.

    **Порог времени ОБЪЯВЛЕН, а не поднят молча.** Замер на этой машине — **73 с**
    (134 батареи × 6 чтений читателем класса + 9 с на поиск батарей среди 2998
    файлов). Общий `--timeout=180` остаётся НЕ ТРОНУТЫМ (инв. #16 и заказ G1030
    п. 11): объявление стои́т у ОДНОГО класса, с измеренным числом и причиной, —
    иначе медленный, но верный замер попал бы в род стенных часов на более
    медленном раннере и читался бы как дефект кода (ровно та ротация, о которой
    G1030 п. 7). Та же форма и та же причина, что у `test_delta_mutation_run`.
    """

    pytestmark = pytest.mark.timeout(600)

    @classmethod
    def setUpClass(cls):
        cls.declared = json.loads((_REPO / _BASELINE).read_text(encoding="utf-8"))
        cls.sibling = json.loads(
            (_REPO / _SIBLING_BASELINE).read_text(encoding="utf-8"))
        cls.census = pac.calibrated_measure(
            _REPO, cls.sibling["members"], subjects_source=_SIBLING_BASELINE)
        cls.live = {row.rel: row for row in cls.census.rows}

    def _by(self, key: str, value: str) -> set[str]:
        return {rel for rel, row in self.live.items()
                if getattr(row, key) == value}

    def test_the_live_tree_answers_about_a_KNOWN_MEMBER_in_the_test_itself(self):
        """ЖИВОЙ зов стои́т ВНУТРИ теста — и это не вкус, а замер.

        Первая редакция держала зов в `setUpClass`, а тесты читали `self.census`.
        Читатель класса ADR-1041 засевает помощников, КОТОРЫХ ЗОВЁТ ТЕСТ, а
        фикстуру `setUpClass` тест не зовёт — поэтому пробы он не видел, и этот
        прибор ВЫШЕЛ НОВЫМ ЧЛЕНОМ класса, который мерит (замер: население соседа
        90 → 91, `no_probe` 46 → 47). Нашёл это не глаз, а прогон соседа.

        Перечень берётся У ИСТОЧНИКА и усечён НАМЕРЕННО: предмет пробы — «живой
        зов + названный член», а не цена полного замера; полный замер стои́т
        рядом, в `setUpClass`. Калибровочные приборы входят в срез ОБЯЗАТЕЛЬНО:
        без них `calibrated_measure` справедливо ОТКАЗЫВАЕТ («калибровочного
        прибора нет во входе») — замер, у которого нет известного члена, мерой
        не является, и усечение входа этого правила не отменяет.
        """
        declared = sorted(json.loads(
            (_REPO / _SIBLING_BASELINE).read_text(encoding="utf-8"))["members"])
        MEMBERS_DECLARED = sorted(set(pac.CALIBRATION_FLIP) | set(declared[:3]))
        self.assertTrue(MEMBERS_DECLARED, "объявление соседа ПУСТО")
        for member in MEMBERS_DECLARED:
            self.assertIn(member, declared)
        census = pac.calibrated_measure(_REPO, MEMBERS_DECLARED,
                                        subjects_source=_SIBLING_BASELINE)
        answered = {row.rel: row.outcome for row in census.rows}
        for member in MEMBERS_DECLARED:
            self.assertIn(member, answered)

    def test_every_KNOWN_MEMBER_of_the_declaration_is_answered_about(self):
        answered = set(self.live)
        MEMBERS_DECLARED = self.sibling["members"]
        self.assertTrue(MEMBERS_DECLARED, "объявление соседа ПУСТО")
        for member in MEMBERS_DECLARED:
            self.assertIn(member, answered)

    def test_every_live_row_carries_a_declared_outcome_and_a_distance(self):
        for row in self.census.rows:
            self.assertIn(row.outcome, pac.OUTCOMES, row.rel)
            self.assertIn(row.distance, pac.DISTANCES, row.rel)

    def test_both_live_axes_cover_the_live_population_exactly(self):
        self.assertEqual(self.census.population, sum(self.census.counts.values()))
        self.assertEqual(self.census.population, sum(self.census.distances.values()))
        self.assertEqual(self.census.population, sum(self.census.doors.values()))

    def test_every_door_label_of_the_declaration_is_seen_on_the_live_tree(self):
        for label, count in self.declared["doors_at_measure"].items():
            if count:
                self.assertIn(label, self.census.doors, label)

    def test_the_near_side_names_the_test_it_found(self):
        for rel in self._by("distance", pac.ONE_CLAIM_AWAY):
            self.assertTrue(self.live[rel].distance_test, rel)

    def test_this_battery_does_NOT_change_the_neighbours_answer(self):
        """Мой файл не вправе выводить члена из класса, который мерит."""
        sibling = km.measure(_REPO, self.sibling["members"],
                             surface_source=_SIBLING_BASELINE)
        self.assertEqual(len(self.sibling["members"]),
                         sibling.counts[km.NO_PROBE],
                         "батарея этого прибора изменила ответ соседа о классе")

    # ── храповик: объявленное разбиение убывает, расти ему запрещено (инв. #16)
    def test_no_name_appears_that_the_declaration_does_not_carry(self):
        unknown = sorted(set(self.live) - set(self.declared["rows"]))
        self.assertEqual([], unknown,
                         "в классе появилось имя, которого в объявлении нет — "
                         "дописывать его в базу ЗАПРЕЩЕНО (инв. #16)")

    def test_a_blind_detector_is_a_finding_because_the_declaration_has_none(self):
        declared = {rel for rel, row in self.declared["rows"].items()
                    if row["outcome"] == pac.DETECTOR_BLIND}
        self.assertEqual(set(), self._by("outcome", pac.DETECTOR_BLIND) - declared)

    def test_a_loose_detector_is_a_finding_because_the_declaration_has_none(self):
        declared = {rel for rel, row in self.declared["rows"].items()
                    if row["outcome"] == pac.DETECTOR_LOOSE}
        self.assertEqual(set(), self._by("outcome", pac.DETECTOR_LOOSE) - declared)

    def test_an_unmeasured_row_is_a_finding_because_the_declaration_has_none(self):
        declared = {rel for rel, row in self.declared["rows"].items()
                    if row["outcome"] == pac.UNMEASURED}
        self.assertEqual(set(), self._by("outcome", pac.UNMEASURED) - declared)

    def test_the_far_side_of_the_distance_axis_can_only_shrink(self):
        declared = {rel for rel, row in self.declared["rows"].items()
                    if row["distance"] == pac.NO_LIVE_CALL}
        arrived = sorted(self._by("distance", pac.NO_LIVE_CALL) - declared)
        self.assertEqual([], arrived,
                         "прибор ОТОДВИНУЛСЯ от пробы: живой зов, который был в "
                         "его батарее, исчез — это регрессия, а не новая строка базы")

    def test_the_declared_counts_still_describe_the_live_tree_or_shrink(self):
        for outcome in pac.OUTCOMES:
            self.assertLessEqual(
                self.census.counts[outcome],
                self.declared["counts_at_measure"][outcome], outcome)


class TheDeclarationCarriesItsOwnContract(unittest.TestCase):
    """База — ПЕРЕЧЕНЬ ИМЁН с исходом у каждого, а не число (урок ADR-912)."""

    @classmethod
    def setUpClass(cls):
        cls.declared = json.loads((_REPO / _BASELINE).read_text(encoding="utf-8"))
        cls.sibling = json.loads(
            (_REPO / _SIBLING_BASELINE).read_text(encoding="utf-8"))

    def test_the_declaration_names_every_field_it_promises(self):
        for key in ("schema", "_why", "measured_at", "measured_in",
                    "subjects_source", "population_at_measure",
                    "counts_at_measure", "distances_at_measure",
                    "doors_at_measure", "rows"):
            self.assertIn(key, self.declared)

    def test_the_declared_population_is_the_siblings_membership(self):
        self.assertEqual(sorted(self.declared["rows"]),
                         sorted(self.sibling["members"]))

    def test_every_declared_row_names_an_outcome_and_a_distance(self):
        for rel, row in self.declared["rows"].items():
            self.assertIn(row["outcome"], pac.OUTCOMES, rel)
            self.assertIn(row["distance"], pac.DISTANCES, rel)

    def test_the_declared_counts_agree_with_the_declared_rows(self):
        counts = {o: 0 for o in pac.OUTCOMES}
        distances = {d: 0 for d in pac.DISTANCES}
        for row in self.declared["rows"].values():
            counts[row["outcome"]] += 1
            distances[row["distance"]] += 1
        self.assertEqual(self.declared["counts_at_measure"], counts)
        self.assertEqual(self.declared["distances_at_measure"], distances)
        self.assertEqual(self.declared["population_at_measure"],
                         sum(counts.values()))

    def test_the_near_side_of_the_declaration_names_the_test_it_found(self):
        for rel, row in self.declared["rows"].items():
            if row["distance"] == pac.ONE_CLAIM_AWAY:
                self.assertTrue(row["near_test"], rel)

    def test_the_declaration_says_WHY_and_names_the_forbidden_move(self):
        why = " ".join(self.declared["_why"])
        self.assertIn("ТОЛЬКО УБЫВАТЬ", why)
        self.assertIn("ЗАПРЕЩЕНО", why)
