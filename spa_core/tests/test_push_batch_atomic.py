"""
spa_core/tests/test_push_batch_atomic.py

Гейт против рецидива: **набор файлов уезжает ОДНИМ коммитом**.

ЧТО ЛОВИМ (карточка `agent-push-batch-per-file-commits`, найдено циклом #48).
Contents API принимает по ОДНОМУ файлу за вызов, поэтому набор из N
взаимозависимых файлов приземлялся N последовательными коммитами. Измерено на
РЕАЛЬНЫХ прогонах Actions: из пяти коммитов одного пуша ДВА промежуточных дали
`SPA Tests`/`SPA CI` = failure — на `main` уже лежали тесты, а правок, которые
эти тесты проверяют, ещё не было. Регулярный «нормальный» красный `main` учит
игнорировать сигнал (инвариант #16), ломает `git bisect` и отправляет следующую
сессию искать несуществующий дефект (цикл #47 занимался ровно этим).

ВТОРОЙ ДЕФЕКТ, найденный по дороге и закрытый здесь же: старый batch-пушер
ставил КАЖДОЙ записи дерева режим `100644`. В репо 27 файлов с режимом
`100755`, и среди них bash-обёртки launchd (`scripts/auto_push.sh`,
`scripts/install_agents.sh`, …). Пуш такого файла батчем СНЯЛ БЫ x-бит молча —
а агент без x-бита падает exit-78 (инвариант #12), и увидеть это можно только
по мёртвому агенту. Режим существующего файла теперь берётся с remote.

Сеть НЕ ТРОГАЕТСЯ: `_api` подменяется детерминированным фейком GitHub, который
записывает КАЖДЫЙ вызов — поэтому «сколько коммитов создано» здесь измерение,
а не предположение.

Запуск: python3 -m pytest spa_core/tests/test_push_batch_atomic.py -v
"""
from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    """Загрузить модуль пушера по явному пути (как это делает прод-код)."""
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ptg():
    return _load("_test_batch_ptg", "push_to_github.py")


@pytest.fixture()
def batch():
    return _load("_test_batch_cli", "push_to_github_batch.py")


# ─────────────────────────────────────────────────────────────────────────────
# Фейк GitHub: ровно те эндпоинты Git Data API, которыми пользуется batch_push.
# ─────────────────────────────────────────────────────────────────────────────
class FakeGitHub:
    """Детерминированный remote. Считает вызовы — на них и строятся ассерты."""

    def __init__(self, tree: dict | None = None, truncated: bool = False):
        # tree: repo_path → (mode, blob_sha)
        self.tree = dict(tree or {})
        self.truncated = truncated
        self.calls: list[tuple[str, str]] = []          # (method, path)
        self.commits: list[dict] = []                   # созданные коммиты
        self.trees: list[dict] = []                     # созданные деревья
        self.ref_updates: list[str] = []                # PATCH refs
        self.blobs: dict[str, bytes] = {}
        self._n = 0

    def _sha(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n:038d}"

    # `_api(pat, method, path, payload=None)`
    def api(self, pat, method, path, payload=None):
        self.calls.append((method, path))
        if method == "GET" and "/git/ref/heads/" in path:
            return {"object": {"sha": "basecommit"}}
        if method == "GET" and "/git/commits/" in path:
            return {"tree": {"sha": "basetree"}}
        if method == "GET" and "/git/trees/" in path:
            return {
                "tree": [{"path": p, "mode": m, "type": "blob", "sha": s}
                         for p, (m, s) in self.tree.items()],
                "truncated": self.truncated,
            }
        if method == "POST" and path.endswith("/git/blobs"):
            sha = self._sha("b")
            self.blobs[sha] = payload["content"]
            return {"sha": sha}
        if method == "POST" and path.endswith("/git/trees"):
            sha = self._sha("t")
            self.trees.append({"sha": sha, **payload})
            return {"sha": sha}
        if method == "POST" and path.endswith("/git/commits"):
            sha = self._sha("c")
            self.commits.append({"sha": sha, **payload})
            return {"sha": sha}
        if method == "PATCH" and "/git/refs/heads/" in path:
            self.ref_updates.append(payload["sha"])
            return {"object": {"sha": payload["sha"]}}
        raise AssertionError(f"фейк не знает эндпоинт: {method} {path}")


@pytest.fixture()
def repo(tmp_path):
    """Настоящий git-репозиторий: repo_relative_path работает по факту, не по константе."""
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    return r


