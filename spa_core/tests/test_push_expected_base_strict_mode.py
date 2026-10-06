"""Строгий режим `--expected-base` (owner decision по независимому ревью `ddc680757`).

КОНТЕКСТ. Ревьюер нашёл, что фикс чтения файлов >1 МБ (`get_blob_bytes` +
`get_file_content(expected_sha=)`) ПО ДОРОГЕ новό включил авто-ребейз для
`docs/decisions/INDEX.md`: раньше DIVERGED на файле >1 МБ не могла дотянуться до
`rebase_append` (байтов не было — `None`), теперь дотягивается (P0-1). Владелец
подтвердил политику «STOP-on-drift, NO auto-rebase, remote bytes must match the
EXACT expected origin commit» — но ТОЛЬКО для вызывающих, которые об этом явно
просят: автономные циклы полагаются на СЕГОДНЯШНИЙ rebase_append/409-ребилд, и
менять его НЕЛЬЗЯ. Поэтому гарантия — РЕЖИМ (`expected_base=`/`--expected-base`),
а не новое умолчание.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ (пункты контракта из `push_to_github.py`, блок «СТРОГИЙ
РЕЖИМ»):
  (a) живой HEAD ОБЯЗАН совпасть с `expected_base` ДО единой записи;
  (b) страж сравнивает байты ПИНОВАННОГО дерева, не живое чтение ветки;
  (c) DIVERGED (включая чистое дописывание) — STOP, `rebase_append` НЕ вызывается;
  (d) 409/422 при обновлении ref — STOP, без пересборки/второго коммита;
  (e) провал живого чтения известного пути и путь, появившийся ПОСЛЕ пина, —
      тоже STOP (`assert_base_tree_matches(..., strict=True)`).
Плюс P1-2 (независимый ревью): `assert_base_tree_matches`/`RemoteMovedDuringRead`
получают ПЕРВЫЕ тесты вообще, и один из них — через `batch_push` с файлом >1 МБ.

ОБРАТНАЯ СТОРОНА, НАЗВАННАЯ ЯВНО: без `expected_base` (умолчание) поведение НЕ
МЕНЯЕТСЯ — `test_default_mode_still_rebase_appends_unchanged` ниже доказывает,
что обычный режим (используемый автономными циклами) продолжает делать ровно
то же, что при `ddc680757`.

Сеть НЕ ТРОГАЕТСЯ: `urllib.request.urlopen` и `ptg._api` подменены одним
детерминированным фейком (`FakeOrigin`), который считает КАЖДЫЙ вызов — поэтому
«ни одной записи до отказа» здесь измерение, а не предположение.

Запуск: python3 -m pytest spa_core/tests/test_push_expected_base_strict_mode.py -v
"""
from __future__ import annotations

import base64
import hashlib
import importlib.util
import io
import json
import subprocess
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
    return _load("_test_strictbase_ptg", "push_to_github.py")


