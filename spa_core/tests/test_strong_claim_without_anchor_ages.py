"""СИЛЬНЫЙ захват без объявленного якоря обязан СТАРЕТЬ (цикл #803, ADR-647).

Живой случай, ради которого ветка и правится
------------------------------------------------------------------------------
Шаг 0a-голод называл голодающий ПРИКАЗ ВЛАДЕЛЬЦА
`inbox-task-portfolio-cio-dynamic-capital-alloc` первым **634 цикла подряд** — и ни один
цикл не мог взять его инструментом. Замер 08.10 на живой очереди (прод-дерево):

    verdict: unchecked
    claims: 107 × stale            ← на них подъём (`--takeover`) БЫЛ бы разрешён
    unmeasured: 4
      cycle-74714: идентификатор сессии 'cycle-74714' не содержит pid — активность
                   процесса не измерена; захват от 2026-09-05T05:33:34Z (796.11ч назад)
      cycle-491  … 788.59ч   ·   cycle-28734 … 732.62ч   ·   cycle-3512 … 654.29ч

Четыре строки журнала от 05…11.09 перебивали вердикт 107 осиротевших захватов в
`unchecked`, а подъём разрешён ТОЛЬКО на `stale` ⇒ карточка была неберущейся НАВСЕГДА:
`session_state` отдаёт `UNKNOWN` для ярлыка без pid детерминированно и необратимо, а
`release` тут не помощник — держатель живёт в журнале-дописывайке, а не во frontmatter.

**Это третий близнец одной и той же пары.** То же лекарство уже применяли дважды:

* цикл #61 — СЛАБОЕ упоминание запирало карточку навсегда (`agent-weak-mention-locks-card-forever`);
* цикл #412 — ЖИВОЙ якорь при молчащей сессии держал карточку бессрочно;
* цикл #146 — захват из frontmatter читал личность процесса из журнала
  (`agent-frontmatter-claim-locks-card-forever`) — помогает лишь там, где якорь В ЖУРНАЛЕ есть.

У ветки `UNKNOWN + STRONG` окна не было вовсе, хотя слово «Старый» стояло в её
комментарии: возраст вычислялся строкой выше и **печатался в самом тексте отказа**, то
есть единственный доступный операнд был измерен и выброшен из решения.

Ослаблением правка не является, и тесты проверяют это в ОБЕ стороны
------------------------------------------------------------------------------
* «свободна» здесь не говорится никогда — исход `stale`, и `claim` на нём по-прежнему
  ОТКАЗЫВАЕТ без `--takeover` с непустой письменной причиной;
* СВЕЖИЙ захват без якоря до новой ветки не доходит вовсе — он `claimed` (строже, чем
  `stale`), и это ИЗМЕРЕНО тестом, а не предположено;
* захват без якоря, чья сессия подавала голос В ОКНЕ (пусть и по другой карточке),
  остаётся `unchecked` — вот она, настоящая неизмеримость; операнд тот же
  `last_voice_by_session`, что у ветки #412, и он действует в обе стороны;
* подтверждённо живая сессия по-прежнему `claimed`, измеренно мёртвая — `stale`.
"""
import importlib.util
import json
from datetime import timedelta, timezone
from pathlib import Path

import pytest

from spa_core.tests._freshness import now_utc

ROOT = Path(__file__).resolve().parents[2]

#: Якорь времени — РЕАЛЬНЫЕ часы, а не литеральная дата: предмет файла и есть понятие
#: свежести («захват старше окна»), и литерал начал бы падать от сдвига календаря, а не
#: от кода. Часы ИНЪЕКТИРОВАНЫ: все отметки сцены выведены из этого якоря, и он же
#: передаётся измерителю аргументом `now=` — закреплены обе стороны сравнения.
NOW = now_utc()

#: Возрасты четырёх строк, запиравших приказ владельца (замер 08.10, прод-очередь).
INCIDENT_AGES_H = (796.11, 788.59, 732.62, 654.29)
INCIDENT_LABELS = ("cycle-74714", "cycle-491", "cycle-28734", "cycle-3512")

