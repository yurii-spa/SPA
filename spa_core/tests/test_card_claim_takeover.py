"""ПОДЪЁМ осиротевшего захвата: у законного действия появилось имя.

Живой случай (цикл #358, 23.08)
------------------------------------------------------------------------------
Протокол про вердикт `stale` говорит прямо: «кандидат на ручной подъём осиротевшей
работы (порядок шага 0a, авто-захвата нет)». То есть взять такую карточку — ПРЕДПИСАНО,
после ручной сверки. Инструмент же не давал согласиться ни одним способом:
``claim`` на `stale` бросал `ClaimError`, флага не существовало, `--force` есть только у
``release``. Цикл #358 сверил осиротевшую работу по шагу 0a, взял карточку
`inbox-golyi-otvet-vladeltsa-1-2-pri-voprose-be` — и пометить её было НЕЧЕМ: на карточке
остался `claimed_by` умершей сессии, а живой владелец существовал только в журнале.

Это ровно тот класс, который цикл #354 закрыл словом ``dropped`` у уборщика деревьев:
**действие, разрешённое правилом, но не имеющее имени в инструменте, выглядит нарушением
— и его начинают делать в обход инструмента.** Сторож, который блокирует верное действие,
учит себя игнорировать.

Направление ошибки НЕ меняется, и это проверяется тестами в обе стороны:

* подъём разрешён ТОЛЬКО при `stale`; `claimed` (живая сессия) и `unchecked` (занятость
  не измерена) отказывают как прежде — флаг не отмычка;
* причина обязательна и непустая — «подъём» без основания закрыл бы что угодно;
* основание уезжает и в журнал, и во frontmatter карточки: карточка попадает на origin,
  журнал — нет.

Тесты герметичны: свой каталог карточек, свой журнал, `ps` подменён, время подаётся явно.
"""
import importlib.util
import json
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from spa_core.tests._freshness import now_utc

ROOT = Path(__file__).resolve().parents[2]

#: Якорь времени — РЕАЛЬНЫЕ часы, а не литеральная дата: здесь есть понятие свежести
#: (`grace_hours`, «захват старше окна»), и литерал в фикстуре начал бы падать просто
#: оттого, что сдвинулся календарь — по причине, не имеющей отношения к проверяемому
#: поведению (правило `.claude/rules/deployment.md`, храповик `test_frozen_date_ratchet`).
#: Часы при этом ИНЪЕКТИРОВАНЫ: `claim_card(now=NOW)` и все отметки ниже выводятся из
#: этого же якоря, поэтому обе стороны сравнения закреплены и тест детерминирован.
NOW = now_utc()
REASON = "сверил шагом 0a: работа умершей сессии доставлена коммитом abc1234, поднимать нечего"


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_test_card_claim_takeover", "scripts/check_card_claim.py")


@pytest.fixture(scope="module")
def sibling(guard):
    return guard.load_sibling()


@pytest.fixture()
def tracker(tmp_path):
    d = tmp_path / "tracker"
    d.mkdir()
    return d


@pytest.fixture()
def log(tmp_path):
    p = tmp_path / "session_changes.jsonl"
    p.write_text("", encoding="utf-8")
    return p


