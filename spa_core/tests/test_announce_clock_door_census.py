"""Батарея прибора `announce_clock_door_census` (заказ G110 п. 3, ADR-682).

Каждый тест — положительный контроль на НАЗВАННОЕ звено: у каждой проверки есть
обратная сторона, и порванное звено названо прямо в имени теста. Сцены
одноразовые (`mkdtemp`), живое дерево не трогается ни на байт.

# FROZEN-DATE-OK: литерал — САМ ПРЕДМЕТ замера. Отметка
# `2026-10-02T05:07:31.286040` есть дословная форма, на которой заказ ADR-535 п. 3
# измерил отказ двери; свежести здесь не судит ни один тест, а момент-якорь идёт
# ВХОДОМ (`anchor=`) всюду, где он нужен.
"""

from __future__ import annotations

import ast
import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import announce_clock_door_census as M

#: Момент-якорь сцен. Передаётся ВХОДОМ; стенных часов в файле нет ни одних.
NOW = datetime(2026, 10, 2, 5, 7, 31, 286040, tzinfo=timezone.utc)

#: Форма, которую принимает настоящая дверь-эталон.
SEC = NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
#: Форма из заказа — ровно та, на которой эталон отказывает.
MICRO = NOW.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def strict(value):
    """Дверь-эталон сцены: принимает ТОЛЬКО секундную форму (как настоящая)."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return None


def lenient(value):
    """Широкая дверь сцены: ISO целиком, включая микросекунды."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def everything(value):
    """Дверь, принимающая ВСЁ, включая не-строку — оракул для оси B."""
    return value if value is not None else None


def _mod(**names):
    """Подставной модуль: объект с объявленными именами."""
    return type("_Scene", (), dict(names))


def _resolve(expr_src: str, *, consts=None, helpers_src: str = ""):
    """Разобрать выражение отметки сцены → результат `resolve_form`."""
    tree = ast.parse(helpers_src + "\n_v = " + expr_src)
    value = next(n.value for n in ast.walk(tree)
                 if isinstance(n, ast.Assign)
                 and any(getattr(t, "id", None) == "_v" for t in n.targets))
    return M.resolve_form(value, consts or M._module_consts(tree),
                          M._single_return_helpers(tree))


def _writers_of(source: str, *, filename="prod_writer.py", guard=strict):
    """Ось B на одном файле-сцене."""
    root = Path(tempfile.mkdtemp(prefix="acdc_w_"))
    path = root / filename
    path.write_text(source, encoding="utf-8")
    return M.measure_writers(root, files=[path], guard_fn=guard, anchor=NOW)


# ───────────────────────────── словарь форм ─────────────────────────────────

class TestFormDictionary(unittest.TestCase):

    def test_dictionary_covers_exactly_the_declared_names(self):
        forms = M.forms_at(NOW)
        self.assertEqual(set(forms), set(M.FORM_NAMES))

    def test_a_name_declared_but_not_built_is_a_loud_failure(self):
        """Порванное звено: перечень объявлен шире сборки ⇒ громкий отказ.

        Иначе доля принятых форм считалась бы от знаменателя, которого нет.
        """
        original = M.FORM_NAMES
        M.FORM_NAMES = original + ("forma_kotoroy_net",)
        try:
            with self.assertRaises(AssertionError):
                M.forms_at(NOW)
        finally:
            M.FORM_NAMES = original

    def test_micros_form_is_literally_the_form_the_order_measured(self):
        self.assertEqual(M.forms_at(NOW)["micros_z"], "2026-10-02T05:07:31.286040Z")

    def test_the_moment_is_an_input_not_the_wall_clock(self):
        """Порванное звено: якорь взят у стенных часов ⇒ формы перестали зависеть от входа."""
        other = NOW + timedelta(days=400)
        self.assertNotEqual(M.forms_at(NOW)["seconds_z"], M.forms_at(other)["seconds_z"])

    def test_the_canonical_form_is_one_of_the_declared_names(self):
        self.assertIn(M.CANONICAL_FORM, M.FORM_NAMES)


# ───────────────────── ось A: вердикт двери по ИСХОДУ ───────────────────────

class TestAcceptance(unittest.TestCase):

    def test_each_declared_form_gets_a_verdict(self):
        verdicts = M.acceptance_of(strict, M.forms_at(NOW))
        self.assertEqual(set(verdicts), set(M.FORM_NAMES))

    def test_strict_door_accepts_only_seconds(self):
        verdicts = M.acceptance_of(strict, M.forms_at(NOW))
        self.assertEqual(verdicts["seconds_z"], M.V_ACCEPT)
        self.assertEqual(verdicts["micros_z"], M.V_REFUSE)

    def test_a_raising_door_is_its_own_outcome_not_a_refusal(self):
        """Порванное звено: исключение свёрнуто в `refused`.

        Дверь, падающая на форме, и дверь, вернувшая None, ведут себя у
        вызывающего ПО-РАЗНОМУ, и склейка спрятала бы первое за вторым.
        """
        def explodes(value):
            raise RuntimeError("дверь упала")
        verdicts = M.acceptance_of(explodes, M.forms_at(NOW))
        self.assertTrue(verdicts["seconds_z"].startswith(M.V_RAISED + ":"))
        self.assertIn("RuntimeError", verdicts["seconds_z"])
        self.assertNotEqual(verdicts["seconds_z"], M.V_REFUSE)


class TestDoorClassification(unittest.TestCase):

    GUARD = frozenset({"seconds_z"})

    def test_identical_set_agrees(self):
        self.assertEqual(M.classify_door(frozenset({"seconds_z"}), self.GUARD),
                         M.DOOR_AGREES)

    def test_strict_superset_is_wider(self):
        self.assertEqual(
            M.classify_door(frozenset({"seconds_z", "micros_z"}), self.GUARD),
            M.DOOR_WIDER)

    def test_strict_subset_is_narrower(self):
        self.assertEqual(
            M.classify_door(frozenset({"seconds_z"}), frozenset({"seconds_z", "micros_z"})),
            M.DOOR_NARROWER)

    def test_crossing_set_is_neither_wider_nor_narrower(self):
        self.assertEqual(
            M.classify_door(frozenset({"seconds_z", "micros_z"}),
                            frozenset({"seconds_z", "naive_seconds"})),
            M.DOOR_CROSSING)

    def test_a_door_refusing_the_canonical_form_is_not_a_door_of_this_field(self):
        """Отсев ИЗМЕРЕНИЕМ, а не догадкой по имени функции.

        Так отпадает, например, разбор даты приказа `%Y-%m-%d`: он честно
        отказывает всем формам отметки, и записывать его в двери поля было бы
        выдумкой.
        """
        self.assertEqual(M.classify_door(frozenset({"naive_seconds"}), self.GUARD),
                         M.DOOR_FOREIGN)

    def test_every_class_is_in_the_closed_list(self):
        for accepted in (frozenset({"seconds_z"}), frozenset({"seconds_z", "micros_z"}),
                         frozenset(), frozenset({"micros_z"})):
            self.assertIn(M.classify_door(accepted, self.GUARD), M.DOOR_CLASSES)


