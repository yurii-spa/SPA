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


def _cause_axis(population: int) -> dict:
    """Ось причин ЗДОРОВОГО отчёта (ADR-891).

    Сцена дописана, а НЕ ослаблено утверждение (инв. #16): с 01.11 свод кладёт в отчёт
    ось причин, и отчёт БЕЗ неё законно даёт читателю вторую находку («ПРИЧИНА N
    падени(й) НЕ ИЗМЕРЕНА»). Тесты ниже считают находки ТОЧНО, и правильный ответ на
    их падение — привести сцену к тому, что производит сегодняшний свод, а не разрешить
    им не замечать лишнюю находку. Отсутствие оси проверяется ОТДЕЛЬНО и нарочно
    (`TheCauseAxisOfRedIsCarriedToTheReader`).
    """
    return {"schema": "spa-ci-control-cause-axis/1", "status": "measured",
            "population": population, "attributed": population,
            "unattributed": [], "unattributed_n": 0,
            "record_only": [], "record_only_n": 0,
            "kinds": {"AssertionError": population} if population else {},
            "cause_classes": {"cause_named": population} if population else {},
            "identities_hold": {"phases": True, "cause_classes": True,
                                "site_classes": True},
            "fork": {"population": population, "lower": population,
                     "upper": population, "cause_groups": population,
                     "coarse_groups": population, "merged_by_evidence": 0,
                     "largest_component": 1 if population else 0},
            "top": ([["AssertionError", "# != #", population]] if population else [])}


def _report(verdict="GREEN", *, sha="01dcead102aa1fae9c0287e8c6cab788de0a88e6",
            failures=0, incomplete=(), shards=12):
    return {"schema": "spa-ci-control-report/1", "verdict": verdict, "sha": sha,
            "cause_axis": _cause_axis(failures),
            "env": {"python": "3.11.17", "pytest": "9.1.1", "SPA_ENV": "ci",
                    "PYTHONHASHSEED": "0", "roots": ["tests"] * 6},
            "incomplete": list(incomplete),
            "failures": [{"nodeid": f"t{i}"} for i in range(failures)],
            "not_obtained": [], "shards": [{"shard": i} for i in range(shards)],
            "totals": {"population": 136806, "files": 2769, "passed": 136030,
                       "skipped": 719, "failed": failures, "error": 0,
                       "not_obtained": 0, "collect_errors": 0,
                       "shards_planned": shards, "shards_complete": shards}}


