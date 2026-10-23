# LLM_FORBIDDEN
"""§49 `No regression` из записи УЖЕ выполненного CI (`ci-control.yml`) — контроли в обе стороны.

Решение ARB 23.10: вердикт §49 выносит та же мерка
(:func:`no_regression_census.measure` по junit), а запись берётся у контрольного
прогона по шардам, не у pytest на Маке. Здесь проверяется ровно то, что мерка
спрашивать не обязана: ЭТА ли запись (репозиторий, воркфлоу, прогон), о ТОМ ли
коде (SHA плана/свода/шарда, дерево населения), ЦЕЛА ли (план · свод · артефакты ·
каталоги · junit согласованы, исход у каждого теста) и СВЕЖА ли (часы — вход).

Сцена — одноразовое git-дерево с тремя поверхностями и запись CI из двух шардов
в той форме, которую отдаёт GitHub (`run.json`, `artifacts.json`, каталоги
артефактов). Целый контур даёт вердикт мерки; каждая порча — отказ со СВОИМ
кодом причины, и ни одна не превращается ни в зелень, ни в сравнение с базой.
Время сцены отсчитывается от часов теста и подаётся проверяемому коду входом.
"""
from __future__ import annotations

import io
import json
import subprocess
import sys
import urllib.error
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from spa_core.monitoring import no_regression_census as census  # noqa: E402

REPO = census.CI_REPO
RUN_ID = 424242
WF_NAME = "SPA CI control (sharded full suite)"
# FROZEN-DATE-OK: injected-clock — якорь сцены; каждый вызов проверки/сборки получает now=NOW явно
# (чтение стенных часов на импорте запрещено test_no_import_time_clock_in_tests).
NOW = datetime(2026, 10, 23, 12, 0, 0, tzinfo=timezone.utc)
STARTED = NOW - timedelta(hours=2)
PLANNED = STARTED + timedelta(minutes=3)
FINISHED = STARTED + timedelta(minutes=40)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


# ───────────────────────────── сцена: дерево ────────────────────────────────

_FILES = {
    "tests/test_security_audit.py": "def test_secrets():\n    assert True\n",
    "spa_core/tests/test_agent_servers_bind_loopback.py": "def test_bind():\n    assert True\n",
    "spa_core/tests/test_scene_risk.py":
        "import spa_core.risk.policy\n\ndef test_a():\n    pass\n\ndef test_b():\n    pass\n",
    "spa_core/tests/test_scene_arch.py":
        "from spa_core.monitoring import architecture_conformance\n\ndef test_c():\n    pass\n",
    "spa_core/tests/test_scene_other.py": "def test_d():\n    pass\n",
    "scripts/tests/.keep": "",
    "spa_core/analytics/gross_of/.keep": "",
    "research/cards/.keep": "",
}

# nodeid → (файл, classname, имя, шард)
_CASES = [
    ("tests/test_security_audit.py::test_secrets", 0),
    ("spa_core/tests/test_agent_servers_bind_loopback.py::test_bind", 0),
    ("spa_core/tests/test_scene_risk.py::test_a", 0),
    ("spa_core/tests/test_scene_risk.py::test_b", 0),
    ("spa_core/tests/test_scene_arch.py::test_c", 1),
    ("spa_core/tests/test_scene_other.py::test_d", 1),
]


def _git(root: Path, *args: str) -> str:
    out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True,
                         check=True)
    return out.stdout.strip()


def _tree(tmp: Path) -> tuple[Path, str]:
    root = tmp / "tree"
    for rel, body in _FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", "main", str(root)], check=True)
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "add", "-A")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "scene")
    return root, _git(root, "rev-parse", "HEAD")


# ───────────────────────────── сцена: запись CI ─────────────────────────────

def _junit(cases: list[tuple[str, str]], when: datetime) -> str:
    """xunit2, как пишет наш CI: файла в атрибутах нет, только classname."""
    rows = []
    for nodeid, outcome in cases:
        path, name = nodeid.split("::")
        classname = path[:-3].replace("/", ".")
        inner = {"failed": '<failure message="boom">boom</failure>',
                 "skipped": '<skipped message="s"/>'}.get(outcome, "")
        rows.append(f'<testcase classname="{classname}" name="{name}" time="0.01">{inner}</testcase>')
    return ('<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest" '
            f'errors="0" failures="0" skipped="0" tests="{len(cases)}" '
            f'timestamp="{when.isoformat()}" hostname="runner">' + "".join(rows)
            + "</testsuite></testsuites>")


def _stream(cases: list[tuple[str, str]], when: datetime) -> str:
    """Потоковая запись шарда в форме `spa_core.ci.pytest_stream_record`."""
    t = when.timestamp()
    ev = [{"e": "session", "t": t}]
    for k, (nodeid, outcome) in enumerate(cases):
        ev.append({"e": "start", "n": nodeid, "t": t + k + 0.1})
        kind = {"failed": "fail", "skipped": "skip"}.get(outcome, "ok")
        row = {"e": kind, "n": nodeid, "d": 0.01, "t": t + k + 0.2}
        if kind == "fail":
            row.update(w="call", msg="boom")
        ev.append(row)
    ev.append({"e": "end", "status": 1 if any(o == "failed" for _, o in cases) else 0,
               "t": t + len(cases) + 1})
    return "".join(json.dumps(e) + "\n" for e in ev)


