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
import os
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


def _guard_report(env: dict, **extra) -> None:
    """Заглушка играет потомка pytest — значит, и его сторожа записи: отчёт установленного
    сторожа в каталог, который назначил прогон (без него прогон честно НЕ ИЗМЕРЕН)."""
    d = env.get(RNC.GUARD_REPORT_ENV)
    if not d:
        return
    roots = [os.path.realpath(r) for r in env.get(RNC.GUARD_ROOTS_ENV, "").split(os.pathsep) if r]
    doc = {"pid": 4242, "installed": True, "roots": roots, "argv0": "__main__.py",
           "pytest": True, "refused": [], "live_reads": 0, "children": [], **extra}
    Path(d, "4242.json").write_text(json.dumps(doc), encoding="utf-8")


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
            _guard_report(kw.get("env") or {})
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
        self.assertEqual(kw["env"]["SPA_DATA_DIR"], str(self.root / "data"),
                         "живое состояние потомка — в дереве прогона, а не в боевом")
        self.assertEqual(kw["env"]["SPA_LIVE_ROOT"], str(self.root))

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
    """`--if-due`: срок меряется возрастом артефакта, а не расписанием запуска.

    Каждый вызов `refresh` здесь НАЗЫВАЕТ каталог хранения: умолчание —
    `DEFAULT_RECORDS_ROOT`, то есть БОЕВОЕ дерево, и забытый вход означает тест,
    пишущий в прод (замер 17.10: этот набор оставил там запись на 145 байт).
    Сторож забывчивости — `НичегоНеУтеклоВПрод` ниже.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "data").mkdir(parents=True, exist_ok=True)
        self.store = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.addCleanup(self.store.cleanup)

    def _artifact(self, hours_old: float, repo_head: str | None = "head-A") -> None:
        made = ANCHOR - timedelta(hours=hours_old)
        (self.root / census.REPORT_REL).write_text(json.dumps({
            "generated_at": made.isoformat().replace("+00:00", "Z"), "repo_head": repo_head,
            "measured": True, "verdict": census.NO_REGRESSION}), encoding="utf-8")

    def test_свежий_артефакт_ничего_не_перезапускает(self):
        """Свеж И о том же коммите, что HEAD дерева, — только тогда не срок."""
        self._artifact(10.0, repo_head="head-A")
        with unittest.mock.patch.object(RNC, "_tree_head", return_value="head-A"):
            out = RNC.refresh(self.root, if_due=True, max_age_h=120.0, write=False, now=ANCHOR,
                              records_root=Path(self.store.name))
        self.assertFalse(out["ran"], "внутри такта прогон не нужен")
        self.assertFalse(out["due"])
        self.assertEqual(out["report"]["verdict"], census.NO_REGRESSION)
        self.assertIn("прежний", out["source"], "источник вердикта назван вслух")

    def _assert_due(self, head):
        with unittest.mock.patch.object(RNC, "_tree_head", return_value=head), \
             unittest.mock.patch.object(RNC, "run_population",
                                        side_effect=RNC.NotMeasured("дошло до прогона")), \
             unittest.mock.patch.object(RNC, "population_files", return_value=["m/test_a.py"]):
            with self.assertRaises(RNC.NotMeasured) as ctx:
                RNC.refresh(self.root, if_due=True, max_age_h=120.0, write=False, now=ANCHOR,
                            records_root=Path(self.store.name))
        self.assertIn("дошло до прогона", str(ctx.exception), "свежесть не выдана за проверку")

    def test_свежий_отчёт_о_другом_коммите_это_срок(self):
        """Раньше хватало возраста: отчёт о коммите A выдавался за проверку коммита B."""
        self._artifact(10.0, repo_head="head-A")
        self._assert_due("head-B")

    def test_свежий_отчёт_без_отметки_коммита_это_срок(self):
        self._artifact(10.0, repo_head=None)
        self._assert_due("head-A")

    def test_дерево_без_git_свежесть_не_доказывает(self):
        self._artifact(10.0, repo_head="head-A")
        self._assert_due(None)

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
                              now=ANCHOR, records_root=Path(self.store.name))
        self.assertTrue(called.get("yes"))
        self.assertTrue(out["ran"])

    def test_артефакта_нет_вовсе_это_срок_а_не_свежесть(self):
        with unittest.mock.patch.object(RNC, "run_population",
                                        side_effect=RNC.NotMeasured("дошло до прогона")), \
             unittest.mock.patch.object(RNC, "population_files", return_value=["m/test_a.py"]):
            with self.assertRaises(RNC.NotMeasured):
                RNC.refresh(self.root, if_due=True, write=False, now=ANCHOR,
                            records_root=Path(self.store.name))

    def test_запись_входом_прогона_не_требует(self):
        rec = self.root / "рука.xml"
        _junit(rec, [("m.test_a", "t1", False)])
        with unittest.mock.patch.object(census, "measure",
                                        return_value={"measured": True,
                                                      "verdict": census.NO_REGRESSION}) as m:
            out = RNC.refresh(self.root, junit=[str(rec)], write=False, now=ANCHOR,
                                records_root=Path(self.store.name))
        self.assertFalse(out["ran"])
        self.assertEqual(m.call_args.kwargs["junit_paths"], [str(rec)])
        self.assertIn("входом", out["source"])

    def test_возраст_измерен_а_отчёт_не_прочитан_это_срок_а_не_свежесть(self):
        """Отчёт исчез между замером возраста и его чтением: его коммит не узнать ⇒ это СРОК —
        замер идёт заново (раньше такой случай отказывал вовсе, блокируя свежий замер)."""
        with unittest.mock.patch.object(RNC, "artifact_age_hours",
                                        return_value=(1.0, "возраст 1.0ч")):
            self._assert_due("head-A")

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
            tacit = RNC.refresh(self.root, junit=[str(rec)], write=False, now=ANCHOR,
                                records_root=Path(self.store.name))
            loud = RNC.refresh(self.root, junit=[str(rec)], write=False, now=ANCHOR,
                               records_root=Path(self.store.name), allow_prod_tree=True)
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


class ЗаписьПереживаетДеревоПрогона(unittest.TestCase):
    """Где ГНАТЬ и где ХРАНИТЬ — два разных входа, и это не стилистика.

    Прогон обязан идти в ОДНОРАЗОВОМ дереве, а одноразовое дерево исчезает вместе с
    записью. Если хранилище привязано к дереву прогона, заказ «записи прогона на хосте
    не держит никто» остаётся НЕвыполненным ровно в том месте, где объявлен закрытым.
    """

    def setUp(self):
        self.run_tree = TemporaryDirectory()
        self.store = TemporaryDirectory()
        (Path(self.run_tree.name) / "data").mkdir(parents=True, exist_ok=True)
        self.addCleanup(self.run_tree.cleanup)
        self.addCleanup(self.store.cleanup)

    def test_запись_ложится_в_каталог_хранения_а_не_в_дерево_прогона(self):
        seen = {}

        def fake_run(root, files, record, **kw):
            seen["record"] = Path(record)
            _junit(Path(record), [("m.test_a", "t1", False)])
            return {"returncode": 0, "cases_in_record": 1, "record": str(record),
                    "tail": "", "files_requested": len(files)}
        with unittest.mock.patch.object(RNC, "run_population", fake_run),              unittest.mock.patch.object(RNC, "population_files", return_value=["m/test_a.py"]),              unittest.mock.patch.object(census, "measure",
                                        return_value={"measured": True,
                                                      "verdict": census.NO_REGRESSION}):
            out = RNC.refresh(Path(self.run_tree.name), write=False, now=ANCHOR,
                              records_root=Path(self.store.name))
        self.assertEqual(out["records_root"], self.store.name)
        self.assertIn(Path(self.store.name), seen["record"].parents,
                      "запись обязана лежать в каталоге ХРАНЕНИЯ")
        self.assertNotIn(Path(self.run_tree.name), seen["record"].parents,
                         "в дереве прогона запись умрёт вместе с деревом")

    def test_умолчание_хранилища_не_есть_дерево_прогона(self):
        """Положительный контроль на САМО умолчание, а не только на явный вход."""
        self.assertEqual(RNC.DEFAULT_RECORDS_ROOT,
                         Path.home() / "Documents" / "SPA_Claude")
        self.assertNotEqual(RNC.DEFAULT_RECORDS_ROOT, Path(self.run_tree.name))


class НичегоНеУтеклоВПрод(unittest.TestCase):
    """Набор не оставляет записей в БОЕВОМ дереве — и это проверяется, а не обещается.

    Замер 17.10 (эта же доставка): `DEFAULT_RECORDS_ROOT` — боевое дерево, и тест,
    забывший передать `records_root`, написал туда junit-фикстуру на 145 байт. Отказ
    `_refuse_if_prod_tree` этого не ловит ПО ПОСТРОЕНИЮ: он про дерево ПРОГОНА, а не
    про каталог хранения. Поэтому у забывчивости свой сторож.
    """

    def test_ни_один_тест_набора_не_написал_в_боевое_хранилище(self):
        live = RNC.DEFAULT_RECORDS_ROOT / RNC.RECORDS_REL
        if not live.is_dir():
            return  # хранилища нет — писать было некуда, утечки нет
        fixtures = [p.name for p in live.glob("*.xml")
                    if p.stat().st_size < 1024 and b"m.test_a" in p.read_bytes()]
        self.assertEqual(fixtures, [], f"фикстуры набора утекли в {live}: {fixtures}")


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


def _git_repo(root: Path) -> str:
    """Временный git-репозиторий с одним коммитом; конфиг хоста не читается."""
    import os
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
               GIT_COMMITTER_EMAIL="t@t")
    (root / "spa_core").mkdir(parents=True)
    (root / "spa_core" / "marker.py").write_text("COMMITTED = True\n", encoding="utf-8")
    for cmd in (["init", "-q", "-b", "main"], ["add", "-A"], ["commit", "-q", "-m", "c"]):
        subprocess.run(["git", "-C", str(root), *cmd], check=True, env=env)
    return subprocess.run(["git", "-C", str(root), "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True, env=env).stdout.strip()


def _tree_bytes(root: Path) -> dict:
    return {str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
            if p.is_file() and ".git" not in p.relative_to(root).parts}


class РежимРасписания(unittest.TestCase):
    """`--scheduled`: прогон в снимке коммита, отчёт — в живой `data/`; агент не включён."""

    def setUp(self):
        self._tmp = TemporaryDirectory(prefix="nrc_sched_")
        self.root = Path(self._tmp.name)
        self.live = self.root / "live"
        self.live.mkdir()
        self.sha = _git_repo(self.live)
        self.work = self.root / "work"
        self.work.mkdir()
        self.calls = []

    def tearDown(self):
        self._tmp.cleanup()

    def _fake_refresh(self, repo_root, **kw):
        self.calls.append((Path(repo_root), kw))
        snap = Path(repo_root) / "spa_core" / "marker.py"
        self.seen = snap.read_text(encoding="utf-8") if snap.exists() else None
        return {"ran": True, "run": {"record": "r.xml"},
                "report": {"verdict": "NO_REGRESSION", "measured": True,
                           "generated_at": ANCHOR.isoformat()}}

    def _put_report(self, hours_old: float, sha: str | None = None):
        p = self.live / "data" / "no_regression_census.json"
        p.parent.mkdir(exist_ok=True)
        doc = {"generated_at": (ANCHOR - timedelta(hours=hours_old)).isoformat(),
               "verdict": "REGRESSION", "measured": True}
        if sha:
            doc["invoked_by"] = {"entry": "scheduled", "sha": sha}
        p.write_text(json.dumps(doc), encoding="utf-8")

    def test_трек_изменился_за_прогон_это_отказ_и_живой_отчёт_цел(self):
        """Третья линия изоляции: не-Python потомок сторожу записи не виден, хеш трека — виден."""
        track = self.live / RNC.TRACK_REL
        track.parent.mkdir(exist_ok=True)
        track.write_text("[1]", encoding="utf-8")
        self._put_report(500, sha="old")
        report_before = (self.live / "data" / "no_regression_census.json").read_bytes()

        def leaking(repo_root, **kw):
            track.write_text("[1, 2]", encoding="utf-8")
            return self._fake_refresh(repo_root, **kw)
        with self.assertRaises(RNC.NotMeasured) as ctx:
            RNC.scheduled(self.live, ref="main", now=ANCHOR, refresh_fn=leaking, workdir=self.work)
        self.assertIn("изменился за время прогона", str(ctx.exception))
        self.assertEqual((self.live / "data" / "no_regression_census.json").read_bytes(), report_before)
        self.assertTrue(list((self.live / RNC.RECORDS_REL).glob("*.refusal.json")))

    def test_охраняется_и_корень_отчёта(self):
        out = RNC.scheduled(self.live, ref="main", now=ANCHOR, refresh_fn=self._fake_refresh,
                            workdir=self.work)
        self.assertTrue(out["due"])
        roots = self.calls[-1][1]["protected_roots"]
        self.assertIn(self.live.resolve(), roots)

    def test_вердикт_изоляции_едет_в_отметку_отчёта(self):
        def iso(repo_root, **kw):
            out = self._fake_refresh(repo_root, **kw)
            out["run"]["isolation"] = {"refused_writes": 0, "protected_roots": ["/x"]}
            return out
        out = RNC.scheduled(self.live, ref="main", now=ANCHOR, refresh_fn=iso, workdir=self.work)
        self.assertEqual(out["report"]["invoked_by"]["isolation"]["refused_writes"], 0)

    def test_свежий_отчёт_ничего_не_снимает_и_не_пишет(self):
        """Свеж И о том же коммите, который велено проверить, — только тогда не срок."""
        self._put_report(10, sha=self.sha)
        before = _tree_bytes(self.live)
        out = RNC.scheduled(self.live, ref="main", now=ANCHOR, refresh_fn=self._fake_refresh,
                            workdir=self.work)
        self.assertFalse(out["due"])
        self.assertEqual(self.calls, [])
        self.assertEqual(_tree_bytes(self.live), before)

    def test_свежий_отчёт_о_другом_коммите_снимает_заново(self):
        """Раньше хватало возраста: отчёт о другом коммите выдавался за проверку этого."""
        self._put_report(10, sha="0" * 40)
        out = RNC.scheduled(self.live, ref="main", now=ANCHOR, refresh_fn=self._fake_refresh,
                            workdir=self.work)
        self.assertTrue(out["due"])
        self.assertIn("другом коммите", out["due_reason"])
        self.assertEqual(len(self.calls), 1)

    def test_свежий_отчёт_без_отметки_коммита_снимает_заново(self):
        self._put_report(10)
        out = RNC.scheduled(self.live, ref="main", now=ANCHOR, refresh_fn=self._fake_refresh,
                            workdir=self.work)
        self.assertTrue(out["due"])

    def test_срок_прогон_в_снимке_коммита_отчёт_в_живое_data(self):
        self._put_report(500)
        # рабочая копия разошлась с коммитом — в снимок обязан попасть КОММИТ
        (self.live / "spa_core" / "marker.py").write_text("COMMITTED = False\n", encoding="utf-8")
        out = RNC.scheduled(self.live, ref="main", now=ANCHOR, refresh_fn=self._fake_refresh,
                            workdir=self.work)
        (snap_root, kw), = self.calls
        self.assertNotEqual(snap_root.resolve(), self.live.resolve(), "прогон не в боевом дереве")
        self.assertEqual(self.seen, "COMMITTED = True\n", "снимок — точный коммит, не рабочая копия")
        self.assertEqual(kw["records_root"], self.live)
        self.assertFalse(kw["write"], "снимок отчёт себе не пишет — пишет режим расписания")
        doc = json.loads((self.live / "data" / "no_regression_census.json").read_text())
        inv = doc["invoked_by"]
        self.assertEqual({k: inv[k] for k in ("entry", "producer", "ref", "sha", "tree")},
                         {"entry": "scheduled", "producer": RNC.SCHEDULED_PRODUCER,
                          "ref": "main", "sha": self.sha, "tree": "git archive snapshot"})
        env = inv["env"]
        self.assertTrue(env["python"] and env["platform"], "окружение вердикта записано")
        self.assertEqual(env["run_env"], RNC.RUN_ENV)
        self.assertEqual(env["via"], "manual", "ручной запуск не выдаётся за работу агента")
        self.assertEqual(out["sha"], self.sha)
        self.assertEqual(list(self.work.iterdir()), [], "временный снимок удалён")
        self.assertEqual((self.live / "spa_core" / "marker.py").read_text(), "COMMITTED = False\n",
                         "рабочая копия боевого дерева не тронута")

    def test_отказ_прогона_живой_отчёт_не_трогает(self):
        self._put_report(500)
        before = (self.live / "data" / "no_regression_census.json").read_bytes()

        def boom(repo_root, **kw):
            raise RNC.NotMeasured("pytest не запущен")

        with self.assertRaises(RNC.NotMeasured):
            RNC.scheduled(self.live, ref="main", now=ANCHOR, refresh_fn=boom, workdir=self.work)
        self.assertEqual((self.live / "data" / "no_regression_census.json").read_bytes(), before)
        self.assertEqual(list(self.work.iterdir()), [])
        refusals = list((self.live / RNC.RECORDS_REL).glob("*.refusal.json"))
        self.assertEqual(len(refusals), 1, "причина отказа сохранена рядом с записями")
        rec = json.loads(refusals[0].read_text(encoding="utf-8"))
        self.assertEqual(rec["sha"], self.sha)
        self.assertIn("pytest не запущен", rec["reason"])
        self.assertTrue(rec["live_report_untouched"])

    def test_агентский_запуск_помечен_агентом(self):
        """Только обёртка агента ставит SPA_NO_REGRESSION_VIA — признак production-запуска."""
        self._put_report(500)
        with unittest.mock.patch.dict(os.environ, {RNC.VIA_ENV: "launchd:" + RNC.SCHEDULED_PRODUCER}):
            RNC.scheduled(self.live, ref="main", now=ANCHOR, refresh_fn=self._fake_refresh,
                          workdir=self.work)
        doc = json.loads((self.live / "data" / "no_regression_census.json").read_text())
        self.assertEqual(doc["invoked_by"]["env"]["via"], "launchd:" + RNC.SCHEDULED_PRODUCER)

    def test_неполная_запись_не_зеленеет(self):
        """Запись, где у части населения нет исхода, — НЕ «нет регрессий» (перепись: UNMEASURED)."""
        population = {"risk": ["spa_core/tests/test_a.py", "spa_core/tests/test_b.py"]}
        record = {"files": {"spa_core/tests/test_a.py": {"passed": 3, "skipped": 0, "bad": []}}}
        judged = census.judge(population, record)
        self.assertEqual(judged["verdict"], census.UNMEASURED)
        self.assertFalse(judged["complete"])
        self.assertEqual([u["file"] for u in judged["unmeasured_members"]], ["spa_core/tests/test_b.py"])
        # всё пропущено — тоже не «прошло»
        skipped = {"files": {"spa_core/tests/test_a.py": {"passed": 0, "skipped": 2, "bad": []},
                             "spa_core/tests/test_b.py": {"passed": 1, "skipped": 0, "bad": []}}}
        self.assertEqual(census.judge(population, skipped)["verdict"], census.UNMEASURED)

    def test_неизвестная_ссылка_это_НЕ_ИЗМЕРЕНО_до_снимка(self):
        self._put_report(500)
        with self.assertRaises(RNC.NotMeasured):
            RNC.scheduled(self.live, ref="no-such-ref", now=ANCHOR, refresh_fn=self._fake_refresh,
                          workdir=self.work)
        self.assertEqual(self.calls, [])
        self.assertEqual(list(self.work.iterdir()), [])

    def test_обёртка_и_plist_подготовлены_и_зовут_режим_расписания(self):
        import plistlib
        plist = REPO_ROOT / "launchd" / f"{RNC.SCHEDULED_PRODUCER}.plist"
        doc = plistlib.loads(plist.read_bytes())
        self.assertEqual(doc["Label"], RNC.SCHEDULED_PRODUCER)
        self.assertEqual(doc["ProgramArguments"][0], "/bin/bash")
        wrapper = Path(doc["ProgramArguments"][1])
        self.assertEqual(wrapper.name, "agent_no_regression_census.sh")
        self.assertIs(doc["RunAtLoad"], False)
        text = (REPO_ROOT / "scripts" / wrapper.name).read_text(encoding="utf-8")
        self.assertIn("refresh_no_regression_census.py", text)
        self.assertIn("--scheduled", text)
        self.assertIn("agent_template.sh", text)
        self.assertIn(f'{RNC.VIA_ENV}="launchd:{RNC.SCHEDULED_PRODUCER}"', text,
                      "обёртка агента помечает запуск как агентский")


_SCENE_CONFTEST = "import sys, os\nsys.dont_write_bytecode = True\n"


class ИзоляцияПрогонаОтБоевогоКорня(unittest.TestCase):
    """Снимок кода — не изоляция: потомок pytest не вправе писать под охраняемым корнем.

    Сцены гоняют НАСТОЯЩИЙ pytest-потомок; охраняемый корень — временный каталог,
    изображающий боевое дерево (настоящее боевое дерево не трогается и не читается)."""

    def setUp(self):
        self.tmp = TemporaryDirectory()
        base = Path(self.tmp.name)
        self.addCleanup(self.tmp.cleanup)
        self.root = base / "run"
        self.live = base / "live"
        (self.root / "m").mkdir(parents=True)
        (self.live / "data").mkdir(parents=True)
        (self.live / "data" / "track.json").write_text("{}", encoding="utf-8")
        (self.root / "conftest.py").write_text(_SCENE_CONFTEST, encoding="utf-8")
        self.record = base / "store" / RNC.RECORDS_REL / "run.xml"

    def _run(self, body: str, **kw):
        (self.root / "m" / "test_scene.py").write_text(
            "import os, subprocess\nLIVE = %r\n\n" % str(self.live) + body, encoding="utf-8")
        return RNC.run_population(self.root, ["m/test_scene.py"], self.record,
                                  protected_roots=[self.live], timeout_s=120, **kw)

    def test_запись_в_боевой_корень_отказана_и_замер_НЕ_состоялся(self):
        with self.assertRaises(RNC.NotMeasured) as ctx:
            self._run("def test_w():\n    open(os.path.join(LIVE, 'data', 'leak.json'), 'w').write('x')\n")
        self.assertIn("изоляция НАРУШЕНА", str(ctx.exception))
        self.assertFalse((self.live / "data" / "leak.json").exists(), "запись дошла до корня")
        self.assertFalse(self.record.exists(), "запись прогона с нарушенной изоляцией не хранится")

    def test_переименование_и_удаление_в_корне_тоже_отказаны(self):
        with self.assertRaises(RNC.NotMeasured):
            self._run("def test_r():\n    os.remove(os.path.join(LIVE, 'data', 'track.json'))\n")
        self.assertTrue((self.live / "data" / "track.json").exists())
        with self.assertRaises(RNC.NotMeasured):
            self._run("def test_r():\n    p = os.path.join(LIVE, 'data', 'track.json')\n"
                      "    os.replace(p, p + '.x')\n")
        self.assertTrue((self.live / "data" / "track.json").exists())

    def test_чтение_корня_разрешено_и_названо_числом(self):
        got = self._run("def test_r():\n    assert open(os.path.join(LIVE, 'data', 'track.json')).read() == '{}'\n")
        self.assertEqual(got["returncode"], 0)
        iso = got["isolation"]
        self.assertEqual(iso["refused_writes"], 0)
        self.assertGreaterEqual(iso["live_reads"], 1)
        self.assertEqual(iso["protected_roots"], [os.path.realpath(self.live)])
        self.assertTrue(self.record.exists(), "запись перенесена в хранилище родителем")

    def test_потомок_видит_песочницу_а_не_живое(self):
        with unittest.mock.patch.dict(os.environ, {"SPA_ALLOW_LIVE_WRITE": "1"}):
            got = self._run(
                "def test_e():\n"
                "    r = os.path.realpath\n"
                "    assert r(os.environ['SPA_DATA_DIR']) == r(os.path.join(os.getcwd(), 'data'))\n"
                "    assert r(os.environ['SPA_LIVE_ROOT']) == r(os.getcwd())\n"
                "    assert 'SPA_ALLOW_LIVE_WRITE' not in os.environ\n")
        self.assertEqual(got["returncode"], 0, got["tail"])

    def test_не_Python_потомок_назван_неохваченным(self):
        got = self._run("def test_c():\n    subprocess.run(['/bin/echo', 'x'], check=True, capture_output=True)\n")
        self.assertIn("echo", got["isolation"]["unaudited_children"])

    def test_нет_отчёта_сторожа_это_НЕ_ДОКАЗАНО(self):
        def silent(cmd, **kw):
            target = Path([c for c in cmd if str(c).startswith("--junitxml=")][0].split("=", 1)[1])
            _junit(target, [("m.test_a", "t1", False)])
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        with unittest.mock.patch.object(RNC.subprocess, "run", silent):
            with self.assertRaises(RNC.NotMeasured) as ctx:
                RNC.run_population(self.root, ["m/test_a.py"], self.record,
                                   protected_roots=[self.live])
        self.assertIn("НЕ ДОКАЗАНА", str(ctx.exception))

    def test_отчёт_о_другом_корне_не_засчитывается(self):
        def wrong(cmd, **kw):
            target = Path([c for c in cmd if str(c).startswith("--junitxml=")][0].split("=", 1)[1])
            _junit(target, [("m.test_a", "t1", False)])
            _guard_report({**kw["env"], RNC.GUARD_ROOTS_ENV: "/elsewhere"})
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        with unittest.mock.patch.object(RNC.subprocess, "run", wrong):
            with self.assertRaises(RNC.NotMeasured):
                RNC.run_population(self.root, ["m/test_a.py"], self.record,
                                   protected_roots=[self.live])

    def test_охраняемый_по_умолчанию_корень_есть_боевой(self):
        from spa_core.utils.live_paths import DEFAULT_LIVE_ROOT
        self.assertEqual(RNC.default_protected_roots(self.root), [Path(DEFAULT_LIVE_ROOT).resolve()])
        self.assertEqual(RNC.default_protected_roots(Path(DEFAULT_LIVE_ROOT)), [])
