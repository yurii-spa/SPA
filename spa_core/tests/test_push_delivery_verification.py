"""
spa_core/tests/test_push_delivery_verification.py

Гейт против рецидива: **пушер не отчитывается `OK` о доставке, которую не
сверял**.

ЧТО ЛОВИМ (карточка `agent-pusher-does-not-verify-what-it-delivered`, найдено
циклом #99). Пушер печатал `OK … pushed=N, skipped=0`, ни разу не сравнив
доставленное с отправленным: побайтовую сверку делала ДИСЦИПЛИНА вызывающего —
руками, после пуша, `git show origin/main:<файл> | cmp - <файл>`. Дубль хвоста
`docs/journal/2026-W32.md` в цикле #95 поймала именно она. Убери эту строчку из
протокола (а живые вызывающие — `com.spa.autopush` → `auto_push.sh`, дневной
цикл, кастодиан сайта — её и не делают, там никто не смотрит в момент запуска)
— и порча уехала бы в общую память проекта под зелёным `OK`. Это класс
#29/#31/#35–#38/#40: утверждение об измерении, которого не было.

ЧТО ЗАКРЕПЛЯЕТСЯ ЗДЕСЬ (все три исхода, а не только счастливый):
  1. расхождение доставленного с ответом remote даёт FAIL, а не `OK`
     (положительные контроли: подменяем ответ так, чтобы remote отличался, —
     тесты обязаны краснеть, и краснеют на всех трёх точках записи);
  2. совпадение НЕ даёт ложных красных;
  3. «не смогли сверить» остаётся «не измерено», печатается явной строкой и
     доставку НЕ блокирует (инвариант #2 — но и не превращается в стоп-кран,
     иначе гейт научил бы обходить себя).

ЦЕНА СВЕРКИ ИЗМЕРЕНА, А НЕ ОБЪЯВЛЕНА: `test_verification_costs_zero_extra_*`
считают запросы к API до и после и требуют РАВЕНСТВА. Второго GET после записи
нет намеренно: Contents API согласован в конечном счёте (тот же эффект уже
измерен на refs — `_read_ref_with_404_retry`), и чтение сразу после PUT могло бы
вернуть прежнее содержимое ⇒ ложный красный, то есть тихо вставшая доставка.
Сверяем sha из ответа на НАШУ запись.

Сеть НЕ ТРОГАЕТСЯ: `_api` и `urllib.request.urlopen` подменяются
детерминированными фейками; ни один тест не ходит наружу.

Запуск: python3 -m pytest spa_core/tests/test_push_delivery_verification.py -v
"""
from __future__ import annotations

import base64
import importlib.util
import json
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
    return _load("_test_delivery_ptg", "push_to_github.py")


@pytest.fixture()
def batch_cli():
    return _load("_test_delivery_batch", "push_to_github_batch.py")


@pytest.fixture()
def repo(tmp_path):
    """Настоящий git-репозиторий: repo_relative_path работает по факту."""
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    return r


def _write(repo: Path, rel: str, text: str) -> Path:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


# ═════════════════════════════════════════════════════════════════════════════
# 0. Вердикт как таковой — три исхода, и «не измерено» не равно «совпало»
# ═════════════════════════════════════════════════════════════════════════════
def test_verdict_match_when_returned_sha_equals_sent_bytes(ptg):
    data = b"hello\n"
    v = ptg.verify_blob_delivery(data, ptg.git_blob_sha(data), "docs/a.md")
    assert v["state"] == "match"
    assert v["note"] == "", "у совпадения не должно быть шумовой ноты"


def test_verdict_mismatch_when_remote_confirms_other_content(ptg):
    v = ptg.verify_blob_delivery(b"hello\n", "f" * 40, "docs/a.md")
    assert v["state"] == "mismatch"
    assert "docs/a.md" in v["note"], "в вердикте обязан быть назван файл"


@pytest.mark.parametrize("returned", [
    None,                    # поля нет вовсе
    "",                      # пустая строка
    "abcdef1234567890",      # укороченная sha (так отвечают некоторые стабы)
    "z" * 40,                # не hex
    12345,                   # не строка
    ["f" * 40],              # не скаляр
])
def test_verdict_unmeasured_is_never_reported_as_match(ptg, returned):
    """Инвариант #2: непрочитанная sha — «не измерено», а не «совпало»."""
    v = ptg.verify_blob_delivery(b"hello\n", returned, "docs/a.md")
    assert v["state"] == "unmeasured", (
        f"{returned!r} не позволяет сверить доставку — это обязано остаться "
        f"«не измерено», иначе пушер снова утверждает то, чего не мерял")
    assert "НЕ ИЗМЕРЕНО" in v["note"]


