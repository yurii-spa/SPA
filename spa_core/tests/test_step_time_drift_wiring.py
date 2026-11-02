"""Проводка прибора подорожания шага: у числа есть ПРОИЗВОДИТЕЛЬ и ЧИТАТЕЛЬ.

Заказ **G891 п. 7** приказа владельца «Portfolio CIO», решение — ADR-896.

## Что измерялось ДО написания файла

`spa_core/monitoring/step_time_drift.py` написан 02.10 (хвост ADR-534, заказ
G87 п. 3 переоткрыт) и **не был позван НИ РАЗУ**. Это не впечатление: храповик
`spa_core/tests/test_unwired_guard_modules_ratchet.py` на чистой вершине
`origin/main` 7df4aae72 давал **1 failed, 9 passed** с ОДНИМ именем в жалобе —
`spa_core/monitoring/step_time_drift.py`. Правило храповика названо в его же
сообщении: «В KNOWN_UNWIRED НЕ добавлять — подключить или вывести карточкой».

Соль находки в том, что ВХОД у прибора был всё это время: контрольный прогон
(`.github/workflows/ci-control.yml`) выгружает потоковую запись КАЖДОГО из 12
шардов артефактом `ctl-shard-<N>` (член `stream.jsonl`, хранение 30 дней).
Ходить за ними было НЕКОМУ.

## Почему проверок несколько, а не одна

Проводка рвётся в четырёх разных местах, и каждое молчит по-своему — таблица
дословно та же, что у соседей (`test_list_identity_census_wiring`,
`test_ci_control_verdict_wiring`), потому что и места те же:

| Звено | Как молчит, если порвано |
|---|---|
| вызов в `findings_bridge.main` | артефакт не обновляется никогда; SLO скажет часами позже и чужим голосом |
| запись в `artifacts[]` конституции | шаг 0-офис файл не открывает вовсе — числа нет в контексте |
| запись в `produces[]` паспорта | агент утверждает, что этого продукта не производит; SLO не назначен |
| именная ветка отрисовки | файл открыт, прочитано НОЛЬ строк, квитанция не пишется («вхолостую») |

Пятое звено у этой работы своё и к проводке не относится: **у прибора были
перепутаны исходы кода возврата**, и подключение это вскрыло (класс инв. #17).

У каждой проверки здесь есть обратная сторона: порванное звено краснеет, целое
проходит. Проверка, никогда не видевшая поломки, — украшение
(`.claude/rules/deployment.md`).

Часы и двери к сети ИНЪЕКТИРОВАНЫ, литеральных дат нет вовсе, живое `data/` не
читается и не пишется: все стенды одноразовые, поэтому вердикт не зависит ни от
календаря хоста, ни от того, что сегодня у GitHub.
"""
from __future__ import annotations

import ast
import datetime as dt
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile

_ROOT = pathlib.Path(__file__).resolve().parents[2]
for _p in (str(_ROOT), str(_ROOT / "scripts")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from spa_core.monitoring import findings_bridge as FB            # noqa: E402
from spa_core.monitoring import step_time_drift as D             # noqa: E402

import step_time_drift_run as P                                  # noqa: E402

ARTIFACT = "data/step_time_drift.json"
PRODUCER = "scripts/step_time_drift_run.py"
MODULE = "spa_core/monitoring/step_time_drift.py"
AGENT = "com.spa.decision_loop"

#: Часы ЗАДАЁТСЯ входом, а не берётся у хоста, и якорь — ЧИСЛО, не дата: литерал
#: вида `2026-..-..` завёл бы файл в класс замороженных дат ни за что (тот же
#: приём, что в `test_step_time_drift.py`).
T0 = 1_000_000.0
NOW = dt.datetime.fromtimestamp(T0 + 10_000.0, tz=dt.timezone.utc)

#: 200 файлов по 2 с: довольно, чтобы квартили имели смысл (порог прибора 100).
PER_FILE = {"spa_core/tests/f%03d.py" % i: 2.0 + i * 0.01 for i in range(200)}


def stream_text(per_file, *, ended=True, cases_per_file=2, sessions=1) -> str:
    """Потоковая запись одной сессии (или нескольких — для ДОИГРЫВАНИЯ)."""
    lines = []
    t = T0
    for _ in range(sessions):
        lines.append(json.dumps({"e": "session", "t": t, "iso": "scene", "pid": 1,
                                 "args": ["spa_core/tests/"]}, sort_keys=True))
        t += 1.0
        for fname, total in sorted(per_file.items()):
            each = total / cases_per_file
            for i in range(cases_per_file):
                nid = "%s::t%d" % (fname, i)
                lines.append(json.dumps({"e": "start", "n": nid, "t": t}, sort_keys=True))
                t += each
                lines.append(json.dumps({"e": "ok", "n": nid, "t": t, "d": each / 2},
                                        sort_keys=True))
        if ended:
            lines.append(json.dumps({"e": "end", "t": t, "status": 0,
                                     "started": 0, "finished": 0}, sort_keys=True))
    return "\n".join(lines) + "\n"


def zip_bytes(member: str, text: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, text)
    return buf.getvalue()


class FakeHub:
    """Одноразовый GitHub: отдаёт РОВНО то, что сцена объявила, и ничего больше.

    Двери те же, что у живого прибора (`fetch` — JSON API, `grab` — байты), и
    вопрос к ним — тот же; подменяется только то, что за ними отвечает. Запрос,
    которого сцена не предусмотрела, поднимает `AssertionError`: молчаливый
    пустой ответ сделал бы «прибор не спросил» неотличимым от «ответа нет».
    """

    def __init__(self, runs, parts, *, matrix_runs=(), matrix_parts=None):
        self.runs = list(runs)                  # [(id, {label: text|None})]
        self.parts = parts                      # {run_id: {label: text|None}}
        self.matrix_runs = list(matrix_runs)
        self.matrix_parts = matrix_parts or {}
        self.asked = []
        self.grabbed = []

    def fetch(self, path):
        self.asked.append(path)
        if "workflows/ci-control.yml/runs" in path:
            return {"workflow_runs": [
                {"id": rid, "status": "completed", "conclusion": "failure",
                 "head_sha": "sha%s" % rid, "created_at": "момент-%s" % rid,
                 "event": "schedule"} for rid in self.runs]}
        if "workflows/test.yml/runs" in path:
            return {"workflow_runs": [
                {"id": rid, "status": "completed", "conclusion": "failure",
                 "head_sha": "sha%s" % rid, "created_at": "момент-%s" % rid,
                 "event": "schedule"} for rid in self.matrix_runs]}
        if "/artifacts" in path:
            rid = int(path.split("/runs/")[1].split("/")[0])
            rows = []
            for label in sorted((self.parts.get(rid) or {})
                                | (self.matrix_parts.get(rid) or {})):
                rows.append({"name": label, "expired": False, "id": "%s-%s" % (rid, label),
                             "archive_download_url": "zip://%s/%s" % (rid, label)})
            return {"artifacts": rows}
        raise AssertionError("сцена не предусмотрела запрос %r" % path)

    def grab(self, url):
        self.grabbed.append(url)
        rid, label = url[len("zip://"):].split("/", 1)
        rid = int(rid)
        store = self.parts.get(rid) or {}
        member = P.SHARD_MEMBER
        if label not in store:
            store = self.matrix_parts.get(rid) or {}
            member = P.MATRIX_MEMBER
        text = store[label]
        if text is None:
            raise OSError("артефакт %s не отдан хранилищем" % label)
        return zip_bytes(member, text)


def shards(per_file, *, parts=12, **kw):
    """Двенадцать частей, РАЗНЫЕ файлы в каждой — как режет план по файлу."""
    names = sorted(per_file)
    out = {}
    for i in range(parts):
        mine = {n: per_file[n] for j, n in enumerate(names) if j % parts == i}
        out["ctl-shard-%d" % i] = stream_text(mine, **kw) if mine else stream_text(
            {names[0]: per_file[names[0]]}, **kw)
    return out


def hub_of_pair(base_per_file, later_per_file, **kw):
    return FakeHub(runs=[2000, 1000],
                   parts={2000: shards(later_per_file, **kw),
                          1000: shards(base_per_file)})


# ───────────── звено 1: вызов в `findings_bridge.main` ─────────────

def _calls_in_main(source: str) -> set:
    """Имена, которые ЗОВЁТ `main()` моста. Разбор AST, а не поиск подстроки.

    Подстрока нашлась бы и в комментарии — ровно тот класс, на котором сторож
    сирот сам себя ослеплял чужой прозой (`_code_only`, 30.08).
    """
    tree = ast.parse(source)
    main = next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")
    return {n.func.id for n in ast.walk(main)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}


class TheStageIsCalledByTheBridge(unittest.TestCase):

    def setUp(self):
        self.source = (_ROOT / "spa_core/monitoring/findings_bridge.py").read_text(
            encoding="utf-8")

    def test_main_calls_the_stage(self):
        self.assertIn("step_time_drift_step", _calls_in_main(self.source),
                      "ступень не зовётся из main() — артефакт не обновится НИКОГДА")

    def test_main_prints_the_line_a_human_reads(self):
        self.assertIn("step_time_drift_line", _calls_in_main(self.source),
                      "строки ступени в логе нет — молчание неотличимо от успеха")

    def test_the_measure_reddens_when_the_call_is_removed(self):
        """Обратная сторона: мера обязана УВИДЕТЬ порванное звено.

        Без этого плеча обе проверки выше были бы зелены и на мёртвой мере
        (урок #144): «ничего не нашли» читалось бы как «всё на месте».
        """
        torn = self.source.replace(
            "print(step_time_drift_line(step_time_drift_step(args.root)))",
            "pass  # звено порвано сценой")
        self.assertNotEqual(torn, self.source, "сцена не нашла строку вызова")
        self.assertNotIn("step_time_drift_step", _calls_in_main(torn))

    def test_the_stage_is_in_the_declared_roster(self):
        """Состав ступени ОБЪЯВЛЕН, и объявление сверяется с телом main()."""
        self.assertIn("step_time_drift", FB.CENSUS_STAGE)
        self.assertEqual(FB.CENSUS_PRODUCT["step_time_drift"],
                         {"module": PRODUCER, "artifact": ARTIFACT})

    def test_the_paths_are_one_object_not_two_literals(self):
        self.assertEqual(FB.STEP_TIME_DRIFT_ARTIFACT, ARTIFACT)
        self.assertEqual(FB.STEP_TIME_DRIFT_PRODUCER, PRODUCER)
        self.assertTrue((_ROOT / PRODUCER).is_file(), "производителя нет на диске")
        self.assertTrue((_ROOT / MODULE).is_file(), "прибора нет на диске")


# ───────────── звено 2 и 3: конституция и паспорт ─────────────

class TheArtifactIsDeclaredInTheConstitution(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads(
            (_ROOT / "architecture/manifest.json").read_text(encoding="utf-8"))

    def row(self):
        rows = [a for a in self.manifest["artifacts"] if a.get("path") == ARTIFACT]
        self.assertEqual(len(rows), 1, "артефакт объявлен не один раз — или ни разу")
        return rows[0]

    def test_it_is_active_and_has_a_producer(self):
        row = self.row()
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["producer"], AGENT)
        self.assertIn("orchestrator_protocol", row["consumers"],
                      "потребителя нет — артефакт объявлен и не нужен никому")

    def test_the_slo_has_margin_above_the_tact(self):
        """SLO, равный такту, краснеет от дрожания запуска (класс `no_margin`)."""
        slo = float(self.row()["slo_hours"])
        tact_h = FB.STEP_TIME_DRIFT_TACT_DAYS * 24.0
        self.assertGreater(slo, tact_h,
                           "SLO не больше такта: артефакт объявят протухшим в ту "
                           "минуту, когда ему только предстоит перемериться")

    def test_the_passport_admits_it_produces_this(self):
        agent = next(a for a in self.manifest["agents"] if a.get("label") == AGENT)
        mine = [p for p in agent["produces"] if p.get("artifact") == ARTIFACT]
        self.assertEqual(len(mine), 1, "паспорт агента этого продукта не признаёт")
        self.assertEqual(float(mine[0]["slo_hours"]),
                         float(self.row()["slo_hours"]),
                         "два объявления SLO разошлись — одно из них неверно")


# ───────────── звено 4: именная ветка шага 0-офис ─────────────

class TheOfficeRendersItRatherThanOpeningItHollow(unittest.TestCase):

    def doc(self):
        """Документ сцены — ЛИТЕРАЛ, и `**kw` у него нет намеренно.

        Площадку двери читает статикой сторож зазора фикстур, и `base.update(kw)`
        он честно объявляет немоделируемой мутацией (`value_unresolved`): какой
        путь после неё есть у документа, из текста НЕ ВИДНО. Потолок того ведра
        тоже исчерпан, поэтому сцена-вариант мутирует документ ПРИСВАИВАНИЕМ ПО
        КЛЮЧУ — эту форму разбор видит. Замерено на этой самой площадке #1009.
        """
        return {
            "schema": P.SCHEMA, "generated_at": NOW.isoformat(), "status": "measured",
            "verdict": "measured", "kind": "work_changed", "applied": False,
            "invoked_by": {"measured": True, "entry": PRODUCER, "doors_agree": True},
            "base": {"run": "1000", "sha": "aaa", "created_at": "раньше", "parts": 12,
                     "parts_read": 12, "parts_unread": [], "cases": 10, "ended": True},
            "later": {"run": "2000", "sha": "bbb", "created_at": "позже", "parts": 12,
                      "parts_read": 12, "parts_unread": [], "cases": 11, "ended": True},
            "control": {"ratio": None, "reason": "матрицы нет"},
            "drift": {"verdict": "measured", "comparable_files": 646,
                      "median_ratio": 1.234, "q1_ratio": 1.1, "q3_ratio": 1.3,
                      "iqr": 0.4, "share_slower": 0.6, "cases_base": 10,
                      "cases_later": 11, "case_growth": 0.1, "span_base_s": 60.0,
                      "span_later_s": 90.0, "base_ended": True, "later_ended": True,
                      "span_is_wall": False, "parts_base": 12, "parts_later": 12,
                      "parts_read_base": 12, "parts_read_later": 12,
                      "parts_unread_base": [], "parts_unread_later": [],
                      "sessions_base": 12, "sessions_later": 12,
                      "resumed_base": False, "resumed_later": False,
                      "files_in_two_parts": [], "fastest": [], "slowest": []},
            "findings": [], "reason": "",
        }

    def test_the_office_prints_the_number_instead_of_reading_it_hollow(self):
        import consume_office_reports as OFF
        # Имя артефакта — ЛИТЕРАЛ, а не `os.path.join`: площадку двери читает
        # статикой сторож зазора фикстур (`_fixture_schema_gap`), и собранное
        # вызовом имя он честно кладёт в НЕ ИЗМЕРЕНО. Запас того потолка
        # ИСЧЕРПАН (10 из 10), поэтому неразрешимое имя краснит набор сразу —
        # замерено на этой самой площадке циклом #1009.
        lines = OFF._summarize_json(ARTIFACT, self.doc(), now=NOW, root=str(_ROOT))
        text = "\n".join(lines)
        self.assertNotIn("РАЗОБРАТЬ НЕЧЕМ", text, "артефакт читается ВХОЛОСТУЮ")
        self.assertIn("1.234", text, "медианы в контексте оркестратора нет")
        self.assertIn("work_changed", text)

    def test_an_unmeasured_document_is_not_printed_as_a_verdict(self):
        import consume_office_reports as OFF
        doc = self.doc()
        doc["status"] = "unmeasured"
        doc["verdict"] = "unmeasured:no_pair_of_runs"
        doc["reason"] = "пары прогонов нет"
        lines = OFF._summarize_json(ARTIFACT, doc, now=NOW, root=str(_ROOT))
        text = "\n".join(lines)
        self.assertIn("НЕ ИЗМЕРЕНО", text)
        self.assertNotIn("1.234", text, "числа нет, а напечатано — это вердикт из ничего")

    def test_the_three_office_registries_name_it(self):
        import consume_office_reports as OFF
        self.assertIn("step_time_drift.json", OFF._READ_SCHEMA,
                      "формы чтения нет — поля никто не обязан прочесть")
        self.assertIn("step_time_drift.json", OFF._PRODUCER,
                      "производитель не объявлен — сверить схему нечем")

    def test_the_rendering_rule_lives_with_the_producer_not_here(self):
        """Вторая копия правила отрисовки разошлась бы с первой молча (ADR-220)."""
        office = (_ROOT / "scripts/consume_office_reports.py").read_text(encoding="utf-8")
        self.assertIn("from step_time_drift_run import format_report", office)


# ───────────── ступень: зов, срок, запись, третий исход ─────────────

class _Cp:
    def __init__(self, code, out="", err=""):
        self.returncode, self.stdout, self.stderr = code, out, err


class TheStageWritesOnlyWhatWasMeasured(unittest.TestCase):

    def doc_json(self, findings=()):
        return json.dumps({"schema": P.SCHEMA, "generated_at": NOW.isoformat(),
                           "status": "measured", "verdict": "measured",
                           "kind": "work_changed", "findings": list(findings)})

    def test_code_zero_is_ok_and_the_report_is_written(self):
        with tempfile.TemporaryDirectory() as td:
            self.setup_tree(td)
            seen = []
            out = FB.step_time_drift_step(
                td, runner=lambda *a, **k: _Cp(0, self.doc_json()),
                writer=lambda doc, target: seen.append((doc, target)), now=NOW)
            self.assertEqual(out["status"], "ok")
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0][1], os.path.join(td, ARTIFACT))

    def test_code_one_is_a_finding_and_still_written(self):
        with tempfile.TemporaryDirectory() as td:
            self.setup_tree(td)
            seen = []
            out = FB.step_time_drift_step(
                td, runner=lambda *a, **k: _Cp(1, self.doc_json(["шаг подорожал"])),
                writer=lambda doc, target: seen.append(doc), now=NOW)
            self.assertEqual(out["status"], "finding")
            self.assertEqual(out["findings"], 1)
            self.assertEqual(len(seen), 1)

    def test_code_two_is_unmeasured_and_NOTHING_is_written(self):
        """Артефакт с выдуманным числом лгал бы ещё и своим возрастом."""
        with tempfile.TemporaryDirectory() as td:
            self.setup_tree(td)
            seen = []
            out = FB.step_time_drift_step(
                td, runner=lambda *a, **k: _Cp(2, "", "токена нет"),
                writer=lambda doc, target: seen.append(doc), now=NOW)
            self.assertEqual(out["status"], "unmeasured")
            self.assertIn("токена нет", out["reason"])
            self.assertEqual(seen, [], "НЕ ИЗМЕРЕНО записано файлом")

    def test_a_timeout_is_unmeasured_not_a_zero(self):
        with tempfile.TemporaryDirectory() as td:
            self.setup_tree(td)

            def boom(*a, **k):
                raise subprocess.TimeoutExpired(cmd="x", timeout=1)

            out = FB.step_time_drift_step(td, runner=boom, writer=lambda *a: None,
                                          now=NOW)
            self.assertEqual(out["status"], "unmeasured")
            self.assertIn("сроку", out["reason"])

    def test_an_absent_producer_is_unmeasured_not_green(self):
        with tempfile.TemporaryDirectory() as td:
            out = FB.step_time_drift_step(td, runner=lambda *a, **k: _Cp(0),
                                          writer=lambda *a: None, now=NOW)
            self.assertEqual(out["status"], "unmeasured")
            self.assertIn("прибора нет на диске", out["reason"])

    def test_inside_the_tact_the_subprocess_is_not_raised_at_all(self):
        """Срок решает ФАЙЛ: внутри такта в сеть не идёт никто."""
        with tempfile.TemporaryDirectory() as td:
            self.setup_tree(td)
            target = pathlib.Path(td) / ARTIFACT
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(json.dumps({"generated_at": NOW.isoformat()}),
                              encoding="utf-8")
            calls = []
            out = FB.step_time_drift_step(
                td, runner=lambda *a, **k: calls.append(a) or _Cp(0, self.doc_json()),
                writer=lambda *a: None, now=NOW)
            self.assertEqual(out["status"], "within_tact")
            self.assertEqual(calls, [], "внутри такта прибор всё равно позвали")

    def test_a_document_without_a_verdict_is_not_read_as_green(self):
        with tempfile.TemporaryDirectory() as td:
            self.setup_tree(td)
            seen = []
            out = FB.step_time_drift_step(
                td, runner=lambda *a, **k: _Cp(0, json.dumps({"findings": []})),
                writer=lambda doc, target: seen.append(doc), now=NOW)
            self.assertEqual(out["status"], "unmeasured")
            self.assertEqual(seen, [])

    def setup_tree(self, td):
        """Одноразовое дерево: только то, что ступень обязана найти."""
        producer = pathlib.Path(td) / PRODUCER
        producer.parent.mkdir(parents=True, exist_ok=True)
        producer.write_text("# заглушка производителя\n", encoding="utf-8")