class TestMeasureDoors(unittest.TestCase):

    def _loader(self, table):
        def load(path, label):
            if path not in table:
                raise ImportError(f"сцена не объявила модуль {path}")
            value = table[path]
            if isinstance(value, Exception):
                raise value
            return value
        return load

    def test_guard_that_does_not_load_leaves_the_whole_axis_unmeasured(self):
        """Порванное звено: эталон не загрузился, а перечень дверей всё равно выдан."""
        out = M.measure_doors(Path("/nonexistent"), anchor=NOW,
                              candidates=[("x.py", "_parse_ts", 1)],
                              loader=self._loader({M.GUARD_DOOR[0]: ImportError("нет файла")}))
        self.assertFalse(out["measured"])
        self.assertIn("не загружена", out["reason"])
        self.assertEqual(out["doors"], [])

    def test_guard_without_the_name_is_unmeasured_with_a_named_reason(self):
        out = M.measure_doors(Path("/x"), anchor=NOW, candidates=[],
                              loader=self._loader({M.GUARD_DOOR[0]: _mod()}))
        self.assertFalse(out["measured"])
        self.assertIn(M.GUARD_DOOR[1], out["reason"])

    def test_guard_refusing_the_canonical_form_cannot_be_the_reference(self):
        """Порванное звено: эталоном взята дверь, разбирающая не это поле."""
        out = M.measure_doors(Path("/x"), anchor=NOW, candidates=[],
                              loader=self._loader(
                                  {M.GUARD_DOOR[0]: _mod(_parse_ts=lambda v: None)}))
        self.assertFalse(out["measured"])
        self.assertIn(M.CANONICAL_FORM, out["reason"])

    def test_a_wider_door_is_found_and_named(self):
        table = {M.GUARD_DOOR[0]: _mod(_parse_ts=strict),
                 "scripts/wide.py": _mod(_parse_ts=lenient)}
        out = M.measure_doors(Path("/x"), anchor=NOW,
                              candidates=[("scripts/wide.py", "_parse_ts", 7)],
                              loader=self._loader(table))
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(out["by_class"][M.DOOR_WIDER], 1)
        row = out["doors"][0]
        self.assertEqual(row["class"], M.DOOR_WIDER)
        self.assertIn("micros_z", row["accepted"])
        self.assertEqual(row["line"], 7)

    def test_an_agreeing_door_is_not_reported_as_a_disagreement(self):
        table = {M.GUARD_DOOR[0]: _mod(_parse_ts=strict),
                 "scripts/same.py": _mod(_parse_ts=strict)}
        out = M.measure_doors(Path("/x"), anchor=NOW,
                              candidates=[("scripts/same.py", "_parse_ts", 1)],
                              loader=self._loader(table))
        self.assertEqual(out["by_class"][M.DOOR_WIDER], 0)
        self.assertEqual(out["by_class"][M.DOOR_AGREES], 1)

    def test_a_module_that_does_not_load_is_a_third_outcome_named_by_name(self):
        """Порванное звено: незагрузившаяся дверь пропущена молча."""
        table = {M.GUARD_DOOR[0]: _mod(_parse_ts=strict),
                 "scripts/broken.py": ImportError("импорт упал")}
        out = M.measure_doors(Path("/x"), anchor=NOW,
                              candidates=[("scripts/broken.py", "_parse_ts", 3)],
                              loader=self._loader(table))
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(out["by_class"][M.DOOR_UNMEASURED], 1)
        self.assertEqual(out["unmeasured"][0]["file"], "scripts/broken.py")
        self.assertIn("импорт упал", out["unmeasured"][0]["reason"])

    def test_a_name_found_by_parsing_but_absent_in_the_module_is_unmeasured(self):
        table = {M.GUARD_DOOR[0]: _mod(_parse_ts=strict),
                 "scripts/gone.py": _mod()}
        out = M.measure_doors(Path("/x"), anchor=NOW,
                              candidates=[("scripts/gone.py", "_parse_ts", 1)],
                              loader=self._loader(table))
        self.assertEqual(out["by_class"][M.DOOR_UNMEASURED], 1)
        self.assertEqual(out["doors"], [])

    def test_accounting_identity_classes_cover_the_population(self):
        """Инв. #17: сумма ОБЪЯВЛЕННЫХ исходов равна населению."""
        table = {M.GUARD_DOOR[0]: _mod(_parse_ts=strict),
                 "scripts/wide.py": _mod(_parse_ts=lenient),
                 "scripts/same.py": _mod(_parse_ts=strict),
                 "scripts/bad.py": ImportError("нет"),
                 "scripts/foreign.py": _mod(_parse_ts=lambda v: None)}
        out = M.measure_doors(Path("/x"), anchor=NOW, candidates=[
            ("scripts/wide.py", "_parse_ts", 1), ("scripts/same.py", "_parse_ts", 1),
            ("scripts/bad.py", "_parse_ts", 1), ("scripts/foreign.py", "_parse_ts", 1)],
            loader=self._loader(table))
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(out["population"], 4)
        self.assertEqual(sum(out["by_class"][k] for k in M.DOOR_CLASSES), 4)

    def test_the_guard_row_is_marked_as_the_guard(self):
        table = {M.GUARD_DOOR[0]: _mod(_parse_ts=strict)}
        out = M.measure_doors(Path("/x"), anchor=NOW,
                              candidates=[(M.GUARD_DOOR[0], M.GUARD_DOOR[1], 1)],
                              loader=self._loader(table))
        self.assertTrue(out["doors"][0]["is_guard"])


class TestDoorCandidates(unittest.TestCase):

    def _scene(self, files):
        root = Path(tempfile.mkdtemp(prefix="acdc_c_"))
        paths = []
        for name, body in files.items():
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(body, encoding="utf-8")
            paths.append(path)
        return root, paths

    def test_a_file_naming_the_journal_with_a_one_value_parser_is_a_candidate(self):
        root, paths = self._scene({"reader.py": (
            "LOG = 'data/session_changes.jsonl'\n"
            "import datetime\n"
            "def _parse_ts(value):\n"
            "    return datetime.datetime.strptime(value, '%Y')\n")})
        found, bad = M.door_candidates(root, files=paths)
        self.assertEqual([(f, d) for f, d, _ in found], [("reader.py", "_parse_ts")])
        self.assertEqual(bad, [])

    def test_naming_the_journal_without_a_parse_call_is_not_a_door(self):
        """Порванное звено: кандидатом стал файл, который лишь УПОМИНАЕТ журнал.

        Токен в файле читателем не делает (ADR-550/620) — и дверью тоже.
        """
        root, paths = self._scene({"mentions.py": (
            "LOG = 'data/session_changes.jsonl'\n"
            "def _parse_ts(value):\n"
            "    return value\n")})
        found, _ = M.door_candidates(root, files=paths)
        self.assertEqual(found, [])

    def test_a_parser_in_a_file_unrelated_to_the_field_is_not_a_candidate(self):
        """Порванное звено: население набрано по наличию разбора, без привязки к полю."""
        root, paths = self._scene({"stranger.py": (
            "import datetime\n"
            "def _parse_ts(value):\n"
            "    return datetime.datetime.fromisoformat(value)\n")})
        found, _ = M.door_candidates(root, files=paths)
        self.assertEqual(found, [])

    def test_a_file_using_the_schema_reader_is_a_candidate_without_naming_the_journal(self):
        root, paths = self._scene({"viaschema.py": (
            "import datetime\n"
            "def consume(rows):\n"
            "    return session_state(rows)\n"
            "def _parse_ts(value):\n"
            "    return datetime.datetime.fromisoformat(value)\n")})
        found, _ = M.door_candidates(root, files=paths)
        self.assertEqual([d for _, d, _ in found], ["_parse_ts"])

    def test_a_two_argument_function_is_not_a_door_of_one_value(self):
        root, paths = self._scene({"two.py": (
            "LOG = 'data/session_changes.jsonl'\n"
            "import datetime\n"
            "def age(value, now):\n"
            "    return datetime.datetime.fromisoformat(value) - now\n")})
        found, _ = M.door_candidates(root, files=paths)
        self.assertEqual(found, [])

    def test_an_unparseable_file_is_named_not_skipped(self):
        """Порванное звено: файл с синтаксической ошибкой пропущен молча."""
        root, paths = self._scene({"broken.py": "def (:\n"})
        (root / "broken.py").write_text(
            "LOG = 'data/session_changes.jsonl'\ndef (:\n", encoding="utf-8")
        found, bad = M.door_candidates(root, files=paths)
        self.assertEqual(found, [])
        self.assertEqual(len(bad), 1)
        self.assertIn("SyntaxError", bad[0]["reason"])

    def test_test_files_are_outside_the_door_population(self):
        root, paths = self._scene({"test_scene.py": (
            "LOG = 'data/session_changes.jsonl'\n"
            "import datetime\n"
            "def _parse_ts(value):\n"
            "    return datetime.datetime.strptime(value, '%Y')\n")})
        found, _ = M.door_candidates(root, files=paths)
        self.assertEqual(found, [])


# ──────────── ось B: производители ФОРМЫ, а не имени ключа ─────────────────

