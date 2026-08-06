"""Тесты моста «находка → карточка → закрытие» (ADR-066 C2,
`spa_core/monitoring/findings_bridge_c125.py`).

ВНИМАНИЕ: модуль переименован 06.08 после столкновения двух независимых реализаций
Фазы 3 за одну ночь — канонические имена остались за РАЗВЁРНУТОЙ версией
(`com.spa.decision_loop`). Проверки не менялись, изменён только путь импорта.

Приёмка карточки фазы 3 сформулирована так: **искусственная находка проходит путь
находка→карточка→закрытие без рук**. Последний тест в этом файле исполняет ровно это
end-to-end — через НАСТОЯЩИЙ `orchestrator_queue.py` во временном трекере; остальные
проверяют дисциплину против спама поштучно.

Каждый тест — положительный контроль конкретного отказа, который мост обязан не
допустить: спам одинаковыми карточками, карточка на мигнувшую находку, наводнение
очереди за сутки, тихое обрезание отложенного, и — самое опасное — закрытие карточек
из-за ТОГО, ЧТО СТОРОЖ ЗАМОЛЧАЛ.

Время — вход (`now`), пути — во временный каталог: ни один тест не трогает живую
очередь и живые data/*.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path

import pytest

BRIDGE_PATH = (Path(__file__).resolve().parents[1] / "monitoring"
               / "findings_bridge_c125.py")
_spec = importlib.util.spec_from_file_location("findings_bridge_c125", BRIDGE_PATH)
B = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(B)

NOW = dt.datetime(2026, 8, 5, 12, 0, tzinfo=dt.timezone.utc)


def iso(hours_ago: float = 0.0) -> str:
    return (NOW - dt.timedelta(hours=hours_ago)).isoformat()


def finding(key, severity="WARN", cls="strong", check="B1", msg=None, first_seen=None):
    return {"key": key, "check": check, "severity": severity, "class": cls,
            "message": msg or f"находка {key}", "first_seen": first_seen or iso(1)}


def report(findings, src_generated_h=1.0, overall="WARN"):
    return {"generated_at": iso(src_generated_h), "overall": overall, "findings": findings}


def write_source(root: Path, src: str, doc):
    path = root / B.SOURCES[src]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


class FakeQueue:
    """Заглушка CLI очереди: записывает вызовы, выдаёт правдоподобные пути карточек."""

    def __init__(self, tracker: Path, fail=False):
        self.tracker = tracker
        self.calls: list[list[str]] = []
        self.notified: list[str] = []
        self.fail = fail
        self._n = 0

    def run(self, args):
        self.calls.append(args)
        if self.fail:
            return 1, "", "queue упал"
        if args[0] == "create":
            self._n += 1
            p = self.tracker / f"card-{self._n}.md"
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("---\ntrackerStatus:\n  type: agent-task\nstatus: backlog\n---\n\nтело\n",
                         encoding="utf-8")
            return 0, str(p), ""
        return 0, "OK", ""

    def notify(self, path):
        self.notified.append(path)
        return 0, "OK", ""


@pytest.fixture()
def root(tmp_path):
    (tmp_path / "data").mkdir(parents=True, exist_ok=True)
    return tmp_path


def run_bridge(root, q, *, apply=True, now=NOW, **kw):
    return B.run(str(root), now, apply=apply, runner=q.run, notifier=q.notify, **kw)


def created_paths(q):
    return [str(p) for p in sorted(q.tracker.glob("card-*.md"))]


def created_titles(q):
    out = []
    for args in q.calls:
        if args and args[0] == "create":
            out.append(args[args.index("--title") + 1])
    return out


# ── гистерезис: мигнувшая находка карточку не заводит ────────────────────────

def test_first_sighting_does_not_create_a_card(root):
    """Находка, увиденная ОДИН раз, карточки не получает: сторож мог мигнуть.
    Это и есть гистерезис, требуемый ADR-066 C2."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("B1:dead:com.spa.x")]))
    rep = run_bridge(root, q)
    assert rep["counts"]["opened"] == 0
    assert rep["counts"]["pending"] == 1
    assert "1 из 2" in rep["pending"][0]["reason"]
    assert created_titles(q) == []


