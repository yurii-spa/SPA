"""Один отчёт — один sha; снимок не выдаёт себя за сервер (решение ARB 22.10, ADR-361/362).

# LLM_FORBIDDEN

Сцены — одноразовые git-репозитории (`Scene` из `test_server_ref_pin`: bare-«сервер»,
рабочая копия с настоящим удалённым, второй писатель). Сеть наружу не используется.
Шпион — обёртка над ``server_ref._git``: ЕДИНСТВЕННОЙ дверью, через которую закрепитель
спрашивает сервер, поэтому счёт ``ls-remote`` — это счёт вопросов к серверу.

Три оси, и у каждой контроль в обе стороны:

* **стоимость** — число ``ls-remote`` на ОДИН отчёт (проход ``audit()``, сводка §49,
  одна родословная карточки, сборка Director OS) — 1 (или 0 для витрины зеркала), а
  тело того же отчёта БЕЗ области даёт 1+N (положительный контроль: число меряет
  область, а не форму сцены);
* **согласованность** — сервер сдвигается ПОСЛЕ первого вопроса: все элементы отчёта
  судятся одним sha (вердикт второй карточки не меняется), а без области — меняется;
* **род значения** — кэш/снимок читаются ЯВНО (``source`` и возраст названы), при
  отрезанной сети текущий-серверный читатель отказывает, а снимок-читатель (бэкап,
  витрина зеркала) работает и сервер не спрашивает вовсе.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from spa_core.tests.test_server_ref_pin import TRACKER, Scene, _git
from spa_core.utils import server_ref as SR


class Spy:
    """Считает вопросы к серверу; по желанию двигает сервер после N-го вопроса."""

    def __init__(self, monkeypatch, after_first=None):
        self.ls_remote = 0
        self.fetch = 0
        self._after_first = after_first
        real = SR._git

        def spy(repo, args, timeout):
            got = real(repo, args, timeout)
            if args and args[0] == "ls-remote":
                self.ls_remote += 1
                if self.ls_remote == 1 and self._after_first is not None:
                    self._after_first()
            if args and args[0] == "fetch":
                self.fetch += 1
            return got

        monkeypatch.setattr(SR, "_git", spy)


# ───────────────────── область «один отчёт — один sha» ─────────────────────

def test_scope_answers_the_same_question_once_including_a_refusal(tmp_path, monkeypatch):
    sc = Scene(tmp_path, {"a.txt": "v1\n"})
    spy = Spy(monkeypatch)
    with SR.one_pin_per_report():
        a = SR.pin_server_ref(str(sc.work), "origin/main")
        b = SR.pin_server_ref(str(sc.work), "refs/remotes/origin/main")
    assert a.sha == b.sha and spy.ls_remote == 1
    sc.cut_network()
    spy.ls_remote = 0
    with SR.one_pin_per_report():
        refusals = [SR.pin_server_ref(str(sc.work), "origin/main") for _ in range(3)]
    assert all(not p.ok for p in refusals) and spy.ls_remote == 1, \
        "отказ сервера обязан запоминаться: иначе таймаут на каждый элемент"
    spy.ls_remote = 0
    for _ in range(2):
        SR.pin_server_ref(str(sc.work), "origin/main")
    assert spy.ls_remote == 2, "вне области каждый вопрос идёт к серверу"


# ───────────────────── audit(): проход по карточкам ─────────────────────

ORDER_A, ORDER_B = "inbox-order-a", "inbox-order-b"
CLEAN = "---\nstatus: in-progress\n---\nbody\n"
DECLARES = "---\nstatus: in-progress\nacceptance_probe: some_probe\n---\nbody\n"
PROBE = "no_single_criterion_probe_on_a_multi_criterion_order"


def _audit_scene(tmp_path):
    """Два открытых карточки-задания, у каждой проба про СВОЙ приказ; приказы — только
    на сервере (локальных копий нет), и оба чисты."""
    sc = Scene(tmp_path, {f"{TRACKER}/{ORDER_A}.md": CLEAN, f"{TRACKER}/{ORDER_B}.md": CLEAN})
    tracker = sc.work / TRACKER
    for o in (ORDER_A, ORDER_B):
        (tracker / f"{o}.md").unlink()
    for key, order in (("inbox-x", ORDER_A), ("inbox-y", ORDER_B)):
        (tracker / f"{key}.md").write_text(
            f"---\nstatus: in-progress\nacceptance_probe: {PROBE}:{order}\n---\nbody\n",
            encoding="utf-8")
    return sc, tracker


def _verdicts(rep):
    return {r["card"]: r["verdict"] for r in rep["rows"]}


def test_audit_asks_the_server_once_per_pass_and_the_unscoped_body_asks_per_card(
        tmp_path, monkeypatch):
    from spa_core.monitoring import card_acceptance as ca
    sc, tracker = _audit_scene(tmp_path)
    spy = Spy(monkeypatch)
    rep = ca.audit(str(tracker))
    assert _verdicts(rep) == {"inbox-x": ca.SATISFIED, "inbox-y": ca.SATISFIED}, rep["rows"]
    assert spy.ls_remote == 1, f"проход audit спросил сервер {spy.ls_remote} раз"
    spy.ls_remote = 0
    ca._audit_in_one_pin(str(tracker))
    assert spy.ls_remote == 3, "контроль: тело прохода без области — 1 + по карточке"


def test_audit_judges_every_card_by_one_sha_when_the_server_moves_mid_pass(
        tmp_path, monkeypatch):
    from spa_core.monitoring import card_acceptance as ca
    sc, tracker = _audit_scene(tmp_path)
    Spy(monkeypatch, after_first=lambda: sc.advance(
        f"{TRACKER}/{ORDER_B}.md", DECLARES, "order B declares a probe mid-pass"))
    rep = ca.audit(str(tracker))
    assert _verdicts(rep)["inbox-y"] == ca.SATISFIED, \
        "сервер сдвинулся посреди прохода — вторая карточка судится тем же sha"


def test_the_unscoped_pass_is_torn_when_the_server_moves(tmp_path, monkeypatch):
    """Положительный контроль соседнего теста: без области тот же сдвиг МЕНЯЕТ вердикт."""
    from spa_core.monitoring import card_acceptance as ca
    sc, tracker = _audit_scene(tmp_path)
    Spy(monkeypatch, after_first=lambda: sc.advance(
        f"{TRACKER}/{ORDER_B}.md", DECLARES, "order B declares a probe mid-pass"))
    rep = ca._audit_in_one_pin(str(tracker))
    assert _verdicts(rep)["inbox-y"] == ca.NOT_SATISFIED


def test_audit_without_the_network_waits_once_not_per_card(tmp_path, monkeypatch):
    from spa_core.monitoring import card_acceptance as ca
    sc, tracker = _audit_scene(tmp_path)
    sc.cut_network()
    spy = Spy(monkeypatch)
    rep = ca.audit(str(tracker))
    assert rep["origin"]["state"] == "unmeasured"
    assert set(_verdicts(rep).values()) == {ca.UNMEASURED}
    assert spy.ls_remote == 1


# ───────────────────── сводка §49 ─────────────────────

S49 = ("---\ntitle: \"TASK\"\nstatus: in-progress\n---\n\n## Задание\n\nпреамбула\n\n\n⸻\n\n\n"
       "49. Acceptance criteria\nРабота считается выполненной только когда доказано следующее.\n"
       "Architecture\nописание.\nEconomics\nописание.\nNo regression\nописание.\n\n\n⸻\n\n\n"
       "50. Definition of Done\n")


def test_rollup_asks_the_server_once_per_summary(tmp_path, monkeypatch):
    import cio_acceptance_rollup as rollup
    sc = Scene(tmp_path, {rollup.CARD_REL: S49})
    monkeypatch.setattr(rollup, "probes_by_s49_criterion",
                        lambda: {c: [f"p_{i}"] for i, c in
                                 enumerate(("Architecture", "Economics", "No regression"))})
    seen = []

    def runner(spec, **_kw):
        pin = SR.pin_server_ref(str(sc.work), "origin/main")
        seen.append(pin.sha)
        return rollup.UNMEASURED, pin.describe()

    spy = Spy(monkeypatch)
    rollup.measure(str(sc.work), probe_runner=runner)
    assert spy.ls_remote == 1 and len(set(seen)) == 1 and len(seen) == 3, (spy.ls_remote, seen)
    spy.ls_remote = 0
    rollup._measure_in_one_pin(str(sc.work), probe_runner=runner)
    assert spy.ls_remote == 4, "контроль: без области — население + по критерию"


# ───────────────────── родословная карточки и release_of ─────────────────────

def _lineage_scene(tmp_path):
    from spa_core.owner_queue import queue as Q    # тот же создатель карточек, что в сценах build_loop
    sc = Scene(tmp_path, {"x.txt": "x\n"})
    tdir = tmp_path / "tracker"
    tdir.mkdir()
    slug = Q.create_card("agent-task", "lineage probe", "b", status="in-progress", source="s",
                         tracker_dir=tdir).stem
    sc.advance("y.txt", "y\n", f"fix: {slug} (ADR-900)")
    _git(sc.work, "fetch", "-q", "origin")
    return sc, tdir, slug


def test_lineage_asks_the_server_once_and_reads_commits_by_that_sha(tmp_path, monkeypatch):
    from spa_core.studio_os import build_loop as bl
    sc, tdir, slug = _lineage_scene(tmp_path)
    # кэш НАРИСОВАН назад: по имени ссылки коммита карточки не видно
    _git(sc.work, "update-ref", "refs/remotes/origin/main", sc.base)
    spy = Spy(monkeypatch)
    x = bl.lineage(slug, tdir=tdir, root=sc.work, data_dir=tmp_path, memory=False)
    assert x["stages"]["ARTIFACT"]["state"] == "DONE", x["stages"]["ARTIFACT"]
    assert x["stages"]["RELEASE"]["evidence"]["on_origin_main"] is True
    assert spy.ls_remote == 1, "одна родословная — один вопрос к серверу"


def test_lineage_without_the_server_is_unknown_not_missing(tmp_path, monkeypatch):
    from spa_core.studio_os import build_loop as bl
    sc, tdir, slug = _lineage_scene(tmp_path)
    sc.cut_network()
    x = bl.lineage(slug, tdir=tdir, root=sc.work, data_dir=tmp_path, memory=False)
    assert x["stages"]["ARTIFACT"]["state"] == "UNKNOWN"
    assert x["stages"]["RELEASE"]["state"] == "UNKNOWN"
    assert "НЕ УСТАНОВЛЕН" in x["stages"]["ARTIFACT"]["evidence"]


# ───────────────────── Director OS: витрина зеркала ─────────────────────

def test_mirror_feed_reads_the_fetch_head_snapshot_without_the_network(tmp_path, monkeypatch):
    """Предмет ленты — «что видит зеркало»: читается FETCH_HEAD последнего fetch зеркала
    (с его возрастом), сервер НЕ спрашивается, а нарисованный кэш ответом не является."""
    from spa_core.studio_os import mission_control as mc
    sc = Scene(tmp_path, {"a.txt": "v1\n"})
    seen = sc.advance("a.txt", "v2\n", "feat: the mirror saw this")
    _git(sc.work, "fetch", "-q", "origin")                      # зеркало обновилось
    _git(sc.work, "update-ref", "refs/remotes/origin/main", sc.base)   # кэш сдвинут кем-то назад
    sc.advance("a.txt", "v3\n", "feat: after the mirror's fetch")      # сервер ушёл дальше
    sc.cut_network()
    spy = Spy(monkeypatch)
    inp = mc.MCInputs(repo=sc.work, mirror=sc.work, measure_host=True)
    base = mc._mirror_base(inp)
    assert base.source == "snapshot" and base.sha == seen and base.observed_at, base
    assert "СНИМОК" in base.describe() and "не ответ сервера" in base.describe()
    feed = mc._git_feed(inp, base=base)
    assert [c["full"] for c in feed][:1] == [seen], feed
    assert spy.ls_remote == 0 and spy.fetch == 0, "витрина зеркала ходила в сеть"


def test_mirror_snapshot_without_a_main_line_is_not_measured(tmp_path):
    sc = Scene(tmp_path, {"a.txt": "v1\n"})
    _git(sc.work, "fetch", "-q", "origin")
    fh = sc.work / ".git" / "FETCH_HEAD"
    fh.write_text("".join(ln.replace("branch 'main'", "branch 'other'") + "\n"
                          for ln in fh.read_text().splitlines()), encoding="utf-8")
    snap = SR.fetch_head_snapshot(str(sc.work), "main")
    assert snap.sha is None and "нет строки ветки" in snap.reason


# ───────────────────── перепись «две сессии на одном предмете» ─────────────────────

def test_census_base_is_the_server_value_and_refuses_without_it(tmp_path):
    from spa_core.monitoring import duplicate_subject_census as dsc
    sc = Scene(tmp_path, {"scripts/a.py": "x\n"})
    sc.advance("scripts/delivered_after_the_cache.py", "y\n", "delivered after the last fetch")
    sc.hide_from_cache()
    assert "scripts/delivered_after_the_cache.py" not in _git(
        sc.work, "ls-tree", "-r", "--name-only", "origin/main"), "предпосылка: кэш отстал"
    base = dsc.read_base_tree(sc.work, "origin/main")
    assert base["measured"] and "scripts/delivered_after_the_cache.py" in base["paths"], base
    assert base["ref_source"] == "server"
    sc.cut_network()
    base = dsc.read_base_tree(sc.work, "origin/main")
    assert base["measured"] is False and "не ответил" in base["reason"], base


# ───────────────────── сироты доставки: кэш ПО ЗАМЫСЛУ, но явно ─────────────────────

def test_orphans_name_the_cache_when_the_server_is_unreachable(tmp_path):
    from spa_core.monitoring import card_delivery as cd
    sc = Scene(tmp_path, {f"{TRACKER}/inbox-base.md": CLEAN})
    (sc.work / TRACKER / "inbox-orphan.md").write_text(CLEAN, encoding="utf-8")
    sc.cut_network()
    r = cd.orphan_candidates(str(sc.work), ref="origin/main", fetch=True)
    assert r["status"] == cd.ORPHAN_MEASURED and r["ref_fresh"] is False
    assert r["ref_source"] == "cache" and "КЭШ" in r["ref_pin"]
    assert r["candidates"] == [os.path.join(cd.TRACKER_REL, "inbox-orphan.md")]


# ───────────────────── бэкап: исключение по снимку, без сети и без записи ─────────────────────

def test_shadow_bundle_excludes_by_the_named_snapshot_offline_and_read_only(tmp_path, monkeypatch):
    import memory_backup as mb
    sc = Scene(tmp_path, {"a.txt": "v1\n"})
    _git(sc.work, "checkout", "-q", "-b", mb.SHADOW_BRANCH)
    (sc.work / "local.txt").write_text("only here\n", encoding="utf-8")
    _git(sc.work, "add", "local.txt")
    _git(sc.work, "commit", "-q", "-m", "local-only")
    local_only = _git(sc.work, "rev-parse", "HEAD")
    sc.advance("a.txt", "v2\n", "server moved; this clone never fetched it")
    sc.cut_network()
    refs_before = _git(sc.work, "for-each-ref")
    spy = Spy(monkeypatch)
    store = tmp_path / "store"
    store.mkdir()
    res = mb.bundle_shadow_branch(sc.work, store)
    assert res["ok"], res
    assert "КЭШ" in res["exclusion_base"] and sc.base[:12] in res["exclusion_base"], res
    assert spy.ls_remote == 0 and spy.fetch == 0
    assert _git(sc.work, "for-each-ref") == refs_before, "бэкап писал в источник"
    heads = _git(sc.work, "bundle", "list-heads", str(store / Path(res["bundle"]).name))
    assert local_only in heads


def test_shadow_bundle_without_a_snapshot_fails_named(tmp_path):
    import memory_backup as mb
    repo = tmp_path / "r"
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    (repo / "a").write_text("a", encoding="utf-8")
    _git(repo, "add", "a")
    _git(repo, "commit", "-q", "-m", "a")
    store = tmp_path / "store"
    store.mkdir()
    res = mb.bundle_shadow_branch(repo, store)
    assert res["ok"] is False and "не разрешается" in res["error"], res


@pytest.fixture(autouse=True)
def _scripts_on_path(monkeypatch):
    root = Path(__file__).resolve().parents[2]
    monkeypatch.syspath_prepend(str(root / "scripts"))
    monkeypatch.syspath_prepend(str(root))


def test_a_decorated_report_asks_once_and_census_reports_are_decorated(tmp_path, monkeypatch):
    from spa_core.monitoring import duplicate_subject_census as dsc
    from spa_core.monitoring import history_door_price as hdp
    from spa_core.monitoring import order_subject_census as osc
    sc = Scene(tmp_path, {"scripts/a.py": "x\n"})

    @SR.one_pin_per_call
    def report():
        return [dsc.read_base_tree(sc.work, "origin/main")["sha"] for _ in range(3)]

    spy = Spy(monkeypatch)
    assert len(set(report())) == 1 and spy.ls_remote == 1
    for fn in (dsc.run_census, osc.run_census, hdp.build_report):
        assert getattr(fn, "__wrapped__", None) is not None, f"{fn.__module__}.{fn.__name__}"