def _blob_sha(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def _registry_row(n: int) -> bytes:
    return (f"| ADR-{n:05d} | synthetic decision row {n} padding padding padding "
            f"| Accepted | [ADR-{n:05d}](ADR-{n:05d}-slug.md) |\n").encode()


_ROWS = 16000
_BIG = (b"# Registry decisions\n\n| # | Decision | Status | File |\n|---|---|---|---|\n"
       + b"".join(_registry_row(i) for i in range(1, _ROWS + 1)))
assert len(_BIG) > 1_000_000, "фикстура обязана реально превышать 1 МБ"


# ═════════════════════════════════════════════════════════════════════════════
# Фейковый origin: ровно те эндпоинты, которыми пользуются push_file/batch_push.
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


def _http_error(url, code, body=b'{"message":"error"}'):
    return urllib.error.HTTPError(url, code, "error", {}, io.BytesIO(body))


class FakeOrigin:
    """Содержимое путей — единственная истина; HEAD/дерево производятся от него.

    ``ref_fail_times`` — сколько РАЗ подряд PATCH ref обязан ответить 409
    («not a fast forward») перед тем, как принять запись (0 — никогда).
    ``head_commit`` фиксирован (не двигается сам при PUT/PATCH) — тесты СТРОГОГО
    режима именно про то, что `expected_base` зовётся РОВНО с этим значением.
    """

    def __init__(self, files: dict, branch: str = "main",
                truncated: bool = False, ref_fail_times: int = 0,
                live_sha_overrides: dict | None = None,
                blob_response_unmeasured: bool = False,
                ref_response_unmeasured: bool = False):
        self.files = {k: (v.encode() if isinstance(v, str) else v) for k, v in files.items()}
        self.branch = branch
        self.truncated = truncated
        # ОБЯЗАНЫ быть настоящим hex (ре-ревью, P2: `--expected-base` теперь требует
        # полную 40-hex sha, а не просто строку длины 40).
        self.head_commit = "c0ffee" + "0" * 34
        self.tree_sha = "7ee300" + "0" * 34
        self.ref_fail_times = ref_fail_times
        # Живое чтение (Contents API GET) может ОТЛИЧАТЬСЯ от пинованного
        # дерева по требованию теста (смоделировать провал/дрейф живого чтения
        # без того, чтобы это отражалось на дереве). path -> sha|None|"ERROR".
        self.live_sha_overrides = live_sha_overrides or {}
        # Ре-ревью, раунд 3, P3 (инв. #17): ответ POST .../git/blobs или PATCH
        # .../refs без пригодной sha — "unmeasured", НЕ "mismatch" и НЕ "match".
        self.blob_response_unmeasured = blob_response_unmeasured
        self.ref_response_unmeasured = ref_response_unmeasured
        self.calls: list[tuple[str, str]] = []
        self.puts: list[tuple[str, bytes]] = []
        self.blobs_created: list[bytes] = []
        self.trees_created: list[dict] = []
        self.commits_created: list[dict] = []
        self.ref_updates: list[str] = []

    def tree_entries(self) -> list:
        return [{"path": p, "mode": "100644", "type": "blob", "sha": _blob_sha(d)}
                for p, d in self.files.items()]

    # ── `_api` (git/* endpoints) ─────────────────────────────────────────────
    def api(self, pat, method, path, payload=None):
        self.calls.append((method, path))
        if method == "GET" and f"/git/ref/heads/{self.branch}" in path:
            return {"object": {"sha": self.head_commit}}
        if method == "GET" and "/git/commits/" in path:
            return {"tree": {"sha": self.tree_sha}}
        if method == "GET" and "/git/trees/" in path:
            return {"tree": self.tree_entries(), "truncated": self.truncated}
        if method == "GET" and "/git/blobs/" in path:
            blob_sha = path.rsplit("/", 1)[-1]
            for d in self.files.values():
                if _blob_sha(d) == blob_sha:
                    return {"sha": blob_sha, "encoding": "base64",
                           "content": base64.b64encode(d).decode()}
            raise _http_error(path, 404)
        if method == "POST" and path.endswith("/git/blobs"):
            data = base64.b64decode(payload["content"])
            self.blobs_created.append(data)
            if self.blob_response_unmeasured:
                return {"sha": "short"}   # НЕ 40-hex — "unmeasured", не "match"/"mismatch"
            return {"sha": _blob_sha(data)}
        if method == "POST" and path.endswith("/git/trees"):
            self.trees_created.append(payload)
            return {"sha": f"7ee3{len(self.trees_created):036x}"}
        if method == "POST" and path.endswith("/git/commits"):
            self.commits_created.append(payload)
            return {"sha": f"c0ffee{len(self.commits_created):034x}"}
        if method == "PATCH" and "/git/refs/heads/" in path:
            if self.ref_fail_times > 0:
                self.ref_fail_times -= 1
                raise _http_error(path, 422, b'{"message":"Update is not a fast forward"}')
            new_sha = payload["sha"]
            self.ref_updates.append(new_sha)
            if self.ref_response_unmeasured:
                return {"object": {"sha": "short"}}   # НЕ 40-hex — "unmeasured"
            return {"object": {"sha": new_sha}}
        raise AssertionError(f"фейк не знает эндпоинт: {method} {path}")

    # ── Contents API (GET sha/content, PUT) ──────────────────────────────────
    def urlopen(self, req, *a, **kw):
        method = req.get_method()
        url = req.full_url
        self.calls.append((method, url))
        if "/contents/" in url and method == "GET":
            path = url.split("/contents/", 1)[1].split("?", 1)[0]
            if path in self.live_sha_overrides:
                ov = self.live_sha_overrides[path]
                if ov is None:
                    raise _http_error(url, 500)   # живое чтение ПРОВАЛИЛОСЬ
                return _Resp({"sha": ov, "size": 1})
            data = self.files.get(path)
            if data is None:
                raise _http_error(url, 404)
            sha = _blob_sha(data)
            payload = {"sha": sha, "size": len(data)}
            if len(data) <= 900_000:
                payload["encoding"] = "base64"
                payload["content"] = base64.b64encode(data).decode()
            return _Resp(payload)
        if method == "PUT":
            body = json.loads(req.data.decode())
            path = url.split("/contents/", 1)[1]
            content = base64.b64decode(body["content"])
            self.files[path] = content
            self.puts.append((path, content))
            return _Resp({"content": {"sha": _blob_sha(content)}})
        raise AssertionError(f"фейк не знает запрос: {method} {url}")


def _wire(ptg, monkeypatch, origin: FakeOrigin):
    monkeypatch.setattr(ptg, "_api", origin.api)
    monkeypatch.setattr(ptg.urllib.request, "urlopen", origin.urlopen)
    return origin


def _checkout(tmp_path, repo_path: str, base_bytes: bytes, local_bytes: bytes | None = None):
    """Git-копия, ЧЕСТНО основанная на ветке доставки (как `base_version` требует)."""
    root = tmp_path / "checkout"
    root.mkdir()
    full = root / repo_path
    full.parent.mkdir(parents=True, exist_ok=True)
    env = {"GIT_CONFIG_NOSYSTEM": "1", "HOME": str(root)}

    def _git(*args):
        subprocess.run(["git", "-C", str(root), *args], check=True,
                       capture_output=True, env=env)

    _git("init", "-q", "-b", "main")
    _git("config", "user.email", "t@example.invalid")
    _git("config", "user.name", "t")
    full.write_bytes(base_bytes)
    _git("add", "-A")
    _git("commit", "-qm", "база")
    _git("update-ref", "refs/remotes/origin/main", "HEAD")
    if local_bytes is not None:
        full.write_bytes(local_bytes)
    return root, full


# ═════════════════════════════════════════════════════════════════════════════
# (a) живой HEAD не совпал с --expected-base ⇒ STOP ДО ЛЮБОЙ записи.
# ═════════════════════════════════════════════════════════════════════════════
def test_strict_mode_head_moved_stops_before_any_write_single_file(ptg, monkeypatch, tmp_path):
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: _BIG}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", tmp_path)
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG + _registry_row(_ROWS + 1))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(f), "цикл", "o/r",
                        expected_base="deadbeef" * 5)   # НЕ head_commit фейка

    assert res["ok"] is False and res.get("diverged") is True
    assert "--expected-base" in res["error"], "причина отказа обязана называть себя"
    assert "deadbeef" * 5 in res["error"], "отказ обязан называть ЗАДАННУЮ sha, не только факт несовпадения"
    assert origin.puts == [], "строгий режим обязан отказать ДО единой записи"
    assert origin.blobs_created == [] and origin.ref_updates == [] and origin.commits_created == []


