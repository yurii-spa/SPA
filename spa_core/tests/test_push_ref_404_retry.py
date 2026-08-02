"""
spa_core/tests/test_push_ref_404_retry.py

Гейт против рецидива: **ПЕРВЫЙ чекпойнт сессии не падает трейсбеком на ref'е,
который сам же только что создал**.

ЧТО ЛОВИМ (карточка `agent-checkpoint-tool-crashes-on-first-use`, найдено циклом
#81). `checkpoint_deliver.push_checkpoint` создаёт ветку `wip/<сессия>`
(`POST /git/refs`), а следом `batch_push` читает её базу
(`GET /git/ref/heads/<branch>`) — и получал **404** на ветке, созданной
мгновение назад: refs-API GitHub согласован в конечном счёте. `HTTPError` никто
не обрабатывал, процесс падал.

Цена дефекта ровно обратна назначению инструмента. `checkpoint_deliver`
существует, чтобы готовая-но-непроверенная работа пережила смерть сессии. Но
первый же его вызов в сессии завершался трейсбеком — то есть страховка не
срабатывала ровно там, где сессии и умирают: между «сделал» и «доставил»
(циклы #79 и #80 подряд, `main` простоял красным ~4 часа).

ГРАНИЦА ЧЕСТНОСТИ. Ретраится ТОЛЬКО 404 и ТОЛЬКО на чтении ref'а. Исчерпав
конечное число попыток, функция пробрасывает тот же `HTTPError`: «не смог
прочитать ref» не превращается в «ветки нет» и не даёт пушу поехать от неверной
базы (fail-CLOSED, инв. #2 — тот самый класс #29/#31/#35–#38/#40, где «не
измерено» сворачивалось в «всё хорошо»). Любой другой код (403/409/500) обязан
валить команду СРАЗУ, без ретраев, — недоступность API остаётся отказом.

СЕТЬ И ЧАСЫ НЕ ТРОГАЮТСЯ НИ ОДНИМ ТЕСТОМ: `_api` подменяется фейком, `sleep`
инъецируется параметром и только записывает задержки.

Запуск: python3 -m pytest spa_core/tests/test_push_ref_404_retry.py -v
"""
from __future__ import annotations

import importlib.util
import io
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def ptg():
    return _load("_test_ref404_ptg", "push_to_github.py")


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(
        "https://api.github.com/x", code, "err", {}, io.BytesIO(b"{}"))


class RefAPI:
    """Фейк GitHub для двух эндпоинтов `get_base_ref`. Считает КАЖДЫЙ вызов.

    `ref_codes` — очередь кодов ответа на `GET /git/ref/heads/...`: `None`
    означает «ответить успешно», число — бросить `HTTPError` с этим кодом.
    Очередь исчерпалась → дальше отвечаем успешно.
    """

    def __init__(self, ref_codes=()):
        self.ref_codes = list(ref_codes)
        self.calls: list[tuple[str, str]] = []

    def api(self, pat, method, path, payload=None):
        self.calls.append((method, path))
        if method == "GET" and "/git/ref/heads/" in path:
            code = self.ref_codes.pop(0) if self.ref_codes else None
            if code is not None:
                raise _http_error(code)
            return {"object": {"sha": "basecommit"}}
        if method == "GET" and "/git/commits/" in path:
            return {"tree": {"sha": "basetree"}}
        raise AssertionError(f"фейк не знает эндпоинт: {method} {path}")

    @property
    def ref_reads(self) -> int:
        return sum(1 for m, p in self.calls if m == "GET" and "/git/ref/heads/" in p)


@pytest.fixture()
def slept():
    """Инъецируемый `sleep`: только записывает задержки, никогда не ждёт."""
    return []


# ═════════════════════════════════════════════════════════════════════════════
# 1. Положительный контроль: видимый ref работает ровно как раньше
# ═════════════════════════════════════════════════════════════════════════════

