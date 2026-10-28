"""Проводка ЧИТАТЕЛЯ вердикта контрольного прогона CI (ADR-845, заказ G843 п. 2).

Предмет. С 16.10 приёмку полного набора даёт ТОЛЬКО контрольный прогон по шардам
(`ci-control.yml` + `scripts/ci_control.py`): у `SPA CI` на `main` вердикт недостижим по
построению — набору нужно ≈6 ч до сводки, медиана промежутка между пушами 0.72 ч, а
`cancel-in-progress` снимает прогон (ADR-844). Вердикт контрольного прогона живёт
АРТЕФАКТОМ GitHub (`ci-control-report`, 90 дней), в git не кладётся — и до 28.10 его не
спрашивал НИ ОДИН шаг цикла. Класс ADR-345, названный ADR-844 и им же не закрытый.

Второе и главное: **`conclusion` прогона вердиктом НЕ является.** Замер 28.10 по 20
последним завершённым прогонам на `main` (живой API):

* `conclusion` = `failure` у **20 из 20**;
* вердикт при этом **RED 17 · INCOMPLETE 3** — то есть «упавшие НАЗВАНЫ поимённо» и «не
  измерено ВОВСЕ» в списке прогонов неразличимы (инв. #17), и неразличимость встречается
  в 15 % прогонов;
* у **2 прогонов из 20** `head_sha` ≠ коммит, который прогон мерил (`inputs.sha`
  закрепляет джоба `manifest`): прогон 40164854726 числится на `546687543` и отвечает про
  `84ab03679`, `failed=2` против `failed=70` у расписанного прогона на самом `546687543`.

Каждый тест ниже — ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ одного порванного звена, и звено названо в его
docstring. Проверка, никогда не видевшая настоящей поломки, — украшение
(`.claude/rules/deployment.md`, § «Проверка сторожа сторожей»).

Ни сети, ни живой машины этот файл не спрашивает ни разу: и подпроцесс, и `fetch`, и
`grab`, и часы — ВХОДЫ. Единственный литеральный якорь времени — :data:`NOW`, и обе
стороны каждого сравнения возраста от него производны.

# FROZEN-DATE-OK: injected-clock — якорь `NOW` уезжает входом `now=NOW` в
# `ccv.run(...)` / `fb.ci_control_verdict_step(...)`, а отметки сцен считаются от него же
# (`NOW - timedelta`); обе стороны сравнения закреплены одним якорем, стенных часов нет.
"""
# LLM_FORBIDDEN
from __future__ import annotations

import ast
import importlib.util
import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.monitoring import findings_bridge as fb  # noqa: E402
from spa_core.tests._unwired import unwired_scripts  # noqa: E402

PRODUCER_REL = os.path.join("scripts", "ci_control_verdict.py")
ARTIFACT = "data/ci_control_verdict.json"
STAGE = "ci_control_verdict"

#: Момент замера — ВХОД сцены. Ни одна другая дата в файле не литерал.
NOW = datetime(2026, 10, 28, 12, 0, tzinfo=timezone.utc)


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, _REPO / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ccv = _load("_t965_ccv", PRODUCER_REL)


# ──────────────────────────── сцены: сеть ВХОДОМ ──────────────────────────────

def _run_row(rid="40640339909", *, status="completed", conclusion="failure",
             sha="01dcead102aa1fae9c0287e8c6cab788de0a88e6", ended_h=1.0,
             event="schedule"):
    return {"id": rid, "status": status, "conclusion": conclusion, "event": event,
            "head_sha": sha, "head_branch": "main",
            "created_at": (NOW - timedelta(hours=ended_h + 0.6)).isoformat(),
            "updated_at": (NOW - timedelta(hours=ended_h)).isoformat(),
            "html_url": f"https://github.com/yurii-spa/SPA/actions/runs/{rid}"}


def _report(verdict="GREEN", *, sha="01dcead102aa1fae9c0287e8c6cab788de0a88e6",
            failures=0, incomplete=(), shards=12):
    return {"schema": "spa-ci-control-report/1", "verdict": verdict, "sha": sha,
            "env": {"python": "3.11.17", "pytest": "9.1.1", "SPA_ENV": "ci",
                    "PYTHONHASHSEED": "0", "roots": ["tests"] * 6},
            "incomplete": list(incomplete),
            "failures": [{"nodeid": f"t{i}"} for i in range(failures)],
            "not_obtained": [], "shards": [{"shard": i} for i in range(shards)],
            "totals": {"population": 136806, "files": 2769, "passed": 136030,
                       "skipped": 719, "failed": failures, "error": 0,
                       "not_obtained": 0, "collect_errors": 0,
                       "shards_planned": shards, "shards_complete": shards}}


