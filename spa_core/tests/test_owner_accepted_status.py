#!/usr/bin/env python3
"""«Принято — беру в работу» ≠ «сделано». Три состояния очереди вместо двух (#350).

**Авария, которую воспроизводит каждый тест этого файла.** Карточка-ПОРУЧЕНИЕ
``owner-decision-snyat-mertvyi-adres-checkup-earn-defi-co`` просила владельца удалить
запись DNS и написать в чат «снял». Критерий приёмки записан в ней самой:
«``curl -I https://checkup.earn-defi.com/`` больше не отвечает ``404`` от Railway»;
обещание агента — «я проверю это сам и напишу результат».

===================  ===============================================================
22.08 20:29:33Z      владелец нажал «✅ Принято — беру в работу» ⇒ ``status: owner-done``
22.08 20:47Z         замер: ``curl`` по-прежнему отдаёт ``404 x-railway-fallback: true``
===================  ===============================================================

Карточка стала ТЕРМИНАЛЬНОЙ в момент, когда её собственный критерий приёмки не выполнен.
Обещанной перепроверки делать стало некому: пункт выбыл из очереди, а удалять запись
всё ещё некому, кроме владельца. Замер населения (#350): ack-закрытий в трекере на тот
день ровно ОДНО — и оно же авария. Не «редкий край», а сто процентов случаев.

**Класс знакомый:** механизм честно отвечает на СВОЙ вопрос («владелец ответил?») и
этим закрывает другой, которого никто не задавал («поручение исполнено?»).

**Что разведено.** Ответ владельца ведёт в один из ДВУХ статусов, и правило живёт
ровно в одном месте — :func:`owner_answer.status_for_answer`:

* выбор варианта → ``owner-done``. Ответ И ЕСТЬ результат, закрытие нажатием решено
  осознанно (ADR-075, решение владельца 08.08) — это **обратный контроль** здесь;
* «🚫 Не надо — не делаем» → ``owner-done``. Отказ тоже полон: ждать нечего;
* «✅ Принято — беру в работу» → ``owner-accepted``, **НЕтерминальный**.

**Инвариант #14 не ослаблен ни в одну сторону, и это проверяется.** Новый статус —
такой же owner-only, как ``owner-done``: агент не может ни поставить его
(``set_status`` отказывает), ни создать карточку в нём. Единственный выход из него
для агента — ``ingested``, то есть отчёт об исполнении.

Время — вход, а не окружение: ``FIXED_NOW`` передаётся всем писателям, литеральных дат
в фикстурах нет (дата 22.08 живёт в прозе — она предмет, а не поведение).
"""
from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from spa_core.monitoring import owner_decision_pending as odp
from spa_core.monitoring import tracker_status_sentinel as tss
from spa_core.owner_queue import origin_view, owner_answer
from spa_core.owner_queue import queue as qmod
from spa_core.telegram import alert_actions as aa
from spa_core.telegram import owner_decisions as od
from spa_core.tests._freshness import now_utc

FIXED_NOW = now_utc()

OWNER = "424242"
REF = "origin/main"

_HEAD = """---
trackerStatus:
  type: owner-decision
title: "Снять мёртвый адрес checkup.earn-defi.com"
status: needs-owner
created: 2026-08-22
---

## Что случилось и почему это важно

Поддомен `checkup` отвечает 404 от Railway — к домену он не привязан.

## Что от тебя нужно

"""

#: ПОРУЧЕНИЕ — списано с живой карточки 22.08: выбора нет, есть действие владельца
#: и критерий приёмки, проверить который может только агент ПОСЛЕ действия.
CARD_INSTRUCTION = _HEAD + (
    "Удали запись DNS `checkup` в Cloudflare и напиши в чат «снял».\n\n"
    "## Как понять, что готово\n\n"
    "`curl -I https://checkup.earn-defi.com/` больше не отвечает `404` от Railway.\n"
)

#: ВЫБОР — обратный контроль: здесь закрытие нажатием верно и решено (ADR-075).
CARD_OPTIONS = _HEAD + (
    "* **Вариант 1 (рекомендую) — снять запись.** Текст.\n"
    "* **Вариант 2 — оставить как есть.** Текст.\n"
)