def test_visible_ref_needs_no_retry_and_never_sleeps(ptg, monkeypatch, slept):
    """Существующая ветка: ОДНО чтение ref'а, ноль задержек, те же shas.

    Это контроль на то, что фикс аддитивен: счастливый путь не изменился —
    иначе «починка» тихо добавила бы задержку каждому пушу репозитория.
    """
    gh = RefAPI()
    monkeypatch.setattr(ptg, "_api", gh.api)
    assert ptg.get_base_ref("PAT", "o/r", "main", sleep=slept.append) == \
        ("basecommit", "basetree")
    assert gh.ref_reads == 1, "видимый ref не должен перечитываться"
    assert slept == [], "на счастливом пути задержек быть не должно"


# ═════════════════════════════════════════════════════════════════════════════
# 2. Сценарий цикла #81 дословно: 404 на первом чтении, 200 на втором
# ═════════════════════════════════════════════════════════════════════════════

def test_404_then_200_succeeds_without_traceback(ptg, monkeypatch, slept):
    """Ровно наблюдавшийся случай: свежесозданный ref ещё не виден.

    До фикса здесь летел `urllib.error.HTTPError: HTTP Error 404` — тот самый
    трейсбек из карточки.
    """
    gh = RefAPI(ref_codes=[404])
    monkeypatch.setattr(ptg, "_api", gh.api)
    assert ptg.get_base_ref("PAT", "o/r", "wip/cycle81", sleep=slept.append) == \
        ("basecommit", "basetree")
    assert gh.ref_reads == 2, "должен быть ровно один повтор"
    assert slept == [0.5], "первая задержка — по документированной лестнице"


def test_404_twice_then_200_still_succeeds(ptg, monkeypatch, slept):
    """Задержки растут по документированной лестнице, а не по случайной."""
    gh = RefAPI(ref_codes=[404, 404])
    monkeypatch.setattr(ptg, "_api", gh.api)
    assert ptg.get_base_ref("PAT", "o/r", "wip/c", sleep=slept.append)[0] == "basecommit"
    assert gh.ref_reads == 3
    assert slept == [0.5, 1.0]


# ═════════════════════════════════════════════════════════════════════════════
# 3. Fail-CLOSED: «не смог прочитать» НЕ равно «ветки нет»
# ═════════════════════════════════════════════════════════════════════════════

def test_persistent_404_raises_and_does_not_invent_a_base(ptg, monkeypatch, slept):
    """404 на ВСЕХ попытках → тот же `HTTPError` наружу, пуш не едет.

    Ровно тот класс, из-за которого этот репозиторий уже получал успокоительные
    вердикты: соблазн «404 значит ветки нет — создам/возьму main» отправил бы
    коммит от НЕВЕРНОЙ базы. Отказ обязан остаться отказом.
    """
    gh = RefAPI(ref_codes=[404] * 99)
    monkeypatch.setattr(ptg, "_api", gh.api)
    with pytest.raises(urllib.error.HTTPError) as ei:
        ptg.get_base_ref("PAT", "o/r", "wip/never", sleep=slept.append)
    assert ei.value.code == 404
    assert gh.ref_reads == ptg._REF_404_RETRIES + 1, "число попыток конечно"
    assert len(slept) == ptg._REF_404_RETRIES, "спим между попытками, не после последней"


def test_retry_budget_is_bounded(ptg):
    """Лестница задержек конечна и не пустая — бесконечный ретрай = зависший агент."""
    assert 1 <= ptg._REF_404_RETRIES <= 5
    assert len(ptg._REF_404_BACKOFF) >= 1
    assert sum(ptg._REF_404_BACKOFF) <= 10.0, "суммарное ожидание не должно съедать цикл"


# ═════════════════════════════════════════════════════════════════════════════
# 4. Недоступность API по-прежнему валит команду — БЕЗ ретраев
# ═════════════════════════════════════════════════════════════════════════════

