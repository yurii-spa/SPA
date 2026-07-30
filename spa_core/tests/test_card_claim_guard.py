"""Гарантия шага 0b протокола: «эту карточку уже кто-то взял?».

Дефект процесса (карточка `agent-card-claim-collision-guard`, найден циклом #46): 30.07 две
автономные сессии независимо взяли ОДНУ карточку `agent-ci-ignores-golive-gate-tests` —
`pid6621` в 14:04:48Z и `pid17579` в 15:16:32Z. Обе проделали одну и ту же работу, обе правили
`.github/workflows/ci.yml` и `test.yml`; доставлена одна, работа второй осталась в
`/private/tmp/spa_wt_cycle46`. Протокол обязывает объявлять владение, но `log_session_change.py`
— журнал, а не проверка: «занята ли карточка» решалось внимательностью, и ровно она отказала.

`scripts/check_card_claim.py` отвечает на этот вопрос детерминированно (stdlib, read-only, без
сети): захват в frontmatter карточки + объявления, относящиеся к ней (поле `card:` · файл
карточки в объявленном владении · упоминание в тексте), с измерением активности сессии тем же
кодом, что и шаг 0a. Всё, что измерить не удалось, публикуется как «НЕ ИЗМЕРЕНО» и даёт код
возврата 2 (fail-CLOSED, инв. #2) — молчаливого «свободна» нет.

Тесты герметичны: свой каталог карточек и свой журнал в ``tmp_path``, `ps` подменяется,
время подаётся явно. Сети и git тут нет.
"""
import importlib.util
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]

NOW = datetime(2026, 7, 30, 20, 0, 0, tzinfo=timezone.utc)


def _load(name, rel):
    path = ROOT / rel
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_test_card_claim_guard", "scripts/check_card_claim.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


@pytest.fixture()
def ps_dead():
    """`ps` отвечает «процесса нет» — активность не подтверждена (типичный случай)."""
    return lambda pid: (1, "")


@pytest.fixture()
def ps_alive():
    """`ps` показывает процесс, стартовавший ДО объявления ⇒ активность ПОДТВЕРЖДЕНА."""
    started = (NOW - timedelta(hours=48)).astimezone().strftime("%a %b %d %H:%M:%S %Y")
    return lambda pid: (0, started + "\n")


@pytest.fixture()
def ps_broken():
    """`ps` не отработал — активность НЕ измерена (fail-CLOSED, не «свободна»)."""
    return lambda pid: (127, "")


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@pytest.fixture()
def tracker(tmp_path):
    d = tmp_path / "tracker"
    d.mkdir()
    return d


def write_card(tracker, cid, *, status="backlog", claimed_by=None, claimed_at=None,
               title="Тестовая карточка", extra_body="тело карточки\n"):
    fm = ["---", "trackerStatus:", "  type: agent-task", f"title: {title}",
          f"status: {status}", "priority: high"]
    if claimed_by:
        fm.append(f"claimed_by: {claimed_by}")
    if claimed_at:
        fm.append(f"claimed_at: {claimed_at}")
    fm.append("---")
    p = tracker / f"{cid}.md"
    p.write_text("\n".join(fm) + "\n\n" + extra_body, encoding="utf-8")
    return p


@pytest.fixture()
def log(tmp_path):
    p = tmp_path / "session_changes.jsonl"
    p.write_text("", encoding="utf-8")
    return p


def write_log(path, entries):
    path.write_text("".join(json.dumps(e, ensure_ascii=False) + "\n" for e in entries),
                    encoding="utf-8")


def announce(session, ts, *, summary="работа", files=(), card=None, card_state=None):
    e = {"ts": _fmt(ts), "session": session, "summary": summary,
         "files": [str(f) for f in files], "verified": ""}
    if card:
        e["card"] = card
        e["card_state"] = card_state or "claim"
    return e


def run(guard, tracker, log, card, *, session="pid1", ps=None, now=NOW,
        grace_hours=3.0, planned_files=(), sibling=None):
    return guard.gather(card, log=log, tracker_dir=tracker, sibling=sibling,
                        self_session=session, now=now, grace_hours=grace_hours,
                        planned_files=planned_files, ps=ps)


# ── базовая семантика вердикта ───────────────────────────────────────────────