CARD_ID = "owner-decision-snyat-mertvyi-adres-checkup-earn-defi-co"


# ── окружение (тот же шов, что у test_owner_decision_ack_button) ─────────────


def _git(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args],
                         capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.stderr}"
    return res.stdout


@pytest.fixture()
def env(tmp_path):
    root = tmp_path / "repo"
    (root / origin_view.TRACKER_REL).mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", REF, str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "test")
    beacon = tmp_path / "beacon.json"
    beacon.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot",
        "updated_at": (FIXED_NOW - timedelta(seconds=10)).isoformat(), "pid": 1,
        "capabilities": [aa.CAPABILITY],
    }), encoding="utf-8")
    return {
        "root": root,
        "tracker": root / origin_view.TRACKER_REL,
        "state": tmp_path / "telegram_owner_decisions.json",
        "beacon": beacon,
    }


def _write(env, body, name=CARD_ID) -> Path:
    p = env["tracker"] / f"{name}.md"
    p.write_text(body, encoding="utf-8")
    return p


def _commit(env):
    _git(env["root"], "add", "-A")
    _git(env["root"], "commit", "-q", "-m", "c")


def _push(env, card: Path, body):
    prep = od.register_push(card, "Снять мёртвый адрес checkup", body, now=FIXED_NOW,
                            state_path=env["state"], beacon_path=env["beacon"],
                            live_root=env["root"])
    live = json.loads(env["state"].read_text(encoding="utf-8"))["pushes"][-1]["card"]
    return prep, Path(live)


# ── 1. САМА АВАРИЯ 22.08 20:29Z ──────────────────────────────────────────────


def test_accept_does_not_close_the_instruction_card(env):
    """Положительный контроль: нажатие 22.08 20:29Z больше не делает карточку мёртвой."""
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)
    prep, live = _push(env, card, CARD_INSTRUCTION)

    res = od.record_choice(prep.pid, od.ACK_ACCEPT, OWNER, owner_chat_id=OWNER,
                           now=FIXED_NOW, state_path=env["state"])

    assert res["ok"] is True and res["kind"] == "ack"
    text = live.read_text(encoding="utf-8")
    assert "status: owner-accepted" in text
    assert "status: owner-done" not in text, (
        "карточка-ПОРУЧЕНИЕ стала терминальной при невыполненном критерии приёмки — "
        "ровно авария 22.08 20:29Z")
    # Ответ владельца записан полностью: «принято» — это ЕГО решение, и след его
    # личности не должен зависеть от того, терминальный статус или нет.
    assert "owner_choice: ack" in text
    assert "owner_answer_kind: ack" in text
    assert "**Принято — беру в работу**" in text


def test_the_card_body_says_the_card_is_still_open(env):
    """Приписка под ответом обязана быть правдой — её читает человек, а не фильтр."""
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)
    prep, live = _push(env, card, CARD_INSTRUCTION)

    od.record_choice(prep.pid, od.ACK_ACCEPT, OWNER, owner_chat_id=OWNER,
                     now=FIXED_NOW, state_path=env["state"])

    text = live.read_text(encoding="utf-8")
    assert "Карточка закрыта самим владельцем" not in text
    assert "owner-accepted" in text and "критерий приёмки" in text


def test_confirmation_to_the_owner_does_not_promise_a_closed_card(env):
    """Владелец узнаёт правду сразу в чате, а не через неделю по несделанному."""
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)
    prep, _ = _push(env, card, CARD_INSTRUCTION)

    res = od.record_choice(prep.pid, od.ACK_ACCEPT, OWNER, owner_chat_id=OWNER,
                           now=FIXED_NOW, state_path=env["state"])
    said = od.confirmation_text(res)

    assert "закрыта" not in said
    assert "остаётся открытой" in said
    assert "вариант" not in said.lower(), "выдуманный «вариант» — тот же обман"


# ── 2. ОБРАТНЫЕ КОНТРОЛИ: где закрытие нажатием верно, оно и осталось ────────


def test_decline_still_closes_the_card(env):
    """«Не надо» — полный ответ: после него не ждут ни действия, ни проверки."""
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)
    prep, live = _push(env, card, CARD_INSTRUCTION)

    res = od.record_choice(prep.pid, od.ACK_DECLINE, OWNER, owner_chat_id=OWNER,
                           now=FIXED_NOW, state_path=env["state"])

    assert "status: owner-done" in live.read_text(encoding="utf-8")
    assert "закрыта твоим решением" in od.confirmation_text(res)