#: Якорь личности для герметичных проверок: пара (pid, «старт verbatim»), которую никто
#: не меряет через `ps` — она сравнивается только с такими же парами внутри сцены.
#: Литеральный НОМЕР безопасен именно потому, что живым процессом не притворяется; а вот
#: время старта литералом НЕ пишется — оно выведено из того же якоря `NOW`, иначе в файле
#: появилась бы замороженная дата, и пришлось бы оправдывать её пометкой вместо того,
#: чтобы её не иметь (`.claude/rules/deployment.md`, приём №1).
SELF_START = (NOW - timedelta(hours=68)).astimezone().strftime("%a %b %d %H:%M:%S %Y")
SELF_ANCHOR = (41721, SELF_START)

DEAD = lambda pid: (1, "")                                           # noqa: E731

#: Строка `ps -o lstart`, которую отдаёт подменённая проба для ЖИВОГО процесса. Та же
#: строка кладётся в `session_pid_start` записи сцены: личность процесса — это ПАРА
#: (номер, старт), и расхождение стартов читается как переиспользованный номер, то есть
#: «не тот процесс». Без совпадения сцена проверяла бы совсем другое утверждение.
LIVE_START = (NOW - timedelta(hours=48)).astimezone().strftime("%a %b %d %H:%M:%S %Y")
ALIVE = lambda pid: (0, LIVE_START + "\n")                          # noqa: E731


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def guard():
    return _load("_c803_claim_guard", "scripts/check_card_claim.py")


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


def _card(tracker, cid="inbox-prikaz", status="in-progress"):
    p = tracker / f"{cid}.md"
    p.write_text("---\ntrackerStatus:\n  type: inbox\n"
                 f"title: Приказ владельца\nstatus: {status}\npriority: critical\n---\n"
                 "\n## Тело\n\nстрока\n", encoding="utf-8")
    return p


def _write(log, rows):
    log.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                   encoding="utf-8")


def _claim_row(session, ts, card="inbox-prikaz", *, anchor=None, summary="взял"):
    """Запись-ЗАХВАТ: поле `card:` — тот самый СИЛЬНЫЙ признак (`announce_claim`)."""
    row = {"ts": _fmt(ts), "session": session, "summary": summary,
           "files": [], "card": card, "card_state": "claim"}
    if anchor:
        row["session_pid"], row["session_pid_start"] = anchor
    return row


def _verdict(guard, sibling, tracker, log, *, ps=DEAD, now=None):
    return guard.gather("inbox-prikaz", log=log, tracker_dir=tracker, sibling=sibling,
                        self_session="cycle-803", now=now or NOW, ps=ps,
                        self_anchor=SELF_ANCHOR, shared_trees=())


# ── ПОЛОЖИТЕЛЬНЫЙ КОНТРОЛЬ: дословная сцена 08.10 ───────────────────────────────


def test_the_owners_starving_order_is_takeable_again(guard, sibling, tracker, log):
    """Четыре строки без pid возрастом 654…796 ч ⇒ `stale`, а не `unchecked`.

    Это замер живой очереди 08.10, перенесённый в сцену: ярлыки и возрасты дословные.
    """
    _card(tracker)
    _write(log, [_claim_row(lab, NOW - timedelta(hours=age))
                 for lab, age in zip(INCIDENT_LABELS, INCIDENT_AGES_H)])
    report = _verdict(guard, sibling, tracker, log)
    assert report["verdict"] == guard.STALE, (
        f"вердикт {report['verdict']!r}: приказ владельца снова неберущийся — "
        f"не измерено: {report['unmeasured']}")
    assert not report["unmeasured"], report["unmeasured"]
    assert {c["session"] for c in report["claims"]} == set(INCIDENT_LABELS)
    assert all(c["state"] == "stale" for c in report["claims"])


