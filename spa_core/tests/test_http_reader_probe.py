"""Приёмка G29 (ADR-404): часы HTTP-ветви переписи и тело ответа-объекта.

Каждый тест — положительный контроль конкретной поломки, замеренной 17.09:

* у 18 маршрутов вердикта не было, потому что между двумя пробами ОДНОГО стенда
  расходилась отметка верхнего уровня, выставленная стенными часами;
* 20 маршрутов сравнивались по ``repr`` объекта ``JSONResponse`` — то есть по
  АДРЕСУ в памяти, а не по телу;
* запуск зонда по пути затенял стандартный ``signal`` соседним
  ``spa_core/monitoring/signal.py``, и падал импорт ВСЕХ маршрутов.

Приёмка G30 (там же, ниже ``CallMomentTests``): у 18 маршрутов вердикт гасила
отметка ТЕЛА из ``time.time()`` — 16 дверей, общей нет; момент выдачи теперь
узнаётся по окну зова. И второй раз тот же ``signal``: через путь со ссылкой
(``/tmp`` на macOS) сравнение ``abspath`` не совпадало.
"""
# FROZEN-DATE-OK: injected-clock — _PIN передаётся зонду окружением
# (SPA_CENSUS_PINNED_NOW) и в pin_clock(_PIN.isoformat()); проверяется, что
# дверь вернула именно его, стенные часы ни одна проверка не читает.
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from spa_core.monitoring import _http_reader_probe as probe
from spa_core.monitoring import run_identity_key_price as census

_TREE = Path(__file__).resolve().parents[2]

#: Закреплённый момент. Далеко от любых настоящих часов, чтобы «дверь вернула
#: стенное время» и «дверь вернула пин» различались всегда.
_PIN = datetime(2020, 1, 2, 3, 4, 5, tzinfo=timezone.utc)


def _run_probe_by_path(names, data_dir, pinned=None):
    """Зонд так, как его зовёт перепись: отдельный процесс, ПО ПУТИ к файлу."""
    with tempfile.TemporaryDirectory(prefix="g29_run_") as tmp:
        mods = Path(tmp) / "m.json"
        out = Path(tmp) / "o.json"
        mods.write_text(json.dumps(list(names)), encoding="utf-8")
        env = dict(os.environ)
        env[probe.DATA_DIR_ENV] = str(data_dir)
        env.pop(probe.CLOCK_ENV, None)
        if pinned is not None:
            env[probe.CLOCK_ENV] = pinned
        env["PYTHONPATH"] = str(_TREE)
        proc = subprocess.run(
            [sys.executable, str(_TREE / "spa_core" / "monitoring" / "_http_reader_probe.py"),
             str(mods), str(out)],
            cwd=str(_TREE), env=env, capture_output=True, timeout=300)
        answer = json.loads(out.read_text(encoding="utf-8")) if out.exists() else None
        return proc.returncode, answer, proc.stderr.decode("utf-8", "replace")


class PinClockTests(unittest.TestCase):
    """Подмена класса часов — и её обязательный откат."""

    def tearDown(self):
        probe.unpin_clock()

    def test_now_and_utcnow_return_the_pinned_moment(self):
        import datetime as dt
        probe.pin_clock(_PIN.isoformat())
        self.assertEqual(dt.datetime.now(timezone.utc), _PIN)
        self.assertEqual(dt.datetime.utcnow(), _PIN.replace(tzinfo=None))
        self.assertEqual(dt.datetime.now().astimezone(timezone.utc), _PIN)

    def test_unpin_restores_the_real_class(self):
        import datetime as dt
        real = dt.datetime
        probe.pin_clock(_PIN.isoformat())
        probe.pin_clock(_PIN.isoformat())      # повторный пин не наслаивается навсегда
        self.assertIsNot(dt.datetime, real)
        probe.unpin_clock()
        self.assertIs(dt.datetime, real)
        self.assertNotEqual(dt.datetime.now(timezone.utc), _PIN)

    def test_a_moment_without_a_zone_is_refused(self):
        """Наивное время — догадка о поясе. fail-CLOSED, класс не подменён."""
        import datetime as dt
        real = dt.datetime
        with self.assertRaises(ValueError):
            probe.pin_clock("2020-01-02T03:04:05")
        self.assertIs(dt.datetime, real)