class TestResolveForm(unittest.TestCase):

    def test_strftime_with_a_literal_is_a_producer_and_the_format_node_travels(self):
        klass, kind, detail, node = _resolve("now.strftime('%Y-%m-%dT%H:%M:%SZ')")
        self.assertEqual((klass, kind, detail),
                         (M.WRITER_PRODUCES, "strftime", "%Y-%m-%dT%H:%M:%SZ"))
        self.assertIsNotNone(node, "узел формата обязан доехать до оси C")

    def test_strftime_with_a_module_constant_is_resolved(self):
        klass, kind, detail, _ = _resolve(
            "now.strftime(STAMP)", helpers_src="STAMP = '%Y-%m-%dT%H:%M:%SZ'\n")
        self.assertEqual((klass, kind, detail),
                         (M.WRITER_PRODUCES, "strftime", "%Y-%m-%dT%H:%M:%SZ"))

    def test_isoformat_is_a_producer_of_the_offset_form(self):
        klass, kind, _, _ = _resolve("now.isoformat()")
        self.assertEqual((klass, kind), (M.WRITER_PRODUCES, "iso_offset"))

    def test_isoformat_replace_is_the_micros_z_form(self):
        klass, kind, _, _ = _resolve("now.isoformat().replace('+00:00', 'Z')")
        self.assertEqual((klass, kind), (M.WRITER_PRODUCES, "iso_z"))

    def test_a_single_return_helper_is_followed(self):
        klass, kind, detail, node = _resolve(
            "_fmt(now)",
            helpers_src="def _fmt(dt):\n    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')\n")
        self.assertEqual((klass, kind, detail),
                         (M.WRITER_PRODUCES, "strftime", "%Y-%m-%dT%H:%M:%SZ"))
        self.assertIsNotNone(node,
                             "у производителя через помощника формат тоже обязан доехать")

    def test_a_helper_with_two_returns_is_not_guessed(self):
        """Порванное звено: у помощника с двумя возвратами выбрана одна ветка.

        Форма зависит от ветки, и объявлять её одной значило бы выбрать за него.
        """
        klass, _, detail, _ = _resolve(
            "_fmt(now)",
            helpers_src=("def _fmt(dt):\n"
                         "    if dt:\n"
                         "        return dt.strftime('%Y')\n"
                         "    return dt.isoformat()\n"))
        self.assertEqual(klass, M.WRITER_UNMEASURED)
        self.assertIn("_fmt", detail)

    def test_a_value_read_from_another_record_relays_and_is_not_a_writer(self):
        for expr in ("entry.get('ts')", "rec['ts']", "head.group('ts')"):
            klass, _, detail, _ = _resolve(expr)
            self.assertEqual(klass, M.WRITER_RELAYS, expr)
            self.assertIn("чтением", detail)

    def test_an_unresolved_name_is_a_third_outcome_carrying_the_name(self):
        klass, _, detail, _ = _resolve("ts_raw")
        self.assertEqual(klass, M.WRITER_UNMEASURED)
        self.assertIn("ts_raw", detail)

    def test_a_non_string_constant_is_unmeasured_with_the_type_named(self):
        klass, _, detail, _ = _resolve("None")
        self.assertEqual(klass, M.WRITER_UNMEASURED)
        self.assertIn("NoneType", detail)

    def test_the_depth_limit_is_named_as_a_number_not_a_silent_stop(self):
        helpers = "".join(f"def h{i}(d):\n    return h{i+1}(d)\n" for i in range(12))
        klass, _, detail, _ = _resolve("h0(now)", helpers_src=helpers)
        self.assertEqual(klass, M.WRITER_UNMEASURED)
        self.assertIn(str(M.RESOLVE_DEPTH), detail)

    def test_every_outcome_is_in_the_closed_list(self):
        for expr in ("now.strftime('%Y')", "'literal'", "entry.get('ts')", "whatever"):
            klass, _, _, _ = _resolve(expr)
            self.assertIn(klass, M.WRITER_CLASSES, expr)


class TestMeasureWriters(unittest.TestCase):

    def test_a_record_carrying_field_and_companion_is_a_producer(self):
        out = _writers_of("rec = {'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'),"
                          " 'session': 'c1'}\n")
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(out["by_class"][M.WRITER_PRODUCES], 1)
        self.assertEqual(out["producers"][0]["subject"], "announce_ts")

    def test_the_field_without_the_companion_key_is_outside_the_population(self):
        """Порванное звено: население набрано по ИМЕНИ КЛЮЧА, а не по ФОРМЕ записи.

        Ключ `ts` стои́т в 790 местах 451 файла дерева: без companion-ключа
        читателя прибор мерил бы «где встречается слово».
        """
        out = _writers_of("rec = {'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'),"
                          " 'apy': 4.2}\n")
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(out["population"], 0)

    def test_the_card_subject_needs_its_own_companion_key(self):
        yes = _writers_of("rec = {'claimed_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),"
                          " 'claimed_by': 'c1'}\n")
        no = _writers_of("rec = {'claimed_at': now.strftime('%Y-%m-%dT%H:%M:%SZ'),"
                         " 'status': 'new'}\n")
        self.assertEqual(yes["population"], 1)
        self.assertEqual(no["population"], 0)
        self.assertEqual(yes["producers"][0]["subject"], "card_claimed_at")

    def test_the_guard_is_the_oracle_of_the_form_not_the_reading_of_percent_f(self):
        """Порванное звено: вердикт форме вынесен разбором формата, а не дверью.

        Одна и та же сцена с ШИРОКОЙ дверью обязана дать другой вердикт — иначе
        «дверь приняла» было бы утверждением прибора о себе.
        """
        src = ("rec = {'ts': now.strftime('%Y-%m-%dT%H:%M:%S.%fZ'), 'session': 'c1'}\n")
        narrow = _writers_of(src, guard=strict)
        wide = _writers_of(src, guard=lenient)
        self.assertEqual(narrow["producers"][0]["door"], M.V_REFUSE)
        self.assertEqual(wide["producers"][0]["door"], M.V_ACCEPT)

    def test_a_micros_producer_is_refused_by_the_strict_guard(self):
        out = _writers_of("rec = {'ts': now.isoformat(), 'session': 'c1'}\n")
        self.assertEqual(out["producers"][0]["door"], M.V_REFUSE)
        self.assertEqual(out["production_by_door"][M.V_REFUSE], 1)

    def test_a_relay_is_not_counted_among_producers_of_form(self):
        out = _writers_of("rec = {'ts': entry.get('ts'), 'session': 'c1'}\n")
        self.assertEqual(out["by_class"][M.WRITER_RELAYS], 1)
        self.assertEqual(sum(out["production_by_door"].values()), 0)

    def test_production_and_test_roles_do_not_merge(self):
        """Порванное звено: сцены тестов сложены с писателями живого поля.

        Тестов в дереве кратно больше, и склейка утопила бы ответ заказа.
        """
        src = "rec = {'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'session': 'c1'}\n"
        prod = _writers_of(src, filename="writer.py")
        test = _writers_of(src, filename="test_writer.py")
        self.assertEqual(prod["production_by_door"][M.V_ACCEPT], 1)
        self.assertEqual(prod["test_by_door"][M.V_ACCEPT], 0)
        self.assertEqual(test["production_by_door"][M.V_ACCEPT], 0)
        self.assertEqual(test["test_by_door"][M.V_ACCEPT], 1)

    def test_an_unparseable_file_is_named_not_skipped(self):
        out = _writers_of("def (:\n")
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(len(out["unmeasured"]), 1)
        self.assertIn("SyntaxError", out["unmeasured"][0]["reason"])

    def test_a_guard_that_is_not_callable_leaves_the_axis_unmeasured(self):
        out = _writers_of("rec = {'ts': 'x', 'session': 'c1'}\n", guard="не функция")
        self.assertFalse(out["measured"])
        self.assertIn("не вызывается", out["reason"])

    def test_a_raising_guard_is_its_own_outcome(self):
        def explodes(value):
            raise ValueError("дверь упала")
        out = _writers_of("rec = {'ts': now.strftime('%Y'), 'session': 'c1'}\n",
                          guard=explodes)
        self.assertTrue(out["producers"][0]["door"].startswith(M.V_RAISED + ":"))

    def test_accounting_identity_classes_cover_the_population(self):
        out = _writers_of(
            "a = {'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'session': 'c1'}\n"
            "b = {'ts': entry.get('ts'), 'session': 'c2'}\n"
            "c = {'ts': 'literal', 'session': 'c3'}\n"
            "d = {'ts': whatever, 'session': 'c4'}\n")
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(out["population"], 4)
        self.assertEqual(sum(out["by_class"][k] for k in M.WRITER_CLASSES), 4)

    def test_private_row_keys_never_reach_the_artifact(self):
        """Порванное звено: узел AST уехал в сериализацию ⇒ артефакт не записывается.

        «Не записался» неотличимо от «ступень не запускалась» (ADR-526).
        """
        out = _writers_of("rec = {'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'),"
                          " 'session': 'c1'}\n")
        self.assertIn(M.ROW_FMT_NODE, out["producers"][0])
        M.strip_private_rows(out)
        for key in M.ROW_PRIVATE:
            self.assertNotIn(key, out["producers"][0])
        json.dumps(out, ensure_ascii=False)

    def test_stripping_twice_is_not_an_error(self):
        out = _writers_of("rec = {'ts': 'x', 'session': 'c1'}\n")
        M.strip_private_rows(out)
        M.strip_private_rows(out)
        M.strip_private_rows(None)


# ───────────── ось C: приватная копия против СВЯЗАННОСТИ с дверью ──────────