def test_verdict_compares_sent_bytes_not_the_file_on_disk(ptg, repo):
    """Страж перезаписи отправляет «свежий remote + наш хвост», а не файл.

    Сверка с содержимым файла краснела бы каждый раз, когда пере-база
    сработала ПО ДЕЛУ, — то есть наказывала бы за правильное поведение.
    """
    on_disk = b"base\nmy tail\n"
    actually_sent = b"base\nother session\nmy tail\n"     # результат пере-базы
    v = ptg.verify_blob_delivery(actually_sent, ptg.git_blob_sha(actually_sent), "j.md")
    assert v["state"] == "match"
    assert ptg.git_blob_sha(on_disk) != ptg.git_blob_sha(actually_sent)


def test_sha_comparison_is_case_insensitive(ptg):
    data = b"hello\n"
    v = ptg.verify_blob_delivery(data, ptg.git_blob_sha(data).upper(), "a.md")
    assert v["state"] == "match", "регистр hex не является расхождением содержимого"


# ═════════════════════════════════════════════════════════════════════════════
# 1. Contents API (одиночный файл): PUT → сверка `content.sha`
# ═════════════════════════════════════════════════════════════════════════════
class FakeContentsRemote:
    """Детерминированный remote для одиночного пути. Считает ЗАПРОСЫ.

    `sha_override` — единственная точка, которой положительные контроли делают
    ответ «неправдой»: всё остальное поведение остаётся настоящим.
    """

    def __init__(self, sha_override=None, files=None):
        self.files: dict = dict(files or {})
        self.requests: list[str] = []          # каждый обращение к API
        self.sha_override = sha_override

    def get_file_sha(self, ptg):
        def _sha(pat, repo, repo_path, branch="main"):
            self.requests.append(f"GET {repo_path}")
            data = self.files.get(repo_path)
            return None if data is None else ptg.git_blob_sha(data)
        return _sha

    def get_file_content(self):
        def _content(pat, repo, repo_path, branch="main"):
            self.requests.append(f"GET-content {repo_path}")
            return self.files.get(repo_path)
        return _content

    def urlopen(self, ptg):
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
            self.requests.append(f"PUT {path}")
            self.files[path] = content
            # Настоящий GitHub возвращает sha ИМЕННО того blob'а, который
            # сохранил. Override позволяет соврать — на этом и строятся
            # положительные контроли.
            sha = self.sha_override if self.sha_override is not None \
                else ptg.git_blob_sha(content)
            return _Resp({"content": {"sha": sha}})

        return _open


def _wire_contents(ptg, monkeypatch, remote, repo):
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "get_file_sha", remote.get_file_sha(ptg))
    monkeypatch.setattr(ptg, "get_file_content", remote.get_file_content())
    monkeypatch.setattr(ptg.urllib.request, "urlopen", remote.urlopen(ptg))
    monkeypatch.delenv("SPA_AUTONOMOUS", raising=False)


def test_single_file_push_is_ok_and_marked_verified(ptg, monkeypatch, repo):
    """Честный remote ⇒ `ok` И явная отметка, что сверка СОСТОЯЛАСЬ."""
    remote = FakeContentsRemote()
    _wire_contents(ptg, monkeypatch, remote, repo)
    f = _write(repo, "docs/a.md", "содержимое\n")

    res = ptg.push_file("pat", str(f), "msg", "o/r")

    assert res["ok"], res
    assert res["verified"] == "match", (
        "успех обязан быть ИЗМЕРЕННЫМ: без этой отметки `OK` снова означает "
        "лишь «PUT не упал»")


