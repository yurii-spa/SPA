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


# ── база сначала ЧИТАЕТСЯ, и только потом судит (цикл #283) ──────────────────
#
# Живая авария 17.08 (дерево цикла #282): файл карточки, байт-в-байт равный `origin/main`,
# объявлен `unique` — «здесь может лежать НЕДОСТАВЛЕННАЯ работа». Причина не в сравнении с
# базой дерева, как читалось сначала, а в том, что базу НИКТО НЕ ЧИТАЛ: пуш идёт прямо в origin
# через API, локальный `refs/remotes/origin/main` при этом не двигается. Каждый цикл пушит из
# дерева ⇒ ложный отказ был нормой, и уборка стояла именно на нём.


def _push_to_origin(tmp_path, origin, rel, content, msg):
    """Доставить содержимое ПРЯМО в origin, минуя `root` — так работает пуш через API.

    Локальный `refs/remotes/origin/main` у `root` от этого не двигается: ровно то состояние,
    в котором уборщик судил доставку по снимку неизвестной давности."""
    side = tmp_path / f"side-{abs(hash(msg)) % 10**6}"
    _run(tmp_path, "clone", str(origin), str(side))
    path = side / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    _run(side, "add", "-A")
    _run(side, "commit", "-m", msg)
    _run(side, "push", "origin", "main")


def test_delivered_while_local_ref_stale_is_reaped(repo, tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ аварии 17.08: содержимое лежит на origin, локальный ref отстал.

    На неисправленном коде это `unique` + KEEP («НЕДОСТАВЛЕННАЯ работа») — тот самый ложный
    отказ, из-за которого уборку каждый раз чинили руками через `git reset`."""
    root, origin = repo
    wt = _worktree(root, "spa_wt_c282")
    delivered = "доставлено циклом #282\n"
    (wt / "docs" / "STATE.md").write_text(delivered, encoding="utf-8")
    _push_to_origin(tmp_path, origin, "docs/STATE.md", delivered, "deliver via API")
    _age(wt)
    _log(root, [])

    # Предпосылка аварии: локальный ref ОТСТАЛ — доставку через API он не видел.
    assert _run(root, "rev-parse", "origin/main").strip() != _run(
        root, "ls-remote", str(origin), "main").split()[0]

    t = _verdict(_report(root), wt)
    # Прочитав базу, уборщик видит: расхождения с ней нет вовсе — значит и «недоставленного»
    # тут нет. На неисправленном коде ровно этот путь звался `unique`.
    assert t["verdict"] == R.REAP, t["reasons"]
    assert "НЕДОСТАВЛЕННАЯ" not in " ".join(t["reasons"])
    assert [p for p in t["paths"] if p["state"] in (R.UNIQUE, R.ABSENT)] == []


def test_intermediate_delivered_version_survives_a_stale_ref(repo, tmp_path):
    """Тот же класс, но содержимое дерева — УЖЕ ПЕРЕКРЫТАЯ доставленная версия.

    Здесь путь остаётся в отчёте и обязан получить `delivered`: его blob лежит в истории базы.
    На неисправленном коде устаревший ref не знает ни одной из двух версий ⇒ `unique`."""
    root, origin = repo
    wt = _worktree(root, "spa_wt_mid")
    (wt / "docs" / "STATE.md").write_text("версия X\n", encoding="utf-8")
    _push_to_origin(tmp_path, origin, "docs/STATE.md", "версия X\n", "deliver X")
    _push_to_origin(tmp_path, origin, "docs/STATE.md", "версия Y\n", "supersede with Y")
    _age(wt)
    _log(root, [])

    t = _verdict(_report(root), wt)
    assert [p["state"] for p in t["paths"]] == [R.DELIVERED], t["paths"]
    assert t["verdict"] == R.REAP, t["reasons"]


def test_stale_ref_cannot_invent_a_delivery_only_hide_one(repo, tmp_path):
    """ОБРАТНЫЙ КОНТРОЛЬ: настоящая недоставленная правка остаётся недоставленной и после fetch.

    Иначе «починка» свелась бы к тому, что уборщик перестал отказывать вообще."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_real")
    (wt / "docs" / "STATE.md").write_text("работы этой нет нигде\n", encoding="utf-8")
    _age(wt)
    _log(root, [])

    t = _verdict(_report(root), wt)
    assert t["verdict"] == R.KEEP
    assert [p["state"] for p in t["paths"]] == [R.UNIQUE]
    assert "НЕДОСТАВЛЕННАЯ" in t["reasons"][0]


