"""Гейт: доставка ЦЕЛЫМИ ФАЙЛАМИ не даёт права стереть чужую правку.

ДЕФЕКТ (карточка `agent-shared-doc-whole-file-push-overwrites`, найдено циклом #50).
Пушер отправляет СОДЕРЖИМОЕ файла и коммитит поверх текущего `main` — слияния нет.
Для файлов, которые ДОПИСЫВАЮТ (недельный журнал `docs/journal/*.md`, `docs/STATE.md`,
`nimbalyst-local/tracker/_BOARD.md`), это «последний писатель побеждает»: сессия,
чья копия основана на более старом коммите, молча сносит запись той, что успела
запушить раньше. Протокол оркестратора ОБЯЗЫВАЕТ каждый цикл дописывать ровно эти
файлы («Шаг 3 — обновить память») ⇒ пересечение неизбежно в КАЖДОМ цикле, а поймать
потерю нечем:

  * шаг 0b (пересечение по файлам) на общие документы работать не может — иначе
    занятой оказывается ЛЮБАЯ карточка в любом цикле;
  * шаг 0a («объявил → доставил») увидит расхождение только СЛЕДУЮЩИМ циклом,
    постфактум и без атрибуции;
  * сам пушер честно отчитается `OK` — он доставил ровно то, что ему дали.

В цикле #50 потери не произошло только потому, что `origin/main` не двинулся между
началом работы и пушем. Это свойство механизма, а не гипотеза о вреде.

ЧТО ПРОВЕРЯЕМ ЗДЕСЬ. Три версии файла (база рабочей копии · наша · remote):
remote == база → пуш как раньше; обе стороны дописывают → наша добавка ложится на
свежий remote; иначе → ОТКАЗ (fail-CLOSED, инвариант #2). Плюс граница
применимости: копия, не основанная на ветке доставки (хост-репо autopush'а сидит на
своей ветке), даёт «НЕ ИЗМЕРЕНО» — и прежний путь доставки не ломается.

Все тесты герметичны: настоящие git-репозитории в ``tmp_path``, GitHub подменён
детерминированным фейком, сети нет.

Запуск: python3 -m pytest spa_core/tests/test_push_divergence_guard.py -v
"""
import base64
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
    reason="нужен настоящий git: база рабочей копии читается через git cat-file "
           "(условный skipif — на машине с git тесты выполняются)",
)


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ptg():
    return _load("_test_div_ptg", "push_to_github.py")


@pytest.fixture()
def batch():
    return _load("_test_div_batch", "push_to_github_batch.py")


# ── git-хелперы (герметично, без ~/.gitconfig прогоняющего) ───────────────────

def _git(cwd, *args):
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    env["HOME"] = str(cwd)
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=True, env=env)


BASE_TEXT = "# журнал недели\n\n- запись цикла #49\n"
OTHER_APPEND = "- запись ПАРАЛЛЕЛЬНОЙ сессии\n"
MY_APPEND = "- запись моего цикла\n"


@pytest.fixture()
def checkout(tmp_path):
    """Рабочая копия, ЧЕСТНО основанная на ветке доставки.

    `refs/remotes/origin/main` заводится явно: именно по нему страж и решает,
    что HEAD — законная база (в проде это worktree от `origin/main`).
    """
    root = tmp_path / "checkout"
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    (root / "docs").mkdir()
    (root / "docs" / "journal.md").write_text(BASE_TEXT, encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "база")
    _git(root, "update-ref", "refs/remotes/origin/main", "HEAD")
    return root


@pytest.fixture()
def journal(checkout):
    return checkout / "docs" / "journal.md"


def _append(path: Path, text: str) -> None:
    path.write_bytes(path.read_bytes() + text.encode())


class FakeRemote:
    """Deterministic GitHub: помнит содержимое путей, считает записи."""

    def __init__(self, files: dict):
        self.files = {k: v.encode() if isinstance(v, str) else v
                      for k, v in files.items()}
        self.puts: list[tuple[str, bytes]] = []

    # ── подмены для Contents-пути (push_file) ────────────────────────────────
    def get_file_sha(self, ptg):
        def _sha(pat, repo, repo_path, branch="main"):
            data = self.files.get(repo_path)
            return None if data is None else ptg.git_blob_sha(data)
        return _sha

    def get_file_content(self):
        def _content(pat, repo, repo_path, branch="main"):
            return self.files.get(repo_path)
        return _content

    def urlopen(self):
        """Перехват PUT: записываем то, что реально уехало бы на remote."""
        import json

        class _Resp:
            def __init__(self, payload):
                self._payload = payload

            def read(self):
                return json.dumps(self._payload).encode()

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def _open(req, *a, **kw):
            body = json.loads(req.data.decode())
            path = req.full_url.split("/contents/", 1)[1]
            content = base64.b64decode(body["content"])
            self.files[path] = content
            self.puts.append((path, content))
            return _Resp({"content": {"sha": "f" * 40}})

        return _open


