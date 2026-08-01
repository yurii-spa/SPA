"""
spa_core/tests/test_checkpoint_deliver.py

Тесты чекпойнт-доставки (`scripts/checkpoint_deliver.py`, карточка
`agent-verification-outlives-cycle-budget`).

ЧТО ПИННИТСЯ. Инструмент существует, чтобы готовая-но-НЕпроверенная работа
пережила смерть сессии, не став при этом доставкой. Поэтому здесь проверяются не
«функции вообще», а ровно те свойства, нарушение которых превратило бы страховку
в новую дыру:

  1. чекпойнт НИКОГДА не уезжает в `main` (он по определению не проверен);
  2. `landing/**` — ОТКАЗ, чтобы не появился второй маршрут в обход owner-gate
     (ADR-OWN-2026-07): Cloudflare Pages билдит сайт ВНЕ Actions и может собрать
     preview с не-main ветки;
  3. живой go-live трек не публикуется;
  4. «не измерено» остаётся «не измерено» и не сворачивается в «доставлено» —
     класс дефектов #29/#31/#35–#38/#40, из-за которого этот репозиторий уже
     получал успокоительные вердикты о проверках, которых не было;
  5. отказ происходит ДО PAT и до любого обращения к сети.

СЕТЬ НЕ ТРОГАЕТСЯ НИ ОДНИМ ТЕСТОМ: весь ввод-вывод инъецируется (`api=`,
`pusher=`), а тест `test_refusal_happens_before_pat_and_network` это пиннит явно.

Запуск: python3 -m pytest spa_core/tests/test_checkpoint_deliver.py -v
"""
from __future__ import annotations

import importlib.util
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
def cd():
    return _load("_test_checkpoint_deliver", "scripts/checkpoint_deliver.py")