# ───────────── пятое звено: исходы кода возврата не путаются ─────────────

class TheThirdOutcomeIsNotAFinding(unittest.TestCase):
    """Подключение вскрыло у прибора подмену: «не измерено» шло за находку.

    Прежняя строка: `return 1 if result["kind"] != "within_runner_spread" else 0`.
    Род `unmeasured:no_same_commit_control` ей не равен, поэтому отсутствие
    контроля объявлялось НАХОДКОЙ — ровно то, что запрещает инв. #17.
    """

    MEASURED = {"verdict": "measured", "median_ratio": 1.4, "iqr": 0.1,
                "share_slower": 0.99}

    def test_a_kind_that_is_unmeasured_exits_two(self):
        code = D.exit_code({**self.MEASURED,
                            "kind": "unmeasured:no_same_commit_control"})
        self.assertEqual(code, D.CODE_UNMEASURED)

    def test_the_old_rule_would_have_called_it_a_finding(self):
        """Контроль самой подмены: прежнее правило на той же сцене даёт 1."""
        kind = "unmeasured:no_same_commit_control"
        self.assertEqual(1 if kind != "within_runner_spread" else 0, D.CODE_FINDING)
        self.assertNotEqual(D.exit_code({**self.MEASURED, "kind": kind}),
                            D.CODE_FINDING)

    def test_environment_beyond_the_spread_is_still_a_finding(self):
        self.assertEqual(
            D.exit_code({**self.MEASURED, "kind": "environment_beyond_runner_spread"}),
            D.CODE_FINDING)

    def test_within_the_spread_is_not_a_finding(self):
        self.assertEqual(
            D.exit_code({**self.MEASURED, "kind": "within_runner_spread"}), D.CODE_OK)

    def test_a_cheaper_step_is_not_a_finding_even_when_work_changed(self):
        """Находка — ПОДОРОЖАНИЕ. Шаг, ставший дешевле, находкой не является."""
        self.assertEqual(
            D.exit_code({**self.MEASURED, "median_ratio": 0.9, "kind": "work_changed"}),
            D.CODE_OK)

    def test_an_unmeasured_verdict_exits_two(self):
        self.assertEqual(D.exit_code({"verdict": "unmeasured:later_record_absent"}),
                         D.CODE_UNMEASURED)


