"""Уборка мёртвых рабочих деревьев — правило снятия и его положительные контроли.

Каждый тест воспроизводит РЕАЛЬНОЕ состояние, замеренное 14.08 (циклы #224/#230): 70
регистраций `git worktree list`, из них шесть-семь давали шаг 0a одни и те же строки
«НЕ ДОСТАВЛЕНО» цикл за циклом. Проверка, никогда не видевшая настоящей поломки, —
украшение (`.claude/rules/deployment.md`), поэтому здесь: superseded-состояние `docs/STATE.md`
из дерева #227 (перекрыто циклом #228), доставленный, но незакоммиченный файл (пуш идёт прямо
в origin через API), осиротевший `scripts/edge_criterion_consensus.py` из `spa_wt_rnd49`
(на origin его нет вовсе — снять такое дерево значит потерять работу).

Тесты гоняют настоящий git на временном репозитории: сеть не нужна, «origin» — локальный
bare-репозиторий. Дат в фикстурах нет — время подаётся ВХОДОМ (`now`, `now_ts`).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import reap_stale_worktrees as R  # noqa: E402


NOW = datetime(2026, 8, 14, 16, 0, tzinfo=timezone.utc)   # FROZEN-DATE-OK: время — ВХОД теста
NOW_TS = NOW.timestamp()
OLD_TS = NOW_TS - 72 * 3600


def _run(cwd, *args):
    env = dict(os.environ)
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env)
    assert p.returncode == 0, f"git {args} -> {p.returncode}: {p.stderr}"
    return p.stdout


def _age(path):
    """Состарить дерево: ни один файл не должен выглядеть свежим."""
    for dirpath, dirnames, filenames in os.walk(path):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        for name in filenames:
            try:
                os.utime(os.path.join(dirpath, name), (OLD_TS, OLD_TS))
            except OSError:
                pass


@pytest.fixture
def repo(tmp_path):
    """(root, origin) — рабочий репозиторий с настоящим `origin/main`."""
    origin = tmp_path / "origin.git"
    _run(tmp_path, "init", "--bare", "-b", "main", str(origin))
    root = tmp_path / "work"
    _run(tmp_path, "clone", str(origin), str(root))
    (root / "docs").mkdir()
    (root / "docs" / "STATE.md").write_text("v1\n", encoding="utf-8")
    (root / "keep.txt").write_text("keep\n", encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-m", "base")
    _run(root, "push", "origin", "main")
    (root / "data").mkdir()
    (root / "data" / "session_changes.jsonl").write_text("", encoding="utf-8")
    return root, origin


def _worktree(root, name, at="HEAD"):
    wt = root.parent / name
    _run(root, "worktree", "add", "--detach", str(wt), at)
    return wt


def _log(root, entries):
    path = root / "data" / "session_changes.jsonl"
    path.write_text("\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n",
                    encoding="utf-8")
    return path


def _report(root, **kw):
    return R.build_report(root, "origin/main", root / "data" / "session_changes.jsonl",
                          kw.pop("grace_hours", 24.0), now=kw.pop("now", NOW),
                          now_ts=kw.pop("now_ts", NOW_TS), **kw)


def _verdict(report, wt):
    for t in report["trees"]:
        if Path(t["path"]).resolve() == Path(wt).resolve():
            return t
    raise AssertionError(f"{wt} нет в отчёте: {[t['path'] for t in report['trees']]}")


# ── что именно является осадком, а что работой ───────────────────────────────

def test_superseded_intermediate_state_is_reaped(repo):
    """Авария 14.08: `docs/STATE.md` из дерева #227 «нет в истории origin», потому что цикл
    #228 переписал файл ПОСЛЕ него. Работа не потеряна — потеряна актуальность дерева."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_c227")
    (wt / "docs" / "STATE.md").write_text("промежуточное состояние #227\n", encoding="utf-8")
    _age(wt)
    # origin двигается по тому же пути ПОСЛЕ HEAD дерева
    (root / "docs" / "STATE.md").write_text("v2 (цикл #228)\n", encoding="utf-8")
    _run(root, "commit", "-am", "cycle 228")
    _run(root, "push", "origin", "main")
    _log(root, [])

    t = _verdict(_report(root), wt)
    assert t["verdict"] == R.REAP, t["reasons"]
    assert [p["state"] for p in t["paths"]] == [R.SUPERSEDED]


