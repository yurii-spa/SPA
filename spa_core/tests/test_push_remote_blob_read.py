"""Чтение БОЛЬШИХ файлов remote (Contents API молчит про тело >1 МБ).

ОШИБКА (owner decision, см. `docs/journal/2026-W40.md`). Contents API
(`GET /repos/{repo}/contents/{path}`) отдаёт `content` ТОЛЬКО для файлов
≤1 МБ; для больших он называет `sha`/размер, но тело отсутствует.
`get_file_content` читал РОВНО этот эндпоинт и на отсутствии `content`
возвращал `None` — а страж общей тетради (`guard_entry_loss`) трактует
`None` при известной `sha` как «содержимое remote НЕ ПРОЧИТАНО» и отказывает
НАВСЕГДА. `docs/decisions/INDEX.md` уже 1.6 МБ: любой пуш в него не проходил
иначе как `--allow-overwrite` (запрещённый владельцем как обход, а не решение).

ЧТО ДЕЛАЕМ (здесь проверяем). Тот же ответ Contents API уже называет SHA пути
на этом ref; blob — контент-адресуемый объект, поэтому его можно дочитать
НАПРЯМУЮ по SHA (`GET /repos/{repo}/git/blobs/{sha}`, Git Blob API, до 100 МБ)
БЕЗ повторного чтения пути на меняющейся ветке. Полученные байты ОБЯЗАНЫ
хешироваться обратно в ту же SHA (:func:`git_blob_sha`) — иначе отказ, а не
«похоже сработало».

Сеть НЕ ТРОГАЕТСЯ: ``urllib.request.urlopen`` подменён детерминированным
фейком GitHub. Каждый тест — измерение, а не предположение.

Запуск: python3 -m pytest spa_core/tests/test_push_remote_blob_read.py -v
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
INDEX = "docs/decisions/INDEX.md"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / filename)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ptg():
    return _load("_test_blobread_ptg", "push_to_github.py")


# ═════════════════════════════════════════════════════════════════════════════
# Фейковый GitHub: Contents API + Git Blob API, ничего больше.
# ═════════════════════════════════════════════════════════════════════════════
class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _http_error(url, code, body=b"{}"):
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(body))


class FakeGitHub:
    """Contents API (``get_file_sha``/``get_file_content``'s own GET) + Blob API.

    ``large_paths`` — пути, для которых Contents API ведёт себя как на файле
    >1 МБ: называет ``sha``/``size``, но НЕ называет ``content``. ``corrupt`` —
    sha блоба, для которого Blob API честно отвечает, но байты не хешируются
    обратно в неё (симулирует повреждённый/подменённый ответ). ``contents_down``
    — Contents API стабильно рвётся (сеть), а Blob API — нет.
    """

    def __init__(self, files: dict, large_paths: tuple = (), corrupt: dict | None = None,
                contents_down: bool = False, blobs_down: bool = False):
        self.files = {k: (v.encode() if isinstance(v, str) else v) for k, v in files.items()}
        self.large_paths = set(large_paths)
        self.corrupt = corrupt or {}
        self.contents_down = contents_down
        self.blobs_down = blobs_down
        self.calls: list[tuple[str, str]] = []

    def sha_of(self, path: str) -> str:
        return self._blob_sha(self.files[path])

    @staticmethod
    def _blob_sha(data: bytes) -> str:
        import hashlib
        return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()

    def urlopen(self, req, *a, **kw):
        method = req.get_method()
        url = req.full_url
        self.calls.append((method, url))

        if "/contents/" in url and method == "GET":
            if self.contents_down:
                raise urllib.error.URLError("сеть недоступна (сымитировано)")
            path = url.split("/contents/", 1)[1].split("?", 1)[0]
            data = self.files.get(path)
            if data is None:
                raise _http_error(url, 404)
            sha = self._blob_sha(data)
            payload = {"sha": sha, "size": len(data)}
            if path not in self.large_paths:
                payload["encoding"] = "base64"
                payload["content"] = base64.b64encode(data).decode()
            return _Resp(payload)

        if "/git/blobs/" in url and method == "GET":
            if self.blobs_down:
                raise _http_error(url, 503)
            blob_sha = url.rsplit("/", 1)[-1]
            data = None
            for d in self.files.values():
                if self._blob_sha(d) == blob_sha:
                    data = d
                    break
            if data is None:
                raise _http_error(url, 404)
            if blob_sha in self.corrupt:
                data = self.corrupt[blob_sha]
            return _Resp({"sha": blob_sha, "encoding": "base64",
                         "content": base64.b64encode(data).decode()})

        if method == "PUT":
            body = json.loads(req.data.decode())
            path = url.split("/contents/", 1)[1]
            content = base64.b64decode(body["content"])
            self.files[path] = content
            sha = self._blob_sha(content)
            return _Resp({"content": {"sha": sha}})

        raise AssertionError(f"фейк не знает запрос: {method} {url}")


def _wire(ptg, monkeypatch, gh: FakeGitHub):
    monkeypatch.setattr(ptg.urllib.request, "urlopen", gh.urlopen)
    return gh


_SMALL = b"small file, content comes back on the Contents API read\n"


def _registry_row(n: int) -> bytes:
    """Строка реестра решений — та же форма, что настоящий `docs/decisions/INDEX.md`."""
    return (f"| ADR-{n:05d} | synthetic decision row {n} padding padding padding "
            f"| Accepted | [ADR-{n:05d}](ADR-{n:05d}-slug.md) |\n").encode()


#: Большой (>1 МБ) реестр — РОВНО форма настоящего `docs/decisions/INDEX.md`
#: (1.6 МБ на момент дефекта), не стилизованный журнал: owner-сценарий именно
#: про этот файл, и тождество записи у него — НОМЕР (`REGISTRY_ROW_RE`), а не
#: заголовок `## …`.
_ROWS = 16000
_BIG = (b"# Registry decisions\n\n| # | Decision | Status | File |\n|---|---|---|---|\n"
       + b"".join(_registry_row(i) for i in range(1, _ROWS + 1)))


# ═════════════════════════════════════════════════════════════════════════════
# (a) обычный файл <1 МБ через Contents API — путь НЕ меняется.
# ═════════════════════════════════════════════════════════════════════════════
def test_small_file_reads_via_contents_api_unchanged(ptg, monkeypatch):
    gh = _wire(ptg, monkeypatch, FakeGitHub({"a.md": _SMALL}))
    sha = gh.sha_of("a.md")

    out = ptg.get_file_content("pat", "o/r", "a.md", "main")

    assert out == _SMALL
    assert not any("/git/blobs/" in u for _, u in gh.calls), (
        "маленький файл не обязан идти через Blob API")


# ═════════════════════════════════════════════════════════════════════════════
# (b) файл >1 МБ: content отсутствует → Blob API, страж меряет правильно.
# ═════════════════════════════════════════════════════════════════════════════
def test_large_file_falls_back_to_blob_api(ptg, monkeypatch):
    assert len(_BIG) > 1_000_000, "фикстура обязана быть реально большой"
    gh = _wire(ptg, monkeypatch, FakeGitHub({INDEX: _BIG}, large_paths=(INDEX,)))

    out = ptg.get_file_content("pat", "o/r", INDEX, "main")

    assert out == _BIG, "Blob API обязан отдать РОВНО те же байты"
    assert any("/git/blobs/" in u for _, u in gh.calls), (
        "для файла без content обязан произойти переход на Blob API")


def test_large_file_entry_guard_no_longer_refuses_forever(ptg, monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ к (b): это ровно тот сценарий, который раньше
    отказывал НАВСЕГДА (``remote_bytes is None`` при известной ``remote_sha``).
    """
    remote_sha = FakeGitHub._blob_sha(_BIG)
    _wire(ptg, monkeypatch, FakeGitHub({INDEX: _BIG}))

    content = ptg.get_file_content("pat", "o/r", INDEX, "main", expected_sha=remote_sha)
    assert content == _BIG

    note = ptg.guard_entry_loss(INDEX, content, _BIG + _registry_row(_ROWS + 1), remote_sha)
    assert note == "", "дописывание поверх ПРОЧИТАННОГО контента не теряет записей"


# ═════════════════════════════════════════════════════════════════════════════
# (c) remote изменился со времени подготовки кандидата (база не совпала) ⇒ STOP.
# ═════════════════════════════════════════════════════════════════════════════
def test_stale_base_still_refuses_with_blob_path_available(ptg, monkeypatch, tmp_path):
    """Регрессия: появление Blob-fallback'а НЕ ослабляет страж расхождения.

    Рабочая копия основана на СТАРОЙ версии; remote (большой файл) успел
    измениться. ``push_file`` обязан отказать (``DivergenceRefused``), а не
    тихо принять новую remote-версию как «безопасную» только потому, что она
    теперь ЧИТАЕТСЯ.
    """
    import subprocess

    root = tmp_path / "checkout"
    root.mkdir()
    (root / "docs" / "decisions").mkdir(parents=True)
    old = _BIG
    env = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(root)}

    def _git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True, env=env)

    _git("init", "-q", "-b", "main")
    _git("config", "user.email", "t@example.invalid")
    _git("config", "user.name", "t")
    (root / "docs" / "decisions" / "INDEX.md").write_bytes(old)
    _git("add", "-A")
    _git("commit", "-qm", "база")
    _git("update-ref", "refs/remotes/origin/main", "HEAD")

    # Рабочая копия правит СЕРЕДИНУ (не чистое дописывание) — из своей базы.
    mine = old.replace(_registry_row(1), _registry_row(1).replace(b"padding", b"EDITED", 1), 1)
    (root / "docs" / "decisions" / "INDEX.md").write_bytes(mine)

    # remote тем временем — ДРУГОЙ большой файл (не префикс и не наша база).
    remote_big = old + _registry_row(_ROWS + 1)
    gh = _wire(ptg, monkeypatch, FakeGitHub({INDEX: remote_big}, large_paths=(INDEX,)))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(root / "docs" / "decisions" / "INDEX.md"),
                        "цикл", "o/r")

    assert res["ok"] is False and res.get("diverged") is True
    assert not any(m == "PUT" for m, _ in gh.calls), "при отказе PUT быть не должно"