class ProbeProcessTests(unittest.TestCase):
    """Процесс-зонд целиком: часы у двери и импорт маршрутов при запуске по пути."""

    def test_the_door_answers_the_pinned_moment(self):
        with tempfile.TemporaryDirectory(prefix="g29_door_") as tmp:
            code, answer, err = _run_probe_by_path([], tmp, pinned=_PIN.isoformat())
        self.assertEqual(code, 0, err)
        self.assertEqual(answer["__clock__"]["shared_now"], _PIN.isoformat())
        self.assertEqual(answer["__clock__"]["pinned"], _PIN.isoformat())

    def test_without_the_pin_the_door_answers_the_wall_clock(self):
        """Обратный контроль: без него первый тест был бы истинным по построению."""
        with tempfile.TemporaryDirectory(prefix="g29_door_") as tmp:
            code, answer, err = _run_probe_by_path([], tmp)
        self.assertEqual(code, 0, err)
        self.assertIsNone(answer["__clock__"]["pinned"])
        self.assertNotEqual(answer["__clock__"]["shared_now"], _PIN.isoformat())
        self.assertIsNotNone(answer["__clock__"]["shared_now"])

    def test_a_naive_pin_is_refused_by_the_process(self):
        with tempfile.TemporaryDirectory(prefix="g29_door_") as tmp:
            code, answer, _err = _run_probe_by_path([], tmp, pinned="2020-01-02T03:04:05")
        self.assertEqual(code, 2)
        self.assertIsNone(answer)

    def test_run_by_path_still_imports_a_fastapi_router(self):
        """Замер 17.09: первая редакция снимала каталог скрипта из sys.path
        только в `__main__`, а `import asyncio` наверху уже брал соседний
        `spa_core/monitoring/signal.py` — ImportError у ВСЕХ 20 модулей."""
        name = "spa_core.api.routers.competitive_watch"
        with tempfile.TemporaryDirectory(prefix="g29_imp_") as tmp:
            code, answer, err = _run_probe_by_path([name], tmp, pinned=_PIN.isoformat())
        self.assertEqual(code, 0, err)
        self.assertNotIn("import_failed", answer[name], err[-500:])
        self.assertTrue(answer[name]["routes"])

    def test_the_census_runner_carries_the_clock_to_the_door(self):
        """Проводка переписи, а не только зонд: `_run_http_probe(now=)` обязан
        донести ИМЕННО переданный момент до `_shared.now()`."""
        with tempfile.TemporaryDirectory(prefix="g29_run_") as tmp:
            answer, why = census._run_http_probe(Path(tmp), [], _TREE, now=_PIN)
            self.assertIsNotNone(answer, why)
            self.assertEqual(answer["__clock__"]["shared_now"], _PIN.isoformat())
            bare, why = census._run_http_probe(Path(tmp), [], _TREE)
            self.assertIsNotNone(bare, why)
            self.assertNotEqual(bare["__clock__"]["shared_now"], _PIN.isoformat())


def _stands(tmp: str) -> dict:
    return {k: str(Path(tmp) / k) for k in ("s1", "s2", "s3")}


