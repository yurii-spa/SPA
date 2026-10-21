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
from typing import Optional

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


def _member(view, *, declared_opens: int = 1, ledger: str = LEDGER_REL,
            mid: str = "fake_book", ledger_id: str = "fake_book",
            invoke=None) -> lpc.Member:
    return lpc.Member(id=mid, ledger_id=ledger_id, ledger=ledger, view=view,
                      invoke=invoke,
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
            #: ВТОРОЙ вид той же ленты стенда: личность пары своя, личность ФАЙЛА общая —
            #: ровно форма, ради которой заказ G780 п. 1 и делался
            loud = lpc.Member(id="loud", ledger_id="fake_book", ledger=LEDGER_REL,
                              view=_view_builtin_open(9),
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
        вместе с ADR, а не молчаливое расхождение.

        Утверждение это про ЛЕНТУ (реализацию), а не про пару «лента ↔ вид»: с цикла #900
        у ``research_factory`` два вида, и оба живут в ОДНОМ модуле с одной областью кэша.
        Считать тут пары значило бы сменить предмет теста, не сказав об этом, — поэтому
        счёт идёт по ``ledger_id``, и рядом проверяется, что виды ОДНОЙ ленты объявляют
        дверь ОДИНАКОВО: дверь есть свойство реализации, а не читателя.
        """
        on_door = sorted({m.ledger_id for m in lpc.LEDGERS if m.scoped_door})
        self.assertEqual(on_door, ["research_factory"])
        by_ledger: dict = {}
        for m in lpc.LEDGERS:
            by_ledger.setdefault(m.ledger_id, set()).add(m.scoped_door)
        for lid, doors in sorted(by_ledger.items()):
            self.assertEqual(len(doors), 1,
                             f"{lid}: виды одной ленты объявили РАЗНУЮ дверь кэша — "
                             f"дверь есть свойство реализации, а не читателя")


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


def _stand_member(name: str, *, declared_opens: int = 1, mid: str = "fake_book",
                  ledger_id: str = "fake_book", attr: str = "latest") -> lpc.Member:
    return lpc.Member(id=mid, ledger_id=ledger_id, ledger=LEDGER_REL,
                      view=f"{name}:{attr}",
                      declared_opens=declared_opens,
                      opens_reason="стенд: столько разборов делает вид стенда",
                      scoped_door=False, scoped_reason="стенд области кэша не открывает")


#: Частота у стенда НЕ ОБЪЯВЛЕНА намеренно: стенд не агент, расписания у него нет и
#: журнала тоже. Третий исход у суточной цены тогда ВЕРЕН, и тесты про него — отдельные
#: (``TestTheThirdMultiplier*``), со своими настоящими plist и журналом.
_STAND_CADENCE = lpc.Cadence(plist=None, agent=None, log=None,
                             reason="стенд: ни расписания, ни журнала — частоту мерить нечем")


def _stand_workload(runner, *, calls: int = 1, wid: str = "stand_run",
                    opens: Optional[int] = None,
                    cadence: Optional[lpc.Cadence] = None) -> lpc.Workload:
    """Прогон стенда. ``opens`` по умолчанию равно ``calls``: вид стенда разбирает ленту
    РОВНО раз за зов, поэтому модель и замер у него сходятся — и расхождение в тестах ниже
    добывается НАРОЧНО, а не случайной неточностью стенда."""
    return lpc.Workload(id=wid, run=runner, reason="стенд: прогон читает ленту стенда",
                        declared_calls={"fake_book": calls},
                        calls_reason={"fake_book": "стенд: столько зовов делает прогон стенда"},
                        declared_opens={"fake_book": calls if opens is None else opens},
                        opens_reason={"fake_book": "стенд: столько разборов делает прогон"},
                        cadence=cadence or _STAND_CADENCE)


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
        m_idle = lpc.Member(id="idle_book", ledger_id="fake_book", ledger=LEDGER_REL,
                            view=f"{other}:latest",
                            declared_opens=1, opens_reason="стенд",
                            scoped_door=False, scoped_reason="стенд")
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            wl = lpc.Workload(id="stand_run", run=_calls_runner(name, 1),
                              reason="стенд", declared_calls={"fake_book": 1, "idle_book": 0},
                              calls_reason={"fake_book": "стенд", "idle_book": "стенд"},
                              declared_opens={"fake_book": 1},
                              opens_reason={"fake_book": "стенд"},
                              cadence=_STAND_CADENCE)
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
            counts, cannot, answer, err, opens, _sites = lpc.count_calls(
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
                                        calls_reason={"fake_book": "стенд"},
                                        declared_opens={"fake_book": 0},
                                        opens_reason={"fake_book": "стенд"},
                                        cadence=_STAND_CADENCE)])
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
            m_opaque = lpc.Member(id="opaque_book", ledger_id="fake_book",
                                  ledger=LEDGER_REL,
                                  view=_view_builtin_open(1), declared_opens=1,
                                  opens_reason="стенд", scoped_door=False,
                                  scoped_reason="стенд")
            wl = lpc.Workload(id="stand_run", run=_calls_runner(name, 1), reason="стенд",
                              declared_calls={"fake_book": 1, "opaque_book": 0},
                              calls_reason={"fake_book": "стенд", "opaque_book": "стенд"},
                              declared_opens={"fake_book": 1},
                              opens_reason={"fake_book": "стенд"},
                              cadence=_STAND_CADENCE)
            doc = lpc.measure(data, members=[_stand_member(name), m_opaque],
                              tree_root=Path(td), parse_rounds=1, workloads=[wl])
            row = doc["workloads"]["rows"][0]
            self.assertIsNotNone(row["not_countable"], "несчитаемый член не назван вовсе")
            self.assertIn("opaque_book", row["not_countable"])
            self.assertIn(lpc.U_VIEW_NOT_PATCHABLE, row["not_countable"]["opaque_book"])


# ══════════════════════════════════════════════════════════════════════════════════════
# ТРЕТИЙ множитель: сколько раз за СУТКИ зовут сам прогон (заказ G779, цикл #898).
#
# Полная суточная цена есть произведение ТРЁХ: цена разбора × разборов за прогон ×
# прогонов за сутки. Третьего множителя у прибора не было вовсе, и ADR-779 назвал его
# отсутствие своим остатком. Частота бывает двух природ, и мерятся они РАЗНЫМ: расписание
# ОБЪЯВЛЕНО в plist, нажатие владельца НАБЛЮДАЕМО только по записи. Нет ни того, ни
# другого ⇒ третий исход, а не ноль.
#
# Часы здесь — ВХОД (`now=`), п. 1 порядка предпочтения `.claude/rules/deployment.md`:
# закреплены обе стороны — и отметки журнала, и момент, от которого считается окно, —
# поэтому ни один тест ниже не постареет от календаря.
# FROZEN-DATE-OK: injected-clock — `now=_NOW` передаётся в observed_daily_rate/
# measure_cadence/measure, а отметки журнала строятся ОТ `_NOW` арифметикой часов
# ══════════════════════════════════════════════════════════════════════════════════════
import builtins
import datetime as _dt
import io
import plistlib
from typing import Sequence

#: якорь, от которого строится КАЖДАЯ отметка в стендовых журналах ниже
_NOW = _dt.datetime(2026, 10, 18, 12, 0, 0, tzinfo=_dt.timezone.utc)


def _write_plist(path: Path, **keys) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as fh:
        plistlib.dump({"Label": "com.spa.stand", **keys}, fh)
    return path


def _write_agent_log(path: Path, *, agent: str, starts_h_ago: Sequence[float],
                     now: _dt.datetime = _NOW) -> Path:
    """Журнал агента в форме, которую пишет ``scripts/agent_template.sh``."""
    lines = []
    for h in starts_h_ago:
        ts = (now - _dt.timedelta(hours=h)).strftime("%Y-%m-%dT%H:%M:%SZ")
        lines.append(f"[{ts}] START agent={agent} pid=1234")
        lines.append(f"[{ts}] EXIT agent={agent} code=0")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


class TestDeclaredRateComesFromTheSchedule(unittest.TestCase):
    """Объявленная частота читается из plist — и её отсутствие НЕ ноль."""

    def test_an_interval_becomes_runs_per_day(self):
        with TemporaryDirectory() as td:
            pl = _write_plist(Path(td) / "com.spa.stand.plist", StartInterval=300)
            rate, interval, why = lpc.declared_daily_rate(pl)
            self.assertIsNone(why)
            self.assertEqual(interval, 300.0)
            self.assertAlmostEqual(rate, 288.0, places=6)

    def test_a_calendar_list_is_counted_by_its_moments(self):
        with TemporaryDirectory() as td:
            pl = _write_plist(Path(td) / "c.plist",
                              StartCalendarInterval=[{"Hour": 8}, {"Hour": 20}])
            rate, interval, why = lpc.declared_daily_rate(pl)
            self.assertIsNone(why)
            self.assertEqual(rate, 2.0)
            self.assertIsNone(interval, "календарное расписание интервала не объявляет")

    def test_a_single_calendar_moment_is_once_a_day(self):
        with TemporaryDirectory() as td:
            pl = _write_plist(Path(td) / "c.plist", StartCalendarInterval={"Hour": 8})
            self.assertEqual(lpc.declared_daily_rate(pl)[0], 1.0)

    def test_a_missing_plist_is_unmeasured_not_zero(self):
        rate, interval, why = lpc.declared_daily_rate(Path("/nope/никакого.plist"))
        self.assertIsNone(rate, "ненайденный plist выдан частотой")
        self.assertIn(lpc.U_SCHEDULE_UNREADABLE, why or "")

    def test_a_plist_without_any_schedule_is_unmeasured(self):
        """Агент-долгожитель (KeepAlive) расписания не несёт: «ноль прогонов в сутки» было
        бы про него ложью, а «раз в сутки» — выдумкой."""
        with TemporaryDirectory() as td:
            pl = _write_plist(Path(td) / "c.plist", KeepAlive=True)
            rate, _i, why = lpc.declared_daily_rate(pl)
            self.assertIsNone(rate)
            self.assertIn(lpc.U_SCHEDULE_UNREADABLE, why or "")

    def test_a_broken_plist_names_the_exception(self):
        with TemporaryDirectory() as td:
            pl = Path(td) / "c.plist"
            pl.write_bytes("\x00не plist вовсе".encode("utf-8"))
            rate, _i, why = lpc.declared_daily_rate(pl)
            self.assertIsNone(rate)
            self.assertIn(lpc.U_SCHEDULE_UNREADABLE, why or "")


class TestObservedRateRefusesAWindowDeeperThanTheLog(unittest.TestCase):
    """ЗАМЕР цикла #898, ради которого третий исход тут и написан.

    Один и тот же журнал: окно 24ч дало 272 запуска = 272/сутки, окно 168ч — 675 запусков
    = 96/сутки. Второе число не про частоту вовсе: журнал начинался 62ч назад, и
    168-часовое окно поделило настоящие запуски на пустоту, которой в журнале нет. Это
    свойство ИЗМЕРИТЕЛЯ, выданное за свойство предмета — тот же класс, что календарь и
    номер процесса в `.claude/rules/deployment.md`.
    """

    def test_starts_in_the_window_become_a_rate(self):
        with TemporaryDirectory() as td:
            log = _write_agent_log(Path(td) / "a.log", agent="stand",
                                   starts_h_ago=[0.5, 6.0, 12.0, 20.0, 30.0, 47.0])
            rate, count, why = lpc.observed_daily_rate(log, "stand", now=_NOW, window_h=24.0)
            self.assertIsNone(why)
            self.assertEqual(count, 4, "в окно 24ч попали не те запуски")
            self.assertAlmostEqual(rate, 4.0, places=6)

    def test_a_wider_window_divides_the_same_starts_by_more_days(self):
        """Обратная сторона: на ДОСТАТОЧНО глубоком журнале более широкое окно — законный
        ответ, и он меньше. Отказ ниже вызван глубиной журнала, а не широтой окна."""
        with TemporaryDirectory() as td:
            log = _write_agent_log(Path(td) / "a.log", agent="stand",
                                   starts_h_ago=[1.0, 25.0, 100.0, 170.0])
            rate, count, why = lpc.observed_daily_rate(log, "stand", now=_NOW, window_h=168.0)
            self.assertIsNone(why, "журнал глубиной 170ч при окне 168ч — отказ неверен")
            self.assertEqual(count, 3)
            self.assertAlmostEqual(rate, 3.0 / 7.0, places=6)

    def test_a_log_shallower_than_the_window_is_UNMEASURED_not_a_smaller_number(self):
        with TemporaryDirectory() as td:
            log = _write_agent_log(Path(td) / "a.log", agent="stand",
                                   starts_h_ago=[0.2, 1.0, 2.0])
            rate, count, why = lpc.observed_daily_rate(log, "stand", now=_NOW, window_h=24.0)
            self.assertIsNone(rate, "частота выдана по журналу, которого на окно не хватает")
            self.assertIsNone(count)
            self.assertIn(lpc.U_LOG_SHALLOWER, why or "")
            self.assertIn("3", why or "", "в причине не названо число настоящих запусков")

    def test_an_empty_log_is_unmeasured_because_depth_is_unknown(self):
        with TemporaryDirectory() as td:
            log = Path(td) / "a.log"
            log.write_text("ничего похожего на START\n", encoding="utf-8")
            rate, _c, why = lpc.observed_daily_rate(log, "stand", now=_NOW)
            self.assertIsNone(rate)
            self.assertIn(lpc.U_RATE_NOT_OBSERVABLE, why or "")

    def test_a_missing_log_is_unmeasured(self):
        rate, _c, why = lpc.observed_daily_rate(Path("/nope/никакого.log"), "stand", now=_NOW)
        self.assertIsNone(rate)
        self.assertIn(lpc.U_RATE_NOT_OBSERVABLE, why or "")

    def test_only_the_named_agent_is_counted(self):
        """Журнал подписан именем агента, и чужие строки в частоту не входят: иначе
        общий журнал двух агентов удвоил бы частоту обоим."""
        with TemporaryDirectory() as td:
            log = Path(td) / "a.log"
            _write_agent_log(log, agent="stand", starts_h_ago=[1.0, 2.0, 30.0])
            extra = "\n".join(
                f"[{(_NOW - _dt.timedelta(hours=h)).strftime('%Y-%m-%dT%H:%M:%SZ')}] "
                f"START agent=stranger pid=7" for h in (1.5, 3.0))
            log.write_text(log.read_text(encoding="utf-8") + extra + "\n", encoding="utf-8")
            rate, count, why = lpc.observed_daily_rate(log, "stand", now=_NOW, window_h=24.0)
            self.assertIsNone(why)
            self.assertEqual(count, 2, "в частоту вошли запуски чужого агента")


class TestCadencePutsTheTwoNumbersSideBySide(unittest.TestCase):
    def test_a_schedule_never_observed_is_a_finding(self):
        """Расписание говорит 288 прогонов в сутки, журнал — ни одного. Это находка
        (агент не загружен либо падает до записи), а НЕ бесплатный прогон."""
        with TemporaryDirectory() as td:
            root = Path(td)
            _write_plist(root / "launchd/com.spa.stand.plist", StartInterval=300)
            log = _write_agent_log(root / "a.log", agent="stand",
                                   starts_h_ago=[30.0, 40.0, 50.0])  # глубоко, но НЕ в окне
            cad = lpc.Cadence(plist="launchd/com.spa.stand.plist", agent="stand",
                              log=str(log), reason="стенд: расписание есть, журнал есть")
            out = lpc.measure_cadence(_stand_workload(lambda d: None, cadence=cad),
                                      tree_root=root, now=_NOW, window_h=24.0)
            self.assertAlmostEqual(out["declared_per_day"], 288.0, places=6)
            self.assertEqual(out["observed_count"], 0, "ноль запусков в окне не измерен")
            self.assertEqual([f["kind"] for f in out["findings"]],
                             [lpc.F_SCHEDULE_NEVER_OBSERVED])

    def test_a_live_schedule_with_runs_is_not_a_finding(self):
        """Обратный контроль: исправная пара «расписание + запуски» не краснит ничего."""
        with TemporaryDirectory() as td:
            root = Path(td)
            _write_plist(root / "launchd/com.spa.stand.plist", StartInterval=3600)
            log = _write_agent_log(root / "a.log", agent="stand",
                                   starts_h_ago=[0.5, 5.0, 23.0, 40.0])
            cad = lpc.Cadence(plist="launchd/com.spa.stand.plist", agent="stand",
                              log=str(log), reason="стенд")
            out = lpc.measure_cadence(_stand_workload(lambda d: None, cadence=cad),
                                      tree_root=root, now=_NOW, window_h=24.0)
            self.assertEqual(out["findings"], [])
            self.assertAlmostEqual(out["declared_per_day"], 24.0, places=6)
            self.assertAlmostEqual(out["observed_per_day"], 3.0, places=6)
            self.assertIsNone(out["unmeasured"])

    def test_an_owner_press_has_no_rate_and_says_WHY(self):
        """Нажатие владельца: ни расписания, ни журнала. Третий исход обязан назвать
        ПРИЧИНУ — «не измерено» без причины неотличимо от забывчивости (инв. #17)."""
        out = lpc.measure_cadence(_stand_workload(lambda d: None), now=_NOW)
        self.assertIsNone(out["declared_per_day"])
        self.assertIsNone(out["observed_per_day"])
        self.assertIn(lpc.U_RATE_NOT_OBSERVABLE, out["unmeasured"] or "")
        self.assertTrue((out["reason"] or "").strip())


class TestDailyPriceIsAProductOfThree(unittest.TestCase):
    def test_the_daily_price_is_price_times_rate(self):
        name = "spa_stand_daily_product"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            data.mkdir()
            _write_ledger(data)
            _write_plist(root / "launchd/com.spa.stand.plist", StartInterval=3600)
            log = _write_agent_log(root / "a.log", agent="stand",
                                   starts_h_ago=[1.0, 2.0, 3.0, 30.0])
            cad = lpc.Cadence(plist="launchd/com.spa.stand.plist", agent="stand",
                              log=str(log), reason="стенд")
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=root,
                              parse_rounds=1, now=_NOW, window_h=24.0,
                              workloads=[_stand_workload(_calls_runner(name, 2), calls=2,
                                                         cadence=cad)])
            row = doc["workloads"]["rows"][0]
            self.assertIsNone(row["daily_unmeasured"])
            self.assertAlmostEqual(row["rate_per_day"], 3.0, places=6)
            self.assertAlmostEqual(row["price_day_s"], row["price_s"] * 3.0, places=9)
            self.assertAlmostEqual(row["share_of_day"], row["price_day_s"] / 86400.0,
                                   places=12)
            self.assertIn("НАБЛЮДЕНИЕ", row["rate_source"])

    def test_the_observed_rate_WINS_over_the_declared_one(self):
        """Два числа рядом, но суточная цена считается по НАБЛЮДЁННОМУ: расписание
        говорит, сколько прогонов должно быть, журнал — сколько их было, и платим мы за
        случившиеся."""
        name = "spa_stand_rate_source"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            data.mkdir()
            _write_ledger(data)
            _write_plist(root / "launchd/com.spa.stand.plist", StartInterval=900)  # 96/сутки
            log = _write_agent_log(root / "a.log", agent="stand",
                                   starts_h_ago=[1.0, 2.0, 30.0])              # 2/сутки
            cad = lpc.Cadence(plist="launchd/com.spa.stand.plist", agent="stand",
                              log=str(log), reason="стенд")
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=root,
                              parse_rounds=1, now=_NOW, window_h=24.0,
                              workloads=[_stand_workload(_calls_runner(name, 1), cadence=cad)])
            row = doc["workloads"]["rows"][0]
            self.assertAlmostEqual(row["cadence"]["declared_per_day"], 96.0, places=6)
            self.assertAlmostEqual(row["rate_per_day"], 2.0, places=6)

    def test_the_declared_rate_is_used_when_the_log_cannot_answer(self):
        """Журнал мельче окна ⇒ наблюдения нет, но расписание есть. Суточная цена тогда
        считается по ОБЪЯВЛЕНИЮ, и источник НАЗВАН — иначе два разных числа выглядели бы
        одним."""
        name = "spa_stand_rate_fallback"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            data.mkdir()
            _write_ledger(data)
            _write_plist(root / "launchd/com.spa.stand.plist", StartInterval=1800)
            log = _write_agent_log(root / "a.log", agent="stand", starts_h_ago=[0.5, 1.0])
            cad = lpc.Cadence(plist="launchd/com.spa.stand.plist", agent="stand",
                              log=str(log), reason="стенд")
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=root,
                              parse_rounds=1, now=_NOW, window_h=24.0,
                              workloads=[_stand_workload(_calls_runner(name, 1), cadence=cad)])
            row = doc["workloads"]["rows"][0]
            self.assertAlmostEqual(row["rate_per_day"], 48.0, places=6)
            self.assertIn("ОБЪЯВЛЕНИЕ", row["rate_source"])
            self.assertIn(lpc.U_LOG_SHALLOWER, row["cadence"]["unmeasured"] or "")

    def test_without_any_rate_the_daily_price_is_UNMEASURED_and_the_code_is_two(self):
        name = "spa_stand_daily_unmeasured"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=Path(td),
                              parse_rounds=1, now=_NOW,
                              workloads=[_stand_workload(_calls_runner(name, 1))])
            row = doc["workloads"]["rows"][0]
            self.assertIsNone(row["price_day_s"], "суточная цена выдана без третьего множителя")
            self.assertIn(lpc.U_DAILY_PRICE_UNKNOWN, row["daily_unmeasured"])
            self.assertIsNotNone(row["price_s"], "цена прогона обязана остаться измеренной")
            self.assertEqual(lpc.exit_code(doc), 2,
                             "неизмеренная суточная цена выдана за измеренный вердикт")

    def test_a_price_above_its_own_interval_is_a_finding(self):
        """Порог НЕ придуман: он взят из расписания самого прогона. Разбор, который стои́т
        дороже собственного интервала, означает, что прогон не успевает к своему же
        следующему запуску."""
        name = "spa_stand_interval"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            data.mkdir()
            _write_ledger(data)
            _write_plist(root / "launchd/com.spa.stand.plist", StartInterval=2)
            log = _write_agent_log(root / "a.log", agent="stand",
                                   starts_h_ago=[1.0, 2.0, 30.0])
            cad = lpc.Cadence(plist="launchd/com.spa.stand.plist", agent="stand",
                              log=str(log), reason="стенд")
            out = lpc.measure_workloads(
                data, members=[_stand_member(name)],
                workloads=[_stand_workload(_calls_runner(name, 1), cadence=cad)],
                parse_by_id={"fake_book": 5.0},   # разбор дороже интервала
                tree_root=root, now=_NOW, window_h=24.0)
            kinds = [f["kind"] for f in out["findings"]]
            self.assertIn(lpc.F_PRICE_EXCEEDS_INTERVAL, kinds)

    def test_a_price_below_its_own_interval_is_not_a_finding(self):
        """Обратный контроль того же порога."""
        name = "spa_stand_interval_ok"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            root = Path(td)
            data = root / "data"
            data.mkdir()
            _write_ledger(data)
            _write_plist(root / "launchd/com.spa.stand.plist", StartInterval=300)
            log = _write_agent_log(root / "a.log", agent="stand",
                                   starts_h_ago=[1.0, 2.0, 30.0])
            cad = lpc.Cadence(plist="launchd/com.spa.stand.plist", agent="stand",
                              log=str(log), reason="стенд")
            out = lpc.measure_workloads(
                data, members=[_stand_member(name)],
                workloads=[_stand_workload(_calls_runner(name, 1), cadence=cad)],
                parse_by_id={"fake_book": 0.01},
                tree_root=root, now=_NOW, window_h=24.0)
            self.assertNotIn(lpc.F_PRICE_EXCEEDS_INTERVAL,
                             [f["kind"] for f in out["findings"]])