def _write(repo: Path, rel: str, text: str, executable: bool = False) -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    if executable:
        p.chmod(0o755)
    return p


@pytest.fixture()
def wired(ptg, repo, monkeypatch):
    """Пушер, подключённый к фейковому remote и к временному репозиторию."""
    gh = FakeGitHub()
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    # По умолчанию remote «пустой» ⇒ каждый файл новый и изменённый.
    monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: None)
    return ptg, gh


# ═════════════════════════════════════════════════════════════════════════════
# 1. ГЛАВНОЕ: N файлов = ОДИН коммит
# ═════════════════════════════════════════════════════════════════════════════
def test_many_files_land_in_exactly_one_commit(wired, repo):
    ptg, gh = wired
    files = [str(_write(repo, f"pkg/f{i}.py", f"x = {i}\n")) for i in range(5)]

    res = ptg.batch_push("pat", files, "msg", "o/r", "main")

    assert res["ok"] and res["count"] == 5
    assert len(gh.commits) == 1, (
        "набор файлов обязан приземлиться ОДНИМ коммитом — именно N коммитов "
        "давали красные промежуточные состояния main")
    assert len(gh.ref_updates) == 1
    assert gh.ref_updates[0] == gh.commits[0]["sha"]


def test_one_commit_contains_every_file(wired, repo):
    ptg, gh = wired
    names = ["a.py", "sub/b.py", "docs/c.md"]
    files = [str(_write(repo, n, f"# {n}\n")) for n in names]

    ptg.batch_push("pat", files, "msg", "o/r", "main")

    assert len(gh.trees) == 1
    assert sorted(e["path"] for e in gh.trees[0]["tree"]) == sorted(names), (
        "все файлы набора обязаны быть в ОДНОМ дереве")
    assert gh.trees[0]["base_tree"] == "basetree", "дерево строится поверх базы ветки"
    assert gh.commits[0]["parents"] == ["basecommit"]


def test_commit_message_is_used_verbatim(wired, repo):
    ptg, gh = wired
    files = [str(_write(repo, "a.py", "a\n")), str(_write(repo, "b.py", "b\n"))]
    ptg.batch_push("pat", files, "vX.YZ: описание", "o/r", "main")
    assert gh.commits[0]["message"] == "vX.YZ: описание"


# ═════════════════════════════════════════════════════════════════════════════
# 2. Режим файла (x-бит) — снятый бит = мёртвый launchd-агент (exit-78)
# ═════════════════════════════════════════════════════════════════════════════
def test_existing_executable_keeps_its_exec_bit(ptg, repo, monkeypatch):
    """Файл на remote — 100755; пушим его → режим ОБЯЗАН остаться 100755."""
    gh = FakeGitHub(tree={"scripts/auto_push.sh": ("100755", "old")})
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: "old")   # содержимое изменилось
    # ЛОКАЛЬНО x-бита нет: worktree/чекаут мог его потерять — remote решает.
    f1 = _write(repo, "scripts/auto_push.sh", "#!/bin/bash\necho new\n", executable=False)
    f2 = _write(repo, "docs/x.md", "новый\n")
    monkeypatch.setattr(ptg, "get_file_sha",
                        lambda pat, r, path, br="main": "old" if "auto_push" in path else None)

    ptg.batch_push("pat", [str(f1), str(f2)], "msg", "o/r", "main")

    modes = {e["path"]: e["mode"] for e in gh.trees[0]["tree"]}
    assert modes["scripts/auto_push.sh"] == "100755", (
        "x-бит существующего файла снят молча — bash-обёртка launchd после "
        "такого пуша падает exit-78 (инвариант #12)")
    assert modes["docs/x.md"] == "100644"


def test_new_file_mode_follows_local_exec_bit(wired, repo):
    ptg, gh = wired
    plain = str(_write(repo, "notes.md", "текст\n"))
    runnable = str(_write(repo, "scripts/new_agent.sh", "#!/bin/bash\n", executable=True))

    ptg.batch_push("pat", [plain, runnable], "msg", "o/r", "main")

    modes = {e["path"]: e["mode"] for e in gh.trees[0]["tree"]}
    assert modes["notes.md"] == "100644"
    assert modes["scripts/new_agent.sh"] == "100755"