class BatchClockWiringTests(unittest.TestCase):
    """`http_probe_batch`: один момент на все пять проб, и суд — у двери."""

    def test_every_probe_gets_the_same_moment_and_the_door_decides(self):
        seen = []

        def runner(stand_data, names, tree_root, now=None):
            seen.append(now)
            return {"__clock__": {"shared_now": now.isoformat()}}, ""

        with tempfile.TemporaryDirectory(prefix="g29_b_") as tmp:
            _out, meta = census.http_probe_batch(_stands(tmp), ["m"], _TREE,
                                                 runner=runner, now=_PIN)
        self.assertEqual(seen, [_PIN] * 5)
        self.assertIs(meta["clock_pinned"], True)
        self.assertNotIn("clock_reason", meta)

    def test_a_door_answering_another_time_is_not_pinned(self):
        """Часы переданы, а дверь ответила иное — «закреплено» было бы неправдой."""
        def runner(stand_data, names, tree_root, now=None):
            return {"__clock__": {"shared_now": "1999-01-01T00:00:00+00:00"}}, ""

        with tempfile.TemporaryDirectory(prefix="g29_b_") as tmp:
            _out, meta = census.http_probe_batch(_stands(tmp), ["m"], _TREE,
                                                 runner=runner, now=_PIN)
        self.assertIs(meta["clock_pinned"], False)
        self.assertIn("1999-01-01", meta["clock_reason"])

    def test_one_probe_whose_door_disagrees_unpins_the_whole_batch(self):
        calls = []

        def runner(stand_data, names, tree_root, now=None):
            calls.append(1)
            door = now.isoformat() if len(calls) != 3 else "1999-01-01T00:00:00+00:00"
            return {"__clock__": {"shared_now": door}}, ""

        with tempfile.TemporaryDirectory(prefix="g29_b_") as tmp:
            _out, meta = census.http_probe_batch(_stands(tmp), ["m"], _TREE,
                                                 runner=runner, now=_PIN)
        self.assertIs(meta["clock_pinned"], False)

    def test_a_runner_without_a_clock_parameter_is_not_handed_one(self):
        """Та же единственная копия правила, что у питоньих читателей
        (`clock_kwarg`): имя, которого зовущий не объявил, не подсовывается."""
        def runner(stand_data, names, tree_root):
            return {}, ""

        with tempfile.TemporaryDirectory(prefix="g29_b_") as tmp:
            _out, meta = census.http_probe_batch(_stands(tmp), ["m"], _TREE,
                                                 runner=runner, now=_PIN)
        self.assertIs(meta["clock_pinned"], False)

    def test_without_a_moment_nothing_is_claimed(self):
        def runner(stand_data, names, tree_root, now=None):
            self.assertIsNone(now)
            return {}, ""

        with tempfile.TemporaryDirectory(prefix="g29_b_") as tmp:
            _out, meta = census.http_probe_batch(_stands(tmp), ["m"], _TREE,
                                                 runner=runner)
        self.assertIs(meta["clock_pinned"], False)
        self.assertNotIn("clock_reason", meta)

    def test_the_row_carries_the_batch_clock_verdict(self):
        empty = {"routes": {}, "refused": {}, "elapsed_s": {}}
        route = {"routes": {"/r": {"v": 1}}, "refused": {}, "elapsed_s": {}}
        probes = (route, route, route, route, empty)
        self.assertIs(census.classify_http_reader("m", probes, clock_pinned=True)
                      ["clock_injected"], True)
        self.assertIs(census.classify_http_reader("m", probes)["clock_injected"], False)


class MeasureWiringTests(unittest.TestCase):
    """Проводка в `measure()` — по ФОРМЕ вызова, а не по подстроке.

    Полный `measure` гонит перепись минутами, поэтому здесь сверяется, ЧЕМ
    связаны аргументы двух зовов: момент прогона уходит в партию, а вердикт
    двери — в строку. Снятие любого из двух не краснило бы ничего другого.
    """

    @staticmethod
    def _calls(func_name):
        import ast
        import inspect
        tree = ast.parse(inspect.getsource(census.measure).lstrip())
        return [node for node in ast.walk(tree)
                if isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == func_name]

    def test_the_run_moment_reaches_the_batch(self):
        import ast
        calls = self._calls("http_probe_batch")
        self.assertEqual(len(calls), 1)
        kw = {k.arg: k.value for k in calls[0].keywords}
        self.assertIn("now", kw)
        self.assertIsInstance(kw["now"], ast.Name)
        self.assertEqual(kw["now"].id, "now")

    def test_the_door_verdict_reaches_the_row(self):
        import ast
        calls = self._calls("classify_http_reader")
        self.assertEqual(len(calls), 1)
        kw = {k.arg: k.value for k in calls[0].keywords}
        self.assertIn("clock_pinned", kw)
        names = {n.id for n in ast.walk(kw["clock_pinned"]) if isinstance(n, ast.Name)}
        consts = {n.value for n in ast.walk(kw["clock_pinned"]) if isinstance(n, ast.Constant)}
        self.assertIn("http_meta", names)
        self.assertIn("clock_pinned", consts)