# ───────────── производитель: вход добывается, а исходы различимы ─────────────

class TheProducerAssemblesACompositeRun(unittest.TestCase):

    def test_a_pair_of_sharded_runs_is_measured(self):
        hub = hub_of_pair(PER_FILE, {f: v * 1.4 for f, v in PER_FILE.items()})
        doc = P.measure(fetch=hub.fetch, grab=hub.grab, now=NOW, tree_root=_ROOT)
        self.assertEqual(doc["status"], "measured", doc.get("reason"))
        self.assertEqual(doc["base"]["parts_read"], 12)
        self.assertEqual(doc["later"]["parts_read"], 12)
        self.assertGreaterEqual(doc["drift"]["comparable_files"], D.MIN_COMPARABLE_FILES)
        self.assertAlmostEqual(doc["drift"]["median_ratio"], 1.4, places=2)
        self.assertEqual(len(hub.grabbed), 24, "запись каждой части обязана быть взята")

    def test_the_span_of_a_composite_run_is_not_called_a_wall(self):
        hub = hub_of_pair(PER_FILE, PER_FILE)
        doc = P.measure(fetch=hub.fetch, grab=hub.grab, now=NOW, tree_root=_ROOT)
        self.assertFalse(doc["drift"]["span_is_wall"])
        text = "\n".join(P.format_report(doc))
        self.assertIn("НЕ стена", text, "сумма размахов 12 частей названа стеной")

    def test_an_unreadable_part_is_named_and_becomes_a_finding(self):
        """Молча пропавшая часть уменьшает сопоставимые файлы БЕЗ СЛЕДА."""
        parts = shards(PER_FILE)
        parts["ctl-shard-7"] = None                      # хранилище не отдало
        hub = FakeHub(runs=[2000, 1000],
                      parts={2000: parts, 1000: shards(PER_FILE)})
        doc = P.measure(fetch=hub.fetch, grab=hub.grab, now=NOW, tree_root=_ROOT)
        self.assertEqual(doc["status"], "measured")
        self.assertEqual(doc["later"]["parts_read"], 11)
        self.assertEqual(len(doc["later"]["parts_unread"]), 1)
        self.assertTrue(any("НЕ ПРОЧИТАНО" in f for f in doc["findings"]), doc["findings"])

    def test_a_file_arriving_from_two_parts_is_named_not_summed_silently(self):
        parts = shards(PER_FILE)
        doubled = sorted(PER_FILE)[0]
        parts["ctl-shard-5"] = stream_text({doubled: PER_FILE[doubled]})
        hub = FakeHub(runs=[2000, 1000],
                      parts={2000: parts, 1000: shards(PER_FILE)})
        doc = P.measure(fetch=hub.fetch, grab=hub.grab, now=NOW, tree_root=_ROOT)
        self.assertIn(doubled, doc["drift"]["files_in_two_parts"])
        self.assertTrue(any("ДВУХ частей" in f for f in doc["findings"]), doc["findings"])

    def test_a_resumed_shard_is_named_because_cases_then_exceed_the_work(self):
        hub = FakeHub(runs=[2000, 1000],
                      parts={2000: shards(PER_FILE),
                             1000: shards(PER_FILE, sessions=2)})
        doc = P.measure(fetch=hub.fetch, grab=hub.grab, now=NOW, tree_root=_ROOT)
        self.assertTrue(doc["drift"]["resumed_base"])
        self.assertGreater(doc["drift"]["sessions_base"], doc["drift"]["parts_read_base"])
        self.assertTrue(any("ДОИГРЫВАЛСЯ" in f for f in doc["findings"]), doc["findings"])

    def test_one_run_only_is_unmeasured_with_a_named_reason(self):
        hub = FakeHub(runs=[2000], parts={2000: shards(PER_FILE)})
        doc = P.measure(fetch=hub.fetch, grab=hub.grab, now=NOW, tree_root=_ROOT)
        self.assertEqual(doc["status"], "unmeasured")
        self.assertEqual(doc["verdict"], "unmeasured:no_pair_of_runs")
        self.assertIn("из нужных 2", doc["reason"])
        self.assertEqual(doc["findings"], [])

    def test_a_run_without_parts_is_skipped_by_name_not_silently(self):
        hub = FakeHub(runs=[3000, 2000, 1000],
                      parts={3000: {}, 2000: shards(PER_FILE),
                             1000: shards(PER_FILE)})
        doc = P.measure(fetch=hub.fetch, grab=hub.grab, now=NOW, tree_root=_ROOT)
        self.assertEqual(doc["status"], "measured")
        self.assertEqual(doc["later"]["run"], "2000")
        self.assertEqual(doc["base"]["run"], "1000")

    def test_a_dead_api_is_unmeasured_and_not_an_empty_answer(self):
        class Dead:
            def fetch(self, path):
                raise OSError("сеть закрыта сценой")

            def grab(self, url):
                raise AssertionError("до байтов дойти не должно")

        dead = Dead()
        doc = P.measure(fetch=dead.fetch, grab=dead.grab, now=NOW, tree_root=_ROOT)
        self.assertEqual(doc["verdict"], "unmeasured:runs_not_listed")
        self.assertIn("сеть закрыта сценой", doc["reason"])

    def test_the_absent_control_is_a_named_third_outcome_not_a_substituted_one(self):
        hub = hub_of_pair(PER_FILE, {f: v * 1.09 for f, v in PER_FILE.items()})
        doc = P.measure(fetch=hub.fetch, grab=hub.grab, now=NOW, tree_root=_ROOT)
        self.assertIsNone(doc["control"]["ratio"])
        self.assertIn("нет ни одного завершённого прогона", doc["control"]["reason"])
        self.assertEqual(doc["kind"], "unmeasured:no_same_commit_control")
        self.assertEqual(doc["findings"], [],
                         "отсутствие контроля объявлено находкой — та самая подмена")

    def test_a_live_matrix_gives_the_control_and_the_kind_becomes_decidable(self):
        """Обратное плечо: контроль ЕСТЬ ⇒ род решается, и это другой ответ."""
        hub = hub_of_pair(PER_FILE, {f: v * 1.09 for f, v in PER_FILE.items()})
        hub.matrix_runs = [900]
        hub.matrix_parts = {900: {
            "test-records-3.11-1": stream_text(PER_FILE),
            "test-records-3.12-1": stream_text({f: v * 1.2 for f, v in PER_FILE.items()}),
        }}
        doc = P.measure(fetch=hub.fetch, grab=hub.grab, now=NOW, tree_root=_ROOT)
        self.assertIsNotNone(doc["control"]["ratio"])
        self.assertEqual(doc["kind"], "within_runner_spread")
        self.assertEqual(doc["findings"], [])


# ───────────── и, наконец, храповик сирот обязан СМОЛЧАТЬ про него ─────────────

class TheOrphanCensusNoLongerNamesIt(unittest.TestCase):
    """Поведенческое плечо НА ЖИВОМ ДЕРЕВЕ: вердикт меряется, а не заявляется.

    Контроль деталей выше зелен и на мёртвой проводке (урок #144). Здесь
    спрашивается НАСТОЯЩАЯ перепись того самого храповика, который был красным.
    """

    def test_the_module_is_not_in_the_unwired_census(self):
        from spa_core.tests import test_unwired_guard_modules_ratchet as R
        census = R._census()
        self.assertNotIn(MODULE, census,
                         "прибор снова сирота — проводка порвана")
        self.assertNotIn(MODULE, R.KNOWN_UNWIRED,
                         "имя попало в базу храповика: база может только убывать")

    def test_the_census_still_sees_other_orphans_so_it_is_not_vacuous(self):
        """Иначе «его там нет» значило бы «сканер ничего не находит»."""
        from spa_core.tests import test_unwired_guard_modules_ratchet as R
        self.assertTrue(R._census(), "перепись пуста — сканер сузился")


if __name__ == "__main__":
    unittest.main()