class TestThePriceIsCountedAtTheFileNotAtTheDeclaredView(unittest.TestCase):
    """Предмет цикла #898, и он КРУПНЕЕ третьего множителя.

    До этого цикла цена прогона считалась как «открытий за ОДИН вызов вида × зовов вида».
    Замер у самого файла показал, что предсказание неверно у двух прогонов из трёх: сборка
    Mission Control разбирает ленту research_factory **8** раз против 4 предсказанных, а
    экран Oracle — **4** раза против НУЛЯ (его объявленная причина гласила «экран этой
    ленты не читает»). Причина одна: у ленты ВТОРОЙ вид (``read.cio_view``), которого
    население членов не объявляет, и зовут его через другую читающую модель.
    """

    def _runner_reading_past_the_view(self, mod_name: str, *, calls: int, extra: int):
        """Прогон зовёт объявленный вид ``calls`` раз И ещё ``extra`` раз разбирает ленту
        МИМО него — ровно форма ``cio_view``: тот же файл, другой вход."""
        def run(data_dir):
            mod = sys.modules[mod_name]
            out = None
            for _ in range(calls):
                out = mod.latest(data_dir)
            for _ in range(extra):
                with open(Path(data_dir) / LEDGER_REL, "r", encoding="utf-8") as fh:
                    [json.loads(l) for l in fh if l.strip()]
            return out
        return run

    def test_parses_past_the_declared_view_are_counted_and_priced(self):
        name = "spa_stand_past_the_view"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            wl = _stand_workload(
                self._runner_reading_past_the_view(name, calls=1, extra=3),
                calls=1, opens=4)
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=Path(td),
                              parse_rounds=1, now=_NOW, workloads=[wl])
            row = doc["workloads"]["rows"][0]
            self.assertEqual(row["calls"], {"fake_book": 1}, "зовы вида посчитаны неверно")
            self.assertEqual(row["opens"], {"fake_book": 4}, "разборы у файла не сосчитаны")
            self.assertEqual(row["opens_modelled"], {"fake_book": 1})
            # цена считается по ЗАМЕРУ, а не по модели: вчетверо больше
            parse_s = doc["rows"][0]["parse_s"]
            self.assertAlmostEqual(row["price_s"], 4 * parse_s, places=9)
            kinds = [f["kind"] for f in row["findings"]]
            self.assertIn(lpc.F_MODEL_DISAGREES, kinds,
                          "модель разошлась с замером и об этом НЕ сказано")

    def test_the_model_ABOVE_the_measurement_is_named_too_and_the_direction_is_said(self):
        """Проверка симметрична, поэтому и контроль двусторонний: член объявляет ТРИ
        разбора за вызов, а вид стенда делает один ⇒ модель ВЫШЕ замера. Это другой
        дефект (сработал кэш либо чтение исчезло), и находка обязана назвать направление,
        а не выдать вчерашнее объяснение."""
        name = "spa_stand_model_above"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_stand_member(name, declared_opens=3)],
                              tree_root=Path(td), parse_rounds=1, now=_NOW,
                              workloads=[_stand_workload(_calls_runner(name, 1), calls=1)])
            row = doc["workloads"]["rows"][0]
            self.assertEqual(row["opens"], {"fake_book": 1})
            self.assertEqual(row["opens_modelled"], {"fake_book": 3})
            found = [f for f in row["findings"] if f["kind"] == lpc.F_MODEL_DISAGREES]
            self.assertTrue(found, "модель ВЫШЕ замера не названа вовсе")
            self.assertIn("модель ВЫШЕ замера", found[0]["text"])

    def test_a_workload_whose_model_matches_the_measurement_is_silent(self):
        """Обратная сторона: там, где модель предсказывает замер (экран Sherlock —
        единственный такой из трёх), находки быть не должно."""
        name = "spa_stand_model_matches"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=Path(td),
                              parse_rounds=1, now=_NOW,
                              workloads=[_stand_workload(_calls_runner(name, 2), calls=2)])
            row = doc["workloads"]["rows"][0]
            self.assertEqual(row["opens"], {"fake_book": 2})
            self.assertEqual(row["opens_modelled"], {"fake_book": 2})
            self.assertEqual([f["kind"] for f in row["findings"]], [])

    def _drift_kinds(self, *, declared: int, extra: int, name: str):
        """Один прогон стенда с НАРОЧНЫМ расхождением «объявлено ↔ измерено»."""
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            wl = _stand_workload(
                self._runner_reading_past_the_view(name, calls=1, extra=extra),
                calls=1, opens=declared)
            doc = lpc.measure(data, members=[_stand_member(name)], tree_root=Path(td),
                              parse_rounds=1, now=_NOW, workloads=[wl])
            return [f["kind"] for f in doc["workloads"]["rows"][0]["findings"]]

    # Две стороны одного расхождения — ДВА ОТДЕЛЬНЫХ теста, а не один с ``subTest``.
    # Причина измерена (ADR-761, цикл #876): утверждение под ``subTest`` не меняет НАБОР
    # упавших имён, по которому судит прогон мутаций по дельте, и носитель claim
    # становится ему невидим — мутация «расхождение не называется вовсе» ВЫЖИЛА бы при
    # зелёном тесте. Замер этого цикла: 2 выживших мутации до разделения, 0 после.
    def test_MORE_parses_than_declared_is_a_finding(self):
        """Лишний разбор появился — находка."""
        self.assertIn(lpc.F_WORKLOAD_OPENS_DRIFTED,
                      self._drift_kinds(declared=2, extra=3, name="spa_stand_opens_more"))

    def test_FEWER_parses_than_declared_is_a_finding_too(self):
        """Обратная сторона: нужный разбор ИСЧЕЗ. Починка, тихо снявшая ``verify()``,
        зеленеть не вправе — объявленное число есть замер с причиной, а не потолок."""
        self.assertIn(lpc.F_WORKLOAD_OPENS_DRIFTED,
                      self._drift_kinds(declared=9, extra=3, name="spa_stand_opens_fewer"))

    def test_the_second_door_is_wired_for_the_WORKLOAD_too(self):
        """Счётчик разборов прогона обязан смотреть ОБЕ двери. Если бы он смотрел только
        ``builtins.open``, читатель через ``pathlib`` дал бы ноль разборов при непустом
        ответе — ровно промах, из которого вырос третий исход на уровне вызова."""
        name = "spa_stand_workload_pathlib"
        _stand_module(name)
        self.addCleanup(_drop_module, name)

        def run(data_dir):
            sys.modules[name].latest(data_dir)          # дверь builtins
            return _view_pathlib(data_dir)              # дверь io (pathlib)

        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            counts, _cannot, _answer, err, opens, _sites = lpc.count_calls(
                [_stand_member(name)], _stand_workload(run, calls=1, opens=2), data)
            self.assertIsNone(err)
            self.assertEqual(counts, {"fake_book": 1})
            self.assertEqual(opens, {"fake_book": 2},
                             "вторая дверь (io.open) у счётчика прогона не подменена")

    def test_both_doors_are_restored_after_the_workload_raises(self):
        """Прибор возвращает ОБЕ двери и после отказа прогона: оставленная подмена
        означала бы, что следующий замер идёт по подменённому дереву."""
        name = "spa_stand_doors_back"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        before_b, before_io = builtins.open, io.open

        def boom(_d):
            raise RuntimeError("упал посреди прогона")

        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            _counts, _cannot, _answer, err, _opens, _sites = lpc.count_calls(
                [_stand_member(name)], _stand_workload(boom), data)
        self.assertIsNotNone(err)
        self.assertIs(builtins.open, before_b, "дверь builtins.open осталась подменённой")
        self.assertIs(io.open, before_io, "дверь io.open осталась подменённой")