def test_a_chosen_option_still_closes_the_card(env):
    """ADR-075 не тронут: для карточки-ВЫБОРА ответ И ЕСТЬ результат."""
    card = _write(env, CARD_OPTIONS)
    _commit(env)
    prep, live = _push(env, card, CARD_OPTIONS)

    od.record_choice(prep.pid, "1", OWNER, owner_chat_id=OWNER,
                     now=FIXED_NOW, state_path=env["state"])

    assert "status: owner-done" in live.read_text(encoding="utf-8")


def test_the_rule_lives_in_exactly_one_place():
    """Правило «что значит ответ для очереди» — одна функция, а не ветка в трёх."""
    assert owner_answer.status_for_answer(
        owner_answer.KIND_ACK, od.ACK_ACCEPT) == qmod.OWNER_ACCEPTED_STATUS
    assert owner_answer.status_for_answer(
        owner_answer.KIND_ACK, od.ACK_DECLINE) == qmod.OWNER_ONLY_STATUS
    assert owner_answer.status_for_answer(
        owner_answer.KIND_OPTION, "1") == qmod.OWNER_ONLY_STATUS
    # Незнакомый вид ответа ведёт себя как выбор — прежнее поведение. Новый вид не
    # имеет права молча получить НЕтерминальный статус и зависнуть в очереди.
    assert owner_answer.status_for_answer("нечто-новое", "1") == qmod.OWNER_ONLY_STATUS
    # Имена констант — из одного источника, а не две копии (#143–#145).
    assert od.ACK_ACCEPT is owner_answer.ACK_ACCEPT_CHOICE
    assert od.ACK_DECLINE is owner_answer.ACK_DECLINE_CHOICE


# ── 3. ИНВАРИАНТ #14: новый статус тоже ставит только владелец ───────────────


def test_invariant_14_agent_cannot_set_owner_accepted(tmp_path):
    """«Принято» — слово владельца. Агент не вправе сказать его за него."""
    card = tmp_path / f"{CARD_ID}.md"
    card.write_text(CARD_INSTRUCTION, encoding="utf-8")

    with pytest.raises(qmod.OwnerDoneForbidden):
        qmod.set_status(card, qmod.OWNER_ACCEPTED_STATUS)
    assert "status: needs-owner" in card.read_text(encoding="utf-8")


def test_invariant_14_agent_still_cannot_set_owner_done(tmp_path):
    """Обратный контроль: прежний запрет не ослаб ни на строку."""
    card = tmp_path / f"{CARD_ID}.md"
    card.write_text(CARD_INSTRUCTION, encoding="utf-8")

    with pytest.raises(qmod.OwnerDoneForbidden):
        qmod.set_status(card, qmod.OWNER_ONLY_STATUS)


def test_agent_cannot_create_a_card_already_accepted(tmp_path):
    """Иначе «принято владельцем» рождалось бы без владельца."""
    with pytest.raises(qmod.OwnerDoneForbidden):
        qmod.create_card("owner-decision", "т", "тело",
                         status=qmod.OWNER_ACCEPTED_STATUS, tracker_dir=tmp_path)


def test_ingested_is_the_agent_exit_from_accepted(env):
    """Единственный выход — ОТЧЁТ об исполнении, и он агенту разрешён."""
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)
    prep, live = _push(env, card, CARD_INSTRUCTION)
    od.record_choice(prep.pid, od.ACK_ACCEPT, OWNER, owner_chat_id=OWNER,
                     now=FIXED_NOW, state_path=env["state"])
    assert f"status: {qmod.OWNER_ACCEPTED_STATUS}" in live.read_text(encoding="utf-8"), (
        "иначе тест проверяет выход не из того состояния и зелен по совпадению")

    qmod.set_status(live, "ingested")

    assert "status: ingested" in live.read_text(encoding="utf-8")


def test_accepted_card_counts_as_OPEN_for_duplicate_detection(env):
    """Принятое поручение — открытая работа: второй такой же вопрос заводить нельзя."""
    assert qmod.OWNER_ACCEPTED_STATUS in qmod._OPEN_STATUSES