class ResponseBodyTests(unittest.TestCase):
    """Ответ-объект сравнивается по ТЕЛУ, а не по адресу в памяти."""

    def test_two_equal_json_responses_compare_equal(self):
        from starlette.responses import JSONResponse
        one = probe._call(lambda: JSONResponse({"a": 1}))
        two = probe._call(lambda: JSONResponse({"a": 1}))
        self.assertEqual(one, two)
        self.assertEqual(one["__body__"], {"a": 1})
        self.assertEqual(one["__status__"], 200)
        self.assertNotIn("object at 0x", json.dumps(one))

    def test_different_bodies_compare_different(self):
        """Обратный контроль: равенство выше не должно быть «всё равно всему»."""
        from starlette.responses import JSONResponse
        self.assertNotEqual(probe._call(lambda: JSONResponse({"a": 1})),
                            probe._call(lambda: JSONResponse({"a": 2})))

    def test_the_status_code_is_part_of_the_answer(self):
        from starlette.responses import JSONResponse
        self.assertNotEqual(probe._call(lambda: JSONResponse({"a": 1})),
                            probe._call(lambda: JSONResponse({"a": 1}, status_code=503)))

    def test_a_non_json_body_is_kept_as_text(self):
        from starlette.responses import PlainTextResponse
        self.assertEqual(probe._call(lambda: PlainTextResponse("hi"))["__body__"], "hi")

    def test_a_plain_dict_is_untouched(self):
        self.assertEqual(probe._call(lambda: {"status_code": 1}), {"status_code": 1})

    def test_a_streaming_body_is_marked_unread_not_compared(self):
        from starlette.responses import StreamingResponse
        answer = probe._call(lambda: StreamingResponse(iter([b"x"])))
        self.assertEqual(answer[probe.UNREAD_RESPONSE], "StreamingResponse")

    def test_an_unread_route_gets_its_own_cause_not_a_verdict(self):
        """Одинаковый ТИП ответа на всех стендах читался бы «нечувствителен»."""
        unread = {probe.UNREAD_RESPONSE: "StreamingResponse", "__status__": 200}
        empty = {"routes": {}, "refused": {}, "elapsed_s": {}}
        mod = {"routes": {"/s": unread, "/j": {"v": 1}}, "refused": {}, "elapsed_s": {}}
        mod_s2 = {"routes": {"/s": unread, "/j": {"v": 2}}, "refused": {}, "elapsed_s": {}}
        row = census.classify_http_reader("m", (mod, mod, mod_s2, mod, empty))
        self.assertEqual(row["routes"]["/s"]["cause"], census.CAUSE_RESPONSE_UNREAD)
        self.assertEqual(row["routes"]["/s"]["outcome"], census.READER_UNMEASURED)
        # сосед по модулю своего вердикта не теряет
        self.assertNotEqual(row["routes"]["/j"]["outcome"], census.READER_UNMEASURED)


# ── заказ G30: момент выдачи узнаётся по окну зова ──────────────────────────
#: Окна пяти проб в порядке вердикта (s1, s1 повторно, s2, s3, пустой).
_WINDOWS = ([100.0, 100.5], [300.0, 300.5], [150.0, 150.5], [200.0, 200.5],
            [250.0, 250.5])


def _probes(route_answers, windows=_WINDOWS, path="/r"):
    """Пять проб одного модуля с одним маршрутом ``path``."""
    out = []
    for ans, win in zip(route_answers, windows):
        entry = {"routes": {path: ans}, "refused": {}, "elapsed_s": {}}
        if win is not None:
            entry["window"] = {path: win}
        out.append(entry)
    return tuple(out)