def test_second_sighting_creates_exactly_one_card(root):
    """Подтвердилась вторым прогоном — карточка заводится. Ровно одна."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("B1:dead:com.spa.x")]))
    run_bridge(root, q)
    rep = run_bridge(root, q, now=NOW + dt.timedelta(hours=6))
    assert rep["counts"]["opened"] == 1
    assert len(created_titles(q)) == 1


def test_repeated_finding_never_creates_a_second_card(root):
    """Dedup: сторож повторяет находку каждые 6 часов — очередь не растёт."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("B1:dead:com.spa.x")]))
    for i in range(6):
        run_bridge(root, q, now=NOW + dt.timedelta(hours=6 * i))
    assert len(created_titles(q)) == 1


def test_critical_gets_a_card_on_first_sighting(root):
    """CRITICAL ждать подтверждения не может — это капитал-релевантно."""
    q = FakeQueue(root / "tracker")
    write_source(root, "hvg", report([finding("G2:held_red:maple", severity="CRITICAL",
                                              check="G2")], overall="CRITICAL"))
    rep = run_bridge(root, q)
    assert rep["counts"]["opened"] == 1


def test_escalation_reopens_even_when_card_is_open(root):
    """WARN→CRITICAL — новое событие, а не повтор: владелец обязан узнать."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("B1:x")]))
    run_bridge(root, q)
    run_bridge(root, q, now=NOW + dt.timedelta(hours=6))       # карточка заведена
    write_source(root, "arch", report([finding("B1:x", severity="CRITICAL")]))
    rep = run_bridge(root, q, now=NOW + dt.timedelta(hours=12))
    assert rep["counts"]["opened"] == 1
    assert "эскалация WARN→CRITICAL" in rep["planned_open"][0]["reason"]


# ── маршрутизация ────────────────────────────────────────────────────────────

def test_critical_routes_to_owner_card_and_notifies(root):
    """CRITICAL → owner-decision/needs-owner + Telegram (ADR-066 C2)."""
    q = FakeQueue(root / "tracker")
    write_source(root, "hvg", report([finding("G2:held_red:maple", severity="CRITICAL")],
                                     overall="CRITICAL"))
    run_bridge(root, q)
    create = next(a for a in q.calls if a[0] == "create")
    assert create[create.index("--type") + 1] == "owner-decision"
    assert create[create.index("--status") + 1] == "needs-owner"
    assert len(q.notified) == 1


def test_owner_card_body_has_the_four_mandatory_sections(root):
    """Инвариант #15: у карточки владельцу ровно эти четыре заголовка, по-русски."""
    body = B.owner_body(finding("G2:held_red:maple", severity="CRITICAL"), {})
    for head in ("## Что случилось и почему это важно", "## Что от тебя нужно",
                 "## Как понять, что готово", "## Что будет после"):
        assert head in body


def test_card_title_is_russian_and_bounded():
    """Заголовок карточки владельцу — по-русски (инвариант #15) и не бесконечный."""
    long = finding("G1:x", msg="о" * 400)
    title = B.card_title(long)
    assert title.startswith("Находка сторожа:")
    assert len(title) <= 110


