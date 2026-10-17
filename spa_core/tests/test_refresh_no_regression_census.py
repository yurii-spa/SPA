"""Контроли производителя записи для критерия §49 `No regression` (заказ G673 п. 1).

Предмет: `scripts/refresh_no_regression_census.py` — он производит junit-ЗАПИСЬ
прогона, которой на хосте не держал никто, и отдаёт её переписи. Каждое звено
проверяется В ОБЕ СТОРОНЫ: целый контур зелен, порванное звено краснеет С ИМЕНЕМ.

Три двери к окружению закрыты входами, как требует `.claude/rules/deployment.md`:
часы (`now=`), дерево (`repo_root`), сам прогон (`subprocess.run` подменяется).
Поэтому ни один тест здесь не зависит от календаря, хоста и наличия pytest-плагинов.

FROZEN-DATE-OK: injected-clock — отметки отчётов вычисляются от `now`, который
передаётся функции аргументом; литеральных дат в файле нет, и якорь не берётся
ни у стенных часов, ни на импорте (ADR-348).
"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import unittest
import unittest.mock
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Якорь времени — ПРОСТОЕ имя уровня модуля, и это не стилистика: сторож пометки
#: `injected-clock` (`spa_core/tests/_injected_clock.py`) считает привязкой только
#: простое имя, поэтому `ANCHOR = datetime(...)` происхождением НЕ является, а
#: `now=ANCHOR` — является. Пометка обязана быть ПРАВДОЙ, а не запиской.
ANCHOR = datetime(2026, 1, 1, tzinfo=timezone.utc)  # FROZEN-DATE-OK: injected-clock — подаётся аргументом now= во все судящие о свежести вызовы


def _load_script():
    """Загрузить скрипт как модуль (он живёт в `scripts/`, пакетом не является)."""
    path = REPO_ROOT / "scripts" / "refresh_no_regression_census.py"
    spec = importlib.util.spec_from_file_location("refresh_no_regression_census", path)
    assert spec and spec.loader, f"скрипт не загружается: {path}"
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RNC = _load_script()

from spa_core.monitoring import no_regression_census as census  # noqa: E402


def _junit(path: Path, cases: list[tuple[str, str, bool]]) -> None:
    """Записать junit-XML: `(classname, name, упал ли)`. Пустой список = ноль случаев."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = "".join(
        f'<testcase classname="{cls}" name="{name}">'
        + ("<failure message=\"boom\"/>" if bad else "")
        + "</testcase>"
        for cls, name, bad in cases)
    path.write_text(f'<?xml version="1.0"?><testsuites><testsuite name="pytest" '
                    f'tests="{len(cases)}">{body}</testsuite></testsuites>',
                    encoding="utf-8")


