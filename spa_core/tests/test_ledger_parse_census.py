"""Контроли переписи повторного разбора хеш-лент (ADR-778, заказ G777 п. 1).

Каждый тест — ПОРВАННОЕ ЗВЕНО с названным звеном, плюс обратная сторона: перепись
обязана быть зелёной на целом контуре и красной на каждом порванном
(`.claude/rules/acceptance.md`, п. 3). Предмет мерится ИСХОДОМ — числом открытий файла и
вердиктом, — а не присутствием подстроки в источнике.

Ни одной литеральной даты здесь нет и быть не может: предмет переписи — байты, открытия и
секунды, а не календарь. Часы в предмет не входят вовсе, поэтому инъектировать нечего.
"""
from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from spa_core.monitoring import ledger_parse_census as lpc

LEDGER_REL = "fake_book/ledger.jsonl"

#: корень ДЕРЕВА, из которого идёт прогон — мера неполноты населения мерится по нему,
#: а не по тому дереву, где прибор случайно установлен.
_REPO = Path(__file__).resolve().parents[2]


def _write_ledger(data_dir: Path, lines: int = 3) -> Path:
    path = data_dir / LEDGER_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps({"seq": i, "payload": "x" * 64}) + "\n" for i in range(lines)),
        encoding="utf-8")
    return path


def _member(view, *, declared_opens: int = 1, ledger: str = LEDGER_REL) -> lpc.Member:
    return lpc.Member(id="fake_book", ledger=ledger, view=view,
                      declared_opens=declared_opens,
                      opens_reason="стенд: столько разборов делает вид стенда",
                      scoped_door=False,
                      scoped_reason="стенд области кэша не открывает")


def _view_builtin_open(times: int):
    """Вид, читающий через ``builtins.open`` — так читают три из четырёх реализаций."""
    def view(data_dir: Path):
        rows = []
        for _ in range(times):
            rows = []
            with open(Path(data_dir) / LEDGER_REL, "r", encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if line:
                        rows.append(json.loads(line))
        return rows
    return view


def _view_pathlib(data_dir: Path):
    """Вид, читающий через ``pathlib`` — ВТОРАЯ дверь (``io.open``), ровно
    ``sleeve/composer.py::load_ledger``."""
    text = (Path(data_dir) / LEDGER_REL).read_text(encoding="utf-8")
    return [json.loads(l) for l in text.splitlines() if l.strip()]


def _view_os_open(data_dir: Path):
    """Вид, читающий МИМО обеих наблюдаемых дверей (``os.open``) и отвечающий НЕПУСТО.
    Это и есть улика третьего исхода: ноль открытий тут не замер, а слепота прибора."""
    fd = os.open(str(Path(data_dir) / LEDGER_REL), os.O_RDONLY)
    try:
        raw = b""
        while chunk := os.read(fd, 65536):
            raw += chunk
    finally:
        os.close(fd)
    return [json.loads(l) for l in raw.decode().splitlines() if l.strip()]


class TestWholeCircuitGreen(unittest.TestCase):
    def test_a_view_that_parses_exactly_as_declared_yields_no_findings(self):
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_member(_view_builtin_open(1), declared_opens=1)],
                              tree_root=Path(td), parse_rounds=1)
            self.assertEqual(doc["findings"], [], doc["rows"])
            self.assertEqual(doc["unmeasured"], [])
            row = doc["rows"][0]
            self.assertEqual(row["opens"], 1)
            self.assertIsNotNone(row["parse_s"])
            self.assertIsNotNone(row["growth_factor"])


class TestTheSecondDoorIsWired(unittest.TestCase):
    """Положительный контроль двери ``io.open``: ``io.open is builtins.open`` истинно, но
    ``pathlib`` зовёт объект через пространство имён ``io``. Если прибор смотрит одну
    дверь, этот тест даёт НЕ «0 открытий», а третий исход — и это проверяется."""

    def test_a_pathlib_reader_is_counted(self):
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_member(_view_pathlib, declared_opens=1)],
                              tree_root=Path(td), parse_rounds=1)
            self.assertEqual(doc["unmeasured"], [], "pathlib-читатель ушёл в третий исход — "
                                                    "значит дверь io.open не подменяется")
            self.assertEqual(doc["rows"][0]["opens"], 1)

    def test_watching_only_builtins_open_would_blind_the_probe(self):
        """Обратная сторона того же звена: подменив ТОЛЬКО ``builtins.open``, тот же
        pathlib-читатель даёт ноль — и прибор обязан назвать это НЕ ИЗМЕРЕНО."""
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            opens, answer, err = lpc.count_opens(data / LEDGER_REL,
                                                 lambda: _view_pathlib(data))
            self.assertIsNone(err)
            self.assertEqual(opens, 1, "обе двери обязаны быть подменены — иначе ноль")
            self.assertTrue(answer)


