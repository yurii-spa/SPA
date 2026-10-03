"""Сторожа уборки одноразового стенда (ADR-546, авария 2026-10-03, цикл #759).

Каждый тест — положительный контроль на КОНКРЕТНЫЙ способ той аварии: приборы
``heir_all_rows_price`` и ``judge_alone_price`` копировали живое ``data/`` в
временный каталог и не снимали его. За трое суток накопилось **957 брошенных
стендов, 87 ГБ**, диск дошёл до нуля свободных байт — и в этом состоянии падает
любая запись, включая ``atomic_save``, то есть трек и все сторожа молча теряют
способность записать результат.

Поэтому предмет здесь — не «есть ли в коде `rmtree`», а ИСХОД: остался ли
каталог на диске после зова. Каждый тест считает каталоги в ПОДСТАВЛЕННОМ
временном корне, а не судит по форме вызова.
"""
# FROZEN-DATE-OK: injected-clock — все даты фикстур происходят от якоря NOW,
# который передаётся в measure(now=); стенных часов тест не спрашивает.
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from spa_core.monitoring import heir_all_rows_price as H
from spa_core.monitoring import judge_alone_price as J
from spa_core.monitoring import run_identity_key_price as G16
from spa_core.utils import disposable_stand as DS

NOW = datetime(2026, 9, 15, 6, 0, 0, tzinfo=timezone.utc)


def _day(n: int) -> str:
    """Дата, происходящая ОТ ЯКОРЯ: стенных часов фикстура не спрашивает."""
    return (NOW - timedelta(days=n)).date().isoformat()


def _row(day: str) -> dict:
    return {
        "cycle_date": day,
        "decision_id": f"adr060-shadow-{day}",
        "generated_at": f"{day}T23:31:36.000000+00:00",
        "verdict": "HOLD",
        "capital_usd": 100_000.0,
        "turnover_usd": 20_000.0,
        "cost_usd": 40.0,
        "current_positions": {"aave_v3": 60_000.0, "maple": 40_000.0},
        "target_positions": {"aave_v3": 40_000.0, "maple": 60_000.0},
        "apy_evidenced_pct": {"aave_v3": 3.0, "maple": 9.0},
        "reasons": ["gain_below_band:0.1pp<0.75pp"],
    }


class _StandScene(unittest.TestCase):
    """Общая сцена: ПОДСТАВЛЕННЫЙ временный корень + крошечные дерево и журнал.

    Корень подставляется затем, чтобы «сколько стендов осталось» было ИЗМЕРИМО,
    а не выводилось из чтения кода. Без подстановки тест писал бы в общий
    ``/var/folders/.../T`` — тот самый каталог, который авария и забила.
    """

    DAYS = 6

    def setUp(self):
        self.box = Path(tempfile.mkdtemp(prefix="stand_scene_"))
        self.addCleanup(shutil.rmtree, self.box, ignore_errors=True)
        # подстановка общего временного корня: mkdtemp приборов попадёт СЮДА
        self._real_tempdir = tempfile.tempdir
        tempfile.tempdir = str(self.box / "tmproot")
        (self.box / "tmproot").mkdir(parents=True, exist_ok=True)
        self.addCleanup(self._restore_tempdir)

        self.tree = self.box / "tree"
        (self.tree / "spa_core").mkdir(parents=True, exist_ok=True)
        self.data = self._data_dir(self.box / "src", self.DAYS)

        # перепись читателей — не предмет этого файла; она самая дорогая часть
        # замера и к уборке стенда отношения не имеет.
        self._real_pop = G16.reader_population
        G16.reader_population = lambda tree_root, **kw: (set(), {"population": 0})
        self.addCleanup(self._restore_population)

    def _restore_tempdir(self):
        tempfile.tempdir = self._real_tempdir

    def _restore_population(self):
        G16.reader_population = self._real_pop

    def _data_dir(self, root: Path, days: int) -> Path:
        data = root / "data"
        data.mkdir(parents=True, exist_ok=True)
        rows = [_row(_day(days - i)) for i in range(days)]
        (data / H.HISTORY_FILENAME).write_text(
            "\n".join(json.dumps(r, sort_keys=True) for r in rows) + "\n",
            encoding="utf-8")
        return data

    def leftovers(self, prefix: str):
        root = Path(tempfile.tempdir)
        return sorted(p.name for p in root.iterdir() if p.name.startswith(prefix))

    def heir(self, **kw):
        return H.measure(self.data, now=NOW, tree_root=self.tree,
                         sweep_entries=False, **kw)

    def judge(self, **kw):
        return J.measure(self.data, now=NOW, tree_root=self.tree,
                         with_capacity=False, **kw)


class OurOwnStandIsRemovedTest(_StandScene):
    """Авария дословно: зов прошёл, стенд остался. Теперь обязан не остаться."""

    def test_heir_leaves_no_stand_behind(self):
        doc = self.heir()
        self.assertEqual(self.leftovers("g17_"), [],
                         "стенд g17_ остался на диске — это и есть авария "
                         "2026-10-03 (286 таких каталогов, 48,5 ГБ)")
        self.assertEqual(doc[DS.FIELD], DS.DISPOSAL_REMOVED)

    def test_judge_leaves_no_stand_behind(self):
        doc = self.judge()
        self.assertEqual(self.leftovers("g18_"), [],
                         "стенд g18_ остался на диске — 671 такой каталог, "
                         "38,8 ГБ в замере аварии")
        self.assertEqual(doc[DS.FIELD], DS.DISPOSAL_REMOVED)

    def test_disposal_outcome_is_reported_with_a_reason(self):
        for name, doc in (("g17", self.heir()), ("g18", self.judge())):
            self.assertIn(DS.REASON_FIELD, doc, f"{name}: исход без причины")
            self.assertIn("снят", doc[DS.REASON_FIELD])