@pytest.mark.parametrize("code", [401, 403, 409, 422, 500, 502, 503])
def test_non_404_raises_immediately_without_retry(ptg, monkeypatch, slept, code):
    """403/500/… — отказ СРАЗУ: ретрай тут маскировал бы отзыв PAT или аварию.

    Измеряем именно число обращений: «упало после ретраев» и «упало сразу» —
    разные вещи, и вторая обязана остаться.
    """
    gh = RefAPI(ref_codes=[code])
    monkeypatch.setattr(ptg, "_api", gh.api)
    with pytest.raises(urllib.error.HTTPError) as ei:
        ptg.get_base_ref("PAT", "o/r", "main", sleep=slept.append)
    assert ei.value.code == code
    assert gh.ref_reads == 1, f"HTTP {code} не должен ретраиться"
    assert slept == [], f"HTTP {code} не должен ничего ждать"


def test_network_failure_is_not_swallowed(ptg, monkeypatch, slept):
    """Обрыв сети (не HTTPError) пробрасывается как есть, без ретраев."""
    def boom(pat, method, path, payload=None):
        raise urllib.error.URLError("нет сети")
    monkeypatch.setattr(ptg, "_api", boom)
    with pytest.raises(urllib.error.URLError):
        ptg.get_base_ref("PAT", "o/r", "main", sleep=slept.append)
    assert slept == []


def test_error_on_the_commit_read_is_not_retried_as_a_ref_404(ptg, monkeypatch, slept):
    """404 на ЧТЕНИИ КОММИТА — не наш случай: ретраится только чтение ref'а."""
    class CommitBoom(RefAPI):
        def api(self, pat, method, path, payload=None):
            if method == "GET" and "/git/commits/" in path:
                self.calls.append((method, path))
                raise _http_error(404)
            return super().api(pat, method, path, payload)

    gh = CommitBoom()
    monkeypatch.setattr(ptg, "_api", gh.api)
    with pytest.raises(urllib.error.HTTPError):
        ptg.get_base_ref("PAT", "o/r", "main", sleep=slept.append)
    assert gh.ref_reads == 1
    assert slept == []


# ═════════════════════════════════════════════════════════════════════════════
# 5. Сквозь batch_push — путь, которым чекпойнт и падал
# ═════════════════════════════════════════════════════════════════════════════

class BatchGitHub(RefAPI):
    """RefAPI + минимум эндпоинтов, которых требует `batch_push`."""

    def __init__(self, ref_codes=()):
        super().__init__(ref_codes)
        self.commits: list[dict] = []
        self.ref_updates: list[str] = []
        self._n = 0

    def api(self, pat, method, path, payload=None):
        if method == "POST" and path.endswith("/git/blobs"):
            self.calls.append((method, path))
            self._n += 1
            return {"sha": f"b{self._n:038d}"}
        if method == "POST" and path.endswith("/git/trees"):
            self.calls.append((method, path))
            self._n += 1
            return {"sha": f"t{self._n:038d}"}
        if method == "POST" and path.endswith("/git/commits"):
            self.calls.append((method, path))
            self._n += 1
            sha = f"c{self._n:038d}"
            self.commits.append({"sha": sha, **(payload or {})})
            return {"sha": sha}
        if method == "PATCH" and "/git/refs/heads/" in path:
            self.calls.append((method, path))
            self.ref_updates.append(payload["sha"])
            return {"object": {"sha": payload["sha"]}}
        if method == "GET" and "/git/trees/" in path:
            self.calls.append((method, path))
            return {"tree": [], "truncated": False}
        return super().api(pat, method, path, payload)


@pytest.fixture()
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=r, check=True)
    return r


def test_first_checkpoint_of_a_session_survives_the_404(ptg, repo, monkeypatch):
    """Сквозной путь: ветка создана мгновение назад ⇒ первое чтение 404.

    До фикса `batch_push` падал здесь трейсбеком и коммит не создавался вовсе —
    то есть работа сессии оставалась без страховки ровно в момент, ради
    которого инструмент написан.
    """
    gh = BatchGitHub(ref_codes=[404])
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: None)
    monkeypatch.setattr(ptg.time, "sleep", lambda *_: None)   # часы не трогаем
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")

    res = ptg.batch_push("PAT", [str(repo / "a.py")], "CHECKPOINT (UNVERIFIED) cycle82",
                         "o/r", "wip/cycle82")

    assert res["ok"] is True
    assert len(gh.commits) == 1, "ровно один коммит, несмотря на 404 при чтении базы"
    assert gh.ref_updates == [gh.commits[0]["sha"]], "ветка сдвинута на созданный коммит"
    assert gh.ref_reads == 2, "одно 404-чтение + успешный повтор"