def test_delivered_content_is_recognised_though_uncommitted(repo):
    """Пуш идёт прямо в origin через API — локально работа остаётся НЕЗАКОММИЧЕННОЙ правкой.
    «Незакоммичено» не равно «не доставлено»: точный blob есть в истории origin."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_c192")
    (wt / "docs" / "STATE.md").write_text("доставленное содержимое\n", encoding="utf-8")
    _age(wt)
    (root / "docs" / "STATE.md").write_text("доставленное содержимое\n", encoding="utf-8")
    _run(root, "commit", "-am", "delivered via API")
    (root / "docs" / "STATE.md").write_text("ещё позже\n", encoding="utf-8")
    _run(root, "commit", "-am", "later")
    _run(root, "push", "origin", "main")
    _log(root, [])

    t = _verdict(_report(root), wt)
    assert t["verdict"] == R.REAP
    assert [p["state"] for p in t["paths"]] == [R.DELIVERED]


def test_unique_work_keeps_the_tree(repo):
    """origin по пути НЕ двигался, содержимого в истории нет ⇒ снятие потеряло бы работу."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_c208")
    (wt / "docs" / "STATE.md").write_text("работа, которой нигде больше нет\n", encoding="utf-8")
    _age(wt)
    _log(root, [])

    report = _report(root)
    t = _verdict(report, wt)
    assert t["verdict"] == R.KEEP
    assert "НЕДОСТАВЛЕННАЯ" in t["reasons"][0] and "docs/STATE.md" in t["reasons"][0]
    assert R.exit_code(report) == 1


def test_new_file_absent_on_origin_keeps_the_tree(repo):
    """`spa_wt_rnd49`: `scripts/edge_criterion_consensus.py` на origin нет ВОВСЕ — это и есть
    класс осиротевшей работы #41–#43, ради которого сторож доставки существует."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_rnd49")
    (wt / "scripts").mkdir()
    (wt / "scripts" / "edge_criterion_consensus.py").write_text("# orphan\n", encoding="utf-8")
    _age(wt)
    _log(root, [])

    t = _verdict(_report(root), wt)
    assert t["verdict"] == R.KEEP
    assert [p["state"] for p in t["paths"]] == [R.ABSENT]


def test_untracked_directory_is_expanded_not_swallowed(repo):
    """git схлопывает неотслеживаемый КАТАЛОГ в одну строку — файл внутри обязан быть виден
    (иначе новая работа в новом каталоге снимается молча)."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_dir")
    (wt / "newpkg").mkdir()
    (wt / "newpkg" / "mod.py").write_text("# new\n", encoding="utf-8")
    _age(wt)
    _log(root, [])

    t = _verdict(_report(root), wt)
    assert t["verdict"] == R.KEEP
    assert [p["path"] for p in t["paths"]] == ["newpkg/mod.py"]


# ── что защищает живое дерево ────────────────────────────────────────────────

def test_main_worktree_is_never_reaped(repo):
    root, _ = repo
    _log(root, [])
    t = _verdict(_report(root), root)
    assert t["verdict"] == R.KEEP and "главное" in t["reasons"][0]