# ═════════════════════════════════════════════════════════════════════════════
# (d) локальный кандидат убирает строки remote ⇒ страж записей отказывает.
# ═════════════════════════════════════════════════════════════════════════════
def test_local_candidate_dropping_remote_rows_is_refused(ptg):
    remote = _BIG
    dropped = b"".join(_registry_row(i) for i in (10, 11, 12, 13, 14))
    ours = remote.replace(dropped, b"", 1)   # потеряли пять строк реестра

    with pytest.raises(ptg.EntryLossRefused) as e:
        ptg.guard_entry_loss(INDEX, remote, ours, remote_sha="deadbeef" * 5)
    for i in (10, 11, 12, 13, 14):
        assert f"ADR-{i:05d}" in str(e.value)


# ═════════════════════════════════════════════════════════════════════════════
# (e) additive-only правка БОЛЬШОГО INDEX.md проходит БЕЗ единого флага.
#
# Это и есть сценарий владельца: `docs/decisions/INDEX.md` (1.6+ МБ), ПАРАЛЛЕЛЬНАЯ
# сессия уже дописала свою строку (ровно как цикл за циклом в проде), наша
# сессия дописывает свою — обе обязаны выжить (пере-база дописывания), и ДЛЯ
# ЭТОГО пушеру нужны настоящие БАЙТЫ свежего remote (больше 1 МБ) — ровно то,
# что раньше возвращало `None` навсегда.
# ═════════════════════════════════════════════════════════════════════════════
def test_additive_only_large_index_update_passes_without_any_flag(ptg, monkeypatch, tmp_path):
    import subprocess

    root = tmp_path / "checkout"
    root.mkdir()
    (root / "docs" / "decisions").mkdir(parents=True)
    env = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(root)}

    def _git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True, env=env)

    _git("init", "-q", "-b", "main")
    _git("config", "user.email", "t@example.invalid")
    _git("config", "user.name", "t")
    (root / "docs" / "decisions" / "INDEX.md").write_bytes(_BIG)
    _git("add", "-A")
    _git("commit", "-qm", "база")
    _git("update-ref", "refs/remotes/origin/main", "HEAD")

    # Наша рабочая копия дописывает СВОЮ строку (пока не закоммичено).
    my_row = _registry_row(_ROWS + 1)
    (root / "docs" / "decisions" / "INDEX.md").write_bytes(_BIG + my_row)

    # Remote тем временем УЖЕ принял строку ПАРАЛЛЕЛЬНОЙ сессии (другой номер,
    # отличной от нашей) — ровно то, из-за чего база (`_BIG`) и remote расходятся.
    # Файл на remote теперь >1 МБ и БЕЗ `content` в ответе Contents API —
    # ровно условие дефекта.
    other_row = _registry_row(_ROWS + 2)
    remote_now = _BIG + other_row
    gh = _wire(ptg, monkeypatch, FakeGitHub({INDEX: remote_now}, large_paths=(INDEX,)))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(root / "docs" / "decisions" / "INDEX.md"), "цикл", "o/r")

    assert res["ok"] is True, res
    assert any("/git/blobs/" in u for _, u in gh.calls), (
        "БЕЗ Blob-fallback'а пере-база большого файла раньше отказывала НАВСЕГДА")
    landed = gh.files[INDEX]
    assert landed == remote_now + my_row, (
        "обе записи (параллельной сессии И нашей) обязаны выжить")