class TestFormatProvenance(unittest.TestCase):

    ALIASES = frozenset({"sibling", "STAMP_FROM_DOOR"})

    def _node(self, src):
        return ast.parse("_v = " + src).body[0].value

    def test_an_inline_literal_is_a_private_copy(self):
        klass, detail = M.format_provenance(self._node("'%Y'"), {}, self.ALIASES)
        self.assertEqual(klass, M.FMT_OWN_LITERAL)
        self.assertIn("%Y", detail)

    def test_a_named_constant_of_the_same_file_is_still_a_private_copy(self):
        """Порванное звено: названная константа зачтена как общее определение.

        Она лишь ВЫГЛЯДИТ общей: правку двери такая копия не узнает.
        """
        klass, detail = M.format_provenance(self._node("STAMP"), {"STAMP": "%Y"},
                                            self.ALIASES)
        self.assertEqual(klass, M.FMT_OWN_CONSTANT)
        self.assertIn("STAMP", detail)

    def test_a_name_imported_from_the_door_is_bound(self):
        """Положительный контроль: правило СПОСОБНО сказать `bound`.

        Без него «связано 0» было бы свойством правила, а не дерева.
        """
        klass, _ = M.format_provenance(self._node("STAMP_FROM_DOOR"), {}, self.ALIASES)
        self.assertEqual(klass, M.FMT_BOUND)

    def test_an_attribute_of_the_doors_module_is_bound(self):
        klass, detail = M.format_provenance(self._node("sibling.STAMP"), {},
                                            self.ALIASES)
        self.assertEqual(klass, M.FMT_BOUND)
        self.assertIn("sibling.STAMP", detail)

    def test_an_attribute_of_an_unknown_module_is_a_third_outcome(self):
        """Порванное звено: неопознанный модуль зачтён связанным или копией."""
        klass, detail = M.format_provenance(self._node("other.STAMP"), {},
                                            self.ALIASES)
        self.assertEqual(klass, M.FMT_UNMEASURED)
        self.assertIn("other", detail)

    def test_every_outcome_is_in_the_closed_list(self):
        for src in ("'%Y'", "STAMP", "sibling.STAMP", "other.STAMP", "f(x)"):
            klass, _ = M.format_provenance(self._node(src), {"STAMP": "%Y"},
                                           self.ALIASES)
            self.assertIn(klass, M.FMT_CLASSES, src)


class TestDoorAliases(unittest.TestCase):

    STEM = "check_undelivered_work"

    def test_an_import_as_alias_is_found(self):
        tree = ast.parse("import pkg.check_undelivered_work as sib\n")
        self.assertIn("sib", M.door_aliases(tree, self.STEM))

    def test_a_from_import_name_is_found(self):
        tree = ast.parse("from pkg.check_undelivered_work import STAMP\n")
        self.assertIn("STAMP", M.door_aliases(tree, self.STEM))

    def test_merely_naming_the_door_in_the_file_is_not_an_alias(self):
        """Порванное звено: «в файле упомянуто имя двери» зачтено происхождением.

        Ровно эта подмена дала 23 «связанных» из 37 в первой редакции прибора —
        число, которого в дереве нет (ADR-550: токен читателем не делает).
        """
        tree = ast.parse("PATH = 'scripts/check_undelivered_work.py'\n"
                         "# check_undelivered_work рядом в комментарии\n")
        self.assertEqual(M.door_aliases(tree, self.STEM), frozenset())

    def test_an_unrelated_import_is_not_an_alias(self):
        tree = ast.parse("import json as check_undelivered\n")
        self.assertEqual(M.door_aliases(tree, self.STEM), frozenset())


class TestMeasureBinding(unittest.TestCase):

    GUARD_SRC = ("import datetime\n"
                 "def _parse_ts(value):\n"
                 "    return datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')\n")

    def _scene(self, writer_src, *, guard_src=None, writer_name="writer.py"):
        root = Path(tempfile.mkdtemp(prefix="acdc_b_"))
        guard_path = root / M.GUARD_DOOR[0]
        guard_path.parent.mkdir(parents=True, exist_ok=True)
        guard_path.write_text(guard_src if guard_src is not None else self.GUARD_SRC,
                              encoding="utf-8")
        writer = root / writer_name
        writer.write_text(writer_src, encoding="utf-8")
        doors = {"measured": True,
                 "guard": {"file": M.GUARD_DOOR[0], "door": M.GUARD_DOOR[1]}}
        writers = M.measure_writers(root, files=[writer], guard_fn=strict, anchor=NOW)
        return root, doors, writers

    def test_the_literal_is_taken_from_the_doors_own_file_not_declared_here(self):
        """Порванное звено: литерал объявлен в приборе ⇒ сверка копий со своей копией.

        Второй экземпляр мерки запрещён (ADR-220): согласие держалось бы само собой.
        """
        root, doors, writers = self._scene(
            "rec = {'ts': now.strftime('%d.%m.%Y'), 'session': 'c1'}\n",
            guard_src=("import datetime\n"
                       "def _parse_ts(value):\n"
                       "    return datetime.datetime.strptime(value, '%d.%m.%Y')\n"))
        out = M.measure_binding(root, doors=doors, writers=writers)
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(out["format_literal"], "%d.%m.%Y")
        self.assertEqual(out["copies"], 1)

    def test_a_door_without_a_strptime_literal_leaves_the_axis_unmeasured(self):
        root, doors, writers = self._scene(
            "rec = {'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'session': 'c1'}\n",
            guard_src=("import datetime\n"
                       "def _parse_ts(value):\n"
                       "    return datetime.datetime.fromisoformat(value)\n"))
        out = M.measure_binding(root, doors=doors, writers=writers)
        self.assertFalse(out["measured"])
        self.assertIn("не добыт", out["reason"])

    def test_an_inline_literal_counts_as_a_copy_and_not_as_bound(self):
        root, doors, writers = self._scene(
            "rec = {'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'session': 'c1'}\n")
        out = M.measure_binding(root, doors=doors, writers=writers)
        self.assertEqual((out["copies"], out["bound"]), (1, 0))

    def test_a_format_imported_from_the_door_counts_as_bound(self):
        """Положительный контроль связанности на целом контуре."""
        root, doors, writers = self._scene(
            "from scripts.check_undelivered_work import STAMP\n"
            "rec = {'ts': now.strftime(STAMP), 'session': 'c1'}\n")
        # формат раскрывается по константе модуля, поэтому объявим её значением
        (root / "writer.py").write_text(
            "from scripts.check_undelivered_work import STAMP\n"
            "STAMP = '%Y-%m-%dT%H:%M:%SZ'\n"
            "rec = {'ts': now.strftime(STAMP), 'session': 'c1'}\n", encoding="utf-8")
        writers = M.measure_writers(root, files=[root / "writer.py"],
                                    guard_fn=strict, anchor=NOW)
        out = M.measure_binding(root, doors=doors, writers=writers)
        self.assertEqual(out["bound"], 1, out["sites"])
        self.assertEqual(out["copies"], 0)

    def test_a_producer_through_a_helper_still_gets_its_provenance_measured(self):
        """Порванное звено: ось C ищет формат ВТОРЫМ поиском и не находит его.

        У производителя `{'ts': _fmt(ts)}` вызов `strftime` стои́т в теле
        помощника; второй поиск давал «не измерено» на 25 площадках из 37 при
        нулевой связанности, то есть ПРЯТАЛ предмет оси за своей же слепотой.
        """
        root, doors, writers = self._scene(
            "def _fmt(dt):\n"
            "    return dt.strftime('%Y-%m-%dT%H:%M:%SZ')\n"
            "rec = {'ts': _fmt(now), 'session': 'c1'}\n")
        out = M.measure_binding(root, doors=doors, writers=writers)
        self.assertEqual(len(out["sites"]), 1)
        self.assertEqual(out["by_class"][M.FMT_UNMEASURED], 0, out["sites"])
        self.assertEqual(out["copies"], 1)

    def test_a_format_other_than_the_doors_is_not_a_copy_of_it(self):
        root, doors, writers = self._scene(
            "rec = {'ts': now.strftime('%Y-%m-%d'), 'session': 'c1'}\n")
        out = M.measure_binding(root, doors=doors, writers=writers)
        self.assertEqual(out["sites"], [])
        self.assertEqual(out["copies"], 0)

    def test_the_axis_refuses_when_an_upstream_axis_is_unmeasured(self):
        root, doors, writers = self._scene(
            "rec = {'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'session': 'c1'}\n")
        out = M.measure_binding(root, doors={"measured": False}, writers=writers)
        self.assertFalse(out["measured"])
        self.assertIn("не измерена", out["reason"])

    def test_accounting_identity_classes_cover_the_sites(self):
        root, doors, writers = self._scene(
            "STAMP = '%Y-%m-%dT%H:%M:%SZ'\n"
            "a = {'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'session': 'c1'}\n"
            "b = {'ts': now.strftime(STAMP), 'session': 'c2'}\n")
        out = M.measure_binding(root, doors=doors, writers=writers)
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(sum(out["by_class"].values()), len(out["sites"]))


# ──────────────────────── сборка, вердикт, отчёт ───────────────────────────