class TestEveryDeclaredOpensAndCadenceHasAReason(unittest.TestCase):
    """Ни одного голого числа у настоящего населения прогонов."""

    def test_no_workload_carries_bare_opens(self):
        """РАЗБОРЫ объявляются у ФАЙЛА, ЗОВЫ — у ПАРЫ «лента ↔ вид», и у каждого числа
        своя причина. Ключи здесь РАЗНЫЕ намеренно (цикл #900): сведя их к одному, мы
        вернули бы ту самую экономию, из-за которой второй вид объявить было нечем."""
        ledger_ids = {m.ledger_id for m in lpc.LEDGERS}
        pair_ids = {m.id for m in lpc.LEDGERS}
        for w in lpc.WORKLOADS:
            self.assertEqual(set(w.declared_opens), ledger_ids,
                             f"{w.id}: население объявленных РАЗБОРОВ разошлось с ЛЕНТАМИ")
            self.assertEqual(set(w.declared_calls), pair_ids,
                             f"{w.id}: население объявленных ЗОВОВ разошлось с ПАРАМИ")
            for lid in w.declared_opens:
                self.assertTrue((w.opens_reason.get(lid) or "").strip(),
                                f"{w.id}/{lid}: число разборов объявлено без причины")
            for mid in w.declared_calls:
                self.assertTrue((w.calls_reason.get(mid) or "").strip(),
                                f"{w.id}/{mid}: число зовов объявлено без причины")

    def test_every_cadence_carries_a_reason(self):
        for w in lpc.WORKLOADS:
            self.assertTrue((w.cadence.reason or "").strip(),
                            f"{w.id}: частота объявлена без причины")

    def test_the_scheduled_workload_points_at_a_plist_that_EXISTS(self):
        """Объявленный путь расписания проверяется по дереву: ссылка на исчезнувший plist
        молча превратила бы объявленную частоту в «не измерено»."""
        scheduled = [w for w in lpc.WORKLOADS if w.cadence.plist]
        self.assertTrue(scheduled, "ни один прогон не объявляет расписания — предмет исчез")
        for w in scheduled:
            self.assertTrue((_REPO / w.cadence.plist).is_file(),
                            f"{w.id}: plist {w.cadence.plist} в дереве не найден")
            rate, _i, why = lpc.declared_daily_rate(_REPO / w.cadence.plist)
            self.assertIsNone(why, f"{w.id}: расписание не читается: {why}")
            self.assertGreater(rate, 0.0)

    def test_the_model_summed_over_views_MATCHES_the_declared_parses(self):
        """ПРЕЕМНИК теста цикла #898, а не его снятие (инв. #16) — и замена объявлена.

        Прежний тест требовал, чтобы у какого-то прогона разборов было БОЛЬШЕ, чем
        «открытий за зов × зовов», и сам назвал условие своей замены: *«Если это
        перестанет быть правдой, прибор обязан потерять не предмет, а находку — и тест
        скажет, что предмет исчез»*. Цикл #900 ровно это и сделал: объявил ВТОРОЙ вид
        ленты, и сумма по видам сошлась с замером у файла на всех трёх прогонах.

        Оставить прежний тест значило бы держать зелёным утверждение о модели, которой у
        прибора больше нет: арифметически «8 > 2×2» верно и сегодня, но прибор так уже не
        считает — тест мерил бы снятую формулу. Поэтому предикат заменён на преемника:
        **сумма по ОБЪЯВЛЕННЫМ видам обязана сходиться с объявленными разборами**, и
        расхождение означает читателя, которого население не знает.
        """
        opens_per_call = {m.id: m.declared_opens for m in lpc.LEDGERS}
        ledger_of = {m.id: m.ledger_id for m in lpc.LEDGERS}
        for w in lpc.WORKLOADS:
            modelled: dict = {}
            for mid, calls in w.declared_calls.items():
                lid = ledger_of[mid]
                modelled[lid] = modelled.get(lid, 0) + opens_per_call[mid] * calls
            for lid, declared in sorted(w.declared_opens.items()):
                self.assertEqual(
                    modelled.get(lid, 0), declared,
                    f"{w.id}/{lid}: сумма по объявленным видам {modelled.get(lid, 0)} не "
                    f"сходится с объявленными разборами {declared} — либо у ленты есть "
                    f"вид, которого население не знает, либо число объявлено наугад")

    def test_the_form_itself_is_USED_or_the_subject_has_vanished(self):
        """Вторая половина того же преемника: форма «лента ↔ НЕСКОЛЬКО видов» обязана
        быть ЗАНЯТА. Если у каждой ленты снова ровно один вид, то дефект ADR-780
        («второй вид объявить нечем») стал бы непредставимым молча — и тест скажет об
        этом, а не промолчит зелёным."""
        by_ledger: dict = {}
        for m in lpc.LEDGERS:
            by_ledger.setdefault(m.ledger_id, []).append(m.id)
        multi = {lid: ids for lid, ids in by_ledger.items() if len(ids) > 1}
        self.assertTrue(multi,
                        "ни у одной ленты не объявлено двух видов — форма не занята, и "
                        "предмет заказа G780 п. 1 исчез из населения")
        self.assertIn("research_factory", multi,
                      "второй вид research_factory (read.cio_view) исчез из населения")

    def test_the_two_identities_of_a_ledger_agree_in_the_live_population(self):
        """Ключ, по которому складывается произведение, сверяется сам с собой: один файл —
        одна личность, одна личность — один файл. Без этой сверки член с новой личностью на
        том же пути молча удвоил бы цену своего файла."""
        self.assertEqual(lpc.ledger_id_split(lpc.LEDGERS), {},
                         "два объявления личности ленты разошлись в боевом населении")