def test_strict_mode_head_moved_stops_before_any_write_batch(ptg, monkeypatch, tmp_path):
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG + _registry_row(_ROWS + 1))
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: _BIG}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    with pytest.raises(ptg.BaseDriftRefused):
        ptg.batch_push("pat", [str(f)], "цикл", "o/r", "main",
                       expected_base="deadbeef" * 5)

    assert origin.puts == [] and origin.blobs_created == [] and origin.ref_updates == []


def test_strict_mode_rejects_a_short_sha_prefix(ptg, monkeypatch, tmp_path):
    """Ре-ревью, P2: `--expected-base` требует ПОЛНУЮ 40-hex sha — короткий
    префикс (даже если он ЖИВОЙ и совпал бы по старому правилу) — именованный
    отказ ДО сети, а не «похоже совпало»."""
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: _BIG}))

    short = origin.head_commit[:8]   # живой префикс — раньше ПРИНИМАЛСЯ
    with pytest.raises(ptg.ExpectedBaseNotExact):
        ptg.assert_expected_base("pat", "o/r", "main", short)

    assert origin.calls == [], "форма входа проверяется ДО единого сетевого вызова"


def test_strict_mode_requires_exactly_40_hex_chars(ptg, monkeypatch, tmp_path):
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: _BIG}))

    with pytest.raises(ptg.ExpectedBaseNotExact):
        ptg.assert_expected_base("pat", "o/r", "main", origin.head_commit + "a")  # 41

    with pytest.raises(ptg.ExpectedBaseNotExact):
        ptg.assert_expected_base("pat", "o/r", "main", "not-hex-at-all-" + "0" * 25)

    # Полная, ТОЧНО совпадающая sha — проходит.
    base_commit_sha, _ = ptg.assert_expected_base("pat", "o/r", "main", origin.head_commit)
    assert base_commit_sha == origin.head_commit


