"""Гарантии инструмента ДОСТАВКИ: путь файла внутри репо определяется по факту,
а «не знаю» — это ОШИБКА, а не basename в корень репо.

Дефект (цикл #40, карточка `agent-push-worktree-path-collapse`): оба пушера считали
путь как ``local.relative_to(PROJECT_ROOT)`` с молчаливым ``except ValueError:
repo_path = local.name``. Протокол оркестратора ОБЯЗЫВАЕТ работать в изолированном
worktree (§3.4), а worktree всегда ВНЕ хост-репо ⇒ каждый автономный цикл по
умолчанию находился в условиях срабатывания: 6 файлов легли в КОРЕНЬ репо под
basename'ами, инструмент напечатал ``OK`` с настоящими sha, настоящие пути остались
со старым содержимым. Для ``landing/**`` это ещё хуже: страница сайта НЕ менялась,
а в корне появлялся стрэй (``index.astro``) — и именно batch-пушер стоит под
``scripts/safe_site_push.py``.

Все тесты герметичны: настоящие git-репозитории строятся в ``tmp_path``, сети нет.
"""
import importlib.util
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None,
    reason="нужен настоящий git: проверяем определение корня репо через git rev-parse "
           "(условный skipif — на машине с git тесты выполняются)",
)


def _load(name: str, filename: str):
    """Загрузить пушер по явному пути (оба файла лежат в корне репо, не пакет)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def pusher():
    return _load("_test_pt_push", "push_to_github.py")


@pytest.fixture(scope="module")
def batch():
    return _load("_test_pt_batch", "push_to_github_batch.py")


# ── git-хелперы (герметично, без глобального конфига пользователя) ─────────────

def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = str(cwd)  # не читать ~/.gitconfig прогоняющего
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=True, env=env)


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    _git(path, "init", "-q")
    _git(path, "config", "user.email", "t@example.invalid")
    _git(path, "config", "user.name", "t")
    (path / "seed.txt").write_text("seed", encoding="utf-8")
    _git(path, "add", "seed.txt")
    _git(path, "commit", "-qm", "seed")
    return path


def _add_file(root: Path, rel: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("x = 1\n", encoding="utf-8")
    return p


@pytest.fixture()
def repo(tmp_path):
    return _make_repo(tmp_path / "host_repo")


@pytest.fixture()
def worktree(repo, tmp_path):
    """Linked worktree ТОГО ЖЕ репозитория, лежащий ВНЕ хост-чекаута."""
    wt = tmp_path / "elsewhere" / "wt41"
    _git(repo, "worktree", "add", "--detach", "-q", str(wt), "HEAD")
    return wt


# ── 1. Дефект: worktree-путь больше не схлопывается в basename ────────────────

def test_worktree_path_keeps_full_repo_path(pusher, repo, worktree):
    """ЭТО и есть починенный дефект: было 'mod.py', стало 'pkg/sub/mod.py'."""
    f = _add_file(worktree, "pkg/sub/mod.py")
    got = pusher.repo_relative_path(f, project_root=repo)
    assert got == "pkg/sub/mod.py"
    assert got != f.name, "путь снова схлопнулся в basename — файл уедет в КОРЕНЬ репо"


def test_worktree_landing_file_keeps_landing_prefix(pusher, repo, worktree):
    """Сайтовый след дефекта: правка страницы уезжала в корень как index.astro."""
    f = _add_file(worktree, "landing/src/pages/index.astro")
    got = pusher.repo_relative_path(f, project_root=repo)
    assert got == "landing/src/pages/index.astro"
    assert not got.startswith("index."), "страница сайта снова уедет мимо (стрэй в корне)"


def test_batch_resolve_files_keeps_worktree_path(batch, repo, worktree, monkeypatch):
    """Batch-пушер (под ним стоит safe_site_push) — тот же контракт."""
    monkeypatch.setattr(batch, "PROJECT_ROOT", repo)
    monkeypatch.setattr(batch._root_push, "PROJECT_ROOT", repo)
    f = _add_file(worktree, "landing/src/pages/pricing.astro")
    resolved = batch.resolve_files([str(f)])
    assert [rp for rp, _ in resolved] == ["landing/src/pages/pricing.astro"]


# ── 2. Fail-CLOSED: «не знаю» — ошибка, а не догадка ──────────────────────────

def test_path_outside_any_repo_raises(pusher, repo, tmp_path):
    stray = tmp_path / "not_a_repo" / "mod.py"
    stray.parent.mkdir(parents=True)
    stray.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(pusher.RepoPathError) as exc:
        pusher.repo_relative_path(stray, project_root=repo)
    assert "mod.py" in str(exc.value), "в ошибке должен быть виден проблемный путь"


def test_path_in_a_different_repo_raises(pusher, repo, tmp_path):
    """Чужой git-репозиторий — не повод угадывать путь в НАШЕМ репо."""
    other = _make_repo(tmp_path / "other_repo")
    f = _add_file(other, "pkg/mod.py")
    with pytest.raises(pusher.RepoPathError):
        pusher.repo_relative_path(f, project_root=repo)


def test_push_file_fails_closed_and_never_touches_network(pusher, repo, tmp_path, monkeypatch):
    """push_file отдаёт честный FAIL до любого сетевого вызова."""
    monkeypatch.setattr(pusher, "PROJECT_ROOT", repo)

    def _boom(*a, **kw):  # pragma: no cover — вызов = провал теста
        raise AssertionError("сеть не должна дёргаться при нерешаемом пути")

    monkeypatch.setattr(pusher, "get_file_sha", _boom)
    stray = tmp_path / "not_a_repo" / "mod.py"
    stray.parent.mkdir(parents=True)
    stray.write_text("x = 1\n", encoding="utf-8")

    res = pusher.push_file("pat", str(stray), "msg", "yurii-spa/SPA")
    assert res["ok"] is False
    assert res["path"] == str(stray)          # НЕ basename
    assert "fail-CLOSED" in res["error"]


def test_batch_resolve_files_raises_outside_repo(batch, repo, tmp_path, monkeypatch):
    monkeypatch.setattr(batch, "PROJECT_ROOT", repo)
    monkeypatch.setattr(batch._root_push, "PROJECT_ROOT", repo)
    stray = tmp_path / "not_a_repo" / "mod.py"
    stray.parent.mkdir(parents=True)
    stray.write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(RuntimeError):
        batch.resolve_files([str(stray)])


# ── 3. Положительные контроли: старое поведение НЕ сломано ────────────────────

def test_host_path_maps_to_nested_path(pusher, repo):
    f = _add_file(repo, "spa_core/monitoring/mod.py")
    assert pusher.repo_relative_path(f, project_root=repo) == "spa_core/monitoring/mod.py"


def test_file_at_repo_root_still_maps_to_bare_name(pusher, repo):
    """Файл, который РЕАЛЬНО лежит в корне, обязан остаться в корне."""
    f = _add_file(repo, "push_to_github.py")
    assert pusher.repo_relative_path(f, project_root=repo) == "push_to_github.py"


def test_relative_path_still_resolves_against_project_root(batch, repo, monkeypatch):
    monkeypatch.setattr(batch, "PROJECT_ROOT", repo)
    monkeypatch.setattr(batch._root_push, "PROJECT_ROOT", repo)
    _add_file(repo, "docs/STATE.md")
    resolved = batch.resolve_files(["docs/STATE.md"])
    assert [rp for rp, _ in resolved] == ["docs/STATE.md"]


def test_push_file_dry_run_uses_nested_path(pusher, repo, monkeypatch):
    """Контроль «не инвертировано»: рабочий путь по-прежнему доезжает до API."""
    monkeypatch.setattr(pusher, "PROJECT_ROOT", repo)
    seen = {}

    def _fake_sha(pat, repo_name, repo_path, branch="main"):
        seen["path"] = repo_path
        return None

    monkeypatch.setattr(pusher, "get_file_sha", _fake_sha)
    f = _add_file(repo, "spa_core/monitoring/mod.py")
    res = pusher.push_file("pat", str(f), "msg", "yurii-spa/SPA", dry_run=True)
    assert res["ok"] is True
    assert res["path"] == "spa_core/monitoring/mod.py"
    assert seen["path"] == "spa_core/monitoring/mod.py"


# ── 4. Деградация без git (launchd-PATH у autopush) ───────────────────────────

def test_without_git_host_paths_still_work(pusher, repo, monkeypatch):
    """У launchd в PATH может не быть git — хост-пути обязаны работать и так."""
    monkeypatch.setattr(pusher, "_git_out", lambda *a, **kw: None)
    f = _add_file(repo, "spa_core/monitoring/mod.py")
    assert pusher.repo_relative_path(f, project_root=repo) == "spa_core/monitoring/mod.py"


def test_without_git_outside_path_still_fails_closed(pusher, repo, worktree, monkeypatch):
    """Без git worktree опознать нельзя ⇒ отказ, а НЕ basename."""
    f = _add_file(worktree, "pkg/mod.py")
    monkeypatch.setattr(pusher, "_git_out", lambda *a, **kw: None)
    with pytest.raises(pusher.RepoPathError):
        pusher.repo_relative_path(f, project_root=repo)


# ── 5. Гейт против рецидива КЛАССА (молчаливый basename-fallback) ─────────────

@pytest.mark.parametrize("filename", ["push_to_github.py", "push_to_github_batch.py"])
def test_pushers_have_no_silent_basename_fallback(filename):
    src = (ROOT / filename).read_text(encoding="utf-8")
    assert "repo_path = local.name" not in src, (
        f"{filename}: вернулся молчаливый fallback в basename — файлы поедут в корень репо"
    )
    # НАМЕРЕННОЕ ИЗМЕНЕНИЕ ПРОВЕРКИ (инвариант #16, цикл #49 — обоснование здесь
    # и в docs/journal/2026-W31.md). Было: `assert "repo_relative_path(" in src`
    # — текстовый признак «в файле есть ВЫЗОВ общей функции». После переноса
    # resolve_files в канонический push_to_github.py batch-CLI больше не зовёт её
    # сам (он делегирует ВСЮ доставку), поэтому подстроки в тексте нет, хотя
    # проверяемое свойство стало СИЛЬНЕЕ. Проверка не ослаблена, а переведена с
    # текста на ПОВЕДЕНИЕ: символ модуля обязан быть той самой канонической
    # функцией (по файлу её кода). Своя копия — даже байт-в-байт совпадающая —
    # такую проверку краснит, а старую текстовую проходила бы.
    mod = _load(f"_test_pt_fallback_{filename}", filename)
    resolver = getattr(mod, "repo_relative_path", None)
    assert resolver is not None, (
        f"{filename}: пушер не выставляет repo_relative_path вовсе"
    )
    assert Path(resolver.__code__.co_filename).name == "push_to_github.py", (
        f"{filename}: пушер обязан считать путь общим repo_relative_path, а не своей "
        f"копией (сейчас код идёт из {resolver.__code__.co_filename})"
    )


def test_single_implementation_of_path_resolution():
    """Логика ОДНА: batch не имеет своего определения функции, только импорт."""
    batch_src = (ROOT / "push_to_github_batch.py").read_text(encoding="utf-8")
    assert "def repo_relative_path" not in batch_src