class TestBuildReport(unittest.TestCase):

    DOORS_OK = {"measured": True, "guard": {"file": "g.py", "door": "_parse_ts",
                                            "accepted": ["seconds_z"],
                                            "verdicts": {}},
                "doors": [], "unmeasured": [],
                "by_class": {k: 0 for k in M.DOOR_CLASSES},
                "population": 0, "forms": {}}
    WRITERS_OK = {"measured": True, "producers": [], "unmeasured": [], "population": 0,
                  "by_class": {k: 0 for k in M.WRITER_CLASSES},
                  "production_by_door": {M.V_ACCEPT: 0, M.V_REFUSE: 0,
                                         M.V_UNMEASURED: 0},
                  "test_by_door": {M.V_ACCEPT: 0, M.V_REFUSE: 0, M.V_UNMEASURED: 0}}
    BIND_OK = {"measured": True, "copies": 0, "bound": 0, "sites": [],
               "format_literal": "%Y-%m-%dT%H:%M:%SZ",
               "by_class": {k: 0 for k in M.FMT_CLASSES}}

    def _doors(self, **counts):
        doors = json.loads(json.dumps(self.DOORS_OK))
        doors["by_class"].update(counts)
        return doors

    def test_the_shape_is_constant_even_when_nothing_is_measured(self):
        report = M.build_report(Path("/x"), now=NOW, anchor=NOW,
                                doors={"measured": False, "reason": "нет"},
                                writers={"measured": False, "reason": "нет"},
                                binding={"measured": False, "reason": "нет"})
        for key in ("generated_at", "order", "measured", "status", "reason",
                    "applied", "anchor", "doors", "writers", "binding", "answer"):
            self.assertIn(key, report)
        self.assertEqual(report["status"], M.STATUS_UNMEASURED)
        self.assertIsNone(report["answer"])

    def test_the_reason_names_how_many_axes_are_unmeasured(self):
        report = M.build_report(Path("/x"), now=NOW, doors=self.DOORS_OK,
                                writers={"measured": False, "reason": "писатели"},
                                binding={"measured": False, "reason": "копии"})
        self.assertIn("2 из 3", report["reason"])
        self.assertIn("писатели", report["reason"])

    def test_a_wider_door_makes_the_status_disagree(self):
        report = M.build_report(Path("/x"), now=NOW,
                                doors=self._doors(**{M.DOOR_WIDER: 1}),
                                writers=self.WRITERS_OK, binding=self.BIND_OK)
        self.assertEqual(report["status"], M.STATUS_DOORS_DISAGREE)
        self.assertEqual(report["answer"]["doors_disagreeing"], 1)

    def test_doors_that_only_agree_or_are_foreign_make_the_status_agree(self):
        report = M.build_report(Path("/x"), now=NOW,
                                doors=self._doors(**{M.DOOR_AGREES: 3,
                                                     M.DOOR_FOREIGN: 2}),
                                writers=self.WRITERS_OK, binding=self.BIND_OK)
        self.assertEqual(report["status"], M.STATUS_DOORS_AGREE)

    def test_a_narrower_door_also_counts_as_a_disagreement(self):
        report = M.build_report(Path("/x"), now=NOW,
                                doors=self._doors(**{M.DOOR_NARROWER: 1}),
                                writers=self.WRITERS_OK, binding=self.BIND_OK)
        self.assertEqual(report["status"], M.STATUS_DOORS_DISAGREE)

    def test_one_producer_is_not_a_second_writer_but_two_are(self):
        """Порванное звено: ответ заказа взведён уже на единственном писателе."""
        one = dict(self.WRITERS_OK,
                   production_by_door={M.V_ACCEPT: 1, M.V_REFUSE: 0,
                                       M.V_UNMEASURED: 0})
        two = dict(self.WRITERS_OK,
                   production_by_door={M.V_ACCEPT: 1, M.V_REFUSE: 1,
                                       M.V_UNMEASURED: 0})
        r1 = M.build_report(Path("/x"), now=NOW, doors=self.DOORS_OK, writers=one,
                            binding=self.BIND_OK)
        r2 = M.build_report(Path("/x"), now=NOW, doors=self.DOORS_OK, writers=two,
                            binding=self.BIND_OK)
        self.assertFalse(r1["answer"]["second_writer_exists"])
        self.assertTrue(r2["answer"]["second_writer_exists"])

    def test_the_instrument_declares_itself_read_only(self):
        report = M.build_report(Path("/x"), now=NOW, doors=self.DOORS_OK,
                                writers=self.WRITERS_OK, binding=self.BIND_OK)
        self.assertFalse(report["applied"])

    def test_exit_code_tells_the_three_outcomes_apart(self):
        self.assertEqual(M.exit_code_for({"measured": False}), 2)
        self.assertEqual(M.exit_code_for({"measured": True,
                                          "status": M.STATUS_DOORS_DISAGREE}), 1)
        self.assertEqual(M.exit_code_for({"measured": True,
                                          "status": M.STATUS_DOORS_AGREE}), 0)


class TestFormatReport(unittest.TestCase):

    def test_an_unmeasured_report_says_so_with_its_reason(self):
        lines = M.format_report({"measured": False, "reason": "эталон не загружен"})
        self.assertEqual(len(lines), 1)
        self.assertIn("НЕ ИЗМЕРЕНО", lines[0])
        self.assertIn("эталон не загружен", lines[0])

    def test_a_disagreeing_door_is_named_with_the_forms_it_accepts_beyond_the_guard(self):
        report = M.build_report(
            Path("/x"), now=NOW,
            doors={"measured": True,
                   "guard": {"file": "g.py", "door": "_parse_ts",
                             "accepted": ["seconds_z"], "verdicts": {}},
                   "doors": [{"file": "scripts/wide.py", "door": "_parse_ts",
                              "line": 5, "class": M.DOOR_WIDER,
                              "accepted": ["seconds_z", "micros_z"],
                              "verdicts": {}, "is_guard": False}],
                   "unmeasured": [],
                   "by_class": dict({k: 0 for k in M.DOOR_CLASSES},
                                    **{M.DOOR_WIDER: 1}),
                   "population": 1, "forms": {}},
            writers=TestBuildReport.WRITERS_OK, binding=TestBuildReport.BIND_OK)
        text = "\n".join(M.format_report(report))
        self.assertIn("scripts/wide.py", text)
        self.assertIn("micros_z", text)
        self.assertIn("СВЕРХ эталона", text)

    def test_the_report_names_what_it_does_not_measure(self):
        report = M.build_report(Path("/x"), now=NOW, doors=TestBuildReport.DOORS_OK,
                                writers=TestBuildReport.WRITERS_OK,
                                binding=TestBuildReport.BIND_OK)
        text = "\n".join(M.format_report(report))
        self.assertIn("НЕ ДОКЛАДЫВАЕТ", text)
        self.assertIn("ADVISORY", text)


class TestRunLeavesTheArtifact(unittest.TestCase):

    def test_the_artifact_is_left_even_when_nothing_is_measured(self):
        """Порванное звено: при третьем исходе артефакт не оставлен.

        Отсутствие файла неотличимо от «ступень не запускалась» (ADR-526).
        """
        root = Path(tempfile.mkdtemp(prefix="acdc_r_"))
        (root / "data").mkdir()
        out = M.run(root=str(root), now=NOW)
        self.assertFalse(out["measured"])
        path = root / "data" / M.ARTIFACT_NAME
        self.assertTrue(path.is_file())
        doc = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(doc["status"], M.STATUS_UNMEASURED)
        self.assertIsNotNone(doc["reason"])

    def test_a_failed_write_is_named_and_does_not_kill_the_bridge(self):
        """Порванное звено: неудачная запись валит ступень моста целиком.

        Сцена ломает запись по-настоящему: `data` — ФАЙЛ, а не каталог. Отсутствие
        каталога поломкой не является (`atomic_save` создаёт его сам) — проверено
        на этой же правке, и прежняя редакция теста зеленела бы от того, что
        запись УДАЛАСЬ.
        """
        root = Path(tempfile.mkdtemp(prefix="acdc_r2_"))
        (root / "data").write_text("я файл, а не каталог\n", encoding="utf-8")
        out = M.run(root=str(root), now=NOW)
        self.assertIn("artifact_not_written", out["doc"])
        self.assertIn("measured", out)


# ─────────────────────────── проводка до читателя ──────────────────────────

