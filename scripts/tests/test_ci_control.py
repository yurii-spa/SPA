# LLM_FORBIDDEN
"""Контроли на контрольный прогон по шардам (`scripts/ci_control.py`, `ci-control.yml`).

Каждый контроль — в обе стороны (`.claude/rules/deployment.md`, «Проверка сторожа
сторожей»): целый контур даёт GREEN/RED, а каждое порванное звено — INCOMPLETE с НАЗВАННОЙ
причиной. Порванные звенья взяты из замера 2026-10-16, а не придуманы:

* шард, снятый пределом времени (как джоба 116884127339 на `[ 94%]`), — запись без `end`,
  без кода возврата;
* шард, не отчитавшийся вовсе (отменён до старта) — артефакта нет;
* союз шардов ≠ населению — «зелёный ПОДНАБОР» под видом зелёного набора;
* `needs.shards.result == cancelled` — ответа нет, даже если файлы на месте.

Последняя группа гоняет ЖИВОЙ pytest с обоими плагинами на одноразовой сцене: рукописная
фикстура доказывает поведение свода, живая — что он читает настоящую форму записи.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPT = _REPO_ROOT / "scripts" / "ci_control.py"
_WORKFLOW = _REPO_ROOT / ".github" / "workflows" / "ci-control.yml"


def _load():
    spec = importlib.util.spec_from_file_location("_ci_control_under_test", _SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


cc = _load()

POP = [
    "tests/test_a.py::test_1", "tests/test_a.py::test_2",
    "tests/test_b.py::test_1",
    "spa_core/tests/test_c.py::T::test_1", "spa_core/tests/test_c.py::T::test_2",
]
WEIGHTS = {"files": {"tests/test_a.py": 10.0, "tests/test_b.py": 1.0}, "per_test_fallback_s": 0.5}


def _manifest(shards: int = 2, population=None, collect_errors=None) -> dict:
    population = list(POP if population is None else population)
    plan = cc.make_plan(population, collect_errors or [], WEIGHTS, shards, 3600.0)
    return {"schema": cc.MANIFEST_SCHEMA, "sha": "abc123", "env": {"python": "3.11.9"},
            "roots": ["tests", "spa_core/tests"], "population": len(population),
            "collected": population, "collect_errors": collect_errors or [], **plan}


def _write_shard(root: Path, manifest: dict, i: int, *, outcomes: dict | None = None,
                 end: bool = True, exit_code: int | None = 0, collected: bool = True,
                 stream: bool = True, extra_collected=()) -> Path:
    """Записи шарда в ровно той форме, что пишут плагины и шаг воркфлоу."""
    d = root / f"{cc.SHARD_DIR_PREFIX}{i}"
    d.mkdir(parents=True, exist_ok=True)
    (d / cc.SHARD_FILE).write_text(json.dumps({"shard": i}), encoding="utf-8")
    files = manifest["shards"][i]["files"]
    nodes = [n for n in manifest["collected"] if cc.file_of(n) in files]
    outcomes = outcomes or {}
    if collected:
        (d / cc.COLLECTED_FILE).write_text(json.dumps(
            {"e": "collected", "count": len(nodes) + len(extra_collected),
             "nodeids": nodes + list(extra_collected)}) + "\n", encoding="utf-8")
    if stream:
        lines = [{"e": "session", "t": 100.0}]
        t = 100.0
        for n in nodes:
            t += 1
            lines.append({"e": "start", "n": n, "t": t})
            o = outcomes.get(n, "ok")
            if o is None:
                continue                                  # начался и не кончился
            if o == "ok":
                lines.append({"e": "ok", "n": n, "t": t + 0.5, "d": 0.5})
            elif o == "skip":
                lines.append({"e": "skip", "n": n, "w": "setup", "t": t + 0.5})
            else:
                lines.append({"e": "fail", "n": n, "w": o, "t": t + 0.5, "d": 0.5,
                              "msg": f"boom {n}"})
        if end:
            lines.append({"e": "end", "t": t + 1, "status": exit_code or 0})
        (d / cc.STREAM_FILE).write_text("\n".join(json.dumps(x) for x in lines) + "\n",
                                        encoding="utf-8")
    if exit_code is not None:
        (d / cc.EXIT_FILE).write_text(json.dumps({"exit": exit_code}), encoding="utf-8")
    return d


def _healthy(tmp_path: Path, shards: int = 2) -> tuple[dict, Path]:
    m = _manifest(shards)
    root = tmp_path / "shards"
    for i in range(shards):
        _write_shard(root, m, i)
    return m, root


def _reasons(report: dict) -> str:
    return " | ".join(f"{x['shard']}:{x['reason']}" for x in report["incomplete"])


# ── план ─────────────────────────────────────────────────────────────────────

def test_plan_union_equals_population_and_is_disjoint():
    m = _manifest(3)
    listed = [f for sh in m["shards"] for f in sh["files"]]
    assert sorted(listed) == sorted(m["files"])
    assert len(listed) == len(set(listed))


def test_plan_is_deterministic_and_keeps_collection_order_inside_a_shard():
    a = cc.make_plan(POP, [], WEIGHTS, 2, 3600.0)
    b = cc.make_plan(list(POP), [], dict(WEIGHTS), 2, 3600.0)
    assert a == b
    order = a["files"]
    for sh in a["shards"]:
        assert sh["files"] == [f for f in order if f in sh["files"]]


def test_plan_puts_the_heaviest_file_alone_and_estimates_unmeasured_ones():
    p = cc.make_plan(POP, [], WEIGHTS, 2, 3600.0)
    heavy = [sh for sh in p["shards"] if "tests/test_a.py" in sh["files"]][0]
    assert heavy["files"] == ["tests/test_a.py"]
    assert p["estimated_files"] == 1                    # spa_core/tests/test_c.py — оценён по числу тестов


def test_plan_over_budget_is_reported_not_hidden():
    p = cc.make_plan(POP, [], WEIGHTS, 1, 5.0)
    assert p["within_budget"] is False


def test_plan_includes_a_file_that_failed_to_collect():
    errs = [{"n": "tests/test_broken.py", "msg": "ImportError"}]
    p = cc.make_plan(POP, errs, WEIGHTS, 2, 3600.0)
    assert "tests/test_broken.py" in [f for sh in p["shards"] for f in sh["files"]]


def test_cmd_plan_refuses_without_a_finished_collection(tmp_path):
    col = tmp_path / "collected.jsonl"
    col.write_text(json.dumps({"e": "collect_error", "n": "x.py", "msg": "m"}) + "\n")
    w = tmp_path / "w.json"
    w.write_text(json.dumps(WEIGHTS))
    code = cc.main(["plan", "--collected", str(col), "--weights", str(w), "--shards", "2",
                    "--budget-min", "60", "--sha", "s", "--roots", "tests",
                    "--out-dir", str(tmp_path / "out")])
    assert code == 2


def test_cmd_plan_refuses_an_empty_population(tmp_path):
    col = tmp_path / "collected.jsonl"
    col.write_text(json.dumps({"e": "collected", "count": 0, "nodeids": []}) + "\n")
    w = tmp_path / "w.json"
    w.write_text(json.dumps(WEIGHTS))
    code = cc.main(["plan", "--collected", str(col), "--weights", str(w), "--shards", "2",
                    "--budget-min", "60", "--sha", "s", "--roots", "tests",
                    "--out-dir", str(tmp_path / "out")])
    assert code == 2


# ── свод: целый контур ───────────────────────────────────────────────────────

def test_complete_healthy_run_is_green(tmp_path):
    m, root = _healthy(tmp_path)
    r = cc.aggregate(m, root, "success")
    assert r["verdict"] == cc.GREEN, _reasons(r)
    assert r["totals"]["passed"] == len(POP)
    assert r["totals"]["shards_complete"] == 2


def test_failures_are_named_with_their_shard_and_make_red(tmp_path):
    m = _manifest(2)
    root = tmp_path / "shards"
    bad = "tests/test_b.py::test_1"
    owner = [sh["shard"] for sh in m["shards"] if "tests/test_b.py" in sh["files"]][0]
    for i in range(2):
        out = {bad: "call"} if i == owner else {}
        _write_shard(root, m, i, outcomes=out, exit_code=1 if i == owner else 0)
    r = cc.aggregate(m, root, "failure")
    assert r["verdict"] == cc.RED, _reasons(r)
    assert r["failures"] == [{"nodeid": bad, "outcome": cc.FAILED, "shard": owner,
                              "msg": f"boom {bad}"}]


def test_setup_failure_is_an_error_not_a_pass(tmp_path):
    m = _manifest(1)
    root = tmp_path / "shards"
    _write_shard(root, m, 0, outcomes={POP[0]: "setup"}, exit_code=1)
    r = cc.aggregate(m, root, "failure")
    assert r["verdict"] == cc.RED
    assert r["failures"][0]["outcome"] == cc.ERROR


def test_collection_error_is_red(tmp_path):
    m = _manifest(2, collect_errors=[{"n": "tests/test_broken.py", "msg": "ImportError"}])
    root = tmp_path / "shards"
    for i in range(2):
        d = _write_shard(root, m, i, exit_code=0)
        if "tests/test_broken.py" in m["shards"][i]["files"]:
            (d / cc.EXIT_FILE).write_text(json.dumps({"exit": 1}))
            with open(d / cc.COLLECTED_FILE, "a") as fh:
                fh.write(json.dumps({"e": "collect_error", "n": "tests/test_broken.py",
                                     "msg": "ImportError"}) + "\n")
    r = cc.aggregate(m, root, "failure")
    assert r["verdict"] == cc.RED, _reasons(r)
    assert [e["n"] for e in r["collect_errors"]] == ["tests/test_broken.py"]


# ── свод: каждое порванное звено ⇒ INCOMPLETE (положительные контроли) ───────

def test_missing_shard_is_incomplete(tmp_path):
    m, root = _healthy(tmp_path)
    import shutil
    shutil.rmtree(root / f"{cc.SHARD_DIR_PREFIX}1")
    r = cc.aggregate(m, root, "success")
    assert r["verdict"] == cc.INCOMPLETE
    assert any(x["shard"] == 1 and "артефакта шарда нет" in x["reason"] for x in r["incomplete"])
    assert r["totals"]["not_obtained"] > 0


def test_union_not_equal_to_manifest_is_incomplete(tmp_path):
    m, root = _healthy(tmp_path)
    dropped = m["shards"][0]["files"].pop()            # файл населения выпал из плана
    r = cc.aggregate(m, root, "success")
    assert r["verdict"] == cc.INCOMPLETE
    assert any("союз шардов ≠ населению" in x["reason"] and dropped in x["reason"]
               for x in r["incomplete"]), _reasons(r)


def test_file_in_two_shards_is_incomplete(tmp_path):
    m, root = _healthy(tmp_path)
    m["shards"][1]["files"].append(m["shards"][0]["files"][0])
    r = cc.aggregate(m, root, "success")
    assert r["verdict"] == cc.INCOMPLETE
    assert any("несколько шардов" in x["reason"] for x in r["incomplete"])


def test_cancelled_shard_is_incomplete_and_names_the_test_it_died_on(tmp_path):
    """Сцена джобы 116884127339: сессия снята посреди файла — записи конца и кода нет."""
    m = _manifest(1)
    root = tmp_path / "shards"
    hung = POP[2]
    _write_shard(root, m, 0, outcomes={hung: None}, end=False, exit_code=None)
    r = cc.aggregate(m, root, "cancelled")
    assert r["verdict"] == cc.INCOMPLETE
    text = _reasons(r)
    assert "не дошла до конца" in text and "кода возврата pytest нет" in text
    assert "cancelled" in text
    assert hung in r["shards"][0]["unfinished"]
    assert hung in r["not_obtained"]


def test_cancelled_job_result_alone_is_incomplete(tmp_path):
    """Файлы на месте, но джоба шардов отменена — ответом это не считается."""
    m, root = _healthy(tmp_path)
    assert cc.aggregate(m, root, "success")["verdict"] == cc.GREEN
    assert cc.aggregate(m, root, "cancelled")["verdict"] == cc.INCOMPLETE
    assert cc.aggregate(m, root, "skipped")["verdict"] == cc.INCOMPLETE


def test_shard_without_results_file_is_incomplete(tmp_path):
    m = _manifest(2)
    root = tmp_path / "shards"
    _write_shard(root, m, 0)
    _write_shard(root, m, 1, stream=False)
    r = cc.aggregate(m, root, "success")
    assert r["verdict"] == cc.INCOMPLETE
    assert any(x["shard"] == 1 and "потоковой записи нет" in x["reason"] for x in r["incomplete"])


def test_shard_without_collection_record_is_incomplete(tmp_path):
    m = _manifest(2)
    root = tmp_path / "shards"
    _write_shard(root, m, 0)
    _write_shard(root, m, 1, collected=False)
    r = cc.aggregate(m, root, "success")
    assert r["verdict"] == cc.INCOMPLETE
    assert any(x["shard"] == 1 and "перечня собранного нет" in x["reason"]
               for x in r["incomplete"])


def test_shard_that_collected_something_else_is_incomplete(tmp_path):
    m = _manifest(1)
    root = tmp_path / "shards"
    _write_shard(root, m, 0, extra_collected=["tests/test_a.py::test_ghost"])
    r = cc.aggregate(m, root, "success")
    assert r["verdict"] == cc.INCOMPLETE
    assert "вне населения" in _reasons(r)


def test_exit_one_without_a_named_failure_is_incomplete(tmp_path):
    m = _manifest(1)
    root = tmp_path / "shards"
    _write_shard(root, m, 0, exit_code=1)
    r = cc.aggregate(m, root, "failure")
    assert r["verdict"] == cc.INCOMPLETE
    assert "ни одного упавшего имени" in _reasons(r)


def test_interrupted_exit_code_is_incomplete(tmp_path):
    m = _manifest(1)
    root = tmp_path / "shards"
    _write_shard(root, m, 0, exit_code=2)
    assert cc.aggregate(m, root, "failure")["verdict"] == cc.INCOMPLETE


def test_no_manifest_is_incomplete(tmp_path):
    r = cc.aggregate(None, tmp_path / "nothing", "skipped")
    assert r["verdict"] == cc.INCOMPLETE


def test_stray_artifact_outside_the_plan_is_incomplete(tmp_path):
    m, root = _healthy(tmp_path)
    (root / f"{cc.SHARD_DIR_PREFIX}7").mkdir()
    r = cc.aggregate(m, root, "success")
    assert r["verdict"] == cc.INCOMPLETE


def test_cmd_aggregate_exit_codes_and_word(tmp_path, capsys):
    m, root = _healthy(tmp_path)
    mdir = tmp_path / "ctl"
    mdir.mkdir()
    (mdir / "manifest.json").write_text(json.dumps(m))
    args = ["aggregate", "--manifest-dir", str(mdir), "--shards-dir", str(root),
            "--out-json", str(tmp_path / "r.json"), "--out-md", str(tmp_path / "r.md")]
    assert cc.main(args + ["--needs-result", "success"]) == 0
    assert cc.main(args + ["--needs-result", "cancelled"]) == 2
    assert "CI-CONTROL VERDICT: INCOMPLETE" in capsys.readouterr().out
    assert "INCOMPLETE" in (tmp_path / "r.md").read_text()


# ── сравнение двух отчётов ───────────────────────────────────────────────────

def _report(tmp_path: Path, name: str, fails: dict, missing=()) -> dict:
    m = _manifest(1)
    root = tmp_path / name
    _write_shard(root, m, 0, outcomes={n: (None if n in missing else w)
                                       for n, w in {**fails, **{k: None for k in missing}}.items()},
                 exit_code=1 if fails else 0, end=not missing)
    return cc.aggregate(m, root, "failure" if fails else "success")


def test_compare_classifies_new_pre_existing_not_obtained_and_fixed(tmp_path):
    a, b, c, d = POP[0], POP[1], POP[2], POP[3]
    base = _report(tmp_path, "base", {a: "call", d: "call"}, missing=(c,))
    head = _report(tmp_path, "head", {a: "call", b: "call", c: "call"})
    res = cc.compare(base, head)
    assert res["comparable"]
    assert res["pre_existing"] == [a]
    assert res["new"] == [b]
    assert res["not_obtained"] == [c]
    assert res["fixed"] == [d]


def test_compare_refuses_different_environments(tmp_path):
    base = _report(tmp_path, "base", {})
    head = _report(tmp_path, "head", {})
    head["env"] = dict(head["env"], python="3.12.1")
    res = cc.compare(base, head)
    assert not res["comparable"] and res["new"] == []
    assert "python" in res["why_not"][0]


def test_cmd_compare_exit_codes(tmp_path):
    base = _report(tmp_path, "base", {})
    head = _report(tmp_path, "head", {POP[0]: "call"})
    bp, hp = tmp_path / "b.json", tmp_path / "h.json"
    bp.write_text(json.dumps(base))
    hp.write_text(json.dumps(head))
    assert cc.main(["compare", str(bp), str(hp)]) == 1          # новая поломка
    assert cc.main(["compare", str(bp), str(bp)]) == 0
    hp.write_text(json.dumps({"schema": "other"}))
    assert cc.main(["compare", str(bp), str(hp)]) == 2


# ── живой pytest: плагины → план → шарды → свод ──────────────────────────────

def _scene(tmp_path: Path) -> Path:
    root = tmp_path / "scene"
    (root / "tests").mkdir(parents=True)
    (root / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    (root / "tests" / "test_one.py").write_text("def test_a(): assert True\n"
                                                "def test_b(): assert True\n")
    (root / "tests" / "test_two.py").write_text("def test_red(): assert False, 'named'\n")
    (root / "tests" / "test_three.py").write_text(textwrap.dedent("""
        import pytest
        @pytest.mark.parametrize("x", [1, 2])
        def test_p(x): assert x
        def test_s(): pytest.skip("why")
    """))
    (root / "tests" / "test_broken.py").write_text("import no_such_module_xyz\n")
    return root


def _pytest(root: Path, args: list[str], env_extra: dict) -> int:
    env = {**os.environ, "PYTHONPATH": str(_REPO_ROOT), "SPA_ENV": "ci", "PYTHONHASHSEED": "0",
           **env_extra}
    for name in ("SPA_PYTEST_STREAM", "SPA_PYTEST_MANIFEST"):
        if name not in env_extra:
            env.pop(name, None)          # унаследованная запись родителя здесь чужая
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *args, "--rootdir", str(root), "-q",
         "-p", "no:randomly", "-p", "no:cacheprovider"],
        cwd=str(root), env=env, capture_output=True, text=True, timeout=120)
    return proc.returncode


def test_live_pytest_end_to_end_red_then_incomplete_when_a_shard_is_lost(tmp_path):
    root = _scene(tmp_path)
    ctl = root / "ctl"
    code = _pytest(root, ["tests", "--collect-only", "-p", "spa_core.ci.pytest_collect_manifest",
                          "--continue-on-collection-errors"],
                   {"SPA_PYTEST_MANIFEST": str(ctl / "collected.jsonl")})
    assert code in (0, 1), code
    w = tmp_path / "w.json"
    w.write_text(json.dumps({"files": {}, "per_test_fallback_s": 1.0}))
    assert cc.main(["plan", "--collected", str(ctl / "collected.jsonl"), "--weights", str(w),
                    "--shards", "2", "--budget-min", "60", "--sha", "deadbeef",
                    "--roots", "tests", "--out-dir", str(ctl)]) == 0
    manifest = json.loads((ctl / "manifest.json").read_text())
    assert manifest["population"] == 6
    assert "tests/test_broken.py" in manifest["files"]
    shards = root / "shards"
    for i in range(2):
        out = shards / f"{cc.SHARD_DIR_PREFIX}{i}"
        out.mkdir(parents=True)
        (out / cc.SHARD_FILE).write_text(json.dumps({"shard": i}))
        files = (ctl / f"shard-{i}.txt").read_text().split()
        rc = _pytest(root, [*files, "-p", "spa_core.ci.pytest_stream_record",
                            "-p", "spa_core.ci.pytest_collect_manifest",
                            "--continue-on-collection-errors"],
                     {"SPA_PYTEST_STREAM": str(out / cc.STREAM_FILE),
                      "SPA_PYTEST_MANIFEST": str(out / cc.COLLECTED_FILE)})
        (out / cc.EXIT_FILE).write_text(json.dumps({"exit": rc}))
    r = cc.aggregate(manifest, shards, "failure")
    assert r["verdict"] == cc.RED, _reasons(r)
    assert [f["nodeid"] for f in r["failures"]] == ["tests/test_two.py::test_red"]
    assert [e["n"] for e in r["collect_errors"]] == ["tests/test_broken.py"]
    assert r["totals"]["passed"] == 4 and r["totals"]["skipped"] == 1
    # Тот же прогон без одного шарда — уже не ответ.
    import shutil
    shutil.rmtree(shards / f"{cc.SHARD_DIR_PREFIX}1")
    assert cc.aggregate(manifest, shards, "failure")["verdict"] == cc.INCOMPLETE


# ── проводка воркфлоу ────────────────────────────────────────────────────────

def _wf() -> dict:
    import yaml   # в CI стоит всегда; отсутствие — громкий ImportError, а не скип
    return yaml.safe_load(_WORKFLOW.read_text(encoding="utf-8"))


def test_workflow_is_not_cancellable_by_push_and_does_not_run_on_push():
    doc = _wf()
    on = doc.get("on", doc.get(True))
    assert set(on) == {"schedule", "workflow_dispatch"}, on
    assert doc["concurrency"] == {"group": "ci-control", "cancel-in-progress": False}


def test_every_job_runs_the_pinned_commit():
    jobs = _wf()["jobs"]
    checkout = {name: next(s for s in job["steps"] if str(s.get("uses", "")).startswith(
        "actions/checkout")) for name, job in jobs.items()}
    assert "needs.manifest.outputs.sha" in checkout["shards"]["with"]["ref"]
    assert "needs.manifest.outputs.sha" in checkout["aggregate"]["with"]["ref"]
    assert jobs["manifest"]["outputs"]["sha"] == "${{ steps.pin.outputs.sha }}"


def test_shard_step_records_where_the_aggregator_reads():
    jobs = _wf()["jobs"]
    step = next(s for s in jobs["shards"]["steps"] if s.get("name") == "Run shard")
    run = step["run"]
    assert "-p spa_core.ci.pytest_stream_record" in run
    assert "-p spa_core.ci.pytest_collect_manifest" in run
    assert "--timeout-method=signal" in run and "thread" not in run
    assert "-p no:randomly" in run
    assert step["env"]["SPA_ENV"] == "ci" and str(step["env"]["PYTHONHASHSEED"]) == "0"
    assert step["env"]["SPA_PYTEST_STREAM"] == f"ctl-out/{cc.STREAM_FILE}"
    assert step["env"]["SPA_PYTEST_MANIFEST"] == f"ctl-out/{cc.COLLECTED_FILE}"
    assert f"ctl-out/{cc.EXIT_FILE}" in run and f"ctl-out/{cc.SHARD_FILE}" in run
    upload = next(s for s in jobs["shards"]["steps"] if s.get("name") == "Upload shard records")
    assert upload["if"] == "${{ always() }}"
    assert upload["with"]["name"].startswith(cc.SHARD_DIR_PREFIX)
    assert jobs["shards"]["strategy"]["fail-fast"] is False


def test_aggregate_always_runs_and_cannot_be_skipped_by_a_missing_artifact():
    agg = _wf()["jobs"]["aggregate"]
    assert agg["if"] == "${{ always() }}"
    assert set(agg["needs"]) == {"manifest", "shards"}
    downloads = [s for s in agg["steps"] if str(s.get("uses", "")).startswith(
        "actions/download-artifact")]
    assert downloads and all(s.get("continue-on-error") is True for s in downloads)
    step = next(s for s in agg["steps"] if "aggregate" in str(s.get("run", "")))
    assert "needs.shards.result" in step["run"]
