"""Уборщик и ЛОКАЛЬНЫЙ коммит дерева: работа, которой он не видел по построению (цикл #294).

До #294 «работой дерева» считалось ПЕРЕСЕЧЕНИЕ двух множеств:

    {git diff --name-only HEAD} ∩ {git diff --name-only <база>}  ∪  {неотслеживаемые}

Файл, закоммиченный в дереве локально (save-point commit — сессии делают его перед
верификацией, а пушер такой коммит отбивает, см. память `savepoint-commit-blocks-the-pusher`),
в `git diff HEAD` не попадает ПО ПОСТРОЕНИЮ: он уже в HEAD. Значит он не входил в пофайловый
вердикт, не копировался в архив и не попадал в квитанцию — дерево снималось, а работа
исчезала молча и без следа.

**Положительный контроль — не выдумка, а замер.** 18.08 на 45 живых деревьях: 10 держали
коммиты, недостижимые с базы, и НИ ОДНО не было защищено ИМИ — каждое уцелело по постороннему
неотслеживаемому файлу (`.claude/settings.local.json`). Рецидив #234: «уцелел по совпадению,
а не по правилу». Тесты ниже воспроизводят обе половины: дерево с недоставленным коммитом и
БЕЗ единого неотслеживаемого файла (сегодняшний уборщик снял бы его) и дерево, коммит которого
уже лежит на базе (обратный контроль — уборка обязана продолжать работать).

Дат в фикстурах нет — время подаётся ВХОДОМ (`now`, `now_ts`), см. `.claude/rules/deployment.md`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import reap_stale_worktrees as R  # noqa: E402


NOW = datetime(2026, 8, 18, 22, 0, tzinfo=timezone.utc)   # FROZEN-DATE-OK: время — ВХОД теста
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


def _commit_in(wt, rel, text, message="save-point"):
    """Закоммитить файл ВНУТРИ дерева и не пушить — тот самый save-point commit."""
    path = Path(wt) / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    _run(wt, "add", "-A")
    _run(wt, "commit", "-m", message)


def _report(root, **kw):
    return R.build_report(root, "origin/main", root / "data" / "session_changes.jsonl",
                          kw.pop("grace_hours", 24.0), now=kw.pop("now", NOW),
                          now_ts=kw.pop("now_ts", NOW_TS), **kw)


def _tree(report, wt):
    got = [t for t in report["trees"] if os.path.realpath(t["path"]) == os.path.realpath(str(wt))]
    assert got, f"дерева {wt} нет в отчёте"
    return got[0]


# --- главная авария: работа лежит в коммите, и её никто не видит ----------------------------

def test_local_commit_of_new_file_keeps_the_tree(repo):
    """Дерево с локальным коммитом файла, которого нет на базе, обязано ОСТАТЬСЯ.

    Ни одного неотслеживаемого файла в дереве нет намеренно: до #294 именно посторонний
    неотслеживаемый файл был единственным, что удерживало такие деревья живьём."""
    root, _ = repo
    wt = _worktree(root, "spa_local_commit")
    _commit_in(wt, "scripts/edge_criterion_consensus.py", "print('работа сессии')\n")
    _age(wt)

    t = _tree(_report(root), wt)

    assert t["verdict"] == R.KEEP, t["reasons"]
    assert any("НЕДОСТАВЛЕННАЯ работа" in r for r in t["reasons"]), t["reasons"]
    assert "scripts/edge_criterion_consensus.py" in " ".join(t["reasons"]), t["reasons"]


def test_local_commit_path_is_named_in_the_per_path_verdict(repo):
    """Путь коммита обязан попасть в ПОФАЙЛОВЫЙ вердикт — иначе его нет ни в архиве, ни в квитанции."""
    root, _ = repo
    wt = _worktree(root, "spa_commit_verdict")
    _commit_in(wt, "scripts/edge_criterion_consensus.py", "print('работа сессии')\n")
    _age(wt)

    t = _tree(_report(root), wt)

    named = {v["path"]: v["state"] for v in t["paths"]}
    assert "scripts/edge_criterion_consensus.py" in named, named
    assert named["scripts/edge_criterion_consensus.py"] == R.ABSENT, named


def test_committed_modification_of_existing_file_keeps_the_tree(repo):
    """Не только НОВЫЙ файл: закоммиченная правка существующего пути тоже была невидима."""
    root, _ = repo
    wt = _worktree(root, "spa_commit_modify")
    _commit_in(wt, "docs/STATE.md", "v2 — работа сессии\n")
    _age(wt)

    t = _tree(_report(root), wt)

    assert t["verdict"] == R.KEEP, t["reasons"]
    assert "docs/STATE.md" in " ".join(t["reasons"]), t["reasons"]
    assert {v["path"]: v["state"] for v in t["paths"]}["docs/STATE.md"] == R.UNIQUE


def test_unpushed_commit_count_is_measured_and_reported(repo):
    """Число коммитов сверх базы — ИЗМЕРЕНИЕ, а не догадка: оно лежит в отчёте машинно."""
    root, _ = repo
    wt = _worktree(root, "spa_commit_count")
    _commit_in(wt, "a.txt", "1\n", message="save-point 1")
    _commit_in(wt, "b.txt", "2\n", message="save-point 2")
    _age(wt)

    assert _tree(_report(root), wt)["unpushed_commits"] == 2


# --- обратный контроль: уборка обязана продолжать работать ----------------------------------

def test_tree_without_local_commits_still_reaps(repo):
    """Обычное мёртвое дерево (коммитов сверх базы нет) снимается ровно как раньше.

    Обратный контроль: он обязан быть ЗЕЛЁНЫМ и на непочиненном origin — потому и не
    спрашивает ни одного нового поля."""
    root, _ = repo
    wt = _worktree(root, "spa_plain_dead")
    _age(wt)

    assert _tree(_report(root), wt)["verdict"] == R.REAP


def test_commit_already_on_base_still_reaps(repo):
    """Коммит, УЖЕ лежащий на базе, снятию не мешает — иначе уборка встанет совсем.

    Ровно этого требует карточка: обратный контроль обязателен. Он зелёный и на origin."""
    root, _ = repo
    wt = _worktree(root, "spa_commit_pushed")
    _commit_in(wt, "shipped.txt", "доставлено\n")
    _run(wt, "push", "origin", "HEAD:main")
    _run(root, "fetch", "origin", "main")
    _age(wt)

    assert _tree(_report(root), wt)["verdict"] == R.REAP


def test_delivered_content_in_a_commit_does_not_block_reaping(repo):
    """Содержимое коммита есть в истории базы ⇒ работа доставлена ⇒ дерево снимается.

    «Лежит коммитом» само по себе не есть «не доставлено»: судит содержимое, а не форма."""
    root, _ = repo
    wt = _worktree(root, "spa_commit_delivered")
    # то же содержимое по тому же пути уезжает на базу ЧЕРЕЗ ДРУГОЕ дерево (как это делает пушер)
    (root / "docs" / "STATE.md").write_text("v2 — доставлено\n", encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-m", "доставка")
    _run(root, "push", "origin", "main")
    _run(root, "fetch", "origin", "main")
    _commit_in(wt, "docs/STATE.md", "v2 — доставлено\n")
    _age(wt)

    t = _tree(_report(root), wt)

    assert t["verdict"] == R.REAP, t["reasons"]
    # Путь коммита НАЗВАН доставленным, а не пропущен молча: снятие такого дерева безопасно
    # именно потому, что содержимое сверено с историей базы, а не потому, что его не видели.
    assert {v["path"]: v["state"] for v in t["paths"]}.get("docs/STATE.md") == R.DELIVERED


# --- границы: несопоставимая история и churn ------------------------------------------------

def test_incomparable_history_keeps_without_per_path_verdict(repo, monkeypatch):
    """История без общего предка с базой: дерево ОСТАЁТСЯ, пути не перечисляются.

    Замер 18.08: у 9 из 45 живых деревьев `merge-base` с базой пуст, а «коммитов сверх базы»
    — 23 283. Перечислять их пофайлово нечего и незачем; отказ обязан быть назван числом."""
    root, _ = repo
    wt = _worktree(root, "spa_incomparable")
    # raising=False — чтобы на НЕПОЧИНЕННОМ модуле тест краснел ПОВЕДЕНИЕМ (дерево снимается),
    # а не отсутствием константы: «нет такого атрибута» о потере работы не говорит ничего.
    monkeypatch.setattr(R, "COMMITTED_PATHS_CAP", 2, raising=False)
    for i in range(4):
        _commit_in(wt, f"f{i}.txt", f"{i}\n", message=f"save-point {i}")
    _age(wt)

    t = _tree(_report(root), wt)

    assert t["verdict"] == R.KEEP, t["reasons"]
    assert t["paths"] == [], "пофайловый вердикт выше потолка не выносится"
    assert "больше потолка" in " ".join(t["reasons"]), t["reasons"]
    assert "4" in " ".join(t["reasons"]), t["reasons"]


def test_committed_data_churn_does_not_keep_a_tree(repo):
    """`data/` — след живого цикла, а не работа сессии: закоммиченный churn снятию не мешает.

    Обратный контроль (зелёный и на origin): расширение «работы» коммитами не смеет
    превратить след цикла в вечный KEEP — иначе уборка встанет на каждом дереве."""
    root, _ = repo
    wt = _worktree(root, "spa_commit_churn")
    _commit_in(wt, "data/analytics_report.json", "{}\n")
    _age(wt)

    t = _tree(_report(root), wt)

    assert t["verdict"] == R.REAP, t["reasons"]
    assert t["paths"] == []


def test_churn_path_counted_once_when_both_edited_and_committed(repo):
    """Один и тот же churn-путь в правке И в коммите считается ОДИН раз.

    Два счётчика сложить без двойного счёта нельзя — пересечение видно только у множеств;
    ради этого `work_paths` и отдаёт множество, а не число."""
    root, _ = repo
    wt = _worktree(root, "spa_churn_once")
    _commit_in(wt, "data/analytics_report.json", "{}\n")
    (Path(wt) / "data" / "analytics_report.json").write_text('{"ещё": 1}\n', encoding="utf-8")
    _age(wt)

    t = _tree(_report(root), wt)

    assert t["verdict"] == R.REAP, t["reasons"]
    assert t["churn"] == 1, t


def test_unmeasurable_commit_range_refuses_fail_closed(repo):
    """`git` не ответил про диапазон ⇒ `unmeasured`, а НЕ снятие (fail-CLOSED).

    Сломанный git подаётся ВХОДОМ (`git=`), а не подменой атрибута модуля: `inspect` берёт
    его умолчанием параметра, и подмена `R._git` до вердикта не доезжает вовсе — тест бы
    ЗЕЛЕНЕЛ на непочиненном коде."""
    root, _ = repo
    wt = _worktree(root, "spa_commit_unmeasured")
    _age(wt)

    def broken(cwd, *args):
        if args and args[0] == "rev-list":
            return 128, "", "fatal: bad revision"
        return R._git(cwd, *args)

    regs, why = R.list_registrations(root)
    assert regs is not None, why
    reg = next(r for r in regs
               if os.path.realpath(r["path"]) == os.path.realpath(str(wt)))
    t = R.inspect(root, reg, "origin/main", [], 24.0, git=broken, now_ts=NOW_TS)

    assert t["verdict"] == R.UNMEASURED, t["reasons"]
    assert "rev-list" in " ".join(t["reasons"]), t["reasons"]


def test_unmeasurable_commit_paths_refuse_fail_closed(repo):
    """Коммиты есть, а список их путей git не отдал ⇒ `unmeasured`, а не снятие."""
    root, _ = repo
    wt = _worktree(root, "spa_commit_paths_unmeasured")
    _commit_in(wt, "orphan.txt", "работа\n")
    _age(wt)

    def broken(cwd, *args):
        # Сверять args[0] нельзя: вызов идёт с префиксом `-c core.quotepath=false`, и такой
        # предикат молча не срабатывает вовсе — тест зеленел бы, ничего не сломав.
        if "log" in args and "--name-only" in args and "--format=" in args:
            return 128, "", "fatal: bad revision"
        return R._git(cwd, *args)

    regs, why = R.list_registrations(root)
    assert regs is not None, why
    reg = next(r for r in regs
               if os.path.realpath(r["path"]) == os.path.realpath(str(wt)))
    t = R.inspect(root, reg, "origin/main", [], 24.0, git=broken, now_ts=NOW_TS)

    assert t["verdict"] == R.UNMEASURED, t["reasons"]
    assert t["unpushed_commits"] == 1, t


def test_commit_range_is_measured_without_merge_base(repo):
    """Ложный ноль, полученный ЖИВЬЁМ при разборе карточки, закреплён тестом.

    У дерева с НЕСОПОСТАВИМОЙ историей общего предка с базой нет, и `merge-base` возвращает
    ПУСТО. Подстановка пустой строки в диапазон даёт `..HEAD`, то есть `HEAD..HEAD` — ровно
    ноль коммитов на дереве, где их 23 283 (замер 18.08, 9 деревьев из 45). Первый замер этой
    самой карточки был сделан именно так и сказал «случай не наблюдается»; починки бы не было.
    Поэтому диапазон берётся разностью множеств `<база>..HEAD`, которой предок не нужен."""
    root, _ = repo
    wt = _worktree(root, "spa_orphan_history")
    _run(wt, "switch", "--orphan", "orphan-history")
    _commit_in(wt, "orphan.txt", "работа сессии\n", message="корень чужой истории")
    _age(wt)

    # rc=1 и пустой вывод — это и есть «общего предка нет»; через `_run` не идём, он ждёт rc=0.
    mb = subprocess.run(["git", "-C", str(wt), "merge-base", "HEAD", "origin/main"],
                        capture_output=True, text=True)
    assert mb.stdout.strip() == "", (
        "фикстура обязана давать ПУСТОЙ merge-base — иначе тест проверяет не то")

    count, paths, why = R.committed_paths(wt, "origin/main")

    assert why is None, why
    assert count == 1, count
    assert paths == ["orphan.txt"]
    # и вердикт целиком: такое дерево обязано остаться
    assert _tree(_report(root), wt)["verdict"] == R.KEEP


# --- квитанция: её полноту теперь можно проверить задним числом ------------------------------

def test_receipt_carries_head_and_commit_count(repo, tmp_path):
    """`head` в квитанции — то, чем шаг 0a проверит её полноту, а не поверит на слово."""
    root, _ = repo
    wt = _worktree(root, "spa_receipt_head")
    _age(wt)
    t = _tree(_report(root), wt)
    ledger = tmp_path / "reap_log.jsonl"

    path, why = R.record_reap(root, t["path"], "origin/main", t["paths"], t["churn"], None,
                              ledger=ledger, head=t["head"],
                              unpushed_commits=t.get("unpushed_commits"))

    assert why is None, why
    row = json.loads(Path(path).read_text(encoding="utf-8").strip())
    assert row["head"] == t["head"] and len(row["head"]) == 40
    assert row["unpushed_commits"] == 0