class TestWiring(unittest.TestCase):

    ROOT = Path(__file__).resolve().parents[2]

    def test_the_artifact_is_declared_in_the_manifest_with_producer_and_slo(self):
        manifest = json.loads((self.ROOT / "architecture" / "manifest.json")
                              .read_text(encoding="utf-8"))
        rows = [a for a in manifest["artifacts"]
                if a.get("path") == f"data/{M.ARTIFACT_NAME}"]
        self.assertEqual(len(rows), 1, "артефакт объявлен ровно одной строкой")
        self.assertEqual(rows[0]["producer"], "com.spa.decision_loop")
        self.assertEqual(rows[0]["slo_hours"], 12)
        self.assertIn("orchestrator_protocol", rows[0]["consumers"])

    def test_the_bridge_declares_the_stage_and_calls_it(self):
        src = (self.ROOT / "spa_core" / "monitoring" / "findings_bridge.py") \
            .read_text(encoding="utf-8")
        self.assertIn("announce_clock_door_census", src)
        self.assertIn("announce_clock_door_census.run(", src)

    def test_the_office_step_has_a_named_branch_and_a_declared_schema(self):
        """Порванное звено: артефакт объявлен, а читателя внутри цикла нет.

        Без поимённой ветки шаг 0-офис читает его ВХОЛОСТУЮ — находка без
        читателя, ровно тот дефект, что ловит сам заказ (ADR-526).
        """
        src = (self.ROOT / "scripts" / "consume_office_reports.py") \
            .read_text(encoding="utf-8")
        self.assertIn(f'elif name == "{M.ARTIFACT_NAME}"', src)
        self.assertIn("announce_clock_door_census import format_report", src)
        self.assertIn(f'"{M.ARTIFACT_NAME}": ("status", "measured"', src)

    def test_the_guard_door_named_by_the_instrument_exists_in_the_tree(self):
        path = self.ROOT / M.GUARD_DOOR[0]
        self.assertTrue(path.is_file(), f"двери-эталона нет по пути {path}")
        tree = ast.parse(path.read_text(encoding="utf-8"))
        names = {n.name for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        self.assertIn(M.GUARD_DOOR[1], names)

    def test_the_instrument_does_not_widen_the_guard_door(self):
        """Заказ прямо запретил починку вслепую: дверь остаётся секундной.

        Тест — положительный контроль НА ЗАПРЕТ: расширится дверь молча, и
        красным станет он, а не чужая батарея.
        """
        src = (self.ROOT / M.GUARD_DOOR[0]).read_text(encoding="utf-8")
        tree = ast.parse(src)
        formats = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) \
                    and node.name == M.GUARD_DOOR[1]:
                for call in ast.walk(node):
                    if isinstance(call, ast.Call) \
                            and isinstance(call.func, ast.Attribute) \
                            and call.func.attr == "strptime" and len(call.args) > 1 \
                            and isinstance(call.args[1], ast.Constant):
                        formats.append(call.args[1].value)
        self.assertEqual(formats, ["%Y-%m-%dT%H:%M:%SZ"],
                         "дверь-эталон изменена — это предмет заказа, не попутная правка")


# ──────────── КОНТРАКТ: перечни сверяются с ЛИТЕРАЛАМИ, не с собой ──────────
#
# Урок, измеренный мутациями этой же доставки: 232 мутанта из 607 выжили, и
# ГЛАВНЫЙ их класс — подмена имени ключа или класса, которую тест не видит
# потому, что сравнивает значение С САМИМ СОБОЙ (`M.DOOR_WIDER == M.DOOR_WIDER`).
# Словарь артефакта есть ВНЕШНИЙ контракт: его читают шаг 0-офис и будущие ADR.
# Поэтому ниже он пришпилен ДОСЛОВНО.

class TestClosedVocabularyIsPinnedToLiterals(unittest.TestCase):

    def test_door_classes(self):
        self.assertEqual(M.DOOR_CLASSES, ("agrees_with_guard", "wider_than_guard",
                                          "narrower_than_guard", "crossing_guard",
                                          "not_this_field", "unmeasured"))

    def test_writer_classes(self):
        self.assertEqual(M.WRITER_CLASSES, ("produces_form", "relays_read_value",
                                            "literal_value", "unmeasured"))

    def test_format_provenance_classes(self):
        self.assertEqual(M.FMT_CLASSES, ("own_literal", "own_named_constant",
                                         "bound_to_door", "unmeasured"))

    def test_form_names(self):
        self.assertEqual(M.FORM_NAMES, ("seconds_z", "micros_z", "isoformat_offset",
                                        "isoformat_sec_offset", "naive_seconds",
                                        "space_separator", "epoch_float"))

    def test_per_form_verdicts(self):
        self.assertEqual((M.V_ACCEPT, M.V_REFUSE, M.V_RAISED, M.V_UNMEASURED),
                         ("accepted", "refused", "raised", "unmeasured"))

    def test_statuses(self):
        self.assertEqual((M.STATUS_DOORS_DISAGREE, M.STATUS_DOORS_AGREE,
                          M.STATUS_UNMEASURED),
                         ("CLOCK_DOORS_DISAGREE", "CLOCK_DOORS_AGREE", "UNMEASURED"))

    def test_population_roots_and_the_journal_name(self):
        self.assertEqual(M.ROOTS, ("spa_core", "scripts", "tests", "studio_shell",
                                   "research"))
        self.assertEqual(M.JOURNAL_FILENAME, "session_changes.jsonl")
        self.assertEqual(M.SCHEMA_READER_NAMES, ("read_entries", "session_state"))

    def test_the_guard_door_is_named_by_path_and_function(self):
        self.assertEqual(M.GUARD_DOOR,
                         ("scripts/check_undelivered_work.py", "_parse_ts"))

    def test_subjects_name_the_field_and_the_companion_key_the_reader_requires(self):
        self.assertEqual(M.SUBJECTS, {"announce_ts": ("ts", "session"),
                                      "card_claimed_at": ("claimed_at", "claimed_by")})

    def test_canonical_form_and_resolve_depth(self):
        self.assertEqual(M.CANONICAL_FORM, "seconds_z")
        self.assertEqual(M.RESOLVE_DEPTH, 6)

    def test_private_row_keys(self):
        self.assertEqual(M.ROW_PRIVATE, ("_fmt_node", "_consts", "_helpers_file"))

    def test_the_anchor_is_the_moment_the_order_measured(self):
        """Якорь ПРИБОРА, а не сцены: микросекунды в нём — предмет заказа."""
        self.assertEqual(M.ANCHOR.isoformat(), "2026-10-02T05:07:31.286040+00:00")

    def test_every_form_string_is_pinned_verbatim(self):
        """Порванное звено: форма собрана не той строкой.

        Вердикт двери считается ОТ этих семи строк; собери одну из них иначе —
        и дверь ответит про другую форму, а перечень при этом не изменится.
        """
        self.assertEqual(M.forms_at(NOW), {
            "seconds_z": "2026-10-02T05:07:31Z",
            "micros_z": "2026-10-02T05:07:31.286040Z",
            "isoformat_offset": "2026-10-02T05:07:31.286040+00:00",
            "isoformat_sec_offset": "2026-10-02T05:07:31+00:00",
            "naive_seconds": "2026-10-02T05:07:31",
            "space_separator": "2026-10-02 05:07:31Z",
            "epoch_float": NOW.timestamp(),
        })


class TestArtifactSchemaMatchesTheOfficeContract(unittest.TestCase):
    """Ключи отчёта — ВНЕШНИЙ контракт: их объявил шаг 0-офис.

    Переименуй ключ в приборе молча, и шаг 0-офис прочтёт артефакт ВХОЛОСТУЮ:
    находка без читателя внутри цикла (ADR-526). Поэтому перечень берётся у
    ЧИТАТЕЛЯ и сверяется с тем, что производитель действительно кладёт.
    """

    ROOT = Path(__file__).resolve().parents[2]

    def _declared(self):
        import re
        src = (self.ROOT / "scripts" / "consume_office_reports.py") \
            .read_text(encoding="utf-8")
        head = src.index(f'"{M.ARTIFACT_NAME}": (')
        tail = src.index(")", head)
        return tuple(re.findall(r'"([a-z_]+)"', src[head + len(M.ARTIFACT_NAME) + 4:tail]))

    def test_the_office_declares_the_keys_the_report_actually_carries(self):
        declared = self._declared()
        self.assertEqual(declared, ("status", "measured", "order", "applied",
                                    "answer", "doors", "writers", "binding"))
        report = M.build_report(Path("/x"), now=NOW,
                                doors=TestBuildReport.DOORS_OK,
                                writers=TestBuildReport.WRITERS_OK,
                                binding=TestBuildReport.BIND_OK)
        for key in declared:
            self.assertIn(key, report, f"шаг 0-офис объявил ключ `{key}`, а его нет")

    def test_the_generated_stamp_carries_z_and_not_an_offset(self):
        report = M.build_report(Path("/x"), now=NOW, doors=TestBuildReport.DOORS_OK,
                                writers=TestBuildReport.WRITERS_OK,
                                binding=TestBuildReport.BIND_OK)
        self.assertTrue(report["generated_at"].endswith("Z"), report["generated_at"])
        self.assertNotIn("+00:00", report["generated_at"])
        self.assertEqual(report["anchor"], "2026-10-02T05:07:31.286040Z")

    def test_the_answer_names_every_number_the_order_asked_for(self):
        report = M.build_report(Path("/x"), now=NOW, doors=TestBuildReport.DOORS_OK,
                                writers=TestBuildReport.WRITERS_OK,
                                binding=TestBuildReport.BIND_OK)
        self.assertEqual(set(report["answer"]), {
            "second_writer_exists", "production_producers", "refused_by_guard",
            "doors_disagreeing", "format_copies", "format_bound_to_door"})