def _http(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://x", code, "err", {}, None)


def _looks_like_sha(s: str) -> bool:
    """Настоящий Git Data API принимает по этому пути только полный sha."""
    return len(s) >= 7 and all(c in "0123456789abcdef" for c in s.lower())


class FakeAPI:
    """Инъецируемая замена сети. Пишет ЖУРНАЛ вызовов — по нему тесты и судят."""

    def __init__(self, responses=None, errors=None):
        self.responses = responses or {}
        self.errors = errors or {}
        self.calls = []

    def __call__(self, method, path, payload=None):
        self.calls.append((method, path, payload))
        # Фейк обязан ОТВЕРГАТЬ то, что отвергает настоящий API. `/git/commits/`
        # принимает только sha, не имя ветки — первая версия фейка отвечала и на
        # `/git/commits/main`, поэтому герметичный тест благословил вызов,
        # который на живом origin падал (нашёл живой прогон, а не сюита).
        if "/git/commits/" in path:
            sha = path.rsplit("/", 1)[-1]
            if not _looks_like_sha(sha):
                raise _http(422)
        key = (method, path)
        if key in self.errors:
            raise self.errors[key]
        if key in self.responses:
            return self.responses[key]
        raise AssertionError(f"неожиданный вызов сети: {method} {path}")


# ── 1. Имя ветки ─────────────────────────────────────────────────────────────

def test_branch_for_builds_wip_branch(cd):
    assert cd.branch_for("cycle65") == "wip/cycle65"


def test_branch_for_refuses_empty_session_instead_of_defaulting(cd):
    """Дефолтная ветка была бы худшим поведением: две сессии затирали бы друг друга."""
    with pytest.raises(cd.CheckpointRefused) as e:
        cd.branch_for("")
    assert "пуст" in str(e.value)


@pytest.mark.parametrize("bad", ["cycle 65", "cycle/65", "cycle;rm", "../evil", "a" * 65])
def test_branch_for_refuses_unsafe_session_ids(cd, bad):
    with pytest.raises(cd.CheckpointRefused):
        cd.branch_for(bad)


@pytest.mark.parametrize("protected", ["main", "master", "HEAD", "gh-pages", "trunk"])
def test_guard_branch_refuses_protected_branches(cd, protected):
    """ГЛАВНОЕ свойство: непроверенная работа не может уехать в main."""
    with pytest.raises(cd.CheckpointRefused) as e:
        cd.guard_branch(protected)
    assert protected in str(e.value)


def test_guard_branch_refuses_any_branch_outside_wip(cd):
    with pytest.raises(cd.CheckpointRefused):
        cd.guard_branch("feature/nice")


def test_guard_branch_accepts_wip(cd):
    assert cd.guard_branch("wip/cycle65") == "wip/cycle65"


# ── 2. Запрещённые файлы ─────────────────────────────────────────────────────

def test_landing_files_are_refused_owner_gate_has_no_second_route(cd):
    reason = cd.classify_path("landing/src/pages/index.astro")
    assert reason is not None
    assert "safe_site_push.py" in reason


def test_live_track_is_refused(cd):
    reason = cd.classify_path("data/equity_curve_daily.json")
    assert reason is not None
    assert "трек" in reason


def test_ordinary_code_path_is_allowed(cd):
    assert cd.classify_path("spa_core/risk/policy.py") is None
    assert cd.classify_path("scripts/checkpoint_deliver.py") is None


def test_other_data_files_are_not_blanket_refused(cd):
    """Отказ точечный: запрещён живой трек, а не весь `data/`."""
    assert cd.classify_path("data/adapter_status.json") is None


def test_guard_files_reports_every_reason_not_just_the_first(cd):
    """Одна причина за раз означала бы чинить их по кругу."""
    with pytest.raises(cd.CheckpointRefused) as e:
        cd.guard_files(["landing/a.astro", "data/equity_curve_daily.json", "ok.py"])
    msg = str(e.value)
    assert "landing/a.astro" in msg and "data/equity_curve_daily.json" in msg


def test_guard_files_refuses_empty_set(cd):
    with pytest.raises(cd.CheckpointRefused):
        cd.guard_files([])


def test_guard_files_passes_clean_set(cd):
    assert cd.guard_files(["a/b.py"]) == ["a/b.py"]


# ── 3. Создание ссылки ───────────────────────────────────────────────────────

def test_ensure_ref_reports_existed_and_creates_nothing(cd):
    api = FakeAPI({("GET", "/repos/r/git/ref/heads/wip/c65"): {"object": {"sha": "s"}}})
    assert cd.ensure_ref(api, "r", "wip/c65", "base") == "existed"
    assert all(m != "POST" for m, _, _ in api.calls)


def test_ensure_ref_creates_branch_from_base_when_absent(cd):
    api = FakeAPI(
        responses={("POST", "/repos/r/git/refs"): {"ok": True}},
        errors={("GET", "/repos/r/git/ref/heads/wip/c65"): _http(404)})
    assert cd.ensure_ref(api, "r", "wip/c65", "base123") == "created"
    post = [c for c in api.calls if c[0] == "POST"][0]
    assert post[2] == {"ref": "refs/heads/wip/c65", "sha": "base123"}


def test_ensure_ref_does_not_read_a_server_error_as_branch_absent(cd):
    """«Не смог прочитать» ≠ «не существует»: иначе сбой создаёт ветку от неверной базы."""
    api = FakeAPI(errors={("GET", "/repos/r/git/ref/heads/wip/c65"): _http(500)})
    with pytest.raises(urllib.error.HTTPError):
        cd.ensure_ref(api, "r", "wip/c65", "base")
    assert all(m != "POST" for m, _, _ in api.calls)


def test_ensure_ref_refuses_protected_branch_before_touching_network(cd):
    api = FakeAPI()
    with pytest.raises(cd.CheckpointRefused):
        cd.ensure_ref(api, "r", "main", "base")
    assert api.calls == []


# ── 4. Сообщение коммита ─────────────────────────────────────────────────────

def test_message_marks_checkpoint_first_so_git_log_oneline_shows_it(cd):
    msg = cd.checkpoint_message("cycle65", "полсотни тестов")
    assert msg.startswith(cd.CHECKPOINT_MARK)
    assert "UNVERIFIED" in msg.split("\n")[0]


def test_message_without_note_still_marked(cd):
    assert cd.checkpoint_message("cycle65").startswith(cd.CHECKPOINT_MARK)


# ── 5. Вердикт доставки — три состояния ──────────────────────────────────────

def test_unreadable_trees_are_unmeasured_never_delivered(cd):
    for a, b in ((None, {}), ({}, None), (None, None)):
        verdict, _ = cd.delivery_verdict(a, b)
        assert verdict == cd.UNMEASURED


def test_empty_checkpoint_is_unmeasured_not_delivered(cd):
    """Пустой список изменений — это «не увидел», а не «всё совпало»."""
    verdict, _ = cd.delivery_verdict({}, {"a": "1"})
    assert verdict == cd.UNMEASURED


def test_file_absent_on_main_is_undelivered(cd):
    verdict, why = cd.delivery_verdict({"a.py": "1"}, {"b.py": "2"})
    assert verdict == cd.UNDELIVERED
    assert "a.py" in why


def test_file_differing_from_main_is_undelivered(cd):
    verdict, why = cd.delivery_verdict({"a.py": "1"}, {"a.py": "2"})
    assert verdict == cd.UNDELIVERED
    assert "a.py" in why


def test_all_blobs_identical_is_delivered(cd):
    verdict, _ = cd.delivery_verdict({"a.py": "1", "b.py": "2"},
                                     {"a.py": "1", "b.py": "2", "c.py": "3"})
    assert verdict == cd.DELIVERED


_C_SHA = "0123456789abcdef0123456789abcdef01234567"


def test_truncated_tree_is_unmeasured_not_a_partial_answer(cd):
    api = FakeAPI({
        ("GET", f"/repos/r/git/commits/{_C_SHA}"): {"tree": {"sha": "t1"}},
        ("GET", "/repos/r/git/trees/t1?recursive=1"): {"truncated": True, "tree": []},
    })
    # sha должен быть НАСТОЯЩИМ: с плейсхолдером «sha1» строгий фейк отвергал
    # вызов, и тест зеленел не из-за обрезанного дерева, а из-за 422.
    assert cd._tree_blobs(api, "r", _C_SHA) is None
    assert any("trees/t1" in p for _, p, _ in api.calls)


def test_tree_blobs_reads_blobs_only(cd):
    api = FakeAPI({
        ("GET", f"/repos/r/git/commits/{_C_SHA}"): {"tree": {"sha": "t1"}},
        ("GET", "/repos/r/git/trees/t1?recursive=1"): {
            "truncated": False,
            "tree": [{"path": "a.py", "sha": "1", "type": "blob"},
                     {"path": "d", "sha": "9", "type": "tree"}]},
    })
    assert cd._tree_blobs(api, "r", _C_SHA) == {"a.py": "1"}


# ── 6. list ──────────────────────────────────────────────────────────────────

_MAIN_SHA = "abc1234def5678901234567890abcdef12345678"


def _list_api(files, main_tree, truncated=False):
    return FakeAPI({
        ("GET", "/repos/r/git/matching-refs/heads/wip/"): [
            {"ref": "refs/heads/wip/cycle64", "object": {"sha": "headsha1"}}],
        ("GET", "/repos/r/compare/main...wip/cycle64"): {"files": files},
        # `main` СНАЧАЛА разрешается в sha — ровно как на живом origin.
        ("GET", "/repos/r/git/ref/heads/main"): {"object": {"sha": _MAIN_SHA}},
        ("GET", f"/repos/r/git/commits/{_MAIN_SHA}"): {"tree": {"sha": "tmain"}},
        ("GET", "/repos/r/git/trees/tmain?recursive=1"): {
            "truncated": truncated,
            "tree": [{"path": p, "sha": s, "type": "blob"}
                     for p, s in main_tree.items()]},
    })


def test_main_is_resolved_to_a_sha_before_reading_its_tree(cd):
    """Регрессия живого прогона: имя ветки в `/git/commits/` API отвергает."""
    api = _list_api([{"filename": "a.py", "sha": "same", "status": "modified"}],
                    {"a.py": "same"})
    assert cd.list_checkpoints(api, "r")[0]["verdict"] == cd.DELIVERED
    assert ("GET", "/repos/r/git/ref/heads/main", None) in api.calls


def test_unresolvable_main_is_unmeasured_not_delivered(cd):
    api = _list_api([{"filename": "a.py", "sha": "same", "status": "modified"}],
                    {"a.py": "same"})
    api.errors[("GET", "/repos/r/git/ref/heads/main")] = _http(500)
    assert cd.list_checkpoints(api, "r")[0]["verdict"] == cd.UNMEASURED


def test_list_reports_undelivered_checkpoint(cd):
    api = _list_api([{"filename": "a.py", "sha": "new", "status": "modified"}],
                    {"a.py": "old"})
    rows = cd.list_checkpoints(api, "r")
    assert len(rows) == 1
    assert rows[0]["verdict"] == cd.UNDELIVERED
    assert rows[0]["session"] == "cycle64"
    assert rows[0]["files"] == ["a.py"]


def test_list_reports_delivered_checkpoint(cd):
    api = _list_api([{"filename": "a.py", "sha": "same", "status": "modified"}],
                    {"a.py": "same"})
    assert cd.list_checkpoints(api, "r")[0]["verdict"] == cd.DELIVERED


def test_list_is_unmeasured_when_compare_fails(cd):
    api = FakeAPI(
        responses={("GET", "/repos/r/git/matching-refs/heads/wip/"): [
            {"ref": "refs/heads/wip/cycle64", "object": {"sha": "h"}}]},
        errors={("GET", "/repos/r/compare/main...wip/cycle64"): _http(500)})
    assert cd.list_checkpoints(api, "r")[0]["verdict"] == cd.UNMEASURED


def test_list_ignores_deleted_files_in_compare(cd):
    api = _list_api([{"filename": "gone.py", "sha": "x", "status": "removed"},
                     {"filename": "a.py", "sha": "same", "status": "modified"}],
                    {"a.py": "same"})
    rows = cd.list_checkpoints(api, "r")
    assert rows[0]["files"] == ["a.py"]


def test_list_is_empty_when_no_checkpoint_branches(cd):
    api = FakeAPI({("GET", "/repos/r/git/matching-refs/heads/wip/"): []})
    assert cd.list_checkpoints(api, "r") == []


# ── 7. push — куда именно уезжает ────────────────────────────────────────────

class FakePusher:
    REPO = "r"

    def __init__(self):
        self.batch_calls = []
        self.pat_reads = 0

    def resolve_files(self, files):
        # Верный фейк отдаёт РЕПО-ОТНОСИТЕЛЬНЫЙ путь, как настоящий
        # `push_to_github.resolve_files` (`/repo/landing/x` → `landing/x`).
        # Первая версия фейка резала только ведущий «/» и оставляла «repo/…» —
        # тогда `landing/**` не совпадал ни с одним правилом, и три теста
        # покраснели. Красили они ФЕЙК, а не прод: подмена пути маскировала бы
        # ровно ту проверку, ради которой написаны.
        return [(str(f).replace("/repo/", "", 1).lstrip("/"), f) for f in files]

    def get_pat(self):
        self.pat_reads += 1
        return "PAT"

    def get_base_ref(self, pat, repo, branch):
        return ("basecommit", "basetree")

    def _api(self, pat, method, path, payload=None):
        raise AssertionError("живая сеть в тесте")

    def batch_push(self, pat, files, message, repo, branch, **kw):
        self.batch_calls.append({"branch": branch, "message": message,
                                 "files": files, "repo": repo})
        return {"ok": True, "commit": "c0ffee", "count": len(files)}


def test_push_lands_on_wip_branch_never_on_main(cd):
    pusher = FakePusher()
    api = FakeAPI({("GET", "/repos/r/git/ref/heads/wip/cycle65"): {"object": {"sha": "s"}}})
    r = cd.checkpoint_push(["/repo/a.py"], "cycle65", pat="PAT", api=api, pusher=pusher)
    assert r["branch"] == "wip/cycle65"
    assert pusher.batch_calls[0]["branch"] == "wip/cycle65"
    assert pusher.batch_calls[0]["branch"] not in cd.PROTECTED_BRANCHES


def test_push_commit_message_is_marked_unverified(cd):
    pusher = FakePusher()
    api = FakeAPI({("GET", "/repos/r/git/ref/heads/wip/cycle65"): {"object": {"sha": "s"}}})
    cd.checkpoint_push(["/repo/a.py"], "cycle65", note="wip", pat="PAT",
                       api=api, pusher=pusher)
    assert pusher.batch_calls[0]["message"].startswith(cd.CHECKPOINT_MARK)


def test_push_creates_the_branch_from_main_when_missing(cd):
    pusher = FakePusher()
    api = FakeAPI(
        responses={("POST", "/repos/r/git/refs"): {}},
        errors={("GET", "/repos/r/git/ref/heads/wip/cycle65"): _http(404)})
    r = cd.checkpoint_push(["/repo/a.py"], "cycle65", pat="PAT", api=api, pusher=pusher)
    assert r["ref"] == "created"


def test_push_refuses_site_files(cd):
    pusher = FakePusher()
    with pytest.raises(cd.CheckpointRefused) as e:
        cd.checkpoint_push(["/repo/landing/src/pages/index.astro"], "cycle65",
                           pat="PAT", api=FakeAPI(), pusher=pusher)
    assert "safe_site_push.py" in str(e.value)
    assert pusher.batch_calls == []


def test_push_refuses_live_track(cd):
    pusher = FakePusher()
    with pytest.raises(cd.CheckpointRefused):
        cd.checkpoint_push(["/repo/data/equity_curve_daily.json"], "cycle65",
                           pat="PAT", api=FakeAPI(), pusher=pusher)
    assert pusher.batch_calls == []


def test_refusal_happens_before_pat_and_network(cd):
    """Отказ обязан стоять до PAT и до сети — иначе он проверяет не то."""
    pusher = FakePusher()
    api = FakeAPI()          # любой вызов = AssertionError
    with pytest.raises(cd.CheckpointRefused):
        cd.checkpoint_push(["/repo/landing/x.astro"], "cycle65", api=api, pusher=pusher)
    assert pusher.pat_reads == 0
    assert api.calls == []


def test_dry_run_touches_neither_network_nor_pusher(cd):
    pusher = FakePusher()
    r = cd.checkpoint_push(["/repo/a.py"], "cycle65", dry_run=True, pusher=pusher)
    assert r["dry_run"] is True and pusher.batch_calls == [] and pusher.pat_reads == 0


# ── 8. drop ──────────────────────────────────────────────────────────────────

def test_drop_refuses_undelivered_checkpoint(cd):
    api = _list_api([{"filename": "a.py", "sha": "new", "status": "modified"}],
                    {"a.py": "old"})
    with pytest.raises(cd.CheckpointRefused):
        cd.drop_checkpoint(api, "r", "wip/cycle64")
    assert all(m != "DELETE" for m, _, _ in api.calls)


def test_drop_refuses_unmeasured_checkpoint(cd):
    """Нельзя уничтожать работу, которую не смогли прочитать."""
    api = FakeAPI(
        responses={("GET", "/repos/r/git/matching-refs/heads/wip/"): [
            {"ref": "refs/heads/wip/cycle64", "object": {"sha": "h"}}]},
        errors={("GET", "/repos/r/compare/main...wip/cycle64"): _http(500)})
    with pytest.raises(cd.CheckpointRefused):
        cd.drop_checkpoint(api, "r", "wip/cycle64")
    assert all(m != "DELETE" for m, _, _ in api.calls)


def test_drop_removes_delivered_checkpoint(cd):
    api = _list_api([{"filename": "a.py", "sha": "same", "status": "modified"}],
                    {"a.py": "same"})
    api.responses[("DELETE", "/repos/r/git/refs/heads/wip/cycle64")] = {}
    r = cd.drop_checkpoint(api, "r", "wip/cycle64")
    assert r["ok"] and any(m == "DELETE" for m, _, _ in api.calls)


def test_drop_force_removes_undelivered_but_marks_it(cd):
    api = _list_api([{"filename": "a.py", "sha": "new", "status": "modified"}],
                    {"a.py": "old"})
    api.responses[("DELETE", "/repos/r/git/refs/heads/wip/cycle64")] = {}
    r = cd.drop_checkpoint(api, "r", "wip/cycle64", force=True)
    assert r["forced"] is True


def test_drop_refuses_unknown_branch(cd):
    api = FakeAPI({("GET", "/repos/r/git/matching-refs/heads/wip/"): []})
    with pytest.raises(cd.CheckpointRefused):
        cd.drop_checkpoint(api, "r", "wip/nope")


def test_drop_refuses_protected_branch_outright(cd):
    api = FakeAPI()
    with pytest.raises(cd.CheckpointRefused):
        cd.drop_checkpoint(api, "r", "main")
    assert api.calls == []


# ── 9. Свойства модуля целиком ───────────────────────────────────────────────

def test_module_is_stdlib_only(cd):
    """Инвариант #4: только stdlib в рантайме."""
    src = (ROOT / "scripts" / "checkpoint_deliver.py").read_text(encoding="utf-8")
    third_party = ("requests", "yaml", "numpy", "pandas", "httpx", "aiohttp")
    for name in third_party:
        assert f"import {name}" not in src


def test_checkpoint_is_never_advertised_as_delivery(cd):
    """Чекпойнт не должен читаться как проверенная доставка."""
    src = (ROOT / "scripts" / "checkpoint_deliver.py").read_text(encoding="utf-8")
    assert "ЭТО НЕ ДОСТАВКА" in src
    assert cd.CHECKPOINT_MARK == "CHECKPOINT (UNVERIFIED)"


def test_main_branch_appears_only_as_a_base_or_a_refusal(cd):
    """Нигде в модуле `main` не может оказаться ЦЕЛЬЮ пуша."""
    assert "main" in cd.PROTECTED_BRANCHES