def test_expected_base_not_exact_is_a_base_drift_refused(ptg):
    assert issubclass(ptg.ExpectedBaseNotExact, ptg.BaseDriftRefused)


# ═════════════════════════════════════════════════════════════════════════════
# (b)+(c) DIVERGED (включая чистое дописывание параллельной сессии) ⇒ STOP,
# rebase_append НЕ вызывается. Это ФЛИП теста из test_push_remote_blob_read.py,
# где ТОТ ЖЕ сценарий в ОБЫЧНОМ режиме проходит через пере-базу.
# ═════════════════════════════════════════════════════════════════════════════
def test_strict_mode_append_only_divergence_stops_no_rebase(ptg, monkeypatch, tmp_path):
    """Remote УЖЕ принял строку параллельной сессии — в обычном режиме это
    чистое дописывание и пуш проходит (см. test_push_remote_blob_read.py);
    в строгом режиме это STOP, и ни одна запись не уходит на remote."""
    other_row = _registry_row(_ROWS + 2)
    remote_now = _BIG + other_row
    my_row = _registry_row(_ROWS + 1)
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG + my_row)
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: remote_now}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(f), "цикл", "o/r",
                        expected_base=origin.head_commit)

    assert res["ok"] is False and res.get("diverged") is True
    assert origin.puts == [], ("авто-ребейз СРАБОТАЛ бы в обычном режиме — строгий "
                               "обязан остановиться ДО записи (P0-1 ревью)")
    assert origin.files[INDEX] == remote_now, "remote не тронут"


def test_default_mode_still_rebase_appends_unchanged(ptg, monkeypatch, tmp_path):
    """Контрольная сторона: БЕЗ `expected_base` поведение `ddc680757` цело —
    автономные циклы на него полагаются, и эта правка его не трогает."""
    other_row = _registry_row(_ROWS + 2)
    remote_now = _BIG + other_row
    my_row = _registry_row(_ROWS + 1)
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG + my_row)
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: remote_now}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(f), "цикл", "o/r")   # expected_base НЕ передан

    assert res["ok"] is True, res
    assert origin.files[INDEX] == remote_now + my_row, "обе записи выжили (пере-база)"


def test_strict_mode_passes_without_any_flag_when_remote_equals_base(ptg, monkeypatch, tmp_path):
    """Требование ревью: additive-only в СТРОГОМ режиме проходит, когда remote
    РОВНО равен нашей базе (SAFE) — без `--allow-overwrite` и без единого флага
    согласия, кроме самого `--expected-base`."""
    my_row = _registry_row(_ROWS + 1)
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG + my_row)
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: _BIG}))   # remote == база, никто не трогал
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(f), "цикл", "o/r", expected_base=origin.head_commit)

    assert res["ok"] is True, res
    assert _BIG + my_row in origin.blobs_created, (
        "итоговое содержимое обязано уехать ОДНИМ blob'ом через Git Data API")


def test_strict_mode_batch_append_only_divergence_stops(ptg, monkeypatch, tmp_path):
    """Тот же (b)+(c) контракт на batch-пути, с файлом >1 МБ (P1-2: до этой
    правки batch-путь ни разу не тестировался с файлом >1 МБ вообще)."""
    other_row = _registry_row(_ROWS + 2)
    remote_now = _BIG + other_row
    my_row = _registry_row(_ROWS + 1)
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG + my_row)
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: remote_now}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    with pytest.raises(ptg.BaseDriftRefused):
        ptg.batch_push("pat", [str(f)], "цикл", "o/r", "main",
                       expected_base=origin.head_commit)

    assert origin.puts == [] and origin.ref_updates == []


