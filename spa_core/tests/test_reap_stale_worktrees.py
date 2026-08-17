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

import importlib
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


# ── #234: инструмент обязан работать оттуда, где по §3.4 работают сессии ─────────
#
# Замер 14.08 из worktree: без `--root` уборщик отказывал целиком («журнал объявлений
# не прочитан» — `data/` в `.gitignore`, в worktree журнала нет и не будет), а щит
# «главное рабочее дерево не снимается» доставался одноразовому дереву ПРОГОНА, тогда
# как ПРОД шёл в кандидаты на общих основаниях и уцелел лишь по случайному свежему
# объявлению. Каждый тест ниже краснеет на неисправленном файле.


def test_shield_belongs_to_the_main_tree_not_to_the_run_root(repo):
    """Прогон ИЗ worktree: щит остаётся у главного дерева, а не переезжает на `--root`.

    Положительный контроль ровно того, что случилось бы с прод-деревом: журнал пуст,
    файлы состарены, правки объяснены ⇒ по старому коду главное дерево получало REAP."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_c234")
    _age(wt)
    _age(root)
    _log(root, [])

    report = R.build_report(wt, "origin/main", root / "data" / "session_changes.jsonl",
                            24.0, now=NOW, now_ts=NOW_TS)
    main_tree = _verdict(report, root)
    assert main_tree["verdict"] == R.KEEP, "главное дерево ушло в кандидаты на снятие"
    assert "главное" in main_tree["reasons"][0]


def test_run_own_tree_is_never_reaped_either(repo):
    """Второй щит: дерево, ОТКУДА идёт прогон, тоже не снимается — но это другая причина."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_self")
    _age(wt)
    _log(root, [])

    t = _verdict(R.build_report(wt, "origin/main", root / "data" / "session_changes.jsonl",
                                24.0, now=NOW, now_ts=NOW_TS), wt)
    assert t["verdict"] == R.KEEP
    assert "прогона" in t["reasons"][0], t["reasons"]


def test_default_root_is_the_main_tree_so_the_journal_is_found(repo, monkeypatch):
    """Без `--root` корень берётся из `git worktree list`, а не из каталога этого файла.

    Иначе журнал ищется в дереве прогона, где его нет: отказ fail-CLOSED честен, но
    инструмент неработоспособен ровно там, где протокол велит работать."""
    root, _ = repo
    _worktree(root, "spa_wt_default")
    _log(root, [])
    monkeypatch.setattr(R, "main_worktree", lambda *a, **k: (root, None), raising=False)

    seen, real = {}, R.build_report
    monkeypatch.setattr(R, "build_report", lambda r, b, lp, g, **kw:
                        (seen.update(root=Path(r), log=Path(lp)), real(r, b, lp, g, **kw))[1])
    R.main(["--json"])

    assert seen["root"] == root
    assert seen["log"] == root / "data" / "session_changes.jsonl"


def test_explicit_root_stays_authoritative(repo, monkeypatch):
    """`--root` — это и есть способ спросить про ДРУГОЕ дерево; догадка его не перебивает."""
    root, _ = repo
    other = _worktree(root, "spa_wt_asked")
    _log(root, [])
    monkeypatch.setattr(R, "main_worktree", lambda *a, **k: (root, None), raising=False)

    seen, real = {}, R.build_report
    monkeypatch.setattr(R, "build_report", lambda r, b, lp, g, **kw:
                        (seen.update(root=Path(r), log=Path(lp)), real(r, b, lp, g, **kw))[1])
    R.main(["--root", str(other), "--json"])

    assert seen["root"] == other
    assert seen["log"] == other / "data" / "session_changes.jsonl"


def test_unresolved_main_tree_is_said_aloud_not_guessed(repo, monkeypatch):
    """Не определилось главное дерево — это НАЗЫВАЕТСЯ (код 2), а не молча гадается."""
    root, _ = repo
    _log(root, [])
    monkeypatch.setattr(R, "main_worktree", lambda *a, **k: (None, "git не ответил"),
                        raising=False)
    monkeypatch.setattr(R, "build_report", lambda r, b, lp, g, **kw:
                        {"root": str(r), "base": b, "grace_hours": g,
                         "trees": [], "unmeasured_reasons": []})

    rc = R.main(["--json"])
    assert rc == 2, "необъяснённый корень прошёл как чистый прогон"