def test_the_verdict_names_why_waiting_is_pointless(guard, sibling, tracker, log):
    """Исход обязан СКАЗАТЬ, на каком основании он состарился: часы молчания и окно.

    Без этого `stale` здесь был бы неотличим от `stale` по измеренной смерти процесса —
    а это разные утверждения («процесса нет» против «личности не объявил никто»).
    """
    _card(tracker)
    _write(log, [_claim_row("cycle-74714", NOW - timedelta(hours=796.11))])
    report = _verdict(guard, sibling, tracker, log)
    why = report["claims"][0]["session_state"]
    assert "не содержит pid" in why, why
    assert "796" in why.replace(",", "."), why
    assert "не объявлена НИГДЕ" in why, why
    assert "--takeover" in why, why


def test_takeover_with_a_reason_now_succeeds_on_that_very_scene(guard, sibling, tracker,
                                                                log, monkeypatch):
    """Подъём доезжает до КАРТОЧКИ: вердикт `stale` ⇒ `--takeover` разрешён.

    До правки тот же вызов падал `ClaimError` с вердиктом `unchecked`, и выхода не было
    ни одного — именно поэтому «взять первой» было невыполнимо 634 цикла.
    """
    monkeypatch.setenv("SPA_SESSION_ID", "cycle-803")
    card = _card(tracker)
    _write(log, [_claim_row(lab, NOW - timedelta(hours=age))
                 for lab, age in zip(INCIDENT_LABELS, INCIDENT_AGES_H)])
    out = guard.claim_card("inbox-prikaz", log=log, session="cycle-803",
                           tracker_dir=tracker, now=NOW, sibling=sibling, ps=DEAD,
                           self_anchor=SELF_ANCHOR,
                           takeover_reason="сверил шагом 0a: работы в деревьях нет")
    assert out["claimed_by"] == "cycle-803"
    assert sorted(out["takeover_from"]) == sorted(INCIDENT_LABELS)
    text = card.read_text(encoding="utf-8")
    assert "claimed_by: cycle-803" in text
    assert "claim_takeover_reason:" in text, "основание подъёма не доехало до карточки"


# ── ОБРАТНАЯ СТОРОНА: что НЕ изменилось ─────────────────────────────────────────


def test_a_fresh_anchorless_claim_still_blocks_as_claimed(guard, sibling, tracker, log):
    """Свежий захват без якоря до новой ветки даже НЕ ДОХОДИТ — он `claimed`.

    Это измерено, а не предположено: свежий СИЛЬНЫЙ признак блокирует ветвью выше, и
    правка её не касается. Сессия могла объявиться минуту назад и работать прямо сейчас,
    поэтому исход строже `stale`, а не слабее.
    """
    _card(tracker)
    _write(log, [_claim_row("cycle-901", NOW - timedelta(minutes=20))])
    report = _verdict(guard, sibling, tracker, log)
    assert report["verdict"] == guard.CLAIMED, report["claims"]
    assert report["claims"][0]["state"] == "fresh"


def test_an_old_anchorless_claim_whose_session_still_speaks_stays_unchecked(
        guard, sibling, tracker, log):
    """Голос берётся по ВСЕМУ журналу: сессия жива ⇒ возраст захвата ничего не решает.

    Операнд тот же, которым ветка живого якоря (#412) перестала держать вечно, — и
    он обязан действовать в обе стороны, иначе долгая законная работа сорвалась бы.
    """
    _card(tracker)
    _write(log, [_claim_row("cycle-901", NOW - timedelta(hours=700)),
                 {"ts": _fmt(NOW - timedelta(minutes=10)), "session": "cycle-901",
                  "summary": "продолжаю работу", "files": []}])
    report = _verdict(guard, sibling, tracker, log)
    assert report["verdict"] == guard.UNCHECKED, (
        "сессия подавала голос 10 минут назад при окне 3ч — состарить её захват нельзя")