def _record(tmp: Path, sha: str, *, outcomes: dict[str, str] | None = None) -> Path:
    """Запись CI в форме, которую отдаёт GitHub; свод строит ДЕЙСТВУЮЩИЙ агрегатор.

    Каждый шард несёт то же, что настоящий (`ci-control.yml`, шаг run-shard):
    `shard.json`, `collected.jsonl`, `stream.jsonl`, `exit.json`, `junit.xml`; свод
    `report.json` собирает `ci_control.aggregate` — не рукописная копия, иначе сцена
    проверяла бы сверку со своей трактовкой, а не с контрактом CI.
    """
    outcomes = outcomes or {}
    rec = tmp / "record"
    rec.mkdir(parents=True, exist_ok=True)
    env = {"python": "3.11.17", "workflow": WF_NAME, "SPA_ENV": "ci", "PYTHONHASHSEED": "0"}
    population = [n for n, _ in _CASES]
    files = sorted({n.split("::")[0] for n in population})
    tests_per_file = {f: sum(1 for n in population if n.startswith(f + "::")) for f in files}
    shards = []
    for i in (0, 1):
        sh_files = sorted({n.split("::")[0] for n, s in _CASES if s == i})
        shards.append({"shard": i, "files": sh_files,
                       "tests": sum(1 for _, s in _CASES if s == i), "est_s": 1.0})
    manifest = {"schema": census.CI_MANIFEST_SCHEMA, "sha": sha, "created_at": _iso(PLANNED),
                "env": env, "population": len(population), "collected": population,
                "files": files, "tests_per_file": tests_per_file, "shards": shards,
                "collect_errors": []}
    run = {"id": RUN_ID, "name": WF_NAME, "path": census.CI_WORKFLOW_PATH, "head_sha": sha,
           "event": "schedule", "status": "completed",
           "conclusion": "failure" if any(o == "failed" for o in outcomes.values()) else "success",
           "created_at": _iso(STARTED), "run_started_at": _iso(STARTED),
           "updated_at": _iso(FINISHED), "run_attempt": 1,
           "html_url": f"https://github.com/{REPO}/actions/runs/{RUN_ID}",
           "repository": {"full_name": REPO}}
    names = [census.CI_REPORT_ARTIFACT, census.CI_MANIFEST_ARTIFACT, "ctl-shard-0", "ctl-shard-1"]
    arts = {"total_count": len(names), "artifacts": [
        {"id": 100 + k, "name": n, "expired": False, "size_in_bytes": 1,
         "archive_download_url": f"https://api.github.com/repos/{REPO}/actions/artifacts/{100 + k}/zip",
         "workflow_run": {"id": RUN_ID, "head_sha": sha}} for k, n in enumerate(names)]}
    _write(rec / census.CI_RUN_FILE, run)
    _write(rec / census.CI_ARTIFACTS_FILE, arts)
    _write(rec / census.CI_MANIFEST_ARTIFACT / "manifest.json", manifest)
    for i in (0, 1):
        d = rec / f"ctl-shard-{i}"
        _write(d / "shard.json", {"shard": i})
        cases = [(n, outcomes.get(n, "passed")) for n, s in _CASES if s == i]
        when = PLANNED + timedelta(minutes=1)
        (d / "collected.jsonl").write_text(
            json.dumps({"e": "collected", "count": len(cases),
                        "nodeids": [n for n, _ in cases]}) + "\n", encoding="utf-8")
        (d / "stream.jsonl").write_text(_stream(cases, when), encoding="utf-8")
        code = 1 if any(o == "failed" for _, o in cases) else 0
        _write(d / "exit.json", {"exit": code, "attempts": [
            {"attempt": 0, "exit": code, "session_end": True, "requested": None}],
            "crashes": [], "resumed": False, "remaining": None})
        (d / "junit.xml").write_text(_junit(cases, when), encoding="utf-8")
    report = census._ci_control().aggregate(
        manifest, rec, run={"id": str(RUN_ID), "attempt": "1", "event": "schedule",
                            "url": f"https://github.com/{REPO}/actions/runs/{RUN_ID}"})
    _write(rec / census.CI_REPORT_ARTIFACT / "report.json", report)
    return rec


def _write(path: Path, doc: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc), encoding="utf-8")


def _edit(path: Path, fn) -> None:
    doc = json.loads(path.read_text(encoding="utf-8"))
    fn(doc)
    path.write_text(json.dumps(doc), encoding="utf-8")


@pytest.fixture()
def scene(tmp_path):
    root, sha = _tree(tmp_path)
    rec = _record(tmp_path, sha)
    return root, sha, rec, tmp_path


def _measure(root, sha, rec, **kw):
    kw.setdefault("now", NOW)
    return census.measure_from_ci_record(str(rec), expected_sha=sha, repo_root=str(root), **kw)


def _refused(code, root, sha, rec, **kw):
    with pytest.raises(census.CIRecordRefused) as info:
        _measure(root, sha, rec, **kw)
    assert info.value.code == code, str(info.value)
    return info.value


# ───────────────────────────── целый контур ─────────────────────────────────

def test_whole_contour_green_is_the_verdict_of_the_measure(scene):
    root, sha, rec, _ = scene
    report = _measure(root, sha, rec, expected_run_id=RUN_ID)
    assert report["verdict"] == census.NO_REGRESSION
    assert report["population_total"] == 4 and report["unmeasured_total"] == 0
    assert len(report["records_read"]) == 2
    src = report["source"]
    assert (src["repo"], src["workflow"], src["run_id"], src["sha"]) == (
        REPO, census.CI_WORKFLOW_PATH, RUN_ID, sha)
    assert src["shards"] == [0, 1] and src["sha_binding"] == "run_head_sha"
    assert src["run_url"] == f"https://github.com/{REPO}/actions/runs/{RUN_ID}"
    # Возраст судится по времени ИСХОДА, а не сборки.
    assert report["generated_at"] == STARTED.isoformat()
    assert report["assembled_at"] != report["generated_at"]


def test_whole_contour_red_names_the_failing_member(tmp_path):
    root, sha = _tree(tmp_path)
    rec = _record(tmp_path, sha, outcomes={"spa_core/tests/test_scene_arch.py::test_c": "failed"})
    report = _measure(root, sha, rec)
    assert report["verdict"] == census.REGRESSION
    assert [f["file"] for f in report["failed"]] == ["spa_core/tests/test_scene_arch.py"]
    assert report["source"]["ci_verdict"] == "RED"


def test_failure_outside_the_population_does_not_redden_s49(tmp_path):
    """Красный CI ≠ красный §49: упавший тест вне трёх поверхностей вердикт не меняет."""
    root, sha = _tree(tmp_path)
    rec = _record(tmp_path, sha, outcomes={"spa_core/tests/test_scene_other.py::test_d": "failed"})
    report = _measure(root, sha, rec)
    assert report["source"]["ci_verdict"] == "RED"
    assert report["verdict"] == census.NO_REGRESSION


def test_all_skipped_member_stays_unmeasured_not_green(tmp_path):
    root, sha = _tree(tmp_path)
    rec = _record(tmp_path, sha, outcomes={"spa_core/tests/test_scene_arch.py::test_c": "skipped"})
    report = _measure(root, sha, rec)
    assert report["verdict"] == census.UNMEASURED
    assert report["unmeasured_members"][0]["kind"] == census.ALL_CASES_SKIPPED


# ───────────────────────────── чья запись ───────────────────────────────────

def test_foreign_repository(scene):
    root, sha, rec, _ = scene
    _edit(rec / "run.json", lambda d: d["repository"].update(full_name="evil/SPA"))
    _refused(census.CI_WRONG_REPOSITORY, root, sha, rec)