# ══════════════════════════════════════════════════════════════════════════════════════
# Лента ↔ НЕСКОЛЬКО видов (ADR-782, заказ G780 п. 1, цикл #900)
#
# ADR-780 нашёл расхождение модели с замером, назвал его верно — и снять не мог: член нёс
# пару «лента ↔ вид», а личность пары и личность ФАЙЛА были одним полем. Находка стояла
# постоянно. Тесты ниже проверяют ИСХОД двух вещей сразу, и обе обязательны:
#   * на ПОЛНОМ населении видов находка МОЛЧИТ (иначе лечение не лечит);
#   * на СПРЯТАННОМ третьем читателе она ВОЗВРАЩАЕТСЯ (иначе лечение ослепило сторожа).
# ══════════════════════════════════════════════════════════════════════════════════════


def _two_view_module(name: str, *, hidden: int = 0):
    """Модуль с ДВУМЯ видами одной ленты и — по требованию — со СПРЯТАННЫМ третьим
    читателем, которого население видов не объявляет.

    ``hidden`` разборов делает ``shadow()``: это и есть тот читатель, ради которого
    находка существует. Вид ``cio_view`` принимает ещё и ``now`` — так же, как настоящий
    ``research_factory.read.cio_view``, ради которого в ``Member`` появился ``invoke``.
    """
    mod = types.ModuleType(name)

    def _parse(data_dir, times):
        rows = []
        for _ in range(times):
            rows = []
            with open(Path(data_dir) / LEDGER_REL, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        rows.append(json.loads(line))
        return rows

    def latest(data_dir):
        return _parse(data_dir, 2)

    def cio_view(data_dir, now):
        #: момент приходит ВХОДОМ и запоминается — им проверяется, что часы не взяты
        #: со стены внутри адаптера
        mod.seen_now.append(now)
        return _parse(data_dir, 2)

    def shadow(data_dir):
        return _parse(data_dir, hidden)

    mod.seen_now = []
    mod.latest, mod.cio_view, mod.shadow = latest, cio_view, shadow
    sys.modules[name] = mod
    return mod


def _two_view_members(name: str):
    """Пара членов: ДВА вида ОДНОЙ ленты — личность пары разная, личность файла одна."""
    return [
        _stand_member(name, declared_opens=2, mid="fake_book", ledger_id="fake_book"),
        lpc.Member(id="fake_book.cio_view", ledger_id="fake_book", ledger=LEDGER_REL,
                   view=f"{name}:cio_view", declared_opens=2,
                   opens_reason="стенд: второй вид разбирает ленту дважды за зов",
                   scoped_door=False, scoped_reason="стенд области кэша не открывает",
                   invoke=lpc._invoke_with_now),
    ]


def _two_view_workload(name: str, *, latest_calls: int, cio_calls: int,
                       shadow_calls: int = 0, opens: Optional[int] = None) -> lpc.Workload:
    def run(data_dir):
        mod = sys.modules[name]
        out = None
        for _ in range(latest_calls):
            out = mod.latest(data_dir)
        for _ in range(cio_calls):
            out = mod.cio_view(data_dir, "МОМЕНТ")
        for _ in range(shadow_calls):
            out = mod.shadow(data_dir)
        return out

    modelled = 2 * latest_calls + 2 * cio_calls
    return lpc.Workload(
        id="stand_run", run=run, reason="стенд: прогон зовёт оба вида ленты",
        declared_calls={"fake_book": latest_calls, "fake_book.cio_view": cio_calls},
        calls_reason={"fake_book": "стенд", "fake_book.cio_view": "стенд"},
        declared_opens={"fake_book": modelled if opens is None else opens},
        opens_reason={"fake_book": "стенд: столько разборов делает прогон"},
        cadence=_STAND_CADENCE)


class TestOneLedgerCanCarrySeveralViews(unittest.TestCase):
    """Предмет заказа G780 п. 1: форма, которой у прибора не было."""

    def _run(self, *, hidden: int, latest_calls: int, cio_calls: int,
             shadow_calls: int = 0, opens: Optional[int] = None):
        name = f"spa_stand_two_views_{hidden}_{latest_calls}_{cio_calls}_{shadow_calls}"
        _two_view_module(name, hidden=hidden)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data, lines=20)
            doc = lpc.measure(
                data, members=_two_view_members(name), tree_root=Path(td), parse_rounds=1,
                workloads=[_two_view_workload(name, latest_calls=latest_calls,
                                              cio_calls=cio_calls,
                                              shadow_calls=shadow_calls, opens=opens)])
            return doc, doc["workloads"]["rows"][0], sys.modules[name]

    def test_the_model_sums_over_BOTH_views_and_matches_the_file(self):
        """Целый контур: лента с двумя видами, оба объявлены, читателей больше нет ⇒
        модель сходится с замером у файла и находки нет НИ ОДНОЙ."""
        doc, row, _mod = self._run(hidden=0, latest_calls=2, cio_calls=2)
        self.assertIsNone(row["unmeasured"], row)
        self.assertEqual(row["calls"], {"fake_book": 2, "fake_book.cio_view": 2})
        self.assertEqual(row["opens"], {"fake_book": 8},
                         "разборы обязаны считаться у ФАЙЛА одним числом, а не у каждого вида")
        self.assertEqual(row["opens_modelled"], {"fake_book": 8},
                         "модель обязана складываться по ВИДАМ ленты")
        self.assertEqual([f for f in doc["findings"]
                          if f["kind"] == lpc.F_MODEL_DISAGREES], [],
                         "на полном населении видов расхождения быть не может")

    def test_a_HIDDEN_third_reader_brings_the_finding_BACK(self):
        """ПОРВАННОЕ ЗВЕНО — то самое, ради которого находка существует: ленту читает
        кто-то помимо объявленных видов. Объявление второго вида не вправе ослепить
        сторожа — иначе лечение стоило бы предмета."""
        doc, row, _mod = self._run(hidden=3, latest_calls=1, cio_calls=1, shadow_calls=1,
                                   opens=7)
        self.assertEqual(row["opens"], {"fake_book": 7})
        self.assertEqual(row["opens_modelled"], {"fake_book": 4})
        found = [f for f in doc["findings"] if f["kind"] == lpc.F_MODEL_DISAGREES]
        self.assertEqual(len(found), 1, doc["findings"])
        self.assertIn("модель НИЖЕ замера", found[0]["text"])
        self.assertIn("помимо объявленных видов", found[0]["text"])
        self.assertIn("fake_book.cio_view", found[0]["text"],
                      "находка обязана НАЗВАТЬ, какие виды уже объявлены — иначе она не "
                      "говорит, чего именно не хватает")

    def test_two_views_of_one_ledger_do_NOT_price_the_file_twice(self):
        """Несущее звено новой формы. Два вида одной ленты получили бы по счётчику
        разборов каждый, и цена ФАЙЛА сложилась бы дважды — прибор завысил бы ровно то,
        что мерит. Проверяется ИСХОДОМ: цена прогона равна цене разбора × ИЗМЕРЕННЫЕ
        разборы, а не вдвое большему."""
        doc, row, _mod = self._run(hidden=0, latest_calls=2, cio_calls=2)
        parse_s = doc["rows"][0]["parse_s"]
        self.assertIsNotNone(parse_s)
        self.assertAlmostEqual(row["price_s"], 8 * parse_s, places=9)
        self.assertEqual(doc["rows"][0]["parse_s"], doc["rows"][1]["parse_s"],
                         "цена разбора есть свойство ФАЙЛА — у двух его видов она одна")
        self.assertEqual(doc["rows"][0]["ledger_id"], doc["rows"][1]["ledger_id"])

    def test_the_view_that_needs_a_clock_is_still_COUNTED_at_the_module_attribute(self):
        """``Member.invoke`` добавляет виду недостающий аргумент — и не вправе увести зов
        мимо счётчика. Подменить вид готовым вызываемым значило бы ослепить счётчик
        (U_VIEW_NOT_PATCHABLE), и тогда вся форма была бы бесполезна."""
        _doc, row, _mod = self._run(hidden=0, latest_calls=0, cio_calls=3)
        self.assertEqual(row["calls"]["fake_book.cio_view"], 3,
                         "зовы вида с адаптером не досчитаны — адаптер увёл зов мимо "
                         "атрибута модуля")

    def test_the_clock_reaches_the_view_as_an_INPUT_not_from_the_wall(self):
        """Часы у вида, которому они нужны, — ВХОД: ``measure(now=…)`` обязан дойти до
        самого вида. Иначе прибор, мерящий ЧИСЛО РАЗБОРОВ, зависел бы ещё и от календаря
        (`.claude/rules/deployment.md`, «Время в тестах»)."""
        name = "spa_stand_two_views_clock"
        _two_view_module(name)
        self.addCleanup(_drop_module, name)
        anchor = "ЯКОРЬ-МОМЕНТ"
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data, lines=5)
            lpc.measure(data, members=_two_view_members(name), tree_root=Path(td),
                        parse_rounds=1, now=anchor)
        self.assertIn(anchor, sys.modules[name].seen_now,
                      "момент не дошёл до вида — адаптер взял часы со стены")