# ═════════════════════════════════════════════════════════════════════════════
# 6. Доказательство ПОВЕДЕНИЕМ, а не подписью (цикл #83)
#
# Секции 1-5 написаны циклом #82 и зовут `get_base_ref(..., sleep=...)` — кварг,
# которого на `origin/main` нет. Измерено при подборе осиротевшей работы: на
# чистом `origin/main` эти 15 тестов краснеют **все**, но 14 из них — с
# `TypeError: unexpected keyword argument 'sleep'` (13) и `AttributeError:
# _REF_404_RETRIES` (1). То есть краснота 14 тестов доказывает лишь то, что
# подпись новая; настоящий дефект воспроизводит РОВНО ОДИН тест.
#
# Это ровно тот класс, который репозиторий ловит с цикла #29: утверждение об
# измерении, которого не было, — здесь в виде «15 красных» вместо «1 красный».
# Ниже — тесты, которые зовут функцию БЕЗ нового кварга, поэтому исполнимы на
# обеих версиях кода. Часть из них КРАСНЫЕ на origin (настоящее поведение), а
# часть ЗЕЛЁНЫЕ на обеих (положительные контроли: фикс аддитивен и не
# ослабляет отказ). Без них у секций 1-5 нет ни одного положительного контроля.
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def no_clock(ptg, monkeypatch):
    """Записывает задержки, не ожидая: `sleep` НЕ передаётся кваргом.

    Патчится `time.sleep`, который зовёт сама функция по умолчанию, — значит
    тест исполним и на коде `origin/main`, где кварга `sleep` не существует.
    """
    delays: list[float] = []
    monkeypatch.setattr(ptg.time, "sleep", delays.append)
    return delays


def test_stale_ref_404_reproduces_the_defect_without_the_new_signature(
        ptg, monkeypatch, no_clock):
    """КРАСНЫЙ на origin ПОВЕДЕНЧЕСКИ: 404 → 200 без единого нового аргумента.

    На `origin/main` здесь летит `urllib.error.HTTPError: HTTP Error 404` —
    тот самый трейсбек из карточки, воспроизведённый вызовом, который выглядит
    ровно так же на обеих версиях кода. Именно этот тест (а не подпись)
    доказывает, что дефект был.
    """
    gh = RefAPI(ref_codes=[404])
    monkeypatch.setattr(ptg, "_api", gh.api)
    assert ptg.get_base_ref("PAT", "o/r", "wip/cycle83") == ("basecommit", "basetree")
    assert gh.ref_reads == 2
    assert no_clock == [0.5], "ждём между попытками — и только между ними"