def test_missing_journal_still_blocks_every_reap(repo, monkeypatch):
    """Fail-CLOSED НЕ ослаблен: нечитаемый журнал по-прежнему отменяет снятие целиком."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_nolog")
    _age(wt)
    monkeypatch.setattr(R, "main_worktree", lambda *a, **k: (root, None), raising=False)
    removed = []
    monkeypatch.setattr(R, "reap", lambda *a, **k: (removed.append(a) or (True, "снято")))

    rc = R.main(["--log", str(root / "data" / "no_such.jsonl"), "--apply", "--json"])
    assert rc == 2 and removed == [] and wt.is_dir()


def test_receipt_lands_in_the_main_tree_not_in_a_doomed_one(repo, monkeypatch, tmp_path):
    """Квитанция обязана пережить снятие: в дереве прогона она исчезнет вместе с ним."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_receipt")
    _age(wt)
    _log(root, [])
    monkeypatch.setattr(R, "main_worktree", lambda *a, **k: (root, None), raising=False)
    monkeypatch.setattr(R, "archive", lambda *a, **k: (str(tmp_path / "arch"), None))

    R.main(["--apply", "--json"])

    ledger = root / "data" / "worktree_reap_log.jsonl"
    assert ledger.exists(), "квитанции нет в главном дереве"
    row = json.loads(ledger.read_text(encoding="utf-8").strip().splitlines()[-1])
    assert row["worktree"] == str(wt)


# ── второй реестр того же осадка: ЗАХВАТЫ КАРТОЧЕК мёртвых сессий ────────────

def _tracker(tmp_path, cards):
    """Каталог карточек. `cards` — (идентификатор, статус, держатель, claimed_at)."""
    d = tmp_path / "tracker"
    d.mkdir(exist_ok=True)
    for cid, status, holder, at in cards:
        fm = ["---", "trackerStatus:", "  type: agent-task", f"title: {cid}",
              f"status: {status}"]
        if holder:
            fm += [f"claimed_by: {holder}", f"claimed_at: {at}"]
        fm.append("---")
        (d / f"{cid}.md").write_text("\n".join(fm) + "\n\nтело\n", encoding="utf-8")
    return d


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture
def ps_dead():
    """`ps` отвечает «процесса нет» — активность держателя не подтверждена."""
    return lambda pid: (1, "")


@pytest.fixture
def ps_alive():
    """`ps` показывает процесс, стартовавший ДО захвата ⇒ активность ПОДТВЕРЖДЕНА."""
    started = (NOW - timedelta(hours=400)).astimezone().strftime("%a %b %d %H:%M:%S %Y")
    return lambda pid: (0, started + "\n")