class TestOneBlindViewDoesNotTakeTheFilePriceFromTheSeeingOne(unittest.TestCase):
    """Дыру эту нашёл ПРИБОР мутаций, а не автор: первый прогон дал 12 убитых из 13, и
    выживший мутант снимал ровно условие ``parse_s is not None`` у кэша цены разбора.

    Цена разбора есть свойство ФАЙЛА, а не читателя: один вид ленты может быть слеп
    (упал, читает мимо наблюдаемых дверей, не разрешился) — файл от этого цену не теряет.
    Без условия последний по порядку член ленты ЗАТИРАЛ бы измеренную цену своим
    ``None``, и цена прогона уходила бы в ``U_PRICE_UNKNOWN`` при измеренном файле:
    третий исход, выданный на месте замера, — дефект того же класса, что и обратный.
    """

    @staticmethod
    def _module_with_a_broken_second_view(name: str):
        mod = types.ModuleType(name)

        def latest(data_dir):
            rows = []
            with open(Path(data_dir) / LEDGER_REL, "r", encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        rows.append(json.loads(line))
            return rows

        def broken(data_dir):
            raise RuntimeError("второй вид той же ленты упал")

        mod.latest, mod.broken = latest, broken
        sys.modules[name] = mod
        return mod

    def test_the_price_of_the_file_survives_a_blind_second_view(self):
        name = "spa_stand_blind_second_view"
        self._module_with_a_broken_second_view(name)
        self.addCleanup(_drop_module, name)
        #: ПОРЯДОК НЕСУЩИЙ: слепой член идёт ВТОРЫМ, иначе затирание не воспроизводится
        members = [
            _stand_member(name, declared_opens=1, mid="fake_book", ledger_id="fake_book"),
            lpc.Member(id="fake_book.broken", ledger_id="fake_book", ledger=LEDGER_REL,
                       view=f"{name}:broken", declared_opens=1,
                       opens_reason="стенд: вид падает, и это третий исход",
                       scoped_door=False, scoped_reason="стенд"),
        ]

        def run(data_dir):
            return sys.modules[name].latest(data_dir)

        wl = lpc.Workload(
            id="stand_run", run=run, reason="стенд: прогон зовёт только зрячий вид",
            declared_calls={"fake_book": 1, "fake_book.broken": 0},
            calls_reason={"fake_book": "стенд", "fake_book.broken": "стенд"},
            declared_opens={"fake_book": 1}, opens_reason={"fake_book": "стенд"},
            cadence=_STAND_CADENCE)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data, lines=10)
            doc = lpc.measure(data, members=members, tree_root=Path(td),
                              parse_rounds=1, workloads=[wl])
        seeing = next(r for r in doc["rows"] if r["id"] == "fake_book")
        blind = next(r for r in doc["rows"] if r["id"] == "fake_book.broken")
        self.assertIsNotNone(seeing["parse_s"], "зрячий вид не измерил цену разбора")
        self.assertIsNotNone(blind["unmeasured"], "упавший вид обязан быть третьим исходом")
        self.assertIn(lpc.U_VIEW_RAISED, blind["unmeasured"])
        self.assertIsNone(blind["parse_s"])

        row = doc["workloads"]["rows"][0]
        self.assertIsNone(row["unmeasured"],
                          "слепой вид забрал у ФАЙЛА измеренную цену разбора: цена прогона "
                          "ушла в третий исход при измеренном файле")
        self.assertAlmostEqual(row["price_s"], 1 * seeing["parse_s"], places=9)