class CallMomentTests(unittest.TestCase):
    """Правило окна — в обе стороны, и каждое звено отдельно."""

    def _answers(self, stamps, key="_fetched_at", body=None):
        return [dict(body or {"v": 1}, **{key: t}) for t in stamps]

    def test_a_stamp_inside_every_call_window_is_the_call_moment(self):
        answers = self._answers([100.2, 300.1, 150.3, 200.4, 250.0])
        self.assertEqual(census.call_moment_coords(answers, _WINDOWS), {"._fetched_at"})

    def test_a_stamp_outside_the_window_on_ONE_probe_is_not(self):
        """Где-то координата несёт не момент зова — значит может нести стенд."""
        answers = self._answers([100.2, 300.1, 150.3, 42.0, 250.0])
        self.assertEqual(census.call_moment_coords(answers, _WINDOWS), set())

    def test_a_probe_without_a_window_where_the_stamp_is_present_disqualifies(self):
        answers = self._answers([100.2, 300.1, 150.3, 200.4, 250.0])
        windows = list(_WINDOWS)
        windows[2] = None
        self.assertEqual(census.call_moment_coords(answers, windows), set())

    def test_no_window_on_the_repeated_s1_means_no_candidates(self):
        answers = self._answers([100.2, 300.1, 150.3, 200.4, 250.0])
        windows = list(_WINDOWS)
        windows[1] = None
        self.assertEqual(census.call_moment_coords(answers, windows), set())

    def test_a_derived_age_is_not_the_call_moment(self):
        """Производная от часов в окно не попадает — остаётся нестабильной."""
        answers = self._answers([0.2, 0.1, 0.3, 0.4, 0.0], key="age_s")
        self.assertEqual(census.call_moment_coords(answers, _WINDOWS), set())

    def test_a_stamp_absent_on_the_repeated_s1_is_not_a_moment(self):
        """Кандидат наблюдён ОБЕИМИ пробами одного стенда, а не одной."""
        answers = self._answers([100.2, 300.1, 150.3, 200.4, 250.0])
        answers[1] = {"v": 1}
        self.assertEqual(census.call_moment_coords(answers, _WINDOWS), set())

    def test_a_stamp_after_the_window_is_not_a_moment(self):
        """Будущая отметка стенда (``expires_at``) выше окна — не момент зова."""
        answers = self._answers([900.0] * 5, key="expires_at")
        self.assertEqual(census.call_moment_coords(answers, _WINDOWS), set())

    def test_a_boolean_is_never_a_moment(self):
        answers = [{"flag": True} for _ in range(5)]
        windows = [[0.5, 1.5]] * 5
        self.assertEqual(census.call_moment_coords(answers, windows), set())

    def test_absence_on_the_empty_probe_does_not_disqualify(self):
        answers = self._answers([100.2, 300.1, 150.3, 200.4])
        answers.append({"error": "нет файла"})
        self.assertEqual(census.call_moment_coords(answers, _WINDOWS), {"._fetched_at"})

    def test_nested_coordinates_use_the_census_path_notation(self):
        answers = [{"__body__": {"rows": [{"ts": t}]}}
                   for t in (100.2, 300.1, 150.3, 200.4, 250.0)]
        self.assertEqual(census.call_moment_coords(answers, _WINDOWS),
                         {".__body__.rows[0].ts"})


class CallMomentVerdictTests(unittest.TestCase):
    """Проводка в ``classify_http_reader``: вердикт стоит на стенде, не на часах."""

    def test_the_moment_no_longer_hides_an_insensitive_route(self):
        stamps = (100.2, 300.1, 150.3, 200.4, 250.0)
        answers = [{"v": 1, "_fetched_at": t} for t in stamps[:4]]
        answers.append({"v": None, "_fetched_at": stamps[4]})
        row = census.classify_http_reader("m", _probes(answers))
        route = row["routes"]["/r"]
        self.assertEqual(route["outcome"], census.READER_INSENSITIVE, route)
        self.assertEqual(route["call_moment_coords"], ["._fetched_at"])

    def test_without_windows_the_old_verdict_stands(self):
        """Обратный контроль: без окна ничего не снимается — прежний вердикт."""
        stamps = (100.2, 300.1, 150.3, 200.4, 250.0)
        answers = [{"v": 1, "_fetched_at": t} for t in stamps]
        row = census.classify_http_reader("m", _probes(answers, windows=[None] * 5))
        route = row["routes"]["/r"]
        self.assertEqual(route["cause"], census.CAUSE_RESTS_ON_UNSTABLE, route)
        self.assertNotIn("call_moment_coords", route)

    def test_the_empty_probe_is_compared_after_the_same_masking(self):
        """Ответ, не читавший стенд, узнаётся и тогда, когда у него есть отметка."""
        stamps = (100.2, 300.1, 150.3, 200.4, 250.0)
        answers = [{"pong": True, "ts": t} for t in stamps]
        row = census.classify_http_reader("m", _probes(answers))
        self.assertEqual(row["routes"]["/r"]["cause"], census.CAUSE_STAND_NOT_READ)

    def test_a_collapse_is_still_a_collapse(self):
        """Снятие момента не гасит улику: стенд, сдвинувший тело, виден."""
        stamps = (100.2, 300.1, 150.3, 200.4, 250.0)
        vals = ("B", "B", "B", "A", None)
        answers = [{"v": v, "ts": t} for v, t in zip(vals, stamps)]
        row = census.classify_http_reader("m", _probes(answers))
        self.assertEqual(row["routes"]["/r"]["outcome"], census.READER_LAST)

    def test_a_stamp_from_the_stand_keeps_the_route_unmeasured(self):
        """Отметка, на одной пробе взятая НЕ из зова, не снимается."""
        stamps = (100.2, 300.1, 7.0, 200.4, 250.0)
        answers = [{"v": 1, "_fetched_at": t} for t in stamps]
        row = census.classify_http_reader("m", _probes(answers))
        self.assertEqual(row["routes"]["/r"]["outcome"], census.READER_UNMEASURED)