# ═════════════════════════════════════════════════════════════════════════════
# (d) 409/422 при PATCH ref ⇒ STOP, БЕЗ пересборки/второго коммита.
# ═════════════════════════════════════════════════════════════════════════════
def test_strict_mode_409_on_ref_update_stops_no_second_commit(ptg, monkeypatch, tmp_path):
    # Строгий режим судит ЛЮБОЕ состояние кроме SAFE — новому файлу без git-базы
    # нужна измеримая (хоть и пустая) база, иначе отказ случится РАНЬШЕ, на
    # guard_overwrite, и тест измерил бы не ref-update, а другую дверь.
    root, f = _checkout(tmp_path, "placeholder.txt", b"x\n")
    f = root / "a.py"
    f.write_text("print(1)\n")
    origin = _wire(ptg, monkeypatch, FakeOrigin({}, ref_fail_times=1))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    with pytest.raises(ptg.BaseDriftRefused):
        ptg.batch_push("pat", [str(f)], "цикл", "o/r", "main",
                       expected_base=origin.head_commit)

    assert len(origin.commits_created) == 1, "ПЕРЕсборки/второго коммита быть не должно"
    assert origin.ref_updates == [], "ref не сдвинулся — ни первая, ни вторая попытка"


def test_strict_mode_single_file_push_file_also_stops_on_409_no_second_commit(
        ptg, monkeypatch, tmp_path):
    """P1-NEW (ре-ревью, раунд 2): `push_file(..., expected_base=)` на ОДНОМ
    файле ОБЯЗАН пройти через `batch_push`, а не через Contents API PUT —
    у PUT нет понятия родителя, и "HEAD продвинулся МЕЖДУ чтением базы и
    записью" (здесь — PATCH ref, отвечающий 409/422) ловится ТОЛЬКО если
    коммит строится с `parent=pinned_base` и ref обновляется НЕ force'ом.
    Это и есть сценарий «HEAD сдвинулся во время записи»: наш коммит УЖЕ
    создан (с правильным родителем), но PATCH его отклоняет — значит он НЕ
    приземлился на чужом родителе, он просто не приземлился вовсе.
    """
    root, f = _checkout(tmp_path, "placeholder.txt", b"x\n")
    f = root / "a.py"
    f.write_text("print(1)\n")
    origin = _wire(ptg, monkeypatch, FakeOrigin({}, ref_fail_times=1))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(f), "цикл", "o/r", expected_base=origin.head_commit)

    assert res["ok"] is False and res.get("diverged") is True
    assert len(origin.commits_created) == 1, "ПЕРЕсборки/второго коммита быть не должно"
    assert origin.commits_created[0]["parents"] == [origin.head_commit], (
        "коммит был бы корректно припаркован на пинованной базе ДО отказа")
    assert origin.ref_updates == [], (
        "ref НЕ сдвинулся — ни один коммит не приземлился ни на каком родителе")


def test_strict_mode_single_file_uses_batch_push_not_contents_put(ptg, monkeypatch, tmp_path):
    """Прямое доказательство P1-NEW-фикса: single-file strict НЕ делает PUT на
    Contents API вовсе (у PUT нет родителя, который можно было бы пинить) —
    только git/blobs + git/trees + git/commits + PATCH git/refs."""
    my_row = _registry_row(_ROWS + 1)
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG + my_row)
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: _BIG}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(f), "цикл", "o/r", expected_base=origin.head_commit)

    assert res["ok"] is True, res
    assert not any(m == "PUT" for m, _ in origin.calls), (
        "строгий single-file не имеет права писать через Contents API PUT вообще "
        "(у PUT нет понятия родительского коммита — ровно дефект P1-NEW)")
    assert len(origin.commits_created) == 1 and len(origin.ref_updates) == 1
    assert _BIG + my_row in origin.blobs_created, (
        "итоговое содержимое обязано уехать ОДНИМ blob'ом через Git Data API")