def test_fresh_declaration_protects_tree(repo):
    """Владение объявляется АВАНСОМ: в дереве может ещё не быть ни одной правки."""
    root, _ = repo
    wt = _worktree(root, "spa_c230")
    _age(wt)
    _log(root, [{"ts": (NOW - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "files": [str(wt / "scripts" / "new.py")]}])

    t = _verdict(_report(root), wt)
    assert t["verdict"] == R.KEEP and "объявление" in t["reasons"][0]


def test_stale_declaration_does_not_protect_tree(repo):
    root, _ = repo
    wt = _worktree(root, "spa_wt_old")
    _age(wt)
    _log(root, [{"ts": (NOW - timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                 "files": [str(wt / "scripts" / "new.py")]}])

    assert _verdict(_report(root), wt)["verdict"] == R.REAP


def test_recently_touched_tree_is_kept(repo):
    """Сессия могла и не объявляться — свежий файл в дереве тоже признак жизни."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_live")
    _age(wt)
    os.utime(wt / "keep.txt", (NOW_TS - 600, NOW_TS - 600))
    _log(root, [])

    t = _verdict(_report(root), wt)
    assert t["verdict"] == R.KEEP and "изменённый" in t["reasons"][0]


# ── fail-CLOSED ──────────────────────────────────────────────────────────────

def test_unreadable_log_blocks_every_reap(repo):
    """Журнал не прочитан ⇒ занятость деревьев не измерена ⇒ не снимается НИЧЕГО."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_x")
    _age(wt)
    (root / "data" / "session_changes.jsonl").unlink()

    report = _report(root)
    assert _verdict(report, wt)["verdict"] == R.UNMEASURED
    assert not any(t["verdict"] == R.REAP for t in report["trees"])
    assert R.exit_code(report) == 2


def test_broken_git_in_tree_is_unmeasured_not_reaped(repo):
    """«git не отработал» — это измерение, а не разрешение снять дерево."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_broken")
    _age(wt)
    _log(root, [])

    def broken_git(cwd, *args):
        if Path(cwd).resolve() == Path(wt).resolve():
            return 128, "", "fatal: not a git repository"
        return R._git(cwd, *args)

    report = R.build_report(root, "origin/main", root / "data" / "session_changes.jsonl", 24.0,
                            git=broken_git, now=NOW, now_ts=NOW_TS)
    t = _verdict(report, wt)
    assert t["verdict"] == R.UNMEASURED
    assert R.exit_code(report) == 2


def test_unmeasured_path_never_becomes_reapable(repo):
    """Один непрочитанный путь отменяет снятие всего дерева (частичное измерение ≠ вердикт)."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_partial")
    (wt / "docs" / "STATE.md").write_text("что-то\n", encoding="utf-8")
    _age(wt)
    _log(root, [])

    def no_history(cwd, *args):
        if args[:1] == ("log",) and "--raw" in args:
            return 1, "", "boom"
        return R._git(cwd, *args)

    report = R.build_report(root, "origin/main", root / "data" / "session_changes.jsonl", 24.0,
                            git=no_history, now=NOW, now_ts=NOW_TS)
    assert _verdict(report, wt)["verdict"] == R.UNMEASURED
    assert R.exit_code(report) == 2


# ── churn: исключение поимённое и считаемое, а не молчаливое ─────────────────

