#!/usr/bin/env python3
"""Карточка, ОТКРЫТАЯ в этом дереве и уже ЗАКРЫТАЯ на origin (цикл #472).

**Авария, которую воспроизводит каждый положительный контроль этого файла.**
2026-09-03 обязательный шаг 0-офис (ADR-066) напечатал по живому прод-дереву:

===============================  =============================================
`принято владельцем, НЕ ИСПОЛНЕНО: 2`   `…-tier1-2`, `…-weekly-2` «ждут агента»
`pending_count: 7`                      среди них `…-digest-2` — «живой вопрос»
===============================  =============================================

Все три карточки на `origin/main` (80f25077a) стояли в `ingested` **с 15:46Z**: ответ
владельца получен («Да, перезагрузить все три сейчас»), исполнен интерактивной сессией в
13:41Z (`launchctl bootstrap` каждому, `deployment_acceptance` OK до и после), статус
переведён циклом #470. Артефакт снят в **18:21Z** — на 2.6 ч ПОЗЖЕ — и всё равно заказывал
сделанную работу.

**Механизм.** Сверка с origin в модуле БЫЛА (`_resolve_missing_on_origin`,
`closed_on_origin`, ADR-192), но прикладывалась исключительно к карточкам, которых в дереве
НЕТ. Карточке, которая в дереве ЕСТЬ, верили на слово — а прод-копия устаревает по
построению: `nimbalyst-local/` в прод не возит никто (#193), протокол §3.4 обязывает агента
работать из изолированного worktree, значит КАЖДЫЙ разбор шага 2 оставляет прод-копию
позади. Расхождение не рассасывается никогда.

**Цена.** Шаг 0-офис ПРИКАЗЫВАЕТ переделать сделанное — ровно на этом цикл #471 потерял
работу (ADR-220: объявил владение и написал ручную правку прежде, чем перемерил основание
приказа). Плюс закрытый вопрос остаётся в очереди владельца, а жалоба «поток одинаковых
сообщений» звучала уже дважды (#215).

**Направление ПРОВЕРЯЕТСЯ, а не предполагается — и это обратный контроль здесь.**
Прод-дерево есть ПИСАТЕЛЬ ответов владельца (бот пишет туда, минуя git), поэтому «на origin
закрыто» само по себе ничего не решает. Решает, чья отметка позже — одна мерка
(`status_audit.latest_change_at`) на обе копии, ПАРАМЕТРОМ, а не вторым экземпляром:
копия разъехалась бы с оригиналом молча (урок ADR-220). Наша новее ⇒ это поздний `ack`
владельца, карточка остаётся открытой (`inbox-pozdnii-prinyato-voskreshaet-kartochku-z`).

Время — вход, а не окружение: все отметки считаются от `FIXED_NOW`, литеральных дат в
фикстурах нет (дата 03.09 живёт в прозе — она предмет, а не поведение).
"""
from __future__ import annotations

import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from spa_core.monitoring import owner_decision_pending as odp
from spa_core.owner_queue import origin_view
from spa_core.owner_queue import status_audit as sa
from spa_core.tests._freshness import now_utc

FIXED_NOW = now_utc()
REF = "origin/main"

#: Момент ответа владельца кнопкой (10:10Z живой аварии).
ANSWERED_AT = FIXED_NOW - timedelta(hours=8)
#: Момент, когда агент перевёл карточку в `ingested` на origin (15:46Z живой аварии).
CLOSED_AT = FIXED_NOW - timedelta(hours=3)
#: Поздний ответ владельца — ПОСЛЕ закрытия на origin (обратный контроль).
LATE_ANSWER_AT = FIXED_NOW - timedelta(minutes=30)

CARD_ID = "owner-decision-kritichnaya-nahodka-petli-com-spa-tier1-2"


def _card(*, status: str, trail: list[tuple[str, str, str]] | None = None,
          answered_at=None) -> str:
    """Текст карточки: статус + необязательный след + необязательный ответ владельца."""
    lines = ["---", "trackerStatus:", "  type: owner-decision",
             'title: "Критичная находка петли: com.spa.tier1_digest не загружен"',
             f"status: {status}", "source: nimbalyst"]
    if answered_at is not None:
        lines += ["owner_choice: ack", f"owner_answered_at: {answered_at.isoformat()}"]
    if trail:
        lines.append("status_trail:")
        lines += [f'  - "{ts.isoformat()} {old} -> {new} · queue.set_status"'
                  for ts, old, new in trail]
    lines += ["---", "", "## Что случилось и почему это важно", "",
              "com.spa.tier1_digest: intent=active, но НЕ загружен во флоте.", ""]
    return "\n".join(lines)


def _git(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.stderr}"
    return res.stdout


@pytest.fixture()
def tree(tmp_path):
    """Дерево-репозиторий, чья ветка НАЗВАНА `origin/main` — как в соседних наборах."""
    root = tmp_path / "repo"
    (root / origin_view.TRACKER_REL).mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", REF, str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "test")
    ddir = tmp_path / "data"
    ddir.mkdir()
    return {"root": root, "tracker": root / origin_view.TRACKER_REL, "data": ddir}


