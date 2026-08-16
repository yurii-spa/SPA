"""«Убрать за собой» обязано быть ИЗМЕРЕННЫМ действием (цикл #257).

**Авария, которую воспроизводит каждый тест здесь — 16.08.** Цикл #256 доставил работу на
`origin/main` (HEAD `2adf5de8a`) и по-хорошему убрал за собой: `git worktree remove` на своё
`/tmp/spa_c256`. Квитанции снятия при этом не осталось ни одной, и шаг 0a на следующем заходе
выдал **12 строк «НЕ ИЗМЕРЕНО» и код 2** — навсегда: байтов больше нет ни в дереве, ни в
архиве, и вопрос «доехала ли работа» ответа уже не получит никогда.

Причина — не в шаге 0a. Правило уборки (`reap_stale_worktrees.py`, цикл #230) отвечает на
вопрос «дерево МЁРТВОЕ?», и для сессии, которая только что доставила и убирает за собой,
честный ответ всегда «нет»: её объявление свежее, файлы изменены минуту назад. То есть
измеренного способа убрать за собой не существовало вовсе, а обе оставшиеся возможности плохи:
снять руками ⇒ необратимое «не измерено» (класс «морит очередь»), не снимать ⇒ тот самый осадок
из 70 мёртвых деревьев, ради которого #230 и писался.

Здесь проверяются ОБЕ половины починки и, отдельными обратными контролями, то, что не сдвинулось:

* явный режим `--worktree` снимает ровно признаки «сессия молчит» — и НЕ снимает пофайловый
  вердикт: недоставленная работа по-прежнему отменяет снятие;
* подметающий прогон не изменился ни в одном вердикте;
* шаг 0a сжимает осадок «дерево снято руками» в одну строку на дерево, не теряя ни записи и
  не смягчая код возврата.

Тесты гоняют настоящий git на временном репозитории (сети нет, «origin» — локальный bare).
Литеральных дат в фикстурах нет: время подаётся ВХОДОМ (`now`, `now_ts`).
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: правило снятия судит по истории origin "
           "(условный skipif — на машине с git тесты выполняются)",
)

import reap_stale_worktrees as R  # noqa: E402


def _guard():
    """Шаг 0a грузится по явному пути: `scripts/` — не пакет."""
    path = ROOT / "scripts" / "check_undelivered_work.py"
    spec = importlib.util.spec_from_file_location("_test_self_reap_guard", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


NOW = datetime(2026, 8, 16, 8, 0, tzinfo=timezone.utc)   # FROZEN-DATE-OK: время — ВХОД теста
NOW_TS = NOW.timestamp()


def _run(cwd, *args):
    env = dict(os.environ)
    env.update({"GIT_CONFIG_NOSYSTEM": "1", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})
    p = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, env=env)
    assert p.returncode == 0, f"git {args} -> {p.returncode}: {p.stderr}"
    return p.stdout


@pytest.fixture
def repo(tmp_path):
    """(root, origin) — рабочий репозиторий с настоящим `origin/main`."""
    origin = tmp_path / "origin.git"
    _run(tmp_path, "init", "--bare", "-b", "main", str(origin))
    root = tmp_path / "work"
    _run(tmp_path, "clone", str(origin), str(root))
    (root / "docs").mkdir()
    (root / "docs" / "STATE.md").write_text("v1\n", encoding="utf-8")
    (root / "docs" / "OTHER.md").write_text("v1\n", encoding="utf-8")
    _run(root, "add", "-A")
    _run(root, "commit", "-m", "base")
    _run(root, "push", "origin", "main")
    (root / "data").mkdir()
    (root / "data" / "session_changes.jsonl").write_text("", encoding="utf-8")
    return root, origin


def _worktree(root, name):
    wt = root.parent / name
    _run(root, "worktree", "add", "--detach", str(wt), "HEAD")
    return wt


def _announce(root, wt, files, ts=None):
    """Свежее объявление владения путями внутри дерева — как его пишет живая сессия."""
    ts = ts or NOW.strftime("%Y-%m-%dT%H:%M:%SZ")
    row = {"ts": ts, "session": "cycle-256", "summary": "доставил, убираю за собой",
           "files": [str(Path(wt) / f) for f in files]}
    path = root / "data" / "session_changes.jsonl"
    path.write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _deliver(root, rel, text):
    """Работа уехала на origin (в проде — прямым пушем через API)."""
    (root / rel).write_text(text, encoding="utf-8")
    _run(root, "commit", "-am", f"deliver {rel}")
    _run(root, "push", "origin", "main")


def _sweep(root, **kw):
    return R.build_report(root, "origin/main", root / "data" / "session_changes.jsonl",
                          kw.pop("grace_hours", 24.0), now=kw.pop("now", NOW),
                          now_ts=kw.pop("now_ts", NOW_TS), **kw)


def _self(root, target, **kw):
    return R.build_self_report(root, "origin/main", target,
                               root / "data" / "session_changes.jsonl",
                               kw.pop("grace_hours", 24.0), now=kw.pop("now", NOW),
                               now_ts=kw.pop("now_ts", NOW_TS),
                               cwd=kw.pop("cwd", root), **kw)


def _verdict(report, wt):
    for t in report["trees"]:
        if Path(t["path"]).resolve() == Path(wt).resolve():
            return t
    raise AssertionError(f"{wt} нет в отчёте: {[t['path'] for t in report['trees']]}")


def _delivered_tree(root, name="spa_c256"):
    """Дерево ровно в состоянии #256: работа доставлена, сессия ещё «шумит».

    Содержимое дерева уехало на origin (пуш идёт прямо туда через API, локально правка так и
    остаётся незакоммиченной), а затем база по тому же пути ушла дальше — так и живёт
    `docs/STATE.md`, который правит КАЖДЫЙ цикл. Поэтому путь расходится с текущим
    `origin/main`, но его точный blob есть в истории ⇒ вердикт `delivered`."""
    wt = _worktree(root, name)
    (wt / "docs" / "STATE.md").write_text(f"работа {name}\n", encoding="utf-8")
    _deliver(root, "docs/STATE.md", f"работа {name}\n")
    _deliver(root, "docs/STATE.md", f"следующий цикл после {name}\n")
    _announce(root, wt, ["docs/STATE.md"])
    return wt


# ── половина 1: у сессии не было измеренного способа убрать за собой ─────────

def test_sweep_cannot_reap_the_tree_of_a_session_that_just_delivered(repo):
    """Положительный контроль САМОГО дефекта 16.08: работа доставлена вся, но подметающий
    прогон дерево не снимет — сессия «шумит» по построению (она только что закончила).
    Именно отсюда брался `git worktree remove` руками и необратимое «не измерено»."""
    root, _ = repo
    wt = _delivered_tree(root)

    t = _verdict(_sweep(root), wt)
    assert t["verdict"] == R.KEEP, t["reasons"]
    assert any("свежее объявление" in r for r in t["reasons"]), t["reasons"]


def test_explicit_request_reaps_own_fresh_tree_when_every_path_is_delivered(repo):
    """Та же секунда, то же дерево, тот же журнал — но дерево названо владельцем поимённо.
    Признаки «сессия молчит» перекрыты запросом, вердикт по путям обычный ⇒ снимается."""
    root, _ = repo
    wt = _delivered_tree(root)

    t = _verdict(_self(root, wt), wt)
    assert t["verdict"] == R.REAP, t["reasons"]
    assert [p["state"] for p in t["paths"]] == [R.DELIVERED]


def test_explicit_request_names_what_it_overrode_instead_of_skipping_silently(repo):
    """Пропуск проверки обязан быть ВИДЕН в отчёте: сколько объявлений внутри и был ли
    свежий файл. Молчаливое «просто не проверял» — это и есть глохнущий сторож."""
    root, _ = repo
    wt = _delivered_tree(root)

    t = _verdict(_self(root, wt), wt)
    said = " ".join(t["reasons"])
    assert "свежих объявлений внутри: 1" in said, said
    assert "файл свежее 24ч: да" in said, said


# ── половина 2: гарантия, которую явный режим НЕ снимает ────────────────────

def test_explicit_request_still_refuses_when_work_is_undelivered(repo):
    """Главная гарантия. Явный режим — про «жив ли тут кто-то», а не про «доехала ли работа».
    Недоставленный путь (`unique`) отменяет снятие даже по прямой просьбе владельца дерева."""
    root, _ = repo
    wt = _worktree(root, "spa_c256")
    (wt / "docs" / "STATE.md").write_text("работа, которой нет на origin\n", encoding="utf-8")
    _announce(root, wt, ["docs/STATE.md"])

    report = _self(root, wt)
    t = _verdict(report, wt)
    assert t["verdict"] == R.KEEP, t["reasons"]
    assert [p["state"] for p in t["paths"]] == [R.UNIQUE]
    assert any("НЕДОСТАВЛЕННАЯ" in r for r in t["reasons"]), t["reasons"]
    assert R.exit_code(report) == 1


def test_explicit_request_never_reaps_the_main_worktree(repo):
    """Щит №1 (#234) не зависит ни от какого режима: главное дерево — это прод."""
    root, _ = repo
    t = _verdict(_self(root, root), root)
    assert t["verdict"] == R.KEEP
    assert any("главное рабочее дерево" in r for r in t["reasons"]), t["reasons"]


def test_explicit_request_refuses_a_directory_git_does_not_call_a_worktree(repo):
    """Просьба про каталог, которого нет в `git worktree list`: мерить нечего, снимать нечего,
    молчать нельзя ⇒ «не измерено», код 2."""
    root, _ = repo
    stray = root.parent / "not_a_worktree"
    stray.mkdir()

    report = _self(root, stray)
    assert report["trees"] == []
    assert any("git не считает этот каталог рабочим деревом" in r
               for r in report["unmeasured_reasons"]), report["unmeasured_reasons"]
    assert R.exit_code(report) == 2


def test_explicit_request_refuses_when_run_from_inside_the_tree_being_removed(repo):
    """`git worktree remove` вынул бы каталог из-под собственного `cwd`, и всё, что сессия
    сделает следующей командой, произошло бы в несуществующем месте."""
    root, _ = repo
    wt = _delivered_tree(root)

    report = _self(root, wt, cwd=wt / "docs")
    assert report["trees"] == []
    assert any("изнутри снимаемого дерева" in r for r in report["unmeasured_reasons"]), \
        report["unmeasured_reasons"]
    assert R.exit_code(report) == 2


def test_unreadable_tree_stays_unmeasured_even_when_named_explicitly(repo):
    """«Обход дерева не удался» — это неизмеримость, а не признак занятости, и просьба
    владельца её не отменяет: снимать то, что не читается, нельзя ни по чьему указанию."""
    root, _ = repo
    wt = _delivered_tree(root)

    def blind(path, grace_hours, now_ts=None, skip=()):
        return None, "обход дерева не удался: подменено тестом"

    real, R.newest_mtime = R.newest_mtime, blind
    try:
        report = _self(root, wt)
    finally:
        R.newest_mtime = real
    t = _verdict(report, wt)
    assert t["verdict"] == R.UNMEASURED, t["reasons"]
    assert R.exit_code(report) == 2


# ── обратный контроль: подметающий прогон не изменился ──────────────────────

def test_sweep_verdicts_are_untouched_by_the_new_mode(repo):
    """Ослабления «заодно» не произошло: у подметающего прогона все три исхода прежние —
    свежее дерево остаётся, старое с недоставленным остаётся, старое доставленное снимается."""
    root, _ = repo
    fresh = _delivered_tree(root, "spa_fresh")            # шумит ⇒ KEEP
    old_unique = _worktree(root, "spa_old_unique")
    # ОТДЕЛЬНЫЙ путь: если бы дерево правило тот же `docs/STATE.md`, что и доставка ниже,
    # база ушла бы по нему вперёд и вердикт стал бы `superseded` — то есть тест мерил бы
    # не «недоставленное остаётся», а перекрытие. Здесь база по пути не двигается.
    (old_unique / "docs" / "OTHER.md").write_text("не доставлено\n", encoding="utf-8")
    old_ok = _worktree(root, "spa_old_ok")
    (old_ok / "docs" / "STATE.md").write_text("доставлено давно\n", encoding="utf-8")
    _deliver(root, "docs/STATE.md", "доставлено давно\n")
    _deliver(root, "docs/STATE.md", "и ещё позже\n")

    old_ts = NOW_TS - 72 * 3600
    for wt in (old_unique, old_ok):
        for dirpath, dirnames, filenames in os.walk(wt):
            dirnames[:] = [d for d in dirnames if d != ".git"]
            for name in filenames:
                os.utime(os.path.join(dirpath, name), (old_ts, old_ts))

    report = _sweep(root)
    assert _verdict(report, fresh)["verdict"] == R.KEEP
    assert _verdict(report, old_unique)["verdict"] == R.KEEP
    assert _verdict(report, old_ok)["verdict"] == R.REAP
    assert all(t.get("explicit") is False for t in report["trees"])


# ── сквозная петля: снятие оставляет измерение, шаг 0a его читает ───────────

def test_explicit_removal_leaves_a_receipt_the_step_0a_guard_accepts(repo, monkeypatch):
    """Ради этого всё и делалось. После явного снятия дерева нет, а измерение есть: шаг 0a
    видит объявленный путь внутри исчезнувшего дерева и читает по нему квитанцию — вместо
    «измерить нечем» (код 2) получается «снято по правилу, содержимое объяснено»."""
    root, _ = repo
    wt = _delivered_tree(root)
    declared = str(wt / "docs" / "STATE.md")
    archive_root = root.parent / "archives"

    report = _self(root, wt)
    t = _verdict(report, wt)
    assert t["verdict"] == R.REAP

    dest, why = R.archive(t["path"], "origin/main", t["paths"], archive_root=archive_root)
    assert dest, why
    ledger, why = R.record_reap(root, t["path"], "origin/main", t["paths"], t["churn"], dest)
    assert ledger, why
    ok, msg = R.reap(root, t["path"])
    assert ok, msg
    assert not Path(wt).exists()

    guard = _guard()
    rows, why = guard.read_reap_ledger(root)
    assert why is None and rows, (why, rows)
    state, detail = guard.reaped_state(declared, rows, root, "origin/main")
    assert state == guard.DELIVERED, detail
    assert "объяснено при снятии" in detail, detail


def test_receipt_does_not_whitewash_a_path_it_calls_undelivered(repo):
    """Обратный контроль квитанции: пропуск даётся только пути, названному `delivered`/
    `superseded`. Строка `unique` в квитанции — по-прежнему «не измерено», а не тишина."""
    root, _ = repo
    wt = _worktree(root, "spa_c256")
    declared = str(wt / "docs" / "STATE.md")
    R.record_reap(root, str(wt), "origin/main",
                  [{"path": "docs/STATE.md", "state": R.UNIQUE, "why": "-"}], 0, "/dev/null")
    _run(root, "worktree", "remove", "--force", str(wt))

    guard = _guard()
    rows, _ = guard.read_reap_ledger(root)
    state, detail = guard.reaped_state(declared, rows, root, "origin/main")
    assert state == guard.UNMEASURED, (state, detail)


# ── шаг 0a: осадок «снято руками» — одной строкой на дерево ─────────────────

def _render_input(unmeasured):
    """Минимальный отчёт в форме, которую строит `build_report` — только то, что читает
    `render`. Поля не выдуманы: имена сверены с самим `build_report`."""
    return {"base_ref": "origin/main", "base_sha": "abcdef123", "root": "/r",
            "grace_hours": 3.0, "entries_checked": 1, "sessions_checked": 1,
            "sessions_active": 0, "findings": [], "nowhere": [], "stale_copies": [],
            "foreign_only": [], "reaped": [], "card_findings": [], "dead_worktrees": [],
            "unmeasured": unmeasured, "fresh": [], "exit_code": 2}


def _gone(session, tree, names):
    guard = _guard()
    return [{"session": session, "path": f"{tree}/{n}",
             "reason": f"{guard.TREE_GONE} — доставку измерить нечем: {tree}/{n}",
             "tree_gone": True} for n in names]


def test_twelve_paths_of_one_removed_tree_collapse_to_one_line(repo):
    """Замер 16.08: одно снятое руками дерево дало 12 строк об одном событии, и у всех
    двенадцати одно и то же действие читателя — никакого. Так сторожа и глохнут."""
    guard = _guard()
    unmeasured = _gone("cycle-256", "/tmp/spa_c256",
                       [f"f{i}.py" for i in range(12)])
    groups = guard.group_tree_gone(unmeasured)
    assert len(groups) == 1
    assert groups[0]["count"] == 12
    assert groups[0]["session"] == "cycle-256"
    assert groups[0]["common_root"] == "/tmp/spa_c256"


def test_collapsed_section_keeps_every_record_and_the_exit_code(repo):
    """Обратный контроль: сжат ЧЕЛОВЕЧЕСКИЙ вывод, а не измерение. Все записи на месте,
    счёт в заголовке прежний, код возврата остаётся 2 (fail-CLOSED не смягчён)."""
    guard = _guard()
    unmeasured = _gone("cycle-256", "/tmp/spa_c256", [f"f{i}.py" for i in range(12)])
    report = _render_input(unmeasured)
    text = guard.render(report)

    assert "❓ НЕ ИЗМЕРЕНО (12)" in text                     # счёт по записям, не по строкам
    assert text.count("снятое БЕЗ квитанции") == 1           # но строка одна
    assert "f7.py: рабочее дерево удалено" not in text       # пути не размазаны по строкам
    assert "ПОДНИМАТЬ НЕЧЕГО" in text
    assert "--worktree" in text                              # читателю названо, чем чинить


def test_other_unmeasured_rows_are_still_printed_one_by_one(repo):
    """Второй обратный контроль: группировка трогает РОВНО свой класс. Любая другая строка
    «не измерено» печатается как раньше — по одной, со своей причиной."""
    guard = _guard()
    unmeasured = _gone("cycle-256", "/tmp/spa_c256", ["a.py", "b.py"]) + [
        {"session": "cycle-99", "path": "scripts/x.py",
         "reason": "рабочее дерево с базой НЕ сверено"}]
    report = _render_input(unmeasured)
    text = guard.render(report)

    assert "cycle-99 · scripts/x.py: рабочее дерево с базой НЕ сверено" in text
    assert "❓ НЕ ИЗМЕРЕНО (3)" in text


def test_paths_from_different_roots_do_not_get_a_made_up_common_root(repo):
    """Общий корень не выдумывается. Нет общего пути — так и сказано, а не подставлен `/`."""
    guard = _guard()
    unmeasured = [
        {"session": "s", "path": "/tmp/a/x.py", "reason": guard.TREE_GONE, "tree_gone": True},
        {"session": "s", "path": "relative/y.py", "reason": guard.TREE_GONE, "tree_gone": True},
    ]
    groups = guard.group_tree_gone(unmeasured)
    assert groups[0]["common_root"] == "общего корня у объявленных путей нет"


def test_tree_gone_marker_is_set_by_the_guard_itself_not_by_the_test(repo):
    """Признак класса ставится в проде, а не в фикстуре: `resolve_rel` для пути внутри
    исчезнувшего дерева обязана вернуть причину, начинающуюся с того же самого `TREE_GONE`,
    по которому группирует отчёт. Разойдутся — группировка молча перестанет работать."""
    guard = _guard()
    root, _ = repo
    ghost = root.parent / "vanished_tree" / "docs" / "STATE.md"

    rel, err = guard.resolve_rel(str(ghost), root)
    assert rel is None
    assert err.startswith(guard.TREE_GONE), err