class TestTheLedgerIdentityIsSelfChecking(unittest.TestCase):
    """Ключ, по которому складывается произведение, сверяется сам с собой — в ОБЕ стороны.
    Без этого член с новой личностью на том же пути молча удвоил бы цену своего файла."""

    def _members_split_by_id(self):
        return [
            _member(_view_builtin_open(1), mid="a", ledger_id="a"),
            _member(_view_builtin_open(1), mid="b", ledger_id="b"),  # тот же путь!
        ]

    def _members_split_by_path(self):
        return [
            _member(_view_builtin_open(1), mid="a", ledger_id="shared"),
            _member(_view_builtin_open(1), mid="b", ledger_id="shared",
                    ledger="other_book/ledger.jsonl"),  # та же личность, другой файл!
        ]

    def test_one_file_under_two_identities_is_the_THIRD_outcome(self):
        bad = lpc.ledger_id_split(self._members_split_by_id())
        self.assertTrue(bad)
        self.assertIn(lpc.U_LEDGER_ID_SPLIT, " ".join(bad.values()))
        self.assertIn("сложилась бы", " ".join(bad.values()),
                      "причина обязана называть ПОСЛЕДСТВИЕ, а не только факт")

    def test_one_identity_over_two_files_is_the_THIRD_outcome_too(self):
        bad = lpc.ledger_id_split(self._members_split_by_path())
        self.assertTrue(bad)
        self.assertIn("в ОДИН счётчик", " ".join(bad.values()))

    def test_a_split_identity_REFUSES_the_measurement_and_the_code_is_two(self):
        """Отказ, а не число: прибор, продолживший мерить расколотую личность, напечатал
        бы цену вдвое — и она выглядела бы как обычное число."""
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            doc = lpc.measure(data, members=self._members_split_by_id(),
                              tree_root=Path(td), parse_rounds=1)
            self.assertEqual(len(doc["unmeasured"]), 2, doc["rows"])
            for r in doc["rows"]:
                self.assertIn(lpc.U_LEDGER_ID_SPLIT, r["unmeasured"])
            self.assertEqual(lpc.exit_code(doc), 2,
                             "расколотая личность обязана давать НЕ ИЗМЕРЕНО, а не находку")

    def test_the_same_gate_stands_at_the_workload_counter_too(self):
        """Гейт стоит у КАЖДОЙ двери, где строятся цели счётчика, и реализация у него
        ОДНА: вторая копия правила разошлась бы с первой при первой же правке."""
        name = "spa_stand_split_wl"
        _stand_module(name)
        self.addCleanup(_drop_module, name)
        with TemporaryDirectory() as td:
            data = Path(td)
            _write_ledger(data)
            counts, cannot, answer, err, opens, _sites = lpc.count_calls(
                self._members_split_by_id(), _stand_workload(_calls_runner(name, 1)), data)
            self.assertIsNotNone(err, "счётчик прогона принял расколотую личность молча")
            self.assertIn(lpc.U_LEDGER_ID_SPLIT, err)
            self.assertEqual((counts, cannot, opens), ({}, {}, {}),
                             "отказ обязан быть ДО замера, а не после половины его")

    def test_the_live_population_passes_the_same_gate(self):
        """Обратная сторона: на боевом населении гейт МОЛЧИТ. Сторож, краснеющий на
        верном состоянии, — тот же дефект, что и молчащий на неверном."""
        self.assertEqual(lpc.ledger_id_split(lpc.LEDGERS), {})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()


def _tree(root: Path, files: dict) -> Path:
    """Одноразовое дерево: путь → текст. Статика ничего не импортирует, поэтому модули
    стенда могут не существовать в ``sys.modules`` вовсе — это и отличает статический
    замер от динамического."""
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _stand_view_member(mid: str = "stand", mod: str = "spa_core.stand.read",
                       attr: str = "latest") -> lpc.Member:
    return lpc.Member(id=mid, ledger_id=mid, ledger=LEDGER_REL, view=f"{mod}:{attr}",
                      declared_opens=1, opens_reason="стенд",
                      scoped_door=False, scoped_reason="стенд")


_VIEW_FILE = "def latest(data_dir):\n    return []\n"