def test_warn_routes_to_agent_backlog_without_notify(root):
    """Не-CRITICAL не дёргает владельца — уходит в agent-бэклог молча (но видимо)."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("B1:x")]))
    run_bridge(root, q)
    run_bridge(root, q, now=NOW + dt.timedelta(hours=6))
    create = next(a for a in q.calls if a[0] == "create")
    assert create[create.index("--type") + 1] == "agent-task"
    assert create[create.index("--status") + 1] == "backlog"
    assert q.notified == []


def test_weak_findings_never_become_cards(root):
    """Живой факт: все четыре удерживаемых протокола имеют жёлтый сигнал. Карточки на
    них — спам; но и молчания нет: они перечислены в отчёте моста."""
    q = FakeQueue(root / "tracker")
    write_source(root, "hvg", report([finding(f"G2:held_warn:{p}", cls="weak")
                                      for p in ("pendle", "maple", "aave_v3")]))
    rep = run_bridge(root, q)
    rep = run_bridge(root, q, now=NOW + dt.timedelta(hours=6))
    assert rep["counts"]["opened"] == 0
    assert rep["counts"]["not_carded"] == 3
    assert {f["key"] for f in rep["not_carded"]} == {
        "hvg/G2:held_warn:pendle", "hvg/G2:held_warn:maple", "hvg/G2:held_warn:aave_v3"}


# ── rate-limit: наводнение очереди за сутки ──────────────────────────────────

def test_rate_limit_defers_the_excess_by_name(root):
    """Семь подтверждённых находок за один прогон → 5 карточек, 2 ОТЛОЖЕНЫ и названы.
    Молчаливое обрезание здесь запрещено: отложенное читается в отчёте."""
    q = FakeQueue(root / "tracker")
    fs = [finding(f"B1:dead:com.spa.a{i}") for i in range(7)]
    write_source(root, "arch", report(fs))
    run_bridge(root, q)
    rep = run_bridge(root, q, now=NOW + dt.timedelta(hours=6))
    assert rep["counts"]["opened"] == 5
    assert rep["counts"]["deferred"] == 2
    assert all("отложено: суточный лимит 5" in f["reason"] for f in rep["deferred"])
    assert len({f["key"] for f in rep["deferred"]}) == 2


def test_deferred_finding_is_opened_the_next_day(root):
    """Отложенное не теряется: сутки прошли — бюджет освободился."""
    q = FakeQueue(root / "tracker")
    fs = [finding(f"B1:dead:com.spa.a{i}") for i in range(7)]
    write_source(root, "arch", report(fs))
    run_bridge(root, q)
    run_bridge(root, q, now=NOW + dt.timedelta(hours=6))
    rep = run_bridge(root, q, now=NOW + dt.timedelta(hours=31))
    assert rep["counts"]["opened"] == 2
    assert rep["counts"]["deferred"] == 0


def test_critical_outranks_warn_in_the_daily_budget(root):
    """Когда бюджет мал, первым уезжает капитал-релевантное."""
    q = FakeQueue(root / "tracker")
    fs = [finding(f"B1:w{i}") for i in range(5)] + [finding("G2:held_red:maple",
                                                            severity="CRITICAL")]
    write_source(root, "arch", report(fs))
    rep = run_bridge(root, q, max_per_day=1)
    assert [f["key"] for f in rep["opened"]] == ["arch/G2:held_red:maple"]


# ── авто-закрытие и его fail-CLOSED граница ──────────────────────────────────

def test_vanished_finding_closes_the_card_with_evidence(root):
    """Находка исчезла из СВЕЖЕГО отчёта — карточка закрывается сама, со ссылкой
    на прогон, в котором её уже не было."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("B1:x")]))
    run_bridge(root, q)
    run_bridge(root, q, now=NOW + dt.timedelta(hours=6))
    card = Path(created_paths(q)[0])

    write_source(root, "arch", report([], overall="OK"))
    rep = run_bridge(root, q, now=NOW + dt.timedelta(hours=12))
    assert rep["counts"]["closed"] == 1
    assert ["set-status", str(card), "done"] in q.calls
    assert "Закрыто автоматически" in card.read_text(encoding="utf-8")