def test_truncated_tree_refuses_instead_of_guessing_mode(ptg, repo, monkeypatch):
    """Дерево пришло усечённым ⇒ существование файла НЕ измерено ⇒ отказ."""
    gh = FakeGitHub(tree={"other.py": ("100644", "s")}, truncated=True)
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: None)
    files = [str(_write(repo, "a.py", "a\n")), str(_write(repo, "b.py", "b\n"))]

    with pytest.raises(ptg.TreeModeError):
        ptg.batch_push("pat", files, "msg", "o/r", "main")

    assert gh.commits == [] and gh.ref_updates == [], (
        "отказ обязан быть ДО коммита — половина набора на main хуже, чем ничего")


def test_truncated_tree_still_pushes_paths_it_did_see(ptg, repo, monkeypatch):
    """Положительный контроль: усечение само по себе не блокирует — блокирует
    НЕИЗМЕРЕННЫЙ путь. Путь, который в усечённом дереве есть, уезжает."""
    gh = FakeGitHub(tree={"a.py": ("100755", "old")}, truncated=True)
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: "old")
    f = _write(repo, "a.py", "изменено\n")

    res = ptg.batch_push("pat", [str(f)], "msg", "o/r", "main")

    assert res["count"] == 1
    assert gh.trees[0]["tree"][0]["mode"] == "100755"


# ═════════════════════════════════════════════════════════════════════════════
# 3. Идемпотентность: неизменённое не создаёт коммитов
# ═════════════════════════════════════════════════════════════════════════════
def test_all_unchanged_creates_no_commit_at_all(ptg, repo, monkeypatch):
    gh = FakeGitHub()
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    files = [_write(repo, f"f{i}.py", f"x = {i}\n") for i in range(3)]
    shas = {str(f.relative_to(repo)): ptg.git_blob_sha(f.read_bytes()) for f in files}
    monkeypatch.setattr(ptg, "get_file_sha", lambda pat, r, path, br="main": shas.get(path))

    res = ptg.batch_push("pat", [str(f) for f in files], "msg", "o/r", "main")

    assert res["ok"] and res["count"] == 0 and res["skipped"] == 3
    assert gh.commits == [] and gh.trees == [] and gh.ref_updates == [], (
        "идентичное содержимое обязано давать НОЛЬ коммитов — иначе каждый "
        "прогон autopush пишет в историю пустой коммит")


def test_only_changed_files_enter_the_commit(ptg, repo, monkeypatch):
    gh = FakeGitHub()
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    same = _write(repo, "same.py", "не менялся\n")
    changed = _write(repo, "changed.py", "новое содержимое\n")
    same_sha = ptg.git_blob_sha(same.read_bytes())
    monkeypatch.setattr(ptg, "get_file_sha",
                        lambda pat, r, path, br="main": same_sha if path == "same.py" else "stale")

    res = ptg.batch_push("pat", [str(same), str(changed)], "msg", "o/r", "main")

    assert res["count"] == 1 and res["skipped"] == 1
    assert [e["path"] for e in gh.trees[0]["tree"]] == ["changed.py"]