def _wire(ptg, monkeypatch, remote, checkout):
    monkeypatch.setattr(ptg, "PROJECT_ROOT", checkout)
    monkeypatch.setattr(ptg, "get_file_sha", remote.get_file_sha(ptg))
    # `raising=False` НАМЕРЕННО: на коде ДО этой правки `get_file_content` не
    # существует, и без этого положительные контроли падали бы на подмене
    # несуществующего символа, а не на поведении — то есть перестали бы быть
    # контролями («зелено и до, и после»).
    monkeypatch.setattr(ptg, "get_file_content", remote.get_file_content(), raising=False)
    monkeypatch.setattr(ptg.urllib.request, "urlopen", remote.urlopen())
    monkeypatch.delenv("SPA_AUTONOMOUS", raising=False)


# ═════════════════════════════════════════════════════════════════════════════
# 1. САМ ДЕФЕКТ: две сессии с общей базой дописывают один файл
#    (на коде до правки вторая доставка ТЕРЯЛА запись первой)
# ═════════════════════════════════════════════════════════════════════════════
def test_parallel_append_is_not_lost_on_single_file_push(ptg, monkeypatch, checkout, journal):
    """Сессия A уже запушила свою строку; сессия B пушит свою — выживают ОБЕ."""
    remote = FakeRemote({"docs/journal.md": BASE_TEXT + OTHER_APPEND})   # сессия A успела
    _wire(ptg, monkeypatch, remote, checkout)
    _append(journal, MY_APPEND)                                          # сессия B дописала

    res = ptg.push_file("pat", str(journal), "цикл B", "o/r")

    assert res["ok"], res
    landed = remote.files["docs/journal.md"].decode()
    assert OTHER_APPEND in landed, (
        "запись параллельной сессии СТЁРТА — ровно тот дефект, "
        "ради которого написан этот файл")
    assert MY_APPEND in landed, "наша собственная запись не доехала"
    assert landed == BASE_TEXT + OTHER_APPEND + MY_APPEND


def test_parallel_append_is_not_lost_in_batch_push(ptg, monkeypatch, checkout, journal):
    """Тот же контракт на batch-пути (под ним стоит safe_site_push)."""
    remote = FakeRemote({"docs/journal.md": BASE_TEXT + OTHER_APPEND})
    _wire(ptg, monkeypatch, remote, checkout)
    _append(journal, MY_APPEND)

    blobs: dict[str, bytes] = {}

    def fake_api(pat, method, path, payload=None):
        if method == "GET" and "/git/ref/heads/" in path:
            return {"object": {"sha": "basecommit"}}
        if method == "GET" and "/git/commits/" in path:
            return {"tree": {"sha": "basetree"}}
        if method == "GET" and "/git/trees/" in path:
            return {"tree": [{"path": "docs/journal.md", "mode": "100644",
                              "type": "blob", "sha": "x" * 40}], "truncated": False}
        if method == "POST" and path.endswith("/git/blobs"):
            data = base64.b64decode(payload["content"])
            sha = ptg.git_blob_sha(data)
            blobs[sha] = data
            return {"sha": sha}
        if method == "POST" and path.endswith("/git/trees"):
            return {"sha": "newtree"}
        if method == "POST" and path.endswith("/git/commits"):
            return {"sha": "newcommit"}
        if method == "PATCH" and "/git/refs/heads/" in path:
            return {"object": {"sha": "newcommit"}}
        raise AssertionError(f"неожиданный вызов: {method} {path}")

    monkeypatch.setattr(ptg, "_api", fake_api)
    res = ptg.batch_push("pat", [str(journal), str(checkout / "docs" / "journal.md")][:1],
                         "цикл B", "o/r", "main")

    assert res["ok"] and res["count"] == 1
    landed = b"".join(blobs.values()).decode()
    assert OTHER_APPEND in landed, "batch-путь стёр запись параллельной сессии"
    assert MY_APPEND in landed