def _zip(member: str, doc) -> bytes:
    """Один zip с одним членом — ровно то, что отдаёт `actions/artifacts/<id>/zip`."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr(member, json.dumps(doc))
    return buf.getvalue()


class _Net:
    """Сеть ВХОДОМ: обе двери (JSON и байты) отвечают сценой, а не живым GitHub.

    Без этого каждый тест ниже отвечал бы на вопрос «что сегодня у GitHub», а не «цела
    ли проводка» (`.claude/rules/deployment.md`, § про инъекцию).
    """

    def __init__(self, runs, artifacts=None, report=None, *, fetch_raises=None,
                 grab_raises=None, zip_bytes=None, run_absent=None,
                 manifest=None, reports=None, manifests=None):
        self.runs = runs
        #: ПЛАН ШАРДОВ (ADR-1077) — второй артефакт того же прогона. Отдельный
        #: вход, а не поле отчёта: артефакты разные и сроки хранения разные, и
        #: сцена, подающая их одним куском, не умела бы изобразить главное
        #: состояние — «отчёт есть, плана нет».
        self.manifest = manifest
        #: по НОМЕРУ прогона, когда сцена изображает ДВА прогона дельты
        self.reports, self.manifests = reports or {}, manifests or {}
        #: Чем отвечает дверь строки прогона, когда номера в сцене НЕТ. Умолчание —
        #: документ без `status`: так ведёт себя ответ, из которого живость не выводится.
        self.run_absent = {} if run_absent is None else run_absent
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
            run = path.split("/actions/runs/", 1)[1].split("/")[0]
            return {"artifacts": self._artifacts_of(run)}
        # Дверь СТРОКИ ОДНОГО прогона (ADR-1058): живой API отдаёт здесь ровно ту же
        # строку, что и в списке, поэтому сцена берёт её из `self.runs` по номеру, а не
        # выдумывает вторую копию. Отдать сюда `{"workflow_runs": …}` значило бы
        # ответить на вопрос о живости документом БЕЗ `status` — и прибор честно сказал
        # бы «НЕ ИЗМЕРЕНО» о прогоне, чей статус сцена знает.
        hit = path.rsplit("/actions/runs/", 1)
        if len(hit) == 2 and hit[1].isdigit():
            for row in self.runs:
                if str(row.get("id")) == hit[1]:
                    return dict(row)
            return self.run_absent
        return {"workflow_runs": self.runs}

    def _artifacts_of(self, run):
        """Перечень артефактов ОДНОГО прогона: отчёт и — если сцена его дала — план.

        Номер прогона входит в адрес артефакта: без этого дельта двух прогонов
        получила бы ОДИН и тот же документ дважды, и «пришло 0» было бы
        свойством сцены.
        """
        if run in self.reports or run in self.manifests:
            rows = []
            if run in self.reports:
                rows.append({"id": f"r{run}", "name": "ci-control-report",
                             "expired": False,
                             "archive_download_url": f"https://api.example/{run}/report.zip"})
            if run in self.manifests:
                rows.append({"id": f"m{run}", "name": "ctl-manifest",
                             "expired": False,
                             "archive_download_url": f"https://api.example/{run}/manifest.zip"})
            return rows
        rows = list(self.artifacts)
        if self.manifest is not None and not any(
                a.get("name") == "ctl-manifest" for a in rows):
            rows.append({"id": 2, "name": "ctl-manifest", "expired": False,
                         "archive_download_url": "https://api.example/manifest.zip"})
        return rows

    def grab(self, url):
        self.asked.append(url)
        if self.grab_raises is not None:
            raise self.grab_raises
        if self.zip_bytes is not None:
            return self.zip_bytes
        for run, doc in self.manifests.items():
            if url.endswith(f"/{run}/manifest.zip"):
                return _zip("manifest.json", doc)
        for run, doc in self.reports.items():
            if url.endswith(f"/{run}/report.zip"):
                return _zip("report.json", doc)
        if "manifest" in url:
            return _zip("manifest.json", self.manifest)
        return _zip("report.json", self.report)

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

    def test_the_cause_of_absence_is_measured_not_assigned(self):
        """Порванное звено ADR-1058: причина «умер раньше сводки» НАЗНАЧАЛАСЬ.

        ДИФФЕРЕНЦИАЛЬНЫЙ контроль, и он единственный, который нельзя пройти случайно:
        две сцены отличаются РОВНО одним полем (`status`) и больше ничем, а причины
        обязаны выйти РАЗНЫЕ. Прибор, не спрашивающий живость (редакция до 18.11), даёт
        на обе сцены ОДНУ строку — и тест краснеет.
        """
        dead = self._cause(_Net([_run_row("44393343317")], artifacts=[]))
        alive = self._cause(_Net([_run_row("44393343317", status="in_progress",
                                           conclusion=None)], artifacts=[]))
        self.assertNotEqual(dead, alive,
                            "причина отсутствия отчёта НЕ ЗАВИСИТ от того, дожил ли "
                            "прогон до сводки — значит она назначена, а не измерена")
        self.assertIn("раньше сводки", dead)
        self.assertIn("ЕЩЁ ИДЁТ", alive)
        self.assertNotIn("умер", alive,
                         "идущий прогон назван мёртвым — ровно замер 18.11 по прогону "
                         "44393343317 (`status: in_progress`, шёл 1.0 ч)")

    def _cause(self, net):
        with self.assertRaises(ccv.NotMeasured) as box:
            ccv.report_of_run("44393343317", fetch=net.fetch, grab=net.grab, now=NOW)
        return str(box.exception)

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


# ──── 6a. ЖИВОСТЬ прогона — отдельное наблюдение от отсутствия отчёта ─────────

class TheLivenessOfARunIsItsOwnObservation(unittest.TestCase):
    """Предмет ADR-1058: причина внутри «НЕ ИЗМЕРЕНО» обязана быть ЗАМЕРОМ.

    Замер 18.11 (цикл #1197): заказанный предшественником вердикт прогона
    **44393343317** прибор объявил НЕ ИЗМЕРЕННЫМ с причиной «его нет вовсе — прогон
    умер раньше сводки», а живой API в ту же минуту отвечал `status: in_progress`
    (начат 20:39Z, шёл 1.0 ч). Отчёт кладёт сводка — у идущего прогона его нет ПОКА.

    Цена ложной причины названа в ADR: «умер» приглашает заказать НОВЫЙ прогон
    (≈1–1.6 ч раннера) и потерять якорь дельты, «ещё идёт» требует обратного.

    Каждый тест ниже — положительный контроль одного порванного звена.
    """

    def test_a_running_run_is_named_running(self):
        """Звено: живость НЕ СПРАШИВАЛАСЬ вовсе."""
        net = _Net([_run_row("44393343317", status="in_progress", conclusion=None)])
        live = ccv.run_liveness("44393343317", fetch=net.fetch, now=NOW)
        self.assertEqual(live["state"], ccv.LIVE_RUNNING)
        self.assertEqual(live["status"], "in_progress")

    def test_a_completed_run_is_named_completed(self):
        net = _Net([_run_row("44393343317")])
        live = ccv.run_liveness("44393343317", fetch=net.fetch, now=NOW)
        self.assertEqual(live["state"], ccv.LIVE_DONE)
        self.assertEqual(live["conclusion"], "failure")

    def test_an_unreadable_run_row_is_the_THIRD_outcome(self):
        """Звено: немочь двери подставлялась бы как «завершён» либо как «идёт».

        Оба подставления неверны в ОПАСНУЮ сторону (инв. #17), поэтому у «не прочитано»
        своё состояние и своя названная причина.
        """
        net = _Net([_run_row("1")])  # номера 44393343317 в сцене НЕТ
        live = ccv.run_liveness("44393343317", fetch=net.fetch, now=NOW)
        self.assertEqual(live["state"], ccv.LIVE_UNMEASURED)
        self.assertIn("статуса не несёт", live["why"])

        net = _Net([_run_row("44393343317")],
                   fetch_raises=OSError("сеть отвалилась"))
        live = ccv.run_liveness("44393343317", fetch=net.fetch, now=NOW)
        self.assertEqual(live["state"], ccv.LIVE_UNMEASURED)
        self.assertIn("не прочитана", live["why"])

    def test_the_three_states_never_collapse_into_two(self):
        """Звено: два из трёх состояний назывались бы ОДНОЙ строкой."""
        scenes = {
            ccv.LIVE_DONE: _Net([_run_row("7")]),
            ccv.LIVE_RUNNING: _Net([_run_row("7", status="queued", conclusion=None)]),
            ccv.LIVE_UNMEASURED: _Net([_run_row("8")]),
        }
        seen = {want: ccv.run_liveness("7", fetch=net.fetch, now=NOW)["state"]
                for want, net in scenes.items()}
        self.assertEqual(seen, {k: k for k in scenes},
                         "состояния живости слиплись — «не измерено» перестало быть "
                         "отличимым от ответа")

    def test_the_age_is_anchored_to_the_injected_clock(self):
        """Звено: возраст идущего прогона спрашивался бы у СТЕННЫХ часов.

        Обе стороны сравнения производны от якоря `NOW`: `created_at` сцены считается
        от него же, поэтому тест не краснеет от того, что сдвинулся календарь
        (`.claude/rules/deployment.md`, § про время в тестах).
        """
        net = _Net([_run_row("9", status="in_progress", conclusion=None, ended_h=1.0)])
        live = ccv.run_liveness("9", fetch=net.fetch, now=NOW)
        self.assertAlmostEqual(live["age_h"], 1.6, places=3)

    def test_the_liveness_is_asked_ONLY_when_the_report_is_missing(self):
        """Звено: лишний запрос на счастливом пути (цена без вопроса).

        Вторая половина — ОБРАТНАЯ: когда отчёта нет, запрос обязан БЫТЬ, иначе
        причина не может быть заработана ничем.
        """
        def asked_run_rows(net):
            return [p for p in net.asked
                    if "/actions/runs/" in str(p) and "/artifacts" not in str(p)
                    and str(p).rsplit("/", 1)[-1].isdigit()]

        healthy = _Net([_run_row("44393343317")])
        ccv.report_of_run("44393343317", fetch=healthy.fetch, grab=healthy.grab, now=NOW)
        self.assertEqual(asked_run_rows(healthy), [],
                         "отчёт на месте, а строку прогона всё равно спросили — "
                         "это цена без вопроса")

        empty = _Net([_run_row("44393343317")], artifacts=[])
        with self.assertRaises(ccv.NotMeasured):
            ccv.report_of_run("44393343317", fetch=empty.fetch, grab=empty.grab, now=NOW)
        self.assertTrue(asked_run_rows(empty),
                        "отчёта нет, а живость не спросили — причину взять негде")

    def test_the_delta_path_says_WAIT_not_DIED(self):
        """Звено, которое и было найдено: именно `--delta` получает номер ИЗВНЕ.

        В :func:`ccv.census` прогон завершён ПО ПОСТРОЕНИЮ (отбор по
        `status == "completed"`), поэтому дефект там не наблюдался ни разу — и ровно
        поэтому его не замечали: сцена счастливого пути его не производит.
        """
        net = _Net([_run_row("44371815483"),
                    _run_row("44393343317", status="in_progress", conclusion=None)],
                   artifacts=[])
        with self.assertRaises(ccv.NotMeasured) as box:
            ccv.delta_run("44371815483", "44393343317",
                          fetch=net.fetch, grab=net.grab, now=NOW)
        self.assertIn("раньше сводки", str(box.exception),
                      "прежний прогон ЗАВЕРШЁН, и про него причина прежняя")

        net = _Net([_run_row("44371815483"),
                    _run_row("44393343317", status="in_progress", conclusion=None)],
                   artifacts=[])
        with self.assertRaises(ccv.NotMeasured) as box:
            ccv.delta_run("44393343317", "44371815483",
                          fetch=net.fetch, grab=net.grab, now=NOW)
        self.assertIn("ЕЩЁ ИДЁТ", str(box.exception))
        self.assertNotIn("умер", str(box.exception))
        # Возраст тоже обязан быть от ЯКОРЯ: не доехал бы `now` до двери — строка несла
        # бы верное состояние и ВЫДУМАННЫЙ срок, а срок здесь и есть то, по чему решают
        # «ждать ещё» или «прогон завис».
        self.assertIn("идёт 1.6ч", str(box.exception))

    def test_the_exit_code_of_all_three_stays_the_THIRD_outcome(self):
        """Звено: «ещё идёт» получило бы код, который читается как вердикт.

        Код у всех трёх один (**2**) намеренно: вердиктом не является ни одно из
        состояний, а различие живёт в ПРИЧИНЕ. Отдельный код без читателя был бы
        «написано и не позвано» (ADR-345).
        """
        for scene in ("in_progress", "completed"):
            net = _Net([_run_row("44393343317", status=scene,
                                 conclusion=None if scene == "in_progress" else "failure")],
                       artifacts=[])
            # Патчатся ВСЕ три двери наружу, включая Keychain: этот файл живой машины не
            # спрашивает ни разу (шапка), а `artifact_grab(_keychain_token())` поднял бы
            # подпроцесс `security` и отвечал бы на вопрос «что сегодня у этого Мака».
            saved = (ccv.github_fetch, ccv.artifact_grab, ccv._keychain_token)
            ccv.github_fetch = lambda: net.fetch
            ccv.artifact_grab = lambda token=None: net.grab
            ccv._keychain_token = lambda: "сцена"
            try:
                code = ccv.main(["--delta", "44393343317", "44393343317"])
            finally:
                ccv.github_fetch, ccv.artifact_grab, ccv._keychain_token = saved
            self.assertEqual(code, 2, f"сцена {scene}: третий исход потерял свой код")


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


# ─── 12. ПЕРЕПИСЬ красного населения (ADR-888, заказ G885 п. 4) ───────────────

def _red_report(rows, *, declared=None, non_passed=None, verdict="RED",
                shards=12, drop_failures=False):
    """Отчёт со СЦЕНОЙ красного населения. Сцена — ВХОД, а не словарь пробы.

    ``rows`` — пары «nodeid, шард»; ``declared`` подменяет итоги, чтобы сцена могла
    РАЗОЙТИСЬ с названным; ``non_passed`` — второй, независимый перечень исходов того
    же прогона. ``drop_failures`` снимает перечень целиком: это сцена третьего исхода,
    и она обязана быть отличима от зелёного отчёта.
    """
    doc = _report(verdict, shards=shards)
    failures = [{"nodeid": n, "outcome": o, "shard": sh} for n, o, sh in rows]
    if drop_failures:
        doc.pop("failures", None)
    else:
        doc["failures"] = failures
    doc["cause_axis"] = _cause_axis(len(rows))
    counts = {"failed": sum(1 for _, o, _ in rows if o == "failed"),
              "error": sum(1 for _, o, _ in rows if o == "error")}
    doc["totals"] = {**doc["totals"], **counts, **(declared or {})}
    if non_passed is not None:
        doc["non_passed"] = non_passed
    return doc


#: Сцена разной кратности: один файл несёт три падения, один — два, два — по одному.
#: Сцена из одних одиночек не отличила бы «50 работ» от «14 работ», то есть не
#: отвечала бы на вопрос, ради которого перепись написана (замер 01.11: 79 падений,
#: 50 файлов, 14 из них несут 43 падения).
_SCENE = [("spa_core/tests/test_a.py::T::test_one", "failed", 1),
          ("spa_core/tests/test_a.py::T::test_two", "failed", 1),
          ("spa_core/tests/test_a.py::T::test_three", "failed", 2),
          ("scripts/tests/test_b.py::test_one", "failed", 3),
          ("scripts/tests/test_b.py::test_two", "failed", 3),
          ("tests/test_c.py::test_one", "failed", 4),
          ("spa_core/tests/test_d.py::test_one", "failed", 5)]

_SCENE_NAMES = {n: "failed" for n, _, _ in _SCENE}


class ThePopulationOfRedIsNamedNotOnlyCounted(unittest.TestCase):
    """Порванное звено: до 01.11 читатель отдавал про красное РОВНО одно число.

    Замер того дня на `126a2ec2a`: **79** падений, и шаг 0-офис знал про них только
    «упавших 79» плюс приписку «названы поимённо в `report.json` артефакта». Имена там
    и лежали; не брал их НИ ОДИН читатель, поэтому девять разобранных храповиков были
    подмножеством, доля которого в населении не измерялась ни разу.
    """

    def setUp(self):
        self.doc = _Net([_run_row()], report=_red_report(
            _SCENE, non_passed={**_SCENE_NAMES, "tests/test_z.py::t": "skipped"})).doc()
        self.cen = self.doc["red_census"]

    def test_the_document_carries_the_census(self):
        self.assertEqual(self.cen["status"], "measured")

    def test_the_files_under_the_number_are_counted(self):
        self.assertEqual(self.cen["named"], 7)
        self.assertEqual(self.cen["files"], 4)

    def test_a_file_with_several_failures_is_one_work_not_several(self):
        """Урок #1002: три красных теста `test_fixture_schema_gap_ratchet` оказались
        ОДНОЙ правкой. Число работ и число падений — разные числа."""
        self.assertEqual(self.cen["subjects_multi"], 2)
        self.assertEqual(self.cen["in_multi"], 5)
        self.assertEqual(self.cen["subjects_single"], 2)

    def test_the_worst_file_is_named_so_there_is_a_place_to_start(self):
        self.assertEqual(self.cen["worst"][0], ["spa_core/tests/test_a.py", 3])

    def test_the_roots_are_split(self):
        self.assertEqual(self.cen["roots"],
                         {"scripts": 2, "spa_core": 4, "tests": 1})

    def test_the_rendered_lines_name_the_file_because_the_office_reads_them(self):
        """Шаг 0-офис идёт через `report()`: перепись в документе и перепись в
        строках — два разных наблюдения, и второе и есть то, что читают."""
        lines = "\n".join(ccv.format_report(self.doc))
        self.assertIn("spa_core/tests/test_a.py", lines)
        self.assertIn("с чего начинать", lines)

    def test_the_red_finding_itself_carries_the_population(self):
        """Находка остаётся ОДНА — но она больше не отсылает к артефакту,
        которого не читает никто."""
        self.assertEqual(len(self.doc["findings"]), 1)
        self.assertIn("перепись", self.doc["findings"][0])
        self.assertIn("файл", self.doc["findings"][0])
        self.assertNotIn("в `report.json` артефакта", self.doc["findings"][0],
                         "находка по-прежнему отсылает к артефакту, которого не "
                         "читает ни один читатель — предмет заказа G885 п. 4")


class AnAbsentPopulationIsNotZero(unittest.TestCase):
    """Третий исход (инв. #17): «красное не названо» ≠ «красного нет».

    Чинятся они разным: первое — у производителя отчёта, второе — ничем. Свести их
    значило бы вернуть предмет на шаг дальше, уже внутри переписи.
    """

    def test_a_report_without_the_failures_list_is_unmeasured(self):
        doc = _Net([_run_row()], report=_red_report(
            _SCENE, drop_failures=True)).doc()
        self.assertEqual(doc["red_census"]["status"], "unmeasured")
        self.assertIn("failures", doc["red_census"]["why"])

    def test_that_absence_is_a_finding_of_its_own(self):
        doc = _Net([_run_row()], report=_red_report(
            _SCENE, drop_failures=True)).doc()
        self.assertIn("население красного НЕ ИЗМЕРЕНО", " ".join(doc["findings"]))

    def test_the_rendering_says_words_not_zero(self):
        doc = _Net([_run_row()], report=_red_report(
            _SCENE, drop_failures=True)).doc()
        lines = "\n".join(ccv.format_report(doc))
        self.assertIn("НЕ ИЗМЕРЕНА", lines)
        self.assertNotIn("с чего начинать", lines,
                         "перечень «с чего начинать» напечатан у НЕ ИЗМЕРЕННОЙ "
                         "переписи — пустая строка читается как «начинать не с чего»")

    def test_an_incomplete_verdict_still_carries_the_population_in_the_lines(self):
        """Отдельная строка отчёта НЕ избыточна, и это ИЗМЕРЕНО, а не объявлено.

        У красного вердикта перепись едет ДВУМЯ носителями — строкой отчёта и самой
        находкой. У `INCOMPLETE` находки о красном нет ВОВСЕ, поэтому носителем
        остаётся одна строка; сними её — и население, которое уже измерено, читателю
        не достанется.
        """
        rep = _red_report(_SCENE, verdict="INCOMPLETE", shards=0,
                          non_passed=_SCENE_NAMES)
        rep["incomplete"] = [{"shard": 3, "reason": "шард снят"}]
        doc = _Net([_run_row()], report=rep).doc()
        self.assertEqual(doc["verdict"], "INCOMPLETE")
        self.assertNotIn("КРАСЕН", " ".join(doc["findings"]))
        lines = "\n".join(ccv.format_report(doc))
        self.assertIn("перепись: названных 7", lines)
        self.assertIn("spa_core/tests/test_a.py", lines)

    def test_a_green_report_is_measured_and_empty_not_unmeasured(self):
        """Обратная половина: у зелёного отчёта перечень пуст ПО ПОСТРОЕНИЮ, и
        требовать его значило бы краснеть на здоровом прогоне."""
        doc = _Net([_run_row(conclusion="success")],
                   report=_report("GREEN")).doc()
        self.assertEqual(doc["red_census"]["status"], "measured")
        self.assertEqual(doc["red_census"]["named"], 0)
        self.assertEqual(doc["findings"], [])


class TheThreeRecordsOfOneRunAreCompared(unittest.TestCase):
    """Порванное звено: красное, которое ОБЪЯВЛЕНО и не НАЗВАНО, разобрать нечем.

    У одного отчёта три независимые записи красного — перечень `failures`, итоги
    (`failed` + `error`) и второй перечень исходов `non_passed`. У здорового отчёта
    они равны; расхождение любой пары чинится не в наборе, а у производителя отчёта,
    поэтому это СВОЯ находка, а не «набор красен».
    """

    def test_declared_more_than_named_is_a_finding_with_both_numbers(self):
        doc = _Net([_run_row()], report=_red_report(
            _SCENE, declared={"failed": 9}, non_passed=_SCENE_NAMES)).doc()
        found = " ".join(doc["findings"])
        self.assertIn("НАЗВАНО не всё", found)
        self.assertIn("9", found)
        self.assertIn("7", found)

    def test_an_error_outcome_counts_as_declared_red(self):
        """Обратная половина, и она про АРИФМЕТИКУ находки: производитель кладёт в
        `failures` И `failed`, И `error`, а в итоги разводит их по двум ключам.
        Операнд из одного ключа кричал бы «названо не всё» на здоровом отчёте."""
        rows = _SCENE[:-1] + [("spa_core/tests/test_d.py::test_one", "error", 5)]
        doc = _Net([_run_row()], report=_red_report(
            rows, non_passed={n: o for n, o, _ in rows})).doc()
        cen = doc["red_census"]
        self.assertEqual(cen["declared_parts"], {"failed": 6, "error": 1})
        self.assertEqual((cen["declared"], cen["named"], cen["cross_named"]), (7, 7, 7))
        self.assertNotIn("НАЗВАНО не всё", " ".join(doc["findings"]))

    def test_the_second_list_disagreeing_is_its_own_finding(self):
        short = dict(list(_SCENE_NAMES.items())[:4])
        doc = _Net([_run_row()], report=_red_report(
            _SCENE, non_passed=short)).doc()
        self.assertIn("две независимые записи", " ".join(doc["findings"]))

    def test_an_absent_second_list_is_not_a_disagreement(self):
        """Отсутствие второго перечня — НЕ расхождение: «не измерено» нельзя
        выдавать за находку, иначе находка говорит о форме отчёта, а не о красном."""
        doc = _Net([_run_row()], report=_red_report(_SCENE)).doc()
        self.assertIsNone(doc["red_census"]["cross_named"])
        self.assertNotIn("две независимые записи", " ".join(doc["findings"]))
        self.assertIn("второй перечень прогона НЕ ИЗМЕРЕНО",
                      "\n".join(ccv.format_report(doc)))

    def test_absent_totals_keys_are_unmeasured_not_zero(self):
        rep = _red_report(_SCENE, non_passed=_SCENE_NAMES)
        rep["totals"] = {k: v for k, v in rep["totals"].items()
                         if k not in ("failed", "error")}
        doc = _Net([_run_row()], report=rep).doc()
        self.assertIsNone(doc["red_census"]["declared"])
        self.assertIn("объявленное число красного НЕ ИЗМЕРЕНО",
                      " ".join(doc["findings"]))

    def test_a_failure_row_without_a_nodeid_is_counted_not_dropped(self):
        rep = _red_report(_SCENE, non_passed=_SCENE_NAMES)
        rep["failures"] = rep["failures"] + [{"outcome": "failed", "shard": 7}]
        doc = _Net([_run_row()], report=rep).doc()
        self.assertEqual(doc["red_census"]["nameless_rows"], 1)
        self.assertIn("без разбираемого", " ".join(doc["findings"]))


class TheCensusKeysComeFromTheProducer(unittest.TestCase):
    """Тот же порванный провод, что у секции 8, но на ключах ПЕРЕПИСИ.

    Первая редакция соседа спрашивала итог `no_outcome`, которого
    `ci_control.aggregate` не пишет вовсе, и о здоровом отчёте говорила «НЕ
    ИЗМЕРЕНО» — жаловалась на свою опечатку. У переписи дверей больше: перечень
    `failures`, поля его строк и второй перечень `non_passed`.
    """

    @classmethod
    def setUpClass(cls):
        src = (_REPO / "scripts" / "ci_control.py").read_text(encoding="utf-8")
        cls.literals = {n.value for n in ast.walk(ast.parse(src))
                        if isinstance(n, ast.Constant) and isinstance(n.value, str)}

    def test_every_key_the_census_asks_is_written_by_ci_control(self):
        for key in ("failures", "non_passed", "nodeid", "outcome", "shard", "totals"):
            self.assertIn(key, self.literals,
                          f"перепись спрашивает {key!r}, которого производитель "
                          f"отчёта не пишет: о здоровом отчёте она скажет «НЕ ИЗМЕРЕНО»")

    def test_the_red_outcome_literals_are_the_producers_own(self):
        for outcome in ccv.RED_OUTCOMES:
            self.assertIn(outcome, self.literals)
        for key in ccv.DECLARED_RED_KEYS:
            self.assertIn(key, self.literals)

    def test_control_a_fabricated_key_is_caught(self):
        self.assertNotIn("non_passed_rows", self.literals,
                         "проверка выше ничего не стоит: выдуманный ключ она "
                         "признала бы написанным производителем")

    def test_the_producer_really_puts_both_outcomes_into_the_failures_list(self):
        """Операнд-сумма держится НЕ на прозе: производитель отбирает в `failures`
        строки, чей исход попал в `(FAILED, ERROR)`. Разойдись это — находка
        «названо не всё» заговорила бы о своей же арифметике."""
        src = (_REPO / "scripts" / "ci_control.py").read_text(encoding="utf-8")
        self.assertIn("outcomes.get(n) in (FAILED, ERROR)", src)


class TheCauseAxisOfRedIsCarriedToTheReader(unittest.TestCase):
    """Ось ПРИЧИН доходит до шага 0-офис, а её отсутствие НАЗЫВАЕТСЯ (ADR-891).

    Читатель ось не переопознаёт: опознаёт её единственная дверь
    (`spa_core/monitoring/failure_cause_census.py`) у свода, а читатель ПРОНОСИТ готовое
    и говорит словами, когда нести нечего. Поэтому здесь проверяется ПРОВОДКА и три
    исхода, а не арифметика причин (её контроль — `test_ci_cause_axis.py`).
    """

    def _doc(self, report):
        return _Net([_run_row()], report=report).doc()

    def test_a_measured_axis_reaches_the_rendered_lines(self):
        doc = self._doc(_red_report(rows=[("tests/test_a.py::t1", "failed", 1),
                                          ("tests/test_a.py::t2", "failed", 1)]))
        axis = doc["red_census"]["cause_axis"]
        self.assertEqual(axis["status"], "measured", axis)
        lines = "\n".join(ccv.report(doc))
        self.assertIn("опознано 2 из 2", lines)
        self.assertEqual([f for f in doc["findings"] if "ПРИЧИНА" in f], [])

    def test_a_report_without_the_axis_is_named_not_zeroed(self):
        rep = _red_report(rows=[("tests/test_a.py::t1", "failed", 1)])
        rep.pop("cause_axis")
        doc = self._doc(rep)
        self.assertIsNone(doc["red_census"]["cause_axis"])
        lines = "\n".join(ccv.report(doc))
        self.assertIn("НЕ ИЗМЕРЕНА", lines)
        self.assertTrue([f for f in doc["findings"]
                         if "ПРИЧИНА" in f and "НЕ ИЗМЕРЕНА" in f], doc["findings"])

    def test_a_green_report_without_the_axis_is_not_a_finding(self):
        """У зелёного отчёта падений нет ПО ПОСТРОЕНИЮ — требовать причин было бы
        красным на здоровом прогоне."""
        rep = _report()
        rep.pop("cause_axis")
        doc = self._doc(rep)
        self.assertEqual([f for f in doc["findings"] if "ПРИЧИНА" in f], [])

    def test_an_unattributed_failure_is_a_finding_of_its_own(self):
        rep = _red_report(rows=[("tests/test_a.py::t1", "failed", 1),
                                ("tests/test_a.py::t2", "failed", 1)])
        rep["cause_axis"] = {**rep["cause_axis"], "attributed": 1,
                             "unattributed": ["tests/test_a.py::t2"],
                             "unattributed_n": 1}
        doc = self._doc(rep)
        self.assertTrue([f for f in doc["findings"] if "НЕ\u00a0ОПОЗНАНА" in f
                         or "НЕ ОПОЗНАНА" in f], doc["findings"])

    def test_a_broken_identity_of_the_axis_is_a_finding(self):
        rep = _red_report(rows=[("tests/test_a.py::t1", "failed", 1)])
        rep["cause_axis"] = {**rep["cause_axis"],
                             "identities_hold": {"phases": False,
                                                 "cause_classes": True,
                                                 "site_classes": True}}
        doc = self._doc(rep)
        self.assertTrue([f for f in doc["findings"] if "тождество учёта" in f],
                        doc["findings"])

    def test_the_rule_of_the_line_has_exactly_one_copy(self):
        """Правило чтения оси живёт у свода; читатель БЕРЁТ его, а не пишет второе."""
        src = (_REPO / "scripts" / "ci_control_verdict.py").read_text(encoding="utf-8")
        self.assertIn("_load_cause_line", src)
        self.assertNotIn("дефектов НЕ МЕНЬШЕ", src,
                         "вторая копия строки про вилку: разойдись она с первой — "
                         "два читателя сказали бы о причинах разное молча")


# ───────── 14. ось ПЕРЕЕЗДА у дельты: план шардов (ADR-1077, #1222) ───────────

def _reads_key(node, key: str) -> bool:
    """Читает ли узел ключ ``key`` — подпиской либо ``.get(key)``.

    Запись того же ключа в литерал словаря чтением НЕ является: меряется второй
    РАЗБОР, а не упоминание имени.
    """
    for inner in ast.walk(node):
        if (isinstance(inner, ast.Subscript)
                and isinstance(inner.slice, ast.Constant)
                and inner.slice.value == key):
            return True
        if (isinstance(inner, ast.Call)
                and isinstance(inner.func, ast.Attribute)
                and inner.func.attr == "get"
                and inner.args
                and isinstance(inner.args[0], ast.Constant)
                and inner.args[0].value == key):
            return True
    return False


def _plan_parsers(source: str) -> list:
    """Функции, которые читают И ``files``, И ``shard`` — то есть РАЗБИРАЮТ план.

    Один ключ мерой не является, и это ИЗМЕРЕНО: `files` в приборе читается
    законно (`cen.get("files")` — счёт файлов переписи красного), `shard` тоже
    (`r.get("shard")` — шард упавшего имени в ОТЧЁТЕ). Разбор плана отличается
    от обоих тем, что ему нужны ОБА ключа одной записи — и в приборе таких
    функций нет ни одной.
    """
    return [n.name for n in ast.walk(ast.parse(source))
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _reads_key(n, "files") and _reads_key(n, "shard")]


#: Сцена плана шардов в ФОРМЕ ПРОИЗВОДИТЕЛЯ (`ci_control.cmd_plan`).
def _plan(by_file: dict) -> dict:
    buckets: dict[int, list] = {}
    for path, shard in by_file.items():
        buckets.setdefault(shard, []).append(path)
    return {"schema": "spa-ci-control-manifest/1", "sha": "deadbeef",
            "shards": [{"shard": k, "files": v} for k, v in sorted(buckets.items())]}


class TheManifestArtifactIsNamedByTheWorkflowNotByMemory(unittest.TestCase):
    """Звено: литерал имени/срока разошёлся бы с воркфлоу МОЛЧА.

    Разойдись — прибор ответил бы «плана шардов нет» о живом артефакте, то есть
    выдал бы НЕ ИЗМЕРЕНО на измеримом вопросе. Поэтому и имя, и срок читаются У
    ВОРКФЛОУ, а не помнятся по тексту.
    """

    def setUp(self):
        self.wf = (_REPO / ".github" / "workflows" / "ci-control.yml").read_text(
            encoding="utf-8")

    def test_the_artifact_name_matches_the_workflow(self):
        self.assertIn(f"name: {ccv.MANIFEST_ARTIFACT}", self.wf)

    def test_the_retention_of_the_plan_matches_the_workflow(self):
        self.assertIn(f"retention-days: {ccv.MANIFEST_RETENTION_DAYS}", self.wf)

    def test_the_plan_lives_SHORTER_than_the_report(self):
        """Это НЕ украшение: на нём стои́т штатность состояния «отчёт есть, плана нет».

        Срок отчёта читается у того же воркфлоу — равняй их, и прибор перестал
        бы отличать «истёк» от «прогон умер раньше сводки».
        """
        self.assertIn("retention-days: 90", self.wf)
        self.assertLess(ccv.MANIFEST_RETENTION_DAYS, 90)

    def test_the_plan_is_parsed_by_ONE_door_and_it_is_not_here(self):
        """Второй разбор манифеста разошёлся бы с генератором молча (ADR-220).

        Мерка — AST, а не подстрока: `doc.get("shards")` в приборе ЕСТЬ и
        законно (так читается перечень шардов ОТЧЁТА), и запрет по этой строке
        покраснел бы на верном состоянии. Второй разбор ПЛАНА узнаётся по
        чтению ОБОИХ ключей записи шарда — ``files`` и ``shard``; по одному
        ключу запрет покраснел бы на верном состоянии (оба читаются в приборе
        законно, но в РАЗНЫХ функциях и о РАЗНЫХ документах).
        """
        src = (_REPO / PRODUCER_REL).read_text(encoding="utf-8")
        self.assertIn("red_set_delta.shard_map_of", src)
        self.assertEqual(_plan_parsers(src), [],
                         "в приборе появился свой разбор плана шардов")

    def test_the_AST_measure_finds_a_second_parser_when_there_IS_one(self):
        """ОБРАТНАЯ половина: без неё мерка прошла бы и у той, что не находит НИЧЕГО."""
        fake = ('def parse(doc):\n'
                '    out = {}\n'
                '    for row in doc.get("shards") or []:\n'
                '        for f in row["files"]:\n'
                '            out[f] = row["shard"]\n'
                '    return out\n')
        self.assertEqual(_plan_parsers(fake), ["parse"])

    def test_the_measure_does_not_fire_on_a_single_key(self):
        """Мерка по ОДНОМУ ключу краснела бы на верном приборе — это ИЗМЕРЕНО."""
        one = ('def a(cen):\n    return cen.get("files")\n'
               'def b(rows):\n    return {r.get("shard") for r in rows}\n')
        self.assertEqual(_plan_parsers(one), [])
        self.assertTrue(_reads_key(ast.parse(one), "files"))
        self.assertTrue(_reads_key(ast.parse(one), "shard"))

    def test_the_single_door_is_the_module_function_itself(self):
        """«Имя упомянуто» ≠ «зовётся ОНО»: сверяется объект, а не текст."""
        from spa_core.monitoring import red_set_delta as rsd
        net = _Net([_run_row("45108124169")],
                   manifest=_plan({"spa_core/tests/test_a.py": 4}))
        mine = ccv._shard_map_of_run("45108124169", fetch=net.fetch,
                                     grab=net.grab, now=NOW)
        theirs = rsd.shard_map_of(_plan({"spa_core/tests/test_a.py": 4}),
                                  label=mine.reason or "план")
        self.assertEqual(mine.by_file, theirs.by_file)
        self.assertIs(type(mine), rsd.ShardMap)


class TheRunNumberReachesTheMapFromTHISDoorOnly(unittest.TestCase):
    """ПРОВОДКА номера прогона: поле есть, дверь его принимает — доезжает ли он?

    Найдено мутационным замером цикла #1223 (ADR-1078, заказ G1065 п. 13): после
    разделения родов личности `ShardMap` мутация «снять `run=run_id` у зова
    `shard_map_of`» ВЫЖИЛА — рода были проверены у РАЗБОРЩИКА, а проводку от
    ЭТОЙ двери не спрашивал никто. Класс знакомый: «половина инъекции» того же
    рода, что § «ЛИЧНОСТЬ ПРОЦЕССА» правила доставки («параметр у сторожа есть,
    у проводки нет»).

    Номер прогона знает ТОЛЬКО эта дверь: сам манифест его не несёт
    (`ci_control.cmd_plan` пишет `sha` и номера не пишет вовсе), поэтому
    потерять его здесь значит потерять навсегда.
    """

    def test_the_run_number_arrives_and_the_sha_comes_from_the_manifest(self):
        net = _Net([_run_row("45108124169")],
                   manifest=_plan({"spa_core/tests/test_a.py": 4}))
        chart = ccv._shard_map_of_run("45108124169", fetch=net.fetch,
                                      grab=net.grab, now=NOW)
        self.assertEqual(chart.run, "45108124169",
                         "номер прогона не доехал до карты, а знает его ТОЛЬКО "
                         "эта дверь — в манифесте его нет вовсе")
        self.assertEqual(chart.sha, "deadbeef",
                         "вершина обязана приходить ИЗ МАНИФЕСТА, а не от "
                         "вызывающего")
        self.assertNotEqual(chart.run, chart.sha,
                            "два рода личности слились в одно значение — это и "
                            "был предмет п. 13 заказа G1065")

    def test_the_run_number_arrives_even_when_the_plan_is_UNMEASURED(self):
        """ОБРАТНАЯ половина: немочь сети тоже обязана сказать, О ЧЬЁМ прогоне она."""
        net = _Net([_run_row("45108124169")],
                   artifacts=[{"id": 1, "name": "ci-control-report",
                               "expired": False,
                               "archive_download_url": "https://api.example/zip"}])
        chart = ccv._shard_map_of_run("45108124169", fetch=net.fetch,
                                      grab=net.grab, now=NOW)
        self.assertFalse(chart.measured, "сцена не обеспечена: карта измерена")
        self.assertEqual(chart.run, "45108124169",
                         "безымянный отказ: читатель не узнает, о чьём плане он")
        self.assertIsNone(chart.sha,
                          "вершины не наблюдалось — подставлять вместо неё "
                          "номер прогона нельзя (инв. #17)")


class TheManifestDoorRefusesByNAME(unittest.TestCase):
    """Каждое порванное звено двери плана — названная причина, а не пустая карта."""

    def _net(self, **kw):
        return _Net([_run_row("45108124169")], **kw)

    def test_no_plan_artifact_at_all_refuses(self):
        net = self._net(artifacts=[{"id": 1, "name": "ci-control-report",
                                    "expired": False,
                                    "archive_download_url": "https://api.example/zip"}])
        with self.assertRaises(ccv.NotMeasured) as box:
            ccv.manifest_of_run("45108124169", fetch=net.fetch, grab=net.grab, now=NOW)
        self.assertIn(ccv.MANIFEST_ARTIFACT, str(box.exception))

    def test_an_expired_plan_names_the_retention_and_calls_it_NORMAL(self):
        """«Отчёт есть, плана нет» штатно — сроки РАЗНЫЕ, и это сказано словами."""
        net = self._net(artifacts=[{"id": 2, "name": "ctl-manifest", "expired": True}])
        with self.assertRaises(ccv.NotMeasured) as box:
            ccv.manifest_of_run("45108124169", fetch=net.fetch, grab=net.grab, now=NOW)
        self.assertIn("истёк", str(box.exception))
        self.assertIn(str(ccv.MANIFEST_RETENTION_DAYS), str(box.exception))

    def test_a_broken_zip_refuses(self):
        net = self._net(manifest=_plan({"a.py": 0}), zip_bytes=b"not a zip")
        with self.assertRaises(ccv.NotMeasured) as box:
            ccv.manifest_of_run("45108124169", fetch=net.fetch, grab=net.grab, now=NOW)
        self.assertIn("не разобран", str(box.exception))

    def test_a_zip_without_the_member_refuses(self):
        net = self._net(manifest=_plan({"a.py": 0}),
                        zip_bytes=_zip("collect.log", "пусто"))
        with self.assertRaises(ccv.NotMeasured) as box:
            ccv.manifest_of_run("45108124169", fetch=net.fetch, grab=net.grab, now=NOW)
        self.assertIn("не разобран", str(box.exception))

    def test_the_failure_does_NOT_escape_into_the_delta(self):
        """Несущая половина: немочь ПЛАНА не вправе рушить дельту по родам.

        Обратная сцена — ниже (`test_a_measured_plan_comes_back_as_a_map`): без
        неё проверка проходила бы и у двери, которая НИКОГДА не измеряет.
        """
        net = self._net(artifacts=[])
        chart = ccv._shard_map_of_run("45108124169", fetch=net.fetch,
                                      grab=net.grab, now=NOW)
        self.assertEqual(chart.status, "unmeasured")
        self.assertIn(ccv.MANIFEST_ARTIFACT, chart.reason)
        self.assertEqual(chart.run, "45108124169")

    def test_a_measured_plan_comes_back_as_a_map(self):
        net = self._net(manifest=_plan({"spa_core/tests/test_a.py": 4}))
        chart = ccv._shard_map_of_run("45108124169", fetch=net.fetch,
                                      grab=net.grab, now=NOW)
        self.assertTrue(chart.measured, chart.reason)
        self.assertEqual(chart.by_file, {"spa_core/tests/test_a.py": 4})


class TheArrivalThatMovedShardGetsTheTHIRDCode(unittest.TestCase):
    """Звено, ИЗМЕРЕННОЕ циклом #1219 и оставленное открытым заказом G1063 п. 2.

    Прежняя редакция возвращала **1** («гнаться за N именами») независимо от
    того, тасовались ли шарды. На живой паре 45091782823 → 45108124169 от ОДНОГО
    добавленного тест-файла переехало 1570 файлов из 3011, и переехали ВСЕ ТРИ
    настоящих пришедших имени. Код 0 соврал бы в сторону «чисто» (прямой запрет
    заказа G1064 п. 2), код 1 отдал бы следующему циклу фантом.
    """

    PREV, CURR = "45091782823", "45108124169"
    ARRIVAL = "spa_core/tests/test_new.py::test_it"

    def _code(self, *, prev_plan, curr_plan):
        rows_prev = [("spa_core/tests/test_old.py::test_x", "failed", 1)]
        rows_curr = rows_prev + [(self.ARRIVAL, "failed", 1)]
        nets = {}
        manifests = {}
        if prev_plan is not None:
            manifests[self.PREV] = _plan(prev_plan)
        if curr_plan is not None:
            manifests[self.CURR] = _plan(curr_plan)
        net = _Net([_run_row(self.PREV), _run_row(self.CURR)],
                   reports={self.PREV: _red_report(rows_prev),
                            self.CURR: _red_report(rows_curr)},
                   manifests=manifests)
        nets["net"] = net
        saved = (ccv.github_fetch, ccv.artifact_grab, ccv._keychain_token)
        ccv.github_fetch = lambda: net.fetch
        ccv.artifact_grab = lambda token=None: net.grab
        ccv._keychain_token = lambda: "сцена"
        try:
            return ccv.main(["--delta", self.PREV, self.CURR]), net
        finally:
            ccv.github_fetch, ccv.artifact_grab, ccv._keychain_token = saved

    def test_an_arrival_that_did_NOT_move_is_a_finding_code_one(self):
        code, _ = self._code(
            prev_plan={"spa_core/tests/test_old.py": 1,
                       "spa_core/tests/test_new.py": 7},
            curr_plan={"spa_core/tests/test_old.py": 1,
                       "spa_core/tests/test_new.py": 7})
        self.assertEqual(code, 1, "измеренная регрессия потеряла свой код")

    def test_an_arrival_that_MOVED_is_the_third_outcome_code_two(self):
        code, _ = self._code(
            prev_plan={"spa_core/tests/test_old.py": 1,
                       "spa_core/tests/test_new.py": 7},
            curr_plan={"spa_core/tests/test_old.py": 1,
                       "spa_core/tests/test_new.py": 11})
        self.assertEqual(code, 2, "«переехал» прочитан как вердикт, а не как "
                                  "третий исход — ось врёт в сторону «чисто» "
                                  "либо в сторону фантома")

    def test_a_missing_plan_is_the_third_outcome_too(self):
        code, _ = self._code(
            prev_plan=None,
            curr_plan={"spa_core/tests/test_old.py": 1,
                       "spa_core/tests/test_new.py": 11})
        self.assertEqual(code, 2)

    def test_the_door_asks_the_plan_of_BOTH_runs(self):
        """Иначе одна карта сравнивалась бы сама с собой, и переезд ИСЧЕЗ бы."""
        _, net = self._code(
            prev_plan={"spa_core/tests/test_old.py": 1,
                       "spa_core/tests/test_new.py": 7},
            curr_plan={"spa_core/tests/test_old.py": 1,
                       "spa_core/tests/test_new.py": 11})
        self.assertIn(f"https://api.example/{self.PREV}/manifest.zip", net.asked)
        self.assertIn(f"https://api.example/{self.CURR}/manifest.zip", net.asked)

    def test_no_arrival_at_all_stays_code_zero(self):
        rows = [("spa_core/tests/test_old.py::test_x", "failed", 1)]
        plan = _plan({"spa_core/tests/test_old.py": 1})
        net = _Net([_run_row(self.PREV), _run_row(self.CURR)],
                   reports={self.PREV: _red_report(rows),
                            self.CURR: _red_report(rows)},
                   manifests={self.PREV: plan, self.CURR: plan})
        saved = (ccv.github_fetch, ccv.artifact_grab, ccv._keychain_token)
        ccv.github_fetch = lambda: net.fetch
        ccv.artifact_grab = lambda token=None: net.grab
        ccv._keychain_token = lambda: "сцена"
        try:
            self.assertEqual(ccv.main(["--delta", self.PREV, self.CURR]), 0)
        finally:
            ccv.github_fetch, ccv.artifact_grab, ccv._keychain_token = saved


if __name__ == "__main__":
    unittest.main()