def test_unknown_remote_sha_is_pushed_not_skipped(ptg, repo, monkeypatch):
    """Неопределённость (сетевая ошибка → sha=None) НИКОГДА не читается как
    «не изменился»: реальные правки не теряются (то же направление ошибки,
    что у push_file)."""
    gh = FakeGitHub()
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: None)
    f = _write(repo, "a.py", "a\n")

    res = ptg.batch_push("pat", [str(f)], "msg", "o/r", "main")
    assert res["count"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# 4. Fail-CLOSED на путях: ни один файл не уезжает, если хоть один неразрешим
# ═════════════════════════════════════════════════════════════════════════════
def test_stray_path_aborts_the_whole_batch(wired, repo, tmp_path):
    ptg, gh = wired
    good = str(_write(repo, "good.py", "ok\n"))
    stray = tmp_path / "outside" / "stray.py"
    stray.parent.mkdir()
    stray.write_text("нет\n", encoding="utf-8")

    with pytest.raises(RuntimeError):
        ptg.batch_push("pat", [good, str(stray)], "msg", "o/r", "main")

    assert gh.commits == [] and gh.ref_updates == [], (
        "неразрешимый путь обязан отменять ВЕСЬ набор, а не половину")


def test_missing_file_aborts_the_whole_batch(wired, repo):
    ptg, gh = wired
    good = str(_write(repo, "good.py", "ok\n"))
    with pytest.raises(RuntimeError):
        ptg.batch_push("pat", [good, str(repo / "нет-такого.py")], "msg", "o/r", "main")
    assert gh.commits == []


# ═════════════════════════════════════════════════════════════════════════════
# 5. CLI: многофайловый пуш идёт атомарным путём, одиночный — прежним
# ═════════════════════════════════════════════════════════════════════════════
def _run_main(ptg, monkeypatch, argv, batch_stub=None, push_file_stub=None):
    calls = {"batch": [], "push_file": []}

    # `**_kw` добавлен циклом #51 ОСОЗНАННО (инвариант #16): пушер получил
    # параметр `allow_overwrite` (страж перезаписи, карточка
    # `agent-shared-doc-whole-file-push-overwrites`), и дублёры с жёстко
    # зафиксированной сигнатурой падали TypeError'ом на ВЫЗОВЕ, не дойдя до
    # своих проверок. Изменены только сигнатуры дублёров — ни один ассерт
    # ниже не тронут, набор проверок не сужен. Запись: docs/journal/2026-W31.md.
    def fake_batch(pat, files, message, repo, branch, dry_run=False, **_kw):
        calls["batch"].append(list(files))
        if batch_stub:
            return batch_stub(files)
        return {"ok": True, "count": len(files), "commit": "c" * 40,
                "skipped": 0, "files": files, "skipped_files": []}

    def fake_push_file(pat, f, message, repo, dry_run=False, branch="main", **_kw):
        calls["push_file"].append(f)
        if push_file_stub:
            return push_file_stub(f)
        return {"ok": True, "path": str(f), "sha": "abcdef12"}

    monkeypatch.setattr(ptg, "batch_push", fake_batch)
    monkeypatch.setattr(ptg, "push_file", fake_push_file)
    monkeypatch.setattr(ptg, "get_pat", lambda: "pat")
    monkeypatch.setattr(sys, "argv", ["push_to_github.py", *argv])
    with pytest.raises(SystemExit) as exc:
        ptg.main()
    return calls, exc.value.code


def test_cli_multi_file_uses_the_atomic_path(ptg, repo, monkeypatch):
    files = [str(_write(repo, f"f{i}.py", f"{i}\n")) for i in range(3)]
    calls, code = _run_main(ptg, monkeypatch, ["--files", *files, "--message", "m"])
    assert code == 0
    assert len(calls["batch"]) == 1 and calls["batch"][0] == files
    assert calls["push_file"] == [], (
        "многофайловый пуш не должен идти по одному файлу за коммит")


def test_cli_single_file_keeps_the_contents_api_path(ptg, repo, monkeypatch):
    f = str(_write(repo, "one.py", "1\n"))
    calls, code = _run_main(ptg, monkeypatch, ["--files", f, "--message", "m"])
    assert code == 0
    assert calls["batch"] == [], "одиночный файл — прежний путь, менять нечего"
    assert calls["push_file"] == [f]


def test_cli_refuses_instead_of_falling_back_to_per_file(ptg, repo, monkeypatch):
    """Требование карточки: Git Data API недоступен → ЧЕСТНЫЙ ОТКАЗ,
    а не тихая досылка по одному файлу (ровно она и красит main)."""
    files = [str(_write(repo, f"f{i}.py", f"{i}\n")) for i in range(2)]

    def boom(_files):
        raise RuntimeError("git data api недоступен")

    calls, code = _run_main(ptg, monkeypatch, ["--files", *files, "--message", "m"],
                            batch_stub=boom)
    assert code == 1, "провал атомарного пути обязан быть ненулевым кодом возврата"
    assert calls["push_file"] == [], "молчаливой досылки по одному быть не должно"


def test_cli_dry_run_writes_nothing(ptg, repo, monkeypatch):
    files = [str(_write(repo, f"f{i}.py", f"{i}\n")) for i in range(2)]
    calls, code = _run_main(
        ptg, monkeypatch, ["--files", *files, "--message", "m", "--dry-run"],
        push_file_stub=lambda f: {"ok": True, "dry_run": True, "path": str(f),
                                  "action": "create"})
    assert code == 0
    assert calls["batch"] == [], "--dry-run не должен звать пишущий путь"


# ═════════════════════════════════════════════════════════════════════════════
# 6. Одна реализация на оба CLI (близнец = класс дефектов #37/#40)
# ═════════════════════════════════════════════════════════════════════════════
_SHARED = ["batch_push", "resolve_files", "create_blob", "create_tree",
           "create_commit", "update_ref", "get_base_ref", "remote_tree_modes",
           "tree_entry_mode", "split_unchanged", "get_pat"]


@pytest.mark.parametrize("name", _SHARED)
def test_batch_cli_reuses_the_canonical_function(batch, name):
    """Символ batch-CLI — ТОТ ЖЕ объект, что в каноническом модуле.

    Сравнение идёт с ``batch._root_push`` (модулем, который batch грузит сам), а
    не с отдельно загруженной в тесте копией: две загрузки одного файла дают
    разные объекты функций, и такое сравнение краснело бы всегда, ничего не
    измеряя. Второй ассерт пиннит, что код физически лежит в push_to_github.py.
    """
    fn = getattr(batch, name)
    assert fn is getattr(batch._root_push, name), (
        f"{name} в push_to_github_batch.py — СВОЯ копия; починка в одном пушере "
        f"не доедет до другого (так цикл #37 оставил CI красным)")
    assert Path(fn.__code__.co_filename).name == "push_to_github.py", (
        f"{name} исполняется не из канонического push_to_github.py, а из "
        f"{fn.__code__.co_filename}")


def test_batch_cli_defines_no_delivery_logic_of_its_own(batch):
    src = (ROOT / "push_to_github_batch.py").read_text(encoding="utf-8")
    for name in _SHARED:
        assert f"def {name}" not in src, (
            f"push_to_github_batch.py снова определяет {name} — вернулся близнец")


# ═════════════════════════════════════════════════════════════════════════════
# 6a. Ветка сдвинулась под нами: пересборка на свежей базе, всё ещё ОДИН коммит
# ═════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("code", [409, 422])
def test_stale_ref_recomposes_on_fresh_base_and_still_one_commit(ptg, repo, monkeypatch, code):
    """Параллельный писатель (autopush / дневной цикл) сдвинул ветку.

    GitHub отвечает на PATCH refs именно **422** «Update is not a fast forward»
    (409 — второй возможный код), поэтому ретрай обязан ловить оба: ветка только
    на 409 на реальном коде ошибки не срабатывала бы, и пуш падал бы там, где
    раньше Contents API молча ретраился.
    """
    import urllib.error

    gh = FakeGitHub()
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: None)
    f = _write(repo, "a.py", "a\n")

    calls = {"n": 0}
    real_update = ptg.update_ref

    def flaky_update(pat, r, branch, commit_sha, force=False):
        calls["n"] += 1
        if calls["n"] == 1:
            raise urllib.error.HTTPError(
                "u", code, "stale", {},                       # type: ignore[arg-type]
                __import__("io").BytesIO(b"Update is not a fast forward"))
        return real_update(pat, r, branch, commit_sha, force)

    monkeypatch.setattr(ptg, "update_ref", flaky_update)

    res = ptg.batch_push("pat", [str(f)], "msg", "o/r", "main")

    assert res["ok"] and calls["n"] == 2
    assert len(gh.ref_updates) == 1, "на ветку обязан приземлиться ровно один коммит"
    assert gh.ref_updates[0] == gh.commits[-1]["sha"], "уехал не пересобранный коммит"