def test_single_file_push_FAILS_when_remote_confirms_other_content(ptg, monkeypatch, repo):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: remote подтвердил не наши байты ⇒ FAIL, не OK."""
    remote = FakeContentsRemote(sha_override="f" * 40)
    _wire_contents(ptg, monkeypatch, remote, repo)
    f = _write(repo, "docs/a.md", "содержимое\n")

    res = ptg.push_file("pat", str(f), "msg", "o/r")

    assert not res["ok"], (
        "пушер обязан краснеть, когда доставленное не совпало с отправленным — "
        "ровно этого не делал код до правки")
    assert res["verified"] == "mismatch"
    assert "ДОСТАВЛЕНО НЕ ТО" in res["error"]
    assert "docs/a.md" in res["error"], "в отказе обязан быть назван файл"


def test_single_file_push_survives_unreadable_sha_but_says_so(ptg, monkeypatch, repo, capsys):
    """«Не смогли сверить» ⇒ доставка НЕ блокируется, но и не молчит."""
    remote = FakeContentsRemote(sha_override="abcdef")     # не 40-hex
    _wire_contents(ptg, monkeypatch, remote, repo)
    f = _write(repo, "docs/a.md", "содержимое\n")

    res = ptg.push_file("pat", str(f), "msg", "o/r")

    assert res["ok"], (
        "нечитаемая sha в ответе — не повод останавливать доставку: гейт, "
        "который блокирует на ровном месте, научили бы обходить")
    assert res["verified"] == "unmeasured"
    assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out, (
        "молчаливого «не измерено» здесь быть не должно — это и есть fail-OPEN")


def test_verification_costs_zero_extra_requests_on_contents_path(ptg, monkeypatch, repo):
    """ЦЕНА ИЗМЕРЕНА: сверка не добавила ни одного обращения к API.

    Именно этого требует карточка: «сначала измерить, а не включить проверку».
    Второй GET после PUT дал бы и стоимость, и риск ложного красного из-за
    задержки согласованности Contents API.
    """
    remote = FakeContentsRemote()
    _wire_contents(ptg, monkeypatch, remote, repo)
    f = _write(repo, "docs/a.md", "содержимое\n")

    ptg.push_file("pat", str(f), "msg", "o/r")

    puts = [r for r in remote.requests if r.startswith("PUT")]
    gets = [r for r in remote.requests if r.startswith("GET")]
    assert len(puts) == 1, remote.requests
    assert len(gets) == 1, (
        f"после PUT не должно быть ни одного дополнительного чтения, "
        f"а их {len(gets)}: {remote.requests}")


# ═════════════════════════════════════════════════════════════════════════════
# 2. Git Data API (набор файлов): blob → tree → commit → ref
# ═════════════════════════════════════════════════════════════════════════════
class FakeGitData:
    """Фейк Git Data API, отвечающий ПРАВДУ, если её не подменили явно."""

    def __init__(self, blob_sha_override=None, ref_sha_override=None):
        self.calls: list[tuple[str, str]] = []
        self.blob_sha_override = blob_sha_override
        self.ref_sha_override = ref_sha_override
        self.ref_updates: list[str] = []
        self._n = 0
        self._ptg = None

    def bind(self, ptg):
        self._ptg = ptg
        return self

    def _next(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}{self._n:039d}"        # ровно 40 знаков

    def api(self, pat, method, path, payload=None):
        self.calls.append((method, path))
        if method == "GET" and "/git/ref/heads/" in path:
            return {"object": {"sha": "a" * 40}}
        if method == "GET" and "/git/commits/" in path:
            return {"tree": {"sha": "b" * 40}}
        if method == "GET" and "/git/trees/" in path:
            return {"tree": [], "truncated": False}
        if method == "POST" and path.endswith("/git/blobs"):
            data = base64.b64decode(payload["content"])
            true_sha = self._ptg.git_blob_sha(data)
            return {"sha": self.blob_sha_override or true_sha}
        if method == "POST" and path.endswith("/git/trees"):
            return {"sha": self._next("c")}
        if method == "POST" and path.endswith("/git/commits"):
            return {"sha": self._next("d")}
        if method == "PATCH" and "/git/refs/heads/" in path:
            self.ref_updates.append(payload["sha"])
            return {"object": {"sha": self.ref_sha_override or payload["sha"]}}
        raise AssertionError(f"фейк не знает эндпоинт: {method} {path}")


@pytest.fixture()
def wired_batch(ptg, repo, monkeypatch):
    def _make(**kw):
        gh = FakeGitData(**kw).bind(ptg)
        monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
        monkeypatch.setattr(ptg, "_api", gh.api)
        monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: None)
        return gh
    return _make


def test_batch_push_is_ok_when_remote_confirms_our_blobs_and_commit(wired_batch, ptg, repo):
    gh = wired_batch()
    files = [str(_write(repo, f"pkg/f{i}.py", f"x = {i}\n")) for i in range(3)]

    res = ptg.batch_push("pat", files, "msg", "o/r", "main")

    assert res["ok"] and res["count"] == 3
    assert len(gh.ref_updates) == 1


def test_batch_push_REFUSES_when_blob_sha_is_not_our_content(wired_batch, ptg, repo):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на первом звене цепочки.

    Расхождение на blob'е означает, что дерево соберётся из НЕ НАШЕГО
    содержимого. Отказ обязан случиться ДО коммита: ветка ещё не сдвинута,
    поэтому на remote ничего не остаётся наполовину.
    """
    gh = wired_batch(blob_sha_override="f" * 40)
    files = [str(_write(repo, "a.py", "a\n")), str(_write(repo, "b.py", "b\n"))]

    with pytest.raises(ptg.DeliveryUnverified) as exc:
        ptg.batch_push("pat", files, "msg", "o/r", "main")

    assert "ДОСТАВЛЕНО НЕ ТО" in str(exc.value)
    assert gh.ref_updates == [], (
        "ветку двигать нельзя: содержимое blob'ов не подтверждено")
    assert not any(m == "POST" and p.endswith("/git/commits") for m, p in gh.calls), (
        "коммит не должен создаваться после несверенного blob'а")