class TestOpensDriftIsAFinding(unittest.TestCase):
    def test_an_extra_parse_appearing_is_named(self):
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_member(_view_builtin_open(4), declared_opens=1)],
                              tree_root=Path(td), parse_rounds=1)
            kinds = [f["kind"] for f in doc["findings"]]
            self.assertIn(lpc.F_OPENS_DRIFTED, kinds)
            self.assertIn("4", doc["findings"][0]["text"])

    def test_a_necessary_parse_disappearing_is_named_too(self):
        """Расхождение значимо в ОБЕ стороны: у объявленного числа есть причина, и
        исчезновение названного разбора (например свежего ``verify()``) есть такая же
        находка, как появление лишнего."""
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_member(_view_builtin_open(1), declared_opens=2)],
                              tree_root=Path(td), parse_rounds=1)
            self.assertIn(lpc.F_OPENS_DRIFTED, [f["kind"] for f in doc["findings"]])


class TestMarginFloor(unittest.TestCase):
    def test_a_view_without_growth_headroom_is_a_finding(self):
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data, lines=200)
            doc = lpc.measure(data, members=[_member(_view_builtin_open(1), declared_opens=1)],
                              budget_s=1e-9, min_factor=4.0,
                              tree_root=Path(td), parse_rounds=1)
            kinds = [f["kind"] for f in doc["findings"]]
            self.assertIn(lpc.F_MARGIN_SHORT, kinds)

    def test_a_roomy_view_is_not_a_finding(self):
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data, lines=1)
            doc = lpc.measure(data, members=[_member(_view_builtin_open(1), declared_opens=1)],
                              budget_s=10.0, min_factor=4.0,
                              tree_root=Path(td), parse_rounds=1)
            self.assertEqual(doc["findings"], [])


class TestThirdOutcomeIsNeverAZero(unittest.TestCase):
    """Инв. #17: измерено · измерено и равно нулю · НЕ ИЗМЕРЕНО — три разных значения."""

    def test_a_reader_going_past_both_doors_is_unmeasured_not_zero(self):
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_member(_view_os_open, declared_opens=1)],
                              tree_root=Path(td), parse_rounds=1)
            self.assertEqual(len(doc["unmeasured"]), 1)
            self.assertIn(lpc.U_DOOR_NOT_WATCHED, doc["unmeasured"][0]["unmeasured"])
            self.assertEqual(doc["findings"], [],
                             "слепой замер не вправе выдавать находку — у него нет числа")

    def test_zero_opens_with_an_empty_answer_IS_a_measurement(self):
        """Обратная сторона: пустая лента и пустой ответ — ноль есть ЗАМЕР, и запас при
        нулевой цене НЕ ОПРЕДЕЛЁН, а не «бесконечен»."""
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data, lines=0)
            doc = lpc.measure(data, members=[_member(lambda d: [], declared_opens=0)],
                              tree_root=Path(td), parse_rounds=1)
            self.assertEqual(doc["unmeasured"], [])
            row = doc["rows"][0]
            self.assertEqual(row["opens"], 0)
            self.assertIsNone(row["growth_factor"])

    def test_a_raising_view_names_the_exception(self):
        def boom(_d):
            raise RuntimeError("лента рвана")
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_member(boom)], tree_root=Path(td),
                              parse_rounds=1)
            self.assertEqual(len(doc["unmeasured"]), 1)
            why = doc["unmeasured"][0]["unmeasured"]
            self.assertIn(lpc.U_VIEW_RAISED, why)
            self.assertIn("лента рвана", why)

    def test_a_missing_ledger_is_unmeasured(self):
        with TemporaryDirectory() as td:
            data = Path(td)
            doc = lpc.measure(data, members=[_member(_view_builtin_open(1))],
                              tree_root=Path(td), parse_rounds=1)
            self.assertIn(lpc.U_LEDGER_ABSENT, doc["unmeasured"][0]["unmeasured"])

    def test_an_unresolvable_view_is_unmeasured(self):
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_member("spa_core.nope.missing:latest")],
                              tree_root=Path(td), parse_rounds=1)
            self.assertIn(lpc.U_VIEW_UNRESOLVED, doc["unmeasured"][0]["unmeasured"])

    def test_a_resolvable_but_NON_CALLABLE_view_is_unmeasured(self):
        """Третья форма неразрешимости, и самая тихая: модуль импортируется, имя есть, а
        вызвать его нельзя (переименовали функцию в константу). Подставить вместо него
        пустой список значило бы выдать «не измерено» за «измерено и пусто»."""
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(
                data,
                members=[_member("spa_core.monitoring.ledger_parse_census:LEDGER_LITERAL")],
                tree_root=Path(td), parse_rounds=1)
            self.assertEqual(len(doc["unmeasured"]), 1, doc["rows"])
            self.assertIn(lpc.U_VIEW_UNRESOLVED, doc["unmeasured"][0]["unmeasured"])
            self.assertIsNone(doc["rows"][0]["opens"])

    def test_a_view_path_without_a_function_name_is_unmeasured(self):
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_member("spa_core.monitoring.ledger_parse_census")],
                              tree_root=Path(td), parse_rounds=1)
            self.assertIn(lpc.U_VIEW_UNRESOLVED, doc["unmeasured"][0]["unmeasured"])


