"""Проводка переписи оси РАБОТНИКА (ADR-843, заказ G842 п. 2).

Предмет. `scripts/worker_axis_census.py` написан 14.10 (ADR-722) как прибор, мерящий
ИЗМЕРИМОСТЬ оси РАБОТНИКА — и до 28.10 его не звал НИКТО. Замер на чистой вершине
`origin/main c5dde98f4`:

* храповик сирот `test_unwired_scripts_ratchet` КРАСЕН, и единственное его имя — этот
  прибор («новые скрипты с точкой входа, которых никто не вызывает»);
* в конституции (`architecture/manifest.json`) артефакта не было вовсе — значит у него
  не было ни SLO, ни потребителя, ни производителя;
* шаг 0-офис о приборе не знал ни строкой.

Прибор был ровно тем, что сам измеряет: **написанной и не позванной проверкой.** Это
класс ADR-345, и чинит его ПРОВОДКА, а не строка в базе храповика (инв. #16).

Каждый тест ниже — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ одного порванного звена, и звено названо в
его docstring. Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`, § «Проверка сторожа сторожей»).

Живую машину этот файл не спрашивает ни разу: и подпроцесс, и `ps`, и часы — ВХОДЫ.
Единственный литеральный якорь времени — :data:`NOW`, и обе стороны каждого сравнения
возраста от него производны.

# FROZEN-DATE-OK: injected-clock — якорь `NOW` уезжает входом `now=NOW` в
# `wac.run(...)`, а отметка отчёта-сцены считается от него же (`NOW - timedelta`);
# обе стороны сравнения закреплены одним якорем, стенных часов в файле нет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.monitoring import findings_bridge as fb  # noqa: E402
from spa_core.tests._unwired import unwired_scripts  # noqa: E402

PRODUCER_REL = os.path.join("scripts", "worker_axis_census.py")
ARTIFACT = "data/worker_axis_census.json"
STAGE = "worker_axis_census"

#: Момент замера — ВХОД сцены. Ни одна другая дата в файле не литерал.
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


wac = _load("_t964_wac", PRODUCER_REL)
wrap = _load("_t964_wrap", os.path.join("scripts", "claude_run_with_timeout.py"))

MARK = "orchestrator-24396-ABC"


def _scene(rows):
    """rows: pid → (командная строка, хвост окружения). Живого `ps` здесь нет."""
    snap_rows, argv = {}, {}
    for pid, (cmd, env) in rows.items():
        argv[pid] = cmd
        snap_rows[pid] = (1, "S", 10.0, f"{cmd} {env}".strip())
    readable = sum(1 for _p, (_pp, _s, _a, tail) in snap_rows.items()
                   if "=" in tail and " PATH=" in " " + tail)
    return wrap.Snapshot(snap_rows, readable, len(snap_rows) - readable), argv


class _Runner:
    """Дверь к подпроцессу ВХОДОМ: что бы ни ответил настоящий `ps`, тест судит проводку."""

    def __init__(self, code=0, out="", err="", raise_=None):
        self.code, self.out, self.err, self.raise_ = code, out, err, raise_
        self.cmd = None

    def __call__(self, cmd, **kw):
        self.cmd = cmd
        if self.raise_ is not None:
            raise self.raise_
        return subprocess.CompletedProcess(cmd, self.code, self.out, self.err)


# ─────────────────────────── 1. храповик сирот ────────────────────────────────

class TheOrphanRatchetNoLongerNamesTheProducer(unittest.TestCase):
    """Порванное звено: ЗОВА не было ни одного — прибор числился сиротой."""

    def test_the_real_repo_no_longer_names_it(self):
        self.assertNotIn("worker_axis_census", unwired_scripts(_REPO),
                         "прибор снова сирота: зов из ступени моста пропал")

    def test_control_without_the_call_the_name_comes_back(self):
        """ОБРАТНАЯ половина: убери зов — и храповик обязан назвать прибор снова.

        Без этого контроля тест выше проходил бы и у сторожа, который не находит
        НИЧЕГО и НИКОГДА (`.claude/rules/deployment.md`, § «обратная половина»).
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "scripts").mkdir()
            (root / "spa_core" / "monitoring").mkdir(parents=True)
            (root / "scripts" / "worker_axis_census.py").write_text(
                'if __name__ == "__main__":\n    pass\n', encoding="utf-8")
            # дерево БЕЗ зова: ни обёртки, ни ступени, ни записи в реестре R&D
            self.assertIn("worker_axis_census", unwired_scripts(root),
                          "храповик не назвал сироту в дереве, где зова НЕТ — "
                          "значит он не умеет находить, и зелень выше ничего не стоит")