class TestStaleCardClaimsAreNamed:
    """Мёртвая сессия оставляет после себя не только `/tmp`-дерево, но и ЗАХВАТ КАРТОЧКИ.

    Замер трекера 16.08 (карточка `agent-orphaned-work-recurred-after-its-card-was-closed`):
    `agent-fleet-parity-guard-never-scheduled` держит `cycle-28258` с 05.08 — одиннадцать
    суток, — а `inbox-tier-c-pyat-nastoyaschih-otkazov-agregat` держит `cycle-87477` с 06.08.
    Обе сессии мертвы, обе строки `claimed_by` лежат в git и не истекают НИКОГДА, и шаг 0b по
    ним отвечает «занятость не измерена» (ярлык без pid ⇒ `session_state` = UNKNOWN
    детерминированно и необратимо) — то есть взять карточку нельзя, и рассосаться это не может.
    Ровно тот механизм, которым защита от коллизий работает как защита от ПОДЪЁМА.

    Уборщик их **НАЗЫВАЕТ** и ничего не снимает: снятие чужого захвата остаётся ручным
    действием после сверки по шагу 0a (вопрос «блокировать ли подъём» открыт у владельца).
    Ниже — и находка, и обратные контроли: свежий захват, живой держатель, закрытая карточка.
    Время и `ps` подаются ВХОДОМ, дат в фикстурах нет.
    """

    def _rows(self, tracker, tmp_path, ps, grace_hours=24.0, log=None):
        rows, notes = R.stale_claims(tracker, log or (tmp_path / "no_log.jsonl"),
                                     grace_hours, now=NOW, ps=ps)
        return {r["card"]: r for r in rows}, notes

    def test_the_16_08_measurement_is_named(self, tmp_path, ps_dead):
        tracker = _tracker(tmp_path, [
            ("agent-fleet-parity-guard-never-scheduled", "blocked", "cycle-28258",
             _fmt(NOW - timedelta(hours=264))),
            ("inbox-tier-c-pyat-nastoyaschih-otkazov-agregat", "new", "cycle-87477",
             _fmt(NOW - timedelta(hours=233))),
        ])
        rows, _ = self._rows(tracker, tmp_path, ps_dead)
        assert {c: r["state"] for c, r in rows.items()} == {
            "agent-fleet-parity-guard-never-scheduled": R.STALE_CLAIM,
            "inbox-tier-c-pyat-nastoyaschih-otkazov-agregat": R.STALE_CLAIM}
        assert rows["agent-fleet-parity-guard-never-scheduled"]["holder"] == "cycle-28258"
        assert rows["agent-fleet-parity-guard-never-scheduled"]["age_hours"] == 264.0

    def test_a_fresh_claim_is_not_a_finding(self, tmp_path, ps_dead):
        """Обратный контроль: сессия могла умереть, а могла работать — окно на то и окно."""
        tracker = _tracker(tmp_path, [("agent-x", "in-progress", "cycle-1",
                                       _fmt(NOW - timedelta(hours=2)))])
        rows, _ = self._rows(tracker, tmp_path, ps_dead)
        assert rows["agent-x"]["state"] == R.HELD

    def test_a_live_holder_is_not_a_finding_at_any_age(self, tmp_path, ps_alive):
        """Обратный контроль: держатель ЖИВ и измеренно жив — карточка занята по делу."""
        tracker = _tracker(tmp_path, [("agent-x", "in-progress", "pid4242",
                                       _fmt(NOW - timedelta(hours=200)))])
        rows, _ = self._rows(tracker, tmp_path, ps_alive)
        assert rows["agent-x"]["state"] == R.HELD and "ЖИВ" in rows["agent-x"]["why"]

    def test_a_closed_card_is_not_a_finding(self, tmp_path, ps_dead):
        """Обратный контроль: на карточке в терминальном статусе захват не действует —
        это уже действующее правило шага 0b (`TERMINAL_STATUSES`), а не поблажка уборщика."""
        tracker = _tracker(tmp_path, [("agent-x", "done", "cycle-1",
                                       _fmt(NOW - timedelta(hours=300)))])
        rows, _ = self._rows(tracker, tmp_path, ps_dead)
        assert rows == {}

    def test_an_unparsable_claim_time_is_unmeasured_not_free(self, tmp_path, ps_dead):
        tracker = _tracker(tmp_path, [("agent-x", "new", "cycle-1", "позавчера")])
        rows, _ = self._rows(tracker, tmp_path, ps_dead)
        assert rows["agent-x"]["state"] == R.CLAIM_UNMEASURED
        report = {"grace_hours": 24.0, "base": "origin/main", "trees": [],
                  "unmeasured_reasons": [], "claims": list(rows.values()), "claim_notes": []}
        assert R.exit_code(report) == 2

    def test_a_missing_tracker_is_said_out_loud(self, tmp_path, ps_dead):
        rows, notes = self._rows(tmp_path / "нет-такого", tmp_path, ps_dead)
        assert rows == {} and notes and "НЕ измерены" in notes[0]

    def test_the_reaper_does_not_touch_the_card(self, tmp_path, ps_dead):
        """Уборщик НАЗЫВАЕТ, а не снимает: файл карточки обязан остаться байт-в-байт."""
        tracker = _tracker(tmp_path, [("agent-x", "new", "cycle-28258",
                                       _fmt(NOW - timedelta(hours=264)))])
        card = tracker / "agent-x.md"
        before = card.read_bytes()
        self._rows(tracker, tmp_path, ps_dead)
        assert card.read_bytes() == before

    def test_the_verdict_names_the_manual_order(self, tmp_path, ps_dead):
        """Находка без порядка действий превращается в шум, который учатся пролистывать."""
        tracker = _tracker(tmp_path, [("agent-x", "new", "cycle-28258",
                                       _fmt(NOW - timedelta(hours=264)))])
        rows, notes = self._rows(tracker, tmp_path, ps_dead)
        report = {"grace_hours": 24.0, "base": "origin/main", "trees": [],
                  "unmeasured_reasons": [], "claims": list(rows.values()),
                  "claim_notes": notes}
        text = R.render(report)
        assert "ПРОТУХШИЕ ЗАХВАТЫ КАРТОЧЕК" in text
        assert "cycle-28258" in text and "264.0ч" in text
        assert "РУЧНОЕ действие" in text and "шаг" in text
        assert R.exit_code(report) == 1

    def test_the_sweep_is_wired_to_the_tracker(self, repo, tmp_path, monkeypatch, capsys):
        """Проводка: подметающий прогон обязан спрашивать про захваты САМ.

        Без этого теста «механизм есть» означало бы «функция написана и никем не зовётся» —
        ровно тот класс, который в этом репозитории уже ловил храповик неподключённых скриптов.
        """
        root, _ = repo
        _log(root, [])
        tracker = _tracker(tmp_path, [("agent-fleet-parity-guard-never-scheduled", "blocked",
                                       "cycle-28258", _fmt(NOW - timedelta(hours=264)))])
        monkeypatch.setattr(R, "main_worktree", lambda *a, **k: (root, None), raising=False)
        rc = R.main(["--tracker-dir", str(tracker)])
        out = capsys.readouterr().out
        assert "ПРОТУХШИЕ ЗАХВАТЫ КАРТОЧЕК" in out and "cycle-28258" in out
        assert rc == 1

    def test_the_orphan_pickup_scenario_97_98_is_reproduced(self, tmp_path, ps_dead):
        """Сценарий #97→#98 проверкой, а не пересказом (acceptance карточки).

        Цикл #97 умер не доставив, #98 адоптировал работу и умер тоже; #99 получил по шагу 0b
        запрет и прошёл мимо — при красном `main` и готовом лежащем фиксе. Здесь измеряются
        ОБА конца: шаг 0b по-прежнему не пускает (эта граница owner-gated и не тронута), а
        уборщик тот же захват НАЗЫВАЕТ — молчаливого осадка больше нет.
        """
        claim = importlib.import_module("check_card_claim")
        tracker = _tracker(tmp_path, [("agent-telegram-guard-outermost-fails-only-in-full-run",
                                       "in-progress", "cycle-98",
                                       _fmt(NOW - timedelta(hours=264)))])
        log = tmp_path / "session_changes.jsonl"
        log.write_text("", encoding="utf-8")

        report = claim.gather("agent-telegram-guard-outermost-fails-only-in-full-run",
                              log=log, tracker_dir=tracker, self_session="cycle-99",
                              now=NOW, ps=ps_dead, self_anchor=None)
        assert report["verdict"] in (claim.UNCHECKED, claim.CLAIMED, claim.STALE)
        assert claim.exit_code(report) != 0, "шаг 0b пускать не должен — эта граница не тронута"

        rows, _ = self._rows(tracker, tmp_path, ps_dead, log=log)
        named = rows["agent-telegram-guard-outermost-fails-only-in-full-run"]
        assert named["state"] == R.STALE_CLAIM and named["holder"] == "cycle-98"