class _Net:
    """Сеть ВХОДОМ: обе двери (JSON и байты) отвечают сценой, а не живым GitHub.

    Без этого каждый тест ниже отвечал бы на вопрос «что сегодня у GitHub», а не «цела
    ли проводка» (`.claude/rules/deployment.md`, § про инъекцию).
    """

    def __init__(self, runs, artifacts=None, report=None, *, fetch_raises=None,
                 grab_raises=None, zip_bytes=None):
        self.runs = runs
        self.artifacts = artifacts if artifacts is not None else [
            {"id": 1, "name": "ci-control-report", "expired": False,
             "archive_download_url": "https://api.example/zip"}]
        self.report = report if report is not None else _report()
        self.fetch_raises, self.grab_raises = fetch_raises, grab_raises
        self.zip_bytes = zip_bytes
        self.asked = []

    def fetch(self, path):
        self.asked.append(path)
        if self.fetch_raises is not None:
            raise self.fetch_raises
        if "/artifacts" in path:
            return {"artifacts": self.artifacts}
        return {"workflow_runs": self.runs}

    def grab(self, url):
        self.asked.append(url)
        if self.grab_raises is not None:
            raise self.grab_raises
        if self.zip_bytes is not None:
            return self.zip_bytes
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("report.json", json.dumps(self.report))
        return buf.getvalue()

    def doc(self):
        return ccv.run(root=_REPO, now=NOW, fetch=self.fetch, grab=self.grab)


# ─────────────────────────── 1. храповик сирот ────────────────────────────────

class TheOrphanRatchetDoesNotNameTheProducer(unittest.TestCase):
    """Порванное звено: ЗОВА нет ни одного — прибор числится сиротой."""

    def test_the_real_repo_does_not_name_it(self):
        self.assertNotIn("ci_control_verdict", unwired_scripts(_REPO),
                         "прибор сирота: зова из ступени моста нет")

    def test_control_without_the_call_the_name_comes_back(self):
        """ОБРАТНАЯ половина: убери зов — и храповик обязан назвать прибор.

        Без этого контроля тест выше проходил бы и у сторожа, который не находит
        НИЧЕГО и НИКОГДА.
        """
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            (root / "scripts").mkdir()
            (root / "spa_core" / "monitoring").mkdir(parents=True)
            (root / "scripts" / "ci_control_verdict.py").write_text(
                'if __name__ == "__main__":\n    pass\n', encoding="utf-8")
            self.assertIn("ci_control_verdict", unwired_scripts(root),
                          "храповик не назвал сироту в дереве, где зова НЕТ — значит он "
                          "не умеет находить, и зелень выше ничего не стоит")


# ─────────────────────── 2. ступень объявлена и ЗОВЁТСЯ ───────────────────────