# ─────────────────────── 2. ступень объявлена и ЗОВЁТСЯ ───────────────────────

class TheStageIsDeclaredAndActuallyCalled(unittest.TestCase):
    """Порванное звено: «путь в файле проводкой не является» (урок ADR-835)."""

    def test_it_is_in_both_declarations(self):
        self.assertIn(STAGE, fb.CENSUS_STAGE,
                      "ступень не числится переписью: «пропущено» станет "
                      "неотличимо от «не бывало»")
        self.assertIn(STAGE, fb.CENSUS_PRODUCT,
                      "читатель, идущий по CENSUS_PRODUCT, артефакта не найдёт")

    def test_the_product_points_at_the_single_constant(self):
        """Второй литерал того же пути разошёлся бы с первым МОЛЧА (класс ADR-220)."""
        self.assertEqual(fb.CENSUS_PRODUCT[STAGE]["module"],
                         fb.WORKER_AXIS_CENSUS_PRODUCER)
        self.assertEqual(fb.CENSUS_PRODUCT[STAGE]["artifact"], ARTIFACT)
        self.assertEqual(fb.WORKER_AXIS_CENSUS_PRODUCER, PRODUCER_REL)

    def test_main_really_calls_the_stage(self):
        """Объявление — не зов. Спрашивается ТЕЛО `main()` разбором AST.

        Ровно этот зазор ADR-835 нашёл у таблицы весов CI: пять сторожей числились
        «подключёнными» по строке с путём их же теста, а зова не было.
        """
        src = (_REPO / "spa_core" / "monitoring" / "findings_bridge.py").read_text(
            encoding="utf-8")
        main = next(n for n in ast.walk(ast.parse(src))
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        called = {n.func.id for n in ast.walk(main)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("worker_axis_census_step", called,
                      "ступень объявлена, но из тела main() не зовётся — "
                      "объявление зовом не является")


# ──────────────────── 3. исходы ступени различимы ─────────────────────────────

class _Save:
    """Дверь к ДИСКУ входом: тест проводки не пишет в живое `data/`."""

    def __init__(self):
        self.calls = []

    def __call__(self, doc, path):
        self.calls.append((doc, path))


_DOC = {"status": "CLEAN", "rows_total": 7, "findings": []}
_DOC_FINDING = {"status": "FINDING", "rows_total": 7, "findings": ["ось слепа"]}


def _due(tmp):
    """Дерево-сцена, где отчёта НЕТ ⇒ срок пришёл (первый замер)."""
    root = pathlib.Path(tmp)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "worker_axis_census.py").write_text("", encoding="utf-8")
    return str(root)


class TheStageKeepsItsOutcomesApart(unittest.TestCase):
    """Порванное звено: «не измерено», выданное за «находок нет» (инв. #17)."""

    def test_code_zero_is_measured_clean_and_the_report_is_written(self):
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.worker_axis_census_step(
                _due(tmp), runner=_Runner(0, json.dumps(_DOC)), writer=save, now=NOW)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(save.calls), 1, "отчёт не записан — читателю читать нечего")
        self.assertTrue(save.calls[0][1].endswith("data/worker_axis_census.json"))

    def test_code_one_is_a_named_finding(self):
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.worker_axis_census_step(
                _due(tmp), runner=_Runner(1, json.dumps(_DOC_FINDING)), writer=save, now=NOW)
        self.assertEqual(out["status"], "finding")
        self.assertEqual(out["findings"], 1)
        self.assertIn("ось слепа", out["reason"])
        self.assertEqual(len(save.calls), 1)

    def test_code_two_is_unmeasured_and_writes_nothing(self):
        """Отчёт при неответившем приборе лгал бы ещё и своим ВОЗРАСТОМ."""
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.worker_axis_census_step(
                _due(tmp), runner=_Runner(2, "", "НЕ ИЗМЕРЕНО: ps не ответил"),
                writer=save, now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("ps", out["reason"])
        self.assertEqual(save.calls, [])

    def test_a_missing_code_is_unmeasured_too(self):
        """Код, которого нет, — тот же третий исход, а не успех."""
        class _NoCode:
            stdout = stderr = ""

        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.worker_axis_census_step(_due(tmp), runner=lambda *a, **k: _NoCode(),
                                             writer=save, now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertEqual(save.calls, [])

    def test_an_unparsed_document_is_unmeasured_not_clean(self):
        """Код 0 при неразобранном документе — НЕ «находок нет»: вердикта не видел никто."""
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.worker_axis_census_step(_due(tmp), runner=_Runner(0, "не json"),
                                             writer=save, now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("не разобран", out["reason"])
        self.assertEqual(save.calls, [])

    def test_a_document_without_findings_key_is_unmeasured(self):
        """Документ без перечня находок прочёлся бы как «находок нет» — а это молчание."""
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.worker_axis_census_step(
                _due(tmp), runner=_Runner(0, json.dumps({"status": "CLEAN"})),
                writer=save, now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertEqual(save.calls, [])

    def test_a_failed_write_is_unmeasured_not_a_verdict(self):
        """Вердикт, не доехавший до диска, читателю недоступен — значит не измерен."""
        def _boom(doc, path):
            raise OSError("диск только для чтения")

        with tempfile.TemporaryDirectory() as tmp:
            out = fb.worker_axis_census_step(
                _due(tmp), runner=_Runner(0, json.dumps(_DOC)), writer=_boom, now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("не записан", out["reason"])

    def test_timeout_is_unmeasured_with_its_own_reason(self):
        boom = subprocess.TimeoutExpired(cmd="x", timeout=1)
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.worker_axis_census_step(_due(tmp), runner=_Runner(raise_=boom),
                                             writer=_Save(), now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("сроку", out["reason"])

    def test_a_producer_absent_from_disk_is_unmeasured(self):
        """Прибора нет ⇒ замера НЕ БЫЛО. Это не «находок нет»."""
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.worker_axis_census_step(tmp, runner=_Runner(0), writer=_Save())
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("нет на диске", out["reason"])

    def test_the_call_asks_the_producer_for_a_document_not_a_file(self):
        """Прибор отдаёт документ на stdout; пишет ПОЗВАВШИЙ (класс про сторожа ниже)."""
        r = _Runner(0, json.dumps(_DOC))
        with tempfile.TemporaryDirectory() as tmp:
            fb.worker_axis_census_step(_due(tmp), runner=r, writer=_Save(), now=NOW)
        self.assertIn("--json", r.cmd)
        self.assertNotIn("--write", r.cmd)
        self.assertIn(PRODUCER_REL, " ".join(r.cmd))

    def test_the_line_keeps_three_forms_for_three_outcomes(self):
        unm = fb.worker_axis_census_line({"status": "unmeasured", "reason": "ps молчит"})
        tact = fb.worker_axis_census_line({"status": "within_tact", "reason": "0.1 дн из 0.25"})
        ok = fb.worker_axis_census_line({"status": "ok", "code": 0, "findings": 0,
                                         "reason": "находок нет"})
        self.assertIn("НЕ ИЗМЕРЕНО", unm)
        self.assertIn("такт не истёк", tact)
        self.assertNotIn("НЕ ИЗМЕРЕНО", tact,
                         "«не мерили по сроку» слито с «не измерено» — это разные исходы")
        self.assertNotIn("НЕ ИЗМЕРЕНО", ok)
        self.assertNotIn("такт", ok)


# ──────────────── 4. такт решает ФАЙЛ, а не расписание бегуна ─────────────────

class TheTactIsDecidedByTheFile(unittest.TestCase):
    """Порванное звено: замер каждый час — и наоборот, выдуманный вердикт по сроку."""

    def _scene(self, tmp, age_h):
        root = pathlib.Path(_due(tmp))
        (root / "data").mkdir(exist_ok=True)
        (root / "data" / "worker_axis_census.json").write_text(json.dumps(
            {"generated_at": (NOW - timedelta(hours=age_h)).isoformat()}), encoding="utf-8")
        return str(root)

    def test_within_the_tact_the_subprocess_is_not_even_started(self):
        r, save = _Runner(0, json.dumps(_DOC)), _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.worker_axis_census_step(self._scene(tmp, 1.0), runner=r,
                                             writer=save, now=NOW)
        self.assertEqual(out["status"], "within_tact")
        self.assertIsNone(r.cmd, "внутри такта прибор всё равно подняли — такт не бесплатен")
        self.assertEqual(save.calls, [], "внутри такта отчёт перезаписан — возраст соврал бы")

    def test_past_the_tact_it_measures(self):
        r, save = _Runner(0, json.dumps(_DOC)), _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.worker_axis_census_step(self._scene(tmp, 7.0), runner=r,
                                             writer=save, now=NOW)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(save.calls), 1)

    def test_an_absent_report_means_measure_now(self):
        """Первого замера ещё не было — это «пора», а не «недавно мерили»."""
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.worker_axis_census_step(_due(tmp), runner=_Runner(0, json.dumps(_DOC)),
                                             writer=save, now=NOW)
        self.assertEqual(out["status"], "ok")

    def test_the_tact_gate_is_borrowed_not_copied(self):
        """Вторая копия правила «пора ли мерить» разошлась бы с первой молча."""
        from spa_core.monitoring import python_reader_clock_doors as prcd
        self.assertIs(fb.measurement_due, prcd.measurement_due)

    def test_the_instrument_declares_no_tact_of_its_own(self):
        """Срок решает ФАЙЛ, файл пишет ПОЗВАВШИЙ ⇒ такт живёт ровно у него, в одной копии."""
        self.assertFalse(hasattr(wac, "MEASUREMENT_TACT_DAYS"),
                         "вторая копия такта у прибора разошлась бы с копией писателя молча")


# ───────── 4b. писатель артефакта ДОСТИЖИМ, а не только существует ────────────

class TheDeclaredProductIsNotAnOrphan(unittest.TestCase):
    """Порванное звено, НАЙДЕННОЕ СТОРОЖЕМ в первой редакции ADR-843 до доставки.

    Писателя артефакта `_orphan_producer` ищет среди ТОЧЕК ВХОДА агентов и кода,
    импортированного не-тестовым кодом. Первая редакция писала отчёт внутри
    `scripts/worker_axis_census.py` — скрипта, которого зовут подпроцессом по константе
    пути, то есть невидимо для сторожа; вердикт был `ORPHAN`: «объявленный продукт,
    который никто не вычисляет». Писателем стала СТУПЕНЬ (мост — программа агента
    `com.spa.decision_loop`), и это звено здесь проверяется, а не предполагается.
    """

    def test_the_artifact_is_reachable_on_the_real_repo(self):
        from spa_core.tests import _orphan_producer as op
        rows = [r for r in op.measure(_REPO)["rows"] if r["path"] == ARTIFACT]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["verdict"], op.REACHABLE,
                         f"сторож достижимости о нашем артефакте говорит {rows[0]}")
        self.assertIn("spa_core.monitoring.findings_bridge", rows[0]["writers"])

    def test_the_instrument_itself_writes_nothing(self):
        """Прибор объявлен ЧИТАЮЩИМ, и это проверяется кодом, а не его шапкой."""
        from spa_core.monitoring.artifact_io_scan import WRITE, scan_file
        scanned = scan_file(_REPO / PRODUCER_REL)
        writes = [a for a, kinds in scanned.items() if WRITE in kinds]
        self.assertEqual(writes, [], f"прибор пишет файлы: {writes}")


# ─────────────── 5. третий исход прибора документом НЕ становится ─────────────

class TheThirdOutcomeNeverBecomesADocument(unittest.TestCase):
    """Порванное звено: документ при неответившем `ps` нёс бы выдуманный вердикт."""

    def test_an_unanswering_instrument_raises_instead_of_answering(self):
        class _Blind:
            PsUnavailable = wrap.PsUnavailable

            class Snapshot:
                @staticmethod
                def take():
                    raise _Blind.PsUnavailable("ps не ответил")

            @staticmethod
            def argv_rows():
                return {}

        with self.assertRaises(wac.NotMeasured):
            wac.run(root=_REPO, now=NOW, wrapper=_Blind)


# ─────────────── 6. конституция: производитель, SLO и запас ───────────────────

class TheConstitutionDeclaresTheArtifact(unittest.TestCase):
    """Порванное звено: артефакта в конституции не было — ни SLO, ни потребителя."""

    @classmethod
    def setUpClass(cls):
        doc = json.loads((_REPO / "architecture" / "manifest.json").read_text(
            encoding="utf-8"))
        cls.rows = [a for a in doc["artifacts"] if a.get("path") == ARTIFACT]

    def test_it_is_declared_exactly_once(self):
        self.assertEqual(len(self.rows), 1,
                         "две записи об одном артефакте — это два разных SLO на одно "
                         "число, и какое из них главное, не скажет никто (ADR-257)")

    def test_the_producer_is_named_not_null(self):
        """`producer: null` краснит `test_office_subject_drift_producer_tick` строкой
        «такт НЕ ИЗМЕРИМ» — ровно то состояние, которое ADR-790 застал у соседа."""
        self.assertEqual(self.rows[0].get("producer"), "com.spa.decision_loop")
        self.assertIn("orchestrator_protocol", self.rows[0].get("consumers", []))

    def test_the_slo_has_margin_over_the_tact(self):
        """Порог, РАВНЫЙ такту, краснеет от дрожания прогона и перестаёт быть сигналом.

        Этот класс (`no_margin`) называет дефектом сама перепись порогов (ADR-646),
        и её вывод читает обязательный шаг 0-офис каждый цикл.
        """
        slo_h = float(self.rows[0]["slo_hours"])
        tact_h = fb.WORKER_AXIS_CENSUS_TACT_DAYS * 24.0
        self.assertGreater(slo_h, tact_h,
                           f"SLO {slo_h} ч не больше такта {tact_h} ч — запаса нет")


# ──────────────── 7. шаг 0-офис читает отчёт, а не открывает файл ─────────────

class TheOfficeStepReadsItNotJustOpensIt(unittest.TestCase):
    """Порванное звено: артефакт читался бы ВХОЛОСТУЮ — файл открыт, чисел ноль."""

    @classmethod
    def setUpClass(cls):
        cls.src = (_REPO / "scripts" / "consume_office_reports.py").read_text(
            encoding="utf-8")

    def test_the_schema_producer_and_branch_are_all_three_there(self):
        base = os.path.basename(ARTIFACT)
        self.assertIn(f'"{base}": (', self.src, "полей артефакта не объявлено — "
                      "сверка схемы промолчит о чужом файле")
        self.assertIn(f'"{base}":\n        "{PRODUCER_REL}"', self.src,
                      "производитель артефакта шагу 0-офис не назван")
        self.assertIn(f'elif name == "{base}":', self.src,
                      "поимённой ветки нет ⇒ артефакт читается ВХОЛОСТУЮ")

    def test_the_branch_delegates_rendering_to_the_producer(self):
        """Вторая копия правила отрисовки расходится с первой МОЛЧА (ADR-220)."""
        self.assertIn("from worker_axis_census import format_report", self.src)

    def test_every_declared_field_exists_in_a_real_document(self):
        """Схема, объявляющая поле, которого производитель не пишет, краснит сверку
        словами «СХЕМА РАЗОШЛАСЬ … читаем НЕ ТОТ файл» о здоровом контуре."""
        snap, argv = _scene({10: ("claude -p цикл", f"PATH=/bin {wrap.RUN_ID_VAR}={MARK}")})
        doc = wac.run(root=_REPO, now=NOW, wrapper=wrap, snap=snap, argv=argv)
        declared = self._declared_fields(os.path.basename(ARTIFACT))
        self.assertTrue(declared, "перечень полей не разобран — это НЕ «полей нет»")
        for field in declared:
            self.assertIn(field.split(".")[0], doc,
                          f"шаг 0-офис объявил поле {field!r}, которого в документе нет")

    def _declared_fields(self, base):
        tree = ast.parse(self.src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if (isinstance(k, ast.Constant) and k.value == base
                            and isinstance(v, ast.Tuple)):
                        return [e.value for e in v.elts if isinstance(e, ast.Constant)]
        return []

    def test_the_rendering_prints_absence_as_words_not_as_zero(self):
        """`None` в выводе читается глазом как «пусто, всё в порядке» — fail-OPEN."""
        lines = "\n".join(wac.format_report({"status": "CLEAN"}))
        self.assertIn("НЕ ИЗМЕРЕНО", lines)
        self.assertNotIn("None", lines)
        self.assertNotIn("0 %", lines, "отсутствие доли напечатано нулём — "
                         "«не измерено» стало неотличимо от «измерено и равно нулю»")

    def test_a_finding_is_marked_for_the_office_but_not_invented(self):
        found = wac.format_report({"status": "FINDING", "rows_total": 5,
                                   "findings": ["ось слепа"]})
        self.assertTrue(found[0].startswith("⚠️"))
        clean = wac.format_report({"status": "CLEAN", "rows_total": 5, "findings": []})
        self.assertFalse(clean[0].startswith("⚠️"))


if __name__ == "__main__":
    unittest.main()