# ═════════════════════════════════════════════════════════════════════════════
# 2. ОТКАЗ вместо тихой перезаписи там, где дописыванием не обойтись
# ═════════════════════════════════════════════════════════════════════════════
def test_mid_file_edit_over_diverged_remote_is_refused(ptg, monkeypatch, checkout, journal):
    """`docs/STATE.md` правится в СЕРЕДИНЕ — префикса нет, значит fail-CLOSED."""
    remote = FakeRemote({"docs/journal.md": BASE_TEXT + OTHER_APPEND})
    _wire(ptg, monkeypatch, remote, checkout)
    journal.write_text("# журнал недели\n\n- ПЕРЕПИСАННАЯ шапка\n" + MY_APPEND,
                       encoding="utf-8")

    res = ptg.push_file("pat", str(journal), "цикл B", "o/r")

    assert res["ok"] is False and res.get("diverged") is True
    assert remote.puts == [], "при отказе не должно быть НИ ОДНОЙ записи на remote"
    assert OTHER_APPEND in remote.files["docs/journal.md"].decode()
    assert "перечитать" in res["error"], "в отказе нет инструкции, что делать дальше"


def test_batch_refusal_aborts_the_whole_set(ptg, monkeypatch, checkout, journal):
    """Один расходящийся файл роняет ВЕСЬ батч — рваного набора на main нет."""
    remote = FakeRemote({"docs/journal.md": BASE_TEXT + OTHER_APPEND})
    _wire(ptg, monkeypatch, remote, checkout)
    journal.write_text("совсем другое содержимое\n", encoding="utf-8")
    other = checkout / "docs" / "second.md"
    other.write_text("новый файл\n", encoding="utf-8")

    calls: list[str] = []

    def fake_api(pat, method, path, payload=None):
        calls.append(f"{method} {path}")
        if method == "GET" and "/git/ref/heads/" in path:
            return {"object": {"sha": "basecommit"}}
        if method == "GET" and "/git/commits/" in path:
            return {"tree": {"sha": "basetree"}}
        if method == "GET" and "/git/trees/" in path:
            return {"tree": [], "truncated": False}
        if method == "POST" and path.endswith("/git/blobs"):
            return {"sha": "b" * 40}
        raise AssertionError(f"батч дошёл до записи, хотя обязан был отказать: {method} {path}")

    monkeypatch.setattr(ptg, "_api", fake_api)
    with pytest.raises(ptg.DivergenceRefused):
        ptg.batch_push("pat", [str(journal), str(other)], "цикл B", "o/r", "main")

    assert not any("git/trees" in c and c.startswith("POST") for c in calls)
    assert not any(c.startswith("PATCH") for c in calls), "ветка сдвинулась при отказе"


def test_file_created_by_someone_else_is_refused(ptg, monkeypatch, checkout):
    """Пути нет в нашей базе, но на remote он ЕСТЬ ⇒ его завёл кто-то другой."""
    remote = FakeRemote({"docs/new.md": "чужой файл\n"})
    _wire(ptg, monkeypatch, remote, checkout)
    mine = checkout / "docs" / "new.md"
    mine.write_text("мой файл\n", encoding="utf-8")

    res = ptg.push_file("pat", str(mine), "мой", "o/r")

    assert res["ok"] is False and res.get("diverged") is True
    assert remote.files["docs/new.md"] == "чужой файл\n".encode()


# ═════════════════════════════════════════════════════════════════════════════
# 3. ПОЛОЖИТЕЛЬНЫЕ КОНТРОЛИ: страж не срабатывает там, где расхождения нет.
#    Без них файл доказывал бы лишь «отказ существует», а не «прежний путь цел».
# ═════════════════════════════════════════════════════════════════════════════
def test_control_push_without_divergence_delivers_our_bytes_verbatim(
        ptg, monkeypatch, checkout, journal):
    """remote == база: содержимое уезжает БАЙТ В БАЙТ, как до этой правки."""
    remote = FakeRemote({"docs/journal.md": BASE_TEXT})     # никто не двигал
    _wire(ptg, monkeypatch, remote, checkout)
    _append(journal, MY_APPEND)

    res = ptg.push_file("pat", str(journal), "цикл B", "o/r")

    assert res["ok"] and len(remote.puts) == 1
    assert remote.puts[0][1] == journal.read_bytes(), "содержимое изменено на ровном месте"