# ── 4. ОЧЕРЕДЬ ВИДИТ третье состояние, а не теряет его ──────────────────────


def _report(env, tmp_path, statuses):
    """Отчёт «путь вверх» по каталогу с карточками заданных статусов."""
    ddir = tmp_path / "data"
    ddir.mkdir(exist_ok=True)
    tdir = tmp_path / "tracker"
    tdir.mkdir(exist_ok=True)
    for i, st in enumerate(statuses):
        body = CARD_INSTRUCTION.replace("status: needs-owner", f"status: {st}")
        body = body.replace("---\n\n## Что случилось",
                            f"owner_answered_at: {FIXED_NOW.isoformat()}\n---\n\n## Что случилось")
        (tdir / f"{CARD_ID}-{i}.md").write_text(body, encoding="utf-8")
    return odp.check_pending_owner_decisions(now=FIXED_NOW, data_dir=ddir,
                                             tracker_dir=tdir)


def test_accepted_card_is_not_a_question_to_the_owner(env, tmp_path):
    """Владелец ответил — слать ему тот же вопрос снова нельзя."""
    doc = _report(env, tmp_path, [qmod.OWNER_ACCEPTED_STATUS])

    assert doc["pending_count"] == 0
    assert not any("ждут ответа" in s for s in doc["issues"])


def test_accepted_card_is_named_and_not_lost(env, tmp_path):
    """И не «закрыта»: у обещания обязан быть читатель — иначе всё это зря."""
    doc = _report(env, tmp_path, [qmod.OWNER_ACCEPTED_STATUS])

    assert doc["accepted_count"] == 1
    assert doc["accepted"][0]["card_id"] == f"{CARD_ID}-0"
    assert doc["accepted"][0]["accepted_at"] == FIXED_NOW.isoformat()
    assert "принятых поручений в работе: 1" in doc["reason"]


def test_accepted_card_is_not_silently_unmeasured(env, tmp_path):
    """Незнакомый статус попадал бы в «НЕ ИЗМЕРЕНО» — это шум, а не находка."""
    doc = _report(env, tmp_path, [qmod.OWNER_ACCEPTED_STATUS])

    assert not any(f"{CARD_ID}-0" in str(u.get("check")) for u in doc["unchecked"])


def test_a_waiting_question_is_still_counted(env, tmp_path):
    """Обратный контроль: настоящий вопрос владельцу не растворился в новом ведре."""
    doc = _report(env, tmp_path, ["needs-owner"])

    assert doc["pending_count"] == 1
    assert doc["accepted_count"] == 0
    assert "принятых поручений" not in doc["reason"]


# ── 5. ШАГ 0-ОФИС: обещание печатается там, где его читают ──────────────────


def _office_lines(doc):
    from scripts.consume_office_reports import _summarize_json

    return "\n".join(_summarize_json("owner_decision_pending.json", doc))


def test_office_step_prints_the_accepted_promise(env, tmp_path):
    doc = _report(env, tmp_path, [qmod.OWNER_ACCEPTED_STATUS])

    text = _office_lines(doc)

    assert "принято владельцем, НЕ ИСПОЛНЕНО" in text
    assert f"{CARD_ID}-0" in text


def test_office_step_says_so_when_there_is_nothing_to_report(env, tmp_path):
    doc = _report(env, tmp_path, ["needs-owner"])

    assert "принятых и неисполненных поручений нет" in _office_lines(doc)


def test_office_step_calls_an_old_report_UNMEASURED_not_clean():
    """Отчёт старого образца не имеет права выглядеть как «принятых поручений нет»."""
    old = {"status": "OK", "reason": "остановки нет"}

    assert "принятые поручения НЕ ИЗМЕРЕНЫ" in _office_lines(old)


# ── 6. СТОРОЖ ПЕРЕХОДОВ: обход писателя слышен для ОБОИХ owner-only ─────────


def test_sentinel_treats_forged_acceptance_as_critical():
    """Иначе «принято владельцем» можно было бы подделать под WARN."""
    assert tss._severity("new", qmod.OWNER_ACCEPTED_STATUS) == "CRITICAL"
    assert tss._severity("in-progress", qmod.OWNER_ACCEPTED_STATUS) == "CRITICAL"