def test_visible_ref_is_untouched_by_the_fix(ptg, monkeypatch, no_clock):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ (зелёный и на origin, и с фиксом).

    Счастливый путь обязан остаться байт-в-байт: одно чтение, те же shas, ноль
    ожидания. Иначе «починка» добавила бы задержку каждому пушу репозитория —
    а пушит здесь всё, включая дневной цикл и autopush.
    """
    gh = RefAPI()
    monkeypatch.setattr(ptg, "_api", gh.api)
    assert ptg.get_base_ref("PAT", "o/r", "main") == ("basecommit", "basetree")
    assert gh.ref_reads == 1
    assert no_clock == []


@pytest.mark.parametrize("code", [403, 500])
def test_api_outage_still_fails_immediately(ptg, monkeypatch, no_clock, code):
    """ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ (зелёный на обеих версиях).

    Отзыв PAT (403) и авария GitHub (500) обязаны валить команду СРАЗУ и без
    ожидания — ретрай здесь превратил бы «не измерено» в «подождём ещё».
    Пиннится именно ЧИСЛО обращений: «упало после ретраев» ≠ «упало сразу».
    """
    gh = RefAPI(ref_codes=[code])
    monkeypatch.setattr(ptg, "_api", gh.api)
    with pytest.raises(urllib.error.HTTPError) as ei:
        ptg.get_base_ref("PAT", "o/r", "main")
    assert ei.value.code == code
    assert gh.ref_reads == 1
    assert no_clock == []


def test_exhausted_404_budget_never_invents_a_base(ptg, monkeypatch, no_clock):
    """Fail-CLOSED без нового кварга: вечный 404 → отказ, а не выдуманная база.

    На origin — отказ с первой попытки, с фиксом — после конечного числа; в
    ОБОИХ случаях наружу летит `HTTPError` и НИ ОДНОГО чтения коммита не
    происходит. Пиннится главное: «не смог прочитать ref» никогда не
    сворачивается в «возьму какую-нибудь базу» (инв. #2).
    """
    gh = RefAPI(ref_codes=[404] * 99)
    monkeypatch.setattr(ptg, "_api", gh.api)
    with pytest.raises(urllib.error.HTTPError) as ei:
        ptg.get_base_ref("PAT", "o/r", "wip/never")
    assert ei.value.code == 404
    assert not [p for m, p in gh.calls if "/git/commits/" in p], \
        "база не читалась — значит и выдумана быть не могла"


# ═════════════════════════════════════════════════════════════════════════════
# 7. Граница фикса: PATCH ref'а СОЗНАТЕЛЬНО оставлен без ретрая
#
# Тот же довод «refs-API согласован в конечном счёте» формально применим и к
# шагу 6 `batch_push` (`PATCH /git/refs/heads/<branch>`), где 404 НЕ входит в
# обрабатываемый набор (409, 422) и улетел бы трейсбеком уже ПОСЛЕ создания
# blobs/tree/commit.
#
# Ретрай туда не добавлен, и причина измерима, а не вкусовая: `get_base_ref`
# идёт РАНЬШЕ и теперь сам добивается видимости ref'а, поэтому к моменту PATCH
# ветка уже доказанно читалась (между ними ещё несколько round-trip'ов).
# Наблюдений 404 на PATCH нет ни одного — чинить ненаблюдавшееся значило бы
# гадать. Тест ниже ПИННИТ текущее поведение: 404 на PATCH обязан оставаться
# отказом, чтобы будущая «починка» не проглотила его молча (тогда коммит
# существовал бы, а ветка на него не двигалась — потеря тише нынешней).
# ═════════════════════════════════════════════════════════════════════════════

def test_update_ref_404_is_not_swallowed(ptg, monkeypatch):
    """PATCH-404 — отказ (пин границы, зелёный на обеих версиях)."""
    def api(pat, method, path, payload=None):
        raise _http_error(404)
    monkeypatch.setattr(ptg, "_api", api)
    with pytest.raises(urllib.error.HTTPError) as ei:
        ptg.update_ref("PAT", "o/r", "wip/c", "deadbeef")
    assert ei.value.code == 404


def test_base_ref_is_read_before_the_ref_is_patched(ptg, repo, monkeypatch):
    """Измерение довода из комментария выше: чтение базы ПРЕДШЕСТВУЕТ PATCH.

    Если порядок когда-нибудь изменится, довод «к PATCH ветка уже доказанно
    видна» перестанет быть верным — и тест об этом скажет.
    """
    gh = BatchGitHub(ref_codes=[404])
    monkeypatch.setattr(ptg, "PROJECT_ROOT", repo)
    monkeypatch.setattr(ptg, "_api", gh.api)
    monkeypatch.setattr(ptg, "get_file_sha", lambda *a, **k: None)
    monkeypatch.setattr(ptg.time, "sleep", lambda *_: None)
    (repo / "a.py").write_text("x = 1\n", encoding="utf-8")

    ptg.batch_push("PAT", [str(repo / "a.py")], "msg", "o/r", "wip/cycle83")

    kinds = [f"{m} {p.split('/git/')[-1].split('/')[0]}" for m, p in gh.calls]
    assert kinds.index("PATCH refs") > max(
        i for i, k in enumerate(kinds) if k == "GET ref"), \
        "PATCH ветки обязан идти ПОСЛЕ успешного чтения ref'а"