def test_control_unchanged_file_is_still_skipped(ptg, monkeypatch, checkout, journal):
    """Идемпотентность (пустых коммитов нет) не тронута стражем."""
    remote = FakeRemote({"docs/journal.md": BASE_TEXT})
    _wire(ptg, monkeypatch, remote, checkout)

    res = ptg.push_file("pat", str(journal), "ничего не менял", "o/r")

    assert res["ok"] and res.get("skipped") is True
    assert remote.puts == []


def test_control_brand_new_file_is_pushed(ptg, monkeypatch, checkout):
    """Файла нет ни в базе, ни на remote — обычное создание, без отказа."""
    remote = FakeRemote({})
    _wire(ptg, monkeypatch, remote, checkout)
    fresh = checkout / "docs" / "fresh.md"
    fresh.write_text("новое\n", encoding="utf-8")

    res = ptg.push_file("pat", str(fresh), "новый файл", "o/r")

    assert res["ok"] and res.get("diverged") is not True
    assert remote.files["docs/fresh.md"] == "новое\n".encode()


def test_control_allow_overwrite_restores_old_behaviour(ptg, monkeypatch, checkout, journal):
    """Осознанная перезапись возможна — но ТОЛЬКО явным флагом."""
    remote = FakeRemote({"docs/journal.md": BASE_TEXT + OTHER_APPEND})
    _wire(ptg, monkeypatch, remote, checkout)
    journal.write_text("полностью моя версия\n", encoding="utf-8")

    res = ptg.push_file("pat", str(journal), "перезапись", "o/r", allow_overwrite=True)

    assert res["ok"] and remote.files["docs/journal.md"] == "полностью моя версия\n".encode()


# ═════════════════════════════════════════════════════════════════════════════
# 4. ГРАНИЦА ПРИМЕНИМОСТИ: «не измерено» — это не «всё в порядке»,
#    но и не повод сломать autopush, который пушит из хост-репо
# ═════════════════════════════════════════════════════════════════════════════
def test_checkout_not_based_on_delivery_branch_is_unmeasured(ptg, tmp_path, checkout, journal):
    """Хост-репо autopush'а сидит на своей ветке ⇒ базы нет, страж молчит."""
    _git(checkout, "checkout", "-q", "-b", "env-setup-v3")
    (checkout / "drift.txt").write_text("своя ветка\n", encoding="utf-8")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-qm", "уход с ветки доставки")

    verdict = ptg.divergence_verdict(journal, "docs/journal.md", "d" * 40)
    assert verdict["state"] == ptg.DIVERGENCE_UNMEASURED
    assert "не является предком" in verdict["reason"]


def _plain_dir_push(ptg, monkeypatch, tmp_path):
    """Пуш из копии, не являющейся рабочей копией ветки доставки (autopush)."""
    plain = tmp_path / "plain"
    (plain / "docs").mkdir(parents=True)
    f = plain / "docs" / "state.json"
    f.write_text("{}\n", encoding="utf-8")
    remote = FakeRemote({"docs/state.json": '{"старое": 1}\n'})
    monkeypatch.setattr(ptg, "PROJECT_ROOT", plain)
    monkeypatch.setattr(ptg, "get_file_sha", remote.get_file_sha(ptg))
    monkeypatch.setattr(ptg.urllib.request, "urlopen", remote.urlopen())
    return f, remote


def test_unmeasured_still_pushes_the_old_way(ptg, monkeypatch, tmp_path):
    """Прежний путь доставки не ломается: вне рабочей копии пуш идёт, как шёл.

    autopush, дневной цикл и кастодиан сайта пушат из ХОСТ-репо, который сидит
    на своей ветке ⇒ база неизмерима по построению. Блокировать их — значит
    остановить живую доставку ради неприменимой проверки.
    """
    f, remote = _plain_dir_push(ptg, monkeypatch, tmp_path)

    res = ptg.push_file("pat", str(f), "autopush", "o/r")

    assert res["ok"] and remote.files["docs/state.json"] == b"{}\n"


def test_unmeasured_is_never_reported_as_safe(ptg, monkeypatch, tmp_path, capsys):
    """Но «не измерено» и НЕ выдаётся за «всё в порядке» — причина печатается.

    Это ровно класс дефектов #29/#31/#35–#38/#40 («утверждение об измерении,
    которого не было»), поэтому молчаливого прохода здесь быть не должно.
    """
    f, _ = _plain_dir_push(ptg, monkeypatch, tmp_path)

    ptg.push_file("pat", str(f), "autopush", "o/r")

    out = capsys.readouterr().out
    assert "НЕ ИЗМЕРЕНО" in out, "пуш прошёл молча, как будто расхождение проверено"
    assert "не рабочая копия git" in out, "причина не названа — сигнал непроверяем"