class ProbeWindowTests(unittest.TestCase):
    """Зонд пишет окно зова, и отметка обработчика лежит внутри него."""

    def test_the_handlers_time_stamp_lies_inside_its_recorded_window(self):
        import importlib
        src = ("import time\n"
               "from fastapi import APIRouter\n"
               "router = APIRouter()\n"
               "@router.get('/t')\n"
               "def t():\n"
               "    return {'_fetched_at': time.time()}\n")
        with tempfile.TemporaryDirectory(prefix="g30_mod_") as tmp:
            (Path(tmp) / "g30_fake_router.py").write_text(src, encoding="utf-8")
            sys.path.insert(0, tmp)
            try:
                answer = probe.probe_modules(["g30_fake_router"])
            finally:
                sys.path.remove(tmp)
                sys.modules.pop("g30_fake_router", None)
                importlib.invalidate_caches()
        entry = answer["g30_fake_router"]
        start, end = entry["window"]["/t"]
        self.assertLessEqual(start, entry["routes"]["/t"]["_fetched_at"])
        self.assertLessEqual(entry["routes"]["/t"]["_fetched_at"], end)
        self.assertEqual(census.call_moment_coords(
            [entry["routes"]["/t"]] * 2, [entry["window"]["/t"]] * 2), {"._fetched_at"})


class ProbeBySymlinkTests(unittest.TestCase):
    def test_run_by_a_path_through_a_symlink_still_imports_a_fastapi_router(self):
        """Замер 17.09: дерево под `/tmp` (ссылка на `/private/tmp` на macOS) —
        интерпретатор кладёт в `sys.path[0]` разрешённый путь, сравнение
        `abspath` не совпадало, и `signal` снова затенялся у всех 20 модулей."""
        name = "spa_core.api.routers.competitive_watch"
        with tempfile.TemporaryDirectory(prefix="g30_link_") as tmp:
            link = Path(tmp) / "tree_link"
            link.symlink_to(_TREE, target_is_directory=True)
            mods = Path(tmp) / "m.json"
            out = Path(tmp) / "o.json"
            data = Path(tmp) / "data"
            data.mkdir()
            mods.write_text(json.dumps([name]), encoding="utf-8")
            env = dict(os.environ, PYTHONPATH=str(link))
            env[probe.DATA_DIR_ENV] = str(data)
            env[probe.CLOCK_ENV] = _PIN.isoformat()
            proc = subprocess.run(
                [sys.executable, str(link / "spa_core" / "monitoring" / "_http_reader_probe.py"),
                 str(mods), str(out)],
                cwd=str(link), env=env, capture_output=True, timeout=300)
            err = proc.stderr.decode("utf-8", "replace")
            self.assertEqual(proc.returncode, 0, err)
            answer = json.loads(out.read_text(encoding="utf-8"))
        self.assertNotIn("import_failed", answer[name], err[-500:])
        self.assertTrue(answer[name]["routes"])


if __name__ == "__main__":
    unittest.main()