class TestExitCodesAreThreeDistinctAnswers(unittest.TestCase):
    """Отображение «три исхода → три числа» проверяется у :func:`lpc.exit_code` прямо."""

    def _doc(self, *, unmeasured=(), findings=(), undeclared=(), missing=()):
        return {"unmeasured": list(unmeasured), "findings": list(findings),
                "population": {"code_files_undeclared": list(undeclared),
                               "code_files_missing": list(missing)}}

    def test_clean_is_zero(self):
        self.assertEqual(lpc.exit_code(self._doc()), 0)

    def test_a_finding_is_one(self):
        self.assertEqual(lpc.exit_code(self._doc(findings=[{"kind": "x"}])), 1)

    def test_a_population_drift_is_one_too(self):
        self.assertEqual(lpc.exit_code(self._doc(undeclared=["spa_core/fifth.py"])), 1)
        self.assertEqual(lpc.exit_code(self._doc(missing=["spa_core/gone.py"])), 1)

    def test_unmeasured_is_two(self):
        self.assertEqual(lpc.exit_code(self._doc(unmeasured=[{"id": "x"}])), 2)

    def test_unmeasured_beats_a_finding(self):
        """Слепой член И находка у соседа обязаны дать 2: «не измерено» никогда не
        выдаётся за «измерено, вот что нашли»."""
        self.assertEqual(
            lpc.exit_code(self._doc(unmeasured=[{"id": "blind"}], findings=[{"kind": "x"}])), 2)

    def test_the_cli_returns_two_when_the_ledgers_are_absent(self):
        """Та же лестница через настоящий CLI: на пустом дереве лент нет ⇒ 2, а не 0."""
        with TemporaryDirectory() as td:
            data = Path(td)
            self.assertEqual(
                lpc.main(["--data-dir", str(data), "--tree-root", str(td),
                          "--parse-rounds", "1"]), 2)

    def test_both_outcomes_are_visible_in_one_doc(self):
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data, lines=50)
            blind = _member(_view_os_open, declared_opens=1)
            loud = lpc.Member(id="loud", ledger=LEDGER_REL, view=_view_builtin_open(9),
                              declared_opens=1, opens_reason="стенд",
                              scoped_door=False, scoped_reason="стенд")
            doc = lpc.measure(data, members=[blind, loud], tree_root=Path(td),
                              parse_rounds=1)
            self.assertTrue(doc["unmeasured"])
            self.assertTrue(doc["findings"])
            self.assertEqual(lpc.exit_code(doc), 2)