class TestWhoCallsTheViewIsMeasuredNotGuessed(unittest.TestCase):
    """Заказ G782 п. 1: упоминание вида НЕ ЕСТЬ зов, и у каждой двери свой контроль.

    Замер 21.10 на ``origin/main`` ``2a367e897``, ради которого прибор написан: мера
    неполноты населения прогонов стояла рядом с решением числом УПОМИНАНИЙ — 22, — и
    ошибалась в ОБЕ стороны сразу: десять из двадцати двух файлов вид только называют, а
    трёх настоящих зовущих мера не видела вовсе.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        _tree(self.root, {"spa_core/stand/__init__.py": "",
                          "spa_core/stand/read.py": _VIEW_FILE})

    def _sites(self, member=None):
        member = member or _stand_view_member()
        return lpc.view_call_sites([member], self.root)[member.id]

    def test_door_one_plain_import_and_the_dotted_call(self):
        """``import spa_core.stand.read`` + полный путь в зове."""
        _tree(self.root, {"spa_core/a.py":
                          "import spa_core.stand.read\n\n"
                          "def go(d):\n    return spa_core.stand.read.latest(d)\n"})
        self.assertEqual(self._sites().calls.get("spa_core/a.py"), 1)

    def test_door_one_aliased_module_import(self):
        """``import … as m`` → ``m.latest(d)``."""
        _tree(self.root, {"spa_core/b.py":
                          "import spa_core.stand.read as m\n\n"
                          "def go(d):\n    return m.latest(d)\n"})
        self.assertEqual(self._sites().calls.get("spa_core/b.py"), 1)

    def test_door_two_is_the_one_the_first_probe_of_this_cycle_missed(self):
        """``from <пакет> import <модуль> as <имя>`` — самая населённая дверь живых
        читателей (``from spa_core.research_factory import read as rf_read``).

        Первая проба цикла #901 эту дверь не разбирала и дала **ноль** зовущих при
        четырёх настоящих. Ноль там означал не «никто не зовёт», а «дверь не смотрели» —
        поэтому контроль именно на неё, и он же объясняет, зачем у статики есть
        динамическая обратная сторона.
        """
        _tree(self.root, {"spa_core/c.py":
                          "from spa_core.stand import read as rf_read\n\n"
                          "def go(d):\n    return rf_read.latest(d)\n"})
        self.assertEqual(self._sites().calls.get("spa_core/c.py"), 1,
                         "дверь «from пакет import модуль as имя» не разобрана — "
                         "замер даст слепой ноль")

    def test_door_two_multi_name_import_is_the_measured_finding(self):
        """``from pkg import a, b, read`` — дверь, которой мера УПОМИНАНИЙ не видит.

        Это не гипотеза: так зовут вид ``research_factory.read.latest`` три настоящих
        файла (``failure_matrix.py``, ``failure_matrix_v2.py``, ``run.py``), и ни одного
        из них :func:`view_reference_files` не называет. Контроль сверяет оба замера на
        одном файле, то есть воспроизводит расхождение, а не верит ему на слово.
        """
        _tree(self.root, {"spa_core/d.py":
                          "from spa_core.stand import other, read, third\n\n"
                          "def go(d):\n    return read.latest(d)\n"})
        member = _stand_view_member()
        self.assertEqual(self._sites(member).calls.get("spa_core/d.py"), 1)
        self.assertNotIn("spa_core/d.py", lpc.view_reference_files(member, self.root),
                         "мера упоминаний увидела эту дверь — тогда расхождение, ради "
                         "которого прибор написан, воспроизвести нечем")

    def test_door_three_name_bound_at_import_is_still_a_call(self):
        """``from <модуль> import latest as v`` → ``v(d)``.

        Такое связывание само есть находка СЧЁТЧИКА зовов (:data:`F_IMPORT_BOUND_VIEW`),
        но зов через него обязан быть посчитан: иначе статика печатала бы ноль там, где
        зовущий есть, и находка счётчика маскировала бы слепоту замера.
        """
        _tree(self.root, {"spa_core/e.py":
                          "from spa_core.stand.read import latest as v\n\n"
                          "def go(d):\n    return v(d)\n"})
        self.assertEqual(self._sites().calls.get("spa_core/e.py"), 1)

    def test_door_four_the_defining_module_calls_its_own_view(self):
        """Внутримодульный зов — ``composer.py`` зовёт свой ``load_ledger`` без основания."""
        _tree(self.root, {"spa_core/stand/read.py":
                          _VIEW_FILE + "\n\ndef wrapper(d):\n    return latest(d)\n"})
        self.assertEqual(self._sites().calls.get("spa_core/stand/read.py"), 1)

    def test_a_bare_name_outside_the_defining_module_is_not_a_call(self):
        """Обратная сторона двери 4: то же имя в ЧУЖОМ файле зовом вида не является.

        Иначе любой локальный ``latest(...)`` соседа попадал бы в зовущие, и замер
        завышал бы ровно то, ради чего написан.
        """
        _tree(self.root, {"spa_core/f.py":
                          "def latest(d):\n    return []\n\n"
                          "def go(d):\n    return latest(d)\n"})
        self.assertNotIn("spa_core/f.py", self._sites().calls)

    def test_the_same_attribute_name_on_a_foreign_object_is_not_a_call(self):
        """Основание зова СВЕРЯЕТСЯ с модулем вида: `.latest()` чужого объекта не зов.

        Дыру нашёл мутационный прибор, а не глаз автора: снятие сверки основания
        оставляло батарею зелёной. Без этой проверки в зовущие попадал бы любой
        `cursor.latest()` или `registry.latest()` соседа, и замер завышал бы ровно то,
        ради чего написан, — повторив дефект меры упоминаний другим способом.
        """
        _tree(self.root, {"spa_core/k.py":
                          "from spa_core.stand import read\n"
                          "import spa_core.other as other\n\n"
                          "def go(d, cursor):\n"
                          "    cursor.latest(d)\n"
                          "    return other.latest(d)\n",
                          "spa_core/other.py": _VIEW_FILE})
        self.assertNotIn("spa_core/k.py", self._sites().calls,
                         "зов у ЧУЖОГО основания посчитан как зов вида")

    def test_a_relative_import_resolves_to_the_same_module(self):
        """``from . import read`` и ``from ..stand import read`` — тот же модуль вида.

        Внутрипакетный зовущий иначе теряется МОЛЧА, то есть занижает замер; занижение
        опаснее завышения, потому что успокаивает. Дыру нашёл мутационный прибор: живые
        зовущие пользуются абсолютной формой, и на дереве эта дверь не проверялась ничем.
        """
        _tree(self.root, {"spa_core/stand/sibling.py":
                          "from . import read\n\n"
                          "def go(d):\n    return read.latest(d)\n",
                          "spa_core/stand/deep/__init__.py": "",
                          "spa_core/stand/deep/nephew.py":
                          "from .. import read\n\n"
                          "def go(d):\n    return read.latest(d)\n"})
        calls = self._sites().calls
        self.assertEqual(calls.get("spa_core/stand/sibling.py"), 1)
        self.assertEqual(calls.get("spa_core/stand/deep/nephew.py"), 1)

    def test_a_caller_is_never_also_listed_as_mention_only(self):
        """Вычитание зовущих из упоминающих НЕСУЩЕЕ, а не косметическое.

        Два списка читаются как ответы на разные вопросы; файл в обоих означал бы, что
        отчёт говорит «упоминает и НЕ зовёт» про зовущего — то есть ровно ту ошибку, из
        которой вырос заказ, только напечатанную рядом с её исправлением.
        """
        _tree(self.root, {"spa_core/m.py":
                          "from spa_core.stand import read\n\n"
                          "def go(d):\n    return read.latest(d)\n"})
        sites = self._sites()
        self.assertIn("spa_core/m.py", sites.calls)
        self.assertNotIn("spa_core/m.py", sites.mentions_only)

    def test_a_mention_in_a_string_is_not_a_call(self):
        """Проба не проходит ПОДСТРОКОЙ (ADR-333): текст зова в докстроке — упоминание.

        Ровно этим и завышала прежняя мера: ``hash_ledger.py`` и ``mission_build.py``
        называют вид в тексте и не зовут его ни разу.
        """
        _tree(self.root, {"spa_core/g.py":
                          '"""Сосед зовёт spa_core.stand.read.latest(d) — но не мы."""\n'
                          "from spa_core.stand import read\n\n"
                          "TEXT = 'read.latest(d)'\n"})
        sites = self._sites()
        self.assertNotIn("spa_core/g.py", sites.calls)
        self.assertIn("spa_core/g.py", sites.mentions_only,
                      "файл обязан остаться в упоминающих — его снимают из ЗОВУЩИХ, "
                      "а не из населения вовсе")

    def test_a_file_that_does_not_parse_is_the_third_outcome(self):
        """Неразобранный файл — НЕ ИЗМЕРЕНО с названной причиной, а не «зовов нет»."""
        _tree(self.root, {"spa_core/broken.py": "def go(:\n    pass\n"})
        sites = self._sites()
        self.assertIn("spa_core/broken.py", sites.unparsed)
        self.assertIn(lpc.U_CALL_SITE_UNPARSED, sites.unparsed["spa_core/broken.py"])
        self.assertNotIn("spa_core/broken.py", sites.calls)

    def test_a_call_on_a_non_static_base_is_the_third_outcome(self):
        """``factory()[0].latest(d)`` — имя вида есть, основание статикой не разрешается.

        Выдать это за «не зовёт» значило бы молча потерять зовущего; выдать за зов —
        приписать вызов тому, кого не измеряли. Поэтому третий исход.
        """
        _tree(self.root, {"spa_core/h.py":
                          "from spa_core.stand import read\n\n"
                          "def go(d, factory):\n    return factory()[0].latest(d)\n"})
        sites = self._sites()
        self.assertIn("spa_core/h.py", sites.unresolved_base)
        self.assertIn(lpc.U_CALL_BASE_UNRESOLVED, sites.unresolved_base["spa_core/h.py"])

    def test_the_sweep_skips_tests_and_the_instrument_itself(self):
        """Население обхода — то же, что у меры упоминаний: иначе сверять их нельзя."""
        _tree(self.root, {"spa_core/tests/test_x.py":
                          "from spa_core.stand import read\n\n"
                          "def t(d):\n    return read.latest(d)\n",
                          lpc.SELF_REL:
                          "from spa_core.stand import read\n\n"
                          "def t(d):\n    return read.latest(d)\n"})
        calls = self._sites().calls
        self.assertNotIn("spa_core/tests/test_x.py", calls)
        self.assertNotIn(lpc.SELF_REL, calls)

    def test_a_second_view_of_the_same_module_is_counted_apart(self):
        """Два вида одного модуля не сливаются: у ленты их бывает несколько (цикл #900)."""
        _tree(self.root, {"spa_core/stand/read.py":
                          _VIEW_FILE + "\n\ndef cio_view(d, now):\n    return []\n",
                          "spa_core/i.py":
                          "from spa_core.stand import read\n\n"
                          "def go(d, now):\n"
                          "    read.latest(d)\n"
                          "    return read.cio_view(d, now)\n"})
        both = lpc.view_call_sites(
            [_stand_view_member(), _stand_view_member(mid="stand.cio", attr="cio_view")],
            self.root)
        self.assertEqual(both["stand"].calls.get("spa_core/i.py"), 1)
        self.assertEqual(both["stand.cio"].calls.get("spa_core/i.py"), 1)

    def test_several_calls_in_one_file_are_counted_not_flattened(self):
        """Число зовов в файле — число, а не признак: два зова это два."""
        _tree(self.root, {"spa_core/j.py":
                          "from spa_core.stand import read\n\n"
                          "def go(d):\n    read.latest(d)\n    return read.latest(d)\n"})
        self.assertEqual(self._sites().calls.get("spa_core/j.py"), 2)

    def test_a_callable_view_has_no_call_sites_and_says_so(self):
        """Вид, переданный вызываемым (стенды), статике не адресуем — его в замере нет
        вовсе, а не «зовущих ноль»."""
        member = lpc.Member(id="callable", ledger_id="callable", ledger=LEDGER_REL,
                            view=lambda d: [], declared_opens=1, opens_reason="стенд",
                            scoped_door=False, scoped_reason="стенд")
        self.assertEqual(lpc.view_call_sites([member], self.root), {})


class TestTheTwoMeasurementsOfCallersAreComparedBothWays(unittest.TestCase):
    """Статика и прогон отвечают на один вопрос разными способами — сверка в ОБЕ стороны."""

    def _static(self, calls, *, mentions=(), unparsed=None, murky=None):
        return {"stand": lpc.CallSites(calls=dict(calls), mentions_only=tuple(mentions),
                                       unparsed=dict(unparsed or {}),
                                       unresolved_base=dict(murky or {}))}

    def test_a_runtime_caller_the_static_sweep_does_not_see_is_not_measured(self):
        """Прогон видел зов, статика его не видит ⇒ у статики непросмотренная дверь.

        Это третий исход (:data:`U_CALL_SITES_BLIND`), а не находка о коде: про такой
        файл статика не измерила НИЧЕГО.
        """
        cross = lpc.cross_check_call_sites(
            self._static({"spa_core/a.py": 1}),
            {"stand": {"spa_core/zz.py": 3}}, sites_measured=True)
        self.assertEqual(cross["status"], "compared")
        self.assertIn("spa_core/zz.py", cross["blind"]["stand"])
        self.assertIn(lpc.U_CALL_SITES_BLIND, cross["blind"]["stand"]["spa_core/zz.py"])

    def test_a_static_caller_no_workload_reaches_is_named_incompleteness(self):
        """Статика видит зовущего, прогоны его не достигают ⇒ НАЗВАННАЯ неполнота.

        Население прогонов — РЕШЕНИЕ, поэтому это не дефект и не третий исход; ценность
        в том, что неполнота названа ФАЙЛОМ, а не числом упоминаний.
        """
        cross = lpc.cross_check_call_sites(
            self._static({"spa_core/a.py": 1, "spa_core/b.py": 2}),
            {"stand": {"spa_core/a.py": 1}}, sites_measured=True)
        self.assertEqual(cross["outside_workloads"], {"stand": ["spa_core/b.py"]})
        self.assertEqual(cross["agreed"], {"stand": ["spa_core/a.py"]})
        self.assertFalse(cross["blind"])

    def test_nothing_to_compare_with_is_its_own_outcome(self):
        """Ни один прогон не принят ⇒ «не сверялось», и это НЕ «сошлось» (инв. #17)."""
        cross = lpc.cross_check_call_sites(self._static({"spa_core/a.py": 1}), {},
                                           sites_measured=False)
        self.assertEqual(cross["status"], "not_measured")
        self.assertTrue((cross["reason"] or "").strip())
        self.assertFalse(cross["blind"])
        self.assertFalse(cross["outside_workloads"])

    def test_a_frame_outside_the_tree_is_not_called_blindness(self):
        """Кадр из чужого каталога статике не подсуден: она обходит ДЕРЕВО."""
        cross = lpc.cross_check_call_sites(
            self._static({"spa_core/a.py": 1}),
            {"stand": {"/opt/other/x.py": 1, "<string>": 1, "spa_core/a.py": 1}},
            sites_measured=True)
        self.assertFalse(cross["blind"])
        self.assertEqual(cross["out_of_tree"]["stand"], ["/opt/other/x.py", "<string>"])
        self.assertEqual(cross["agreed"], {"stand": ["spa_core/a.py"]})

    def test_the_instrument_own_frame_is_declared_not_blindness(self):
        """Прибор сам поднимает прогоны, и его файл исключён из обхода ОБЪЯВЛЕННО."""
        cross = lpc.cross_check_call_sites(
            self._static({"spa_core/a.py": 1}),
            {"stand": {lpc.SELF_REL: 2, "spa_core/a.py": 1}}, sites_measured=True)
        self.assertFalse(cross["blind"])
        self.assertNotIn(lpc.SELF_REL, cross["agreed"].get("stand", []))

    def test_an_unparsed_file_seen_at_runtime_names_the_parse_reason(self):
        """Файл, который статика не разобрала, а прогон из него звал: причина — РАЗБОР,
        а не непросмотренная дверь. Два разных «не измерено» не сливаются."""
        cross = lpc.cross_check_call_sites(
            self._static({}, unparsed={"spa_core/broken.py": "call_sites_file_not_parsed: X"}),
            {"stand": {"spa_core/broken.py": 1}}, sites_measured=True)
        self.assertIn(lpc.U_CALL_SITE_UNPARSED, cross["blind"]["stand"]["spa_core/broken.py"])


class TestTheRuntimeCallerNamesItself(unittest.TestCase):
    """Динамическая атрибуция: зов называет ТОГО, КТО ЕГО НАПИСАЛ, а не поднявшего прогон.

    Именно этого различия не хватало ADR-777: цену платил вложенный читатель
    (``capital_shadow.readiness`` → ``research_factory.read.latest``), которого
    вызывающий не называет.
    """

    def setUp(self):
        self._tmp = TemporaryDirectory()
        self.data = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        (self.data / LEDGER_REL).parent.mkdir(parents=True, exist_ok=True)
        (self.data / LEDGER_REL).write_text('{"a":1}\n', encoding="utf-8")

    def test_the_nested_caller_is_recorded_not_the_runner(self):
        mod = _stand_module("stand_sites_mod")
        self.addCleanup(_drop_module, "stand_sites_mod")
        member = _stand_member("stand_sites_mod")
        workload = _stand_workload(_calls_runner("stand_sites_mod", 1))
        _counts, _cannot, _answer, err, _opens, sites = lpc.count_calls(
            [member], workload, self.data)
        self.assertIsNone(err)
        #: зов написан в ЭТОМ тест-файле (``_calls_runner``), и он же назван
        self.assertEqual(sum(sites["fake_book"].values()), 1)
        where = next(iter(sites["fake_book"]))
        self.assertTrue(where.endswith("test_ledger_parse_census.py"), where)
        del mod

    def test_the_attribution_reaches_the_report_not_just_the_counter(self):
        """Проводка ИЗМЕРЯЕТСЯ: число в приборе, которого не видит отчёт, — класс ADR-412."""
        _stand_module("stand_sites_mod2")
        self.addCleanup(_drop_module, "stand_sites_mod2")
        doc = lpc.measure_workloads(
            self.data, members=[_stand_member("stand_sites_mod2")],
            workloads=[_stand_workload(_calls_runner("stand_sites_mod2", 2))],
            price_by_id={"fake_book": 0.001}, parse_by_id={"fake_book": 0.001})
        self.assertTrue(doc["sites_measured"])
        self.assertEqual(sum(doc["call_sites"]["fake_book"].values()), 2)

    def test_a_refused_workload_contributes_no_attribution(self):
        """Отказавший прогон замера зовущих не даёт: иначе его неполнота читалась бы как
        слепота статики."""
        _stand_module("stand_sites_mod3")
        self.addCleanup(_drop_module, "stand_sites_mod3")

        def boom(_data_dir):
            raise RuntimeError("прогон стенда отказал нарочно")

        doc = lpc.measure_workloads(
            self.data, members=[_stand_member("stand_sites_mod3")],
            workloads=[_stand_workload(boom)],
            price_by_id={"fake_book": 0.001}, parse_by_id={"fake_book": 0.001})
        self.assertFalse(doc["sites_measured"])
        self.assertEqual(doc["call_sites"], {})


class TestCallSiteOutcomesMapToExitCodes(unittest.TestCase):
    """Три исхода прибора зовущих — три разных кода возврата, и порядок намеренный."""

    def _doc(self, **call_sites) -> dict:
        base = {
            "unmeasured": [], "findings": [],
            "population": {"code_files_undeclared": [], "code_files_missing": []},
            "workloads": {"unmeasured": [], "unreached": {}, "daily_unmeasured": []},
            "call_sites": {"static": {}, "unparsed": {},
                           "cross": {"status": "compared", "blind": {},
                                     "outside_workloads": {}, "agreed": {}}},
        }
        base["call_sites"].update(call_sites)
        return base

    def test_a_clean_sweep_is_zero(self):
        self.assertEqual(lpc.exit_code(self._doc()), 0)

    def test_blindness_is_the_third_outcome_not_a_finding(self):
        doc = self._doc(cross={"status": "compared", "blind": {"stand": {"a.py": "x"}},
                               "outside_workloads": {}, "agreed": {}})
        self.assertEqual(lpc.exit_code(doc), 2)

    def test_an_unparsed_file_is_the_third_outcome(self):
        self.assertEqual(lpc.exit_code(self._doc(unparsed={"a.py": "x"})), 2)

    def test_a_non_static_base_is_the_third_outcome(self):
        doc = self._doc(static={"stand": {"calls": {}, "mentions_only": [],
                                          "unresolved_base": {"a.py": "x"}}})
        self.assertEqual(lpc.exit_code(doc), 2)

    def test_named_incompleteness_alone_does_not_raise_the_code(self):
        """Неполнота населения прогонов — ЗАМЕР рядом с решением, а не дефект прибора.

        Поднять на ней код значило бы объявить решение владельца поломкой и сделать
        строку несмолкающей — ровно то, что цикл #900 снимал у соседней находки.
        """
        doc = self._doc(cross={"status": "compared", "blind": {},
                               "outside_workloads": {"stand": ["a.py"]}, "agreed": {}})
        self.assertEqual(lpc.exit_code(doc), 0)


class TestTheLiveTreeAnswersTheOrder(unittest.TestCase):
    """Замер на ЖИВОМ дереве — тот, которым закрыт заказ G782 п. 1."""

    def test_the_three_callers_the_mention_measure_never_saw(self):
        """Три настоящих зовущих ``research_factory.read.latest``, которых мера упоминаний
        не называет: дверь ``from pkg import a, b, read`` ей не видна."""
        rf = [m for m in lpc.LEDGERS if m.id == "research_factory"][0]
        sites = lpc.view_call_sites([rf], _REPO)["research_factory"]
        refs = set(lpc.view_reference_files(rf, _REPO))
        for rel in ("spa_core/research_factory/failure_matrix.py",
                    "spa_core/research_factory/run.py"):
            with self.subTest(rel=rel):
                self.assertIn(rel, sites.calls, "зовущий потерян")
                self.assertNotIn(rel, refs,
                                 "мера упоминаний его видит — расхождение исчезло, "
                                 "и замер заказа воспроизвести нечем")

    def test_a_mention_only_file_of_the_live_tree_is_named(self):
        """``hash_ledger.py`` ленту ОБЪЯВЛЯЕТ и вид не зовёт — он упоминающий, не зовущий."""
        rf = [m for m in lpc.LEDGERS if m.id == "research_factory"][0]
        sites = lpc.view_call_sites([rf], _REPO)["research_factory"]
        self.assertIn("spa_core/utils/hash_ledger.py", sites.mentions_only)
        self.assertNotIn("spa_core/utils/hash_ledger.py", sites.calls)

    def test_every_declared_view_has_at_least_one_caller_in_the_tree(self):
        """Объявленный вид без ОДНОГО зовущего в дереве — слепой ноль, а не население.

        Вид, которого не зовёт никто, незачем мерить вовсе; поэтому ноль зовущих у
        объявленного члена и есть признак непросмотренной двери.
        """
        sites = lpc.view_call_sites(lpc.LEDGERS, _REPO)
        for mid, v in sites.items():
            with self.subTest(mid=mid):
                self.assertTrue(v.calls, f"{mid}: зовущих ноль — статика ослепла")