class ВозрастОтчёта(unittest.TestCase):
    """`artifact_age_hours` различает ТРИ исхода, а не два."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.tmp.cleanup)

    def _write(self, doc) -> None:
        (self.root / census.REPORT_REL).write_text(
            doc if isinstance(doc, str) else json.dumps(doc), encoding="utf-8")

    def test_отчёта_нет_возраст_НЕ_ИЗМЕРЕН(self):
        age, why = RNC.artifact_age_hours(self.root, now=ANCHOR)
        self.assertIsNone(age, "отсутствие файла обязано быть НЕ ИЗМЕРЕНО, а не нулём часов")
        self.assertIn("отчёта переписи нет", why)

    def test_отчёт_не_разобран_возраст_НЕ_ИЗМЕРЕН(self):
        self._write("{не json")
        age, why = RNC.artifact_age_hours(self.root, now=ANCHOR)
        self.assertIsNone(age)
        self.assertIn("не разобран", why)

    def test_отчёт_без_отметки_времени_возраст_НЕ_ИЗМЕРЕН(self):
        self._write({"measured": True, "verdict": census.NO_REGRESSION})
        age, why = RNC.artifact_age_hours(self.root, now=ANCHOR)
        self.assertIsNone(age, "«нет отметки» нельзя прочитать как «свежий»")
        self.assertIn("generated_at", why)

    def test_возраст_считается_от_поданных_часов(self):
        made = ANCHOR - timedelta(hours=73.5)
        self._write({"generated_at": made.isoformat().replace("+00:00", "Z"),
                     "measured": True, "verdict": census.NO_REGRESSION})
        age, why = RNC.artifact_age_hours(self.root, now=ANCHOR)
        self.assertAlmostEqual(age, 73.5, places=3)
        self.assertIn("73.5", why)

    def test_отметка_без_зоны_читается_как_UTC_а_не_падает(self):
        made = (ANCHOR - timedelta(hours=10)).replace(tzinfo=None)
        self._write({"generated_at": made.isoformat(), "measured": True})
        age, _ = RNC.artifact_age_hours(self.root, now=ANCHOR)
        self.assertAlmostEqual(age, 10.0, places=3)


class НаселениеБерётсяУПереписи(unittest.TestCase):
    """Своей копии правила принадлежности у скрипта нет (класс ADR-522)."""

    def test_состав_дословно_из_переписи_без_повторов(self):
        pop = {"roots_absent": [], "unparsed": [], "surfaces": {
            "risk": {"files": ["a.py", "b.py"]},
            "security": {"files": ["b.py", "c.py"]},
            "architecture": {"files": ["d.py"]}}}
        with unittest.mock.patch.object(census, "population", return_value=pop):
            got = RNC.population_files(Path("/нет/такого"))
        self.assertEqual(got, ["a.py", "b.py", "c.py", "d.py"],
                         "файл, принадлежащий двум поверхностям, прогоняется ОДИН раз")

    def test_каталог_прогона_не_найден_отказ_с_именем(self):
        pop = {"roots_absent": ["scripts/tests"], "unparsed": [], "surfaces": {}}
        with unittest.mock.patch.object(census, "population", return_value=pop):
            with self.assertRaises(RNC.NotMeasured) as ctx:
                RNC.population_files(Path("/нет/такого"))
        self.assertIn("scripts/tests", str(ctx.exception))

    def test_неразобранный_файл_отказ_с_именем(self):
        pop = {"roots_absent": [], "unparsed": [{"file": "spa_core/tests/test_x.py"}],
               "surfaces": {"risk": {"files": ["a.py"]}}}
        with unittest.mock.patch.object(census, "population", return_value=pop):
            with self.assertRaises(RNC.NotMeasured) as ctx:
                RNC.population_files(Path("/нет/такого"))
        self.assertIn("test_x.py", str(ctx.exception))
        self.assertIn("НЕИЗВЕСТНА", str(ctx.exception))

    def test_пустая_поверхность_отказ_с_именем(self):
        pop = {"roots_absent": [], "unparsed": [], "surfaces": {
            "risk": {"files": ["a.py"]}, "security": {"files": []}}}
        with unittest.mock.patch.object(census, "population", return_value=pop):
            with self.assertRaises(RNC.NotMeasured) as ctx:
                RNC.population_files(Path("/нет/такого"))
        self.assertIn("security", str(ctx.exception),
                      "сторож без населения зелен по построению — это отказ, а не satisfied")

    def test_живое_дерево_даёт_все_три_объявленные_поверхности(self):
        """Положительный контроль на самом дереве: контур цел, население непусто."""
        files = RNC.population_files(REPO_ROOT)
        self.assertGreater(len(files), 50, "население трёх поверхностей не может быть крошечным")
        self.assertEqual(len(files), len(set(files)))


class ОтказВБоевомДереве(unittest.TestCase):
    """Прогон в прод-дереве запрещён ДО запуска (`.claude/rules/deployment.md` п. 4)."""

    def test_боевое_дерево_отказ_и_причина_названа(self):
        from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT
        with self.assertRaises(RNC.NotMeasured) as ctx:
            RNC._refuse_if_prod_tree(Path(DEFAULT_LIVE_ROOT), allow=False)
        self.assertIn("БОЕВОЕ", str(ctx.exception))
        self.assertIn("deployment.md", str(ctx.exception))

    def test_осознанный_обход_снимает_отказ(self):
        from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT
        RNC._refuse_if_prod_tree(Path(DEFAULT_LIVE_ROOT), allow=True)  # не поднимает

    def test_одноразовое_дерево_не_отказывает(self):
        with TemporaryDirectory() as tmp:
            RNC._refuse_if_prod_tree(Path(tmp), allow=False)  # не поднимает

    def test_нечем_спросить_путь_прода_это_отказ_а_не_разрешение(self):
        import spa_core.utils.live_paths as lp
        with unittest.mock.patch.dict("sys.modules", {"spa_core.utils.live_paths": None}):
            with self.assertRaises(RNC.NotMeasured) as ctx:
                RNC._refuse_if_prod_tree(Path("/tmp/что-то"), allow=False)
        self.assertIn("боевого дерева", str(ctx.exception))
        self.assertTrue(hasattr(lp, "DEFAULT_LIVE_ROOT"), "подмена не должна переживать тест")


class ПрогонНаселения(unittest.TestCase):
    """Запись — предмет прогона, и её отсутствие НЕ есть «все прошли»."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.record = self.root / RNC.RECORDS_REL / "run.xml"

    def _stub(self, *, write: list | None, rc: int = 0, out: str = ""):
        def fake_run(cmd, **kw):
            self.seen = {"cmd": cmd, **kw}
            if write is not None:
                target = Path([c for c in cmd if str(c).startswith("--junitxml=")][0]
                              .split("=", 1)[1])
                _junit(target, write)
            return subprocess.CompletedProcess(cmd, rc, stdout=out, stderr="")
        return fake_run

    def test_целый_контур_отдаёт_наблюдения_прогона(self):
        with unittest.mock.patch.object(RNC.subprocess, "run",
                                        self._stub(write=[("m.test_a", "t1", False)], rc=0)):
            got = RNC.run_population(self.root, ["m/test_a.py"], self.record)
        self.assertEqual(got["cases_in_record"], 1)
        self.assertEqual(got["returncode"], 0)
        self.assertEqual(got["files_requested"], 1)

    def test_команда_несёт_предписанное_окружение_и_своё_дерево(self):
        with unittest.mock.patch.object(RNC.subprocess, "run",
                                        self._stub(write=[("m.test_a", "t1", False)])):
            RNC.run_population(self.root, ["m/test_a.py", "m/test_b.py"], self.record)
        cmd, kw = self.seen["cmd"], self.seen
        self.assertIn("m/test_a.py", cmd)
        self.assertIn("m/test_b.py", cmd)
        self.assertIn("no:randomly", cmd)
        self.assertTrue(any(str(c).startswith("--junitxml=") for c in cmd))
        self.assertEqual(kw["cwd"], str(self.root), "прогон идёт в СВОЁМ дереве")
        for key, value in RNC.RUN_ENV.items():
            self.assertEqual(kw["env"][key], value,
                             f"переменная {key} — часть команды, а не фон (цикл #421)")
        self.assertFalse([c for c in cmd if str(c).startswith("--timeout")],
                         "порог --timeout этот прибор не задаёт (инв. #16)")

    def test_записи_после_прогона_нет_это_НЕ_ИЗМЕРЕНО(self):
        with unittest.mock.patch.object(RNC.subprocess, "run", self._stub(write=None, rc=1)):
            with self.assertRaises(RNC.NotMeasured) as ctx:
                RNC.run_population(self.root, ["m/test_a.py"], self.record)
        text = str(ctx.exception)
        self.assertIn("junit-записи нет", text)
        self.assertIn("ADR-474", text, "снятая сессия обязана быть названа своим именем")

    def test_пустая_запись_это_НЕ_ИЗМЕРЕНО_а_не_ноль_поломок(self):
        with unittest.mock.patch.object(RNC.subprocess, "run", self._stub(write=[], rc=0)):
            with self.assertRaises(RNC.NotMeasured) as ctx:
                RNC.run_population(self.root, ["m/test_a.py"], self.record)
        self.assertIn("ноль случаев", str(ctx.exception))

    def test_битая_запись_это_НЕ_ИЗМЕРЕНО(self):
        def fake_run(cmd, **kw):
            target = Path([c for c in cmd if str(c).startswith("--junitxml=")][0]
                          .split("=", 1)[1])
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("<testsuites", encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        with unittest.mock.patch.object(RNC.subprocess, "run", fake_run):
            with self.assertRaises(RNC.NotMeasured) as ctx:
                RNC.run_population(self.root, ["m/test_a.py"], self.record)
        self.assertIn("не разобрана", str(ctx.exception))

    def test_pytest_не_запустился_это_НЕ_ИЗМЕРЕНО(self):
        def boom(cmd, **kw):
            raise FileNotFoundError("нет такого файла: python")
        with unittest.mock.patch.object(RNC.subprocess, "run", boom):
            with self.assertRaises(RNC.NotMeasured) as ctx:
                RNC.run_population(self.root, ["m/test_a.py"], self.record)
        self.assertIn("pytest не запущен", str(ctx.exception))

    def test_снятие_по_сроку_это_НЕ_ИЗМЕРЕНО(self):
        def slow(cmd, **kw):
            raise subprocess.TimeoutExpired(cmd, 1.0)
        with unittest.mock.patch.object(RNC.subprocess, "run", slow):
            with self.assertRaises(RNC.NotMeasured) as ctx:
                RNC.run_population(self.root, ["m/test_a.py"], self.record, timeout_s=1.0)
        self.assertIn("снят по сроку", str(ctx.exception))

    def test_красный_прогон_это_ЗАМЕР_а_не_отказ(self):
        """Код возврата 1 у pytest = «тесты упали», и это ИЗМЕРЕНО, а не сломано."""
        with unittest.mock.patch.object(RNC.subprocess, "run",
                                        self._stub(write=[("m.test_a", "t1", True)], rc=1)):
            got = RNC.run_population(self.root, ["m/test_a.py"], self.record)
        self.assertEqual(got["returncode"], 1)
        self.assertEqual(got["cases_in_record"], 1)


class ТактРешаетФайл(unittest.TestCase):
    """`--if-due`: срок меряется возрастом артефакта, а не расписанием запуска."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.tmp.cleanup)

    def _artifact(self, hours_old: float) -> None:
        made = ANCHOR - timedelta(hours=hours_old)
        (self.root / census.REPORT_REL).write_text(json.dumps({
            "generated_at": made.isoformat().replace("+00:00", "Z"),
            "measured": True, "verdict": census.NO_REGRESSION}), encoding="utf-8")

    def test_свежий_артефакт_ничего_не_перезапускает(self):
        self._artifact(10.0)
        out = RNC.refresh(self.root, if_due=True, max_age_h=120.0, write=False, now=ANCHOR)
        self.assertFalse(out["ran"], "внутри такта прогон не нужен")
        self.assertFalse(out["due"])
        self.assertEqual(out["report"]["verdict"], census.NO_REGRESSION)
        self.assertIn("прежний", out["source"], "источник вердикта назван вслух")

    def test_протухший_артефакт_зовёт_прогон(self):
        self._artifact(200.0)
        called = {}

        def fake_run(root, files, record, **kw):
            called["yes"] = True
            _junit(Path(record), [("m.test_a", "t1", False)])
            return {"returncode": 0, "cases_in_record": 1, "record": str(record),
                    "tail": "", "files_requested": len(files)}
        with unittest.mock.patch.object(RNC, "run_population", fake_run), \
             unittest.mock.patch.object(RNC, "population_files", return_value=["m/test_a.py"]), \
             unittest.mock.patch.object(census, "measure",
                                        return_value={"measured": True,
                                                      "verdict": census.NO_REGRESSION}):
            out = RNC.refresh(self.root, if_due=True, max_age_h=120.0, write=False,
                              now=ANCHOR)
        self.assertTrue(called.get("yes"))
        self.assertTrue(out["ran"])

    def test_артефакта_нет_вовсе_это_срок_а_не_свежесть(self):
        with unittest.mock.patch.object(RNC, "run_population",
                                        side_effect=RNC.NotMeasured("дошло до прогона")), \
             unittest.mock.patch.object(RNC, "population_files", return_value=["m/test_a.py"]):
            with self.assertRaises(RNC.NotMeasured):
                RNC.refresh(self.root, if_due=True, write=False, now=ANCHOR)

    def test_запись_входом_прогона_не_требует(self):
        rec = self.root / "рука.xml"
        _junit(rec, [("m.test_a", "t1", False)])
        with unittest.mock.patch.object(census, "measure",
                                        return_value={"measured": True,
                                                      "verdict": census.NO_REGRESSION}) as m:
            out = RNC.refresh(self.root, junit=[str(rec)], write=False, now=ANCHOR)
        self.assertFalse(out["ran"])
        self.assertEqual(m.call_args.kwargs["junit_paths"], [str(rec)])
        self.assertIn("входом", out["source"])

    def test_возраст_измерен_а_отчёт_не_прочитан_это_НЕ_ИЗМЕРЕНО(self):
        """Отчёт исчез между замером возраста и его чтением — третий исход, не падение."""
        with unittest.mock.patch.object(RNC, "artifact_age_hours",
                                        return_value=(1.0, "возраст 1.0ч")):
            with self.assertRaises(RNC.NotMeasured) as ctx:
                RNC.refresh(self.root, if_due=True, max_age_h=120.0, write=False, now=ANCHOR)
        self.assertIn("не прочитан", str(ctx.exception))

    def test_осознанный_обход_ВИДЕН_в_отчёте(self):
        """Молчаливый обход отказа превратил бы сам отказ в украшение."""
        rec = self.root / "рука.xml"
        _junit(rec, [("m.test_a", "t1", False)])
        full = {"measured": True, "verdict": census.NO_REGRESSION, "population_total": 1,
                "failed_total": 0, "unmeasured_total": 0, "records_read": [str(rec)],
                "records_unread": [], "surfaces": {}, "failed": [], "unmeasured_members": [],
                "generated_at": "x", "repo_head": None, "cases_without_file": 0,
                "records_meta": []}
        with unittest.mock.patch.object(census, "measure", return_value=full):
            tacit = RNC.refresh(self.root, junit=[str(rec)], write=False, now=ANCHOR)
            loud = RNC.refresh(self.root, junit=[str(rec)], write=False, now=ANCHOR,
                               allow_prod_tree=True)
        self.assertFalse(tacit["allow_prod_tree"])
        self.assertTrue(loud["allow_prod_tree"])
        self.assertFalse([l for l in RNC._lines(tacit) if "[ОБХОД]" in l],
                         "без обхода строки быть не должно — иначе она ничего не различает")
        self.assertTrue([l for l in RNC._lines(loud) if "[ОБХОД]" in l])

    def test_предел_такта_НИЖЕ_предела_пробы(self):
        """Равные пороги означали бы протухание ровно в момент наступления срока."""
        from spa_core.monitoring import card_acceptance
        self.assertLess(RNC.DEFAULT_MAX_AGE_H, card_acceptance._NO_REGRESSION_MAX_AGE_H)


class СнятиеЗаписей(unittest.TestCase):
    """Удаление необратимо: по умолчанию не снимается ничего."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.base = self.root / RNC.RECORDS_REL
        self.base.mkdir(parents=True, exist_ok=True)
        for name in ("20260101T000000Z", "20260102T000000Z", "20260103T000000Z"):
            _junit(self.base / f"{name}.xml", [("m.test_a", "t1", False)])
        (self.base / "заметка.txt").write_text("не запись", encoding="utf-8")
        self.addCleanup(self.tmp.cleanup)

    def test_по_умолчанию_не_снимается_ничего(self):
        self.assertEqual(RNC.prune_records(self.root, 0), [])
        self.assertEqual(len(list(self.base.glob("*.xml"))), 3)

    def test_остаются_самые_свежие(self):
        dropped = RNC.prune_records(self.root, 2)
        left = sorted(p.name for p in self.base.glob("*.xml"))
        self.assertEqual(left, ["20260102T000000Z.xml", "20260103T000000Z.xml"])
        self.assertEqual(len(dropped), 1)

    def test_чужие_файлы_не_трогаются(self):
        RNC.prune_records(self.root, 1)
        self.assertTrue((self.base / "заметка.txt").exists(),
                        "снимаются только собственные записи собственного расширения")

    def test_каталога_нет_это_не_ошибка_и_не_удаление(self):
        with TemporaryDirectory() as empty:
            self.assertEqual(RNC.prune_records(Path(empty), 5), [])


class КодВозвратаГоворитОКритерии(unittest.TestCase):
    """0 — зелено · 1 — поломки НАЗВАНЫ · 2 — НЕ ИЗМЕРЕНО. Ни одной склейки."""

    def _main_with(self, report):
        with unittest.mock.patch.object(RNC, "refresh",
                                        return_value={"due": True, "ran": True,
                                                      "artifact_age_h": None,
                                                      "age_reason": "—", "max_age_h": 120.0,
                                                      "source": "прогон", "report": report}):
            return RNC._main(["--no-write"])

    def test_зелено_ноль(self):
        self.assertEqual(self._main_with({
            "measured": True, "verdict": census.NO_REGRESSION, "population_total": 3,
            "failed_total": 0, "unmeasured_total": 0, "records_read": ["r.xml"],
            "records_unread": [], "surfaces": {}, "failed": [], "unmeasured_members": [],
            "generated_at": "x", "repo_head": None, "cases_without_file": 0,
            "records_meta": []}), 0)

    def test_поломка_единица(self):
        self.assertEqual(self._main_with({
            "measured": True, "verdict": census.REGRESSION, "population_total": 3,
            "failed_total": 1, "unmeasured_total": 0, "records_read": ["r.xml"],
            "records_unread": [], "surfaces": {}, "generated_at": "x", "repo_head": None,
            "failed": [{"surface": "risk", "file": "a.py",
                        "cases": [{"case": "a::t1", "kind": "failure",
                                   "message": "boom"}]}],
            "unmeasured_members": [], "cases_without_file": 0, "records_meta": []}), 1)

    def test_перепись_не_измерила_двойка(self):
        self.assertEqual(self._main_with({"measured": False, "reason": "записи нет"}), 2)

    def test_вердикт_НЕ_ИЗМЕРЕНО_двойка_хотя_перепись_измерила(self):
        """Дыра в населении — третий исход, и зелёным кодом он не выдаётся."""
        self.assertEqual(self._main_with({
            "measured": True, "verdict": census.UNMEASURED, "population_total": 3,
            "failed_total": 0, "unmeasured_total": 1, "records_read": ["r.xml"],
            "records_unread": [], "surfaces": {}, "failed": [], "generated_at": "x",
            "repo_head": None, "cases_without_file": 0, "records_meta": [],
            "unmeasured_members": [{"surface": "risk", "file": "a.py",
                                    "kind": census.ABSENT_FROM_RECORD, "reason": "нет"}]}), 2)

    def test_отказ_прибора_двойка(self):
        with unittest.mock.patch.object(RNC, "refresh",
                                        side_effect=RNC.NotMeasured("дерево боевое")):
            self.assertEqual(RNC._main(["--no-write"]), 2)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