def test_strict_unmeasured_is_an_explicit_opt_in_not_an_env_var(ptg, monkeypatch, tmp_path):
    """Требовать измеримую базу можно — но только явным флагом вызывающего.

    Привязки к `SPA_AUTONOMOUS` здесь НЕТ намеренно: поведение пушера не должно
    меняться от того, кто его запустил (иначе один и тот же набор файлов
    доставляется по-разному из cron и из рук, а тесты зависят от среды).
    """
    f, remote = _plain_dir_push(ptg, monkeypatch, tmp_path)
    monkeypatch.setenv("SPA_AUTONOMOUS", "1")

    # env сам по себе ничего не меняет
    assert ptg.push_file("pat", str(f), "autopush", "o/r")["ok"] is True

    # а явный опт-ин — меняет
    with pytest.raises(ptg.DivergenceRefused):
        ptg.guard_overwrite("pat", "o/r", "main", "docs/state.json", f,
                            f.read_bytes(), "d" * 40, strict_unmeasured=True)
    assert "SPA_AUTONOMOUS" not in (ROOT / "push_to_github.py").read_text(
        encoding="utf-8").split("guard_overwrite", 1)[1].split("def push_file", 1)[0]


# ═════════════════════════════════════════════════════════════════════════════
# 5. Чистые функции: пере-база — это ДОПИСЫВАНИЕ, а не слияние «по смыслу»
# ═════════════════════════════════════════════════════════════════════════════
def test_rebase_append_puts_our_tail_after_theirs(ptg):
    got = ptg.rebase_append(b"base\n", b"base\nmine\n", b"base\ntheirs\n")
    assert got == b"base\ntheirs\nmine\n"


@pytest.mark.parametrize("base, local, remote", [
    (b"base\n", "ДРУГОЕ\nmine\n".encode(), b"base\ntheirs\n"),   # наша правка не дописывание
    (b"base\n", b"base\nmine\n", "ДРУГОЕ\n".encode()),           # чужая правка не дописывание
    (b"base\n", b"base\n", b"base\ntheirs\n"),           # нам нечего добавлять
    (None, b"base\nmine\n", b"base\ntheirs\n"),          # базы нет
    (b"base\n", b"base\nmine\n", None),                  # remote не прочитан
])
def test_rebase_append_refuses_anything_that_is_not_pure_append(ptg, base, local, remote):
    assert ptg.rebase_append(base, local, remote) is None


def test_binary_file_is_never_silently_merged(ptg, monkeypatch, checkout):
    """Бинарник с разошедшимся remote — отказ, а не склейка байтов."""
    blob = checkout / "docs" / "pic.bin"
    blob.write_bytes(b"\x00\x01BASE")
    _git(checkout, "add", "-A")
    _git(checkout, "commit", "-qm", "бинарник")
    _git(checkout, "update-ref", "refs/remotes/origin/main", "HEAD")
    remote = FakeRemote({"docs/pic.bin": b"\x00\x01" + "ЧУЖОЕ".encode()})
    _wire(ptg, monkeypatch, remote, checkout)
    blob.write_bytes(b"\x00\x01" + "МОЁ".encode())

    res = ptg.push_file("pat", str(blob), "бинарник", "o/r")

    assert res["ok"] is False and remote.files["docs/pic.bin"] == b"\x00\x01" + "ЧУЖОЕ".encode()


# ═════════════════════════════════════════════════════════════════════════════
# 6. Реализация ОДНА на оба CLI (второй копии логики быть не должно)
# ═════════════════════════════════════════════════════════════════════════════
def test_guard_is_shared_between_both_pushers(batch):
    root = batch._root_push
    for name in ("guard_overwrite", "divergence_verdict", "rebase_append",
                 "base_version", "build_entries", "create_blob_from_bytes",
                 "DivergenceRefused"):
        assert getattr(batch, name) is getattr(root, name), (
            f"{name} разъехался между push_to_github_batch.py и каноническим модулем")


def test_both_clis_expose_allow_overwrite():
    """Осознанная перезапись доступна из обоих CLI — иначе отказ станет тупиком."""
    for rel in ("push_to_github.py", "push_to_github_batch.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "--allow-overwrite" in src, rel
        assert "SPA_PUSH_ALLOW_OVERWRITE" in src, rel
