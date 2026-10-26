"""Контроль ЦЕНЫ штампа атрибуции (ADR-821, заказ G820 п. 1).

Предмет один: **достанется ли артефакту правка, сделанная ОДИН раз внутри общей
двери** (`spa_core.utils.atomic`), — или ему нужна своя. Каждый тест здесь
положительный контроль на КОНКРЕТНЫЙ способ соврать об этом, и три из них
воспроизводят ошибки, сделанные в самом цикле #945 при первом замере:

1. спросить у вызова ИМЯ без владельца — ``str.replace``/``datetime.replace``
   неотличимы от ``os.replace``, и помощник, внутри которого они стоят,
   получает «своя дверь»; цена завышается (замер: 12 артефактов за общей
   дверью против 153 при верном разборе);
2. остановить разбор помощников на ПЕРВОМ шаге — две трети локальных
   ``_atomic_write*`` зовут ``atomic_save`` сами, и без неподвижной точки они
   все читаются своей дверью (142 против 153);
3. сложить «дверь не разобрана» с «дверь своя» — то есть выдать НЕ ИЗМЕРЕНО за
   ответ; и симметрично — свернуть путь артефакта к ИМЕНИ ФАЙЛА, после чего
   шесть разных `status.json` конституции получают двери друг друга.

Литеральных дат в наборе нет: предмет статический (разбор кода), часов он не
спрашивает вовсе.
"""
from __future__ import annotations

import ast
import json
import sys
import tempfile
import unittest
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.monitoring import artifact_io_scan as ios  # noqa: E402
from spa_core.monitoring import slo_keepability as sk  # noqa: E402
from spa_core.monitoring import slo_proposal as sp  # noqa: E402