class TestVerdicts:
    def test_free_card_with_empty_log(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert guard.exit_code(r) == 0
        assert r["claims"] == [] and r["unmeasured"] == []

    def test_fresh_frontmatter_claim_by_other_blocks(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x", claimed_by="pid999",
                   claimed_at=_fmt(NOW - timedelta(minutes=20)))
        r = run(guard, tracker, log, "agent-x", session="pid1", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED
        assert guard.exit_code(r) == 1
        assert r["claims"][0]["session"] == "pid999"
        assert r["claims"][0]["state"] == "fresh"
        assert r["claims"][0]["strength"] == guard.STRONG

    def test_own_claim_does_not_block(self, guard, sibling, tracker, log, ps_dead):
        """Контроль: проверка не должна ловить собственный захват — иначе она бесполезна."""
        write_card(tracker, "agent-x", claimed_by="pid1",
                   claimed_at=_fmt(NOW - timedelta(minutes=5)))
        r = run(guard, tracker, log, "agent-x", session="pid1", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert r["self_claims"] and r["claims"] == []

    def test_old_claim_dead_session_is_stale_not_free(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x", claimed_by="pid999",
                   claimed_at=_fmt(NOW - timedelta(hours=9)))
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.STALE
        assert guard.exit_code(r) == 1
        assert r["claims"][0]["state"] == "stale"
        # порядок прежний: подъём осиротевшей работы — ручной, авто-захвата нет
        assert "вручную" in guard.render(r).lower()

    def test_old_claim_but_session_alive_still_blocks(self, guard, sibling, tracker, log, ps_alive):
        """Сессия работает дольше окна ожидания — подтверждённая активность важнее возраста."""
        write_card(tracker, "agent-x", claimed_by="pid999",
                   claimed_at=_fmt(NOW - timedelta(hours=9)))
        r = run(guard, tracker, log, "agent-x", ps=ps_alive, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED
        assert r["claims"][0]["state"] == "fresh"

    def test_terminal_status_releases_forgotten_claim(self, guard, sibling, tracker, log, ps_dead):
        """Карточка `done` не может быть занята — иначе забытый claimed_by блокирует навсегда."""
        write_card(tracker, "agent-x", status="done", claimed_by="pid999",
                   claimed_at=_fmt(NOW - timedelta(minutes=10)))
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert r["history"] and r["history"][0]["state"] == "released"


# ── fail-CLOSED: «не измерено» никогда не сворачивается в «свободна» ──────────

class TestFailClosed:
    def test_missing_log_is_unchecked(self, guard, sibling, tracker, tmp_path, ps_dead):
        write_card(tracker, "agent-x")
        r = run(guard, tracker, tmp_path / "нет.jsonl", "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.UNCHECKED
        assert guard.exit_code(r) == 2
        assert any("журнала объявлений нет" in u["reason"] for u in r["unmeasured"])

    def test_missing_card_is_unchecked(self, guard, sibling, tracker, log, ps_dead):
        r = run(guard, tracker, log, "agent-nope", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.UNCHECKED
        assert any("карточки нет" in u["reason"] for u in r["unmeasured"])

    def test_unparsable_claimed_at_is_unchecked(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x", claimed_by="pid999", claimed_at="вчера")
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.UNCHECKED
        assert any("claimed_at не разобран" in u["reason"] for u in r["unmeasured"])
        assert "'вчера'" in " ".join(u["reason"] for u in r["unmeasured"])  # вербатим

    def test_old_claim_with_unmeasurable_activity_is_unchecked(self, guard, sibling, tracker,
                                                               log, ps_broken):
        write_card(tracker, "agent-x", claimed_by="pid999",
                   claimed_at=_fmt(NOW - timedelta(hours=9)))
        r = run(guard, tracker, log, "agent-x", ps=ps_broken, sibling=sibling)
        assert r["verdict"] == guard.UNCHECKED
        assert guard.exit_code(r) == 2

    def test_malformed_log_lines_are_reported(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        log.write_text('{"ts": "неполный"\nне json\n', encoding="utf-8")
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.UNCHECKED
        assert any("нечитаемых строк журнала" in u["reason"] for u in r["unmeasured"])

    def test_entry_hits_card_but_timestamp_broken(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        write_log(log, [{"ts": "not-a-date", "session": "pid999", "summary": "работа",
                         "files": [], "card": "agent-x"}])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.UNCHECKED
        assert any("метка времени не разобрана" in u["reason"] for u in r["unmeasured"])

    def test_sibling_must_exist(self, guard, tmp_path):
        """Логика «жива ли сессия» не копируется — если её нет, это «не измерено», не «свободна»."""
        with pytest.raises(ImportError):
            guard.load_sibling(tmp_path / "нет.py")


# ── связь объявление ↔ карточка ──────────────────────────────────────────────

class TestAnnounceLink:
    def test_explicit_card_field_blocks(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=30), card="agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED
        assert r["claims"][0]["strength"] == guard.STRONG
        assert "card:" in r["claims"][0]["detail"]

    def test_card_file_in_declared_files_blocks(self, guard, sibling, tracker, log, ps_dead):
        """Ровно форма реального столкновения #46: карточка объявлена в списке файлов."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=30),
                                 files=["/repo/nimbalyst-local/tracker/agent-x.md"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED
        assert r["claims"][0]["strength"] == guard.STRONG

    def test_text_mention_blocks_only_while_fresh(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=30),
                                 summary="беру карточку agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED
        assert r["claims"][0]["strength"] == guard.WEAK

    def test_old_text_mention_is_history_not_finding(self, guard, sibling, tracker, log, ps_dead):
        """Иначе любая когда-либо тронутая карточка занята навсегда; старое НЕдоставленное —
        домен шага 0a (check_undelivered_work), дублировать его тут нельзя."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(days=6),
                                 summary="раньше трогали agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert r["history"] and r["history"][0]["state"] == "history"

    def test_old_strong_claim_from_log_is_stale(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(hours=8), card="agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.STALE

    def test_card_state_done_releases_claim(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        write_log(log, [
            announce("pid999", NOW - timedelta(hours=2), card="agent-x"),
            announce("pid999", NOW - timedelta(minutes=10), card="agent-x", card_state="done"),
        ])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert any(h["state"] == "released" for h in r["history"])

    def test_terminal_card_status_neutralises_log_claims(self, guard, sibling, tracker, log,
                                                         ps_dead):
        """Закрытую карточку взять нельзя по определению — «занятость» по ней только учит
        игнорировать вердикт. Найдено dogfood-прогоном на живом журнале: снятие захвата
        объявлением работает лишь для ТОЙ ЖЕ сессии, а идентификатор сессии не переживает
        CLI-команду (agent-durable-session-id) ⇒ своя же закрытая карточка «занята»."""
        write_card(tracker, "agent-x", status="done")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=5), card="agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert r["history"] and r["history"][0]["state"] == "released"
        assert "работа закрыта" in r["history"][0]["detail"]

    def test_terminal_status_does_not_hide_file_overlap(self, guard, sibling, tracker, log,
                                                        ps_dead):
        """Контроль: пересечение по ФАЙЛАМ — про файлы, а не про карточку, и остаётся находкой."""
        write_card(tracker, "agent-x", status="done")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=5), card="agent-x",
                                 files=["/repo/scripts/a.py"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/scripts/a.py"])
        assert r["verdict"] == guard.CLAIMED and r["overlaps"]

    def test_reclaim_after_done_blocks_again(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        write_log(log, [
            announce("pid999", NOW - timedelta(hours=2), card="agent-x"),
            announce("pid999", NOW - timedelta(hours=1), card="agent-x", card_state="done"),
            announce("pid999", NOW - timedelta(minutes=5), card="agent-x"),
        ])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED

    def test_other_card_does_not_block(self, guard, sibling, tracker, log, ps_dead):
        """Контроль: чужая карточка в журнале не должна делать эту занятой."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=5), card="agent-other",
                                 files=["/repo/nimbalyst-local/tracker/agent-other.md"],
                                 summary="беру agent-other")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE

    def test_own_announcement_does_not_block(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid1", NOW - timedelta(minutes=5), card="agent-x")])
        r = run(guard, tracker, log, "agent-x", session="pid1", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert r["self_claims"]

    def test_card_argument_accepts_path_and_id(self, guard, tracker):
        p = write_card(tracker, "agent-x")
        assert guard.card_path("agent-x", tracker) == p
        assert guard.card_path("agent-x.md", tracker) == p
        assert guard.card_path(str(p), tracker) == p


# ── пересечение по объявленным файлам ────────────────────────────────────────

class TestFileOverlap:
    def test_fresh_overlap_blocks(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=20),
                                 files=["/repo/.github/workflows/ci.yml"],
                                 summary="правлю CI")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/.github/workflows/ci.yml"])
        assert r["verdict"] == guard.CLAIMED
        assert r["overlaps"][0]["files"] == ["/repo/.github/workflows/ci.yml"]

    def test_overlap_matches_across_worktrees(self, guard, sibling, tracker, log, ps_dead):
        """Одна и та же работа объявляется из разных корней (хост-репо / worktree)."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=20),
                                 files=["/private/tmp/spa_wt_46/workflows/ci.yml"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/.github/workflows/ci.yml"])
        assert r["overlaps"]

    def test_same_basename_alone_is_not_overlap(self, guard):
        """Контроль против ложных срабатываний: `__init__.py` есть везде."""
        assert not guard.paths_overlap("/a/one/__init__.py", "/b/two/__init__.py")
        assert guard.paths_overlap("/a/pkg/__init__.py", "/b/pkg/__init__.py")

    def test_old_overlap_is_not_a_finding(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(days=2),
                                 files=["/repo/.github/workflows/ci.yml"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/.github/workflows/ci.yml"])
        assert r["overlaps"] == [] and r["verdict"] == guard.FREE

    def test_own_files_do_not_overlap(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid1", NOW - timedelta(minutes=10),
                                 files=["/repo/a.py"])])
        r = run(guard, tracker, log, "agent-x", session="pid1", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/a.py"])
        assert r["overlaps"] == []


# ── взятие / освобождение карточки ───────────────────────────────────────────

class TestClaimAndRelease:
    def test_claim_writes_fields_and_preserves_the_rest(self, guard, sibling, tracker, log):
        p = write_card(tracker, "agent-x", extra_body="## Тело\n\nстрока 1\nстрока 2\n")
        before = p.read_text(encoding="utf-8")
        res = guard.claim_card("agent-x", session="pid1", tracker_dir=tracker, now=NOW,
                               sibling=sibling, log=log, ps=lambda pid: (1, ""))
        after = p.read_text(encoding="utf-8")
        assert res["claimed_by"] == "pid1"
        meta = guard.frontmatter(after)
        assert meta["claimed_by"] == "pid1" and meta["claimed_at"] == _fmt(NOW)
        # ровно две новые строки, всё остальное байт-в-байт
        assert [ln for ln in after.splitlines() if ln not in before.splitlines()] == [
            "claimed_by: pid1", f"claimed_at: {_fmt(NOW)}"]
        assert after.split("---", 2)[2] == before.split("---", 2)[2]

    def test_claim_refuses_when_held_by_another(self, guard, sibling, tracker, log):
        write_card(tracker, "agent-x", claimed_by="pid999",
                   claimed_at=_fmt(NOW - timedelta(minutes=5)))
        with pytest.raises(guard.ClaimError) as exc:
            guard.claim_card("agent-x", session="pid1", tracker_dir=tracker, now=NOW,
                             sibling=sibling, log=log, ps=lambda pid: (1, ""))
        assert "claimed" in str(exc.value)

    def test_claim_refuses_when_unmeasured(self, guard, sibling, tracker, tmp_path):
        """Нет журнала ⇒ занятость не измерена ⇒ карточка НЕ берётся (fail-CLOSED)."""
        write_card(tracker, "agent-x")
        with pytest.raises(guard.ClaimError) as exc:
            guard.claim_card("agent-x", session="pid1", tracker_dir=tracker, now=NOW,
                             sibling=sibling, log=tmp_path / "нет.jsonl",
                             ps=lambda pid: (1, ""))
        assert "unchecked" in str(exc.value)

    def test_claim_refuses_while_another_write_is_in_flight(self, guard, sibling, tracker, log):
        p = write_card(tracker, "agent-x")
        lock = guard._lock_path(p)
        lock.write_text("pid999\n", encoding="utf-8")
        with pytest.raises(guard.ClaimError) as exc:
            guard.claim_card("agent-x", session="pid1", tracker_dir=tracker, now=NOW,
                             sibling=sibling, log=log, ps=lambda pid: (1, ""))
        assert "правит другая сессия" in str(exc.value)
        assert lock.exists()          # чужую блокировку не сносим молча

    def test_release_restores_the_card_byte_for_byte(self, guard, sibling, tracker, log):
        p = write_card(tracker, "agent-x")
        before = p.read_text(encoding="utf-8")
        guard.claim_card("agent-x", session="pid1", tracker_dir=tracker, now=NOW,
                         sibling=sibling, log=log, ps=lambda pid: (1, ""))
        guard.release_card("agent-x", session="pid1", tracker_dir=tracker)
        assert p.read_text(encoding="utf-8") == before

    def test_release_refuses_foreign_claim_without_force(self, guard, tracker):
        write_card(tracker, "agent-x", claimed_by="pid999", claimed_at=_fmt(NOW))
        with pytest.raises(guard.ClaimError):
            guard.release_card("agent-x", session="pid1", tracker_dir=tracker)
        res = guard.release_card("agent-x", session="pid1", tracker_dir=tracker, force=True)
        assert res["released"] and res["was"] == "pid999"

    def test_release_without_claim_is_a_no_op(self, guard, tracker):
        p = write_card(tracker, "agent-x")
        before = p.read_text(encoding="utf-8")
        res = guard.release_card("agent-x", session="pid1", tracker_dir=tracker)
        assert res["released"] is False
        assert p.read_text(encoding="utf-8") == before

    def test_claim_then_check_from_another_session_blocks(self, guard, sibling, tracker, log):
        """Сквозной сценарий: я взял → следующая сессия видит занятость."""
        write_card(tracker, "agent-x")
        guard.claim_card("agent-x", session="pid1", tracker_dir=tracker, now=NOW,
                         sibling=sibling, log=log, ps=lambda pid: (1, ""))
        r = run(guard, tracker, log, "agent-x", session="pid2", ps=lambda pid: (1, ""),
                now=NOW + timedelta(minutes=5), sibling=sibling)
        assert r["verdict"] == guard.CLAIMED

    def test_list_claimed_skips_terminal_cards(self, guard, tracker):
        write_card(tracker, "agent-a", claimed_by="pid1", claimed_at=_fmt(NOW))
        write_card(tracker, "agent-b", status="done", claimed_by="pid2", claimed_at=_fmt(NOW))
        write_card(tracker, "agent-c")
        rows = {r["card"]: r for r in guard.list_claimed(tracker)}
        assert set(rows) == {"agent-a", "agent-b"}
        assert rows["agent-a"]["stale"] is False and rows["agent-b"]["stale"] is True

    def test_frontmatter_without_closing_marker_is_refused(self, guard, tracker):
        p = tracker / "agent-bad.md"
        p.write_text("---\ntitle: без закрытия\nstatus: backlog\n", encoding="utf-8")
        with pytest.raises(guard.ClaimError):
            guard._set_claim_fields(p.read_text(encoding="utf-8"),
                                    {"claimed_by": "pid1", "claimed_at": _fmt(NOW)})


# ── CLI и коды возврата ──────────────────────────────────────────────────────

class TestCli:
    def _run(self, guard, argv):
        return guard.main(argv)

    def test_check_free_returns_zero(self, guard, tracker, log, capsys):
        write_card(tracker, "agent-x")
        rc = self._run(guard, ["--tracker-dir", str(tracker), "--log", str(log),
                               "check", "agent-x"])
        assert rc == 0
        assert "СВОБОДНА" in capsys.readouterr().out

    def test_check_claimed_returns_one(self, guard, tracker, log, capsys):
        write_card(tracker, "agent-x", claimed_by="pid999",
                   claimed_at=_fmt(datetime.now(timezone.utc)))
        rc = self._run(guard, ["--tracker-dir", str(tracker), "--log", str(log),
                               "check", "agent-x"])
        assert rc == 1
        assert "ЗАНЯТА" in capsys.readouterr().out

    def test_check_unmeasured_returns_two(self, guard, tracker, tmp_path, capsys):
        write_card(tracker, "agent-x")
        rc = self._run(guard, ["--tracker-dir", str(tracker),
                               "--log", str(tmp_path / "нет.jsonl"), "check", "agent-x"])
        assert rc == 2
        assert "НЕ ИЗМЕРЕНО" in capsys.readouterr().out

    def test_session_flag_excludes_my_own_announcement(self, guard, tracker, log, capsys):
        """Без `--session` собственное объявление читается как чужой захват: журнал пишет pid
        ОДНОКРАТНОЙ CLI-команды, у каждой команды сессии он свой (agent-durable-session-id)."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pidMINE", datetime.now(timezone.utc) - timedelta(minutes=5),
                                 card="agent-x")])
        assert self._run(guard, ["--tracker-dir", str(tracker), "--log", str(log),
                                 "check", "agent-x"]) == 1
        capsys.readouterr()
        assert self._run(guard, ["--tracker-dir", str(tracker), "--log", str(log),
                                 "check", "agent-x", "--session", "pidMINE"]) == 0
        assert "СВОБОДНА" in capsys.readouterr().out

    def test_json_output_is_machine_readable(self, guard, tracker, log, capsys):
        write_card(tracker, "agent-x")
        self._run(guard, ["--tracker-dir", str(tracker), "--log", str(log),
                          "--json", "check", "agent-x"])
        payload = json.loads(capsys.readouterr().out)
        assert payload["verdict"] == guard.FREE and payload["card"] == "agent-x"

    def test_claim_release_roundtrip_via_cli(self, guard, tracker, log, capsys):
        write_card(tracker, "agent-x")
        assert self._run(guard, ["--tracker-dir", str(tracker), "--log", str(log),
                                 "claim", "agent-x", "--session", "pidCLI"]) == 0
        assert guard.list_claimed(tracker)[0]["claimed_by"] == "pidCLI"
        capsys.readouterr()
        assert self._run(guard, ["--tracker-dir", str(tracker), "--log", str(log),
                                 "release", "agent-x", "--session", "pidCLI"]) == 0
        assert guard.list_claimed(tracker) == []

    def test_claim_refusal_exits_one(self, guard, tracker, log, capsys):
        write_card(tracker, "agent-x", claimed_by="pidOTHER",
                   claimed_at=_fmt(datetime.now(timezone.utc)))
        rc = self._run(guard, ["--tracker-dir", str(tracker), "--log", str(log),
                               "claim", "agent-x", "--session", "pidCLI"])
        assert rc == 1
        assert "ОТКАЗ" in capsys.readouterr().out

    def test_script_runs_as_a_subprocess(self, tracker, log):
        """Скрипт должен работать так, как его зовёт протокол — из командной строки."""
        write_card(tracker, "agent-x")
        p = subprocess.run([sys.executable, str(ROOT / "scripts" / "check_card_claim.py"),
                            "--tracker-dir", str(tracker), "--log", str(log),
                            "check", "agent-x"], capture_output=True, text=True)
        assert p.returncode == 0, p.stderr
        assert "СВОБОДНА" in p.stdout


# ── журнал объявлений: поле card ─────────────────────────────────────────────

class TestAnnounceLogField:
    @pytest.fixture()
    def logger(self, tmp_path, monkeypatch):
        mod = _load("_test_log_session_change", "scripts/log_session_change.py")
        monkeypatch.setattr(mod, "_LOG", tmp_path / "session_changes.jsonl")
        return mod

    def test_card_fields_are_written(self, logger):
        e = logger.record("работа", ["/a.py"], "тесты", card="agent-x")
        assert e["card"] == "agent-x" and e["card_state"] == "claim"
        written = json.loads(logger._LOG.read_text(encoding="utf-8").splitlines()[0])
        assert written["card"] == "agent-x"

    def test_card_state_done_is_recorded(self, logger):
        e = logger.record("доставлено", [], "", card="agent-x", card_state="done")
        assert e["card_state"] == "done"

    def test_entries_without_card_keep_the_old_shape(self, logger):
        """Обратная совместимость: старые читатели журнала не должны увидеть новых ключей."""
        e = logger.record("работа", ["/a.py"], "тесты")
        assert set(e) == {"ts", "session", "summary", "files", "verified"}

    def test_cli_accepts_card(self, logger, capsys):
        assert logger.main(["--summary", "s", "--card", "agent-x"]) == 0
        assert "card=agent-x(claim)" in capsys.readouterr().out

    def test_guard_reads_what_the_logger_writes(self, guard, sibling, logger, tracker):
        """Шов между инструментами: что пишет журнал — то читает проверка."""
        write_card(tracker, "agent-x")
        logger.record("беру", [], "", card="agent-x")
        r = guard.gather("agent-x", log=logger._LOG, tracker_dir=tracker, sibling=sibling,
                         self_session="pidOTHER", now=datetime.now(timezone.utc),
                         ps=lambda pid: (1, ""))
        assert r["verdict"] == guard.CLAIMED


# ── доска: занятость видна ───────────────────────────────────────────────────

class TestBoard:
    @pytest.fixture()
    def board(self, tmp_path, monkeypatch):
        mod = _load("_test_build_tracker_board", "scripts/build_tracker_board.py")
        d = tmp_path / "tracker"
        d.mkdir()
        monkeypatch.setattr(mod, "TRACKER", d)
        monkeypatch.setattr(mod, "OUT", d / "_BOARD.md")
        monkeypatch.setattr(mod, "REPO", tmp_path)
        return mod

    def test_claimed_card_is_visible(self, board, capsys):
        write_card(board.TRACKER, "agent-x", claimed_by="pid999", claimed_at=_fmt(NOW),
                   title="Занятая карточка")
        assert board.main() == 0
        text = board.OUT.read_text(encoding="utf-8")
        assert "ЗАНЯТЫ СЕССИЯМИ" in text
        assert "pid999" in text and "Занятая карточка" in text
        assert "занято сессиями: **1**" in text

    def test_terminal_card_claim_is_not_shown_as_busy(self, board):
        write_card(board.TRACKER, "agent-x", status="done", claimed_by="pid999",
                   claimed_at=_fmt(NOW))
        board.main()
        text = board.OUT.read_text(encoding="utf-8")
        assert "ЗАНЯТЫ СЕССИЯМИ" not in text
        assert "занято сессиями: **0**" in text

    def test_board_without_claims_is_unchanged_in_shape(self, board):
        write_card(board.TRACKER, "agent-x")
        board.main()
        text = board.OUT.read_text(encoding="utf-8")
        assert "🔒" not in text and "ЖДЁТ ВЛАДЕЛЬЦА" in text


# ── воспроизведение реального столкновения 30.07 ─────────────────────────────

class TestRealCollision:
    def test_second_session_would_have_been_stopped(self, guard, sibling, tracker, log):
        """Дословно случай #46: `pid6621` объявила карточку в 14:04:48Z (включая файл
        карточки во владении), `pid17579` берётся за неё же в 15:16:32Z."""
        write_card(tracker, "agent-ci-ignores-golive-gate-tests")
        first = datetime(2026, 7, 30, 14, 4, 48, tzinfo=timezone.utc)
        second = datetime(2026, 7, 30, 15, 16, 32, tzinfo=timezone.utc)
        write_log(log, [announce(
            "pid6621", first,
            summary="ЦИКЛ #46: беру карточку agent-ci-ignores-golive-gate-tests",
            files=["/Users/y/SPA/.github/workflows/test.yml",
                   "/Users/y/SPA/.github/workflows/ci.yml",
                   "/Users/y/SPA/nimbalyst-local/tracker/"
                   "agent-ci-ignores-golive-gate-tests.md"])])
        r = guard.gather("agent-ci-ignores-golive-gate-tests", log=log, tracker_dir=tracker,
                         sibling=sibling, self_session="pid17579", now=second,
                         planned_files=["/Users/y/SPA/.github/workflows/ci.yml"],
                         ps=lambda pid: (1, ""))
        assert r["verdict"] == guard.CLAIMED
        assert r["claims"][0]["session"] == "pid6621"
        assert r["overlaps"] and "ci.yml" in r["overlaps"][0]["files"][0]

    def test_after_the_grace_window_it_becomes_a_manual_pickup(self, guard, sibling, tracker, log):
        """Та же запись сутки спустя — не «занята», а кандидат на ручной подъём."""
        write_card(tracker, "agent-ci-ignores-golive-gate-tests")
        first = datetime(2026, 7, 30, 14, 4, 48, tzinfo=timezone.utc)
        write_log(log, [announce("pid6621", first, card="agent-ci-ignores-golive-gate-tests")])
        r = guard.gather("agent-ci-ignores-golive-gate-tests", log=log, tracker_dir=tracker,
                         sibling=sibling, self_session="pid1",
                         now=first + timedelta(days=1), ps=lambda pid: (1, ""))
        assert r["verdict"] == guard.STALE
