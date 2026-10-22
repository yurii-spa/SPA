"""Значение `origin/main` спрашивается у СЕРВЕРА и закрепляется sha (ADR-361/362, инв. #17).

# LLM_FORBIDDEN

Каждая сцена — одноразовые git-репозитории: «сервер» — локальный bare-репо, «рабочая
копия» — клон с настоящим удалённым `origin`. Имя ветки объявлено (`-b main`), сеть
наружу не используется. Контроль в обе стороны:

* **смена ref** — сервер ушёл вперёд, локальный кэш `origin/main` стоит на прошлом:
  прежнее чтение кэша дало бы старый ответ (это и проверяется отдельной строкой — что
  кэш действительно устарел), закреплённое значение — новый;
* **сетевой отказ** — удалённый недоступен: ответа нет (`sha is None` + причина), а не
  чтение кэша, который при этом лежит на месте и читается;
* **конкурентное изменение** — сервер сдвинулся МЕЖДУ вопросом (`ls-remote`) и
  добором объекта (`fetch`): читается ровно названный сервером sha; если же ветку
  переписали так, что названный объект больше не добирается, — отказ.

Те же три сцены прогоняются через каждого исправленного читателя: сторож удалений
(путь доставки), сводка §49, проба многокритериального приказа, дочитывание популяции
проб и `release_of`.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from spa_core.utils import server_ref as SR  # noqa: E402

TRACKER = "nimbalyst-local/tracker"


def _git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                       env={"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
                            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
                            "HOME": str(repo), "GIT_CONFIG_NOSYSTEM": "1"})
    if check and r.returncode != 0:
        raise AssertionError(f"git {' '.join(args)}: {r.stderr}")
    return r.stdout.strip()


def _commit(repo, rel, text, msg):
    p = Path(repo) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    if text is None:
        p.unlink()
        _git(repo, "add", "-A")
    else:
        p.write_text(text, encoding="utf-8")
        _git(repo, "add", rel)
    _git(repo, "commit", "-q", "-m", msg)
    return _git(repo, "rev-parse", "HEAD")


class Scene:
    """Сервер (bare) + рабочая копия `work` + второй писатель `other`."""

    def __init__(self, tmp: Path, files: dict):
        self.server = tmp / "server.git"
        _git(tmp, "init", "-q", "--bare", "-b", "main", str(self.server))
        seed = tmp / "seed"
        _git(tmp, "init", "-q", "-b", "main", str(seed))
        for rel, text in files.items():
            p = seed / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(text, encoding="utf-8")
        _git(seed, "add", "-A")
        _git(seed, "commit", "-q", "-m", "base")
        _git(seed, "remote", "add", "origin", str(self.server))
        _git(seed, "push", "-q", "origin", "main")
        self.base = _git(seed, "rev-parse", "HEAD")
        self.work = tmp / "work"
        _git(tmp, "clone", "-q", "-b", "main", str(self.server), str(self.work))
        self.other = tmp / "other"
        _git(tmp, "clone", "-q", "-b", "main", str(self.server), str(self.other))

    def advance(self, rel, text, msg="advance"):
        """Второй писатель доставляет на сервер; кэш `work` об этом НЕ знает."""
        sha = _commit(self.other, rel, text, msg)
        _git(self.other, "push", "-q", "origin", "main")
        return sha

    def hide_from_cache(self):
        """Объекты сервера уже ЛЕЖАТ локально, а кэш `origin/main` указывает на
        прошлое (так бывает, когда ссылку сдвинул другой процесс или чужой fetch
        принёс объекты раньше). Закрепление тогда не делает fetch, кэш не
        освежается — и читатель, читающий ИМЯ ссылки вместо sha, отвечает о прошлом."""
        before = self.cached()
        _git(self.work, "fetch", "-q", "origin", "main")
        _git(self.work, "update-ref", "refs/remotes/origin/main", before)

    def cached(self):
        return _git(self.work, "rev-parse", "refs/remotes/origin/main")

    def cut_network(self):
        _git(self.work, "remote", "set-url", "origin", str(self.server) + "-gone")


# ───────────────────────── сам закрепитель ─────────────────────────

def test_ref_moved_on_the_server_is_seen_and_the_cache_is_not_read(tmp_path):
    sc = Scene(tmp_path, {"a.txt": "v1\n"})
    new = sc.advance("a.txt", "v2\n")
    assert sc.cached() == sc.base != new, "предпосылка: кэш действительно устарел"
    pin = SR.pin_server_ref(str(sc.work), "origin/main")
    assert pin.ok and pin.source == "server" and pin.sha == new, pin
    assert _git(sc.work, "show", f"{pin.sha}:a.txt") == "v2"
    # та же форма через полное имя ссылки
    assert SR.pin_server_ref(str(sc.work), "refs/remotes/origin/main").sha == new


def test_network_failure_is_unmeasured_not_a_cache_read(tmp_path):
    sc = Scene(tmp_path, {"a.txt": "v1\n"})
    sc.advance("a.txt", "v2\n")
    sc.cut_network()
    assert _git(sc.work, "show", "origin/main:a.txt") == "v1", "кэш лежит и читается"
    pin = SR.pin_server_ref(str(sc.work), "origin/main", timeout=30)
    assert not pin.ok and pin.sha is None and pin.source == "unmeasured"
    assert "не ответил" in pin.reason and "кэш" in pin.reason


def test_branch_absent_on_the_server_is_unmeasured(tmp_path):
    sc = Scene(tmp_path, {"a.txt": "v1\n"})
    pin = SR.pin_server_ref(str(sc.work), "origin/no-such-branch")
    assert not pin.ok and "ветки нет на сервере" in pin.reason


def test_a_painted_cache_without_a_remote_is_not_read_as_local(tmp_path):
    """`refs/remotes/origin/main`, нарисованный `update-ref` без удалённого, — всё равно
    кэш. Классифицировать его как «локальную ссылку» значило бы прочитать его молча."""
    repo = tmp_path / "r"
    _git(tmp_path, "init", "-q", "-b", "main", str(repo))
    _commit(repo, "a.txt", "x\n", "c")
    _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    pin = SR.pin_server_ref(str(repo), "origin/main")
    assert not pin.ok and pin.remote == "origin", pin


def test_a_local_ref_or_sha_is_resolved_locally(tmp_path):
    sc = Scene(tmp_path, {"a.txt": "v1\n"})
    for ref in ("main", "HEAD", sc.base):
        pin = SR.pin_server_ref(str(sc.work), ref)
        assert pin.ok and pin.source == "local" and pin.sha == sc.base, (ref, pin)
    assert not SR.pin_server_ref(str(sc.work), "0" * 40).ok


def test_server_moving_between_the_question_and_the_fetch_reads_the_named_sha(
        tmp_path, monkeypatch):
    """Конкурентное изменение: сервер сдвинулся ПОСЛЕ ls-remote и ДО fetch. Читается
    ровно то состояние, которое сервер назвал (sha закреплён), а не «что там сейчас»."""
    sc = Scene(tmp_path, {"a.txt": "v1\n"})
    named = sc.advance("a.txt", "v2\n", "named by ls-remote")
    real = SR._git
    later = {}

    def racing(repo, args, timeout):
        if args and args[0] == "fetch" and not later:
            later["sha"] = sc.advance("a.txt", "v3\n", "pushed during the fetch window")
        return real(repo, args, timeout)

    monkeypatch.setattr(SR, "_git", racing)
    pin = SR.pin_server_ref(str(sc.work), "origin/main")
    assert later, "предпосылка: сервер действительно сдвинулся между шагами"
    assert pin.ok and pin.sha == named != later["sha"], pin
    assert _git(sc.work, "show", f"{pin.sha}:a.txt") == "v2"


def test_rewritten_branch_between_question_and_fetch_is_refused(tmp_path, monkeypatch):
    """Ветку ПЕРЕПИСАЛИ между ls-remote и fetch: названного объекта на сервере больше
    нет. Закреплять нечего — отказ, а не тихое чтение нового (или старого) значения."""
    sc = Scene(tmp_path, {"a.txt": "v1\n"})
    sc.advance("a.txt", "v2\n", "named, then rewritten away")
    real = SR._git
    done = {}

    def rewriting(repo, args, timeout):
        if args and args[0] == "fetch" and not done:
            _git(sc.other, "reset", "-q", "--hard", sc.base)
            _commit(sc.other, "a.txt", "v9\n", "rewritten")
            _git(sc.other, "push", "-q", "-f", "origin", "main")
            _git(sc.server, "reflog", "expire", "--expire=now", "--all")
            _git(sc.server, "gc", "-q", "--prune=now")
            done["yes"] = True
        return real(repo, args, timeout)

    monkeypatch.setattr(SR, "_git", rewriting)
    pin = SR.pin_server_ref(str(sc.work), "origin/main")
    assert done and not pin.ok and "после fetch объекта нет" in pin.reason, pin


# ───────────── сторож удалений (путь доставки, обе двери пушера) ─────────────

CALC_OLD = '<div><span id="calc-real">1</span></div>\n<div><span id="calc-agg">2</span></div>\n'
CALC_NEW = '<div><span id="calc-real">1</span></div>\n'
PAGE = "landing/src/pages/index.astro"


def _ce():
    import check_change_evidence as CE
    return CE


def test_change_evidence_sees_a_removal_that_already_reached_the_server(tmp_path):
    """Удаление уже на сервере, кэш его не знает. По кэшу сторож отказал бы (ложный
    отказ), по закреплённой базе — удаления в наборе нет."""
    CE = _ce()
    sc = Scene(tmp_path, {PAGE: CALC_OLD})
    sc.advance(PAGE, CALC_NEW, "calc-agg removed with its record, already delivered")
    sc.hide_from_cache()
    (sc.work / PAGE).write_text(CALC_NEW, encoding="utf-8")
    rc_cache, _ = CE.run([str(sc.work / PAGE)], "x", base=sc.cached())
    assert rc_cache == 1, "предпосылка: по устаревшему кэшу сторож отказывает"
    rc, text = CE.run([str(sc.work / PAGE)], "x")
    assert rc == 0 and "no significant removal" in text, text


def test_change_evidence_catches_a_removal_hidden_by_a_stale_cache(tmp_path):
    """Обратная сторона: элемент ДОБАВЛЕН на сервер после кэша и удаляется набором.
    По кэшу удаления не видно (элемента там не было) — по серверу оно есть."""
    CE = _ce()
    sc = Scene(tmp_path, {PAGE: CALC_NEW})
    sc.advance(PAGE, CALC_OLD, "calc-agg added on the server")
    sc.hide_from_cache()
    (sc.work / PAGE).write_text(CALC_NEW, encoding="utf-8")
    rc_cache, _ = CE.run([str(sc.work / PAGE)], "x", base=sc.cached())
    assert rc_cache == 0, "предпосылка: устаревший кэш прячет удаление"
    rc, text = CE.run([str(sc.work / PAGE)], "x")
    assert rc == 1 and "id:calc-agg" in text, text


def test_change_evidence_without_the_server_is_not_measured_and_the_pusher_refuses(tmp_path):
    CE = _ce()
    sc = Scene(tmp_path, {PAGE: CALC_OLD})
    (sc.work / PAGE).write_text(CALC_NEW, encoding="utf-8")
    sc.cut_network()
    rc, text = CE.run([str(sc.work / PAGE)], "x")
    assert rc == 2 and "NOT MEASURED" in text and "не ответил" in text, text
    # путь доставки: пушер отказывает fail-CLOSED; обход — только существующий флаг
    import push_to_github as P
    with pytest.raises(P.ChangeEvidenceMissing):
        P.enforce_change_evidence([str(sc.work / PAGE)], "x",
                                  runner_file=str(ROOT / "push_to_github.py"))
    assert P.enforce_change_evidence([str(sc.work / PAGE)], "x", allow_unmeasured=True,
                                     runner_file=str(ROOT / "push_to_github.py")) is True


# ───────────── проба многокритериального приказа и популяция проб ─────────────

ORDER = "inbox-order-many"
CARD_PROBE = "---\nstatus: in-progress\nacceptance_probe: some_probe\n---\nbody\n"
CARD_CLEAN = "---\nstatus: in-progress\n---\nbody\n"


def test_multi_criterion_probe_reads_the_server_copy(tmp_path):
    from spa_core.monitoring import card_acceptance as ca
    sc = Scene(tmp_path, {f"{TRACKER}/{ORDER}.md": CARD_CLEAN})
    sc.advance(f"{TRACKER}/{ORDER}.md", CARD_PROBE, "probe declared on the order")
    sc.hide_from_cache()
    tracker = sc.work / TRACKER
    (tracker / f"{ORDER}.md").unlink()           # копия только на ref
    # кэш говорит обратное — предпосылка, что ответ придёт не из него
    assert "acceptance_probe" not in _git(sc.work, "show",
                                          f"origin/main:{TRACKER}/{ORDER}.md")
    v, d = ca._probe_no_single_criterion_probe_on_a_multi_criterion_order(
        ORDER, tracker_dir=str(tracker), repo_root=str(sc.work))
    assert v == ca.NOT_SATISFIED and "origin/main" in d, d


def test_multi_criterion_probe_without_the_server_is_unmeasured(tmp_path):
    from spa_core.monitoring import card_acceptance as ca
    sc = Scene(tmp_path, {f"{TRACKER}/{ORDER}.md": CARD_CLEAN})
    sc.cut_network()
    v, d = ca._probe_no_single_criterion_probe_on_a_multi_criterion_order(
        ORDER, tracker_dir=str(sc.work / TRACKER), repo_root=str(sc.work))
    assert v == ca.UNMEASURED and "не прочитана" in d and "не ответил" in d, d


def test_probe_population_on_ref_counts_cards_delivered_after_the_cache(tmp_path):
    from spa_core.monitoring import card_acceptance as ca
    sc = Scene(tmp_path, {f"{TRACKER}/inbox-a.md": CARD_PROBE})
    sc.advance(f"{TRACKER}/inbox-b.md", CARD_PROBE, "second card declares a probe")
    sc.hide_from_cache()
    note: list = []
    got = ca.cards_declaring_a_probe_on_ref(repo_root=str(sc.work), note=note)
    assert sorted(got) == ["inbox-a.md", "inbox-b.md"], (got, note)
    assert note and "спрошен у сервера" in note[0]
    sc.cut_network()
    note = []
    assert ca.cards_declaring_a_probe_on_ref(repo_root=str(sc.work), note=note) is None
    assert "не ответил" in note[0]


def test_audit_names_an_unpinned_ref_as_unmeasured(tmp_path):
    from spa_core.monitoring import card_acceptance as ca
    sc = Scene(tmp_path, {f"{TRACKER}/inbox-a.md": CARD_CLEAN})
    sc.cut_network()
    rep = ca.audit(str(sc.work / TRACKER))
    assert rep["origin"]["state"] == "unmeasured" and "не ответил" in rep["origin"]["reason"]


# ───────────────────────── сводка §49 ─────────────────────────

S49_3 = ("---\ntitle: \"TASK\"\nstatus: in-progress\n---\n\n## Задание\n\nпреамбула\n\n\n⸻\n\n\n"
         "49. Acceptance criteria\nРабота считается выполненной только когда доказано следующее.\n"
         "Architecture\nописание.\nEconomics\nописание.\nNo regression\nописание.\n\n\n⸻\n\n\n"
         "50. Definition of Done\n")
S49_2 = S49_3.replace("No regression\nописание.\n", "")


def test_rollup_population_compares_with_the_server_copy_not_the_cache(tmp_path):
    """§49 на сервере изменился после кэша. По кэшу копии «сошлись» (тавтологично),
    по закреплённому sha — население РАЗНОЕ, и это НЕ ИЗМЕРЕНО, а не вердикт."""
    import cio_acceptance_rollup as rollup
    sc = Scene(tmp_path, {rollup.CARD_REL: S49_3})
    sc.advance(rollup.CARD_REL, S49_2, "§49 narrowed on the server")
    sc.hide_from_cache()
    cached = rollup.read_population(str(sc.work), ref=sc.cached())
    assert cached["criteria"] == ["Architecture", "Economics", "No regression"], \
        "предпосылка: кэш соглашается с деревом"
    with pytest.raises(rollup.Unmeasured) as exc:
        rollup.read_population(str(sc.work))
    assert "РАЗНОЕ население" in str(exc.value), str(exc.value)


def test_rollup_population_without_the_server_names_the_unread_copy(tmp_path):
    import cio_acceptance_rollup as rollup
    sc = Scene(tmp_path, {rollup.CARD_REL: S49_3})
    sc.cut_network()
    got = rollup.read_population(str(sc.work))
    assert got["ref_sha"] is None and len(got["sources"]) == 1, got
    assert "НЕ СОСТОЯЛОСЬ" in got["comparison"]
    assert any("не прочитана" in p and "не ответил" in p for p in got["problems"]), got


# ───────────────────────── release_of ─────────────────────────

def test_release_of_on_a_stale_cache_is_judged_by_the_server(tmp_path):
    from spa_core.studio_os import provenance as prov
    sc = Scene(tmp_path, {"a.txt": "v1\n"})
    new = sc.advance("a.txt", "v2\n")
    _git(sc.work, "fetch", "-q", "origin", "main")
    _git(sc.work, "update-ref", "refs/remotes/origin/main", sc.base)   # кэш отстал
    empty = tmp_path / "nodata"
    empty.mkdir()
    r = prov.release_of(new[:9], root=sc.work, data_dir=empty)
    assert r["state"] == "ON_MAIN_PRODUCTION_UNKNOWN" and r["on_origin_main"] is True, r
    assert "спрошен у сервера" in r["origin_main"]
    # кэш давал бы «не на main» — предпосылка
    rc = subprocess.run(["git", "-C", str(sc.work), "merge-base", "--is-ancestor", new,
                         "origin/main"]).returncode
    assert rc == 1


def test_release_of_without_the_server_is_unknown_not_off_main(tmp_path):
    from spa_core.studio_os import provenance as prov
    sc = Scene(tmp_path, {"a.txt": "v1\n"})
    sc.cut_network()
    empty = tmp_path / "nodata"
    empty.mkdir()
    r = prov.release_of(sc.base[:9], root=sc.work, data_dir=empty)
    assert r["state"] == "UNKNOWN" and r["on_origin_main"] is None, r
    assert "НЕ УСТАНОВЛЕН" in r["origin_main"]
