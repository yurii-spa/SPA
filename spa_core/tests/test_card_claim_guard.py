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

Герметичность журнала теперь ПРОВЕРЯЕТСЯ, а не обещается. До цикла #106 это утверждение было
неверным ровно для четырёх вызовов: `release_card` звался без `log=`, умолчание разрешалось в
настоящий `data/session_changes.jsonl` того дерева, откуда запущен pytest, и каждый прогон
дописывал в него 2 выдуманных захвата (`pid1`, `pid999`). Теперь `log` — обязательный аргумент
пишущих путей, а гейт `test_claim_guard_writes_are_hermetic.py` краснеет, если умолчание
вернут или вызов сделают без него.
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
        grace_hours=3.0, planned_files=(), sibling=None, self_anchor=None):
    # `self_anchor=None` по умолчанию — герметичность: иначе умолчание `gather` измеряло бы
    # долгоживущий процесс из ОКРУЖЕНИЯ прогона (`SPA_SESSION_PID`), и результат зависел бы от
    # того, запущен pytest внутри цикла оркестратора или нет. Проверки опознания подают якорь
    # явно (`TestSelfIdentityByDurableProcess`).
    return guard.gather(card, log=log, tracker_dir=tracker, sibling=sibling,
                        self_session=session, now=now, grace_hours=grace_hours,
                        planned_files=planned_files, ps=ps, self_anchor=self_anchor)


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

    def test_text_mention_blocks_only_while_the_session_is_alive(
            self, guard, sibling, tracker, log, ps_alive):
        """ИЗМЕНЁН НАМЕРЕННО (цикл #67, `agent-fresh-weak-mention-deadlocks-queue`), инв. #16.

        Раньше назывался `test_text_mention_blocks_only_while_fresh` и требовал `CLAIMED`
        при `ps_dead`: свежесть записи считалась достаточной. Замер 01.08 показал, что окно
        свежести перезаряжают сами отчёты шага 0b (циклы обязаны называть карточки поимённо,
        идут раз в час, окно — 3ч) ⇒ «только пока свеж» не наступает никогда, и очередь
        встала целиком. Условие заменено на измеримое: блокирует ЖИВАЯ сессия.
        Полный разбор и остальные контроли — `TestFreshWeakMentionDoesNotDeadlockTheQueue`."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=30),
                                 summary="беру карточку agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_alive, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED
        assert r["claims"][0]["strength"] == guard.WEAK

    def test_text_mention_by_a_dead_session_does_not_block(
            self, guard, sibling, tracker, log, ps_dead):
        """Обратная сторона той же границы (добавлено #67): мёртвая сессия не держит карточку."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=30),
                                 summary="беру карточку agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert r["history"] and r["history"][0]["strength"] == guard.WEAK

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


# ── завершённая сессия не «держит» свои файлы (agent-card-claim-file-overlap-ignores-done) ──

class TestReleasedSessionDoesNotHoldFiles:
    """Захват КАРТОЧКИ снимался объявлением `card_state: done`, а пересечение по ФАЙЛАМ —
    нет: оно смотрело только на возраст записи, поэтому завершённая сессия ещё три часа
    блокировала любую карточку, которой касались её файлы (цикл #49). Ложная занятость
    безопаснее ложной свободы, но она учит игнорировать вердикт — от чего шаг 0b и защищает."""

    def test_done_announcement_does_not_hold_files(self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=20), card="agent-other",
                                 card_state="done", files=["/repo/scripts/tool.py"],
                                 summary="ЦИКЛ #48 ЗАВЕРШЁН И ДОСТАВЛЕН")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/scripts/tool.py"])
        assert r["overlaps"] == []
        assert r["verdict"] == guard.FREE and guard.exit_code(r) == 0

    def test_live_announcement_still_holds_files(self, guard, sibling, tracker, log, ps_dead):
        """Положительный контроль: живое (не-`done`) объявление по-прежнему блокирует."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=20), card="agent-other",
                                 card_state="claim", files=["/repo/scripts/tool.py"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/scripts/tool.py"])
        assert r["verdict"] == guard.CLAIMED and r["overlaps"]

    def test_announcement_without_card_state_still_holds_files(self, guard, sibling, tracker,
                                                               log, ps_dead):
        """Положительный контроль: объявление без карточки вообще — не «done», держит файлы."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=20),
                                 files=["/repo/scripts/tool.py"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/scripts/tool.py"])
        assert r["verdict"] == guard.CLAIMED and r["overlaps"]

    def test_claim_then_done_releases_the_earlier_entry(self, guard, sibling, tracker, log,
                                                        ps_dead):
        """Файлы объявлены при взятии, а `done` пришёл отдельной записью — обе свежие."""
        write_card(tracker, "agent-x")
        write_log(log, [
            announce("pid999", NOW - timedelta(hours=2), card="agent-other",
                     files=["/repo/scripts/tool.py"]),
            announce("pid999", NOW - timedelta(hours=1), card="agent-other",
                     card_state="done", files=["/repo/scripts/tool.py"]),
        ])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/scripts/tool.py"])
        assert r["overlaps"] == [] and r["verdict"] == guard.FREE

    def test_done_then_new_claim_still_holds_files(self, guard, sibling, tracker, log, ps_dead):
        """Сессия закрыла одну карточку и взялась за следующую — более позднее взятие живое."""
        write_card(tracker, "agent-x")
        write_log(log, [
            announce("pid999", NOW - timedelta(hours=2), card="agent-other",
                     card_state="done", files=["/repo/scripts/tool.py"]),
            announce("pid999", NOW - timedelta(minutes=30), card="agent-next",
                     files=["/repo/scripts/tool.py"]),
        ])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/scripts/tool.py"])
        assert r["verdict"] == guard.CLAIMED
        assert r["overlaps"][0]["ts"] == _fmt(NOW - timedelta(minutes=30))

    def test_done_by_another_session_does_not_release_my_overlap(self, guard, sibling, tracker,
                                                                 log, ps_dead):
        """Контроль: `done` снимает файлы ТОЛЬКО объявившей сессии, а не всем сразу."""
        write_card(tracker, "agent-x")
        write_log(log, [
            announce("pid999", NOW - timedelta(minutes=20), files=["/repo/scripts/tool.py"]),
            announce("pid888", NOW - timedelta(minutes=10), card="agent-other",
                     card_state="done", files=["/repo/scripts/tool.py"]),
        ])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/scripts/tool.py"])
        assert r["verdict"] == guard.CLAIMED
        assert [o["session"] for o in r["overlaps"]] == ["pid999"]

    def test_unparsable_release_ts_does_not_release(self, guard, sibling, tracker, log, ps_dead):
        """fail-CLOSED: если время `done` не разобрано, снятие НЕ засчитывается."""
        write_card(tracker, "agent-x")
        broken = announce("pid999", NOW - timedelta(minutes=10), card="agent-other",
                          card_state="done", files=["/repo/scripts/tool.py"])
        broken["ts"] = "вчера"
        write_log(log, [announce("pid999", NOW - timedelta(minutes=20),
                                 files=["/repo/scripts/tool.py"]), broken])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/scripts/tool.py"])
        assert r["verdict"] == guard.CLAIMED and r["overlaps"]

    def test_history_names_the_files_and_the_release_time(self, guard, sibling, tracker, log,
                                                          ps_dead):
        """Снятое пересечение не исчезает молча — оно видно в «истории» с причиной."""
        done_at = NOW - timedelta(minutes=20)
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", done_at, card="agent-other", card_state="done",
                                 files=["/repo/scripts/tool.py"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/scripts/tool.py"])
        hist = [h for h in r["history"] if h["source"] == "announce-log-files"]
        assert len(hist) == 1
        assert "/repo/scripts/tool.py" in hist[0]["detail"]
        assert _fmt(done_at) in hist[0]["detail"]
        assert "/repo/scripts/tool.py" in guard.render(r)

    def test_is_release_reads_only_the_terminal_state(self, guard):
        assert guard.is_release({"card_state": "done"})
        assert guard.is_release({"card_state": " done "})
        assert not guard.is_release({"card_state": "claim"})
        assert not guard.is_release({})

    def test_releases_by_session_keeps_the_latest(self, guard, sibling):
        early, late = NOW - timedelta(hours=5), NOW - timedelta(hours=1)
        rows = [announce("pid999", early, card="a", card_state="done"),
                announce("pid999", late, card="b", card_state="done"),
                announce("pid888", late, card="c")]
        got = guard.releases_by_session(rows, sibling._parse_ts)
        assert set(got) == {"pid999"} and got["pid999"] == late


# ── воспроизведение ложной занятости цикла #49 ───────────────────────────────

class TestCycle49FalseBusy:
    def test_finished_cycle48_no_longer_blocks_the_next_card(self, guard, sibling, tracker, log):
        """Дословно цикл #49: завершённое объявление #48 (`card_state: done`, файл
        `scripts/log_session_change.py`) делало `agent-durable-session-id` «занятой»."""
        write_card(tracker, "agent-durable-session-id")
        done_ts = datetime(2026, 7, 30, 21, 27, 36, tzinfo=timezone.utc)
        now = datetime(2026, 7, 30, 23, 50, 0, tzinfo=timezone.utc)
        write_log(log, [announce(
            "pid83584", done_ts, card="agent-card-claim-collision-guard", card_state="done",
            summary="ЦИКЛ #48 ЗАВЕРШЁН И ДОСТАВЛЕН",
            files=["/Users/y/SPA/scripts/log_session_change.py",
                   "/Users/y/SPA/scripts/check_card_claim.py"])])
        r = guard.gather("agent-durable-session-id", log=log, tracker_dir=tracker,
                         sibling=sibling, self_session="cycle50", now=now,
                         planned_files=["/Users/y/SPA/scripts/log_session_change.py"],
                         ps=lambda pid: (1, ""))
        assert r["overlaps"] == []
        assert r["verdict"] == guard.FREE and guard.exit_code(r) == 0


# ── взятие / освобождение карточки ───────────────────────────────────────────

class TestClaimAndRelease:

    # ── объявленный долгоживущий процесс (цикл #387) ──────────────────────────
    #
    # Коммит `9cb8a7823` ввёл fail-CLOSED `UnmeasurableClaim`: захват под ярлыком без
    # объявленного долгоживущего процесса не записывается вовсе — такой захват НЕ СТАРЕЕТ,
    # и карточка залипла бы навсегда. Тесты НИЖЕ проверяют механику захвата/освобождения,
    # а не поведение «голого» ярлыка, и звали инструмент без переменной — покраснели все и
    # покрасили ВЕСЬ main (карточка `inbox-commit-9cb8a7823-krasit-28-testov-zahvata`).
    #
    # **Гейт не ослаблен.** Фикстура ставит класс в ту же законную конфигурацию, в которой
    # карточки берутся в проде (`scripts/agent_orchestrator.sh` выставляет `SPA_SESSION_PID`).
    # Сам отказ на НЕобъявленном ярлыке проверяет `TestClaimSaysWhenItHasNoIdentity` в этом
    # же файле, и он намеренно оставлен БЕЗ этой фикстуры — иначе положительный контроль
    # гейта был бы замаскирован, то есть мы починили бы красноту, сломав проверку.
    #
    # `os.getpid()` жив по построению. Предусловие — КРАСНОЕ, а не skip (инв. #17).
    @pytest.fixture(autouse=True)
    def _declared_durable_process(self, monkeypatch):
        import os as _os
        monkeypatch.setenv("SPA_SESSION_PID", str(_os.getpid()))
        monkeypatch.setenv("SPA_SESSION_ID", "cycle-under-test")
        announcer = _load("_guard_announcer", "scripts/log_session_change.py")
        proc, why = announcer.durable_process()
        assert proc.get("session_pid") == _os.getpid(), (
            "предусловие не выполнено: долгоживущий процесс не измерен "
            f"({why!r}) — без него класс проверял бы отказ гейта вместо своей механики, "
            "поэтому это КРАСНЫЙ, а не skip")
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
        guard.release_card("agent-x", session="pid1", tracker_dir=tracker, log=log)
        assert p.read_text(encoding="utf-8") == before

    def test_release_refuses_foreign_claim_without_force(self, guard, tracker, log):
        write_card(tracker, "agent-x", claimed_by="pid999", claimed_at=_fmt(NOW))
        with pytest.raises(guard.ClaimError):
            guard.release_card("agent-x", session="pid1", tracker_dir=tracker, log=log)
        res = guard.release_card("agent-x", session="pid1", tracker_dir=tracker, log=log,
                                 force=True)
        assert res["released"] and res["was"] == "pid999"

    def test_release_without_claim_is_a_no_op(self, guard, tracker, log):
        p = write_card(tracker, "agent-x")
        before = p.read_text(encoding="utf-8")
        res = guard.release_card("agent-x", session="pid1", tracker_dir=tracker, log=log)
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

    # ── объявленный долгоживущий процесс (цикл #387) ──────────────────────────
    #
    # Коммит `9cb8a7823` ввёл fail-CLOSED `UnmeasurableClaim`: захват под ярлыком без
    # объявленного долгоживущего процесса не записывается вовсе — такой захват НЕ СТАРЕЕТ,
    # и карточка залипла бы навсегда. Тесты НИЖЕ проверяют механику захвата/освобождения,
    # а не поведение «голого» ярлыка, и звали инструмент без переменной — покраснели все и
    # покрасили ВЕСЬ main (карточка `inbox-commit-9cb8a7823-krasit-28-testov-zahvata`).
    #
    # **Гейт не ослаблен.** Фикстура ставит класс в ту же законную конфигурацию, в которой
    # карточки берутся в проде (`scripts/agent_orchestrator.sh` выставляет `SPA_SESSION_PID`).
    # Сам отказ на НЕобъявленном ярлыке проверяет `TestClaimSaysWhenItHasNoIdentity` в этом
    # же файле, и он намеренно оставлен БЕЗ этой фикстуры — иначе положительный контроль
    # гейта был бы замаскирован, то есть мы починили бы красноту, сломав проверку.
    #
    # `os.getpid()` жив по построению. Предусловие — КРАСНОЕ, а не skip (инв. #17).
    @pytest.fixture(autouse=True)
    def _declared_durable_process(self, monkeypatch):
        import os as _os
        monkeypatch.setenv("SPA_SESSION_PID", str(_os.getpid()))
        monkeypatch.setenv("SPA_SESSION_ID", "cycle-under-test")
        announcer = _load("_guard_announcer", "scripts/log_session_change.py")
        proc, why = announcer.durable_process()
        assert proc.get("session_pid") == _os.getpid(), (
            "предусловие не выполнено: долгоживущий процесс не измерен "
            f"({why!r}) — без него класс проверял бы отказ гейта вместо своей механики, "
            "поэтому это КРАСНЫЙ, а не skip")
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
        """Обратная совместимость: старые читатели журнала не должны увидеть новых ключей.

        Предусловие теперь названо ЯВНО штатным тестовым швом `record(process=…)`: «старая
        форма» — это форма записи сессии, которая долгоживущий процесс НЕ объявила. Раньше оно
        молча бралось из окружения прогона, поэтому под выставленным `SPA_SESSION_PID` (то есть
        ровно в автономном цикле, где эти инструменты и работают) тест краснел, ничего при этом
        не измеряя. Ассерт не изменён — у него появилось условие, при котором он верен, и парный
        контроль ниже, чтобы «покрасить» его, перестав писать якорь вообще, было нельзя."""
        e = logger.record("работа", ["/a.py"], "тесты",
                          process=({}, "долгоживущий процесс сессией не объявлен"))
        assert set(e) == {"ts", "session", "summary", "files", "verified"}

    def test_entries_of_a_session_with_a_durable_process_carry_the_anchor(self, logger):
        """Парный контроль к тесту выше: объявила процесс — якорь в записи ЕСТЬ.

        Пиннит вторую половину контракта (`agent-durable-session-id`): без неё «старую форму»
        можно было бы удержать, просто перестав записывать якорь, и шаг 0a лишился бы
        единственного измерения активности сессии, не покраснев нигде."""
        e = logger.record("работа", ["/a.py"], "тесты",
                          process=({"session_pid": 4242,
                                    "session_pid_start": "Mon Aug  3 21:10:53 2026"}, ""))
        assert set(e) == {"ts", "session", "summary", "files", "verified",
                          "session_pid", "session_pid_start"}
        assert e["session_pid"] == 4242

    def test_cli_accepts_card(self, logger, capsys):
        assert logger.main(["--summary", "s", "--card", "agent-x"]) == 0
        assert "card=agent-x(claim)" in capsys.readouterr().out

    def test_guard_reads_what_the_logger_writes(self, guard, sibling, logger, tracker):
        """Шов между инструментами: что пишет журнал — то читает проверка.

        Захват объявляется ОТ ИМЕНИ другой сессии (`session=`) — ровно так `claim` пишет чужой
        захват, и ровно этот случай проверка обязана прочитать как занятость. Раньше ярлык был
        чужой, а якорь в запись всё равно уходил ЭТОГО процесса, поэтому под `SPA_SESSION_PID`
        проверка узнавала в чужом захвате себя и отвечала `free` (карточка
        `agent-claim-guard-blind-when-session-pid-is-set`). Ассерт не изменён."""
        write_card(tracker, "agent-x")
        logger.record("беру", [], "", card="agent-x", session="pidHOLDER")
        r = guard.gather("agent-x", log=logger._LOG, tracker_dir=tracker, sibling=sibling,
                         self_session="pidOTHER", now=datetime.now(timezone.utc),
                         ps=lambda pid: (1, ""))
        assert r["verdict"] == guard.CLAIMED

    def test_my_own_announcement_is_not_read_as_a_foreign_claim(self, guard, sibling, logger,
                                                                tracker):
        """Положительный контроль к тесту выше: своё же объявление занятостью НЕ считается.

        Пиннит вторую сторону правки `record` — «чужой ярлык ⇒ без якоря» не должно превратиться
        в «якорь не пишется никогда»: тогда сессия перестала бы узнавать саму себя и вернулся бы
        дефект `agent-self-claim-blocked-by-own-second-identity`."""
        write_card(tracker, "agent-x")
        logger.record("беру", [], "", card="agent-x")          # без session= ⇒ это я
        r = guard.gather("agent-x", log=logger._LOG, tracker_dir=tracker, sibling=sibling,
                         self_session=logger._session_id(), now=datetime.now(timezone.utc),
                         ps=lambda pid: (1, ""))
        assert r["verdict"] == guard.FREE


# ── режим автономного цикла: SPA_SESSION_PID ВЫСТАВЛЕН ───────────────────────

class TestGuardUnderADeclaredDurableProcess:
    """Защита от столкновения обязана работать в том режиме, в котором берутся карточки.

    **Почему этот класс существует** (карточка `agent-claim-guard-blind-when-session-pid-is-set`).
    Поведение инструментов зависело от переменной окружения `SPA_SESSION_PID`, которую выставляет
    `scripts/agent_orchestrator.sh` — то есть ИМЕННО тот запуск, где автономный цикл и берёт
    карточки. CI её не выставляет, поэтому на раннере эта ветка не исполнялась НИ РАЗУ: цикл #103
    намерил 4 падения на чистом `origin/main`, которых CI на том же коде не видел (1 падение).
    Дефект прожил незамеченным ровно столько, сколько «зелёный CI» означал «проверено только без
    переменной».

    Поэтому режим задаётся ВНУТРИ теста, а не окружением прогона: эти проверки идут на любом
    раннере и не могут снова стать невидимыми из-за того, как запущен pytest. Предусловие
    (якорь реально измерен) проверяется явно и при неудаче КРАСНОЕ, а не пропущенное — иначе
    это был бы fail-OPEN-скип класса #37/#39: «проверка прошла», которой не было."""

    @pytest.fixture()
    def logger(self, tmp_path, monkeypatch):
        mod = _load("_test_log_session_change_declared", "scripts/log_session_change.py")
        monkeypatch.setattr(mod, "_LOG", tmp_path / "session_changes.jsonl")
        return mod

    @pytest.fixture()
    def declared(self, monkeypatch, logger):
        """Объявить долгоживущий процесс сессии — существующий и живой прямо сейчас.

        `os.getpid()` годится по построению: этот процесс выполняется, значит `ps` его видит,
        и `durable_process` обязана вернуть измеренную пару."""
        import os
        monkeypatch.setenv("SPA_SESSION_PID", str(os.getpid()))
        monkeypatch.setenv("SPA_SESSION_ID", "cycle-under-test")
        proc, why = logger.durable_process()
        assert proc.get("session_pid") == os.getpid(), (
            "предусловие не выполнено: долгоживущий процесс не измерен "
            f"({why!r}) — без него класс ничего не проверяет, поэтому это КРАСНЫЙ, а не skip")
        return proc

    def test_a_foreign_claim_is_still_refused(self, guard, sibling, tracker, tmp_path,
                                              declared, logger):
        """Тот самый отказавший сценарий: чужой захват объявлен, я пытаюсь взять карточку.

        До правки `record` чужая запись уносила якорь ЭТОГО процесса, `self_identities`
        признавала её своей, и `claim_card` НЕ отказывал — защита от столкновения #46 была
        выключена ровно в рабочем режиме цикла."""
        write_card(tracker, "agent-x")
        log = tmp_path / "journal.jsonl"
        log.write_text("", encoding="utf-8")
        guard.claim_card("agent-x", session="pidHOLDER", tracker_dir=tracker, now=NOW,
                         sibling=sibling, log=log, ps=lambda pid: (1, ""))
        with pytest.raises(guard.ClaimError):
            guard.claim_card("agent-x", session="cycle-under-test", tracker_dir=tracker,
                             now=NOW + timedelta(minutes=5), sibling=sibling, log=log,
                             ps=lambda pid: (1, ""))

    def test_a_foreign_claim_reads_as_claimed(self, guard, sibling, tracker, tmp_path,
                                              declared, logger):
        """Шаг 0b на ту же карточку обязан отвечать `claimed`, а не `free`."""
        write_card(tracker, "agent-x")
        log = tmp_path / "journal2.jsonl"
        log.write_text("", encoding="utf-8")
        guard.claim_card("agent-x", session="pidHOLDER", tracker_dir=tracker, now=NOW,
                         sibling=sibling, log=log, ps=lambda pid: (1, ""))
        r = guard.gather("agent-x", log=log, tracker_dir=tracker, sibling=sibling,
                         self_session="cycle-under-test", now=NOW + timedelta(minutes=5),
                         ps=lambda pid: (1, ""))
        assert r["verdict"] == guard.CLAIMED

    def test_a_foreign_announcement_carries_no_anchor_of_mine(self, logger, declared, tmp_path):
        """Причина, названная по коду: запись от имени другой сессии не несёт МОЙ якорь."""
        log = tmp_path / "journal3.jsonl"
        e = logger.record("беру", [], "", card="agent-x", session="pidHOLDER", log=log)
        assert e["session"] == "pidHOLDER"
        assert "session_pid" not in e and "session_pid_start" not in e

    def test_my_own_announcement_still_carries_the_anchor(self, logger, declared, tmp_path):
        """Положительный контроль: своя запись якорь СОХРАНЯЕТ (шаг 0a им меряет активность)."""
        import os
        log = tmp_path / "journal4.jsonl"
        e = logger.record("беру", [], "", card="agent-x", log=log)
        assert e["session"] == "cycle-under-test"
        assert e["session_pid"] == os.getpid() and e["session_pid_start"]

    def test_i_can_still_take_a_card_i_hold_under_another_label(self, guard, sibling, tracker,
                                                                tmp_path, declared):
        """Контроль против перелёта в другую крайность (`agent-self-claim-blocked-by-own-second-identity`).

        Своё же объявление, сделанное ЭТИМ процессом под другим ярлыком, обязано остаться
        своим — иначе сессия начнёт отказывать сама себе, и выхода флагом у `claim` нет."""
        write_card(tracker, "agent-x")
        log = tmp_path / "journal5.jsonl"
        log.write_text("", encoding="utf-8")
        guard.claim_card("agent-x", tracker_dir=tracker, now=NOW, sibling=sibling, log=log,
                         ps=lambda pid: (1, ""))
        r = guard.gather("agent-x", log=log, tracker_dir=tracker, sibling=sibling,
                         self_session="pid-другой-ярлык-той-же-сессии",
                         now=NOW + timedelta(minutes=5), ps=lambda pid: (1, ""))
        assert r["verdict"] == guard.FREE


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


# ── старое СЛАБОЕ упоминание при НЕИЗМЕРИМОЙ активности ──────────────────────

class TestWeakMentionAgesOutEvenWhenActivityUnmeasurable:
    """Карточка `agent-weak-mention-locks-card-forever` (цикл #61).

    Докстринг инструмента объявляет обязательным: «слабый признак (упоминание в тексте)
    блокирует только пока свеж … иначе любая когда-либо тронутая карточка была бы занята
    навсегда». Ветка `state == UNKNOWN` стояла РАНЬШЕ проверки силы признака, поэтому для
    сессии с идентификатором без pid правило не работало вообще: `session_state` отдаёт
    `UNKNOWN` для такого id **детерминированно и необратимо**, старение не наступало
    никогда, и одно упоминание в свободном тексте запирало карточку навсегда.

    Так на 19+ часов выпали из очереди `agent-durable-session-id` и
    `agent-idea21-verdict-data-drift`: обе упомянуты циклом #49 (`cycle49`, id без pid)
    В ОТРИЦАНИИ — «обе НЕ беру». Циклы #50/#51/#53/#54 каждый раз фиксировали «2 не
    измерено (id cycle49 без pid)» и брали другую карточку.

    Ниже — репро, и рядом положительные контроли: fail-CLOSED для СИЛЬНЫХ признаков и
    блокировка свежего слабого упоминания сохранены.
    """

    # ── корень: почему старение не наступало никогда ──────────────────────────

    def test_pidless_session_is_unmeasurable_at_any_age(self, sibling):
        """Пин корня: возраст записи не влияет — `UNKNOWN` необратим, ждать бесполезно."""
        for age in (timedelta(minutes=1), timedelta(days=1), timedelta(days=3650)):
            state, why = sibling.session_state(
                {"session": "cycle49", "ts": _fmt(NOW - age)}, "pid1", ps=lambda pid: (1, ""))
            assert state == sibling.UNKNOWN
            assert "не содержит pid" in why

    # ── репро дефекта (красные до правки) ────────────────────────────────────

    def test_old_weak_mention_by_pidless_session_is_history_not_unchecked(
            self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-durable-session-id")
        write_log(log, [announce(
            "cycle49", NOW - timedelta(hours=18, minutes=54),
            summary=("Шаг 0b: agent-durable-session-id = ЗАНЯТА, "
                     "agent-idea21-verdict-data-drift = СТАРЫЙ ЗАХВАТ ⇒ обе НЕ беру. "
                     "Беру СВОБОДНУЮ: agent-push-batch-per-file-commits"))])
        r = run(guard, tracker, log, "agent-durable-session-id", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert guard.exit_code(r) == 0
        assert not r["unmeasured"]
        assert r["history"] and r["history"][0]["state"] == "history"
        assert r["history"][0]["strength"] == guard.WEAK

    def test_old_weak_mention_when_ps_broken_is_history_not_unchecked(
            self, guard, sibling, tracker, log, ps_broken):
        """Второй маршрут в `UNKNOWN`: id с pid есть, но сам `ps` не отработал."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(days=6),
                                 summary="раньше трогали agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_broken, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert not r["unmeasured"]

    def test_history_record_keeps_the_unmeasured_reason_verbatim(
            self, guard, sibling, tracker, log, ps_dead):
        """Не «замолчали», а «измерили и признали несущественным»: причина видна вербатим."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("cycle49", NOW - timedelta(days=2),
                                 summary="упоминали agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert "не содержит pid" in r["history"][0]["unmeasured_activity"]

    def test_both_starved_cards_become_bookable_again(
            self, guard, sibling, tracker, log, ps_dead):
        """Обе реально заблокированные карточки при ОДНОМ и том же журнале."""
        write_log(log, [
            announce("cycle49", NOW - timedelta(hours=18, minutes=54),
                     summary=("agent-durable-session-id = ЗАНЯТА, "
                              "agent-idea21-verdict-data-drift = СТАРЫЙ ЗАХВАТ ⇒ обе НЕ беру"),
                     card="agent-push-batch-per-file-commits"),
            announce("cycle49", NOW - timedelta(hours=18, minutes=5),
                     summary="ЦИКЛ #49 ЗАВЕРШЁН И ДОСТАВЛЕН",
                     card="agent-push-batch-per-file-commits", card_state="done")])
        for cid in ("agent-durable-session-id", "agent-idea21-verdict-data-drift"):
            write_card(tracker, cid)
            r = run(guard, tracker, log, cid, ps=ps_dead, sibling=sibling)
            assert r["verdict"] == guard.FREE, cid
            assert guard.exit_code(r) == 0, cid

    # ── положительные контроли: ничего не ослаблено ──────────────────────────

    def test_fresh_weak_mention_by_unmeasurable_session_no_longer_blocks(
            self, guard, sibling, tracker, log, ps_dead):
        """ИЗМЕНЁН НАМЕРЕННО (цикл #67, карточка `agent-fresh-weak-mention-deadlocks-queue`).

        Инвариант #16 — изменение объявлено явно, а не сделано молча.

        **Что этот тест утверждал раньше и почему это отменено.** Тест назывался
        `test_fresh_weak_mention_by_pidless_session_still_blocks` и пиннил осознанное
        решение цикла #61: свежее слабое упоминание блокирует. Под ним лежало допущение
        «окно свежести в 3 часа само сольётся».

        **Замер 2026-08-01 показал, что не сольётся: окно перезаряжает сам отчёт.**
        Шаг 0b обязывает называть карточки поимённо, циклы идут раз в час, окно — 3ч.
        `cycle66` (01:55Z) написал «карточку agent-verification-outlives-cycle-budget НЕ беру»,
        `cycle66i` (03:31Z) — «обе backlog-карточки ЗАНЯТЫ ⇒ НЕ беру ни одну»; каждая такая
        фраза содержит идентификатор и засчитывалась как захват. Обе оставшиеся карточки
        бэклога оказались заперты, автономная очередь встала целиком — тот же исход, против
        которого написан весь класс выше, только через свежий признак вместо старого.

        **Ассерт не ослаблен, а перенацелен на измеренную границу.** Ниже — строго более
        сильный положительный контроль: подтверждённо ЖИВАЯ сессия блокирует по слабому
        признаку по-прежнему. Плюс `TestFileOverlapStillBlocksWithoutStrongSignal` пиннит,
        что защита от сессии в обход инструмента не снята (`--files`).
        """
        write_card(tracker, "agent-x")
        write_log(log, [announce("cycle49", NOW - timedelta(minutes=30),
                                 summary="беру карточку agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert guard.exit_code(r) == 0
        assert not r["unmeasured"]
        # не «замолчали»: упоминание видно в истории вербатим
        assert r["history"] and r["history"][0]["strength"] == guard.WEAK

    def test_fresh_weak_mention_by_a_measurably_ALIVE_session_still_blocks(
            self, guard, sibling, tracker, log, ps_alive):
        """Положительный контроль взамен изменённого: живая сессия блокирует ЛЮБЫМ признаком.

        Это и есть та часть решения #61, которая имеет доказательную силу: пока процесс
        сессии реально жив, её обмолвка о карточке — повод не лезть. Она сохранена
        полностью и здесь пиннится."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid4242", NOW - timedelta(minutes=30),
                                 summary="беру карточку agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_alive, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED
        assert guard.exit_code(r) == 1
        assert r["claims"][0]["strength"] == guard.WEAK

    def test_old_strong_card_field_by_pidless_session_stays_unchecked(
            self, guard, sibling, tracker, log, ps_dead):
        """fail-CLOSED НЕ ослаблен: заявленный захват — не обмолвка в тексте."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("cycle49", NOW - timedelta(hours=9), card="agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.UNCHECKED
        assert guard.exit_code(r) == 2

    def test_old_strong_file_ownership_by_pidless_session_stays_unchecked(
            self, guard, sibling, tracker, log, ps_dead):
        """Второй сильный признак — файл карточки в объявленном владении."""
        write_card(tracker, "agent-x")
        write_log(log, [announce(
            "cycle49", NOW - timedelta(hours=9),
            files=["/repo/nimbalyst-local/tracker/agent-x.md"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.UNCHECKED

    def test_old_strong_frontmatter_claim_by_pidless_session_stays_unchecked(
            self, guard, sibling, tracker, log, ps_dead):
        """Третий сильный признак — `claimed_by` во frontmatter самой карточки."""
        write_card(tracker, "agent-x", claimed_by="cycle49",
                   claimed_at=_fmt(NOW - timedelta(hours=9)))
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.UNCHECKED

    def test_old_weak_mention_does_not_mask_a_strong_claim_in_the_same_log(
            self, guard, sibling, tracker, log, ps_dead):
        """Состаренное слабое не «съедает» находку: сильный захват рядом остаётся."""
        write_card(tracker, "agent-x")
        write_log(log, [
            announce("cycle49", NOW - timedelta(days=2), summary="упоминали agent-x"),
            announce("pid999", NOW - timedelta(minutes=20), card="agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED
        assert any(c["strength"] == guard.STRONG for c in r["claims"])

    def test_old_weak_mention_does_not_suppress_file_overlap(
            self, guard, sibling, tracker, log, ps_dead):
        """Пересечение по файлам — независимое измерение, оно не зависит от старения."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("cycle49", NOW - timedelta(minutes=20),
                                 summary="работаю",
                                 files=["/repo/scripts/check_card_claim.py"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead,
                planned_files=["/repo/scripts/check_card_claim.py"], sibling=sibling)
        assert r["overlaps"]


# ── СВЕЖЕЕ слабое упоминание: окно свежести перезаряжает сам отчёт ───────────

class TestFreshWeakMentionDoesNotDeadlockTheQueue:
    """Карточка `agent-fresh-weak-mention-deadlocks-queue` (цикл #67, замер 2026-08-01).

    Цикл #61 состарил СТАРОЕ слабое упоминание и осознанно оставил свежее блокирующим —
    под допущением «окно в 3 часа само сольётся». Замер показал обратное: **окно
    перезаряжает сам отчёт**. Шаг 0b обязывает называть карточки поимённо, циклы идут раз
    в час, окно — 3ч, поэтому каждый честный доклад «карточка X занята, не беру» продлевает
    замок ещё на 3 часа. 01.08 так встала ВСЯ автономная очередь: обе (и единственные)
    оставшиеся карточки бэклога читались как занятые.

    Ниже — репро живого дедлока дословно по `data/session_changes.jsonl` и положительные
    контроли того, что fail-CLOSED не ослаблен ни в одном сильном пути.
    """

    # ── репро (красное до правки) ────────────────────────────────────────────

    def test_report_that_a_card_is_taken_does_not_itself_take_it(
            self, guard, sibling, tracker, log, ps_dead):
        """Ядро дефекта: фраза «карточку X НЕ беру» засчитывалась как захват X."""
        write_card(tracker, "agent-verification-outlives-cycle-budget")
        write_log(log, [announce(
            "cycle66i", NOW - timedelta(hours=1, minutes=9),
            summary=("Обе backlog-карточки ЗАНЯТЫ (agent-idea21-verdict-data-drift — cycle66, "
                     "свежее окно; agent-verification-outlives-cycle-budget — cycle65, работа "
                     "осиротела) ⇒ по шагу 0b НЕ беру ни одну. Прод-код не трогаю."))])
        r = run(guard, tracker, log, "agent-verification-outlives-cycle-budget",
                ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert guard.exit_code(r) == 0
        assert r["history"] and r["history"][0]["strength"] == guard.WEAK

    def test_the_live_deadlock_of_2026_08_01_is_gone(
            self, guard, sibling, tracker, log, ps_dead):
        """Живой журнал 01.08: два отчёта подряд заперли ОБЕ карточки бэклога.

        Здесь воспроизведён именно каскад: `cycle66` докладывает об одной карточке и берёт
        другую, `cycle66i` докладывает об ОБЕИХ. До правки — `claimed` на обеих, брать
        нечего. Настоящий захват в этом же журнале (`cycle66` взяла idea21 полем `card:`)
        обязан продолжать блокировать — он и блокирует, но уже как СИЛЬНЫЙ признак."""
        entries = [
            announce("cycle66", NOW - timedelta(hours=2, minutes=49),
                     summary=("Карточку agent-verification-outlives-cycle-budget НЕ беру: "
                              "шаг 0b даёт claimed => беру следующую. "
                              "Беру agent-idea21-verdict-data-drift."),
                     card="agent-idea21-verdict-data-drift"),
            announce("cycle66i", NOW - timedelta(hours=1, minutes=9),
                     summary=("Обе backlog-карточки ЗАНЯТЫ "
                              "(agent-idea21-verdict-data-drift, "
                              "agent-verification-outlives-cycle-budget) ⇒ НЕ беру ни одну.")),
        ]
        write_log(log, entries)

        # карточка, которую НИКТО не захватывал — только называли в отчётах
        write_card(tracker, "agent-verification-outlives-cycle-budget")
        r = run(guard, tracker, log, "agent-verification-outlives-cycle-budget",
                ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE, "отчёт о занятости не должен запирать карточку"

        # карточка с НАСТОЯЩИМ свежим захватом (поле `card:`) — по-прежнему занята
        write_card(tracker, "agent-idea21-verdict-data-drift")
        r2 = run(guard, tracker, log, "agent-idea21-verdict-data-drift",
                 ps=ps_dead, sibling=sibling)
        assert r2["verdict"] == guard.CLAIMED
        assert any(c["strength"] == guard.STRONG for c in r2["claims"])

    def test_stale_strong_claim_is_not_masked_by_a_fresh_weak_mention(
            self, guard, sibling, tracker, log, ps_dead):
        """Точный вердикт осиротевшей работы: `stale`, а не `claimed` и не `free`.

        Это и есть цена дефекта: `stale` означает «кандидат на ручной подъём» (шаг 0a),
        а свежая обмолвка перекрывала его в `claimed` — «не трогай», из-за чего сирота
        оставалась лежать.

        Идентификатор захватчика взят pid-образным намеренно: только тогда активность
        ИЗМЕРИМА и старый сильный захват даёт `stale`. У id без pid тот же случай честно
        остаётся `unchecked` (код 2) — это отдельный контроль
        `test_old_strong_signal_with_unmeasurable_activity_stays_unchecked`, и правка #67
        его не касается."""
        write_card(tracker, "agent-x")
        write_log(log, [
            announce("pid29435", NOW - timedelta(hours=4, minutes=19), card="agent-x"),
            announce("cycle66i", NOW - timedelta(hours=1), summary="agent-x занята, не беру"),
        ])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.STALE
        assert guard.exit_code(r) == 1

    # ── положительные контроли: fail-CLOSED не ослаблен ──────────────────────

    def test_fresh_strong_card_field_still_blocks(
            self, guard, sibling, tracker, log, ps_dead):
        """Свежий СИЛЬНЫЙ признак — поведение не изменилось ни на бит."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("cycle99", NOW - timedelta(minutes=30), card="agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED

    def test_fresh_strong_file_ownership_still_blocks(
            self, guard, sibling, tracker, log, ps_dead):
        """Второй сильный признак — файл карточки в объявленном владении."""
        write_card(tracker, "agent-x")
        write_log(log, [announce(
            "cycle99", NOW - timedelta(minutes=30),
            files=["/repo/nimbalyst-local/tracker/agent-x.md"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED

    def test_fresh_frontmatter_claim_still_blocks(
            self, guard, sibling, tracker, log, ps_dead):
        """Третий сильный признак — `claimed_by` в самой карточке."""
        write_card(tracker, "agent-x", claimed_by="cycle99",
                   claimed_at=_fmt(NOW - timedelta(minutes=30)))
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED

    def test_old_strong_signal_with_unmeasurable_activity_stays_unchecked(
            self, guard, sibling, tracker, log, ps_dead):
        """fail-CLOSED на сильном признаке не тронут: «не измерено» (код 2), не «свободна»."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("cycle49", NOW - timedelta(hours=9), card="agent-x")])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.UNCHECKED
        assert guard.exit_code(r) == 2


class TestFileOverlapStillBlocksWithoutStrongSignal:
    """Настоящая защита от сессии, работающей в обход инструмента, — НЕ снята.

    Остаточный риск правки #67 назван прямо: сессия, которая взяла карточку без `claim`,
    и назвала её только в прозе, теперь читается как `free`. Смягчение — это измерение:
    работая над карточкой, сессия объявляет владение файлами, а пересечение по файлам
    даёт `claimed` независимо от силы признака по самой карточке."""

    def test_fresh_file_overlap_blocks_even_when_the_card_signal_is_only_weak(
            self, guard, sibling, tracker, log, ps_dead):
        write_card(tracker, "agent-x")
        write_log(log, [announce(
            "cycle49", NOW - timedelta(minutes=20),
            summary="ковыряю agent-x",
            files=["/repo/scripts/check_card_claim.py"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead,
                planned_files=["/repo/scripts/check_card_claim.py"], sibling=sibling)
        assert r["verdict"] == guard.CLAIMED
        assert guard.exit_code(r) == 1
        assert r["overlaps"]

    def test_mention_without_file_overlap_is_free(
            self, guard, sibling, tracker, log, ps_dead):
        """Граница измерена с обеих сторон: без пересечения файлов — свободна."""
        write_card(tracker, "agent-x")
        write_log(log, [announce(
            "cycle49", NOW - timedelta(minutes=20),
            summary="ковыряю agent-x",
            files=["/repo/docs/STATE.md"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead,
                planned_files=["/repo/scripts/check_card_claim.py"], sibling=sibling)
        assert r["verdict"] == guard.FREE


# ── личность сессии = измерение, а не ярлык (agent-self-claim-blocked-by-own-second-identity) ──

MY_ANCHOR = (41721, "Sat Aug  1 13:37:28 2026")


def anchored(entry, anchor):
    """Дописать в запись журнала поля долгоживущего процесса (как это делает
    `log_session_change.durable_process` — только после подтверждения процесса)."""
    e = dict(entry)
    if anchor is not None:
        e["session_pid"], e["session_pid_start"] = anchor[0], anchor[1]
    return e


class TestSelfIdentityByDurableProcess:
    """Ярлык сессии нестабилен, её долгоживущий процесс — нет.

    **Дефект** (карточка `agent-self-claim-blocked-by-own-second-identity`; догфуд цикла #67,
    независимо воспроизведён циклом #70). Без `SPA_SESSION_ID` идентификатор в журнале — pid
    ОДНОКРАТНОЙ CLI-команды, поэтому у каждой команды одной сессии он свой, а «своей»
    признавалась ровно одна строка (`session == self_session`). Следствия, замеренные дословно:
    `claim --session cycle67` отказывал по захвату `pid72203` (это тоже я), `claim --session
    pid72203` — по захвату `cycle67` (и это я); круговая блокировка без выхода (`claim` не
    имеет `--force`). Двух объявлений даже не требуется: штатная пара `claim` … `release`, ту
    самую предписывает протокол, — это две команды, то есть два ярлыка (цикл #70: взял
    `pid15267`, снять пытался `pid17106`).

    **Опознание — по измерению.** Пара (`session_pid`, `session_pid_start`) пишется только
    после подтверждения процесса, а время старта отличает процесс от переиспользованного
    номера. Совпал якорь ⇒ записи написаны одним процессом ⇒ ярлыки мои.

    Каждая проверка ниже идёт с положительным контролем: чужой якорь, тот же pid с другим
    стартом, запись без якоря и половина якоря — блокируют как прежде.
    """

    # ── чистая арифметика якоря ──────────────────────────────────────────────
    def test_anchor_needs_both_pid_and_start(self, guard):
        assert guard.anchor_of({"session_pid": 7, "session_pid_start": "S"}) == (7, "S")
        # половина якоря — не якорь: pid без времени старта переиспользуется ОС
        assert guard.anchor_of({"session_pid": 7}) is None
        assert guard.anchor_of({"session_pid_start": "S"}) is None
        assert guard.anchor_of({"session_pid": 7, "session_pid_start": "   "}) is None

    def test_anchor_rejects_non_process_pids(self, guard):
        assert guard.anchor_of({"session_pid": "7", "session_pid_start": "S"}) == (7, "S")
        assert guard.anchor_of({"session_pid": True, "session_pid_start": "S"}) is None
        assert guard.anchor_of({"session_pid": 1, "session_pid_start": "S"}) is None
        assert guard.anchor_of({"session_pid": "не число", "session_pid_start": "S"}) is None
        assert guard.anchor_of("не запись") is None

    def test_identities_without_anchor_are_just_the_label(self, guard):
        rows = [anchored(announce("pid100", NOW), MY_ANCHOR)]
        assert guard.self_identities(rows, "cycle72", None) == {"cycle72"}

    def test_identities_collect_labels_sharing_the_anchor(self, guard):
        rows = [anchored(announce("pid100", NOW), MY_ANCHOR),
                anchored(announce("pid101", NOW), MY_ANCHOR),
                anchored(announce("чужая", NOW), (999, "другой старт")),
                announce("без якоря", NOW)]
        assert guard.self_identities(rows, "cycle72", MY_ANCHOR) == {
            "cycle72", "pid100", "pid101"}

    # ── захват карточки ──────────────────────────────────────────────────────
    def test_my_own_second_label_is_not_a_claim(self, guard, sibling, tracker, log, ps_dead):
        """Главный случай карточки: моё же объявление под другим ярлыком не блокирует меня."""
        write_card(tracker, "agent-x")
        write_log(log, [anchored(announce("pid100", NOW - timedelta(minutes=5),
                                          card="agent-x"), MY_ANCHOR)])
        r = run(guard, tracker, log, "agent-x", session="cycle72", ps=ps_dead,
                sibling=sibling, self_anchor=MY_ANCHOR)
        assert r["verdict"] == guard.FREE and guard.exit_code(r) == 0
        assert r["claims"] == [] and r["self_claims"]
        assert r["self_sessions"] == ["cycle72", "pid100"]

    def test_the_same_case_blocks_without_the_anchor(self, guard, sibling, tracker, log,
                                                     ps_dead):
        """Тот же вход БЕЗ якоря — прежнее (дефектное) поведение. Анти-тавтология: без этого
        первый тест был бы зелёным и на нечиненом коде."""
        write_card(tracker, "agent-x")
        write_log(log, [anchored(announce("pid100", NOW - timedelta(minutes=5),
                                          card="agent-x"), MY_ANCHOR)])
        r = run(guard, tracker, log, "agent-x", session="cycle72", ps=ps_dead,
                sibling=sibling, self_anchor=None)
        # ПРАВЛЕНО ЦИКЛОМ #238 НАМЕРЕННО (инв. #16, обоснование — здесь и в журнале
        # W33). Вход не менялся ни на байт; изменился ОЖИДАЕМЫЙ вердикт, потому что
        # держатель здесь объявил долгоживущий процесс, а `ps` отвечает «его нет» —
        # то есть смерть ИЗМЕРЕНА, и ждать конца окна свежести некого
        # (`TestOrphanedClaimDoesNotBlockTheRescue`). CLAIMED → STALE: оба ненулевые,
        # оба «молча не бери», разница — «занято» против «кандидат на ручной подъём».
        # Проверка УСИЛЕНА, а не ослаблена: предмет этого теста — опознание личности,
        # и он теперь утверждается прямо (захват чужой: `claims` непуст, `self_claims`
        # пуст) плюс ненулевой код возврата, чего тест не проверял вовсе.
        # Анти-тавтология цела и стала острее: с якорем — FREE (это я), без якоря — НЕ FREE.
        assert r["verdict"] == guard.STALE and r["verdict"] != guard.FREE
        assert r["claims"] and r["self_claims"] == [] and guard.exit_code(r) == 1

    def test_foreign_session_with_its_own_anchor_still_blocks(self, guard, sibling, tracker,
                                                              log, ps_dead):
        """Положительный контроль: чужой процесс — чужой захват (коллизия #46 не ослаблена)."""
        write_card(tracker, "agent-x")
        write_log(log, [anchored(announce("cycle71", NOW - timedelta(minutes=5),
                                          card="agent-x"), (999, "Fri Jul 31 10:00:00 2026"))])
        r = run(guard, tracker, log, "agent-x", session="cycle72", ps=ps_dead,
                sibling=sibling, self_anchor=MY_ANCHOR)
        # ПРАВЛЕНО ЦИКЛОМ #238 НАМЕРЕННО (инв. #16, обоснование — здесь и в журнале
        # W33). Вход не менялся ни на байт; изменился ОЖИДАЕМЫЙ вердикт, потому что
        # держатель здесь объявил долгоживущий процесс, а `ps` отвечает «его нет» —
        # то есть смерть ИЗМЕРЕНА, и ждать конца окна свежести некого
        # (`TestOrphanedClaimDoesNotBlockTheRescue`). CLAIMED → STALE: оба ненулевые,
        # оба «молча не бери», разница — «занято» против «кандидат на ручной подъём».
        # Проверка УСИЛЕНА, а не ослаблена: предмет этого теста — опознание личности,
        # и он теперь утверждается прямо (захват чужой: `claims` непуст, `self_claims`
        # пуст) плюс ненулевой код возврата, чего тест не проверял вовсе.
        assert r["verdict"] == guard.STALE
        assert r["claims"] and r["self_claims"] == [] and guard.exit_code(r) == 1
        # Само же «чужой ЖИВОЙ держатель блокирует» (коллизия #46) — рядом, тем же входом:
        alive = run(guard, tracker, log, "agent-x", session="cycle72",
                    ps=lambda pid: (0, "Fri Jul 31 10:00:00 2026\n"),
                    sibling=sibling, self_anchor=MY_ANCHOR)
        assert alive["verdict"] == guard.CLAIMED and alive["self_claims"] == []

    def test_recycled_pid_is_not_me(self, guard, sibling, tracker, log, ps_dead):
        """Положительный контроль: ТОТ ЖЕ pid с другим временем старта — другой процесс.
        Без времени старта опознание вырождалось бы в «совпал номер» — ровно fail-OPEN."""
        write_card(tracker, "agent-x")
        write_log(log, [anchored(announce("pid100", NOW - timedelta(minutes=5), card="agent-x"),
                                 (MY_ANCHOR[0], "Thu Jul 30 09:00:00 2026"))])
        r = run(guard, tracker, log, "agent-x", session="cycle72", ps=ps_dead,
                sibling=sibling, self_anchor=MY_ANCHOR)
        # ПРАВЛЕНО ЦИКЛОМ #238 НАМЕРЕННО (инв. #16, обоснование — здесь и в журнале
        # W33). Вход не менялся ни на байт; изменился ОЖИДАЕМЫЙ вердикт, потому что
        # держатель здесь объявил долгоживущий процесс, а `ps` отвечает «его нет» —
        # то есть смерть ИЗМЕРЕНА, и ждать конца окна свежести некого
        # (`TestOrphanedClaimDoesNotBlockTheRescue`). CLAIMED → STALE: оба ненулевые,
        # оба «молча не бери», разница — «занято» против «кандидат на ручной подъём».
        # Проверка УСИЛЕНА, а не ослаблена: предмет этого теста — опознание личности,
        # и он теперь утверждается прямо (захват чужой: `claims` непуст, `self_claims`
        # пуст) плюс ненулевой код возврата, чего тест не проверял вовсе.
        assert r["verdict"] == guard.STALE
        assert r["claims"] and r["self_claims"] == [] and guard.exit_code(r) == 1

    def test_entry_without_an_anchor_is_never_absorbed(self, guard, sibling, tracker, log,
                                                       ps_dead):
        """Положительный контроль: запись без долгоживущего процесса остаётся чужой.
        Так ведёт себя ВЕСЬ существующий журнал — старое поведение сохранено байт-в-байт."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid100", NOW - timedelta(minutes=5), card="agent-x")])
        r = run(guard, tracker, log, "agent-x", session="cycle72", ps=ps_dead,
                sibling=sibling, self_anchor=MY_ANCHOR)
        assert r["verdict"] == guard.CLAIMED and r["claims"]

    def test_half_an_anchor_does_not_absorb(self, guard, sibling, tracker, log, ps_dead):
        """Положительный контроль: `session_pid` без `session_pid_start` — не личность."""
        write_card(tracker, "agent-x")
        e = announce("pid100", NOW - timedelta(minutes=5), card="agent-x")
        e["session_pid"] = MY_ANCHOR[0]
        write_log(log, [e])
        r = run(guard, tracker, log, "agent-x", session="cycle72", ps=ps_dead,
                sibling=sibling, self_anchor=MY_ANCHOR)
        # ПРАВЛЕНО ЦИКЛОМ #238 НАМЕРЕННО (инв. #16, обоснование — здесь и в журнале
        # W33). Вход не менялся ни на байт; изменился ОЖИДАЕМЫЙ вердикт, потому что
        # держатель здесь объявил долгоживущий процесс, а `ps` отвечает «его нет» —
        # то есть смерть ИЗМЕРЕНА, и ждать конца окна свежести некого
        # (`TestOrphanedClaimDoesNotBlockTheRescue`). CLAIMED → STALE: оба ненулевые,
        # оба «молча не бери», разница — «занято» против «кандидат на ручной подъём».
        # Проверка УСИЛЕНА, а не ослаблена: предмет этого теста — опознание личности,
        # и он теперь утверждается прямо (захват чужой: `claims` непуст, `self_claims`
        # пуст) плюс ненулевой код возврата, чего тест не проверял вовсе.
        # Отдельно: половина якоря НЕ личность (предмет теста), но объявленным процессом
        # она считается — `session_pid` есть, `ps` говорит «нет» ⇒ смерть измерена. Это не
        # выбор шага 0b: определение смерти ОДНО на оба шага (`durable_process_gone` соседа),
        # и заводить здесь своё означало бы ровно того третьего близнеца, из-за которого
        # чинилось всё остальное.
        assert r["verdict"] == guard.STALE
        assert r["claims"] and r["self_claims"] == [] and guard.exit_code(r) == 1

    def test_frontmatter_claim_by_my_other_label_is_mine(self, guard, sibling, tracker, log,
                                                         ps_dead):
        """Захват в самой карточке тоже опознаётся: `claim` пишет туда ярлык той команды."""
        write_card(tracker, "agent-x", claimed_by="pid100",
                   claimed_at=_fmt(NOW - timedelta(minutes=5)))
        write_log(log, [anchored(announce("pid100", NOW - timedelta(minutes=6),
                                          card="agent-x"), MY_ANCHOR)])
        r = run(guard, tracker, log, "agent-x", session="cycle72", ps=ps_dead,
                sibling=sibling, self_anchor=MY_ANCHOR)
        assert r["verdict"] == guard.FREE
        assert [c["source"] for c in r["self_claims"]].count("frontmatter") == 1

    # ── пересечение по файлам ────────────────────────────────────────────────
    def test_my_other_label_does_not_overlap_with_me(self, guard, sibling, tracker, log,
                                                     ps_dead):
        """Одно измерение — один ответ: иначе собственное объявление, не блокируя как захват,
        блокировало бы как пересечение по файлам (дефект, починенный наполовину)."""
        write_card(tracker, "agent-x")
        write_log(log, [anchored(announce("pid100", NOW - timedelta(minutes=10),
                                          files=["/repo/scripts/check_card_claim.py"]),
                                 MY_ANCHOR)])
        r = run(guard, tracker, log, "agent-x", session="cycle72", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/scripts/check_card_claim.py"], self_anchor=MY_ANCHOR)
        assert r["overlaps"] == [] and r["verdict"] == guard.FREE

    def test_foreign_overlap_still_blocks(self, guard, sibling, tracker, log, ps_dead):
        """Положительный контроль к предыдущему: чужие файлы держат карточку как прежде."""
        write_card(tracker, "agent-x")
        write_log(log, [anchored(announce("cycle71", NOW - timedelta(minutes=10),
                                          files=["/repo/scripts/check_card_claim.py"]),
                                 (999, "Fri Jul 31 10:00:00 2026"))])
        r = run(guard, tracker, log, "agent-x", session="cycle72", ps=ps_dead, sibling=sibling,
                planned_files=["/repo/scripts/check_card_claim.py"], self_anchor=MY_ANCHOR)
        # ПРАВЛЕНО ЦИКЛОМ #238 НАМЕРЕННО (инв. #16, обоснование — здесь и в журнале W33). Вход
        # не менялся; изменился ожидаемый вердикт: держатель файлов объявил долгоживущий
        # процесс, и `ps` отвечает «его нет». Предмет теста — «чужое пересечение не считается
        # моим» — проверяется прямо и остаётся в силе: пересечение НАЗВАНО, просто помечено
        # осиротевшим (недоставленная работа мёртвой сессии лежит ровно в этих файлах — это
        # домен шага 0a, а не «занято»).
        assert r["verdict"] == guard.STALE and r["overlaps"]
        assert r["overlaps"][0]["session"] == "cycle71" and r["overlaps"][0]["orphaned"] is True
        # Живой держатель тех же файлов блокирует как прежде — контроль рядом, тем же входом:
        alive = run(guard, tracker, log, "agent-x", session="cycle72",
                    ps=lambda pid: (0, "Fri Jul 31 10:00:00 2026\n"), sibling=sibling,
                    planned_files=["/repo/scripts/check_card_claim.py"],
                    self_anchor=MY_ANCHOR)
        assert alive["verdict"] == guard.CLAIMED and alive["overlaps"]

    # ── claim / release одной и той же сессией ───────────────────────────────
    def test_claim_takes_over_from_my_other_label(self, guard, sibling, tracker, log):
        """Сквозной случай #67: карточку держит мой прежний ярлык — беру, а не отказываю."""
        write_card(tracker, "agent-x", claimed_by="pid100",
                   claimed_at=_fmt(NOW - timedelta(minutes=5)))
        write_log(log, [anchored(announce("pid100", NOW - timedelta(minutes=5),
                                          card="agent-x"), MY_ANCHOR)])
        res = guard.claim_card("agent-x", session="cycle72", tracker_dir=tracker, now=NOW,
                               sibling=sibling, log=log, ps=lambda pid: (1, ""),
                               self_anchor=MY_ANCHOR)
        assert res["claimed_by"] == "cycle72"
        assert guard.frontmatter((tracker / "agent-x.md").read_text(
            encoding="utf-8"))["claimed_by"] == "cycle72"

    def test_claim_still_refuses_a_foreign_holder(self, guard, sibling, tracker, log):
        """Положительный контроль: чужой захват не перезаписывается и с якорем."""
        write_card(tracker, "agent-x", claimed_by="cycle71",
                   claimed_at=_fmt(NOW - timedelta(minutes=5)))
        write_log(log, [anchored(announce("cycle71", NOW - timedelta(minutes=5),
                                          card="agent-x"), (999, "Fri Jul 31 10:00:00 2026"))])
        with pytest.raises(guard.ClaimError):
            guard.claim_card("agent-x", session="cycle72", tracker_dir=tracker, now=NOW,
                             sibling=sibling, log=log, ps=lambda pid: (1, ""),
                             self_anchor=MY_ANCHOR)

    def test_release_recognises_the_claim_of_my_other_label(self, guard, sibling, tracker, log):
        """Сквозной случай #70: взял одной командой (`pid15267`), снимаю другой (`pid17106`).
        Раньше здесь был отказ «снять чужой захват можно только с --force»."""
        p = write_card(tracker, "agent-x")
        before = p.read_text(encoding="utf-8")
        guard.claim_card("agent-x", session="pid15267", tracker_dir=tracker, now=NOW,
                         sibling=sibling, log=log, ps=lambda pid: (1, ""),
                         self_anchor=MY_ANCHOR)
        # тот же процесс, следующая команда — другой ярлык
        write_log(log, [anchored(announce("pid15267", NOW - timedelta(minutes=1),
                                          card="agent-x"), MY_ANCHOR)])
        res = guard.release_card("agent-x", session="pid17106", tracker_dir=tracker, log=log,
                                 sibling=sibling, self_anchor=MY_ANCHOR)
        assert res["released"] and res["was"] == "pid15267"
        assert p.read_text(encoding="utf-8") == before

    def test_release_still_refuses_a_foreign_claim(self, guard, sibling, tracker, log):
        """Положительный контроль: `--force` НЕ обесценен — чужой захват по-прежнему держит."""
        write_card(tracker, "agent-x", claimed_by="cycle71", claimed_at=_fmt(NOW))
        write_log(log, [anchored(announce("cycle71", NOW - timedelta(minutes=1),
                                          card="agent-x"), (999, "Fri Jul 31 10:00:00 2026"))])
        with pytest.raises(guard.ClaimError):
            guard.release_card("agent-x", session="cycle72", tracker_dir=tracker, log=log,
                               sibling=sibling, self_anchor=MY_ANCHOR)

    def test_release_without_an_anchor_does_not_read_the_log(self, guard, tracker, log):
        """Нет якоря ⇒ журнал не читается ВООБЩЕ и поведение ровно прежнее: опознавать нечем,
        а лишнее чтение общего файла сделало бы `release` зависящим от чужих записей.

        Журнал здесь СУЩЕСТВУЕТ (фикстура `log` создаёт файл) — иначе `_log_entries` вышел бы
        на проверке существования и подставной читатель не вызывался бы никогда: первая версия
        этого теста проходила и с убранным коротким замыканием, то есть не проверяла ничего."""
        write_card(tracker, "agent-x", claimed_by="pid999", claimed_at=_fmt(NOW))
        write_log(log, [announce("pid999", NOW - timedelta(minutes=1), card="agent-x")])

        def _explode(*a, **k):
            raise AssertionError("журнал прочитан, хотя якоря нет")

        with pytest.raises(guard.ClaimError):
            guard.release_card("agent-x", session="pid1", tracker_dir=tracker, log=log,
                               sibling=type("S", (), {"read_entries": staticmethod(_explode)}),
                               self_anchor=None)

    # ── измерение своего якоря из окружения ──────────────────────────────────
    def test_measure_self_anchor_uses_the_announcer(self, guard):
        """Меряет ТОТ ЖЕ код, что пишет якорь в журнал, — близнеца арифметики нет."""
        ok = type("A", (), {"durable_process": staticmethod(
            lambda env=None: ({"session_pid": 7, "session_pid_start": "S"}, ""))})
        assert guard.measure_self_anchor(announcer=ok) == (7, "S")

    def test_measure_self_anchor_is_none_when_the_process_is_not_confirmed(self, guard):
        """Не подтверждён процесс ⇒ якоря нет ⇒ поведение прежнее (никакого «наверное, я»)."""
        no = type("A", (), {"durable_process": staticmethod(lambda env=None: ({}, "нет pid"))})
        assert guard.measure_self_anchor(announcer=no) is None

    def test_measure_self_anchor_survives_a_broken_announcer(self, guard):
        """Модуль-объявитель не загрузился — это не падение шага 0b, а отсутствие якоря."""
        bad = type("A", (), {"durable_process": staticmethod(
            lambda env=None: (_ for _ in ()).throw(OSError("нет файла")))})
        assert guard.measure_self_anchor(announcer=bad) is None

    def test_render_names_the_other_labels(self, guard, sibling, tracker, log, ps_dead):
        """Опознание чужого ЯРЛЫКА как своего видно в отчёте — не молчаливая поблажка."""
        write_card(tracker, "agent-x")
        write_log(log, [anchored(announce("pid100", NOW - timedelta(minutes=5),
                                          card="agent-x"), MY_ANCHOR)])
        text = guard.render(run(guard, tracker, log, "agent-x", session="cycle72", ps=ps_dead,
                                sibling=sibling, self_anchor=MY_ANCHOR))
        assert "pid100" in text and "долгоживущего процесса" in text


# ── ждать некого: держатель объявил долгоживущий процесс, и его больше нет ────

DEAD_ANCHOR = (31748, "Sat Aug 15 05:44:00 2026")


@pytest.fixture()
def ps_alive_matching():
    """`ps` показывает ИМЕННО тот процесс, что записан в якоре ⇒ активность ПОДТВЕРЖДЕНА.

    Нужен как положительный контроль к починке #238: «мёртвый держатель не блокирует» обязано
    доказываться рядом с «живой держатель блокирует по-прежнему», иначе первое неотличимо от
    общего ослабления сторожа.
    """
    return lambda pid: (0, DEAD_ANCHOR[1] + "\n")


class TestOrphanedClaimDoesNotBlockTheRescue:
    """Свежий сильный захват сессии, чья смерть ИЗМЕРЕНА, — не занятость, а кандидат на подъём.

    **Дефект** (карточка `agent-dead-pid-still-holds-files-for-3h`, замер цикла #238 15.08
    04:0xZ). Шаг 0a получил циклом #233 узкое основание не ждать — `durable_process_gone`:
    сессия САМА объявила долгоживущий процесс (`session_pid` + `session_pid_start`), и его
    больше нет. Шаг 0b переиспользует у соседа `session_state`, но `durable_process_gone` не
    звал ни разу ⇒ знание о смерти доезжало до ТЕКСТА отчёта и не доезжало до ВЕРДИКТА:

        ⛔ ЗАНЯТА — держит другая сессия. НЕ бери эту карточку, возьми следующую.
          - [свежий] cycle-237 (2026-08-15T02:55:29Z, 1.08ч назад) — поле `card:`
              активность: долгоживущий процесс сессии pid31748 завершился

    Обе строки — один отчёт; про ту же сессию в ту же минуту шаг 0a говорил обратное
    («🕳 осиротело, но окно не истекло»). Цена: подъём осиротевшей работы запрещался ЧЕТЫРЕ
    цикла подряд (#231→#232, #236, #237, #238 — три захвата одной карточки, все три мертвы),
    и каждый раз запрет перебивали руками. Сторож, блокирующий верное действие, учит себя
    игнорировать.

    Граница узкая намеренно и проверяется в ОБЕ стороны: живой процесс блокирует как прежде,
    запись без объявленного процесса блокирует как прежде («`ps` не нашёл pid» смертью не
    считается — в журнале лежит pid однократной CLI-команды), «не измерено» остаётся кодом 2.
    """

    def _log_with_claim(self, log, *, anchor, session="cycle-237", minutes=65):
        write_log(log, [anchored(announce(session, NOW - timedelta(minutes=minutes),
                                          card="agent-x", summary="работа осиротела"), anchor)])

    def test_orphaned_fresh_claim_is_stale_not_claimed(self, guard, sibling, tracker, log,
                                                       ps_dead):
        """Главный случай: свежий захват + измеренная смерть ⇒ STALE (кандидат на подъём)."""
        write_card(tracker, "agent-x")
        self._log_with_claim(log, anchor=DEAD_ANCHOR)
        r = run(guard, tracker, log, "agent-x", session="cycle-238", ps=ps_dead,
                sibling=sibling)
        assert r["verdict"] == guard.STALE, r["verdict"]
        assert guard.exit_code(r) == 1          # не «свободна»: рc остаётся ненулевым
        assert r["claims"] and r["claims"][0]["state"] == "stale"
        assert r["claims"][0]["orphaned"] is True and r["claims"][0]["fresh"] is True

    def test_the_same_claim_blocks_while_the_process_is_ALIVE(self, guard, sibling, tracker,
                                                              log, ps_alive_matching):
        """Положительный контроль: тот же вход, но процесс жив ⇒ ЗАНЯТА, как прежде."""
        write_card(tracker, "agent-x")
        self._log_with_claim(log, anchor=DEAD_ANCHOR)
        r = run(guard, tracker, log, "agent-x", session="cycle-238", ps=ps_alive_matching,
                sibling=sibling)
        assert r["verdict"] == guard.CLAIMED and guard.exit_code(r) == 1
        # Поле читается через `.get`: этот тест — ОБРАТНЫЙ контроль, он обязан быть зелёным
        # и на нечиненом коде, иначе «блокировка не ослаблена» доказывалась бы наличием
        # нового ключа, а не поведением.
        assert r["claims"][0]["state"] == "fresh"
        assert r["claims"][0].get("orphaned", False) is False

    def test_entry_without_a_declared_process_blocks_as_before(self, guard, sibling, tracker,
                                                               log, ps_dead):
        """Контроль на весь СУЩЕСТВУЮЩИЙ журнал: нет объявленного процесса ⇒ поведение прежнее.

        `ps` здесь отвечает «процесса нет», и это НЕ смерть: `session` в журнале — pid
        однократной CLI-команды, мёртвый всегда. Расширь условие сюда — и сторож перестанет
        блокировать вообще что-либо.
        """
        write_card(tracker, "agent-x")
        write_log(log, [announce("cycle-237", NOW - timedelta(minutes=65), card="agent-x")])
        r = run(guard, tracker, log, "agent-x", session="cycle-238", ps=ps_dead,
                sibling=sibling)
        assert r["verdict"] == guard.CLAIMED
        assert r["claims"][0].get("orphaned", False) is False

    def test_unmeasurable_process_is_not_death(self, guard, sibling, tracker, log, ps_broken):
        """`ps` не отработал ⇒ UNKNOWN ⇒ не осиротело. «Не измерено» смертью не объявляем."""
        write_card(tracker, "agent-x")
        self._log_with_claim(log, anchor=DEAD_ANCHOR)
        r = run(guard, tracker, log, "agent-x", session="cycle-238", ps=ps_broken,
                sibling=sibling)
        assert r["verdict"] == guard.CLAIMED
        assert r["claims"][0].get("orphaned", False) is False

    def test_frontmatter_holder_measured_dead_is_stale(self, guard, sibling, tracker, log,
                                                       ps_dead):
        """Личность держателя карточки берётся из журнала (`durable_by_session`) — и смерть тоже."""
        write_card(tracker, "agent-x", claimed_by="cycle-237",
                   claimed_at=_fmt(NOW - timedelta(minutes=40)))
        self._log_with_claim(log, anchor=DEAD_ANCHOR)
        r = run(guard, tracker, log, "agent-x", session="cycle-238", ps=ps_dead,
                sibling=sibling)
        assert r["verdict"] == guard.STALE
        assert {c["source"] for c in r["claims"]} == {"frontmatter", "announce-log"}
        assert all(c["orphaned"] for c in r["claims"])

    def test_orphaned_file_overlap_does_not_block_but_is_NAMED(self, guard, sibling, tracker,
                                                              log, ps_dead):
        """Второй путь блокировки — пересечение по файлам — мерил ТОЛЬКО возраст.

        Он же и запирал подъём: недоставленная работа мёртвой сессии лежит ровно в тех файлах,
        которые собирается править спасатель. Исчезать из отчёта пересечение не имеет права —
        меняется вердикт, а не видимость.
        """
        write_card(tracker, "agent-x")
        write_log(log, [anchored(announce("cycle-237", NOW - timedelta(minutes=65),
                                          files=["/repo/scripts/consume_office_reports.py"],
                                          summary="работа осиротела"), DEAD_ANCHOR)])
        r = run(guard, tracker, log, "agent-x", session="cycle-238", ps=ps_dead,
                sibling=sibling,
                planned_files=["/repo/scripts/consume_office_reports.py"])
        assert r["verdict"] == guard.STALE
        assert len(r["overlaps"]) == 1 and r["overlaps"][0]["orphaned"] is True
        text = guard.render(r)
        assert "ждать некого" in text and "шаг 0a" in text

    def test_live_file_overlap_still_blocks(self, guard, sibling, tracker, log,
                                            ps_alive_matching):
        """Положительный контроль к предыдущему: живая сессия держит файлы как прежде."""
        write_card(tracker, "agent-x")
        write_log(log, [anchored(announce("cycle-237", NOW - timedelta(minutes=65),
                                          files=["/repo/scripts/consume_office_reports.py"],
                                          summary="работа идёт"), DEAD_ANCHOR)])
        r = run(guard, tracker, log, "agent-x", session="cycle-238", ps=ps_alive_matching,
                sibling=sibling,
                planned_files=["/repo/scripts/consume_office_reports.py"])
        assert r["verdict"] == guard.CLAIMED
        assert r["overlaps"][0].get("orphaned", False) is False
        assert "ждать некого" not in guard.render(r)

    def test_report_says_why_the_freshness_window_stopped_applying(self, guard, sibling,
                                                                   tracker, log, ps_dead):
        """Вердикт без основания — это «поверь на слово»: причина печатается словами."""
        write_card(tracker, "agent-x")
        self._log_with_claim(log, anchor=DEAD_ANCHOR)
        text = guard.render(run(guard, tracker, log, "agent-x", session="cycle-238",
                                ps=ps_dead, sibling=sibling))
        assert "[осиротел]" in text
        assert "окно свежести не действует: ждать некого" in text
        assert "вручную" in text.lower()      # порядок подъёма прежний, авто-захвата нет

    def test_the_real_15_08_case_three_dead_holders(self, guard, sibling, tracker, log,
                                                    ps_dead):
        """Положительный контроль-репортаж: ровно тот вход, что измерен в проде 15.08.

        Три захвата одной карточки (`cycle-74937` 52ч, `cycle-8889` 2.5ч, `cycle-237` 1.1ч),
        у всех трёх объявленный долгоживущий процесс завершился. Старый код: ⛔ ЗАНЯТА.
        """
        write_card(tracker, "inbox-shag-0-ofis", status="new")
        write_log(log, [
            anchored(announce("cycle-74937", NOW - timedelta(hours=52),
                              card="inbox-shag-0-ofis"), (74937, "Wed Aug 12 20:00:00 2026")),
            anchored(announce("cycle-8889", NOW - timedelta(hours=2, minutes=28),
                              card="inbox-shag-0-ofis"), (8875, "Sat Aug 15 03:00:00 2026")),
            anchored(announce("cycle-237", NOW - timedelta(hours=1, minutes=5),
                              card="inbox-shag-0-ofis"), DEAD_ANCHOR)])
        r = run(guard, tracker, log, "inbox-shag-0-ofis", session="cycle-238", ps=ps_dead,
                sibling=sibling)
        assert r["verdict"] == guard.STALE
        assert len(r["claims"]) == 3 and all(c["state"] == "stale" for c in r["claims"])
        assert "НЕ бери эту карточку" not in guard.render(r)


# ── явное поле `card:` главнее косвенного признака (цикл #262) ────────────────
#
# Карточка `agent-card-file-in-ownership-locks-a-card-it-doesnt-claim`. Протокол ОБЯЗЫВАЕТ
# дописывать в чужие карточки (подъём осиротевшей работы, «независимое подтверждение»,
# ссылки §6.4), а каждая дописка делала файл карточки СИЛЬНЫМ признаком её захвата.

class TestExplicitCardFieldBeatsTheCardFile:
    def test_card_file_does_not_claim_when_the_entry_names_another_card(
            self, guard, sibling, tracker, log, ps_dead):
        """Ядро правки: запись машинно называет ДРУГУЮ карточку ⇒ моя не захвачена."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=30),
                                 card="agent-other",
                                 files=["/repo/nimbalyst-local/tracker/agent-x.md"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert not r["claims"]

    def test_the_signal_is_named_not_erased(self, guard, sibling, tracker, log, ps_dead):
        """Находка не имеет права ИСЧЕЗНУТЬ: она уходит в историю и называет причину."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=30),
                                 card="agent-other",
                                 files=["/repo/nimbalyst-local/tracker/agent-x.md"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        hist = [h for h in r["history"] if h["session"] == "pid999"]
        assert hist and hist[0]["strength"] == guard.WEAK
        assert "agent-other" in hist[0]["detail"]
        assert "файл карточки объявлен во владении" in hist[0]["detail"]

    def test_entry_without_card_field_still_blocks(self, guard, sibling, tracker, log, ps_dead):
        """Обратный контроль №1: записи БЕЗ поля `card:` правка не касается вовсе."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=30),
                                 files=["/repo/nimbalyst-local/tracker/agent-x.md"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED         # свежий СИЛЬНЫЙ захват — как и раньше
        assert r["claims"][0]["strength"] == guard.STRONG

    def test_card_field_naming_this_card_still_blocks(self, guard, sibling, tracker, log,
                                                      ps_dead):
        """Обратный контроль №2: `card:` на ЭТУ карточку — сильнее прежнего не стало, но и
        слабее не стало."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=30), card="agent-x",
                                 files=["/repo/nimbalyst-local/tracker/agent-x.md"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED
        assert r["claims"][0]["strength"] == guard.STRONG

    def test_a_live_session_editing_my_card_file_still_blocks(self, guard, sibling, tracker,
                                                              log, ps_alive):
        """Сужение НЕ распространяется на живую сессию: сосед, который прямо сейчас правит
        файл моей карточки, — настоящий конфликт по файлу. Та же политика, что у слабого
        упоминания в тексте (`test_text_mention_blocks_only_while_the_session_is_alive`)."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=30), card="agent-other",
                                 files=["/repo/nimbalyst-local/tracker/agent-x.md"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_alive, sibling=sibling)
        assert r["verdict"] == guard.CLAIMED

    def test_declared_files_overlap_still_blocks(self, guard, sibling, tracker, log, ps_alive):
        """Обратный контроль №3: главная защита от двойной работы — пересечение по `--files`
        — не затронута; файл карточки в ней участвует наравне с любым другим."""
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=30), card="agent-other",
                                 files=["/repo/nimbalyst-local/tracker/agent-x.md"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_alive, sibling=sibling,
                planned_files=["/repo/nimbalyst-local/tracker/agent-x.md"])
        assert r["verdict"] == guard.CLAIMED and r["overlaps"]

    def test_the_real_329h_lock_of_cycle91(self, guard, sibling, tracker, log, ps_dead):
        """Положительный контроль-репортаж: ровно тот вход, что измерен в проде 16.08.

        Цикл #91 взял `agent-signal-aggregator-…`, а в мою карточку лишь дописал раздел —
        и она читалась как захваченная 329 часов. Снятие (`card_state: done`) ушло по полю
        `card:` на ТУ ЖЕ другую карточку, поэтому замок не снимался никогда: старый код
        отвечал `stale` (код 1) о карточке, которую никто не держит.
        """
        cid = "agent-card-file-in-ownership-locks-a-card-it-doesnt-claim"
        other = "agent-signal-aggregator-tier-tests-red-after-blindness-fix"
        write_card(tracker, cid)
        files = [f"/tmp/spa_wt_c91/nimbalyst-local/tracker/{other}.md",
                 f"/tmp/spa_wt_c91/nimbalyst-local/tracker/{cid}.md",
                 "/tmp/spa_wt_c91/docs/STATE.md"]
        write_log(log, [
            announce("pid64251", NOW - timedelta(hours=329), card=other, files=files),
            announce("pid24392", NOW - timedelta(hours=329) + timedelta(minutes=16),
                     card=other, card_state="done", files=files)])
        r = run(guard, tracker, log, cid, ps=ps_dead, sibling=sibling)
        assert r["verdict"] == guard.FREE
        assert guard.exit_code(r) == 0


# ── хвост «каталог/имя» больше не путает два каталога тестов (цикл #262) ──────

class TestRepoRelativeOverlap:
    def test_two_test_dirs_are_not_the_same_file(self, guard, tmp_path):
        """Замер #91: `tests/x.py` и `spa_core/tests/x.py` — РАЗНЫЕ файлы, а хвост у них один.
        В репо 35 таких хвостов на 72 файла (замер 16.08), это правило, а не исключение."""
        for rel in ("tests/test_signal_aggregator.py", "spa_core/tests/test_signal_aggregator.py"):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")
        assert not guard.paths_overlap("/tmp/wt_a/tests/test_signal_aggregator.py",
                                       "/tmp/wt_b/spa_core/tests/test_signal_aggregator.py",
                                       tmp_path)

    def test_same_file_from_two_worktrees_still_overlaps(self, guard, tmp_path):
        """Обратный контроль: ровно ради этого случая хвост и вводился."""
        p = tmp_path / "spa_core/tests/test_x.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        assert guard.paths_overlap("/tmp/wt_a/spa_core/tests/test_x.py",
                                   "/tmp/wt_b/spa_core/tests/test_x.py", tmp_path)

    def test_unresolvable_path_keeps_the_old_behaviour(self, guard, tmp_path):
        """Обратный контроль: если хоть один путь в репо не разрешается — прежнее правило
        (вплоть до хвоста). Непонятность не покупается тишиной."""
        assert guard.paths_overlap("/tmp/wt_a/workflows/ci.yml",
                                   "/tmp/wt_b/workflows/ci.yml", tmp_path)
        assert not guard.paths_overlap("/a/one/__init__.py", "/b/two/__init__.py", tmp_path)

    def test_longest_existing_tail_wins(self, guard, tmp_path):
        """У `…/spa_core/tests/x.py` существуют ОБА хвоста — берётся длинный, иначе файл
        разрешился бы в своего однофамильца из другого каталога."""
        for rel in ("tests/x.py", "spa_core/tests/x.py"):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")
        assert guard.repo_relative("/tmp/wt/spa_core/tests/x.py", tmp_path) == "spa_core/tests/x.py"
        assert guard.repo_relative("/tmp/wt/tests/x.py", tmp_path) == "tests/x.py"
        assert guard.repo_relative("/tmp/wt/nope/y.py", tmp_path) is None

    def test_overlap_of_namesakes_does_not_block_the_report(self, guard, sibling, tracker,
                                                            log, ps_alive, tmp_path):
        """Сквозная проверка ЭФФЕКТА: сессия объявила `tests/x.py`, я планирую
        `spa_core/tests/x.py` — карточка остаётся свободной."""
        for rel in ("tests/x.py", "spa_core/tests/x.py"):
            p = tmp_path / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("x", encoding="utf-8")
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=20),
                                 files=["/tmp/wt_a/tests/x.py"])])
        r = guard.gather("agent-x", log=log, tracker_dir=tracker, sibling=sibling,
                         self_session="pid1", now=NOW, grace_hours=3.0,
                         planned_files=["/tmp/wt_b/spa_core/tests/x.py"], ps=ps_alive,
                         self_anchor=None, repo_root=tmp_path)
        assert r["verdict"] == guard.FREE and not r["overlaps"]

    def test_the_same_file_from_two_roots_still_blocks_end_to_end(self, guard, sibling, tracker,
                                                                  log, ps_alive, tmp_path):
        """Обратный контроль к предыдущему: тот же файл из двух корней по-прежнему ЗАНЯТА."""
        p = tmp_path / "spa_core/tests/x.py"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=20),
                                 files=["/tmp/wt_a/spa_core/tests/x.py"])])
        r = guard.gather("agent-x", log=log, tracker_dir=tracker, sibling=sibling,
                         self_session="pid1", now=NOW, grace_hours=3.0,
                         planned_files=["/tmp/wt_b/spa_core/tests/x.py"], ps=ps_alive,
                         self_anchor=None, repo_root=tmp_path)
        assert r["verdict"] == guard.CLAIMED and r["overlaps"]

    def test_namesake_collision_on_the_REAL_repo(self, guard, sibling, tracker, log, ps_alive):
        """Якорь на ПОВЕДЕНИИ, а не на сигнатуре: тот же вход через умолчание `repo_root`.

        Оба файла реально лежат в репозитории и это РАЗНЫЕ файлы. На неисправленном коде хвост
        «каталог/имя» объявляет их одним, и карточка читается как ⛔ ЗАНЯТА; после правки —
        ✅ СВОБОДНА. Если один из файлов когда-нибудь исчезнет, тест скажет об этом вслух,
        а не позеленеет молча."""
        root = Path(guard.ROOT)
        a, b = root / "tests/conftest.py", root / "spa_core/tests/conftest.py"
        assert a.is_file() and b.is_file(), (
            f"условие замера пропало: {a} / {b} — тест не про них, а про КОЛЛИЗИЮ хвоста; "
            "выбрать другую живую пару одноимённых файлов из двух каталогов")
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=20),
                                 files=[f"/tmp/wt_a/{a.relative_to(root).as_posix()}"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_alive, sibling=sibling,
                planned_files=[f"/tmp/wt_b/{b.relative_to(root).as_posix()}"])
        assert r["verdict"] == guard.FREE and not r["overlaps"]

    def test_the_same_real_file_from_two_roots_still_blocks(self, guard, sibling, tracker, log,
                                                            ps_alive):
        """Обратный контроль к нему же, тоже на умолчании: ОДИН и тот же файл из двух корней
        по-прежнему ⛔ ЗАНЯТА. Зелёный и до правки, и после — это и есть его роль."""
        rel = "spa_core/tests/conftest.py"
        assert (Path(guard.ROOT) / rel).is_file()
        write_card(tracker, "agent-x")
        write_log(log, [announce("pid999", NOW - timedelta(minutes=20),
                                 files=[f"/tmp/wt_a/{rel}"])])
        r = run(guard, tracker, log, "agent-x", ps=ps_alive, sibling=sibling,
                planned_files=[f"/tmp/wt_b/{rel}"])
        assert r["verdict"] == guard.CLAIMED and r["overlaps"]


# ── одно определение личности на оба шага протокола (цикл #265) ──────────────

class TestIdentityHasOneDefinition:
    """`anchor_of` / `durable_by_session` переехали к шагу 0a — здесь только делегирование.

    **Зачем переезд** (карточка `inbox-shag-0a-ne-sprashivaet-zhurnal-o-lichnos`). Тот же
    вопрос — «чей это процесс и жив ли он» — понадобился шагу 0a: запись без своей пары
    (`session_pid`, `session_pid_start`) уходила у него в необратимое «не измерено», хотя
    личность лежала соседней записью того же журнала. Копировать разбор во второй файл было
    нельзя (копии расходятся молча), а зависимость односторонняя: `check_card_claim` грузит
    соседа, не наоборот, — значит определение обязано жить у соседа.

    Тесты ниже — гейт против возврата второй копии: они краснеют, если делегирование заменят
    собственным разбором, который разойдётся с соседним хотя бы на одном входе.
    """

    _CASES = (
        {"session_pid": 7, "session_pid_start": "S"},
        {"session_pid": "7", "session_pid_start": "S"},
        {"session_pid": 7},
        {"session_pid_start": "S"},
        {"session_pid": 7, "session_pid_start": "   "},
        {"session_pid": True, "session_pid_start": "S"},
        {"session_pid": 1, "session_pid_start": "S"},
        {"session_pid": "не число", "session_pid_start": "S"},
        "не запись",
    )

    def test_anchor_of_answers_exactly_what_the_sibling_answers(self, guard, sibling):
        mine = [guard.anchor_of(c) for c in self._CASES]
        theirs = [sibling.anchor_of(c) for c in self._CASES]
        assert mine == theirs
        assert mine[0] == (7, "S") and mine[2] is None     # ответ не «оба None на всём»

    def test_durable_by_session_answers_exactly_what_the_sibling_answers(self, guard, sibling):
        rows = [{"session": "a", "session_pid": 5, "session_pid_start": "S"},
                {"session": "b", "session_pid": 6, "session_pid_start": "S"},
                {"session": "b", "session_pid": 7, "session_pid_start": "S"},   # неоднозначно
                {"session": "c"}]
        assert guard.durable_by_session(rows, sibling) == sibling.durable_by_session(rows)
        assert set(guard.durable_by_session(rows, sibling)) == {"a"}

    def test_the_parser_is_not_duplicated_in_this_file(self, guard):
        """Проводка, а не вкус: разбор `session_pid` не должен вернуться сюда второй копией."""
        src = (Path(guard.__file__).read_text(encoding="utf-8")
               if getattr(guard, "__file__", None)
               else (ROOT / "scripts/check_card_claim.py").read_text(encoding="utf-8"))
        assert "isinstance(raw, str) and raw.strip().isdigit()" not in src


class TestClaimSaysWhenItHasNoIdentity:
    """Захват без личности процесса неизмерим НАВСЕГДА — поэтому он НЕ СОСТОИТСЯ (цикл #387).

    Заимствование личности на стороне читателя (`check_undelivered_work.borrow_durable`)
    спасает запись лишь тогда, когда якорь у ЯРЛЫКА есть хоть где-то в журнале. Живой замер
    16.08: у ярлыка `cycle-263` его нет нигде — такой захват шаг 0a не измерит никогда.

    **ИЗМЕНЕНИЕ ПОВЕДЕНИЯ, НАМЕРЕННОЕ (инвариант #16, журнал W35, цикл #387).** Цикл #263
    назвал класс верно и выбрал ПРЕДУПРЕЖДЕНИЕ на stderr: `claim` брал карточку и печатал
    совет выставить `SPA_SESSION_PID`. Предупреждение не удержало. 26.08 сессия #386 взяла
    карточку под ярлыком `cycle-386` без объявленного долгоживущего процесса, через сорок
    минут умерла, не доставив ничего, — и карточка с настоящей недоставленной работой стала
    НЕБЕРУЩЕЙСЯ: шаг 0a печатал «работу надо поднять», шаг 0b в ту же минуту — `⛔ ЗАНЯТА`,
    а `--takeover` отказывал (подъём разрешён только на `stale`). Время не лечит:
    `session_state` для ярлыка без pid отдаёт `UNKNOWN` необратимо, так что по истечении окна
    вердикт уходит в `unchecked`, где подъём запрещён так же.

    Поэтому два теста ниже ПЕРЕПИСАНЫ с «предупреждает и берёт» на «отказывает и не берёт».
    Оба обратных контроля (`test_claim_reports_a_measured_anchor`,
    `test_cli_is_silent_when_the_anchor_is_there`) оставлены как были и остались зелёными —
    проверка не ослаблена, а ужесточена: отказ проверяется ещё и по тому, что ни карточка, ни
    журнал не тронуты.
    """

    def test_claim_without_a_measurable_identity_is_refused(self, guard, sibling, tracker, log):
        """Отказ, а не совет: неизмеримый захват запирает карточку навсегда."""
        card = write_card(tracker, "agent-x")
        before = card.read_text(encoding="utf-8")
        with pytest.raises(guard.UnmeasurableClaim) as exc:
            guard.claim_card("agent-x", session="cycle-386", tracker_dir=tracker, now=NOW,
                             sibling=sibling, log=log, ps=lambda pid: (1, ""),
                             self_anchor=None)
        assert "SPA_SESSION_PID" in str(exc.value) and "cycle-386" in str(exc.value)
        assert card.read_text(encoding="utf-8") == before, "карточку трогать нельзя"

    def test_the_refused_claim_leaves_no_trace_in_the_shared_log(self, guard, sibling, tracker,
                                                                 log):
        """Порядок отказа: ДО объявления. Иначе в общем журнале осталась бы запись «держу»
        о карточке, которой сессия не владеет, — ровно то состояние, которое чинит
        `_unannounce_claim`, только без единого способа его заметить."""
        write_card(tracker, "agent-x")
        with pytest.raises(guard.UnmeasurableClaim):
            guard.claim_card("agent-x", session="cycle-386", tracker_dir=tracker, now=NOW,
                             sibling=sibling, log=log, ps=lambda pid: (1, ""),
                             self_anchor=None)
        assert log.read_text(encoding="utf-8").strip() == ""

    def test_the_refusal_is_a_claim_error_so_callers_keep_handling_it(self, guard):
        """`UnmeasurableClaim` — подвид `ClaimError`: вызывающие, ловившие отказ захвата,
        продолжают его ловить, и новый исход не проливается мимо их обработчиков."""
        assert issubclass(guard.UnmeasurableClaim, guard.ClaimError)

    def test_claim_reports_a_measured_anchor(self, guard, sibling, tracker, log):
        """Обратный контроль: якорь назван ⇒ предупреждения быть не должно."""
        write_card(tracker, "agent-x")
        res = guard.claim_card("agent-x", session="pid1", tracker_dir=tracker, now=NOW,
                               sibling=sibling, log=log, ps=lambda pid: (1, ""),
                               self_anchor=(4242, "Wed Jan 14 10:00:00 2026"))
        assert res["anchored"] is True

    def test_cli_refuses_with_code_2_when_the_claim_carries_no_identity(self, guard, tracker,
                                                                        log, capsys,
                                                                        monkeypatch):
        """Код возврата 2 — «не измерено», а не 1 («занято»): та же семантика, что у вердикта
        `unchecked`, и цикл-обёртка отличает одно от другого без разбора текста."""
        monkeypatch.delenv("SPA_SESSION_PID", raising=False)
        card = write_card(tracker, "agent-x")
        rc = guard.main(["--tracker-dir", str(tracker), "--log", str(log),
                         "claim", "agent-x", "--session", "cycle-263"])
        captured = capsys.readouterr()
        assert rc == 2
        assert "взята: agent-x" not in captured.out
        assert "SPA_SESSION_PID" in captured.out and "cycle-263" in captured.out
        assert "claimed_by" not in card.read_text(encoding="utf-8")

    def test_cli_is_silent_when_the_anchor_is_there(self, guard, tracker, log, capsys,
                                                    monkeypatch):
        """Обратный контроль: под выставленным `SPA_SESSION_PID` предупреждения нет."""
        import os as _os
        monkeypatch.setenv("SPA_SESSION_PID", str(_os.getpid()))
        write_card(tracker, "agent-y")
        rc = guard.main(["--tracker-dir", str(tracker), "--log", str(log),
                         "claim", "agent-y", "--session", "cycle-265"])
        captured = capsys.readouterr()
        assert rc == 0 and "БЕЗ личности процесса" not in captured.err