def test_batch_push_REFUSES_when_branch_did_not_move_to_our_commit(wired_batch, ptg, repo):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ на последнем звене: ветку увёл кто-то другой.

    Без этой сверки печаталось бы `OK: 1 коммит …`, хотя на `main` наших
    файлов НЕТ — то есть «доставлено» о недоставленном.
    """
    gh = wired_batch(ref_sha_override="e" * 40)
    files = [str(_write(repo, "a.py", "a\n")), str(_write(repo, "b.py", "b\n"))]

    with pytest.raises(ptg.DeliveryUnverified) as exc:
        ptg.batch_push("pat", files, "msg", "o/r", "main")

    assert "ветка main" in str(exc.value)


def test_batch_push_survives_unreadable_shas_but_says_so(wired_batch, ptg, repo, capsys):
    """«Не измерено» на batch-пути тоже не блокирует и не молчит."""
    gh = wired_batch(blob_sha_override="abcdef", ref_sha_override="")
    files = [str(_write(repo, "a.py", "a\n")), str(_write(repo, "b.py", "b\n"))]

    res = ptg.batch_push("pat", files, "msg", "o/r", "main")

    assert res["ok"], "нечитаемая sha не повод рвать доставку набора"
    out = capsys.readouterr().out
    assert out.count("НЕ ИЗМЕРЕНО") >= 2, out


def test_verification_costs_zero_extra_requests_on_batch_path(wired_batch, ptg, repo):
    """ЦЕНА ИЗМЕРЕНА и на батче: ни одного дополнительного запроса."""
    gh = wired_batch()
    files = [str(_write(repo, f"f{i}.py", f"x={i}\n")) for i in range(4)]

    ptg.batch_push("pat", files, "msg", "o/r", "main")

    # Ровно шаги Git Data API: ref, commit, tree(base), 4 blob, tree, commit, ref.
    reads_after_write = [(m, p) for m, p in gh.calls
                         if m == "GET" and "/git/blobs" in p]
    assert reads_after_write == [], "перечитывания записанного быть не должно"
    assert len(gh.calls) == 10, (
        f"число обращений к API изменилось — сверка обязана быть бесплатной: "
        f"{gh.calls}")


# ═════════════════════════════════════════════════════════════════════════════
# 3. ОДНА реализация на оба CLI (близнец логики — уже дважды стоил инцидента)
# ═════════════════════════════════════════════════════════════════════════════
def test_batch_cli_reuses_the_same_verification(batch_cli):
    """`push_to_github_batch.py` не держит своей копии сверки.

    Сравнение идёт с КАНОНИЧЕСКИМ модулем, который загрузил сам CLI
    (`_root_push`), а не со второй загрузкой того же файла в фикстуре `ptg`:
    два `spec_from_file_location` одного файла дают разные объекты классов, и
    сравнение с ними ловило бы артефакт загрузчика, а не переиспользование.
    """
    root = batch_cli._root_push
    assert batch_cli.DeliveryUnverified is root.DeliveryUnverified
    assert batch_cli.verify_blob_delivery is root.verify_blob_delivery
    assert batch_cli.verify_sha_delivery is root.verify_sha_delivery


def test_batch_cli_source_has_no_second_copy_of_the_check():
    """Гейт против близнеца: сверка определяется РОВНО в одном файле."""
    defs = [p for p in (ROOT / "push_to_github_batch.py",
                        ROOT / "scripts" / "push_to_github.py")
            if "def verify_sha_delivery" in p.read_text(encoding="utf-8")]
    assert defs == [], (
        f"вторая копия сверки доставки: {defs}. Копия такой же логики — тот "
        f"механизм, которым цикл #37 оставил CI красным, а цикл #40 разослал "
        f"файлы в корень репо")


def test_fake_refuses_endpoints_it_does_not_model(ptg, repo, monkeypatch):
    """Герметичность здесь — измеренная, а не заявленная.

    Фейк ПАДАЕТ на любом эндпоинте, которого не знает. Значит, если пушер
    когда-нибудь добавит запрос (например тот самый второй GET после записи),
    тесты выше не «пройдут по-тихому» — они упадут на неизвестном вызове, и
    новая стоимость станет видна сразу.
    """
    gh = FakeGitData().bind(ptg)
    with pytest.raises(AssertionError, match="фейк не знает эндпоинт"):
        gh.api("pat", "GET", "/repos/o/r/contents/docs/a.md?ref=main")