# ═════════════════════════════════════════════════════════════════════════════
# 7. Положительные контроли: ЗЕЛЁНЫЕ и до этой правки, и после.
#    Без них файл доказывал бы лишь «новый код существует», а не «прежнее
#    поведение сохранено». Эти три проходят и на чистом origin/main.
# ═════════════════════════════════════════════════════════════════════════════
def test_control_single_file_push_still_skips_unchanged_content(ptg, repo, monkeypatch):
    """Идемпотентность одиночного PUT (Contents API) не тронута этой правкой."""
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    f = _write(repo, "same.py", "не менялся\n")
    monkeypatch.setattr(ptg, "get_file_sha",
                        lambda *a, **k: ptg.git_blob_sha(f.read_bytes()))
    res = ptg.push_file("pat", str(f), "msg", "o/r")
    assert res["ok"] and res.get("skipped") is True


def test_control_path_outside_repo_still_fails_closed(ptg, repo, tmp_path):
    """RepoPathError на пути вне репо — прежний инвариант (цикл #40/#42)."""
    stray = tmp_path / "стрэй.py"
    stray.write_text("нет\n", encoding="utf-8")
    with pytest.raises(ptg.RepoPathError):
        ptg.repo_relative_path(stray, project_root=repo)


def test_owner_gate_interlock_still_present_in_both_pushers():
    """Инварианты авто-шипа сайта не ослаблены этой правкой (ADR-OWN-2026-07)."""
    for rel in ("push_to_github.py", "push_to_github_batch.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "SPA_AUTONOMOUS" in src and "SPA_SITE_PUSH_VERIFIED" in src, rel
        assert "check_owner_gate.py" in src, rel
        assert "sys.exit(3)" in src, f"{rel}: fail-CLOSED выход owner-gate пропал"