def test_default_mode_409_on_ref_update_still_rebuilds_unchanged(ptg, monkeypatch, tmp_path):
    """Контроль: БЕЗ `expected_base` 409/422 всё ещё пересобирает и коммитит
    второй раз — это умолчание `ddc680757`, и оно НЕ меняется этой правкой."""
    f = tmp_path / "repo" / "a.py"
    f.parent.mkdir(parents=True)
    f.write_text("print(1)\n")
    origin = _wire(ptg, monkeypatch, FakeOrigin({}, ref_fail_times=1))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", f.parent)

    res = ptg.batch_push("pat", [str(f)], "цикл", "o/r", "main")   # без expected_base

    assert res["ok"] is True
    assert len(origin.commits_created) == 2, "пересборка создаёт ВТОРОЙ коммит"
    assert len(origin.ref_updates) == 1, "вторая попытка PATCH обязана УСПЕТЬ"


# ═════════════════════════════════════════════════════════════════════════════
# (e) провал живого чтения известного пути / путь появился ПОСЛЕ пина ⇒ STOP.
# ═════════════════════════════════════════════════════════════════════════════
def test_strict_mode_live_sha_none_for_known_path_stops(ptg, monkeypatch, tmp_path):
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG)
    origin = _wire(ptg, monkeypatch,
                   FakeOrigin({INDEX: _BIG}, live_sha_overrides={INDEX: None}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(f), "цикл", "o/r", expected_base=origin.head_commit)

    assert res["ok"] is False and res.get("diverged") is True
    assert origin.puts == []


def test_default_mode_live_sha_none_for_known_path_does_not_stop(ptg):
    """Положительный контроль к (e): БЕЗ `strict=True` этот же разрыв — молчаливый
    `continue` (как и ДО этой правки); `assert_base_tree_matches` не меняет
    умолчание ни на бит."""
    changed = [(INDEX, "/x", None)]
    base_tree_shas = {INDEX: "deadbeef" * 5}
    ptg_mod = _load("_test_strictbase_default_ptg", "push_to_github.py")
    ptg_mod.assert_base_tree_matches(changed, base_tree_shas, False, "basetree0" * 4)
    # не бросило — это и есть утверждение


def test_assert_base_tree_matches_is_exercised_directly_live_none_strict(ptg):
    """P1-2: `assert_base_tree_matches`/`RemoteMovedDuringRead` — прямой unit-тест
    (до этой правки у них не было НИ ОДНОГО теста, независимый ревью)."""
    changed = [(INDEX, "/x", None)]
    base_tree_shas = {INDEX: "deadbeef" * 5}
    with pytest.raises(ptg.RemoteMovedDuringRead):
        ptg.assert_base_tree_matches(changed, base_tree_shas, False,
                                     "basetree0" * 4, strict=True)


def test_assert_base_tree_matches_live_sha_disagrees_with_pinned_strict_and_default(ptg):
    """Базовый дрейф-кейс (всегда отказывает, В ОБЕИХ режимах) — тоже без
    единого теста до независимого ревью (P1-2)."""
    changed = [(INDEX, "/x", "live0000" * 5)]
    base_tree_shas = {INDEX: "pinned00" * 5}
    with pytest.raises(ptg.RemoteMovedDuringRead):
        ptg.assert_base_tree_matches(changed, base_tree_shas, False, "basetree0" * 4)
    with pytest.raises(ptg.RemoteMovedDuringRead):
        ptg.assert_base_tree_matches(changed, base_tree_shas, False, "basetree0" * 4,
                                     strict=True)


def test_strict_mode_path_appeared_after_pin_stops(ptg):
    """Живая sha ЕСТЬ, а пути НЕТ в неусечённом пинованном дереве — появился
    ПОСЛЕ пина. STOP только в строгом режиме; обычный режим молчит (не повод)."""
    changed = [("new/path.md", "/x", "livesha0" * 5)]
    base_tree_shas = {}   # пути нет в пинованной базе

    assert ptg.assert_base_tree_matches(changed, base_tree_shas, False,
                                        "basetree0" * 4) is None   # обычный: не отказ

    with pytest.raises(ptg.RemoteMovedDuringRead):
        ptg.assert_base_tree_matches(changed, base_tree_shas, False, "basetree0" * 4,
                                     strict=True)


def test_strict_mode_truncated_tree_is_unmeasured_not_safe(ptg):
    """Усечённое дерево — присутствие НЕ ИЗМЕРЕНО; строгий режим отказывает на
    неизмеренном (инв. #17), обычный — молчит (объявленная граница)."""
    changed = [("maybe/new.md", "/x", "livesha0" * 5)]
    base_tree_shas = {}

    assert ptg.assert_base_tree_matches(changed, base_tree_shas, True,
                                        "basetree0" * 4) is None   # усечение: обычный не судит

    with pytest.raises(ptg.RemoteMovedDuringRead):
        ptg.assert_base_tree_matches(changed, base_tree_shas, True, "basetree0" * 4,
                                     strict=True)


# ═════════════════════════════════════════════════════════════════════════════
# P2-2: докстринг `get_file_content` больше не несёт неверного «ТОЛЬКО».
# ═════════════════════════════════════════════════════════════════════════════
def test_get_file_content_docstring_no_longer_claims_rebase_only(ptg):
    """P2-2: докстринг больше НЕ УТВЕРЖДАЕТ, что `get_file_content` нужна только
    для пере-базы — первая строка тела (само утверждение, а не историческая
    сноска ниже) обязана называть ВСЕ три применения."""
    doc = ptg.get_file_content.__doc__
    first_paragraph = doc.split("\n\n")[1]   # [0] — однострочное summary
    assert "ТОЛЬКО для пере-базы" not in first_paragraph
    assert "rebase_append" in first_paragraph
    assert "guard_entry_loss" in first_paragraph
    assert "expected-base" in first_paragraph or "strict_base" in first_paragraph


# ═════════════════════════════════════════════════════════════════════════════
# РАУНД 3 независимого ревью (8e416ade1 → CHANGES_REQUIRED, minor):
#
# P2-NEW: `main()` с `--dry-run --expected-base <sha>` падал `KeyError: 'action'`
# — `_push_file_via_batch`'s dry-run ответ не несёт `action`, а `main()` печатает
# `r['action']` безусловно. Воспроизводилось и на 1, и на 3 файлах, на ВЕРНОЙ sha
# (не только на неверной) — рекламируемая pre-валидация пина была недоступна
# из CLI. Выживший мутант M6 («dry-run возвращается ДО `batch_push`, минуя
# проверку HEAD») не был пойман ни одним тестом — закрывается здесь же.
#
# P3 (инв. #17): `_push_file_via_batch` безусловно писала `verified: "match"`,
# даже когда вердикт blob/ref был "unmeasured" — ровно класс «не измерено,
# выданное за безопасно», против которого написан блок «СВЕРКА ДОСТАВЛЕННОГО».
# ═════════════════════════════════════════════════════════════════════════════

def _run_main_strict(ptg, monkeypatch, argv):
    monkeypatch.setattr(ptg, "get_pat", lambda: "pat")
    monkeypatch.setattr(sys, "argv", ["push_to_github.py", *argv])
    with pytest.raises(SystemExit) as exc:
        ptg.main()
    return exc.value.code


def _no_writes(origin) -> bool:
    return not any(m in ("POST", "PATCH", "PUT") for m, _ in origin.calls)


# ── (1) P2-NEW: `main() --dry-run --expected-base` ──────────────────────────
def test_main_dry_run_strict_correct_sha_exits_zero_read_only(ptg, monkeypatch, tmp_path):
    """Было: `KeyError: 'action'` на ВЕРНОЙ sha. Теперь — rc 0, только GET."""
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG)
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: _BIG}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    code = _run_main_strict(ptg, monkeypatch, [
        "--files", str(f), "--message", "m", "--dry-run",
        "--expected-base", origin.head_commit, "--repo", "o/r"])

    assert code == 0
    assert _no_writes(origin), "dry-run обязан быть ЧИСТО read-only"
    assert any(m == "GET" for m, _ in origin.calls), "HEAD обязан быть ПРОЧИТАН, не пропущен"