class TheStageIsDeclaredAndActuallyCalled(unittest.TestCase):
    """Порванное звено: «путь в файле проводкой не является» (урок ADR-835)."""

    def test_it_is_in_both_declarations(self):
        self.assertIn(STAGE, fb.CENSUS_STAGE,
                      "ступень не числится переписью: «пропущено» станет неотличимо "
                      "от «не бывало»")
        self.assertIn(STAGE, fb.CENSUS_PRODUCT,
                      "читатель, идущий по CENSUS_PRODUCT, артефакта не найдёт")

    def test_the_product_points_at_the_single_constant(self):
        """Второй литерал того же пути разошёлся бы с первым МОЛЧА (класс ADR-220)."""
        self.assertEqual(fb.CENSUS_PRODUCT[STAGE]["module"],
                         fb.CI_CONTROL_VERDICT_PRODUCER)
        self.assertEqual(fb.CENSUS_PRODUCT[STAGE]["artifact"], ARTIFACT)
        self.assertEqual(fb.CI_CONTROL_VERDICT_PRODUCER, PRODUCER_REL)

    def test_main_really_calls_the_stage(self):
        """Объявление — не зов. Спрашивается ТЕЛО `main()` разбором AST."""
        src = (_REPO / "spa_core" / "monitoring" / "findings_bridge.py").read_text(
            encoding="utf-8")
        main = next(n for n in ast.walk(ast.parse(src))
                    if isinstance(n, ast.FunctionDef) and n.name == "main")
        called = {n.func.id for n in ast.walk(main)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        self.assertIn("ci_control_verdict_step", called,
                      "ступень объявлена, но из тела main() не зовётся — "
                      "объявление зовом не является")


# ───────── 3. `conclusion` вердиктом НЕ является (предмет ADR-845) ────────────

class TheConclusionIsNotTheVerdict(unittest.TestCase):
    """Порванное звено: `failure` читался бы как «красный набор».

    Замер 28.10: `failure` стоял у 20 прогонов из 20, а INCOMPLETE («не измерено
    ВОВСЕ») был у трёх. Прибор обязан РАЗЛИЧАТЬ эти состояния, и обе сцены ниже
    отличаются ровно вердиктом в `report.json` при одном и том же `conclusion`.
    """

    def test_red_names_the_failures_and_the_commit(self):
        doc = _Net([_run_row()], report=_report("RED", failures=57)).doc()
        self.assertEqual(doc["verdict"], "RED")
        self.assertEqual(doc["failed"], 57)
        self.assertEqual(len(doc["findings"]), 1)
        self.assertIn("КРАСЕН", doc["findings"][0])
        self.assertIn("failed=57", doc["findings"][0])

    def test_incomplete_is_not_measured_at_all_and_says_so(self):
        doc = _Net([_run_row()], report=_report(
            "INCOMPLETE", shards=0,
            incomplete=[{"shard": None, "reason": "манифеста населения нет"}])).doc()
        self.assertEqual(doc["verdict"], "INCOMPLETE")
        found = " ".join(doc["findings"])
        self.assertIn("НЕ ВСЁ", found)
        self.assertIn("манифеста", found)
        self.assertIn("conclusion", found,
                      "находка не называет, что `conclusion` об этом молчит — "
                      "а именно в этом предмет ADR-845")

    def test_the_same_conclusion_gives_two_different_verdicts(self):
        """ОДИН `conclusion`, ДВА вердикта: без отчёта они неразличимы."""
        red = _Net([_run_row(conclusion="failure")],
                   report=_report("RED", failures=5)).doc()
        inc = _Net([_run_row(conclusion="failure")],
                   report=_report("INCOMPLETE", shards=0,
                                  incomplete=[{"reason": "шард 3 снят"}])).doc()
        self.assertEqual(red["run"]["conclusion"], inc["run"]["conclusion"])
        self.assertNotEqual(red["verdict"], inc["verdict"])
        self.assertNotEqual(red["findings"], inc["findings"])

    def test_green_is_clean_and_is_not_invented_from_an_empty_list(self):
        doc = _Net([_run_row(conclusion="success")], report=_report("GREEN")).doc()
        self.assertEqual(doc["status"], "CLEAN")
        self.assertEqual(doc["findings"], [])

    def test_an_unknown_verdict_is_a_finding_not_a_pass(self):
        """Вердикт, которого прибор не знает, — не «зелено»."""
        doc = _Net([_run_row()], report=_report("ЖЁЛТЫЙ")).doc()
        self.assertEqual(doc["status"], "FINDING")
        self.assertIn("не опознан", " ".join(doc["findings"]))


# ──────── 4. вердикт БЫВАЕТ про другой коммит (вторая половина замера) ────────

class TheVerdictMayBeAboutAnotherCommit(unittest.TestCase):
    """Порванное звено: `head_sha` из списка прогонов выдавался бы за измеренный.

    Замер 28.10: у 2 прогонов из 20 они расходятся, и разница не косметическая —
    `failed=2` против `failed=70` на одной и той же голове ветки.
    """

    def test_a_pinned_commit_is_named_as_a_finding(self):
        doc = _Net([_run_row(sha="546687543aaa")],
                   report=_report("RED", sha="84ab03679bbb", failures=2)).doc()
        self.assertEqual(doc["measured_sha"], "84ab03679bbb")
        self.assertEqual(doc["head_sha"], "546687543aaa")
        found = " ".join(doc["findings"])
        self.assertIn("546687543", found)
        self.assertIn("84ab03679", found)

    def test_matching_commits_add_no_finding(self):
        """Обратная половина: совпали — и находки быть не должно."""
        same = "01dcead102aa1fae9c0287e8c6cab788de0a88e6"
        doc = _Net([_run_row(sha=same)], report=_report("GREEN", sha=same)).doc()
        self.assertEqual(doc["findings"], [])


# ─────────── 5. возраст вердикта — отдельное наблюдение от возраста отчёта ────

class TheAgeOfTheVerdictIsItsOwnObservation(unittest.TestCase):
    """Порванное звено: свежий отчёт о позавчерашнем вердикте читался бы как свежий."""

    def test_a_fresh_verdict_is_not_a_finding(self):
        doc = _Net([_run_row(ended_h=3.4)], report=_report("GREEN")).doc()
        self.assertLess(doc["verdict_age_h"], ccv.STALE_AFTER_H)
        self.assertEqual(doc["findings"], [])

    def test_a_stale_verdict_is_a_finding_with_its_age(self):
        doc = _Net([_run_row(ended_h=30.0)], report=_report("GREEN")).doc()
        self.assertGreater(doc["verdict_age_h"], ccv.STALE_AFTER_H)
        self.assertIn("свежего вердикта нет", " ".join(doc["findings"]))

    def test_a_stale_verdict_with_a_run_in_flight_reads_differently(self):
        """«Стар и ничего не идёт» ≠ «стар, но новый уже идёт» — разные состояния."""
        idle = _Net([_run_row(ended_h=30.0)], report=_report("GREEN")).doc()
        busy = _Net([_run_row("111", status="in_progress", conclusion=None),
                     _run_row(ended_h=30.0)], report=_report("GREEN")).doc()
        self.assertIn("ни одного нового прогона не идёт", " ".join(idle["findings"]))
        self.assertIn("идущих прогонов: 1", " ".join(busy["findings"]))
        self.assertEqual(len(busy["in_progress"]), 1)

    def test_an_unparsable_end_moment_is_unmeasured_not_zero(self):
        """Возраст, который не сложился, — СЛОВА «НЕ ИЗМЕРЕН», а не ноль (инв. #17)."""
        row = _run_row()
        row["updated_at"] = "вчера"
        doc = _Net([row], report=_report("GREEN")).doc()
        self.assertIsNone(doc["verdict_age_h"])
        self.assertIn("НЕ ИЗМЕРЕН", " ".join(doc["findings"]))
        self.assertIn("НЕ ИЗМЕРЕН", "\n".join(ccv.report(doc)))

    def test_the_running_rows_do_not_claim_a_verdict(self):
        """У идущего прогона вердикта НЕ спрашивали — и это сказано словами."""
        doc = _Net([_run_row("111", status="in_progress", conclusion=None),
                    _run_row()], report=_report("GREEN")).doc()
        self.assertEqual(doc["in_progress"][0]["verdict"], "НЕ ЗАПРАШИВАЛСЯ")


# ────────── 6. третий исход прибора документом НЕ становится (инв. #17) ───────

class TheThirdOutcomeNeverBecomesAVerdict(unittest.TestCase):
    """Порванное звено: «вердикта нет» выдавалось бы за «вердикт зелёный»."""

    def _raises(self, net, needle):
        with self.assertRaises(ccv.NotMeasured) as box:
            net.doc()
        self.assertIn(needle, str(box.exception))

    def test_no_runs_at_all(self):
        self._raises(_Net([]), "не найдено")

    def test_every_run_still_going(self):
        self._raises(_Net([_run_row("1", status="in_progress", conclusion=None)]),
                     "ещё идут")

    def test_a_run_without_a_report_artifact(self):
        """Прогон умер раньше сводки ⇒ вердикта НЕТ, а `conclusion` об этом молчит."""
        self._raises(_Net([_run_row()], artifacts=[]), "раньше сводки")

    def test_an_expired_artifact_has_its_own_reason(self):
        """«Истёк» и «не бывало» — разные причины, и обе не «зелено»."""
        self._raises(_Net([_run_row()], artifacts=[
            {"id": 1, "name": "ci-control-report", "expired": True}]), "истёк")

    def test_a_broken_zip(self):
        self._raises(_Net([_run_row()], zip_bytes="не zip".encode("utf-8")), "не разобран")

    def test_a_report_without_a_verdict(self):
        doc = _report("GREEN")
        doc.pop("verdict")
        self._raises(_Net([_run_row()], report=doc), "вердикта не несёт")

    def test_a_dead_network(self):
        self._raises(_Net([], fetch_raises=OSError("сети нет")), "не прочитан")

    def test_a_dead_download(self):
        self._raises(_Net([_run_row()], grab_raises=OSError("оборвалось")), "не скачан")

    def test_an_absent_token_is_unmeasured_not_green(self):
        """Токена нет ⇒ вердикта нет. Это не «набор зелёный»."""
        def _no_token():
            raise RuntimeError("токена нет: ни GITHUB_TOKEN, ни Keychain")

        saved = ccv.github_fetch
        ccv.github_fetch = _no_token
        try:
            with self.assertRaises(ccv.NotMeasured) as box:
                ccv.run(root=_REPO, now=NOW, grab=lambda _u: b"")
            self.assertIn("токена нет", str(box.exception))
        finally:
            ccv.github_fetch = saved

    def test_the_cli_returns_two_for_an_unmeasured_verdict(self):
        """Третий исход обязан иметь СВОЙ код возврата, а не код успеха."""
        proc = subprocess.run(
            [sys.executable, str(_REPO / PRODUCER_REL), "--json", "--runs", "1"],
            capture_output=True, text=True,
            env={**os.environ, "GITHUB_TOKEN": "", "GITHUB_PAT_SPA": "",
                 "PATH": "/nonexistent"})
        self.assertEqual(proc.returncode, 2, proc.stdout + proc.stderr)
        self.assertIn("unmeasured", json.loads(proc.stdout.strip().splitlines()[-1]))


# ───── 7. дверь байтов: токен НЕ уезжает на переадресацию (авария 401) ────────

class TheRedirectDropsTheToken(unittest.TestCase):
    """Порванное звено, ЗАМЕРЕННОЕ 28.10 на живом API до написания прибора.

    `GET /actions/artifacts/<id>/zip` отвечает 302 на чужое blob-хранилище. `urllib`
    по умолчанию несёт `Authorization` и на новый адрес, хранилище отвечает **HTTP
    401**, и «вердикт недостижим» выглядело бы отказом доступа при верном токене.
    """

    def test_the_handler_builds_a_request_without_authorization(self):
        handler = ccv._StripAuthOnRedirect()
        req = handler.redirect_request(
            None, None, 302, "Found", {}, "https://blob.example/artifact.zip")
        self.assertIsNotNone(req)
        keys = {k.lower() for k in req.headers}
        self.assertNotIn("authorization", keys,
                         "токен уезжает в чужое хранилище — вернётся HTTP 401, "
                         "и он прочтётся как «вердикта нет»")

    def test_the_first_request_does_carry_the_token(self):
        """Обратная половина: ПЕРВЫЙ запрос токен нести обязан — иначе 401 ответит
        сам GitHub, и «вердикта нет» снова окажется отказом доступа.

        Спрашивается не индекс замыкания (он поехал бы от любой правки тела), а
        ЗАГОЛОВКИ, с которыми дверь идёт в сеть: сцена перехватывает `opener.open`.
        """
        seen = {}

        class _Opener:
            @staticmethod
            def open(req, timeout=None):
                seen["headers"] = dict(req.headers)

                class _R:
                    @staticmethod
                    def read():
                        return b""

                    def __enter__(self_inner):
                        return _R

                    def __exit__(self_inner, *a):
                        return False

                return _R()

        saved = ccv.urllib.request.build_opener
        ccv.urllib.request.build_opener = lambda *a, **k: _Opener()
        try:
            ccv.artifact_grab("ТОКЕН")("https://api.example/zip")
        finally:
            ccv.urllib.request.build_opener = saved
        lower = {k.lower(): v for k, v in seen.get("headers", {}).items()}
        self.assertIn("authorization", lower, "первый запрос идёт без токена")
        self.assertIn("ТОКЕН", lower["authorization"])

    def test_without_a_token_the_first_request_carries_no_header(self):
        """Третья половина того же: `None` не превращается в строку «Bearer None»."""
        grab_head = ccv.artifact_grab(None)
        seen = {}

        class _Opener:
            @staticmethod
            def open(req, timeout=None):
                seen["headers"] = dict(req.headers)
                raise OSError("дальше не идём — заголовки уже сняты")

        saved = ccv.urllib.request.build_opener
        ccv.urllib.request.build_opener = lambda *a, **k: _Opener()
        try:
            grab_head = ccv.artifact_grab(None)
            with self.assertRaises(OSError):
                grab_head("https://api.example/zip")
        finally:
            ccv.urllib.request.build_opener = saved
        lower = {k.lower() for k in seen.get("headers", {})}
        self.assertNotIn("authorization", lower)


# ─── 8. ключи итогов не выдуманы: их пишет `ci_control.aggregate` ─────────────

class TheTotalsKeysComeFromTheProducer(unittest.TestCase):
    """Порванное звено, пойманное живым прогоном В ЭТОМ ЖЕ цикле.

    Первая редакция прибора спрашивала у итогов ключ `no_outcome`, которого
    `ci_control.aggregate` не пишет ВОВСЕ, — и печатала о здоровом отчёте
    «no_outcome=НЕ ИЗМЕРЕНО». То есть сторож жаловался на свою же опечатку, и
    отличить это от настоящего «не измерено» читатель не мог.
    """

    @classmethod
    def setUpClass(cls):
        src = (_REPO / "scripts" / "ci_control.py").read_text(encoding="utf-8")
        cls.literals = {n.value for n in ast.walk(ast.parse(src))
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        doc = _Net([_run_row()], report=_report("GREEN")).doc()
        cls.keys = list(doc["totals"])

    def test_every_asked_key_is_written_by_ci_control(self):
        self.assertTrue(self.keys, "перечень итогов пуст — это НЕ «итогов нет»")
        for key in self.keys:
            self.assertIn(key, self.literals,
                          f"прибор спрашивает итог {key!r}, которого производитель "
                          f"отчёта не пишет: о здоровом отчёте он скажет «НЕ ИЗМЕРЕНО»")

    def test_control_the_check_can_catch_a_fabricated_key(self):
        """Обратная половина — настоящая опечатка этого цикла."""
        self.assertNotIn("no_outcome", self.literals,
                         "проверка выше ничего не стоит: выдуманный ключ она "
                         "признала бы написанным производителем")


# ──────────────────── 9. исходы СТУПЕНИ различимы ────────────────────────────

class _Save:
    """Дверь к ДИСКУ входом: тест проводки не пишет в живое `data/`."""

    def __init__(self):
        self.calls = []

    def __call__(self, doc, path):
        self.calls.append((doc, path))


class _Runner:
    """Дверь к подпроцессу ВХОДОМ: сети нет, судится проводка."""

    def __init__(self, code=0, out="", err="", raise_=None):
        self.code, self.out, self.err, self.raise_ = code, out, err, raise_
        self.cmd = None

    def __call__(self, cmd, **kw):
        self.cmd = cmd
        if self.raise_ is not None:
            raise self.raise_
        return subprocess.CompletedProcess(cmd, self.code, self.out, self.err)


_DOC = {"status": "CLEAN", "verdict": "GREEN", "findings": []}
_DOC_FINDING = {"status": "FINDING", "verdict": "RED", "findings": ["набор КРАСЕН"]}


def _due(tmp):
    """Дерево-сцена, где отчёта НЕТ ⇒ срок пришёл (первый замер)."""
    root = pathlib.Path(tmp)
    (root / "scripts").mkdir(parents=True, exist_ok=True)
    (root / "scripts" / "ci_control_verdict.py").write_text("", encoding="utf-8")
    return str(root)


class TheStageKeepsItsOutcomesApart(unittest.TestCase):
    """Порванное звено: «не измерено», выданное за «вердикт зелёный» (инв. #17)."""

    def test_code_zero_is_measured_clean_and_the_report_is_written(self):
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(
                _due(tmp), runner=_Runner(0, json.dumps(_DOC)), writer=save, now=NOW)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(out["verdict"], "GREEN")
        self.assertEqual(len(save.calls), 1, "отчёт не записан — читателю читать нечего")
        self.assertTrue(save.calls[0][1].endswith("data/ci_control_verdict.json"))

    def test_code_one_is_a_named_finding(self):
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(
                _due(tmp), runner=_Runner(1, json.dumps(_DOC_FINDING)), writer=save,
                now=NOW)
        self.assertEqual(out["status"], "finding")
        self.assertEqual(out["findings"], 1)
        self.assertIn("КРАСЕН", out["reason"])
        self.assertEqual(len(save.calls), 1)

    def test_code_two_is_unmeasured_and_writes_nothing(self):
        """Отчёт при неответившем приборе лгал бы ещё и своим ВОЗРАСТОМ."""
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(
                _due(tmp), runner=_Runner(2, "", "НЕ ИЗМЕРЕНО: токена нет"),
                writer=save, now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("токена", out["reason"])
        self.assertEqual(save.calls, [])

    def test_a_missing_code_is_unmeasured_too(self):
        class _NoCode:
            stdout = stderr = ""

        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(_due(tmp), runner=lambda *a, **k: _NoCode(),
                                             writer=save, now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertEqual(save.calls, [])

    def test_an_unparsed_document_is_unmeasured_not_clean(self):
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(_due(tmp), runner=_Runner(0, "не json"),
                                             writer=save, now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("не разобран", out["reason"])
        self.assertEqual(save.calls, [])

    def test_a_document_without_a_verdict_is_unmeasured(self):
        """Документ без вердикта прочёлся бы как «вердикт зелёный» — а это молчание."""
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(
                _due(tmp), runner=_Runner(0, json.dumps({"findings": []})),
                writer=save, now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertEqual(save.calls, [])

    def test_a_document_without_findings_key_is_unmeasured(self):
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(
                _due(tmp), runner=_Runner(0, json.dumps({"verdict": "GREEN"})),
                writer=save, now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertEqual(save.calls, [])

    def test_a_failed_write_is_unmeasured_not_a_verdict(self):
        def _boom(doc, path):
            raise OSError("диск только для чтения")

        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(
                _due(tmp), runner=_Runner(0, json.dumps(_DOC)), writer=_boom, now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("не записан", out["reason"])

    def test_timeout_is_unmeasured_with_its_own_reason(self):
        boom = subprocess.TimeoutExpired(cmd="x", timeout=1)
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(_due(tmp), runner=_Runner(raise_=boom),
                                             writer=_Save(), now=NOW)
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("сроку", out["reason"])

    def test_a_producer_absent_from_disk_is_unmeasured(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(tmp, runner=_Runner(0), writer=_Save())
        self.assertEqual(out["status"], "unmeasured")
        self.assertIn("нет на диске", out["reason"])

    def test_the_call_asks_for_a_document_not_a_file(self):
        """Прибор отдаёт документ на stdout; пишет ПОЗВАВШИЙ."""
        r = _Runner(0, json.dumps(_DOC))
        with tempfile.TemporaryDirectory() as tmp:
            fb.ci_control_verdict_step(_due(tmp), runner=r, writer=_Save(), now=NOW)
        self.assertIn("--json", r.cmd)
        self.assertNotIn("--write", r.cmd)
        self.assertIn(PRODUCER_REL, " ".join(r.cmd))

    def test_the_line_keeps_three_forms_for_three_outcomes(self):
        unm = fb.ci_control_verdict_line({"status": "unmeasured", "reason": "токена нет"})
        tact = fb.ci_control_verdict_line({"status": "within_tact",
                                           "reason": "0.1 дн из 0.25"})
        ok = fb.ci_control_verdict_line({"status": "ok", "code": 0, "findings": 0,
                                         "verdict": "GREEN", "reason": "находок нет"})
        self.assertIn("НЕ ИЗМЕРЕНО", unm)
        self.assertIn("такт не истёк", tact)
        self.assertNotIn("НЕ ИЗМЕРЕНО", tact,
                         "«не мерили по сроку» слито с «не измерено» — разные исходы")
        self.assertNotIn("НЕ ИЗМЕРЕНО", ok)
        self.assertNotIn("такт", ok)


# ──────────────── 10. такт решает ФАЙЛ, а не расписание бегуна ────────────────

class TheTactIsDecidedByTheFile(unittest.TestCase):
    """Порванное звено: зов в сеть каждый час — и наоборот, вердикт по сроку."""

    def _scene(self, tmp, age_h):
        root = pathlib.Path(_due(tmp))
        (root / "data").mkdir(exist_ok=True)
        (root / "data" / "ci_control_verdict.json").write_text(json.dumps(
            {"generated_at": (NOW - timedelta(hours=age_h)).isoformat()}),
            encoding="utf-8")
        return str(root)

    def test_within_the_tact_the_subprocess_is_not_even_started(self):
        r, save = _Runner(0, json.dumps(_DOC)), _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(self._scene(tmp, 1.0), runner=r,
                                             writer=save, now=NOW)
        self.assertEqual(out["status"], "within_tact")
        self.assertIsNone(r.cmd, "внутри такта прибор всё равно подняли — такт не бесплатен")
        self.assertEqual(save.calls, [], "внутри такта отчёт перезаписан — возраст соврал бы")

    def test_past_the_tact_it_measures(self):
        r, save = _Runner(0, json.dumps(_DOC)), _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(self._scene(tmp, 7.0), runner=r,
                                             writer=save, now=NOW)
        self.assertEqual(out["status"], "ok")
        self.assertEqual(len(save.calls), 1)

    def test_an_absent_report_means_measure_now(self):
        save = _Save()
        with tempfile.TemporaryDirectory() as tmp:
            out = fb.ci_control_verdict_step(_due(tmp), runner=_Runner(0, json.dumps(_DOC)),
                                             writer=save, now=NOW)
        self.assertEqual(out["status"], "ok")

    def test_the_tact_gate_is_borrowed_not_copied(self):
        """Вторая копия правила «пора ли мерить» разошлась бы с первой молча."""
        from spa_core.monitoring import python_reader_clock_doors as prcd
        self.assertIs(fb.measurement_due, prcd.measurement_due)

    def test_the_instrument_declares_no_tact_of_its_own(self):
        """Срок решает ФАЙЛ, файл пишет ПОЗВАВШИЙ ⇒ такт живёт ровно у него."""
        self.assertFalse(hasattr(ccv, "MEASUREMENT_TACT_DAYS"),
                         "вторая копия такта у прибора разошлась бы с копией писателя")

    def test_the_tact_matches_the_cadence_of_the_run_itself(self):
        """Такт зова и такт прогона — одно число: спрашивать чаще нечего.

        Расписание читается У ВОРКФЛОУ, а не помнится по тексту: `cron: 23 */6 * * *`.
        """
        wf = (_REPO / ".github" / "workflows" / "ci-control.yml").read_text(
            encoding="utf-8")
        self.assertIn('cron: "23 */6 * * *"', wf,
                      "расписание прогона изменилось — такт зова обязан поехать за ним")
        self.assertAlmostEqual(fb.CI_CONTROL_VERDICT_TACT_DAYS * 24.0, 6.0, places=6)

    def test_the_staleness_threshold_has_margin_over_the_cadence(self):
        """Порог, РАВНЫЙ такту прогона, краснел бы от дрожания расписания GitHub."""
        self.assertGreater(ccv.STALE_AFTER_H, fb.CI_CONTROL_VERDICT_TACT_DAYS * 24.0)


# ───────── 11. писатель ДОСТИЖИМ, а прибор только читает ──────────────────────

class TheDeclaredProductIsNotAnOrphan(unittest.TestCase):
    """Порванное звено, которое сторож нашёл у соседа до доставки (ADR-843).

    Писателя артефакта `_orphan_producer` ищет среди ТОЧЕК ВХОДА агентов и кода,
    импортированного не-тестовым кодом; зов подпроцессом по константе пути ему не
    виден. Писатель, живущий в приборе, был бы «объявленным продуктом, который никто
    не вычисляет».
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


# ─────────────── 12. конституция: производитель, SLO и запас ──────────────────

class TheConstitutionDeclaresTheArtifact(unittest.TestCase):
    """Порванное звено: артефакта в конституции нет — ни SLO, ни потребителя."""

    @classmethod
    def setUpClass(cls):
        doc = json.loads((_REPO / "architecture" / "manifest.json").read_text(
            encoding="utf-8"))
        cls.rows = [a for a in doc["artifacts"] if a.get("path") == ARTIFACT]

    def test_it_is_declared_exactly_once(self):
        self.assertEqual(len(self.rows), 1,
                         "две записи об одном артефакте — два разных SLO на одно число")

    def test_the_producer_is_named_not_null(self):
        self.assertEqual(self.rows[0].get("producer"), "com.spa.decision_loop")
        self.assertIn("orchestrator_protocol", self.rows[0].get("consumers", []))

    def test_the_slo_has_margin_over_the_tact(self):
        """Порог, РАВНЫЙ такту, краснеет от дрожания прогона (класс `no_margin`)."""
        slo_h = float(self.rows[0]["slo_hours"])
        tact_h = fb.CI_CONTROL_VERDICT_TACT_DAYS * 24.0
        self.assertGreater(slo_h, tact_h,
                           f"SLO {slo_h} ч не больше такта {tact_h} ч — запаса нет")


# ──────────────── 13. шаг 0-офис читает отчёт, а не открывает файл ────────────

class TheOfficeStepReadsItNotJustOpensIt(unittest.TestCase):
    """Порванное звено: артефакт читался бы ВХОЛОСТУЮ — файл открыт, чисел ноль."""

    @classmethod
    def setUpClass(cls):
        cls.src = (_REPO / "scripts" / "consume_office_reports.py").read_text(
            encoding="utf-8")

    def test_the_schema_producer_and_branch_are_all_three_there(self):
        base = os.path.basename(ARTIFACT)
        self.assertIn(f'"{base}": (', self.src,
                      "полей артефакта не объявлено — сверка схемы промолчит о чужом файле")
        self.assertIn(f'"{base}":\n        "{PRODUCER_REL}"', self.src,
                      "производитель артефакта шагу 0-офис не назван")
        self.assertIn(f'elif name == "{base}":', self.src,
                      "поимённой ветки нет ⇒ артефакт читается ВХОЛОСТУЮ")

    def test_the_branch_delegates_rendering_to_the_producer(self):
        """Вторая копия правила отрисовки расходится с первой МОЛЧА (ADR-220)."""
        self.assertIn("from ci_control_verdict import format_report", self.src)

    def test_every_declared_field_exists_in_a_real_document(self):
        """Схема, объявившая лишнее поле, краснит сверку словами «читаем НЕ ТОТ файл»."""
        doc = _Net([_run_row()], report=_report("GREEN")).doc()
        declared = self._declared_fields(os.path.basename(ARTIFACT))
        self.assertTrue(declared, "перечень полей не разобран — это НЕ «полей нет»")
        for field in declared:
            self.assertIn(field.split(".")[0], doc,
                          f"шаг 0-офис объявил поле {field!r}, которого в документе нет")

    def _declared_fields(self, base):
        for node in ast.walk(ast.parse(self.src)):
            if isinstance(node, ast.Dict):
                for k, v in zip(node.keys, node.values):
                    if (isinstance(k, ast.Constant) and k.value == base
                            and isinstance(v, ast.Tuple)):
                        return [e.value for e in v.elts if isinstance(e, ast.Constant)]
        return []

    def test_the_rendering_prints_absence_as_words_not_as_zero(self):
        """`None` в выводе читается глазом как «пусто, всё в порядке» — fail-OPEN."""
        lines = "\n".join(ccv.format_report({"status": "CLEAN"}))
        self.assertIn("НЕ ИЗМЕРЕНО", lines)
        self.assertNotIn("None", lines)

    def test_the_rendering_says_the_conclusion_is_not_the_verdict(self):
        """Читатель обязан увидеть ОБА числа и знать, какое из них вердикт."""
        lines = "\n".join(ccv.format_report(
            _Net([_run_row()], report=_report("RED", failures=57)).doc()))
        self.assertIn("conclusion failure", lines)
        self.assertIn("вердиктом НЕ является", lines)
        self.assertIn("RED", lines)

    def test_a_finding_is_marked_for_the_office_but_not_invented(self):
        found = ccv.format_report({"status": "FINDING", "verdict": "RED",
                                   "findings": ["набор КРАСЕН"]})
        self.assertTrue(found[0].startswith("⚠️"))
        clean = ccv.format_report({"status": "CLEAN", "verdict": "GREEN", "findings": []})
        self.assertFalse(clean[0].startswith("⚠️"))


if __name__ == "__main__":
    unittest.main()