# ─────────────────── ветви, которых сцены не исполняли ─────────────────────

class TestUncoveredBranches(unittest.TestCase):

    def test_a_path_under_a_tests_directory_is_a_test_file_without_the_prefix(self):
        """Порванное звено: роль определялась ТОЛЬКО по приставке имени.

        Файл `spa_core/tests/helpers.py` приставки не несёт, а сценой является.
        """
        self.assertTrue(M.is_test_path(Path("spa_core/tests/helpers.py")))
        self.assertTrue(M.is_test_path(Path("a/test_x.py")))
        self.assertFalse(M.is_test_path(Path("spa_core/monitoring/real.py")))

    def test_a_package_module_is_loaded_by_its_dotted_name_not_by_bare_path(self):
        """Порванное звено: пакетный модуль грузится по пути ⇒ рвутся его импорты.

        Замерено: по пути НЕ ИЗМЕРЕНЫ были 4 двери из 9 — слабость ПРИБОРА,
        выданная за свойство дерева.
        """
        root = Path(__file__).resolve().parents[2]
        loaded = M._load_by_path(
            root / "spa_core" / "monitoring" / "announce_clock_door_census.py",
            "_probe")
        self.assertEqual(loaded.ARTIFACT_NAME, M.ARTIFACT_NAME)
        self.assertIs(loaded, M, "пакетный модуль обязан прийти ТЕМ ЖЕ объектом")

    def test_tree_files_collects_python_only_and_includes_the_root(self):
        root = Path(tempfile.mkdtemp(prefix="acdc_t_"))
        (root / "spa_core").mkdir()
        (root / "spa_core" / "deep.py").write_text("x = 1\n", encoding="utf-8")
        (root / "spa_core" / "notes.txt").write_text("не питон\n", encoding="utf-8")
        (root / "top.py").write_text("y = 2\n", encoding="utf-8")
        names = {p.name for p in M.tree_files(root, roots=("spa_core",))}
        self.assertEqual(names, {"deep.py", "top.py"})

    def test_an_import_without_an_alias_binds_the_base_name(self):
        """Порванное звено: импорт без `as` не давал имени вовсе."""
        tree = ast.parse("import pkg.check_undelivered_work\n")
        self.assertIn("pkg", M.door_aliases(tree, "check_undelivered_work"))

    def test_binding_refuses_when_the_guard_names_a_file_but_not_a_door(self):
        """Порванное звено: `or` в проверке предпосылки заменён на `and`."""
        out = M.measure_binding(Path("/x"),
                                doors={"measured": True,
                                       "guard": {"file": "g.py", "door": None}},
                                writers={"measured": True, "producers": []})
        self.assertFalse(out["measured"])
        self.assertIn("не названа", out["reason"])

    def test_a_producer_of_another_form_kind_is_not_a_copy_site(self):
        """Порванное звено: площадкой копии зачтён производитель НЕ strftime.

        `isoformat()` формата не несёт вовсе — спрашивать о его происхождении
        нечего, и зачесть его копией значило бы насчитать копий больше, чем их есть.
        """
        root = Path(tempfile.mkdtemp(prefix="acdc_k_"))
        guard = root / M.GUARD_DOOR[0]
        guard.parent.mkdir(parents=True, exist_ok=True)
        guard.write_text("import datetime\n"
                         "def _parse_ts(value):\n"
                         "    return datetime.datetime.strptime("
                         "value, '%Y-%m-%dT%H:%M:%SZ')\n", encoding="utf-8")
        writer = root / "w.py"
        writer.write_text("rec = {'ts': now.isoformat(), 'session': 'c1'}\n",
                          encoding="utf-8")
        writers = M.measure_writers(root, files=[writer], guard_fn=strict, anchor=NOW)
        out = M.measure_binding(root, doors={
            "measured": True,
            "guard": {"file": M.GUARD_DOOR[0], "door": M.GUARD_DOOR[1]}},
            writers=writers)
        self.assertEqual(out["sites"], [])


class TestCommandLine(unittest.TestCase):

    def _scene(self):
        root = Path(tempfile.mkdtemp(prefix="acdc_cli_"))
        (root / "data").mkdir()
        return root

    def test_json_output_is_a_machine_readable_report(self):
        import contextlib, io
        root = self._scene()
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            code = M.main(["--repo-root", str(root), "--json"])
        doc = json.loads(buf.getvalue())
        self.assertEqual(code, 2, "третий исход обязан дать ненулевой код")
        self.assertEqual(doc["status"], M.STATUS_UNMEASURED)

    def test_save_writes_the_artifact_where_the_office_step_reads_it(self):
        import contextlib, io
        root = self._scene()
        with contextlib.redirect_stdout(io.StringIO()):
            M.main(["--repo-root", str(root), "--save"])
        self.assertTrue((root / "data" / M.ARTIFACT_NAME).is_file())

    def test_without_save_nothing_is_written(self):
        import contextlib, io
        root = self._scene()
        with contextlib.redirect_stdout(io.StringIO()):
            M.main(["--repo-root", str(root)])
        self.assertFalse((root / "data" / M.ARTIFACT_NAME).exists())


# ───────── сцены, которых не было: третьи исходы и прямые ветви ────────────
#
# Урок мутаций этой доставки: выживший мутант почти всегда означает дыру СЦЕНЫ,
# а не слабость прибора. Ниже — ровно те ветви, до которых сцены не доезжали.

class TestSynthForm(unittest.TestCase):
    """`synth_form` — мост между статической формой и ЖИВОЙ дверью.

    Каждая ветвь проверяется ПРЯМО: через `measure_writers` до них доезжала не
    всякая, и подмена рода формы молча давала строку другой формы — то есть
    вердикт двери о том, чего производитель не пишет.
    """

    def setUp(self):
        self.forms = M.forms_at(NOW)

    def test_strftime_renders_the_format_at_the_anchor(self):
        self.assertEqual(M.synth_form("strftime", "%Y-%m-%dT%H:%M:%SZ", self.forms,
                                      NOW), SEC)

    def test_an_unknown_directive_yields_a_string_and_the_DOOR_refuses_it(self):
        """ИЗМЕРЕНО, а не предположено: `strftime` на неизвестной директиве НЕ падает.

        Замер на этой машине: `'%'`, `'%Q'`, `'%E'`, `'%O'` отдают строку, а не
        исключение. Значит третий исход у такой формы приходит от ДВЕРИ, а не от
        сборки строки, — и утверждать обратное было бы выдумкой о платформе.
        """
        value = M.synth_form("strftime", "%Q", self.forms, NOW)
        self.assertEqual(value, "Q")
        self.assertIsNone(strict(value), "дверь обязана отказать такой строке")

    def test_a_format_that_is_not_a_string_is_a_third_outcome(self):
        """Ветвь отказа сборки: формат не строка ⇒ None, а не падение прибора."""
        self.assertIsNone(M.synth_form("strftime", None, self.forms, NOW))

    def test_iso_offset_is_the_offset_form(self):
        self.assertEqual(M.synth_form("iso_offset", "isoformat()", self.forms, NOW),
                         self.forms["isoformat_offset"])

    def test_iso_z_is_the_micros_form_the_order_measured(self):
        self.assertEqual(M.synth_form("iso_z", "x", self.forms, NOW), MICRO)

    def test_epoch_is_not_a_string_at_all(self):
        value = M.synth_form("epoch", "time.time()", self.forms, NOW)
        self.assertEqual(value, self.forms["epoch_float"])
        self.assertNotIsInstance(value, str)

    def test_a_literal_is_itself(self):
        self.assertEqual(M.synth_form("literal", "не дата", self.forms, NOW),
                         "не дата")

    def test_an_unknown_kind_is_a_third_outcome(self):
        self.assertIsNone(M.synth_form(None, "x", self.forms, NOW))
        self.assertIsNone(M.synth_form("род_которого_нет", "x", self.forms, NOW))


