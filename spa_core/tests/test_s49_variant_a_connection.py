# LLM_FORBIDDEN
"""§49 вариант А и закрепление S у сервера — контроли подключения (решение ARB 23.10, этап 8).

Три предмета, у каждого контроль в обе стороны:

1. **Граница записи при выборе S.** ``pin_server_ref`` при нехватке объекта делает
   ``git fetch`` в переданный репозиторий. Положительный контроль ВОСПРОИЗВОДИТ это на
   копии «боевого» дерева, а ``pin_revision`` производителя обязан закрепить ту же S,
   не изменив в «боевом» ``.git`` ни байта (объект добирается во временный клон).
2. **``--if-due``** отвечает прежним отчётом только о том же прогоне, той же S и
   свежей записи; старую запись свежей не делает, ревизию не обходит.
3. **Вариант А через НАСТОЯЩЕГО вызывающего** (``cio_acceptance_rollup`` →
   ``run_probe`` → проба): решение о чистом снимке S, отчёт из ``report_dir``.
   Контроли: верные S и отчёт · другой SHA · грязный снимок · отчёта нет ·
   отчёт протух · отказ получения записи. Каталог отчёта доходит ТОЛЬКО до пробы §49.

Сцена — одноразовые git-репозитории (сервер = bare, «боевое» = отстающий клон) и
запись CI из ``test_no_regression_census_from_ci``. Ни pytest-прогонов, ни сети.
Время: проверка записи получает ``now`` входом; проба через вызывающего часов не
принимает, поэтому отметка отчёта ставится ОТНОСИТЕЛЬНО часов (`deployment.md`,
приём №2), а не литералом.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for p in (str(_REPO), str(_REPO / "scripts")):
    if p not in sys.path:
        sys.path.insert(0, p)

import cio_acceptance_rollup as rollup  # noqa: E402

from spa_core.monitoring import card_acceptance as ca  # noqa: E402
from spa_core.monitoring import no_regression_census as census  # noqa: E402
from spa_core.tests import test_no_regression_census_from_ci as fc  # noqa: E402
from spa_core.utils import server_ref  # noqa: E402

BRANCH = "main"


def _producer():
    spec = importlib.util.spec_from_file_location(
        "_refresh_s49_variant_a", _REPO / "scripts" / "refresh_no_regression_census.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _g(root: Path, *args: str, check: bool = True) -> str:
    out = subprocess.run(["git", "-C", str(root), "-c", "user.name=t", "-c", "user.email=t@t",
                          *args], capture_output=True, text=True, check=check)
    return out.stdout.strip()


def _fingerprint(git_dir: Path) -> dict:
    """Каждый файл ``.git``: путь → sha256. Любая запись в репозиторий его меняет."""
    out = {}
    for p in sorted(git_dir.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(git_dir))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _server_ahead(tmp: Path, files: dict | None = None) -> tuple[Path, Path, str, str]:
    """Сервер (bare) с двумя коммитами и «боевое» дерево, отставшее на один.

    Возврат: (сервер, боевое, старая вершина, новая вершина S). Объекта S в боевом нет.
    """
    srv = tmp / "srv.git"
    subprocess.run(["git", "init", "-q", "--bare", "-b", BRANCH, str(srv)], check=True)
    seed = tmp / "seed"
    subprocess.run(["git", "init", "-q", "-b", BRANCH, str(seed)], check=True)
    (seed / "README").write_text("old\n", encoding="utf-8")
    _g(seed, "add", "-A")
    _g(seed, "commit", "-qm", "old")
    _g(seed, "remote", "add", "origin", str(srv))
    _g(seed, "push", "-q", "origin", BRANCH)
    old = _g(seed, "rev-parse", "HEAD")
    live = tmp / "live"
    subprocess.run(["git", "clone", "-q", str(srv), str(live)], check=True)
    for rel, body in (files or {"README": "new\n"}).items():
        p = seed / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    _g(seed, "add", "-A")
    _g(seed, "commit", "-qm", "new")
    _g(seed, "push", "-q", "origin", BRANCH)
    new = _g(seed, "rev-parse", "HEAD")
    assert subprocess.run(["git", "-C", str(live), "cat-file", "-e", new + "^{commit}"],
                          capture_output=True).returncode != 0, "предпосылка: S в боевом нет"
    return srv, live, old, new


# ───────────────────────── 1. граница записи при выборе S ─────────────────────────

def test_the_existing_pin_writes_into_the_repository_it_is_given(tmp_path):
    """Положительный контроль опасности, названной ARB: fetch идёт в ПЕРЕДАННЫЙ .git."""
    _srv, live, _old, new = _server_ahead(tmp_path)
    copy = tmp_path / "live_copy"
    shutil.copytree(live, copy)
    before = _fingerprint(copy / ".git")
    pinned = server_ref.pin_server_ref(str(copy), "origin/main")
    assert pinned.sha == new
    assert _fingerprint(copy / ".git") != before, (
        "pin_server_ref больше не пишет в переданный репозиторий — контроль ниже стал "
        "тавтологией, перепроверь предпосылку")


def test_pin_revision_takes_the_server_head_and_leaves_the_source_untouched(tmp_path):
    _srv, live, old, new = _server_ahead(tmp_path)
    before = _fingerprint(live / ".git")
    mod = _producer()
    work = tmp_path / "work"
    work.mkdir()
    rev, pin_repo = mod.pin_revision(live, "origin/main", work)
    assert rev["sha"] == new and rev["source"] == "server"
    assert _g(live, "rev-parse", "origin/main") == old, "кэш боевого не тронут и S не он"
    assert _fingerprint(live / ".git") == before, "в боевой .git записано"
    assert subprocess.run(["git", "-C", str(live), "cat-file", "-e", new + "^{commit}"],
                          capture_output=True).returncode != 0, "объект S попал в боевое"
    # Снимок S снимается из временного клона и указывает ровно на S.
    tree = tmp_path / "snap"
    mod.snapshot_commit(pin_repo, new, tree)
    assert _g(tree, "rev-parse", "HEAD") == new
    assert (tree / "README").read_text() == "new\n"
    assert _fingerprint(live / ".git") == before


def test_an_unreachable_server_is_unmeasured_not_the_cached_head(tmp_path):
    _srv, live, _old, _new = _server_ahead(tmp_path)
    _g(live, "remote", "set-url", "origin", str(tmp_path / "nowhere.git"))
    before = _fingerprint(live / ".git")
    mod = _producer()
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(mod.RevisionUnpinned) as info:
        mod.pin_revision(live, "origin/main", work)
    assert "не закреплена" in str(info.value)
    assert _fingerprint(live / ".git") == before


@pytest.mark.parametrize("ref", ["HEAD", "main"])
def test_a_local_ref_is_not_silently_taken_as_the_server_revision(tmp_path, ref):
    _srv, live, _old, _new = _server_ahead(tmp_path)
    mod = _producer()
    work = tmp_path / "work"
    work.mkdir()
    with pytest.raises(mod.RevisionUnpinned) as info:
        mod.pin_revision(live, ref, work)
    assert "S выбирает СЕРВЕР" in str(info.value)


# ───────────────────── 2. from_ci: S у сервера, только расписанный прогон ─────────────────────

@pytest.fixture()
def served(tmp_path):
    """Боевое дерево отстаёт; S у сервера несёт сцену; запись CI — о S."""
    _srv, live, old, new = _server_ahead(tmp_path, fc._FILES)
    rec = fc._record(tmp_path, new)
    return live, old, new, rec, tmp_path


def test_from_ci_measures_the_server_revision_without_writing_the_source(served, monkeypatch):
    live, _old, new, rec, tmp = served
    mod = _producer()
    monkeypatch.delenv(mod.VIA_ENV, raising=False)
    before = _fingerprint(live / ".git")
    out = mod.from_ci(live, out_root=tmp / "out", http=fc._FakeGitHub(rec), now=fc.NOW)
    doc = json.loads((tmp / "out" / census.REPORT_REL).read_text())
    assert doc["verdict"] == census.NO_REGRESSION and out["sha"] == new
    inv = doc["invoked_by"]
    assert inv["revision"]["source"] == "server" and inv["revision"]["sha"] == new
    assert inv["instrument"]["path"] and "sha" in inv["instrument"]
    assert doc["source"]["sha"] == new and doc["source"]["event"] == "schedule"
    assert _fingerprint(live / ".git") == before


def test_a_manual_run_is_not_picked_automatically(served):
    live, _old, _new, rec, tmp = served
    fc._edit(rec / census.CI_RUN_FILE, lambda d: d.update(event="workflow_dispatch"))
    mod = _producer()
    with pytest.raises(mod.NotMeasured):
        mod.from_ci(live, out_root=tmp / "out", http=fc._FakeGitHub(rec), now=fc.NOW)
    assert not (tmp / "out" / census.REPORT_REL).exists()
    refusal = sorted((tmp / "out" / mod.RECORDS_REL).glob("*.refusal.json"))[-1]
    assert json.loads(refusal.read_text())["code"] == census.CI_RECORD_UNAVAILABLE


def test_an_unpinned_revision_is_refused_with_its_own_code(served):
    live, _old, _new, rec, tmp = served
    _g(live, "remote", "set-url", "origin", str(tmp / "nowhere.git"))
    mod = _producer()
    with pytest.raises(mod.NotMeasured):
        mod.from_ci(live, out_root=tmp / "out", http=fc._FakeGitHub(rec), now=fc.NOW)
    refusal = sorted((tmp / "out" / mod.RECORDS_REL).glob("*.refusal.json"))[-1]
    assert json.loads(refusal.read_text())["code"] == "revision_unpinned"


# ───────────────────────────────── 3. --if-due ─────────────────────────────────

def test_if_due_reuses_only_the_same_run_revision_and_fresh_record(served):
    live, _old, new, rec, tmp = served
    mod = _producer()
    gh = fc._FakeGitHub(rec)
    mod.from_ci(live, out_root=tmp / "out", http=gh, now=fc.NOW)
    target = tmp / "out" / census.REPORT_REL
    written, mtime = target.read_bytes(), target.stat().st_mtime_ns
    again = mod.from_ci(live, out_root=tmp / "out", http=gh, now=fc.NOW, if_due=True)
    assert again["due"] is False and new[:12] in again["age_reason"]
    assert target.read_bytes() == written and target.stat().st_mtime_ns == mtime
    assert any("не срок" in line for line in mod._lines(again)), "печать повтора упала/молчит"


def test_if_due_does_not_make_an_old_record_fresh(served):
    live, _old, _new, rec, tmp = served
    mod = _producer()
    gh = fc._FakeGitHub(rec)
    mod.from_ci(live, out_root=tmp / "out", http=gh, now=fc.NOW)
    target = tmp / "out" / census.REPORT_REL
    written = target.read_bytes()
    later = fc.NOW + timedelta(hours=census.ci_max_age_h() + 1)
    with pytest.raises(mod.NotMeasured):
        mod.from_ci(live, out_root=tmp / "out", http=gh, now=later, if_due=True)
    assert target.read_bytes() == written, "протухший отчёт переписан"
    refusal = sorted((tmp / "out" / mod.RECORDS_REL).glob("*.refusal.json"))[-1]
    assert json.loads(refusal.read_text())["code"] == census.CI_RECORD_STALE


def test_if_due_does_not_bypass_the_revision_check(served):
    live, _old, new, rec, tmp = served
    mod = _producer()
    gh = fc._FakeGitHub(rec)
    mod.from_ci(live, out_root=tmp / "out", http=gh, now=fc.NOW)
    target = tmp / "out" / census.REPORT_REL
    fc._edit(target, lambda d: d["invoked_by"].update(sha="a" * 40))
    again = mod.from_ci(live, out_root=tmp / "out", http=gh, now=fc.NOW, if_due=True)
    assert again["due"] is True and "не о ревизии" in again["reuse"]
    assert json.loads(target.read_text())["invoked_by"]["sha"] == new


# ─────────────────── 4. вариант А через настоящего вызывающего ───────────────────

_SECTION = ("49. Acceptance criteria\nРабота считается выполненной только когда доказано "
            "следующее.\nNo regression\nExisting risk/security/architecture tests проходят.\n"
            "\n\n⸻\n\n\n50. Definition of Done\n")


def _card_tree(tmp: Path) -> str:
    root = tmp / "cards"
    card = root / rollup.CARD_REL
    card.parent.mkdir(parents=True)
    card.write_text("---\ntitle: \"TASK\"\nstatus: in-progress\n---\n\n## Задание\n\n"
                    "преамбула\n\n\n⸻\n\n\n" + _SECTION, encoding="utf-8")
    subprocess.run(["git", "init", "-q", "-b", BRANCH, str(root)], check=True)
    _g(root, "add", "-A")
    _g(root, "commit", "-qm", "card")
    return str(root)


@pytest.fixture()
def variant_a(served):
    """Отчёт о S в out/data (настоящий производитель) и чистый снимок S (настоящий снимок)."""
    live, _old, new, rec, tmp = served
    mod = _producer()
    mod.from_ci(live, out_root=tmp / "out", http=fc._FakeGitHub(rec), now=fc.NOW)
    report_dir = tmp / "out" / "data"
    # Проба через вызывающего часов не принимает — отметка наблюдения ставится
    # относительно часов (приём №2), остальное в отчёте не трогается.
    _restamp(report_dir, hours_ago=2)
    work = tmp / "pinwork"
    work.mkdir()
    _rev, pin_repo = mod.pin_revision(live, "origin/main", work)
    snap = tmp / "snap"
    mod.snapshot_commit(pin_repo, new, snap)
    return {"snap": snap, "report_dir": report_dir, "sha": new, "cards": _card_tree(tmp),
            "tmp": tmp, "mod": mod, "live": live, "rec": rec}


def _restamp(report_dir: Path, *, hours_ago: float) -> None:
    path = report_dir / os.path.basename(census.REPORT_REL)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["generated_at"] = (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def _rollup_row(cards: str, snap, report_dir) -> dict:
    report = rollup.measure(cards, ref=BRANCH, measure_tree=str(snap),
                            report_dir=str(report_dir))
    (row,) = [r for r in report["rows"] if r["criterion"] == "No regression"]
    assert row["probe"] == "no_regression_tests_pass"
    assert report["report_dir"] == str(report_dir) and report["split_tree"] is False
    return row


def test_right_revision_and_report_through_the_real_caller(variant_a):
    v = variant_a
    row = _rollup_row(v["cards"], v["snap"], v["report_dir"])
    assert row["verdict"] == ca.SATISFIED, row["detail"]
    assert row["tree_inputs_reached"] == ["repo_root", "report_dir"]
    d = row["detail"]
    assert f"код {v['sha'][:12]}" in d and f"решение о дереве {v['snap']}" in d
    assert str(v["report_dir"]) in d and f"прогон {fc.RUN_ID}" in d and "прибор" in d


def test_the_cli_of_the_real_caller_carries_the_report_dir(variant_a, capsys):
    v = variant_a
    rollup.main(["--repo-root", v["cards"], "--ref", BRANCH, "--measure-tree", str(v["snap"]),
                 "--report-dir", str(v["report_dir"])])
    out = capsys.readouterr().out
    assert f"отчёт §49 взят из {v['report_dir']}" in out
    assert "дошло входами: repo_root, report_dir" in out


def test_another_sha_in_the_decision_tree_is_unmeasured(variant_a):
    v = variant_a
    (v["snap"] / "README.extra").write_text("x\n", encoding="utf-8")
    _g(v["snap"], "add", "-A")
    _g(v["snap"], "commit", "-qm", "moved on")
    row = _rollup_row(v["cards"], v["snap"], v["report_dir"])
    assert row["verdict"] == ca.UNMEASURED and "за другую ревизию" in row["detail"]


def test_a_dirty_snapshot_is_unmeasured(variant_a):
    v = variant_a
    (v["snap"] / "spa_core" / "tests" / "test_scene_risk.py").write_text(
        "import spa_core.risk.policy\n\ndef test_a():\n    assert False\n", encoding="utf-8")
    row = _rollup_row(v["cards"], v["snap"], v["report_dir"])
    assert row["verdict"] == ca.UNMEASURED and "изменено после коммита" in row["detail"]


def test_a_missing_report_is_unmeasured(variant_a):
    v = variant_a
    empty = v["tmp"] / "empty_reports"
    empty.mkdir()
    row = _rollup_row(v["cards"], v["snap"], empty)
    assert row["verdict"] == ca.UNMEASURED and "не прочитан" in row["detail"]


def test_a_stale_report_is_unmeasured(variant_a):
    v = variant_a
    _restamp(v["report_dir"], hours_ago=ca._NO_REGRESSION_MAX_AGE_H + 1)
    row = _rollup_row(v["cards"], v["snap"], v["report_dir"])
    assert row["verdict"] == ca.UNMEASURED and "старше предела" in row["detail"]


def test_a_refused_record_leaves_the_consumer_unmeasured(served):
    """Получение записи отказало ⇒ отчёта о S нет ⇒ потребитель: НЕ ИЗМЕРЕНО, не зелень."""
    live, _old, new, rec, tmp = served
    mod = _producer()

    class _Cut(fc._FakeGitHub):
        def get_bytes(self, url):
            raise OSError("сеть отрезана")
    with pytest.raises(mod.NotMeasured):
        mod.from_ci(live, out_root=tmp / "out", http=_Cut(rec), now=fc.NOW)
    work = tmp / "w"
    work.mkdir()
    _rev, pin_repo = mod.pin_revision(live, "origin/main", work)
    snap = tmp / "snap"
    mod.snapshot_commit(pin_repo, new, snap)
    (tmp / "out" / "data").mkdir(parents=True, exist_ok=True)
    row = _rollup_row(_card_tree(tmp), snap, tmp / "out" / "data")
    assert row["verdict"] == ca.UNMEASURED and "не прочитан" in row["detail"]


def test_the_live_tree_is_not_judged_by_a_report_about_s(variant_a):
    """Тот же отчёт о S, но решение о «боевом» дереве (другая ревизия) — НЕ засчитан."""
    v = variant_a
    row = _rollup_row(v["cards"], v["live"], v["report_dir"])
    assert row["verdict"] == ca.UNMEASURED and "за другую ревизию" in row["detail"]


# ─────────────── каталог отчёта не меняет предмет остальных критериев ───────────────

def test_only_the_s49_probe_accepts_the_report_dir():
    takers = sorted(n for n in ca.PROBES if "report_dir" in ca.probe_tree_inputs(n))
    assert takers == ["no_regression_tests_pass"]


def test_the_rollup_offers_the_report_dir_to_no_other_criterion(tmp_path, monkeypatch):
    seen = {}

    def runner(spec, **kw):
        seen[spec] = kw
        return ca.UNMEASURED, "фикстура"
    monkeypatch.setattr(rollup, "probe_tree_inputs",
                        lambda name: ("repo_root", "data_dir", "tracker_dir"))
    cards = _card_tree(tmp_path)
    rollup.measure(cards, ref=BRANCH, measure_tree="/t", report_dir="/r", probe_runner=runner)
    assert seen and all("report_dir" not in kw for kw in seen.values())


def test_split_tree_is_still_said_aloud_with_a_report_dir(tmp_path):
    cards = _card_tree(tmp_path)
    report = rollup.measure(cards, ref=BRANCH, measure_tree="/t", data_dir="/d",
                            report_dir="/r", probe_runner=lambda spec, **kw: (ca.UNMEASURED, "x"))
    assert report["split_tree"] is True and report["report_dir"] == "/r"


# ───────────── производитель: решение о снимке S настоящим run_probe ─────────────

def test_the_producer_decides_about_its_own_snapshot_through_run_probe(tmp_path, monkeypatch):
    """`--decide`: проба через `run_probe`, дерево — снимок S, отчёт — out/data.

    Проба часов не принимает (через `run_probe`), поэтому окно записи сцены
    сдвигается к ТЕКУЩИМ часам (приём №2) — бомбы календаря здесь нет.
    """
    now = datetime.now(timezone.utc).replace(microsecond=0)
    monkeypatch.setattr(fc, "STARTED", now - timedelta(hours=2))
    monkeypatch.setattr(fc, "PLANNED", now - timedelta(hours=2) + timedelta(minutes=3))
    monkeypatch.setattr(fc, "FINISHED", now - timedelta(hours=2) + timedelta(minutes=40))
    _srv, live, _old, new = _server_ahead(tmp_path, fc._FILES)
    rec = fc._record(tmp_path, new)
    mod = _producer()
    seen = {}
    real = ca.run_probe

    def spy(spec, **kw):
        seen.update(spec=spec, **kw)
        return real(spec, **kw)
    monkeypatch.setattr(ca, "run_probe", spy)
    out = mod.from_ci(live, out_root=tmp_path / "out", http=fc._FakeGitHub(rec), now=now,
                      decide=True)
    dec = out["decision"]
    assert dec["verdict"] == ca.SATISFIED, dec["detail"]
    assert seen["spec"] == "no_regression_tests_pass"
    assert seen["report_dir"] == str(tmp_path / "out" / "data")
    assert dec["decision_tree"]["sha"] == new and dec["decision_tree"]["clean"] is True
    assert seen["repo_root"] == dec["decision_tree"]["path"] != str(live)
    assert any("[РЕШЕНИЕ §49 О СНИМКЕ]" in line for line in mod._lines(out))