def test_stale_still_refuses_a_claim_without_a_reason(guard, sibling, tracker, log):
    """Авто-захвата не появилось: без `--takeover` отказ, и он называет выход."""
    _card(tracker)
    _write(log, [_claim_row("cycle-74714", NOW - timedelta(hours=796.11))])
    with pytest.raises(guard.ClaimError) as exc:
        guard.claim_card("inbox-prikaz", log=log, session="cycle-803",
                         tracker_dir=tracker, now=NOW, sibling=sibling, ps=DEAD,
                         self_anchor=SELF_ANCHOR)
    msg = str(exc.value)
    assert "`stale`" in msg and "--takeover" in msg, msg


def test_an_empty_reason_is_still_not_a_reason(guard, sibling, tracker, log):
    """Пустое основание — не основание; иначе флаг стал бы отмычкой."""
    _card(tracker)
    _write(log, [_claim_row("cycle-74714", NOW - timedelta(hours=796.11))])
    for empty in ("", "   ", "\n"):
        with pytest.raises(guard.ClaimError):
            guard.claim_card("inbox-prikaz", log=log, session="cycle-803",
                             tracker_dir=tracker, now=NOW, sibling=sibling, ps=DEAD,
                             self_anchor=SELF_ANCHOR, takeover_reason=empty)


def test_a_live_anchored_session_still_holds_the_card(guard, sibling, tracker, log):
    """Подтверждённо живая сессия, подающая голос в окне, — по-прежнему `claimed`."""
    _card(tracker)
    anchor = (int(SELF_ANCHOR[0]) + 1, LIVE_START)
    _write(log, [_claim_row("cycle-902", NOW - timedelta(minutes=30), anchor=anchor)])
    report = _verdict(guard, sibling, tracker, log, ps=ALIVE)
    assert report["verdict"] == guard.CLAIMED, report


def test_an_anchored_session_whose_process_is_gone_is_still_stale(guard, sibling,
                                                                  tracker, log):
    """Измеренная смерть процесса даёт `stale` как и раньше — и причина ДРУГАЯ.

    Два исхода с одним именем обязаны отличаться текстом: «процесс завершился» против
    «личности не объявлено нигде». Иначе разбор находки терял бы операнд.
    """
    _card(tracker)
    anchor = (int(SELF_ANCHOR[0]) + 2, "Sat Aug  1 13:37:28 2026")
    _write(log, [_claim_row("cycle-903", NOW - timedelta(hours=40), anchor=anchor)])
    report = _verdict(guard, sibling, tracker, log, ps=DEAD)
    assert report["verdict"] == guard.STALE, report
    why = report["claims"][0]["session_state"]
    assert "завершился" in why, why
    assert "не объявлена НИГДЕ" not in why, (
        "две разные причины `stale` слиты в один текст — операнд потерян")


def test_a_terminal_card_is_untouched_by_the_new_branch(guard, sibling, tracker, log):
    """На закрытой карточке захват не действует и до правки, и после (цикл #50)."""
    _card(tracker, status="done")
    _write(log, [_claim_row("cycle-74714", NOW - timedelta(hours=796.11))])
    report = _verdict(guard, sibling, tracker, log)
    assert report["verdict"] == guard.FREE, report
    assert not report["claims"]


def test_a_weak_mention_is_still_history_not_a_claim(guard, sibling, tracker, log):
    """Слабый признак в новую ветку не попадает — он уже состарен циклом #61."""
    _card(tracker)
    _write(log, [{"ts": _fmt(NOW - timedelta(hours=700)), "session": "cycle-904",
                  "summary": "шаг 0b: inbox-prikaz = ЗАНЯТА ⇒ не беру", "files": []}])
    report = _verdict(guard, sibling, tracker, log)
    assert report["verdict"] == guard.FREE, report
    assert not report["claims"]
    assert any(h.get("state") == "history" for h in report["history"])


# ── ГРАНИЦА ПРАВКИ: стареет РОВНО ОДНА из шести причин `UNKNOWN` ────────────────
#
# Остальные пять — сбой прибора или записи, и «отсутствие инструмента есть
# самостоятельный третий исход» (`.claude/rules/deployment.md`, урок `pyflakes`). Первая
# редакция этой ветки гасила все шесть разом, и нашли это НЕ эти тесты, а девять уже
# существовавших — поэтому граница пиннится здесь явно, а не держится на их памяти.