def _publish(tree, text: str, card_id: str = CARD_ID) -> Path:
    """Положить версию карточки НА ORIGIN (коммит) — как её видит `origin/main`."""
    path = tree["tracker"] / f"{card_id}.md"
    path.write_text(text, encoding="utf-8")
    _git(tree["root"], "add", "-A")
    _git(tree["root"], "commit", "-q", "-m", "card")
    return path


def _local(tree, text: str, card_id: str = CARD_ID) -> Path:
    """Перезаписать РАБОЧУЮ копию (прод-дерево), не коммитя: origin остаётся впереди."""
    path = tree["tracker"] / f"{card_id}.md"
    path.write_text(text, encoding="utf-8")
    return path


def _report(tree) -> dict:
    return odp.check_pending_owner_decisions(now=FIXED_NOW, data_dir=tree["data"],
                                             tracker_dir=tree["tracker"])


def _office_lines(doc) -> str:
    from scripts.consume_office_reports import _summarize_json

    return "\n".join(_summarize_json("owner_decision_pending.json", doc))


def _incident(tree, *, local_status: str) -> dict:
    """Дословный расклад 03.09: origin закрыл в 15:46Z, прод-копия отстала."""
    _publish(tree, _card(status="ingested", answered_at=ANSWERED_AT,
                         trail=[(CLOSED_AT, "needs-owner", "ingested")]))
    trail = ([(ANSWERED_AT, "needs-owner", "owner-accepted")]
             if local_status == "owner-accepted" else None)
    _local(tree, _card(status=local_status,
                       answered_at=ANSWERED_AT if trail else None, trail=trail))
    return _report(tree)


# ── 1. САМА АВАРИЯ 03.09 18:21Z ─────────────────────────────────────────────


def test_a_promise_closed_on_origin_is_not_an_unfinished_instruction(tree):
    """Положительный контроль: `owner-accepted` здесь + `ingested` на origin ⇒ не поручение."""
    doc = _incident(tree, local_status="owner-accepted")

    assert doc["accepted_count"] == 0, doc["accepted"]
    assert [d["card_id"] for d in doc["closed_on_origin_open_here"]["drift"]] == [CARD_ID]
    assert doc["closed_on_origin_open_here_count"] == 1


def test_a_question_closed_on_origin_is_not_a_live_question(tree):
    """Вторая половина той же аварии: `needs-owner` здесь БЕЗ следа + `ingested` на origin."""
    doc = _incident(tree, local_status="needs-owner")

    assert doc["pending_count"] == 0, doc["pending"]
    assert [d["card_id"] for d in doc["closed_on_origin_open_here"]["drift"]] == [CARD_ID]


def test_the_drift_is_named_not_swallowed(tree):
    """Вынуть из очереди — не значит спрятать: у дрейфа обязан быть читатель."""
    doc = _incident(tree, local_status="owner-accepted")

    drift = doc["closed_on_origin_open_here"]["drift"][0]
    assert drift["origin_status"] == "ingested"
    assert drift["origin_change_at"] == CLOSED_AT.isoformat()
    assert drift["local_change_at"] == ANSWERED_AT.isoformat()
    assert [c["card_id"] for c in doc["drifted_accepted"]] == [CARD_ID]


def test_office_step_prints_the_drift(tree):
    """Читатель — обязательный шаг 0-офис; молчание там и было дефектом."""
    text = _office_lines(_incident(tree, local_status="owner-accepted"))

    assert "дрейф прод↔origin" in text and "УЖЕ ЗАКРЫТ" in text
    assert CARD_ID in text
    assert "принято владельцем, НЕ ИСПОЛНЕНО" not in text


# ── 2. ОБРАТНЫЕ КОНТРОЛИ: живой вопрос не имеет права исчезнуть ─────────────


def test_a_late_owner_answer_keeps_the_promise_open(tree):
    """Наша отметка НОВЕЕ закрытия ⇒ поздний `ack`: карточка остаётся поручением."""
    _publish(tree, _card(status="ingested",
                         trail=[(CLOSED_AT, "needs-owner", "ingested")]))
    _local(tree, _card(status="owner-accepted", answered_at=LATE_ANSWER_AT,
                       trail=[(LATE_ANSWER_AT, "ingested", "owner-accepted")]))

    doc = _report(tree)

    assert doc["accepted_count"] == 1
    assert doc["closed_on_origin_open_here"]["drift"] == []


def test_a_late_owner_answer_without_a_trail_still_keeps_the_card(tree):
    """Проводка: у ЛОКАЛЬНОЙ копии свидетельством служит и `owner_answered_at` без следа."""
    _publish(tree, _card(status="ingested",
                         trail=[(CLOSED_AT, "needs-owner", "ingested")]))
    _local(tree, _card(status="owner-accepted", answered_at=LATE_ANSWER_AT))

    doc = _report(tree)

    assert doc["accepted_count"] == 1
    assert doc["closed_on_origin_open_here"]["drift"] == []