def test_additive_only_large_index_update_used_to_refuse_forever(ptg, monkeypatch):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ к (e): отключи Blob-fallback — вернулся старый дефект.

    Если ``get_blob_bytes`` не способен дочитать содержимое (симулируем отказом
    любого вида — ровно то, что раньше возвращал ``None`` без альтернативы),
    страж общей тетради честно отказывает: ``remote_sha`` есть, байт — нет.
    """
    remote_sha = "a" * 40
    content_bytes = "докладная, выдуманная для теста\n".encode() * 10

    def _always_fails(pat, repo, blob_sha):
        raise ptg.RemoteBlobUnavailable("Blob API симулированно недоступен")

    monkeypatch.setattr(ptg, "get_blob_bytes", _always_fails)
    remote_bytes = ptg.get_file_content("pat", "o/r", INDEX, "main", expected_sha=remote_sha)
    assert remote_bytes is None

    with pytest.raises(ptg.EntryLossRefused) as e:
        ptg.guard_entry_loss(INDEX, remote_bytes, content_bytes, remote_sha)
    assert "НЕ ПРОЧИТАНО" in str(e.value)


# ═════════════════════════════════════════════════════════════════════════════
# (f) Contents API недоступен/рвётся, но Blob API в порядке ⇒ правильные байты.
# ═════════════════════════════════════════════════════════════════════════════
def test_contents_api_down_blob_api_fine_still_reads_correct_bytes(ptg, monkeypatch):
    sha = FakeGitHub._blob_sha(_BIG)
    gh = _wire(ptg, monkeypatch, FakeGitHub({INDEX: _BIG}))  # Blob API работает

    out = ptg.get_file_content("pat", "o/r", INDEX, "main", expected_sha=sha)

    assert out == _BIG
    assert all("/contents/" not in u for _, u in gh.calls), (
        "с expected_sha путь на меняющейся ветке вообще не перечитывается")


# ═════════════════════════════════════════════════════════════════════════════
# (g) Blob SHA mismatch (байты не хешируются в запрошенную sha) ⇒ отказ.
# ═════════════════════════════════════════════════════════════════════════════
def test_blob_sha_mismatch_refuses_named(ptg, monkeypatch):
    sha = FakeGitHub._blob_sha(_BIG)
    gh = _wire(ptg, monkeypatch, FakeGitHub({INDEX: _BIG}, corrupt={sha: "НЕ ТО СОВСЕМ".encode()}))

    with pytest.raises(ptg.RemoteBlobShaMismatch):
        ptg.get_blob_bytes("pat", "o/r", sha)

    # get_file_content ПОГЛОЩАЕТ это в None (как и любой другой провал) —
    # «не прочитано» остаётся единственным публичным сигналом вызывающим,
    # которые уже fail-CLOSE'ятся на None.
    assert ptg.get_file_content("pat", "o/r", INDEX, "main", expected_sha=sha) is None


def test_blob_sha_mismatch_is_a_remote_blob_unavailable(ptg):
    assert issubclass(ptg.RemoteBlobShaMismatch, ptg.RemoteBlobUnavailable)


# ═════════════════════════════════════════════════════════════════════════════
# (h) провал чтения remote ⇒ STOP, НИКОГДА не выдаётся за «безопасно».
# ═════════════════════════════════════════════════════════════════════════════
def test_blob_read_failure_never_assumed_safe(ptg, monkeypatch):
    sha = "f" * 40
    _wire(ptg, monkeypatch, FakeGitHub({}, blobs_down=True))

    with pytest.raises(ptg.RemoteBlobUnavailable):
        ptg.get_blob_bytes("pat", "o/r", sha)

    assert ptg.get_file_content("pat", "o/r", INDEX, "main", expected_sha=sha) is None

    # И на уровне стража общей тетради: sha ЕСТЬ, байт — нет ⇒ отказ, не «ОК».
    with pytest.raises(ptg.EntryLossRefused):
        ptg.guard_entry_loss(INDEX, None, b"## row\nx\n", sha)


def test_blob_read_network_failure_refuses_not_silently(ptg, monkeypatch):
    def _boom(*a, **k):
        raise urllib.error.URLError("сеть недоступна")

    monkeypatch.setattr(ptg.urllib.request, "urlopen", _boom)
    with pytest.raises(ptg.RemoteBlobUnavailable):
        ptg.get_blob_bytes("pat", "o/r", "a" * 40)


def test_not_a_sha40_input_refuses_without_any_network_call(ptg, monkeypatch):
    calls = []
    monkeypatch.setattr(ptg.urllib.request, "urlopen",
                        lambda *a, **k: calls.append(1))
    with pytest.raises(ptg.RemoteBlobUnavailable):
        ptg.get_blob_bytes("pat", "o/r", "not-a-sha")
    assert calls == [], "неверная форма sha не должна стоить сетевого вызова"
