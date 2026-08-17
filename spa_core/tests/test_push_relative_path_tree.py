"""Относительный путь в инструменте доставки читает ДЕРЕВО ОТПРАВКИ, а не хост-дерево.

ЧТО ЛОВИМ (карточка `agent-pusher-relative-path-silently-reads-the-host-tree`,
побочная находка цикла #109). Оба места, где путь превращался в файл, делали

    local = Path(fa)
    if not local.is_absolute():
        local = PROJECT_ROOT / local          # ← хост-дерево, НЕ дерево отправки

(`push_to_github.py::push_file` и `::resolve_files`). `PROJECT_ROOT` — константа
хост-чекаута `/Users/yuriikulieshov/Documents/SPA_Claude`, который дрейфует от
`origin` ПО ПОСТРОЕНИЮ (пуши идут прямо в origin через API; 31.07 копия пушера
там отставала на 574 строки). Протокол §3.4 ОБЯЗЫВАЕТ собирать и тестировать в
изолированном worktree — то есть относительный путь по умолчанию читал ДРУГОЕ
дерево, чем то, которое сессия собрала.

Измерено на одном и том же наборе (цикл #109): абсолютными путями — `update` ×7,
относительными — `skip` для изменённых файлов и `FAIL: файл не найден` для новых.
Опасен именно `skip`: набор из одних ИЗМЕНЁННЫХ файлов проехал бы целиком как
`OK: N файл(ов) (pushed=0, skipped=N)` — успех при НУЛЕВОЙ доставке.

Здесь пиннится ПОВЕДЕНИЕ, а не текст: источник файла — дерево запущенного
инструмента доставки; расхождение деревьев называется вслух; неопределимое
дерево — отказ с названной причиной (fail-CLOSED, инвариант #2), а не «возьмём
что есть».

Все тесты герметичны: настоящие git-репозитории в ``tmp_path``, сети нет.

Запуск: python3 -m pytest spa_core/tests/test_push_relative_path_tree.py -v
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: дерево отправки определяется через git rev-parse",
)


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def pusher():
    return _load("_test_relpath_ptg", "push_to_github.py")


@pytest.fixture()
def batch():
    return _load("_test_relpath_batch", "push_to_github_batch.py")


# ── git-хелперы (герметично, без глобального конфига пользователя) ─────────────

def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = str(cwd)
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=True, env=env)


def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


@pytest.fixture()
def host(tmp_path):
    """Хост-чекаут (тот самый, на который смотрит PROJECT_ROOT) — ОТСТАВШИЙ."""
    root = tmp_path / "host_repo"
    root.mkdir(parents=True)
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    _write(root, "seed.txt", "seed")
    _git(root, "add", "seed.txt")
    _git(root, "commit", "-qm", "seed")
    _write(root, "docs/STATE.md", "СТАРОЕ содержимое хост-дерева\n")
    return root


@pytest.fixture()
def sending(host, tmp_path):
    """Дерево ОТПРАВКИ: linked worktree того же репо, где сессия собрала и тестировала."""
    wt = tmp_path / "elsewhere" / "spa_wt_c109"
    _git(host, "worktree", "add", "--detach", "-q", str(wt), "HEAD")
    _write(wt, "docs/STATE.md", "СВЕЖЕЕ содержимое дерева отправки\n")
    # Копия инструмента доставки лежит в каждом дереве (TOOLCHAIN_FILES).
    shutil.copy2(ROOT / "push_to_github.py", wt / "push_to_github.py")
    return wt


@pytest.fixture()
def as_if_running_from_sending(pusher, host, sending, monkeypatch):
    """Пушер ЗАПУЩЕН из дерева отправки, а процесс сидит в ХОСТ-дереве."""
    monkeypatch.setattr(pusher, "PROJECT_ROOT", host)
    monkeypatch.setattr(pusher, "__file__", str(sending / "push_to_github.py"))
    monkeypatch.chdir(host)
    return pusher


# ── 1. Дефект: источник файла — дерево отправки, а не хост-дерево и не CWD ─────

def test_relative_path_reads_sending_tree_not_host_tree(as_if_running_from_sending,
                                                        host, sending):
    """Ядро дефекта: `docs/STATE.md` — файл ТОГО дерева, из которого идёт доставка."""
    got = as_if_running_from_sending.resolve_local_path("docs/STATE.md")
    assert got == sending / "docs/STATE.md", (
        f"относительный путь снова прочитан из чужого дерева: {got}")
    assert got.read_text(encoding="utf-8").startswith("СВЕЖЕЕ")
    assert not str(got).startswith(str(host) + os.sep)


def test_push_file_relative_path_does_not_report_skip_from_host_tree(
        as_if_running_from_sending, sending):
    """Тот самый ложный `skip`: remote совпадает с ХОСТ-копией, а мы везём свежую.

    Именно этот вердикт делал молчаливый провал опасным — набор из изменённых
    файлов уезжал как `OK (pushed=0, skipped=N)`.
    """
    pusher = as_if_running_from_sending
    host_bytes = (pusher.PROJECT_ROOT / "docs/STATE.md").read_bytes()
    remote_sha = pusher.git_blob_sha(host_bytes)     # remote == отставшая копия
    calls = []

    def _fake_sha(pat, repo_name, repo_path, branch="main"):
        calls.append(repo_path)
        return remote_sha

    pusher.get_file_sha = _fake_sha
    res = pusher.push_file("pat", "docs/STATE.md", "msg", "yurii-spa/SPA", dry_run=True)
    assert res["ok"] is True
    assert res["path"] == "docs/STATE.md"
    assert res["action"] == "update", (
        "пушер сравнил remote с ХОСТ-копией и объявил skip — доставка нулевая, "
        f"а отчёт зелёный (получено {res})")
    assert calls == ["docs/STATE.md"]


def test_resolve_files_relative_path_takes_sending_tree(as_if_running_from_sending,
                                                        sending):
    """Batch-путь (под ним стоит safe_site_push) — тот же контракт."""
    resolved = as_if_running_from_sending.resolve_files(["docs/STATE.md"])
    assert [rp for rp, _ in resolved] == ["docs/STATE.md"]
    assert [p for _, p in resolved] == [sending / "docs/STATE.md"]


def test_batch_cli_shares_one_resolution(batch):
    """У batch-CLI нет своей резолюции: тот же символ из канонического модуля."""
    assert batch.resolve_files.__code__.co_filename.endswith("push_to_github.py")
    assert getattr(batch._root_push, "resolve_local_path", None) is not None


# ── 2. Расхождение деревьев называется ВСЛУХ ──────────────────────────────────

def test_tree_divergence_is_named_out_loud(as_if_running_from_sending, host, sending,
                                           capsys):
    """`skip` читался как «уже на origin». Теперь видно, из КАКОГО дерева взят файл."""
    as_if_running_from_sending.resolve_local_path("docs/STATE.md")
    err = capsys.readouterr().err
    assert str(sending) in err, "дерево отправки не названо"
    assert str(host) in err, "текущий каталог/чужое дерево не названо"
    assert "docs/STATE.md" in err


def test_no_noise_when_trees_coincide(pusher, sending, monkeypatch, capsys):
    """Обратный контроль: одно и то же дерево — тишина, иначе шум научат игнорировать."""
    monkeypatch.setattr(pusher, "PROJECT_ROOT", sending)
    monkeypatch.setattr(pusher, "__file__", str(sending / "push_to_github.py"))
    monkeypatch.chdir(sending)
    pusher.resolve_local_path("docs/STATE.md")
    assert capsys.readouterr().err == ""


# ── 3. Fail-CLOSED: дерево не определяется ⇒ отказ с НАЗВАННОЙ причиной ───────

def test_undeterminable_sending_tree_refuses(pusher, tmp_path, monkeypatch):
    stray = tmp_path / "not_a_repo"
    stray.mkdir()
    monkeypatch.setattr(pusher, "__file__", str(stray / "push_to_github.py"))
    with pytest.raises(pusher.DeliveryTreeError) as exc:
        pusher.resolve_local_path("docs/STATE.md")
    msg = str(exc.value)
    assert str(stray) in msg, "причина обязана называть, ГДЕ лежит запущенный инструмент"
    assert "docs/STATE.md" in msg


def test_without_git_relative_path_refuses(as_if_running_from_sending, monkeypatch):
    """Нет git (PATH у launchd) ⇒ дерево НЕ ИЗМЕРЕНО ⇒ отказ, а не хост-дерево."""
    pusher = as_if_running_from_sending
    monkeypatch.setattr(pusher, "_git_out", lambda *a, **kw: None)
    with pytest.raises(pusher.DeliveryTreeError):
        pusher.resolve_local_path("docs/STATE.md")


def test_push_file_fails_closed_and_never_touches_network(pusher, tmp_path, monkeypatch):
    stray = tmp_path / "not_a_repo"
    stray.mkdir()
    monkeypatch.setattr(pusher, "__file__", str(stray / "push_to_github.py"))

    def _boom(*a, **kw):
        raise AssertionError("сеть тронута при неопределимом дереве отправки")

    monkeypatch.setattr(pusher, "get_file_sha", _boom)
    monkeypatch.setattr(pusher, "_api", _boom)
    res = pusher.push_file("pat", "docs/STATE.md", "msg", "yurii-spa/SPA", dry_run=True)
    assert res["ok"] is False
    assert "docs/STATE.md" in res["error"]
    # Причина названа ИМЕННО та: «дерево отправки не определяется», а не общее
    # «файл не найден» — иначе следующая сессия пойдёт искать пропавший файл.
    assert str(stray) in res["error"], (
        f"отказ не называет, где лежит запущенный инструмент: {res['error']}")


def test_resolve_files_fails_closed_for_whole_batch(pusher, tmp_path, monkeypatch):
    stray = tmp_path / "not_a_repo"
    stray.mkdir()
    monkeypatch.setattr(pusher, "__file__", str(stray / "push_to_github.py"))
    with pytest.raises(RuntimeError) as exc:
        pusher.resolve_files(["docs/STATE.md"])
    assert str(stray) in str(exc.value), (
        f"весь батч отменён, но причина не названа: {exc.value}")


# ── 4. Храповик класса: хост-константа больше не резолвит относительные пути ──

@pytest.mark.parametrize("filename", ["push_to_github.py", "push_to_github_batch.py"])
def test_no_silent_resolve_against_host_constant(filename):
    """Ни один ПУТЬ-ПЕРЕМЕННАЯ больше не склеивается с хост-константой.

    Проверка по AST, а не по подстроке: текстовый вариант краснел бы на
    собственном разборе дефекта в докстринге (и его чинили бы удалением
    объяснения). `PROJECT_ROOT / ".github_pat"` — литерал, к путям файлов
    набора отношения не имеет и остаётся законным.
    """
    import ast

    src = (ROOT / filename).read_text(encoding="utf-8")
    bad = [
        node for node in ast.walk(ast.parse(src))
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div)
        and isinstance(node.left, ast.Name) and node.left.id == "PROJECT_ROOT"
        and not isinstance(node.right, ast.Constant)
    ]
    assert not bad, (
        f"{filename}: относительный путь снова резолвится от ХОСТ-дерева "
        f"(строки {[n.lineno for n in bad]}) — источником обязано быть дерево отправки")


# ── 5. Обратные контроли: то, что работало, работает ─────────────────────────

def test_absolute_path_from_any_tree_is_untouched(as_if_running_from_sending, host):
    """Абсолютный путь — по-прежнему ровно тот файл, что назвали (CLAUDE.md)."""
    f = host / "docs/STATE.md"
    assert as_if_running_from_sending.resolve_local_path(str(f)) == f


def test_absolute_path_needs_no_sending_tree(pusher, host, tmp_path, monkeypatch):
    """Инструмент вне git-дерева всё ещё возит АБСОЛЮТНЫЕ пути: отказ узкий."""
    stray = tmp_path / "not_a_repo"
    stray.mkdir()
    monkeypatch.setattr(pusher, "__file__", str(stray / "push_to_github.py"))
    f = host / "docs/STATE.md"
    assert pusher.resolve_local_path(str(f)) == f


# ── 6. Согласованность со сверкой инструмента доставки (не ослабление) ───────

def test_toolchain_check_does_not_blame_the_cwd_tree(pusher, host, sending, monkeypatch):
    """Относительный путь = файл дерева отправки ⇒ сверять его не с чем.

    Следствие починки, а не её ослабление: раньше сверка смотрела на дерево
    ТЕКУЩЕГО каталога и (после починки источника) отказывала бы из-за дерева, из
    которого файлы больше не берутся. Измеренное расхождение по АБСОЛЮТНЫМ путям
    по-прежнему даёт отказ — это пиннит `test_pusher_copy_guard.py`.
    """
    monkeypatch.chdir(host)
    (host / "push_to_github.py").write_text("# ДРУГОЙ инструмент\n", encoding="utf-8")
    v = pusher.toolchain_verdict(str(sending / "push_to_github.py"), ["docs/STATE.md"])
    assert v["mismatch"] == []
    assert v["trees"] == []