class TestParseCostTakesTheBestRun(unittest.TestCase):
    """Цена разбора — ЛУЧШЕЕ из прогонов, и часы здесь ВХОД, а не стенные.

    Шум машины завышает цену, а завышенная цена даёт завышенную тревогу: член с
    настоящим запасом 50× выглядел бы тесным от того, что рядом шёл чужой прогон.
    Проверяется исходом на инъектированных часах, а не ожиданием реального времени.
    """

    def test_the_minimum_of_the_runs_wins(self):
        ticks = iter([0.0, 9.0,    # прогон 1 — 9.0 с (шум)
                      9.0, 10.0,   # прогон 2 — 1.0 с (лучший)
                      10.0, 15.0]) # прогон 3 — 5.0 с
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            real = lpc.time.perf_counter
            lpc.time.perf_counter = lambda: next(ticks)
            try:
                took = lpc.parse_seconds(data / LEDGER_REL, rounds=3)
            finally:
                lpc.time.perf_counter = real
            self.assertAlmostEqual(took, 1.0, places=9)


class TestPopulationIsClosed(unittest.TestCase):
    def test_a_fifth_ledger_in_the_tree_is_named(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            pkg = root / "spa_core" / "fifth"
            pkg.mkdir(parents=True)
            (pkg / "contract.py").write_text('LEDGER = "ledger.jsonl"\n', encoding="utf-8")
            found = lpc.ledger_code_files(root)
            self.assertIn("spa_core/fifth/contract.py", found)

    def test_test_files_are_not_population(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            tests = root / "spa_core" / "tests"
            tests.mkdir(parents=True)
            (tests / "test_x.py").write_text('L = "ledger.jsonl"\n', encoding="utf-8")
            self.assertEqual(lpc.ledger_code_files(root), [])

    def test_the_probe_itself_is_the_only_named_exclusion(self):
        """Прибор несёт литерал по построению. Исключение одно, оно НАЗВАНО константой, и
        второго молчаливого исключения в обходе нет."""
        with TemporaryDirectory() as td:
            root = Path(td)
            self_path = root / lpc.SELF_REL
            self_path.parent.mkdir(parents=True)
            self_path.write_text('L = "ledger.jsonl"\n', encoding="utf-8")
            other = root / "spa_core" / "other.py"
            other.write_text('L = "ledger.jsonl"\n', encoding="utf-8")
            # СОСЕД прибора по каталогу: расширение исключения до «spa_core/monitoring/»
            # (мутация #7) унесло бы и его, а он — законное население
            neighbour = root / "spa_core" / "monitoring" / "other_census.py"
            neighbour.parent.mkdir(parents=True, exist_ok=True)
            neighbour.write_text('L = "ledger.jsonl"\n', encoding="utf-8")
            found = lpc.ledger_code_files(root)
            self.assertEqual(found, ["spa_core/monitoring/other_census.py",
                                     "spa_core/other.py"],
                             "исключён обязан быть РОВНО один названный файл, не каталог")

    def test_the_declared_code_population_matches_the_real_tree(self):
        """ХРАПОВИК: объявленный перечень файлов сверяется с настоящим деревом. Пятая
        лента (или переезд существующей) краснит здесь, а не находится через полгода."""
        self.assertEqual(sorted(lpc.ledger_code_files()), sorted(lpc.LEDGER_CODE_FILES))


class TestEveryDeclaredNumberHasAReason(unittest.TestCase):
    def test_no_member_carries_a_bare_number(self):
        for m in lpc.LEDGERS:
            with self.subTest(member=m.id):
                self.assertTrue(m.opens_reason.strip(),
                                f"{m.id}: объявленное число открытий без причины")
                self.assertTrue(m.scoped_reason.strip(),
                                f"{m.id}: утверждение про область кэша без причины")
                self.assertGreaterEqual(m.declared_opens, 0)

    def test_every_declared_view_resolves(self):
        """Переименованный или уехавший вид обязан краснеть ЗДЕСЬ, а не отдавать третий
        исход в тихом отчёте."""
        for m in lpc.LEDGERS:
            with self.subTest(member=m.id):
                fn, why = lpc.resolve_view(m)
                self.assertIsNotNone(fn, f"{m.id}: {why}")

    def test_exactly_one_member_claims_the_scoped_cache_door(self):
        """Ответ заказа G777 п. 1, закреплённый тестом: порядок ADR-777 живёт в ОДНОЙ
        реализации из четырёх. Переезд ещё одной ленты на область — правка этого числа
        вместе с ADR, а не молчаливое расхождение."""
        on_door = [m.id for m in lpc.LEDGERS if m.scoped_door]
        self.assertEqual(on_door, ["research_factory"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


# ══════════════════════════════════════════════════════════════════════════════════════
# Второй множитель: сколько РАЗ прогон зовёт вид (ADR-779, заказ G778 п. 3, цикл #896)
#
# Каждый тест ниже — порванное звено с названным звеном плюс обратная сторона. Стенд
# держит вид в НАСТОЯЩЕМ модуле (``types.ModuleType`` в ``sys.modules``), а не отдаёт
# готовое вызываемое: счётчик подменяет атрибут модуля, и стенд, обошедший эту дверь,
# проверял бы не ту дверь, которой пользуется прибор.
# ══════════════════════════════════════════════════════════════════════════════════════
import sys
import types


def _stand_module(name: str, times: int = 1):
    """Модуль со своим видом — ровно та форма, которую подменяет счётчик вызовов."""
    mod = types.ModuleType(name)

    def latest(data_dir):
        rows = []
        for _ in range(times):
            rows = []
            with open(Path(data_dir) / LEDGER_REL, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        rows.append(json.loads(line))
        return rows

    mod.latest = latest
    sys.modules[name] = mod
    return mod


def _drop_module(name: str):
    sys.modules.pop(name, None)


def _stand_member(name: str, *, declared_opens: int = 1) -> lpc.Member:
    return lpc.Member(id="fake_book", ledger=LEDGER_REL, view=f"{name}:latest",
                      declared_opens=declared_opens,
                      opens_reason="стенд: столько разборов делает вид стенда",
                      scoped_door=False, scoped_reason="стенд области кэша не открывает")


def _stand_workload(runner, *, calls: int = 1, wid: str = "stand_run") -> lpc.Workload:
    return lpc.Workload(id=wid, run=runner, reason="стенд: прогон читает ленту стенда",
                        declared_calls={"fake_book": calls},
                        calls_reason={"fake_book": "стенд: столько зовов делает прогон стенда"})


def _calls_runner(mod_name: str, times: int):
    """Прогон, зовущий вид ЧЕРЕЗ ПРОСТРАНСТВО ИМЁН МОДУЛЯ — так делают все сегодняшние
    потребители (``rf_read.latest(...)``), и только так счётчик их видит."""
    def run(data_dir):
        mod = sys.modules[mod_name]
        out = None
        for _ in range(times):
            out = mod.latest(data_dir)
        return out
    return run


class TestTheSecondMultiplierIsMeasured(unittest.TestCase):
    """Целый контур: вызовов столько, сколько объявлено ⇒ ни одной находки."""

    def test_calls_per_workload_are_counted_and_priced(self):
        name = "spa_stand_second_multiplier_green"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=Path(td),
                              parse_rounds=1,
                              workloads=[_stand_workload(_calls_runner(name, 3), calls=3)])
            wl = doc["workloads"]
            self.assertEqual(wl["unmeasured"], [], wl["rows"])
            self.assertEqual(wl["rows"][0]["calls"], {"fake_book": 3})
            self.assertEqual(wl["unreached"], {})
            # полная цена ЕСТЬ произведение, а не цена вызова
            row, per_call = wl["rows"][0], doc["rows"][0]["cost_s"]
            self.assertAlmostEqual(row["price_s"], 3 * per_call, places=9)

    def test_the_product_is_what_the_margin_is_computed_from(self):
        """Обратная сторона: при том же виде ДВА зова дают вдвое меньший запас, чем один.
        Если бы прибор мерил только вызов, оба прогона были бы неотличимы."""
        name = "spa_stand_second_multiplier_product"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(
                data, members=[_stand_member(name)], tree_root=Path(td), parse_rounds=1,
                workloads=[_stand_workload(_calls_runner(name, 1), calls=1, wid="one"),
                           _stand_workload(_calls_runner(name, 2), calls=2, wid="two")])
            by = {r["id"]: r for r in doc["workloads"]["rows"]}
            self.assertEqual(by["one"]["calls"], {"fake_book": 1})
            self.assertEqual(by["two"]["calls"], {"fake_book": 2})
            self.assertAlmostEqual(by["one"]["growth_factor"],
                                   2 * by["two"]["growth_factor"], places=6)


class TestCallsDriftIsAFindingBothWays(unittest.TestCase):
    def test_an_extra_call_appearing_is_named(self):
        name = "spa_stand_calls_more"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=Path(td),
                              parse_rounds=1,
                              workloads=[_stand_workload(_calls_runner(name, 3), calls=2)])
            kinds = [f["kind"] for f in doc["findings"]]
            self.assertIn(lpc.F_CALLS_DRIFTED, kinds, doc["findings"])

    def test_a_declared_call_disappearing_is_named_too(self):
        """Исчезновение названного зова значимо ровно так же: у объявленного числа есть
        причина, и починка, тихо снявшая нужный зов, не вправе зеленеть."""
        name = "spa_stand_calls_fewer"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=Path(td),
                              parse_rounds=1,
                              workloads=[_stand_workload(_calls_runner(name, 1), calls=2)])
            kinds = [f["kind"] for f in doc["findings"]]
            self.assertIn(lpc.F_CALLS_DRIFTED, kinds, doc["findings"])


class TestWorkloadMarginFloor(unittest.TestCase):
    def test_a_workload_without_headroom_is_a_finding(self):
        name = "spa_stand_wl_tight"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=Path(td),
                              parse_rounds=1, workload_budget_s=1e-9,
                              workloads=[_stand_workload(_calls_runner(name, 1), calls=1)])
            kinds = [f["kind"] for f in doc["findings"]]
            self.assertIn(lpc.F_WORKLOAD_MARGIN_SHORT, kinds, doc["findings"])

    def test_a_roomy_workload_is_not_a_finding(self):
        name = "spa_stand_wl_roomy"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=Path(td),
                              parse_rounds=1, workload_budget_s=1e6,
                              workloads=[_stand_workload(_calls_runner(name, 1), calls=1)])
            kinds = [f["kind"] for f in doc["findings"]]
            self.assertNotIn(lpc.F_WORKLOAD_MARGIN_SHORT, kinds, doc["findings"])