def test_unread_base_is_named_not_dressed_as_undelivered_work(repo):
    """База не прочитана ⇒ отказ ОСТАЁТСЯ, но называется своей причиной (код 2, не 1).

    Ослабления нет: дерево по-прежнему не снимается. Ушла ЛОЖЬ о причине — «не спросили
    origin» больше не выдаётся за «здесь лежит недоставленная работа»."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_offline")
    (wt / "docs" / "STATE.md").write_text("что-то\n", encoding="utf-8")
    _age(wt)
    _log(root, [])

    report = _report(root, base_read=(False, "сети нет"))
    t = _verdict(report, wt)
    assert t["verdict"] == R.UNMEASURED, t
    assert "не прочитана" in t["reasons"][0] and "сети нет" in t["reasons"][0]
    assert "НЕДОСТАВЛЕННАЯ" not in t["reasons"][0]
    assert R.exit_code(report) == 2


def test_unread_base_still_reaps_on_positive_evidence(repo, tmp_path):
    """Асимметрия названа и закреплена: несвежая база прячет доставку, но не выдумывает.

    Значит `delivered`/`superseded` — положительные свидетельства — судят как раньше даже
    без чтения базы; неизмеримыми делаются РОВНО отрицательные вердикты."""
    root, origin = repo
    wt = _worktree(root, "spa_wt_pos")
    _push_to_origin(tmp_path, origin, "docs/STATE.md", "версия X\n", "deliver X")
    _push_to_origin(tmp_path, origin, "docs/STATE.md", "версия Y\n", "supersede with Y")
    _run(root, "fetch", "origin")                     # база прочитана ЗАРАНЕЕ, не прогоном
    (wt / "docs" / "STATE.md").write_text("версия X\n", encoding="utf-8")
    _age(wt)
    _log(root, [])

    report = _report(root, base_read=(False, "офлайн"))
    t = _verdict(report, wt)
    assert [p["state"] for p in t["paths"]] == [R.DELIVERED]
    assert t["verdict"] == R.REAP, t["reasons"]


def test_refresh_base_failure_is_named_not_swallowed(repo):
    """Неудача чтения базы обязана вернуться ПРИЧИНОЙ, а не тихим «всё хорошо»."""
    root, _ = repo
    ok, why = R.refresh_base(root, "no_such_remote/main")
    assert ok is False and "no_such_remote" in why

    ok, why = R.refresh_base(root, "origin")          # не вида <remote>/<branch>
    assert ok is False and "<remote>/<branch>" in why


def test_refresh_base_reads_the_ref_the_verdict_uses(repo, tmp_path):
    """Читать надо ИМЕННО `refs/remotes/<remote>/<branch>` — вердикт считается по нему.

    `FETCH_HEAD` здесь не годится: `classify_path` ходит в `origin/main`."""
    root, origin = repo
    before = _run(root, "rev-parse", "origin/main").strip()
    _push_to_origin(tmp_path, origin, "docs/STATE.md", "двинули базу\n", "move base")
    assert _run(root, "rev-parse", "origin/main").strip() == before, "ref не должен был двинуться сам"

    ok, why = R.refresh_base(root, "origin/main")
    assert ok is True, why
    assert _run(root, "rev-parse", "origin/main").strip() != before


def test_refresh_base_does_not_lean_on_remote_config(repo, tmp_path):
    """Ссылку двигает НАШ refspec, а не настройка `remote.origin.fetch` в чужом репозитории.

    Найдено мутацией цикла #286 (она ВЫЖИЛА на исходном наборе): замена явного refspec на
    голое `git fetch origin main` не роняла ни один тест — потому что во всех фикстурах
    репозиторий получен `clone`, а у него `remote.origin.fetch` задан, и git двигает
    remote-tracking ссылку попутно (opportunistic update). Стоило снять эту настройку — и
    голая форма перестаёт двигать ссылку вовсе (замерено: `moved=NO` против `moved=YES`),
    то есть вердикт снова считался бы по снимку неизвестной давности, но уже МОЛЧА: сам
    `fetch` при этом успешен, `refresh_base` вернул бы «прочитана».

    ЧЕСТНО: в проде `remote.origin.fetch` задан (`+refs/heads/*:refs/remotes/origin/*`), так
    что живой поломки этот тест не чинит — он закрепляет причину, которую докстринг
    `refresh_base` уже объявил своей, чтобы она не осталась одним лишь обещанием."""
    root, origin = repo
    _run(root, "config", "--unset", "remote.origin.fetch")
    before = _run(root, "rev-parse", "origin/main").strip()
    _push_to_origin(tmp_path, origin, "docs/STATE.md", "двинули базу без refspec\n", "no refspec")

    ok, why = R.refresh_base(root, "origin/main")
    assert ok is True, why
    assert _run(root, "rev-parse", "origin/main").strip() != before, (
        "ссылка не двинулась без `remote.origin.fetch` — читается FETCH_HEAD, а вердикт "
        "считается по refs/remotes/origin/main")


def test_report_always_says_what_it_measured_against(repo):
    """Чем мерили — печатается всегда, а не только когда не получилось."""
    root, _ = repo
    _log(root, [])
    assert "прочитана перед вердиктом" in R.render(_report(root))
    assert "офлайн-прогон" in R.render(_report(root, base_read=(False, "офлайн-прогон")))


# ── путь, которого дерево НИКОГДА не выкладывало (цикл #377) ──────────────────
#
# Замер #376, воспроизведённый здесь целиком — от `git init` до вердикта. Состояние приходит
# из СТАНДАРТНОГО хода протокола: страж перезаписи пушера отбивает пуш, предписанное
# `CLAUDE.md` лечение — перенести правку на свежий origin и переставить HEAD
# (`git reset --mixed origin/main`), после чего HEAD перечисляет чужие пути, которых дерево
# никогда не выкладывало. Уборщик объявлял их «недоставленной работой» и дерево не снимал.

def _reset_onto_fresh_origin(root, wt):
    """Лечение отбитого пуша по протоколу: перенести HEAD дерева на свежий `origin/main`."""
    _run(root, "fetch", "origin")
    _run(wt, "fetch", "origin")
    _run(wt, "reset", "--mixed", "origin/main")


def test_path_this_tree_never_checked_out_does_not_hold_it(repo, tmp_path):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ #376: чужой путь, приехавший в HEAD переносом на свежий origin.

    На диске дерева файла НЕТ, на origin он ЕСТЬ — терять нечему, а вердикт был вывернут
    наизнанку: `unique`, «здесь может лежать НЕДОСТАВЛЕННАЯ работа». На неисправленном модуле
    тест краснеет: дерево остаётся KEEP навсегда."""
    root, origin = repo
    wt = _worktree(root, "spa_c376")
    _push_to_origin(tmp_path, origin, "scripts/alien.py", "# чужая работа R&D\n", "alien work")
    _reset_onto_fresh_origin(root, wt)
    _age(wt)
    _log(root, [])

    t = _verdict(_report(root), wt)
    assert [p["state"] for p in t["paths"]] == [R.NOT_IN_TREE], t["paths"]
    assert t["verdict"] == R.REAP, t["reasons"]