def test_churn_paths_are_excluded_but_counted(repo):
    """`data/` пишет живой цикл, три точечных пути — прогон тестов (#225). Это след, а не
    работа; отсеянное СЧИТАЕТСЯ и печатается, а не исчезает."""
    root, _ = repo
    (root / "spa_core" / "data").mkdir(parents=True)
    (root / "spa_core" / "data" / "token_emission_log.json").write_text("[]\n", encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-m", "churn files")
    _run(root, "push", "origin", "main")

    wt = _worktree(root, "spa_wt_churn")
    (wt / "data").mkdir(exist_ok=True)
    (wt / "data" / "adapter_status.json").write_text("{}\n", encoding="utf-8")
    (wt / "spa_core" / "data" / "token_emission_log.json").write_text("[1]\n", encoding="utf-8")
    _age(wt)
    _log(root, [])

    t = _verdict(_report(root), wt)
    assert t["verdict"] == R.REAP
    assert t["churn"] >= 1 and t["paths"] == []
    assert "churn" in t["reasons"][0]


def test_source_path_is_never_treated_as_churn(repo):
    """Храповик против соблазна «дописать путь в исключения, чтобы дерево наконец снялось»."""
    assert not any(p.endswith(".py") for p in R.CHURN_PATHS)
    assert R.CHURN_PREFIXES == ("data/",)
    assert "spa_core/risk/policy.py" not in R.CHURN_PATHS


# ── снятие: сначала архив ────────────────────────────────────────────────────

def test_dry_run_removes_nothing(repo):
    root, _ = repo
    wt = _worktree(root, "spa_wt_dry")
    _age(wt)
    _log(root, [])
    assert _verdict(_report(root), wt)["verdict"] == R.REAP
    assert wt.is_dir()


def test_apply_archives_before_removing(tmp_path, repo):
    """Работа не уничтожается, а перестаёт числиться деревом: правка и файлы уезжают в архив."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_arch")
    (wt / "docs" / "STATE.md").write_text("промежуточное\n", encoding="utf-8")
    _age(wt)
    (root / "docs" / "STATE.md").write_text("новее\n", encoding="utf-8")
    _run(root, "commit", "-am", "later")
    _run(root, "push", "origin", "main")
    _log(root, [])

    t = _verdict(_report(root), wt)
    dest, why = R.archive(wt, "origin/main", t["paths"], archive_root=tmp_path / "arch",
                          stamp="STAMP")
    assert why is None, why
    dest = Path(dest)
    assert (dest / "changes.patch").read_text(encoding="utf-8").strip(), "патч пуст"
    assert (dest / "files" / "docs" / "STATE.md").read_text(encoding="utf-8") == "промежуточное\n"
    assert json.loads((dest / "manifest.json").read_text(encoding="utf-8"))["worktree"] == str(wt)

    ok, msg = R.reap(root, wt)
    assert ok, msg
    assert not wt.exists()


def test_archive_failure_cancels_removal(repo, monkeypatch):
    """Архив обязателен: не записался — дерево остаётся на месте (fail-CLOSED)."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_noarch")
    _age(wt)
    _log(root, [])
    monkeypatch.setattr(R, "archive", lambda *a, **k: (None, "диск полон"))
    removed = []
    monkeypatch.setattr(R, "reap", lambda *a, **k: (removed.append(a) or (True, "снято")))

    rc = R.main(["--root", str(root), "--apply", "--json"])
    assert removed == [], "снятие пошло без архива"
    assert rc == 2 and wt.is_dir()


def test_prunable_registration_is_its_own_class(repo):
    """Каталога нет — мерить нечего; это не «не измерено» и не находка."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_gone")
    import shutil
    shutil.rmtree(wt)
    _log(root, [])

    report = _report(root)
    t = _verdict(report, wt)
    assert t["verdict"] == R.PRUNABLE
    assert R.exit_code(report) == 0


# ── квитанция: измерение обязано пережить дерево ─────────────────────────────

def test_receipt_is_written_and_carries_the_verdicts(repo, tmp_path):
    """Без квитанции уборка меняет шило на мыло: шаг 0a про путь внутри снятого дерева
    говорит «измерить нечем» (код 2) — необратимое «не измерено» вместо разбираемой находки."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_rec")
    (wt / "docs" / "STATE.md").write_text("промежуточное\n", encoding="utf-8")
    _age(wt)
    (root / "docs" / "STATE.md").write_text("новее\n", encoding="utf-8")
    _run(root, "commit", "-am", "later")
    _run(root, "push", "origin", "main")
    _log(root, [])

    t = _verdict(_report(root), wt)
    ledger, why = R.record_reap(root, wt, "origin/main", t["paths"], t["churn"],
                                "/arch/x", ledger=tmp_path / "led.jsonl", stamp="STAMP")
    assert why is None, why
    row = json.loads(Path(ledger).read_text(encoding="utf-8").strip())
    assert row["worktree"] == str(wt)
    assert row["paths"] == {"docs/STATE.md": R.SUPERSEDED}
    assert row["archive"] == "/arch/x"


def test_receipt_failure_cancels_removal(repo, monkeypatch, tmp_path):
    """Квитанция обязательна ровно как архив: не записалась — дерево остаётся."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_norec")
    _age(wt)
    _log(root, [])
    monkeypatch.setattr(R, "archive", lambda *a, **k: (str(tmp_path / "arch"), None))
    monkeypatch.setattr(R, "record_reap", lambda *a, **k: (None, "диск полон"))
    removed = []
    monkeypatch.setattr(R, "reap", lambda *a, **k: (removed.append(a) or (True, "снято")))

    rc = R.main(["--root", str(root), "--apply", "--json"])
    assert removed == [] and rc == 2 and wt.is_dir()