def test_foreign_workflow(scene):
    root, sha, rec, _ = scene
    _edit(rec / "run.json", lambda d: d.update(path=".github/workflows/ci.yml"))
    _refused(census.CI_WRONG_WORKFLOW, root, sha, rec)


def test_workflow_name_of_the_report_must_match_the_run(scene):
    root, sha, rec, _ = scene
    _edit(rec / "ci-control-report" / "report.json", lambda d: d["env"].update(workflow="SPA CI"))
    _refused(census.CI_WRONG_WORKFLOW, root, sha, rec)


def test_other_run_than_expected(scene):
    root, sha, rec, _ = scene
    _refused(census.CI_WRONG_RUN, root, sha, rec, expected_run_id=RUN_ID + 1)


def test_artifact_of_another_run(scene):
    root, sha, rec, _ = scene
    _edit(rec / "artifacts.json",
          lambda d: d["artifacts"][2]["workflow_run"].update(id=RUN_ID - 7))
    _refused(census.CI_WRONG_RUN, root, sha, rec)


def test_report_written_by_another_run(scene):
    root, sha, rec, _ = scene
    _edit(rec / "ci-control-report" / "report.json", lambda d: d["run"].update(id="1"))
    _refused(census.CI_WRONG_RUN, root, sha, rec)


def test_cancelled_run_is_not_an_answer(scene):
    root, sha, rec, _ = scene
    _edit(rec / "run.json", lambda d: d.update(conclusion="cancelled"))
    _refused(census.CI_RUN_NOT_FINISHED, root, sha, rec)


# ───────────────────────────── о каком коде ─────────────────────────────────

def test_foreign_sha_in_the_plan(scene):
    root, sha, rec, _ = scene
    other = "a" * 40
    _edit(rec / "ctl-manifest" / "manifest.json", lambda d: d.update(sha=other))
    _refused(census.CI_SHA_MISMATCH, root, sha, rec)


def test_report_and_plan_name_different_commits(scene):
    root, sha, rec, _ = scene
    _edit(rec / "ci-control-report" / "report.json", lambda d: d.update(sha="b" * 40))
    _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)


def test_scheduled_run_on_another_head_cannot_pin_a_commit(scene):
    root, sha, rec, _ = scene
    _edit(rec / "run.json", lambda d: d.update(head_sha="c" * 40))
    _edit(rec / "artifacts.json",
          lambda d: [a["workflow_run"].update(head_sha="c" * 40) for a in d["artifacts"]])
    _refused(census.CI_SHA_MISMATCH, root, sha, rec)


def test_dispatch_pins_a_commit_and_says_so(scene):
    """Замер 39871542027: run.head_sha — версия воркфлоу, проверялся вход inputs.sha."""
    root, sha, rec, _ = scene
    _edit(rec / "run.json", lambda d: d.update(head_sha="c" * 40, event="workflow_dispatch"))
    _edit(rec / "artifacts.json",
          lambda d: [a["workflow_run"].update(head_sha="c" * 40) for a in d["artifacts"]])
    report = _measure(root, sha, rec)
    assert report["source"]["sha"] == sha
    assert report["source"]["workflow_head_sha"] == "c" * 40
    assert report["source"]["sha_binding"] == "dispatch_input_pinned_by_manifest"


def test_shard_passport_naming_another_sha(scene):
    root, sha, rec, _ = scene
    _write(rec / "ctl-shard-1" / "shard.json", {"shard": 1, "sha": "d" * 40})
    _refused(census.CI_SHA_MISMATCH, root, sha, rec)


def test_population_tree_on_another_commit(scene):
    root, sha, rec, _ = scene
    (root / "spa_core/tests/test_scene_other.py").write_text("def test_d():\n    pass\n# x\n")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "moved")
    _refused(census.CI_TREE_MISMATCH, root, sha, rec)


def test_population_tree_dirty_in_the_test_roots(scene):
    root, sha, rec, _ = scene
    (root / "spa_core/tests/test_scene_new.py").write_text(
        "import spa_core.risk\n\ndef test_e():\n    pass\n")
    _refused(census.CI_TREE_MISMATCH, root, sha, rec)


# ───────────────────────────── цела ли запись ───────────────────────────────

def test_missing_shard_directory(scene):
    root, sha, rec, _ = scene
    import shutil
    shutil.rmtree(rec / "ctl-shard-1")
    _refused(census.CI_RECORD_INCOMPLETE, root, sha, rec)


def test_missing_shard_artifact_in_the_run(scene):
    root, sha, rec, _ = scene

    def drop(d):
        d["artifacts"] = [a for a in d["artifacts"] if a["name"] != "ctl-shard-0"]
        d["total_count"] = len(d["artifacts"])
    _edit(rec / "artifacts.json", drop)
    _refused(census.CI_RECORD_INCOMPLETE, root, sha, rec)


def test_truncated_artifact_listing(scene):
    root, sha, rec, _ = scene
    _edit(rec / "artifacts.json", lambda d: d.update(total_count=9))
    _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)


def test_broken_junit_xml(scene):
    root, sha, rec, _ = scene
    p = rec / "ctl-shard-0" / "junit.xml"
    p.write_text(p.read_text()[:120], encoding="utf-8")
    _refused(census.CI_RECORD_BROKEN, root, sha, rec)


def test_broken_report_json(scene):
    root, sha, rec, _ = scene
    (rec / "ci-control-report" / "report.json").write_text("{not json", encoding="utf-8")
    _refused(census.CI_RECORD_BROKEN, root, sha, rec)


def test_plan_and_report_disagree_on_shards(scene):
    root, sha, rec, _ = scene
    _edit(rec / "ci-control-report" / "report.json",
          lambda d: d["totals"].update(shards_planned=3))
    _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)


def test_report_lists_a_shard_the_plan_does_not_have(scene):
    root, sha, rec, _ = scene
    _edit(rec / "ci-control-report" / "report.json",
          lambda d: d["shards"].append({"shard": 2, "problems": []}))
    _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)


def test_incomplete_ci_verdict_is_not_an_answer(scene):
    root, sha, rec, _ = scene
    _edit(rec / "ci-control-report" / "report.json",
          lambda d: d.update(verdict="INCOMPLETE",
                             incomplete=[{"shard": 1, "reason": "сессия не дошла"}]))
    _refused(census.CI_RECORD_INCOMPLETE, root, sha, rec)