class WriteDoorsTell(unittest.TestCase):
    """Разбор двери: чем модуль пишет артефакт."""

    def test_a_direct_call_to_the_shared_door_is_shared(self):
        src = ('from spa_core.utils.atomic import atomic_save\n'
               'NAME = "data/x.json"\n'
               'def go(d):\n'
               '    atomic_save(d, NAME)\n')
        self.assertEqual(ios.write_doors(src), {"data/x.json": {ios.DOOR_SHARED}})

    def test_a_local_helper_that_reaches_the_shared_door_is_ALSO_shared(self):
        """Способ №2 соврать: остановиться на первом шаге разбора."""
        src = ('from spa_core.utils.atomic import atomic_save\n'
               'NAME = "data/x.json"\n'
               'def _atomic_write_json(d, p):\n'
               '    atomic_save(d, p)\n'
               'def go(d):\n'
               '    _atomic_write_json(d, NAME)\n')
        self.assertEqual(ios.write_doors(src)["data/x.json"], {ios.DOOR_SHARED})

    def test_a_helper_chain_of_two_hops_still_reaches_the_shared_door(self):
        src = ('from spa_core.utils.atomic import atomic_save\n'
               'NAME = "data/x.json"\n'
               'def _really(d, p):\n'
               '    atomic_save(d, p)\n'
               'def _middle(d, p):\n'
               '    _really(d, p)\n'
               'def go(d):\n'
               '    _middle(d, NAME)\n')
        self.assertEqual(ios.write_doors(src)["data/x.json"], {ios.DOOR_SHARED})

    def test_a_helper_with_its_OWN_atomic_write_is_its_own_door(self):
        src = ('import os, tempfile\n'
               'NAME = "data/x.json"\n'
               'def _atomic_write(d, p):\n'
               '    fd, tmp = tempfile.mkstemp()\n'
               '    os.replace(tmp, p)\n'
               'def go(d):\n'
               '    _atomic_write(d, NAME)\n')
        self.assertEqual(ios.write_doors(src)["data/x.json"], {ios.DOOR_OWN})

    def test_a_bare_str_replace_is_NOT_a_write_door(self):
        """Способ №1 соврать — и это ошибка самого цикла #945.

        `str.replace` и `datetime.replace` по ИМЕНИ неотличимы от `os.replace`.
        Сцена писала бы артефакт общей дверью, а помощник рядом чистит строку:
        если спрашивать имя без владельца, артефакт получает «своя дверь» и
        цена штампа завышается.
        """
        src = ('from spa_core.utils.atomic import atomic_save\n'
               'NAME = "data/x.json"\n'
               'def _slug(raw):\n'
               '    return raw.replace(" ", "-")\n'
               'def go(d):\n'
               '    atomic_save({"k": _slug("a b")}, NAME)\n')
        self.assertEqual(ios.write_doors(src)["data/x.json"], {ios.DOOR_SHARED},
                         "str.replace прочитан как дверь записи — ошибка #945")

    def test_a_datetime_replace_inside_the_writer_is_NOT_a_write_door(self):
        src = ('import datetime as dt\n'
               'from spa_core.utils.atomic import atomic_save\n'
               'NAME = "data/x.json"\n'
               'def _midnight(moment):\n'
               '    return moment.replace(hour=0)\n'
               'def _write(d, p):\n'
               '    d["t"] = _midnight(dt.datetime.now())\n'
               '    atomic_save(d, p)\n'
               'def go(d):\n'
               '    _write(d, NAME)\n')
        self.assertEqual(ios.write_doors(src)["data/x.json"], {ios.DOOR_SHARED})

    def test_a_dump_on_SOMEONE_ELSES_object_is_not_a_write_door(self):
        """Выжившая мутация первого прогона #945: голое `.dump()` — не дверь.

        `dump` носят numpy, joblib, свои сериализаторы и просто методы классов.
        Признав их дверью, перепись объявила бы «своя правка нужна» модулю,
        который на диск не пишет вовсе, — то есть завысила бы цену именем.
        """
        src = ('from spa_core.utils.atomic import atomic_save\n'
               'NAME = "data/x.json"\n'
               'def go(d, model):\n'
               '    model.dump(NAME)\n'
               '    atomic_save(d, NAME)\n')
        self.assertEqual(ios.write_doors(src)["data/x.json"], {ios.DOOR_SHARED},
                         "чужой .dump() прочитан как дверь записи")

    def test_a_json_dump_IS_a_write_door_so_the_guard_is_not_blanket(self):
        src = ('import json\n'
               'NAME = "data/x.json"\n'
               'def go(d, fh):\n'
               '    json.dump(d, NAME)\n')
        self.assertEqual(ios.write_doors(src)["data/x.json"], {ios.DOOR_OWN})

    def test_an_os_replace_IS_a_write_door_so_the_guard_is_not_blanket(self):
        """Контроль в ОБРАТНУЮ сторону: владелец `os` — настоящая своя дверь."""
        src = ('import os\n'
               'NAME = "data/x.json"\n'
               'def go(tmp):\n'
               '    os.replace(tmp, NAME)\n')
        self.assertEqual(ios.write_doors(src)["data/x.json"], {ios.DOOR_OWN})

    def test_a_helper_that_does_BOTH_is_own_because_own_is_stronger(self):
        src = ('import os\n'
               'from spa_core.utils.atomic import atomic_save\n'
               'NAME = "data/x.json"\n'
               'def _write(d, p, fast):\n'
               '    if fast:\n'
               '        atomic_save(d, p)\n'
               '    else:\n'
               '        os.replace(p + ".tmp", p)\n'
               'def go(d):\n'
               '    _write(d, NAME, True)\n')
        self.assertEqual(ios.write_doors(src)["data/x.json"], {ios.DOOR_OWN})

    def test_a_helper_defined_ELSEWHERE_is_unresolved_not_own_and_not_shared(self):
        src = ('from spa_core.helpers import _atomic_write_json\n'
               'NAME = "data/x.json"\n'
               'def go(d):\n'
               '    _atomic_write_json(d, NAME)\n')
        self.assertEqual(ios.write_doors(src)["data/x.json"], {ios.DOOR_UNRESOLVED})

    def test_broken_syntax_claims_nothing(self):
        self.assertEqual(ios.write_doors("def go(:\n"), {})

    def test_the_resolver_is_the_NEIGHBOURS_not_a_second_copy(self):
        """Одно имя — один объект: своя копия разрешателя была бы вторым.

        Меряется AST: `write_doors` обязана звать имена соседа, а не нести
        собственные определения `_name_table`/`_names_in`/`_scopes`.
        """
        tree = ast.parse(Path(ios.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in tree.body
                  if isinstance(n, ast.FunctionDef) and n.name == "write_doors")
        called = {n.func.id for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        for name in ("_name_table", "_names_in", "_scopes", "_own_nodes"):
            self.assertIn(name, called, f"{name} не позван — разбор пути свой")
        defined = [n.name for n in tree.body
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
        self.assertEqual(len([n for n in defined if n == "_name_table"]), 1)


class ThePriceVerdict(unittest.TestCase):
    """Шесть исходов двери `write_stamp_price`, и ни один не сливается."""

    def test_all_writers_shared_and_an_object_root_costs_ONE_edit(self):
        kind, why = sp.write_stamp_price({ios.DOOR_SHARED}, sp.CARRIER_OBJECT)
        self.assertEqual(kind, sp.STAMP_ONE_EDIT)
        self.assertIn("ОДНОЙ правки", why)

    def test_one_writer_with_its_own_door_costs_its_OWN_edit(self):
        kind, _ = sp.write_stamp_price({ios.DOOR_SHARED, ios.DOOR_OWN},
                                       sp.CARRIER_OBJECT)
        self.assertEqual(kind, sp.STAMP_OWN_EDIT_NEEDED)

    def test_own_is_asked_BEFORE_the_carrier_so_a_majority_cannot_win(self):
        """Обратный порядок ответил бы «дешевле» по большинству писателей."""
        kind, _ = sp.write_stamp_price({ios.DOOR_SHARED, ios.DOOR_OWN}, "list")
        self.assertEqual(kind, sp.STAMP_OWN_EDIT_NEEDED)

    def test_a_shared_door_over_a_root_that_cannot_hold_is_its_own_outcome(self):
        kind, why = sp.write_stamp_price({ios.DOOR_SHARED}, "list")
        self.assertEqual(kind, sp.STAMP_CARRIER_CANNOT_HOLD)
        self.assertIn("НЕКУДА", why)

    def test_no_writer_found_is_not_the_same_as_a_door_unmeasured(self):
        found, _ = sp.write_stamp_price(set(), sp.CARRIER_OBJECT)
        unmeasured, _ = sp.write_stamp_price({ios.DOOR_UNRESOLVED}, sp.CARRIER_OBJECT)
        self.assertEqual(found, sp.STAMP_WRITER_NOT_FOUND)
        self.assertEqual(unmeasured, sp.STAMP_PRICE_UNMEASURED)
        self.assertNotEqual(found, unmeasured)

    def test_writer_not_found_does_NOT_claim_the_writer_does_not_exist(self):
        _kind, why = sp.write_stamp_price(set(), sp.CARRIER_OBJECT)
        self.assertIn("НЕ следует", why)

    def test_a_contested_name_is_asked_FIRST_and_claims_nothing(self):
        """Способ №3 соврать: свернуть путь к имени файла.

        Шесть разных `status.json` конституции получили бы двери друг друга, и
        вердикт «своя правка» был бы напечатан про файл, которого тот писатель
        не трогает.
        """
        kind, why = sp.write_stamp_price({ios.DOOR_OWN}, sp.CARRIER_OBJECT,
                                         name_contested=True)
        self.assertEqual(kind, sp.STAMP_NAME_CONTESTED)
        self.assertIn("не один файл", why)

    def test_an_unmeasured_carrier_is_not_read_as_a_carrier_that_cannot_hold(self):
        kind, _ = sp.write_stamp_price({ios.DOOR_SHARED}, None)
        self.assertEqual(kind, sp.STAMP_PRICE_UNMEASURED)

    def test_an_unmeasured_contest_flag_refuses_rather_than_guessing(self):
        kind, _ = sp.write_stamp_price({ios.DOOR_SHARED}, sp.CARRIER_OBJECT,
                                        name_contested="возможно")
        self.assertEqual(kind, sp.STAMP_PRICE_UNMEASURED)

    def test_a_string_instead_of_a_door_set_is_UNMEASURED_not_a_verdict(self):
        kind, _ = sp.write_stamp_price("shared", sp.CARRIER_OBJECT)
        self.assertEqual(kind, sp.STAMP_PRICE_UNMEASURED)

    def test_every_outcome_has_its_OWN_words(self):
        seen = {
            sp.write_stamp_price({ios.DOOR_SHARED}, sp.CARRIER_OBJECT)[1],
            sp.write_stamp_price({ios.DOOR_SHARED}, "list")[1],
            sp.write_stamp_price({ios.DOOR_OWN}, sp.CARRIER_OBJECT)[1],
            sp.write_stamp_price(set(), sp.CARRIER_OBJECT)[1],
            sp.write_stamp_price({ios.DOOR_UNRESOLVED}, sp.CARRIER_OBJECT)[1],
            sp.write_stamp_price({ios.DOOR_OWN}, sp.CARRIER_OBJECT,
                                  name_contested=True)[1],
        }
        self.assertEqual(len(seen), 6)


class TheCarrierRoot(unittest.TestCase):
    """Второе условие цены — есть ли куда положить отметку."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_an_object_root_can_hold_the_stamp(self):
        p = self.dir / "a.json"
        p.write_text(json.dumps({"k": 1}), encoding="utf-8")
        self.assertEqual(sk.carrier_root(p)[0], sp.CARRIER_OBJECT)

    def test_an_array_root_cannot(self):
        p = self.dir / "a.json"
        p.write_text(json.dumps([1, 2]), encoding="utf-8")
        kind, why = sk.carrier_root(p)
        self.assertEqual(kind, "list")
        self.assertIn("некуда", why)

    def test_a_line_ledger_has_no_top_level_document_at_all(self):
        p = self.dir / "a.jsonl"
        p.write_text('{"k": 1}\n', encoding="utf-8")
        self.assertEqual(sk.carrier_root(p)[0], "лента строк")

    def test_an_absent_carrier_is_UNMEASURED_not_unable(self):
        kind, why = sk.carrier_root(self.dir / "missing.json")
        self.assertIsNone(kind)
        self.assertIn("не измерен", why)

    def test_an_unparsable_carrier_is_UNMEASURED_not_unable(self):
        p = self.dir / "a.json"
        p.write_text("{не json", encoding="utf-8")
        kind, why = sk.carrier_root(p)
        self.assertIsNone(kind)
        self.assertIn("НЕ ИЗМЕРЕН", why)


def _tree(root: Path, files: dict) -> None:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


def _agent(label: str, artifact: str) -> dict:
    return {"label": label, "intent": "active",
            "produces": [{"artifact": artifact, "slo_hours": 24}]}


_FIFTH_OK = {"status": "OK", "rows": [{"artifact": "data/x.json",
                                       "home": "co_produced",
                                       "attribution": sp.ATTRIBUTION_ABSENT}]}


class TheCensus(unittest.TestCase):
    """Перепись: цена по всей конституции и у НАСЕЛЕНИЯ ВОПРОСА."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.data = self.root / "data"
        self.data.mkdir()
        self.addCleanup(self._tmp.cleanup)

    def test_a_shared_door_artifact_is_counted_as_one_edit(self):
        _tree(self.root, {"spa_core/w.py": (
            'from spa_core.utils.atomic import atomic_save\n'
            'def go(d):\n'
            '    atomic_save(d, "data/x.json")\n')})
        (self.data / "x.json").write_text("{}", encoding="utf-8")
        doc = sk.write_stamp_price_census(
            _FIFTH_OK, [_agent("a", "data/x.json")], self.root, self.data)
        self.assertEqual(doc["status"], "OK")
        self.assertEqual(doc["inventory"], {sp.STAMP_ONE_EDIT: 1})

    def test_an_own_door_artifact_NAMES_the_modules_that_need_the_edit(self):
        _tree(self.root, {"spa_core/w.py": (
            'import os\n'
            'def go(tmp):\n'
            '    os.replace(tmp, "data/x.json")\n')})
        (self.data / "x.json").write_text("{}", encoding="utf-8")
        doc = sk.write_stamp_price_census(
            _FIFTH_OK, [_agent("a", "data/x.json")], self.root, self.data)
        self.assertEqual(doc["inventory"], {sp.STAMP_OWN_EDIT_NEEDED: 1})
        self.assertEqual(doc["price_modules"], 1)
        self.assertEqual(doc["rows"][0]["own_writers"], ["spa_core/w.py"])

    def test_a_contested_basename_does_NOT_borrow_a_neighbours_door(self):
        """Положительный контроль на дефект, найденный в цикле #945.

        Два артефакта конституции носят имя `status.json`; у двери видно
        только имя. Свернув путь к имени, перепись объявила бы ОБА своей
        дверью — то есть напечатала бы цену про файл, которого писатель не
        трогает.
        """
        _tree(self.root, {"spa_core/w.py": (
            'import os\n'
            'NAME = "status.json"\n'
            'def go(tmp):\n'
            '    os.replace(tmp, NAME)\n')})
        for rel in ("one/status.json", "two/status.json"):
            path = self.data / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        doc = sk.write_stamp_price_census(
            _FIFTH_OK,
            [_agent("a", "data/one/status.json"), _agent("b", "data/two/status.json")],
            self.root, self.data)
        self.assertEqual(doc["inventory"], {sp.STAMP_NAME_CONTESTED: 2})
        self.assertTrue(all(not r["resolved_exactly"] for r in doc["rows"]))

    def test_an_EXACT_full_path_literal_wins_over_the_contested_name(self):
        """Контроль в обратную сторону: точное разрешение не глушится спором."""
        _tree(self.root, {"spa_core/w.py": (
            'from spa_core.utils.atomic import atomic_save\n'
            'def go(d):\n'
            '    atomic_save(d, "data/one/status.json")\n'),
            "spa_core/v.py": (
            'import os\n'
            'def go(tmp):\n'
            '    os.replace(tmp, "status.json")\n')})
        for rel in ("one/status.json", "two/status.json"):
            path = self.data / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("{}", encoding="utf-8")
        doc = sk.write_stamp_price_census(
            _FIFTH_OK,
            [_agent("a", "data/one/status.json"), _agent("b", "data/two/status.json")],
            self.root, self.data)
        rows = {r["artifact"]: r for r in doc["rows"]}
        self.assertEqual(rows["data/one/status.json"]["price"], sp.STAMP_ONE_EDIT)
        self.assertTrue(rows["data/one/status.json"]["resolved_exactly"])
        self.assertEqual(rows["data/two/status.json"]["price"], sp.STAMP_NAME_CONTESTED)

    def test_an_unreadable_code_tree_is_UNMEASURED_not_231_missing_writers(self):
        """fail-OPEN тише красного: пустой словарь дал бы «писателя нет» всем."""
        doc = sk.write_stamp_price_census(
            _FIFTH_OK, [_agent("a", "data/x.json")], self.root / "нет", self.data)
        self.assertEqual(doc["status"], sp.STAMP_PRICE_UNMEASURED)
        self.assertIn("НЕ ИЗМЕРЕНЫ", doc["cause"])
        self.assertIsNone(doc["inventory"])

    def test_a_constitution_without_artifacts_is_UNMEASURED_not_clean(self):
        _tree(self.root, {"spa_core/w.py": "x = 1\n"})
        doc = sk.write_stamp_price_census(_FIFTH_OK, [], self.root, self.data)
        self.assertEqual(doc["status"], sp.STAMP_PRICE_UNMEASURED)

    def test_the_population_is_taken_from_the_FIFTH_section_by_reference(self):
        _tree(self.root, {"spa_core/w.py": (
            'from spa_core.utils.atomic import atomic_save\n'
            'def go(d):\n'
            '    atomic_save(d, "data/x.json")\n')})
        (self.data / "x.json").write_text("{}", encoding="utf-8")
        doc = sk.write_stamp_price_census(
            _FIFTH_OK, [_agent("a", "data/x.json")], self.root, self.data)
        self.assertEqual(doc["population"], 1)
        self.assertEqual(doc["population_rows"][0]["price"], sp.STAMP_ONE_EDIT)
        self.assertEqual(doc["tally"], {sp.STAMP_ONE_EDIT: 1})

    def test_a_fifth_section_that_REFUSED_leaves_the_population_UNMEASURED(self):
        """«НЕ ИЗМЕРЕНО» пятой не превращается в ноль шестой."""
        _tree(self.root, {"spa_core/w.py": (
            'from spa_core.utils.atomic import atomic_save\n'
            'def go(d):\n'
            '    atomic_save(d, "data/x.json")\n')})
        (self.data / "x.json").write_text("{}", encoding="utf-8")
        doc = sk.write_stamp_price_census(
            {"status": sp.ATTRIBUTION_UNMEASURED, "cause": "каталог не прочитан"},
            [_agent("a", "data/x.json")], self.root, self.data)
        self.assertEqual(doc["status"], "OK")
        self.assertIsNone(doc["population"])
        self.assertIn("НЕ ИЗМЕРЕНО", doc["population_cause"])
        self.assertEqual(doc["tally"], {})

    def test_the_finding_is_the_artifact_that_LOOKS_covered_and_is_not(self):
        _tree(self.root, {"spa_core/w.py": (
            'from spa_core.utils.atomic import atomic_save\n'
            'def go(d):\n'
            '    atomic_save(d, "data/x.json")\n')})
        (self.data / "x.json").write_text("[]", encoding="utf-8")
        doc = sk.write_stamp_price_census(
            _FIFTH_OK, [_agent("a", "data/x.json")], self.root, self.data)
        self.assertEqual([r["artifact"] for r in doc["findings"]], ["data/x.json"])

    def test_an_own_door_artifact_is_NOT_a_finding_because_price_is_not_a_defect(self):
        _tree(self.root, {"spa_core/w.py": (
            'import os\n'
            'def go(tmp):\n'
            '    os.replace(tmp, "data/x.json")\n')})
        (self.data / "x.json").write_text("{}", encoding="utf-8")
        doc = sk.write_stamp_price_census(
            _FIFTH_OK, [_agent("a", "data/x.json")], self.root, self.data)
        self.assertEqual(doc["findings"], [])


class TheTreeSnapshot(unittest.TestCase):
    """Слепок обхода: быстро и БЕЗ ответа о дереве, которого уже нет."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_a_tree_EDITED_after_the_first_scan_is_scanned_again(self):
        """Положительный контроль на ключ по ОДНОМУ пути.

        Такой ключ отвечал бы о дереве, каким оно было при первом зове, —
        то есть утверждал бы о моменте, которого замер уже не видит.
        """
        _tree(self.root, {"spa_core/w.py": (
            'from spa_core.utils.atomic import atomic_save\n'
            'def go(d):\n'
            '    atomic_save(d, "data/x.json")\n')})
        first, _ = sk.write_doors_by_artifact(self.root)
        self.assertEqual(first["data/x.json"], {ios.DOOR_SHARED})
        _tree(self.root, {"spa_core/w.py": (
            'import os\n'
            'def go(tmp):\n'
            '    os.replace(tmp, "data/x.json")\n')})
        second, _ = sk.write_doors_by_artifact(self.root)
        self.assertEqual(second["data/x.json"], {ios.DOOR_OWN},
                         "слепок вернул ответ о дереве, которого уже нет")

    def test_two_different_trees_do_not_share_one_answer(self):
        other = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: None)
        _tree(self.root, {"spa_core/w.py": (
            'from spa_core.utils.atomic import atomic_save\n'
            'def go(d):\n'
            '    atomic_save(d, "data/x.json")\n')})
        _tree(other, {"spa_core/w.py": (
            'import os\n'
            'def go(tmp):\n'
            '    os.replace(tmp, "data/x.json")\n')})
        mine, _ = sk.write_doors_by_artifact(self.root)
        theirs, _ = sk.write_doors_by_artifact(other)
        self.assertEqual(mine["data/x.json"], {ios.DOOR_SHARED})
        self.assertEqual(theirs["data/x.json"], {ios.DOOR_OWN})

    def test_a_tree_without_the_code_folders_is_UNMEASURED(self):
        self.assertEqual(sk.write_doors_by_artifact(self.root / "нет"), (None, None))


class TheReader(unittest.TestCase):
    """Строка обязана быть в выводе, который цикл ЧИТАЕТ (урок ADR-820)."""

    def test_the_line_is_PRESENT_in_the_report_document(self):
        """Зов переписи и её ПРИСУТСТВИЕ в документе — разные утверждения.

        Ровно эта мутация выжила в цикле #944: перепись считалась, а секция
        попадала в документ под другим именем, и строка честно печатала «НЕ
        ИЗМЕРЕНО», не падая ни одним тестом.
        """
        doc = {"status": "OK", "declared_write_stamp_price": {
            "status": "OK", "inventory": {sp.STAMP_ONE_EDIT: 153,
                                          sp.STAMP_OWN_EDIT_NEEDED: 32},
            "inventory_population": 231, "population": 9,
            "price_modules": 33, "tally": {sp.STAMP_ONE_EDIT: 6},
            "findings": [], "rows": []}}
        line = sk.write_stamp_price_line(doc)
        self.assertIn("153", line)
        self.assertIn("ADR-821", line)
        lines = [ln for ln in sk.report(doc) if "цена штампа" in ln]
        self.assertEqual(len(lines), 1, "строки нет в выводе шага 0-офис")

    def test_the_REAL_measure_puts_the_section_under_the_name_the_line_reads(self):
        """Выжившая мутация #944 — и она выжила ЗДЕСЬ ЖЕ при первом прогоне.

        Проверять документ, собранный руками, значит проверять СВОЙ словарь, а
        не проводку: переименуй `measure` ключ секции — перепись всё равно
        считается, строка честно печатает «НЕ ИЗМЕРЕНО: секции нет», и не падает
        НИ ОДИН тест. Поэтому здесь поднимается настоящий `measure` на
        одноразовой конституции, и спрашивается именно ПРИСУТСТВИЕ.
        """
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "architecture").mkdir(parents=True)
        (root / "logs").mkdir()
        (root / "scripts").mkdir()
        data = root / "data"
        data.mkdir()
        (data / "x.json").write_text("{}", encoding="utf-8")
        _tree(root, {"spa_core/w.py": (
            'from spa_core.utils.atomic import atomic_save\n'
            'def go(d):\n'
            '    atomic_save(d, "data/x.json")\n')})
        manifest = root / "architecture" / "manifest.json"
        manifest.write_text(json.dumps({"agents": [
            {"label": "com.spa.a", "intent": "active", "schedule": "interval:3600s",
             "program": "agent_a.sh",
             "produces": [{"artifact": "data/x.json", "slo_hours": 24}]}],
            "artifacts": []}, ensure_ascii=False), encoding="utf-8")
        doc = sk.measure(manifest, log_dir=root / "logs",
                         scripts_dir=root / "scripts", root=root, data_dir=data)
        self.assertIn("declared_write_stamp_price", doc,
                      "секция попала в документ под другим именем")
        line = sk.write_stamp_price_line(doc)
        self.assertNotIn("секции", line)
        self.assertIn("хватило бы 1", line)

    def test_a_document_written_BEFORE_the_section_renders_as_НЕ_ИЗМЕРЕНО(self):
        line = sk.write_stamp_price_line({"status": "OK"})
        self.assertIn("НЕ ИЗМЕРЕНО", line)

    def test_a_refused_section_renders_its_CAUSE_not_zeroes(self):
        line = sk.write_stamp_price_line({"declared_write_stamp_price": {
            "status": sp.STAMP_PRICE_UNMEASURED, "cause": "каталога кода нет"}})
        self.assertIn("каталога кода нет", line)
        self.assertNotIn("хватило бы 0", line)

    def test_an_unmeasured_population_prints_НЕ_ИЗМЕРЕНО_not_zero(self):
        line = sk.write_stamp_price_line({"declared_write_stamp_price": {
            "status": "OK", "inventory": {}, "inventory_population": 231,
            "population": None, "price_modules": 0, "tally": {},
            "findings": [], "rows": []}})
        self.assertIn("НЕ ИЗМЕРЕНО", line)

    def test_the_section_is_computed_ONCE_and_fed_the_fifth_by_reference(self):
        """AST: пятая перепись зовётся один раз и подаётся шестой входом."""
        tree = ast.parse(Path(sk.__file__).read_text(encoding="utf-8"))
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "measure")
        calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)]
        names = [n.func.id for n in calls]
        self.assertEqual(names.count("write_attribution_census"), 1,
                         "пятая перепись считается дважды — два ответа на один вопрос")
        self.assertEqual(names.count("write_stamp_price_census"), 1)
        sixth = next(n for n in calls if n.func.id == "write_stamp_price_census")
        self.assertTrue(any(isinstance(a, ast.Name) and a.id == "_attribution_section"
                            for a in sixth.args),
                        "шестой секции не подан результат пятой")

    def test_the_section_does_not_enter_the_tally_or_the_verdict(self):
        """Заказ G815 п. 2: оси не сводятся ни одним числом."""
        source = Path(sk.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef) and n.name == "measure")
        for node in ast.walk(fn):
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name) \
                    and node.value.id == "tally":
                literal = ast.dump(node.slice)
                self.assertNotIn("stamp", literal.lower())


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