def _fmt(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _card(tracker, cid="agent-x", *, claimed_by=None, claimed_at=None, status="backlog"):
    fm = ["---", "trackerStatus:", "  type: agent-task", "title: Тестовая карточка",
          f"status: {status}", "priority: high"]
    if claimed_by:
        fm.append(f"claimed_by: {claimed_by}")
    if claimed_at:
        fm.append(f"claimed_at: {claimed_at}")
    fm.append("---")
    p = tracker / f"{cid}.md"
    p.write_text("\n".join(fm) + "\n\n## Тело\n\nстрока\n", encoding="utf-8")
    return p


def _orphaned(tracker, cid="agent-x"):
    """Карточка с СИЛЬНЫМ захватом мёртвой сессии — вердикт `stale`."""
    return _card(tracker, cid, claimed_by="pid999",
                 claimed_at=_fmt(NOW - timedelta(hours=17)))


DEAD = lambda pid: (1, "")                                          # noqa: E731
ALIVE = lambda pid: (0, (NOW - timedelta(hours=48)).astimezone()    # noqa: E731
                     .strftime("%a %b %d %H:%M:%S %Y") + "\n")


def _entries(log):
    return [json.loads(ln) for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]


# ── отказ без причины: слово есть, но оно требует основания ───────────────────


def test_stale_still_refuses_without_a_reason_and_names_the_way_out(guard, sibling,
                                                                    tracker, log):
    """Прежний отказ на месте — но теперь он ГОВОРИТ, чем разрешено согласиться.

    Молчаливый отказ и учил обходить инструмент руками: цикл #358 так и сделал.
    """
    card = _orphaned(tracker)
    with pytest.raises(guard.ClaimError) as exc:
        guard.claim_card("agent-x", session="cycle-358", tracker_dir=tracker, now=NOW,
                         sibling=sibling, log=log, ps=DEAD)
    msg = str(exc.value)
    assert "`stale`" in msg
    assert "--takeover" in msg, "отказ не называет разрешённый протоколом выход"
    assert "pid999" in card.read_text(encoding="utf-8"), "карточка тронута при отказе"


def test_an_empty_reason_is_not_a_reason(guard, sibling, tracker, log):
    """`--takeover ""` (и пробелы) — не основание: иначе флаг закрывал бы что угодно."""
    _orphaned(tracker)
    for empty in ("", "   ", "\n"):
        with pytest.raises(guard.ClaimError):
            guard.claim_card("agent-x", session="cycle-358", tracker_dir=tracker, now=NOW,
                             sibling=sibling, log=log, ps=DEAD, takeover_reason=empty)


# ── подъём: разрешён, назван, виден ──────────────────────────────────────────


def test_takeover_lifts_the_orphaned_claim_and_records_the_reason(guard, sibling,
                                                                  tracker, log):
    """Живой случай #358: осиротевший захват перебит, основание лежит В КАРТОЧКЕ."""
    card = _orphaned(tracker)

    res = guard.claim_card("agent-x", session="cycle-358", tracker_dir=tracker, now=NOW,
                           sibling=sibling, log=log, ps=DEAD, takeover_reason=REASON)

    assert res["claimed_by"] == "cycle-358"
    assert res["takeover_from"] == ["pid999"]
    assert res["takeover_reason"] == REASON
    meta = guard.frontmatter(card.read_text(encoding="utf-8"))
    assert meta["claimed_by"] == "cycle-358", "владельцем осталась мёртвая сессия"
    assert meta["claim_takeover_reason"] == REASON
    assert "pid999" not in card.read_text(encoding="utf-8")


def test_the_takeover_is_announced_in_the_shared_log_with_its_reason(guard, sibling,
                                                                     tracker, log):
    """Журнал виден без пуша — и подъём обязан быть виден в нём, а не только в файле."""
    _orphaned(tracker)

    guard.claim_card("agent-x", session="cycle-358", tracker_dir=tracker, now=NOW,
                     sibling=sibling, log=log, ps=DEAD, takeover_reason=REASON)

    rows = [e for e in _entries(log) if e.get("card") == "agent-x"]
    assert rows, "захват не объявлен"
    summary = rows[-1]["summary"]
    assert "ПОДЪЁМ" in summary and "pid999" in summary and REASON in summary
    assert rows[-1]["card_state"] == "claim"


def test_the_body_of_the_card_is_untouched_by_a_takeover(guard, sibling, tracker, log):
    """Инструмент трогает ровно свои строки — карточка остаётся источником правды."""
    card = _orphaned(tracker)
    before = card.read_text(encoding="utf-8")

    guard.claim_card("agent-x", session="cycle-358", tracker_dir=tracker, now=NOW,
                     sibling=sibling, log=log, ps=DEAD, takeover_reason=REASON)

    assert card.read_text(encoding="utf-8").split("---", 2)[2] == before.split("---", 2)[2]


def test_a_multiline_reason_is_folded_so_the_frontmatter_stays_parseable(guard, sibling,
                                                                        tracker, log):
    """Frontmatter читается построчно: многострочная причина развалила бы его у ВСЕХ."""
    card = _orphaned(tracker)

    guard.claim_card("agent-x", session="cycle-358", tracker_dir=tracker, now=NOW,
                     sibling=sibling, log=log, ps=DEAD,
                     takeover_reason="первая строка\nвторая  строка\n\nтретья")

    text = card.read_text(encoding="utf-8")
    meta = guard.frontmatter(text)
    assert meta["claim_takeover_reason"] == "первая строка вторая строка третья"
    assert meta["status"] == "backlog", "frontmatter развалился — соседние поля потерялись"


def test_releasing_a_lifted_card_clears_the_reason_too(guard, sibling, tracker, log):
    """Основание снимается вместе с захватом: объяснение без предмета — то же враньё."""
    card = _orphaned(tracker)
    guard.claim_card("agent-x", session="cycle-358", tracker_dir=tracker, now=NOW,
                     sibling=sibling, log=log, ps=DEAD, takeover_reason=REASON)

    guard.release_card("agent-x", session="cycle-358", tracker_dir=tracker, log=log)

    text = card.read_text(encoding="utf-8")
    assert "claim_takeover_reason" not in text
    assert "claimed_by" not in text


# ── флаг НЕ отмычка: обратные контроли ───────────────────────────────────────


def test_takeover_does_not_touch_a_card_held_by_a_LIVE_session(guard, sibling, tracker, log):
    """Подтверждённо живая сессия ⇒ отказ с причиной и БЕЗ подъёма — это была бы кража."""
    card = _card(tracker, "agent-x", claimed_by="pid999",
                 claimed_at=_fmt(NOW - timedelta(hours=17)))
    log.write_text(json.dumps({"ts": _fmt(NOW - timedelta(minutes=5)), "session": "pid999",
                               "summary": "работаю", "files": [], "verified": "",
                               "card": "agent-x", "card_state": "claim",
                               "session_pid": 999,
                               "session_pid_start": (NOW - timedelta(hours=48)).astimezone()
                               .strftime("%a %b %d %H:%M:%S %Y")},
                              ensure_ascii=False) + "\n", encoding="utf-8")

    with pytest.raises(guard.ClaimError) as exc:
        guard.claim_card("agent-x", session="cycle-358", tracker_dir=tracker, now=NOW,
                         sibling=sibling, log=log, ps=ALIVE, takeover_reason=REASON)

    assert "claimed" in str(exc.value)
    assert "pid999" in card.read_text(encoding="utf-8"), "живой захват перебит флагом"


def test_takeover_does_not_override_unchecked(guard, sibling, tracker, tmp_path):
    """«Занятость не измерена» ⇒ отказ (инв. #2): подъём — решение ПОСЛЕ измерения."""
    _card(tracker, "agent-x")
    with pytest.raises(guard.ClaimError) as exc:
        guard.claim_card("agent-x", session="cycle-358", tracker_dir=tracker, now=NOW,
                         sibling=sibling, log=tmp_path / "журнала-нет.jsonl", ps=DEAD,
                         takeover_reason=REASON)
    assert "unchecked" in str(exc.value)


def test_a_free_card_is_claimed_plainly_and_carries_no_takeover_trace(guard, sibling,
                                                                      tracker, log):
    """Свободную карточку флаг не превращает в «подъём»: поднимать было нечего."""
    card = _card(tracker, "agent-x")

    res = guard.claim_card("agent-x", session="cycle-358", tracker_dir=tracker, now=NOW,
                           sibling=sibling, log=log, ps=DEAD, takeover_reason=REASON)

    assert "takeover_reason" not in res
    assert "claim_takeover_reason" not in card.read_text(encoding="utf-8")


def test_an_ordinary_claim_still_writes_exactly_two_lines(guard, sibling, tracker, log):
    """Обратный контроль: без подъёма форма захвата не изменилась ни на строку."""
    card = _card(tracker, "agent-x")
    before = card.read_text(encoding="utf-8").splitlines()

    guard.claim_card("agent-x", session="pid1", tracker_dir=tracker, now=NOW,
                     sibling=sibling, log=log, ps=DEAD)

    after = card.read_text(encoding="utf-8").splitlines()
    assert [ln for ln in after if ln not in before] == [
        "claimed_by: pid1", f"claimed_at: {_fmt(NOW)}"]


# ── проводка CLI: флаг, который не дошёл до `claim_card`, — украшение ─────────


def test_the_cli_flag_actually_reaches_the_writer(guard, tracker, log, capsys):
    """`claim <карточка> --takeover "…"` через main(): подъём происходит и назван."""
    card = _orphaned(tracker)

    code = guard.main(["--tracker-dir", str(tracker), "--log", str(log),
                       "claim", "agent-x", "--session", "cycle-358",
                       "--takeover", REASON])

    assert code == 0
    out = capsys.readouterr().out
    assert "ПОДНЯТА" in out and "pid999" in out
    assert guard.frontmatter(card.read_text(encoding="utf-8"))["claimed_by"] == "cycle-358"


def test_the_cli_without_the_flag_still_refuses_a_stale_card(guard, tracker, log, capsys):
    """Обратный контроль проводки: без флага поведение CLI прежнее (код 1, отказ)."""
    _orphaned(tracker)

    code = guard.main(["--tracker-dir", str(tracker), "--log", str(log),
                       "claim", "agent-x", "--session", "cycle-358"])

    assert code != 0
    # Отказ печатается в stdout (так же, как и до этой правки) — проверяем то, что есть.
    assert "--takeover" in capsys.readouterr().out