def test_silent_watchdog_closes_nothing(root):
    """САМЫЙ опасный отказ: отчёт сторожа пропал. Отсутствие отчёта ≠ отсутствие
    находки — иначе сломанный сторож «чинил» бы очередь, и мы бы закрыли карточки
    про живые проблемы."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("B1:x")]))
    run_bridge(root, q)
    run_bridge(root, q, now=NOW + dt.timedelta(hours=6))
    (root / B.SOURCES["arch"]).unlink()

    rep = run_bridge(root, q, now=NOW + dt.timedelta(hours=12))
    assert rep["counts"]["closed"] == 0
    assert rep["sources"]["arch"]["readable"] is False
    assert not any(a[0] == "set-status" for a in q.calls)


def test_stale_report_closes_nothing(root):
    """Сторож не падал, но замолчал: отчёт старше окна — тоже не закрывает."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("B1:x")]))
    run_bridge(root, q)
    run_bridge(root, q, now=NOW + dt.timedelta(hours=6))
    write_source(root, "arch", report([], src_generated_h=B.SOURCE_MAX_AGE_H + 5))
    rep = run_bridge(root, q, now=NOW + dt.timedelta(hours=12))
    assert rep["counts"]["closed"] == 0
    assert "протух" in rep["sources"]["arch"]["reason"]


def test_report_without_timestamp_is_not_readable(root):
    """Отчёт без generated_at — свежесть НЕ ИЗМЕРЕНА, источник не считается прочитанным."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", {"overall": "OK", "findings": []})
    rep = run_bridge(root, q)
    assert rep["sources"]["arch"]["readable"] is False


def test_closed_finding_cannot_resurrect_before_cooldown(root):
    """Мигающая находка (то есть, то нет) не должна выдавать карточку за прогон."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("B1:x")]))
    run_bridge(root, q)
    run_bridge(root, q, now=NOW + dt.timedelta(hours=6))
    write_source(root, "arch", report([], overall="OK"))
    run_bridge(root, q, now=NOW + dt.timedelta(hours=12))       # закрыли
    write_source(root, "arch", report([finding("B1:x")]))
    rep = run_bridge(root, q, now=NOW + dt.timedelta(hours=13))  # вернулась через час
    assert rep["counts"]["opened"] == 0
    assert "гистерезис" in rep["suppressed"][0]["reason"]


def test_finding_returning_after_cooldown_opens_again(root):
    """Устаревание подавления: настоящий рецидив спустя сутки обязан быть услышан."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("B1:x")]))
    run_bridge(root, q)
    run_bridge(root, q, now=NOW + dt.timedelta(hours=6))
    write_source(root, "arch", report([], overall="OK"))
    run_bridge(root, q, now=NOW + dt.timedelta(hours=12))
    write_source(root, "arch", report([finding("B1:x")]))
    run_bridge(root, q, now=NOW + dt.timedelta(hours=40))
    rep = run_bridge(root, q, now=NOW + dt.timedelta(hours=46))
    assert rep["counts"]["opened"] == 1


# ── fail-safe и состояние ────────────────────────────────────────────────────

def test_without_apply_nothing_is_mutated(root):
    """Без --apply мост не смеет тронуть ни очередь, ни состояние: случайный запуск
    не наводняет трекер."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("B1:x", severity="CRITICAL")]))
    rep = B.run(str(root), NOW, apply=False, runner=q.run, notifier=q.notify)
    assert q.calls == []
    assert rep["applied"] is False
    assert rep["counts"]["planned_open"] == 1
    assert not (root / B.STATE_REL).exists()


def test_queue_failure_is_reported_not_swallowed(root):
    """Если очередь отказала — карточки нет, и об этом написано. Состояние не
    объявляет карточку открытой (иначе находка исчезла бы из виду навсегда)."""
    q = FakeQueue(root / "tracker", fail=True)
    write_source(root, "arch", report([finding("B1:x", severity="CRITICAL")]))
    rep = run_bridge(root, q)
    assert rep["counts"]["opened"] == 1          # попытка учтена
    assert rep["opened"][0]["error"].startswith("create rc=1")
    state = json.loads((root / B.STATE_REL).read_text(encoding="utf-8"))
    assert state["entries"]["arch/B1:x"]["status"] != "open"