class TestWorkloadThirdOutcomeIsNeverAZero(unittest.TestCase):
    def test_a_raising_workload_names_the_exception(self):
        name = "spa_stand_wl_raises"
        _stand_module(name)
        self.addCleanup(_drop_module, name)

        def boom(_data_dir):
            raise RuntimeError("сборка не поднялась")

        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=Path(td),
                              parse_rounds=1, workloads=[_stand_workload(boom, calls=1)])
            row = doc["workloads"]["rows"][0]
            self.assertIn(lpc.U_WORKLOAD_RAISED, row["unmeasured"] or "")
            self.assertIsNone(row["calls"], "упавший прогон не вправе отдать число вызовов")
            self.assertEqual(lpc.exit_code(doc), 2)

    def test_zero_calls_for_everyone_is_the_probe_not_proven(self):
        """Прогон дошёл до конца, но счётчик не встал: ноль у ВСЕХ членов — это НЕ
        «прогон лент не читает». Условие приёма прогона в население названо в самом
        прибое, и оно же делает это правило самопроверяющим."""
        name = "spa_stand_wl_silent"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=Path(td),
                              parse_rounds=1,
                              workloads=[_stand_workload(lambda _d: "ничего не звал", calls=0)])
            row = doc["workloads"]["rows"][0]
            self.assertIn(lpc.U_PROBE_NOT_PROVEN, row["unmeasured"] or "")
            self.assertEqual(lpc.exit_code(doc), 2)

    def test_a_view_bound_at_import_slips_past_the_counter_AND_is_measured_in_the_tree(self):
        """Дверь счётчика одна, и у неё есть обратная сторона.

        Потребитель, связавший имя на импорте, держит НАСТОЯЩУЮ функцию и подмены не
        видит — прибор обязан не врать про это молча: ноль у всех членов уходит в
        третий исход, а сама форма ищется обходом дерева, поэтому «таких нет» есть
        ЗАМЕР, а не умолчание.
        """
        name = "spa_stand_wl_import_bound"
        mod = _stand_module(name)
        self.addCleanup(_drop_module, name)
        bound = mod.latest           # связано на «импорте», мимо атрибута модуля
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=Path(td),
                              parse_rounds=1,
                              workloads=[_stand_workload(lambda d: bound(d), calls=1)])
            row = doc["workloads"]["rows"][0]
            self.assertIn(lpc.U_PROBE_NOT_PROVEN, row["unmeasured"] or "",
                          "связанное на импорте имя прошло мимо счётчика и это выдали за ноль")

    def test_the_import_binding_form_is_found_in_a_tree_that_has_one(self):
        """Положительный контроль обхода: посаженное связывание обязано найтись, иначе
        «связываний нет» на боевом дереве ничего не значит."""
        with TemporaryDirectory() as td:
            root = Path(td)
            (root / "spa_core" / "planted").mkdir(parents=True)
            (root / "spa_core" / "planted" / "caller.py").write_text(
                "from spa_core.research_factory.read import latest\n", encoding="utf-8")
            hits = lpc.direct_name_bindings(root, lpc.LEDGERS)
            self.assertEqual(len(hits), 1, hits)
            self.assertIn("planted/caller.py", hits[0])

    def test_a_member_no_workload_reaches_is_unmeasured_not_free(self):
        name = "spa_stand_wl_unreached"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        other = "spa_stand_wl_unreached_other"
        _stand_module(other)
        self.addCleanup(_drop_module, other)
        m_called = _stand_member(name)
        m_idle = lpc.Member(id="idle_book", ledger=LEDGER_REL, view=f"{other}:latest",
                            declared_opens=1, opens_reason="стенд",
                            scoped_door=False, scoped_reason="стенд")
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            wl = lpc.Workload(id="stand_run", run=_calls_runner(name, 1),
                              reason="стенд", declared_calls={"fake_book": 1, "idle_book": 0},
                              calls_reason={"fake_book": "стенд", "idle_book": "стенд"})
            doc = lpc.measure(data, members=[m_called, m_idle], tree_root=Path(td),
                              parse_rounds=1, workloads=[wl])
            self.assertIn("idle_book", doc["workloads"]["unreached"])
            self.assertIn(lpc.U_NO_WORKLOAD_REACHES,
                          doc["workloads"]["unreached"]["idle_book"])
            self.assertEqual(lpc.exit_code(doc), 2,
                             "вид без единого измеренного читателя — третий исход, не чистота")

    def test_a_callable_view_has_no_site_to_count_at_and_says_so(self):
        """Вид, переданный готовым вызываемым, подменить негде. Прибор обязан НАЗВАТЬ
        это по каждому такому члену, а не молча считать его нулём."""
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_member(_view_builtin_open(1))],
                              tree_root=Path(td), parse_rounds=1,
                              workloads=[_stand_workload(lambda _d: None, calls=0)])
            row = doc["workloads"]["rows"][0]
            self.assertIn(lpc.U_VIEW_NOT_PATCHABLE, row["unmeasured"] or "")

    def test_a_called_member_without_a_measured_price_refuses_the_product(self):
        """Произведение без второго множителя не число: вызовы сосчитаны, цена одного
        вызова не измерена ⇒ НЕ ИЗМЕРЕНО, а не цена «ноль»."""
        name = "spa_stand_wl_no_price"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            wl = _stand_workload(_calls_runner(name, 1), calls=1)
            out = lpc.measure_workloads(data, members=[_stand_member(name)], workloads=[wl],
                                        price_by_id={"fake_book": None})
            self.assertIn(lpc.U_PRICE_UNKNOWN, out["rows"][0]["unmeasured"] or "")