def test_an_origin_answer_without_a_trail_still_closes_the_card(tree):
    """Та же проводка со стороны origin: одна мерка на обе копии, а не две."""
    _publish(tree, _card(status="ingested", answered_at=CLOSED_AT))
    _local(tree, _card(status="needs-owner", answered_at=ANSWERED_AT,
                       trail=[(ANSWERED_AT, "new", "needs-owner")]))

    doc = _report(tree)

    assert doc["pending_count"] == 0
    assert [d["card_id"] for d in doc["closed_on_origin_open_here"]["drift"]] == [CARD_ID]


def test_a_question_open_on_origin_too_is_still_a_question(tree):
    """origin её не закрывал — сравнивать нечего, вопрос живой."""
    _publish(tree, _card(status="needs-owner"))
    _local(tree, _card(status="needs-owner"))

    doc = _report(tree)

    assert doc["pending_count"] == 1
    assert doc["closed_on_origin_open_here"]["drift"] == []


def test_a_question_absent_on_origin_is_still_a_question(tree):
    """Карточки на ref нет вовсе — это ФАКТ (её ещё не доставили), а не закрытие."""
    _publish(tree, _card(status="ingested"), card_id="owner-decision-drugaya-kartochka")
    _local(tree, _card(status="needs-owner"))   # наша карточка на origin не публиковалась

    doc = _report(tree)

    assert doc["pending_count"] == 1
    assert doc["closed_on_origin_open_here"]["measured"] is True
    assert doc["closed_on_origin_open_here"]["drift"] == []


# ── 3. ТРЕТИЙ ИСХОД: «не измерено» с названной причиной ─────────────────────


def test_unorderable_stamps_keep_the_card_and_say_UNMEASURED(tree):
    """origin закрыт, но БЕЗ отметки, а у нас отметка есть — порядок не устанавливается."""
    _publish(tree, _card(status="ingested"))
    _local(tree, _card(status="owner-accepted", answered_at=ANSWERED_AT,
                       trail=[(ANSWERED_AT, "needs-owner", "owner-accepted")]))

    doc = _report(tree)

    assert doc["accepted_count"] == 1, "карточка обязана остаться: молчание = fail-OPEN"
    assert doc["closed_on_origin_open_here"]["drift"] == []
    assert any(CARD_ID in str(u.get("check")) and "НЕ ИЗМЕРЕНО" in str(u.get("reason"))
               for u in doc["unchecked"]), doc["unchecked"]


def test_a_tracker_outside_git_is_UNMEASURED_not_clean(tmp_path):
    """«Сверять не с чем» не имеет права выглядеть как «дрейфа нет»."""
    tdir = tmp_path / "tracker"
    tdir.mkdir()
    (tdir / f"{CARD_ID}.md").write_text(_card(status="needs-owner"), encoding="utf-8")
    ddir = tmp_path / "data"
    ddir.mkdir()

    doc = odp.check_pending_owner_decisions(now=FIXED_NOW, data_dir=ddir, tracker_dir=tdir)

    assert doc["closed_on_origin_open_here"]["measured"] is False
    assert doc["closed_on_origin_open_here_count"] is None
    assert doc["pending_count"] == 1, "не измерено ⇒ карточка остаётся в очереди"
    assert "НЕ ИЗМЕРЕНО" in _office_lines(doc)


def test_office_step_calls_an_old_report_UNMEASURED_not_clean():
    """Отчёт старого образца не имеет права выглядеть как «дрейфа нет»."""
    old = {"status": "OK", "reason": "остановки нет"}

    assert "закрытые на origin, открытые здесь, НЕ ИЗМЕРЕНЫ" in _office_lines(old)


def test_office_step_says_so_when_there_is_no_drift(tree):
    """Обратный контроль строки: чисто — сказано ЧИСТО, а не промолчано."""
    _publish(tree, _card(status="needs-owner"))
    _local(tree, _card(status="needs-owner"))

    assert "открытых здесь карточек, закрытых на origin, нет" in _office_lines(_report(tree))


# ── 4. МЕРКА: одна на обе копии ────────────────────────────────────────────


def test_latest_change_at_takes_the_latest_of_trail_and_owner_answer():
    """Обе породы отметок обязательны: след пишет наш код, ответ владельца — бот."""
    text = _card(status="owner-accepted", answered_at=LATE_ANSWER_AT,
                 trail=[(ANSWERED_AT, "needs-owner", "owner-accepted")])

    assert sa.latest_change_at(text) == LATE_ANSWER_AT


def test_latest_change_at_is_None_when_the_card_never_moved():
    """«Свидетельств движения нет» — ФАКТ, а не сбой разбора."""
    assert sa.latest_change_at(_card(status="needs-owner")) is None


def test_latest_change_at_reads_a_Z_suffixed_stamp():
    """Отметки владельца приходят и с `Z`: сравнивать их как ТЕКСТ было бы ошибкой."""
    text = _card(status="needs-owner").replace(
        "source: nimbalyst", "source: nimbalyst\nowner_answered_at: 2026-08-29T20:30:00Z")

    stamp = sa.latest_change_at(text)  # FROZEN-DATE-OK: предмет теста — РАЗБОР отметки
    assert stamp is not None and stamp.tzinfo is not None and stamp.hour == 20