def test_not_obtained_tests_are_not_an_answer(scene):
    root, sha, rec, _ = scene
    _edit(rec / "ci-control-report" / "report.json", lambda d: d["totals"].update(not_obtained=1))
    _refused(census.CI_RECORD_INCOMPLETE, root, sha, rec)


def test_junit_short_of_a_test_is_incomplete(scene):
    """Авария на тесте пишется в потоковую запись, не в junit: файл выглядел бы зелёным."""
    root, sha, rec, _ = scene
    cases = [("spa_core/tests/test_scene_risk.py::test_a", "passed"),
             ("tests/test_security_audit.py::test_secrets", "passed"),
             ("spa_core/tests/test_agent_servers_bind_loopback.py::test_bind", "passed")]
    (rec / "ctl-shard-0" / "junit.xml").write_text(
        _junit(cases, PLANNED + timedelta(minutes=1)), encoding="utf-8")
    _refused(census.CI_RECORD_INCOMPLETE, root, sha, rec)


def test_junit_short_of_a_test_outside_the_population_is_incomplete(scene):
    """Свод говорит «не получено 0», а junit шарда несёт не всё — запись противоречива,
    даже если пропал тест ВНЕ трёх поверхностей (пофайловая сверка членов его не видит)."""
    root, sha, rec, _ = scene
    cases = [("spa_core/tests/test_scene_arch.py::test_c", "passed")]
    (rec / "ctl-shard-1" / "junit.xml").write_text(
        _junit(cases, PLANNED + timedelta(minutes=1)), encoding="utf-8")
    err = _refused(census.CI_RECORD_INCOMPLETE, root, sha, rec)
    assert "шарда 1" in err.reason


def test_junit_failure_count_must_match_the_report(scene):
    root, sha, rec, _ = scene
    cases = [(n, "failed" if n.endswith("test_c") else "passed") for n, s in _CASES if s == 1]
    (rec / "ctl-shard-1" / "junit.xml").write_text(
        _junit(cases, PLANNED + timedelta(minutes=1)), encoding="utf-8")
    _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)


def test_shard_directory_naming_itself_another_shard(scene):
    root, sha, rec, _ = scene
    _write(rec / "ctl-shard-1" / "shard.json", {"shard": 0})
    _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)


def test_junit_of_another_run_is_outside_the_run_window(scene):
    """Шард, подложенный из другого прогона с тем же планом: время записи вне окна прогона."""
    root, sha, rec, _ = scene
    cases = [(n, "passed") for n, s in _CASES if s == 1]
    (rec / "ctl-shard-1" / "junit.xml").write_text(
        _junit(cases, STARTED - timedelta(hours=1)), encoding="utf-8")
    _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)


def test_plan_outside_the_run_window(scene):
    root, sha, rec, _ = scene
    _edit(rec / "ctl-manifest" / "manifest.json",
          lambda d: d.update(created_at=_iso(STARTED - timedelta(days=1))))
    _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)


# ───────────────────────────── свежа ли ─────────────────────────────────────

def test_stale_record_by_the_injected_clock(scene):
    root, sha, rec, _ = scene
    limit = census.ci_max_age_h()
    _measure(root, sha, rec, now=STARTED + timedelta(hours=limit - 1))
    _refused(census.CI_RECORD_STALE, root, sha, rec, now=STARTED + timedelta(hours=limit + 1))


def test_freshness_limit_is_the_probe_limit():
    from spa_core.monitoring import card_acceptance
    assert census.ci_max_age_h() == card_acceptance._NO_REGRESSION_MAX_AGE_H


def test_record_from_the_future(scene):
    root, sha, rec, _ = scene
    _refused(census.CI_RECORD_TIME_UNREADABLE, root, sha, rec, now=STARTED - timedelta(hours=1))


def test_unreadable_run_time(scene):
    root, sha, rec, _ = scene
    _edit(rec / "run.json", lambda d: d.update(run_started_at="когда-то", created_at=None))
    _refused(census.CI_RECORD_TIME_UNREADABLE, root, sha, rec)


# ───────────────────────────── доступна ли ──────────────────────────────────

def test_no_record_directory(tmp_path):
    root, sha = _tree(tmp_path)
    _refused(census.CI_RECORD_UNAVAILABLE, root, sha, tmp_path / "nowhere")


def test_no_run_metadata(scene):
    root, sha, rec, _ = scene
    (rec / "run.json").unlink()
    _refused(census.CI_RECORD_UNAVAILABLE, root, sha, rec)


def test_shard_without_junit(scene):
    root, sha, rec, _ = scene
    (rec / "ctl-shard-0" / "junit.xml").unlink()
    _refused(census.CI_RECORD_UNAVAILABLE, root, sha, rec)


class _CutNetwork:
    def get_json(self, path):
        raise urllib.error.URLError("network is unreachable")

    def get_bytes(self, url):
        raise urllib.error.URLError("network is unreachable")


def test_network_cut_on_fetch(tmp_path):
    with pytest.raises(census.CIRecordRefused) as info:
        census.fetch_ci_record(str(tmp_path / "rec"), run_id=RUN_ID, http=_CutNetwork())
    assert info.value.code == census.CI_RECORD_UNAVAILABLE


def test_network_cut_on_run_lookup():
    with pytest.raises(census.CIRecordRefused) as info:
        census.find_ci_run(_CutNetwork(), head_sha="e" * 40)
    assert info.value.code == census.CI_RECORD_UNAVAILABLE