def test_main_dry_run_strict_correct_sha_three_files_exits_zero(ptg, monkeypatch, tmp_path):
    """Тот же сценарий на ТРЁХ файлах — ровно форма, на которой ревьюер
    воспроизвёл KeyError (main() гонит dry-run через цикл push_file, по
    файлу за раз, даже когда файлов больше одного)."""
    root, f0 = _checkout(tmp_path, "placeholder.txt", b"x\n")
    files = []
    for i in range(3):
        p = root / f"new{i}.py"
        p.write_text(f"{i}\n")
        files.append(str(p))
    origin = _wire(ptg, monkeypatch, FakeOrigin({}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    code = _run_main_strict(ptg, monkeypatch, [
        "--files", *files, "--message", "m", "--dry-run",
        "--expected-base", origin.head_commit, "--repo", "o/r"])

    assert code == 0
    assert _no_writes(origin)


def test_main_dry_run_strict_wrong_sha_exits_nonzero_no_writes(ptg, monkeypatch, tmp_path):
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG)
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: _BIG}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    code = _run_main_strict(ptg, monkeypatch, [
        "--files", str(f), "--message", "m", "--dry-run",
        "--expected-base", "d" * 40, "--repo", "o/r"])

    assert code != 0
    assert _no_writes(origin)