class CallerOwnedStandSurvivesTest(_StandScene):
    """Обратный контроль: каталог, НАЗВАННЫЙ вызовом, снимать запрещено.

    Починка «удалять всегда» прошла бы предыдущий класс и унесла бы каталог
    вызывающего — ровно тот класс, которым ``git checkout -- data/`` стёр 116
    файлов живого состояния.
    """

    def test_heir_does_not_touch_the_directory_the_caller_named(self):
        mine = self.box / "mine17"
        doc = self.heir(stand_root=mine)
        self.assertTrue(mine.exists(), "прибор снёс каталог ВЫЗЫВАЮЩЕГО")
        self.assertEqual(doc[DS.FIELD], DS.DISPOSAL_CALLER_OWNS)

    def test_judge_does_not_touch_the_directory_the_caller_named(self):
        mine = self.box / "mine18"
        doc = self.judge(stand_root=mine)
        self.assertTrue(mine.exists(), "прибор снёс каталог ВЫЗЫВАЮЩЕГО")
        self.assertEqual(doc[DS.FIELD], DS.DISPOSAL_CALLER_OWNS)


class RefusalPathAlsoCleansTest(_StandScene):
    """477 из 671 брошенных g18_ были ПОЧТИ ПУСТЫ — это досрочные отказы.

    То есть больше половины утечки давал не удачный замер, а путь «мерить
    нечем»: каталог уже создан, а `return` уходит мимо любой уборки.
    """

    def test_heir_cleans_up_when_the_stands_cannot_be_built(self):
        one_row = self._data_dir(self.box / "one", 1)
        doc = H.measure(one_row, now=NOW, tree_root=self.tree,
                        sweep_entries=False)
        self.assertEqual(doc["status"], H.STATUS_UNMEASURED,
                         "сцена не та: отказа построения стендов не случилось")
        self.assertEqual(self.leftovers("g17_"), [],
                         "досрочный отказ оставил стенд на диске")
        self.assertEqual(doc[DS.FIELD], DS.DISPOSAL_REMOVED)

    def test_judge_creates_no_stand_at_all_when_it_refuses_before_building(self):
        """Граница класса: отказ ДО создания стенда уборки не требует.

        Поле исхода тогда отсутствует — и это не молчание, а отсутствие
        предмета: каталога не было вовсе.
        """
        two_rows = self._data_dir(self.box / "two", 2)
        doc = J.measure(two_rows, now=NOW, tree_root=self.tree,
                        with_capacity=False)
        self.assertEqual(doc["status"], J.STATUS_UNMEASURED)
        self.assertEqual(self.leftovers("g18_"), [])
        self.assertNotIn(DS.FIELD, doc,
                         "стенда не было — об уборке докладывать нечего")


class ExceptionStillCleansTest(_StandScene):
    """Выход по ИСКЛЮЧЕНИЮ — третий путь мимо уборки, и он тоже закрыт."""

    def test_heir_cleans_up_when_the_measurement_blows_up(self):
        real = H.build_stands
        H.build_stands = lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("бум"))
        try:
            with self.assertRaises(RuntimeError):
                self.heir()
        finally:
            H.build_stands = real
        self.assertEqual(self.leftovers("g17_"), [],
                         "исключение унесло замер и ОСТАВИЛО стенд")


class FailedRemovalIsNamedTest(_StandScene):
    """Инв. #17: «место не освобождено» обязано быть ОТДЕЛЬНЫМ значением.

    Молча проглоченный отказ уборки неотличим от успеха — а это ровно та
    форма, которой машина трижды доходила до нуля свободных байт.
    """

    def setUp(self):
        super().setUp()
        self._real_rmtree = DS.shutil.rmtree

        def refuse(path, *a, **kw):
            raise OSError(28, "No space left on device")

        DS.shutil.rmtree = refuse
        self.addCleanup(self._restore_rmtree)

    def _restore_rmtree(self):
        DS.shutil.rmtree = self._real_rmtree

    def test_the_failure_is_in_the_report_and_names_its_cause(self):
        doc = self.heir()
        self.assertTrue(str(doc[DS.FIELD]).startswith(DS.DISPOSAL_FAILED + ":"),
                        f"отказ уборки выдан за успех: {doc[DS.FIELD]!r}")
        self.assertIn("OSError", str(doc[DS.FIELD]))
        self.assertIn("место на диске не освобождено", doc[DS.REASON_FIELD])

    def test_a_failed_cleanup_does_not_destroy_the_measurement(self):
        doc = self.heir()
        self.assertIn("status", doc, "отказ уборки унёс сам замер")
        self.assertIn("generated_at", doc)


class SingleDoorTest(unittest.TestCase):
    """Регрессионный якорь: у обоих приборов ОДНА дверь к временному каталогу.

    Проверяет ФОРМУ места вызова, а не исход (исход проверен выше): вернуть
    строку ``tempfile.mkdtemp(prefix="g17_")`` обратно — самый дешёвый способ
    воспроизвести аварию, и он обязан краснеть сразу.
    """

    def test_neither_instrument_calls_mkdtemp_itself(self):
        for path in ("spa_core/monitoring/heir_all_rows_price.py",
                     "spa_core/monitoring/judge_alone_price.py"):
            src = (Path(__file__).resolve().parents[2] / path).read_text(encoding="utf-8")
            self.assertNotIn("mkdtemp", src,
                             f"{path}: прибор снова сам создаёт стенд — "
                             f"уборка перестала быть частью создания")
            self.assertIn("make_stand(", src, f"{path}: общая дверь не зовётся")
            self.assertIn("drop_stand(", src, f"{path}: уборка не зовётся")


if __name__ == "__main__":
    unittest.main()