class _FakeGitHub:
    """Отдаёт запись сцены так, как её отдаёт API: JSON и zip-архивы артефактов."""

    def __init__(self, rec: Path, *, corrupt: str | None = None, digest: bool = True):
        import hashlib
        self.rec, self.blobs = rec, {}
        self.listing = json.loads((rec / "artifacts.json").read_text())
        for a in self.listing["artifacts"]:
            buf = io.BytesIO()
            with zipfile.ZipFile(buf, "w") as zf:
                for p in sorted((rec / a["name"]).rglob("*")):
                    if p.is_file():
                        zf.write(p, p.relative_to(rec / a["name"]).as_posix())
            blob = buf.getvalue()
            if corrupt == a["name"]:
                blob = blob[: len(blob) // 2]
            self.blobs[a["archive_download_url"]] = blob
            if digest:
                a["digest"] = "sha256:" + hashlib.sha256(buf.getvalue()).hexdigest()

    def get_json(self, path):
        if path.endswith("/artifacts?per_page=100"):
            return json.loads(json.dumps(self.listing))
        if "/runs?" in path:
            return {"workflow_runs": [json.loads((self.rec / "run.json").read_text())]}
        return json.loads((self.rec / "run.json").read_text())

    def get_bytes(self, url):
        return self.blobs[url]


def test_fetch_rebuilds_the_same_record(scene):
    root, sha, rec, tmp = scene
    gh = _FakeGitHub(rec)
    assert census.find_ci_run(gh, head_sha=sha) == RUN_ID
    got = census.fetch_ci_record(str(tmp / "fetched"), run_id=RUN_ID, http=gh, now=NOW)
    report = _measure(root, sha, got)
    assert report["verdict"] == census.NO_REGRESSION
    assert report["source"]["fetched_at"] == NOW.isoformat()
    assert all(a["digest"] for a in report["source"]["artifacts"])


def test_fetch_refuses_a_broken_archive(scene):
    root, sha, rec, tmp = scene
    gh = _FakeGitHub(rec, corrupt="ctl-shard-1", digest=False)
    with pytest.raises(census.CIRecordRefused) as info:
        census.fetch_ci_record(str(tmp / "fetched"), run_id=RUN_ID, http=gh)
    assert info.value.code == census.CI_RECORD_BROKEN


def test_fetch_refuses_bytes_that_do_not_match_the_digest(scene):
    root, sha, rec, tmp = scene
    gh = _FakeGitHub(rec)
    gh.listing["artifacts"][0]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(census.CIRecordRefused) as info:
        census.fetch_ci_record(str(tmp / "fetched"), run_id=RUN_ID, http=gh)
    assert info.value.code == census.CI_RECORD_BROKEN


def test_lookup_without_a_finished_run_is_unavailable(scene):
    root, sha, rec, _ = scene
    gh = _FakeGitHub(rec)
    with pytest.raises(census.CIRecordRefused) as info:
        census.find_ci_run(gh, head_sha="f" * 40)
    assert info.value.code == census.CI_RECORD_UNAVAILABLE


# ───────────────────────────── отказ не затирает ────────────────────────────

def _load_producer():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_refresh_s49_from_ci", _REPO / "scripts" / "refresh_no_regression_census.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_producer_writes_only_on_success_and_keeps_the_prior_report(scene, monkeypatch):
    root, sha, rec, tmp = scene
    mod = _load_producer()
    monkeypatch.delenv(mod.VIA_ENV, raising=False)
    out_root = tmp / "out"
    ok = mod.from_ci(root, out_root=out_root, sha=sha, run_id=RUN_ID, record_dir=rec, now=NOW)
    target = out_root / census.REPORT_REL
    written = target.read_bytes()
    doc = json.loads(written)
    assert doc["verdict"] == census.NO_REGRESSION and ok["written"] == str(target)
    inv = doc["invoked_by"]
    assert inv["entry"] == mod.CI_ENTRY and inv["env"]["via"] == "manual"
    assert inv["source"]["run_id"] == RUN_ID and inv["sha"] == sha

    # Порча: запись CI о чужом коммите. Отказ — отдельным файлом, отчёт байт-в-байт цел.
    _edit(rec / "ctl-manifest" / "manifest.json", lambda d: d.update(sha="a" * 40))
    with pytest.raises(mod.NotMeasured):
        mod.from_ci(root, out_root=out_root, sha=sha, run_id=RUN_ID, record_dir=rec, now=NOW)
    assert target.read_bytes() == written
    refusals = sorted((out_root / mod.RECORDS_REL).glob("*.refusal.json"))
    assert len(refusals) == 1
    refusal = json.loads(refusals[0].read_text())
    assert refusal["code"] == census.CI_SHA_MISMATCH and refusal["live_report_untouched"] is True


def test_producer_marks_the_agent_run_by_its_wrapper_label(scene, monkeypatch):
    root, sha, rec, tmp = scene
    mod = _load_producer()
    monkeypatch.setenv(mod.VIA_ENV, "launchd:com.spa.no_regression_census")
    mod.from_ci(root, out_root=tmp / "out", sha=sha, run_id=RUN_ID, record_dir=rec, now=NOW)
    doc = json.loads((tmp / "out" / census.REPORT_REL).read_text())
    assert doc["invoked_by"]["env"]["via"] == "launchd:com.spa.no_regression_census"


def test_producer_cli_requires_an_explicit_out_root(scene, capsys):
    mod = _load_producer()
    assert mod._main(["--from-ci", "--sha", "0" * 40]) == 2
    assert "--out-root" in capsys.readouterr().out


def test_schema_constants_match_ci_control():
    import importlib.util
    spec = importlib.util.spec_from_file_location("_ctl_for_s49", _REPO / "scripts" / "ci_control.py")
    ctl = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(ctl)
    assert census.CI_REPORT_SCHEMA == ctl.REPORT_SCHEMA
    assert census.CI_MANIFEST_SCHEMA == ctl.MANIFEST_SCHEMA
    assert census.CI_SHARD_PREFIX == ctl.SHARD_DIR_PREFIX
    assert set(census._CI_MEASURED_VERDICTS) == {ctl.GREEN, ctl.RED}
    wf = (_REPO / census.CI_WORKFLOW_PATH).read_text(encoding="utf-8")
    for name in (census.CI_REPORT_ARTIFACT, census.CI_MANIFEST_ARTIFACT):
        assert f"name: {name}" in wf
    assert "name: ctl-shard-${{ matrix.shard }}" in wf



class _Runs:
    def __init__(self, runs):
        self.runs = runs

    def get_json(self, path):
        return {"workflow_runs": self.runs}


def test_lookup_prefers_the_scheduled_run_of_that_head():
    """Ручной прогон того же head мог закрепить другой коммит — расписанный берётся первым."""
    head = "e" * 40
    runs = [{"id": 1, "head_sha": head, "event": "schedule", "conclusion": "failure",
             "created_at": _iso(NOW - timedelta(days=3))},
            {"id": 2, "head_sha": head, "event": "workflow_dispatch", "conclusion": "success",
             "created_at": _iso(NOW - timedelta(days=2))},
            {"id": 3, "head_sha": head, "event": "schedule", "conclusion": "cancelled",
             "created_at": _iso(NOW - timedelta(days=1))}]
    assert census.find_ci_run(_Runs(runs), head_sha=head) == 1
    assert census.find_ci_run(_Runs(runs[1:]), head_sha=head) == 2


# ──────────── поимённая целостность записи (воспроизведения ARB 23.10) ───────────
#
# Обе порчи сохраняют манифест, свод, времена, число случаев и число падений —
# по числам запись неотличима от целой. До поимённой сверки обе давали
# NO_REGRESSION: первая — при `source.ci_verdict == "RED"`, вторая — принимала
# запись как полную.

_ARB_C = 'classname="spa_core.tests.test_scene_arch" name="test_c"'
_ARB_D = 'classname="spa_core.tests.test_scene_other" name="test_d"'


def _swap_identities(rec: Path) -> None:
    """Поменять местами ТОЛЬКО атрибуты name/classname двух случаев шарда 1."""
    p = rec / "ctl-shard-1" / "junit.xml"
    text = p.read_text(encoding="utf-8")
    assert _ARB_C in text and _ARB_D in text
    p.write_text(text.replace(_ARB_C, "\0").replace(_ARB_D, _ARB_C).replace("\0", _ARB_D),
                 encoding="utf-8")


def _second_copy_of_test_a(rec: Path) -> None:
    """В шарде 0 заменить идентичность test_b вторым экземпляром test_a."""
    p = rec / "ctl-shard-0" / "junit.xml"
    text = p.read_text(encoding="utf-8")
    b = 'classname="spa_core.tests.test_scene_risk" name="test_b"'
    assert b in text
    p.write_text(text.replace(b, 'classname="spa_core.tests.test_scene_risk" name="test_a"'),
                 encoding="utf-8")


def test_arb_repro_swapped_identities_are_refused_not_green(tmp_path):
    root, sha = _tree(tmp_path)
    rec = _record(tmp_path, sha, outcomes={"spa_core/tests/test_scene_arch.py::test_c": "failed"})
    assert _measure(root, sha, rec)["verdict"] == census.REGRESSION      # положительный контроль
    _swap_identities(rec)
    err = _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)
    assert "test_scene_arch.py::test_c" in err.reason or "test_scene_other.py::test_d" in err.reason