def test_a_broken_ps_is_still_unchecked_not_stale(guard, sibling, tracker, log):
    """Якорь объявлен, `ps` не отработал ⇒ измерить НЕ СМОГЛИ — это не старение."""
    _card(tracker)
    anchor = (int(SELF_ANCHOR[0]) + 3, LIVE_START)
    _write(log, [_claim_row("cycle-905", NOW - timedelta(hours=700), anchor=anchor)])
    report = _verdict(guard, sibling, tracker, log, ps=lambda pid: (127, ""))
    assert report["verdict"] == guard.UNCHECKED, report["claims"]
    assert guard.exit_code(report) == 2


def test_an_empty_ps_answer_is_still_unchecked(guard, sibling, tracker, log):
    """Пустой ответ `ps` — тоже «не измерено», а не смерть процесса."""
    _card(tracker)
    anchor = (int(SELF_ANCHOR[0]) + 4, LIVE_START)
    _write(log, [_claim_row("cycle-906", NOW - timedelta(hours=700), anchor=anchor)])
    report = _verdict(guard, sibling, tracker, log, ps=lambda pid: (0, "   \n"))
    assert report["verdict"] == guard.UNCHECKED, report["claims"]


def test_an_unparsable_start_time_is_still_unchecked(guard, sibling, tracker, log):
    """Процесс есть, время старта не разобрано ⇒ личность не установлена — `unchecked`."""
    _card(tracker)
    anchor = (int(SELF_ANCHOR[0]) + 5, LIVE_START)
    _write(log, [_claim_row("cycle-907", NOW - timedelta(hours=700), anchor=anchor)])
    report = _verdict(guard, sibling, tracker, log,
                      ps=lambda pid: (0, "это не время старта\n"))
    assert report["verdict"] == guard.UNCHECKED, report["claims"]


def test_a_label_that_declared_an_anchor_ELSEWHERE_is_not_nameless(guard, sibling,
                                                                   tracker, log):
    """«Нигде» значит НИГДЕ: якорь под тем же ярлыком в другой записи журнала считается.

    Это и есть разница между «измерить не смогли» (ярлык с противоречащими якорями,
    цикл #327) и «измерить не сможет никто». `durables` отдаёт якорь только когда он
    однозначен, поэтому противоречие выглядит как молчание — и отличить их можно лишь
    спросив журнал напрямую.
    """
    _card(tracker)
    a1 = (int(SELF_ANCHOR[0]) + 6, LIVE_START)
    a2 = (int(SELF_ANCHOR[0]) + 7, LIVE_START)
    _write(log, [
        _claim_row("cycle-908", NOW - timedelta(hours=800), anchor=a1, card="other-card"),
        _claim_row("cycle-908", NOW - timedelta(hours=700), anchor=a2, card="other-card"),
        _claim_row("cycle-908", NOW - timedelta(hours=700)),
    ])
    report = _verdict(guard, sibling, tracker, log, ps=lambda pid: (127, ""))
    assert report["verdict"] == guard.UNCHECKED, (
        "ярлык объявлял личность в журнале — состарить его захват нельзя")


def test_session_state_itself_is_untouched(guard, sibling):
    """Правка живёт у ПОТРЕБИТЕЛЯ: сам измеритель по-прежнему `UNKNOWN` в любом возрасте.

    Пин цикла #61 (`test_pidless_session_is_unmeasurable_at_any_age`) остаётся верным —
    и это важно: мы не стали утверждать, что активность измерена. Мы перестали ждать.
    """
    for age in (timedelta(minutes=1), timedelta(days=1), timedelta(days=3650)):
        state, why = sibling.session_state(
            {"session": "cycle-74714", "ts": _fmt(NOW - age)}, "cycle-803",
            ps=lambda pid: (1, ""))
        assert state == sibling.UNKNOWN
        assert "не содержит pid" in why