class TestTheCounterPutsTheViewBack(unittest.TestCase):
    """Прибор не вправе оставить дерево подменённым — ни после удачи, ни после отказа."""

    def test_the_module_attribute_is_restored_after_a_clean_run(self):
        name = "spa_stand_restore_ok"
        mod = _stand_module(name)
        self.addCleanup(_drop_module, name)
        before = mod.latest
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            lpc.count_calls([_stand_member(name)],
                            _stand_workload(_calls_runner(name, 1)), data)
        self.assertIs(mod.latest, before)

    def test_the_module_attribute_is_restored_after_the_workload_raises(self):
        name = "spa_stand_restore_boom"
        mod = _stand_module(name)
        self.addCleanup(_drop_module, name)
        before = mod.latest

        def boom(_d):
            raise RuntimeError("упал посреди прогона")

        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            counts, cannot, answer, err = lpc.count_calls(
                [_stand_member(name)], _stand_workload(boom), data)
        self.assertIsNotNone(err)
        self.assertIs(mod.latest, before, "упавший прогон оставил модуль подменённым")


class TestViewReferenceCountIsAMeasurement(unittest.TestCase):
    """Замер рядом с решением: неполноту населения прогонов видно числом."""

    def test_the_defining_file_counts_as_a_reference(self):
        """Внутримодульный зов (``composer.py`` зовёт свой ``load_ledger``) — читатель,
        и наивный поиск по ``pkg.mod`` его теряет."""
        sleeve = [m for m in lpc.LEDGERS if m.id == "sleeve_aggressive"][0]
        refs = lpc.view_reference_files(sleeve, _REPO)
        self.assertIn("spa_core/strategy_lab/sleeve/composer.py", refs)

    def test_the_nested_import_form_is_found(self):
        """Второй вызов ``research_factory.read.latest`` за сборку приходит из
        ``capital_shadow/readiness.py``, и пишет он форму ``from … import read`` —
        поиск подстроки ``research_factory.read`` его НЕ находит."""
        rf = [m for m in lpc.LEDGERS if m.id == "research_factory"][0]
        refs = lpc.view_reference_files(rf, _REPO)
        self.assertIn("spa_core/capital_shadow/readiness.py", refs,
                      "вложенный читатель потерян — значит мера неполноты занижена")