# ── (1) kill surviving mutant M6: dry-run must still check HEAD ─────────────
def test_strict_mode_dry_run_still_checks_head_before_returning(ptg, monkeypatch, tmp_path):
    """Убивает M6: dry-run в строгом режиме НЕ имеет права вернуться БЕЗ
    проверки живого HEAD — и уж точно не имеет права писать."""
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG)
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: _BIG}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(f), "цикл", "o/r", dry_run=True,
                        expected_base="d" * 40)   # НЕ head_commit фейка

    assert res["ok"] is False and res.get("diverged") is True
    assert _no_writes(origin)


def test_strict_mode_dry_run_with_correct_base_reports_an_action(ptg, monkeypatch, tmp_path):
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG)
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: _BIG}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(f), "цикл", "o/r", dry_run=True,
                        expected_base=origin.head_commit)

    assert res["ok"] is True and res["dry_run"] is True
    assert res.get("action"), "без 'action' main() падает KeyError (P2-NEW)"
    assert _no_writes(origin)


# ── (2) P3 / инв. #17: "verified" обязан различать match/unmeasured ─────────
def test_strict_mode_unmeasured_blob_verification_is_not_reported_as_match(
        ptg, monkeypatch, tmp_path):
    my_row = _registry_row(_ROWS + 1)
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG + my_row)
    origin = _wire(ptg, monkeypatch,
                   FakeOrigin({INDEX: _BIG}, blob_response_unmeasured=True))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(f), "цикл", "o/r", expected_base=origin.head_commit)

    assert res["ok"] is True, res
    assert res.get("verified") == "unmeasured", (
        "инв. #17: blob пришёл без пригодной sha — 'match' здесь было бы "
        "«не измерено, выданное за безопасно»")


def test_strict_mode_unmeasured_ref_verification_is_not_reported_as_match(
        ptg, monkeypatch, tmp_path):
    my_row = _registry_row(_ROWS + 1)
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG + my_row)
    origin = _wire(ptg, monkeypatch,
                   FakeOrigin({INDEX: _BIG}, ref_response_unmeasured=True))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(f), "цикл", "o/r", expected_base=origin.head_commit)

    assert res["ok"] is True, res
    assert res.get("verified") == "unmeasured"


def test_strict_mode_fully_verified_push_reports_match(ptg, monkeypatch, tmp_path):
    """Позитивный контроль: когда и blob, и ref ДЕЙСТВИТЕЛЬНО подтверждены —
    'match', а не осторожное 'unmeasured' по умолчанию."""
    my_row = _registry_row(_ROWS + 1)
    root, f = _checkout(tmp_path, INDEX, _BIG, _BIG + my_row)
    origin = _wire(ptg, monkeypatch, FakeOrigin({INDEX: _BIG}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    res = ptg.push_file("pat", str(f), "цикл", "o/r", expected_base=origin.head_commit)

    assert res["ok"] is True
    assert res.get("verified") == "match"


def test_batch_push_verified_field_is_the_aggregate_not_hardcoded(ptg, monkeypatch, tmp_path):
    """Прямая проверка на уровне `batch_push`: поле `"verified"` в ответе
    существует и честно отражает вердикт (не захардкожено где-то выше)."""
    root, f = _checkout(tmp_path, "placeholder.txt", b"x\n")
    new_file = root / "a.py"
    new_file.write_text("print(1)\n")
    origin = _wire(ptg, monkeypatch, FakeOrigin({}))
    monkeypatch.setattr(ptg, "PROJECT_ROOT", root)

    result = ptg.batch_push("pat", [str(new_file)], "цикл", "o/r", "main")

    assert result["verified"] == "match"