def test_arb_repro_second_copy_of_a_test_is_refused_not_complete(scene):
    root, sha, rec, _ = scene
    _second_copy_of_test_a(rec)
    err = _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)
    assert "test_scene_risk.py::test_a" in err.reason and "дважды" in err.reason


def test_swap_of_two_cases_with_the_same_outcome_is_harmless_and_accepted(scene):
    """Обмен имён двух ЗЕЛЁНЫХ случаев одного шарда исходов не меняет — сверка
    не выдумывает порчу там, где каждый случай по-прежнему назван со своим исходом."""
    root, sha, rec, _ = scene
    _swap_identities(rec)
    assert _measure(root, sha, rec)["verdict"] == census.NO_REGRESSION


def test_a_case_of_another_shard_is_refused(scene):
    root, sha, rec, _ = scene
    p0, p1 = rec / "ctl-shard-0" / "junit.xml", rec / "ctl-shard-1" / "junit.xml"
    t0, t1 = p0.read_text(encoding="utf-8"), p1.read_text(encoding="utf-8")
    row = t1[t1.index("<testcase " + _ARB_D):]
    row = row[: row.index("</testcase>") + len("</testcase>")]
    p1.write_text(t1.replace(row, ""), encoding="utf-8")
    p0.write_text(t0.replace("</testsuite>", row + "</testsuite>"), encoding="utf-8")
    err = _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)
    assert "принадлежит плану шарда 1" in err.reason


def test_a_case_outside_the_plan_is_refused(scene):
    root, sha, rec, _ = scene
    p = rec / "ctl-shard-0" / "junit.xml"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "</testsuite>", '<testcase classname="spa_core.tests.test_ghost" name="test_x" '
                        'time="0.01"></testcase></testsuite>'), encoding="utf-8")
    err = _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)
    assert "в плане прогона отсутствует" in err.reason


def test_crash_markers_in_a_measured_attempt_are_not_tolerated(scene):
    """`pytest::internal` допустим только у аварийной попытки."""
    root, sha, rec, _ = scene
    p = rec / "ctl-shard-0" / "junit.xml"
    p.write_text(p.read_text(encoding="utf-8").replace(
        "</testsuite>", '<testcase classname="pytest" name="internal" time="0.0">'
                        '<error message="internal error"/></testcase></testsuite>'),
        encoding="utf-8")
    _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)


def test_report_not_reproducible_from_the_shard_records_is_refused(scene):
    """Поток говорит «упал», свод записан зелёным: свод о своих записях не говорит."""
    root, sha, rec, _ = scene
    p = rec / "ctl-shard-1" / "stream.jsonl"
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines()]
    for r in rows:
        if r.get("n", "").endswith("test_d") and r["e"] == "ok":
            r.update(e="fail", w="call", msg="boom")
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    err = _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)
    assert "не воспроизводится" in err.reason


def test_report_naming_a_failure_its_shards_do_not_have_is_refused(scene):
    """Записи шардов целы и согласны друг с другом, неверен ТОЛЬКО свод: он называет
    упавшим тест вне населения. Поимённая сверка JUnit↔поток этого не видит — свод из
    записей не воспроизводится, и это отказ, а не «вне населения, значит неважно»."""
    root, sha, rec, _ = scene
    d = "spa_core/tests/test_scene_other.py::test_d"

    def lie(doc):
        doc["verdict"] = "RED"
        doc["failures"].append({"nodeid": d, "outcome": "failed", "shard": 1, "msg": "boom"})
        doc["non_passed"][d] = "failed"
        doc["totals"]["failed"] += 1
        doc["totals"]["passed"] -= 1
    _edit(rec / "ci-control-report" / "report.json", lie)
    err = _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)
    assert "не воспроизводится" in err.reason


def test_report_calling_a_passed_test_skipped_is_refused(scene):
    """Свод врёт без единого упавшего: зелёный тест записан пропущенным."""
    root, sha, rec, _ = scene
    d = "spa_core/tests/test_scene_other.py::test_d"

    def lie(doc):
        doc["non_passed"][d] = "skipped"
        doc["totals"]["skipped"] += 1
        doc["totals"]["passed"] -= 1
    _edit(rec / "ci-control-report" / "report.json", lie)
    err = _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)
    assert "не воспроизводится" in err.reason


def test_report_attributing_a_failure_to_another_shard_is_refused(tmp_path):
    """Имя и исход верны, а шард — чужой: принадлежность шарду тоже часть записи."""
    root, sha = _tree(tmp_path)
    rec = _record(tmp_path, sha, outcomes={"spa_core/tests/test_scene_arch.py::test_c": "failed"})
    _edit(rec / "ci-control-report" / "report.json", lambda d: d["failures"][0].update(shard=0))
    err = _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)
    assert "перечень упавших" in err.reason