class TestEveryDeclaredCallHasAReason(unittest.TestCase):
    def test_no_workload_carries_a_bare_number(self):
        for w in lpc.WORKLOADS:
            self.assertTrue(w.reason.strip(), w.id)
            for mid in w.declared_calls:
                self.assertTrue((w.calls_reason.get(mid) or "").strip(),
                                f"{w.id}/{mid}: число объявлено без причины")

    def test_every_workload_declares_every_member(self):
        ids = {m.id for m in lpc.LEDGERS}
        for w in lpc.WORKLOADS:
            self.assertEqual(set(w.declared_calls), ids,
                             f"{w.id}: население объявленных вызовов разошлось с лентами")

    def test_at_least_one_workload_declares_a_second_call(self):
        """Предмет заказа G778 п. 3 — что множитель НЕ единица. Если это перестанет быть
        правдой у всего населения, прибор обязан покраснеть, а не тихо потерять предмет."""
        self.assertTrue(any(n > 1 for w in lpc.WORKLOADS for n in w.declared_calls.values()),
                        "ни один объявленный прогон не зовёт вид дважды — предмет исчез")

    def test_a_member_called_by_only_ONE_workload_is_not_unreached(self):
        """«Дошёл ли до вида хоть один прогон» есть МАКСИМУМ по прогонам, а не минимум:
        член, которого зовёт одна сборка и не зовёт нажатие, читателя ИМЕЕТ."""
        name = "spa_stand_reach_max"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(
                data, members=[_stand_member(name)], tree_root=Path(td), parse_rounds=1,
                workloads=[_stand_workload(_calls_runner(name, 1), calls=1, wid="calls_it"),
                           lpc.Workload(id="ignores_it", run=_calls_runner(name, 0),
                                        reason="стенд: прогон эту ленту не читает",
                                        declared_calls={"fake_book": 0},
                                        calls_reason={"fake_book": "стенд"})])
            self.assertEqual(doc["workloads"]["unreached"], {},
                             "вид, которого зовёт один из прогонов, объявлен без читателя")
            self.assertEqual(doc["workloads"]["calls_by_member"], {"fake_book": 1})

    def test_the_uncountable_member_is_NAMED_beside_the_countable_one(self):
        """Смешанное население: один член считается, другой — нет. Прибор обязан назвать
        второго ПОИМЁННО, иначе прогон выглядит измеренным целиком."""
        name = "spa_stand_mixed"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            m_opaque = lpc.Member(id="opaque_book", ledger=LEDGER_REL,
                                  view=_view_builtin_open(1), declared_opens=1,
                                  opens_reason="стенд", scoped_door=False,
                                  scoped_reason="стенд")
            wl = lpc.Workload(id="stand_run", run=_calls_runner(name, 1), reason="стенд",
                              declared_calls={"fake_book": 1, "opaque_book": 0},
                              calls_reason={"fake_book": "стенд", "opaque_book": "стенд"})
            doc = lpc.measure(data, members=[_stand_member(name), m_opaque],
                              tree_root=Path(td), parse_rounds=1, workloads=[wl])
            row = doc["workloads"]["rows"][0]
            self.assertIsNotNone(row["not_countable"], "несчитаемый член не назван вовсе")
            self.assertIn("opaque_book", row["not_countable"])
            self.assertIn(lpc.U_VIEW_NOT_PATCHABLE, row["not_countable"]["opaque_book"])