class TestResolveFormUncoveredBranches(unittest.TestCase):

    def test_a_literal_value_declares_its_kind(self):
        klass, kind, detail, _ = _resolve("'2026-01-01T00:00:00Z'")
        self.assertEqual((klass, kind), (M.WRITER_LITERAL, "literal"))
        self.assertEqual(detail, "2026-01-01T00:00:00Z")

    def test_a_module_constant_value_declares_its_kind(self):
        klass, kind, _, _ = _resolve("STAMP", helpers_src="STAMP = 'x'\n")
        self.assertEqual((klass, kind), (M.WRITER_LITERAL, "literal"))

    def test_a_strip_call_is_followed_to_the_value_it_wraps(self):
        """Порванное звено: `.strip()` не раскрывается ⇒ производитель теряется."""
        klass, kind, detail, _ = _resolve("now.strftime('%Y-%m-%dT%H:%M:%SZ').strip()")
        self.assertEqual((klass, kind, detail),
                         (M.WRITER_PRODUCES, "strftime", "%Y-%m-%dT%H:%M:%SZ"))

    def test_an_epoch_call_is_a_producer_of_a_non_string(self):
        klass, kind, _, _ = _resolve("time.time()")
        self.assertEqual((klass, kind), (M.WRITER_PRODUCES, "epoch"))

    def test_a_replace_on_something_other_than_isoformat_is_not_the_z_form(self):
        klass, kind, _, _ = _resolve("entry.get('ts').replace('a', 'b')")
        self.assertEqual(klass, M.WRITER_RELAYS)
        self.assertIsNone(kind)

    def test_a_strftime_without_arguments_is_unmeasured_not_a_producer(self):
        klass, _, _, _ = _resolve("now.strftime()")
        self.assertEqual(klass, M.WRITER_UNMEASURED)


class TestIneligibleScenesNowCovered(unittest.TestCase):

    def test_a_non_string_dict_key_does_not_break_the_form_rule(self):
        """Порванное звено: `and` в проверке ключа заменён на `or`.

        Словарь с ключом-числом существует; без проверки типа значение ключа
        сравнивалось бы с именем поля и падало бы на разборе.
        """
        out = _writers_of("rec = {1: 'x', 'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'),"
                          " 'session': 'c1'}\n")
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(out["by_class"][M.WRITER_PRODUCES], 1)

    def test_an_unreadable_file_is_a_named_third_outcome_of_the_door_population(self):
        """Порванное звено: нечитаемый файл пропущен молча.

        Сцена ломает чтение по-настоящему: на месте файла стои́т КАТАЛОГ.
        """
        root = Path(tempfile.mkdtemp(prefix="acdc_u_"))
        (root / "asdir.py").mkdir()
        found, bad = M.door_candidates(root, files=[root / "asdir.py"])
        self.assertEqual(found, [])
        self.assertEqual(len(bad), 1)
        self.assertEqual(bad[0]["file"], "asdir.py")
        self.assertIsNone(bad[0]["door"])
        self.assertIn("не прочитан", bad[0]["reason"])

    def test_an_unreadable_file_is_a_named_third_outcome_of_the_writer_population(self):
        root = Path(tempfile.mkdtemp(prefix="acdc_u2_"))
        (root / "asdir.py").mkdir()
        out = M.measure_writers(root, files=[root / "asdir.py"], guard_fn=strict,
                                anchor=NOW)
        self.assertTrue(out["measured"], out["reason"])
        self.assertEqual(out["unmeasured"][0]["file"], "asdir.py")
        self.assertIsNone(out["unmeasured"][0]["line"])

    def test_the_doors_axis_reports_every_declared_field_of_a_measured_row(self):
        """Порванное звено: ключ строки оси A переименован — читатель ослеп."""
        def load(path, label):
            return _mod(_parse_ts=strict if path == M.GUARD_DOOR[0] else lenient)
        out = M.measure_doors(Path("/x"), anchor=NOW,
                              candidates=[("scripts/wide.py", "_parse_ts", 11)],
                              loader=load)
        row = out["doors"][0]
        self.assertEqual(set(row), {"file", "door", "line", "class", "verdicts",
                                    "accepted", "is_guard"})
        self.assertEqual(set(out), {"measured", "reason", "guard", "doors",
                                    "by_class", "population", "unmeasured",
                                    "forms", "form_not_execution"})
        self.assertEqual(set(out["guard"]), {"file", "door", "verdicts", "accepted"})

    def test_the_writers_axis_reports_every_declared_field_of_a_row(self):
        out = _writers_of("rec = {'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'),"
                          " 'session': 'c1'}\n")
        M.strip_private_rows(out)
        self.assertEqual(set(out["producers"][0]),
                         {"file", "line", "subject", "role", "class", "form_kind",
                          "detail", "stamp", "door"})

    def test_the_binding_axis_reports_every_declared_field_of_a_site(self):
        root = Path(tempfile.mkdtemp(prefix="acdc_s_"))
        guard = root / M.GUARD_DOOR[0]
        guard.parent.mkdir(parents=True, exist_ok=True)
        guard.write_text("import datetime\n"
                         "def _parse_ts(value):\n"
                         "    return datetime.datetime.strptime("
                         "value, '%Y-%m-%dT%H:%M:%SZ')\n", encoding="utf-8")
        writer = root / "w.py"
        writer.write_text("rec = {'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'),"
                          " 'session': 'c1'}\n", encoding="utf-8")
        writers = M.measure_writers(root, files=[writer], guard_fn=strict, anchor=NOW)
        out = M.measure_binding(root, doors={
            "measured": True,
            "guard": {"file": M.GUARD_DOOR[0], "door": M.GUARD_DOOR[1]}},
            writers=writers)
        self.assertEqual(set(out["sites"][0]),
                         {"file", "line", "role", "class", "detail"})


class TestRunOnAMeasurableScene(unittest.TestCase):
    """`run` обязан доложить `measured=True`, когда замер УДАЛСЯ.

    Порванное звено: `run` читает не то поле отчёта и всегда отвечает «не
    измерено». Прежняя батарея этого не видела — она проверяла только сцену, где
    «не измерено» и есть правильный ответ, то есть зеленела от ОБОИХ исходов.
    """

    def _scene(self):
        root = Path(tempfile.mkdtemp(prefix="acdc_run_"))
        (root / "data").mkdir()
        guard = root / M.GUARD_DOOR[0]
        guard.parent.mkdir(parents=True, exist_ok=True)
        guard.write_text(
            "LOG = 'data/session_changes.jsonl'\n"
            "import datetime\n"
            "def _parse_ts(value):\n"
            "    if not isinstance(value, str):\n"
            "        return None\n"
            "    try:\n"
            "        return datetime.datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ')\n"
            "    except ValueError:\n"
            "        return None\n", encoding="utf-8")
        (root / "spa_core").mkdir()
        (root / "spa_core" / "writer.py").write_text(
            "rec = {'ts': now.strftime('%Y-%m-%dT%H:%M:%SZ'), 'session': 'c1'}\n",
            encoding="utf-8")
        return root

    def test_a_measurable_scene_reports_measured_true_and_leaves_the_artifact(self):
        root = self._scene()
        out = M.run(root=str(root), now=NOW)
        self.assertTrue(out["measured"], out["doc"].get("reason"))
        self.assertEqual(out["doc"]["status"], M.STATUS_DOORS_AGREE)
        doc = json.loads((root / "data" / M.ARTIFACT_NAME).read_text(encoding="utf-8"))
        self.assertTrue(doc["measured"])
        self.assertEqual(doc["answer"]["production_producers"], 1)
        self.assertEqual(doc["answer"]["format_copies"], 1)
        self.assertEqual(doc["answer"]["format_bound_to_door"], 0)
        self.assertFalse(doc["answer"]["second_writer_exists"])

    def test_a_second_writer_in_the_scene_flips_the_answer(self):
        """Положительный контроль ответа заказа на целом контуре `run`."""
        root = self._scene()
        (root / "spa_core" / "second.py").write_text(
            "rec = {'ts': now.isoformat(), 'session': 'c2'}\n", encoding="utf-8")
        out = M.run(root=str(root), now=NOW)
        self.assertTrue(out["measured"], out["doc"].get("reason"))
        self.assertTrue(out["doc"]["answer"]["second_writer_exists"])
        self.assertEqual(out["doc"]["answer"]["refused_by_guard"], 1)

    def test_a_wider_door_in_the_scene_makes_the_whole_run_disagree(self):
        root = self._scene()
        (root / "scripts" / "lenient.py").write_text(
            "LOG = 'data/session_changes.jsonl'\n"
            "import datetime\n"
            "def _parse_ts(value):\n"
            "    try:\n"
            "        return datetime.datetime.fromisoformat("
            "str(value).replace('Z', '+00:00'))\n"
            "    except ValueError:\n"
            "        return None\n", encoding="utf-8")
        out = M.run(root=str(root), now=NOW)
        self.assertEqual(out["doc"]["status"], M.STATUS_DOORS_DISAGREE)
        self.assertEqual(out["doc"]["answer"]["doors_disagreeing"], 1)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