def test_deleted_file_this_tree_did_check_out_still_holds_it(repo):
    """ОБРАТНЫЙ КОНТРОЛЬ: удаление ВЫЛОЖЕННОГО файла — тоже возможная работа сессии.

    Отличие меряется stat-записью индекса, а не догадкой о том, как дерево пришло в это
    состояние: у выложенного файла `ino`/`ctime` настоящие. Послабления нет — `unique`."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_deleter")
    os.remove(wt / "keep.txt")
    _age(wt)
    _log(root, [])

    t = _verdict(_report(root), wt)
    assert [p["state"] for p in t["paths"]] == [R.UNIQUE], t["paths"]
    assert t["verdict"] == R.KEEP, t["reasons"]


def test_deleted_empty_file_is_not_mistaken_for_never_checked_out(repo):
    """У пустого файла нулевой `size` — и ровно на нём признак «нулей в индексе» сломался бы,
    возьми он `size`. Берутся `ino`/`ctime`: у выложенного пустого файла они настоящие."""
    root, _ = repo
    (root / "empty.txt").write_text("", encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-m", "empty file")
    _run(root, "push", "origin", "main")
    wt = _worktree(root, "spa_wt_empty")
    os.remove(wt / "empty.txt")
    _age(wt)
    _log(root, [])

    t = _verdict(_report(root), wt)
    assert [p["state"] for p in t["paths"]] == [R.UNIQUE], t["paths"]
    assert t["verdict"] == R.KEEP, t["reasons"]


def test_content_matching_origin_on_disk_stays_delivered(repo):
    """Симметричная половина (п. 2 карточки): путь ЕСТЬ и на диске, и на базе, содержимое
    совпадает ⇒ `delivered`. Сегодня это работает, но тестом закреплено не было — и первая же
    правка ветки «файла на диске нет» ломала бы его молча."""
    root, _ = repo
    wt = _worktree(root, "spa_wt_same")
    (wt / "docs" / "STATE.md").write_text("v1\n", encoding="utf-8")   # байт-в-байт как на базе
    (wt / "untracked.txt").write_text("держит дерево\n", encoding="utf-8")
    _age(wt)
    _log(root, [])

    t = _verdict(_report(root), wt)
    states = {p["path"]: p["state"] for p in t["paths"]}
    assert states.get("docs/STATE.md", R.DELIVERED) == R.DELIVERED, states


def test_unmeasured_index_stat_keeps_the_stricter_verdict(repo, tmp_path):
    """FAIL-CLOSED: stat-запись индекса прочитать не удалось ⇒ судим как раньше (`unique`),
    а не в пользу снятия. Признак не имеет права быть тихой кнопкой «снять что угодно»."""
    root, origin = repo
    wt = _worktree(root, "spa_c376_blind")
    _push_to_origin(tmp_path, origin, "scripts/alien.py", "# чужая работа\n", "alien blind")
    _reset_onto_fresh_origin(root, wt)
    head = _run(wt, "rev-parse", "HEAD").strip()

    def _mute_ls_files(cwd, *args):
        if args and args[0] == "ls-files":
            return 1, "", "boom"
        return R._git(cwd, *args)

    assert R._never_materialised(str(wt), "scripts/alien.py", git=_mute_ls_files) is None
    state, _why = R.classify_path(str(root), "origin/main", head, str(wt), "scripts/alien.py",
                                  git=_mute_ls_files)
    assert state == R.UNIQUE, state
