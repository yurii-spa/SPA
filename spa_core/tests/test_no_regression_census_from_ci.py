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


def _record(tmp: Path, sha: str, *, outcomes: dict[str, str] | None = None) -> Path:
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
                "files": files, "tests_per_file": tests_per_file, "shards": shards}
    failures = [{"nodeid": n, "outcome": "failed", "shard": s, "msg": "boom"}
                for n, s in _CASES if outcomes.get(n) == "failed"]
    report = {"schema": census.CI_REPORT_SCHEMA,
              "verdict": "RED" if failures else "GREEN",
              "run": {"id": str(RUN_ID), "attempt": "1", "event": "schedule",
                      "url": f"https://github.com/{REPO}/actions/runs/{RUN_ID}"},
              "sha": sha, "env": env, "incomplete": [],
              "totals": {"population": len(population), "files": len(files),
                         "not_obtained": 0, "collect_errors": 0, "shards_planned": 2,
                         "shards_complete": 2},
              "failures": failures,
              "shards": [{"shard": i, "problems": []} for i in (0, 1)]}
    run = {"id": RUN_ID, "name": WF_NAME, "path": census.CI_WORKFLOW_PATH, "head_sha": sha,
           "event": "schedule", "status": "completed",
           "conclusion": "failure" if failures else "success",
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
    _write(rec / census.CI_REPORT_ARTIFACT / "report.json", report)
    for i in (0, 1):
        d = rec / f"ctl-shard-{i}"
        _write(d / "shard.json", {"shard": i})
        cases = [(n, outcomes.get(n, "passed")) for n, s in _CASES if s == i]
        (d / "junit.xml").write_text(_junit(cases, PLANNED + timedelta(minutes=1)),
                                     encoding="utf-8")
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