def _resumed_shard_0(rec: Path, *, junit_of_crash: bool) -> None:
    """Шард 0 с аварией pytest на test_a и штатным доигрыванием (`run-shard`).

    Попытка 0: test_secrets, test_bind — исход; на test_a pytest умер (код 3);
    `run-shard` дописал синтетическую ошибку `w="internal"`. Попытка 1 доиграла
    test_b. JUnit аварийной попытки — с двумя служебными случаями (замер f4b098,
    шард 10) или вовсе без файла (процесс убит).
    """
    d = rec / "ctl-shard-0"
    when = PLANNED + timedelta(minutes=1)
    t = when.timestamp()
    a = "spa_core/tests/test_scene_risk.py::test_a"
    b = "spa_core/tests/test_scene_risk.py::test_b"
    first = [("tests/test_security_audit.py::test_secrets", "passed"),
             ("spa_core/tests/test_agent_servers_bind_loopback.py::test_bind", "passed")]
    ev = [{"e": "session", "t": t}]
    for k, (n, _o) in enumerate(first):
        ev += [{"e": "start", "n": n, "t": t + k}, {"e": "ok", "n": n, "d": 0.0, "t": t + k + .1}]
    ev += [{"e": "start", "n": a, "t": t + 5},
           {"e": "fail", "n": a, "w": "internal", "d": 0.0, "t": t + 6, "msg": "pytest internal error"},
           {"e": "session", "t": t + 7},
           {"e": "start", "n": b, "t": t + 8}, {"e": "ok", "n": b, "d": 0.0, "t": t + 9},
           {"e": "end", "status": 0, "t": t + 10}]
    (d / "stream.jsonl").write_text("".join(json.dumps(e) + "\n" for e in ev), encoding="utf-8")
    _write(d / "exit.json", {"exit": 1, "attempts": [
        {"attempt": 0, "exit": 3, "session_end": True, "requested": None},
        {"attempt": 1, "exit": 0, "session_end": True, "requested": 1}],
        "crashes": [{"attempt": 0, "exit": 3, "session_end": True, "tests": [a]}],
        "resumed": True, "remaining": 0})
    j0 = _junit(first, when).replace(
        "</testsuite>", '<testcase time="0.001"></testcase><testcase classname="pytest" '
                        'name="internal" time="0.0"><error message="internal error"/></testcase>'
                        "</testsuite>")
    if junit_of_crash:
        (d / "junit.xml").write_text(j0, encoding="utf-8")
    else:
        (d / "junit.xml").unlink()
    (d / "junit-resume-1.xml").write_text(_junit([(b, "passed")], when), encoding="utf-8")
    report = census._ci_control().aggregate(
        json.loads((rec / "ctl-manifest" / "manifest.json").read_text(encoding="utf-8")), rec,
        run={"id": str(RUN_ID), "attempt": "1", "event": "schedule",
             "url": f"https://github.com/{REPO}/actions/runs/{RUN_ID}"})
    _write(rec / "ci-control-report" / "report.json", report)
    _edit(rec / "run.json", lambda r: r.update(conclusion="failure"))


def test_resumed_shard_is_accepted_and_the_crashed_test_is_a_named_regression(scene):
    """Положительный контроль доигрывания: запись цела, тест аварии — поломка по имени."""
    root, sha, rec, _ = scene
    _resumed_shard_0(rec, junit_of_crash=True)
    report = _measure(root, sha, rec)
    assert report["verdict"] == census.REGRESSION
    assert report["source"]["ci_verdict"] == "RED"
    bad = [c["case"] for f in report["failed"] for c in f["cases"]]
    assert bad == ["spa_core/tests/test_scene_risk.py::test_a"]
    integ = report["source"]["record_integrity"]
    assert integ == {"cases": 6, "confirmed_by_junit": 5, "stream_only_after_crash": 0,
                     "crash_markers": 2}


def test_killed_attempt_without_junit_is_counted_as_stream_only(scene):
    root, sha, rec, _ = scene
    _resumed_shard_0(rec, junit_of_crash=False)
    integ = _measure(root, sha, rec)["source"]["record_integrity"]
    assert integ["stream_only_after_crash"] == 3 and integ["confirmed_by_junit"] == 3


def test_resumed_shard_with_a_second_copy_is_still_refused(scene):
    root, sha, rec, _ = scene
    _resumed_shard_0(rec, junit_of_crash=True)
    p = rec / "ctl-shard-0" / "junit-resume-1.xml"
    p.write_text(p.read_text(encoding="utf-8").replace(
        'name="test_b"', 'name="test_a"'), encoding="utf-8")
    _refused(census.CI_RECORD_INCONSISTENT, root, sha, rec)


def test_a_valid_digest_does_not_vouch_for_the_unpacked_record(tmp_path):
    """Дайджест подтверждает байты архива, а не согласованность распакованной записи:
    испорченная ДО упаковки запись скачивается с верным дайджестом и всё равно отказ."""
    root, sha = _tree(tmp_path)
    rec = _record(tmp_path, sha, outcomes={"spa_core/tests/test_scene_arch.py::test_c": "failed"})
    _swap_identities(rec)
    gh = _FakeGitHub(rec)                       # дайджест посчитан по испорченным байтам
    got = census.fetch_ci_record(str(tmp_path / "fetched"), run_id=RUN_ID, http=gh, now=NOW)
    assert all(a.get("digest") for a in json.loads((got / "artifacts.json").read_text())["artifacts"])
    _refused(census.CI_RECORD_INCONSISTENT, root, sha, got)


def test_refusal_on_a_corrupted_record_keeps_the_prior_report(tmp_path, monkeypatch):
    root, sha = _tree(tmp_path)
    rec = _record(tmp_path, sha, outcomes={"spa_core/tests/test_scene_arch.py::test_c": "failed"})
    mod = _load_producer()
    monkeypatch.delenv(mod.VIA_ENV, raising=False)
    out_root = tmp_path / "out"
    mod.from_ci(root, out_root=out_root, sha=sha, run_id=RUN_ID, record_dir=rec, now=NOW)
    target = out_root / census.REPORT_REL
    written = target.read_bytes()
    assert json.loads(written)["verdict"] == census.REGRESSION
    _swap_identities(rec)
    with pytest.raises(mod.NotMeasured):
        mod.from_ci(root, out_root=out_root, sha=sha, run_id=RUN_ID, record_dir=rec, now=NOW)
    assert target.read_bytes() == written
    refusal = sorted((out_root / mod.RECORDS_REL).glob("*.refusal.json"))[-1]
    doc = json.loads(refusal.read_text(encoding="utf-8"))
    assert doc["code"] == census.CI_RECORD_INCONSISTENT and doc["live_report_untouched"] is True