def test_corrupt_state_is_not_fatal(root):
    """Битое состояние не должно валить мост — но и не должно «терять» карточки молча:
    находки просто заводятся заново по общим правилам."""
    (root / B.STATE_REL).parent.mkdir(parents=True, exist_ok=True)
    (root / B.STATE_REL).write_text("{не json", encoding="utf-8")
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("B1:x", severity="CRITICAL")]))
    rep = run_bridge(root, q)
    assert rep["counts"]["opened"] == 1


def test_findings_from_both_sources_are_namespaced(root):
    """Ключи двух сторожей не должны схлопываться: `G1:x` у обоих — разные находки."""
    q = FakeQueue(root / "tracker")
    write_source(root, "arch", report([finding("X:same")]))
    write_source(root, "hvg", report([finding("X:same")]))
    rep = B.run(str(root), NOW, apply=False, runner=q.run)
    assert {f["key"] for f in rep["pending"]} == {"arch/X:same", "hvg/X:same"}


def test_module_is_llm_free_and_stdlib_only():
    src = BRIDGE_PATH.read_text(encoding="utf-8")
    assert "LLM_FORBIDDEN" in src
    for banned in ("import requests", "import anthropic", "openai"):
        assert banned not in src


# ── ПРИЁМКА КАРТОЧКИ: находка → карточка → закрытие БЕЗ РУК ──────────────────

def test_acceptance_finding_becomes_a_card_and_closes_itself(root, monkeypatch):
    """Приёмка фазы 3 дословно: искусственная находка проходит весь путь без единого
    ручного действия — через НАСТОЯЩИЙ `orchestrator_queue.py` (единственный
    мутационный API очереди), во временном трекере."""
    tracker = root / "tracker"
    tracker.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("SPA_TRACKER_DIR", str(tracker))

    write_source(root, "arch", report([finding(
        "B1:dead:com.spa.iskusstvennaya",
        msg="com.spa.iskusstvennaya: intent=active, но НЕ загружен во флоте")]))

    # прогон 1 — гистерезис: карточки ещё нет
    r1 = B.run(str(root), NOW, apply=True, notifier=lambda p: (0, "", ""))
    assert r1["counts"]["opened"] == 0 and r1["counts"]["pending"] == 1
    assert list(tracker.glob("*.md")) == [] or all(
        p.name == "_BOARD.md" for p in tracker.glob("*.md"))

    # прогон 2 — находка подтвердилась → карточка родилась сама
    r2 = B.run(str(root), NOW + dt.timedelta(hours=6), apply=True,
               notifier=lambda p: (0, "", ""))
    assert r2["counts"]["opened"] == 1
    card = Path(r2["opened"][0]["card_path"])
    assert card.exists()
    text = card.read_text(encoding="utf-8")
    assert "status: backlog" in text
    assert "finding_key:" in text and "arch/B1:dead:com.spa.iskusstvennaya" in text
    assert "com.spa.iskusstvennaya" in text

    # прогон 3 — находка исчезла → карточка закрылась сама, с эвиденсом
    write_source(root, "arch", report([], overall="OK"))
    r3 = B.run(str(root), NOW + dt.timedelta(hours=12), apply=True,
               notifier=lambda p: (0, "", ""))
    assert r3["counts"]["closed"] == 1
    closed = card.read_text(encoding="utf-8")
    assert "status: done" in closed
    assert "Закрыто автоматически" in closed
    assert "больше нет в свежем отчёте" in closed

    # и повторный прогон ничего не воскрешает
    r4 = B.run(str(root), NOW + dt.timedelta(hours=13), apply=True,
               notifier=lambda p: (0, "", ""))
    assert r4["counts"]["opened"] == 0 and r4["counts"]["closed"] == 0