def test_sentinel_still_shouts_about_owner_done():
    """Обратный контроль: прежняя громкость не потерялась."""
    assert tss._severity("new", "owner-done") == "CRITICAL"
    assert tss._severity("needs-owner", "ingested") == "CRITICAL"
    assert tss._severity("new", "in-progress") == "WARN"


def test_sentinel_reads_the_owner_only_set_from_the_queue():
    """Два разъехавшихся перечня — способ замолчать ровно о новом члене класса."""
    assert tss.OWNER_ONLY_STATUSES == qmod.OWNER_ONLY_STATUSES


# ── 7. ОТВЕТ ВЛАДЕЛЬЦА ВИДЕН ИЗ ЛЮБОГО ДЕРЕВА (не повторяем #231) ───────────


@pytest.fixture()
def trees(tmp_path):
    """Прод-дерево + линкованный worktree — та же расстановка, что у #231.

    Настоящие git-деревья, а не подменённый ``_worktree_dirs``: проверяется ЭФФЕКТ,
    а не заглушка (тот же принцип, что в ``test_owner_answer_cross_tree``).
    """
    main = tmp_path / "prod"
    (main / origin_view.TRACKER_REL).mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", REF, str(main))
    _git(main, "config", "user.email", "t@example.com")
    _git(main, "config", "user.name", "test")
    (main / origin_view.TRACKER_REL / f"{CARD_ID}.md").write_text(
        CARD_INSTRUCTION, encoding="utf-8")
    _git(main, "add", "-A")
    _git(main, "commit", "-q", "-m", "вопрос владельцу")

    wt = tmp_path / "wt"
    _git(main, "worktree", "add", "-q", "--detach", str(wt), REF)
    return main, wt


def _accepted_body() -> str:
    """Карточка ровно в том виде, в каком её оставляет нажатие «✅ Принято»."""
    body = CARD_INSTRUCTION.replace("status: needs-owner",
                                    f"status: {qmod.OWNER_ACCEPTED_STATUS}")
    return body.replace(
        "created: 2026-08-22\n",
        f"created: 2026-08-22\nowner_choice: ack\n"
        f"owner_answered_at: {FIXED_NOW.isoformat()}\n")


def test_an_accepted_answer_in_the_main_tree_is_visible_from_a_worktree(trees):
    """Пропустить `owner-accepted` здесь = вернуть #231 для целого КЛАССА ответов."""
    main, wt = trees
    (main / origin_view.TRACKER_REL / f"{CARD_ID}.md").write_text(
        _accepted_body(), encoding="utf-8")

    verdict, found, why = owner_answer.scan_owner_answers_elsewhere(
        wt / origin_view.TRACKER_REL, now=FIXED_NOW)

    assert verdict == owner_answer.CROSS_FOUND, why
    assert [f.card_id for f in found] == [CARD_ID]


def test_a_worktree_that_already_shows_the_acceptance_is_not_a_finding(trees):
    """Обратный контроль: видимый ответ — не находка, иначе сторож звонит на верном."""
    main, wt = trees
    (main / origin_view.TRACKER_REL / f"{CARD_ID}.md").write_text(
        _accepted_body(), encoding="utf-8")
    (wt / origin_view.TRACKER_REL / f"{CARD_ID}.md").write_text(
        _accepted_body(), encoding="utf-8")

    verdict, found, _why = owner_answer.scan_owner_answers_elsewhere(
        wt / origin_view.TRACKER_REL, now=FIXED_NOW)

    assert verdict == owner_answer.CROSS_AGREES and found == []


# ── 8. ДОСКА: обещание стоит наверху, а не среди закрытых ───────────────────


def test_board_puts_the_promise_near_the_top_and_not_among_the_closed():
    from scripts.build_tracker_board import STATUS_ORDER, TERMINAL_STATUSES

    assert qmod.OWNER_ACCEPTED_STATUS not in TERMINAL_STATUSES, (
        "терминальный статус снимает захват — принятое поручение мгновенно "
        "выглядело бы свободным для второй сессии")
    assert STATUS_ORDER.index(qmod.OWNER_ACCEPTED_STATUS) < STATUS_ORDER.index("ingested")