def test_the_identity_rule_is_pytests_own_mangling():
    assert census.junit_key("spa_core/tests/test_x.py::TestA::test_b[p-1::2]") == (
        "spa_core.tests.test_x.TestA", "test_b[p-1::2]")
    assert census.junit_key("tests/test_y.py::test_z") == ("tests.test_y", "test_z")


# ───────────── привязка отчёта к ревизии у конечного потребителя (ARB) ───────────

def _probe(report, root):
    from spa_core.monitoring import card_acceptance as ca
    return ca._probe_no_regression_tests_pass(None, now=NOW, repo_root=str(root), report=report)


def test_arb_repro_report_of_the_old_sha_is_not_counted_for_a_new_commit(scene):
    """Воспроизведение ARB: тот же отчёт, новый коммит с прежним населением."""
    from spa_core.monitoring import card_acceptance as ca
    root, sha, rec, _ = scene
    report = _measure(root, sha, rec)
    verdict, detail = _probe(report, root)
    assert verdict == ca.SATISFIED, detail                 # положительный контроль
    p = root / "tests/test_security_audit.py"
    p.write_text(p.read_text(encoding="utf-8").replace("assert True", "assert False"),
                 encoding="utf-8")
    _git(root, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qam", "break it")
    verdict, detail = _probe(report, root)
    assert verdict == ca.UNMEASURED and "за другую ревизию" in detail, detail
    assert sha[:12] in detail


def test_uncommitted_edit_of_a_checked_source_is_unmeasured(scene):
    from spa_core.monitoring import card_acceptance as ca
    root, sha, rec, _ = scene
    report = _measure(root, sha, rec)
    p = root / "tests/test_security_audit.py"
    p.write_text(p.read_text(encoding="utf-8").replace("assert True", "assert False"),
                 encoding="utf-8")
    verdict, detail = _probe(report, root)
    assert verdict == ca.UNMEASURED and "изменено после коммита" in detail, detail
    assert "tests/test_security_audit.py" in detail


def test_workflow_sha_is_not_the_checked_revision(scene):
    """Дисп-прогон: воркфлоу с другого коммита, код — закреплённый. Засчитывается код."""
    from spa_core.monitoring import card_acceptance as ca
    root, sha, rec, _ = scene
    _edit(rec / "run.json", lambda d: d.update(head_sha="c" * 40, event="workflow_dispatch"))
    _edit(rec / "artifacts.json",
          lambda d: [a["workflow_run"].update(head_sha="c" * 40) for a in d["artifacts"]])
    report = _measure(root, sha, rec)
    verdict, detail = _probe(report, root)
    assert verdict == ca.SATISFIED and "воркфлоу cccccccccccc" in detail, detail
    forged = json.loads(json.dumps(report))
    forged["source"]["sha"] = "c" * 40                     # подставить версию воркфлоу
    verdict, detail = _probe(forged, root)
    assert verdict == ca.UNMEASURED, detail


def test_report_without_a_named_revision_is_unmeasured(scene):
    from spa_core.monitoring import card_acceptance as ca
    root, sha, rec, _ = scene
    report = _measure(root, sha, rec)
    bare = json.loads(json.dumps(report))
    bare["source"].pop("sha")
    verdict, detail = _probe(bare, root)
    assert verdict == ca.UNMEASURED and "не называет проверяемую ревизию" in detail, detail
    local = {k: v for k, v in report.items() if k not in ("tree_revision", "source")}
    verdict, detail = _probe(local, root)
    assert verdict == ca.UNMEASURED and "не называет проверяемую ревизию" in detail, detail


def test_judged_directory_without_git_is_unmeasured(scene, tmp_path):
    from spa_core.monitoring import card_acceptance as ca
    import shutil
    root, sha, rec, _ = scene
    report = _measure(root, sha, rec)
    plain = tmp_path / "plain_copy"
    shutil.copytree(root, plain, ignore=shutil.ignore_patterns(".git"))
    verdict, detail = _probe(report, plain)
    assert verdict == ca.UNMEASURED and "ревизия судимого дерева не измерена" in detail, detail


def test_untracked_new_source_outside_the_population_is_unmeasured(scene):
    """Новый неотслеживаемый исходник (не тест): населения не меняет, а код меняет."""
    from spa_core.monitoring import card_acceptance as ca
    root, sha, rec, _ = scene
    report = _measure(root, sha, rec)
    (root / "spa_core" / "helper_new.py").write_text("X = 1\n", encoding="utf-8")
    verdict, detail = _probe(report, root)
    assert verdict == ca.UNMEASURED and "spa_core/helper_new.py" in detail, detail


def test_a_directory_inside_another_repository_has_no_revision_of_its_own(scene, tmp_path):
    root, sha, rec, _ = scene
    inner = root / "nested_not_a_repo"
    inner.mkdir()
    rev = census.tree_revision(str(inner))
    assert rev["sha"] is None and "сам им не является" in rev["reason"]


def test_report_measured_on_a_dirty_tree_of_the_same_sha_is_unmeasured(tmp_path):
    """Замер снят на дереве той же вершины, но с правкой: о коммите он не говорит,
    даже если правку потом откатили и судимое дерево чисто."""
    from spa_core.monitoring import card_acceptance as ca
    from spa_core.monitoring import no_regression_census as nrc
    root, sha = _tree(tmp_path)
    rec = _record(tmp_path, sha)
    p = root / "tests/test_security_audit.py"
    original = p.read_text(encoding="utf-8")
    p.write_text(original.replace("assert True", "assert False"), encoding="utf-8")
    local = nrc.measure(str(root), record=census.read_record(
        [str(rec / "ctl-shard-0" / "junit.xml"), str(rec / "ctl-shard-1" / "junit.xml")],
        repo_root=str(root)))
    p.write_text(original, encoding="utf-8")
    assert local["tree_revision"]["sha"] == sha and local["tree_revision"]["clean"] is False
    local["generated_at"] = (NOW - timedelta(hours=1)).isoformat()
    verdict, detail = _probe(local, root)
    assert verdict == ca.UNMEASURED and "снят не на целом дереве" in detail, detail
