#!/usr/bin/env python3
"""Ремонт кнопок спрашивает ИСТОЧНИК ПРАВДЫ, а не отставшую копию.

КАЖДЫЙ тест — положительный контроль состояния **22.08.2026**, замеренного шагом
0-офис цикла #347:

    `own-2026-08-19-sudba-voronki-chekapa-i-kanal-zayavok` (priority `high`) стоит
    перед владельцем БЕЗ КНОПОК с 19.08. Причина названа сторожем точно —
    `card_stale_vs_origin`: в живой копии вариантов нет, на `origin/main` их два.

    Лекарство от ровно этого состояния доставлено циклом #339
    (`refresh_live_copy_from_ref`, четыре условия, след ответа владельца не
    затирается никогда) — и до ЭТОЙ карточки не доехало бы никогда. Проводка #339
    стоит на `notify_needs_owner` и `materialize_card`, то есть на ОТПРАВКЕ. А
    вопрос уже отправлен (22.08 09:14:44Z, код #339 приземлился в проде в 10:58):
    `notify` по нему больше не пойдёт — звать владельца ради своей же недоставки
    запрещено (ADR-084). Единственный оставшийся путь — штатный ремонт
    `heal_buttonless`, а он читал ТОЛЬКО живую копию, получал честный отказ о ней
    и молчал.

Класс тот же, что весь #146–#343: путь отвечает на СВОЙ вопрос («что в этом
файле?») вместо нужного («что в очереди?»). Очередь живёт на `origin/main`, а в
прод-дерево её не возит никто (#193) — значит «вариантов нет» в живой копии ещё
не ответ.

**Закреплено обеими сторонами.** Отставшая копия — обновляется и владелец получает
свой выбор; копия со следом ответа владельца не затирается ни при каком
расхождении, «не измерено» зелёным светом не считается, а на здоровом пути git не
трогается вовсе (ремонт крутится в `run_once` бота каждую итерацию поллинга).

Фикстуры — настоящие крошечные git-репозитории без сети, как в
`test_owner_decision_stale_live_copy.py`. Литеральных дат нет: время — вход.
"""
from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from pathlib import Path

import pytest

from spa_core.owner_queue import origin_view
from spa_core.telegram import alert_actions as aa
from spa_core.telegram import owner_decisions as od
from spa_core.tests._freshness import now_utc

FIXED_NOW = now_utc()
#: Ветка источника. Рабочая копия — КЛОН, поэтому сверка находит её как `origin/main`.
REF = "main"

DEAD = aa.BEACON_MAX_AGE_S + 60   # бот лежал в момент отправки — кнопок не было
ALIVE = 10.0                      # бот жив сейчас — чинить есть чем

TITLE = "Судьба чекапа — воронка ведёт в никуда"
CARD_NAME = "own-2026-08-19-sudba-voronki.md"

#: Тело на ref: варианты перечислены и разбираются.
_WITH_OPTIONS = (
    "## Что случилось и почему это важно\n\n"
    "Воронка чекапа ведёт в никуда, канал заявок молчит.\n\n"
    "## Что от тебя нужно\n\n"
    "- **Вариант 1 (⭐ рекомендую) — похоронить.** Снять разделы с сайта.\n"
    "- **Вариант 2 — воскресить.** Достроить канал заявок и оживить воронку.\n"
)
#: Тело живой копии: тот же вопрос ПРОЗОЙ. Ровно замер карточки
#: `inbox-storozh-knopok-obyavlyaet-v-kartochke-ne`: это ВЫБОР
#: (`looks_like_a_choice=True`), но разобрать из него нельзя ни одного варианта —
#: значит и подтверждения не предложить (оно спрятало бы выбор, ADR-075), и
#: клавиатуры не собрать. Именно это состояние стоит перед владельцем с 19.08.
_WITHOUT_OPTIONS = (
    "## Что случилось и почему это важно\n\n"
    "Воронка чекапа ведёт в никуда, канал заявок молчит.\n\n"
    "## Что от тебя нужно\n\n"
    "Вариант 1 — похоронить. Вариант 2 — воскресить. Выбери один.\n"
)


def _card_text(body: str, *, status: str = "needs-owner", answer: bool = False) -> str:
    head = ["---", "trackerStatus:", "  type: owner-decision",
            f'title: "{TITLE}"', f"status: {status}"]
    if answer:
        head += ["owner_choice: '1'",
                 f"owner_answered_at: '{FIXED_NOW.isoformat()}'",
                 "owner_answer_via: telegram", "owner_answered_by: owner"]
    return "\n".join(head) + "\n---\n\n" + body


def _git(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.returncode}: {res.stderr}"
    return res.stdout


def _beacon(directory: Path, *, age_s: float) -> Path:
    """Маячок обработчика нажатий указанного ВОЗРАСТА."""
    directory.mkdir(parents=True, exist_ok=True)
    p = directory / "beacon.json"
    p.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot",
        "updated_at": (FIXED_NOW - timedelta(seconds=age_s)).isoformat(), "pid": 1,
        "capabilities": [aa.CAPABILITY],
    }), encoding="utf-8")
    return p


class Sender:
    """Отправитель вызывающего: копит (text, keyboard). ``ok`` — успех отправки."""

    def __init__(self, ok=True):
        self.sent = []
        self.ok = ok

    def __call__(self, text, keyboard):
        self.sent.append((text, keyboard))
        return {"ok": True, "result": {"message_id": 4242}} if self.ok else None


@pytest.fixture()
def env(tmp_path):
    """Журнал пушей + два маячка + место под пару репозиториев. Сети не касается."""
    return {
        "tmp": tmp_path,
        "state": tmp_path / "telegram_owner_decisions.json",
        "dead": _beacon(tmp_path / "beacon-dead", age_s=DEAD),
        "alive": _beacon(tmp_path / "beacon-alive", age_s=ALIVE),
    }


def _publish(env, body_on_ref: str, *, ref_status: str = "needs-owner",
             ref_answer: bool = False) -> Path:
    """Карточка на `origin/main` + рабочая копия рядом. Возвращает путь живой копии.

    Настоящий КЛОН, а не ветка с похожим именем: сверка ходит в `origin/main`
    именем по умолчанию, и подменять это имя параметром значило бы проверять не
    тот путь, которым ходит бот. Сети клон не касается — источник лежит рядом
    в `tmp_path`.
    """
    src = env["tmp"] / "src"
    (src / origin_view.TRACKER_REL).mkdir(parents=True)
    _git(env["tmp"], "init", "-q", "-b", REF, str(src))
    _git(src, "config", "user.email", "t@example.com")
    _git(src, "config", "user.name", "test")
    (src / origin_view.TRACKER_REL / CARD_NAME).write_text(
        _card_text(body_on_ref, status=ref_status, answer=ref_answer), encoding="utf-8")
    _git(src, "add", "-A")
    _git(src, "commit", "-q", "-m", "card")

    root = env["tmp"] / "repo"
    _git(env["tmp"], "clone", "-q", str(src), str(root))
    env["root"] = root
    return root / origin_view.TRACKER_REL / CARD_NAME


def _live(card: Path, body: str, **kw) -> Path:
    """Переписать ЖИВУЮ копию (коммит остаётся прежним) — расхождение с ref."""
    card.write_text(_card_text(body, **kw), encoding="utf-8")
    return card


def _push(env, card: Path, body: str):
    """Отправка при ЛЕЖАЩЕМ боте: запись получает `buttons is False`."""
    return od.register_push(card, TITLE, body, now=FIXED_NOW,
                            state_path=env["state"], beacon_path=env["dead"])


def _heal(env, *, send=None):
    send = send or Sender()
    fixed = od.heal_buttonless(send, now=FIXED_NOW, state_path=env["state"],
                               beacon_path=env["alive"])
    return fixed, send


def _rec(env, pid):
    doc = json.loads(env["state"].read_text(encoding="utf-8"))
    for r in doc["pushes"]:
        if r.get("pid") == pid:
            return r
    return None


# ===========================================================================
# ЯДРО: ремонт спрашивает ref и владелец получает свой выбор
# ===========================================================================
def test_the_repair_asks_the_ref_and_the_owner_gets_his_buttons(env):
    """Ровно 22.08: копия отстала, вопрос уже уехал — до починки лечить было нечем."""
    card = _publish(env, _WITH_OPTIONS)
    _live(card, _WITHOUT_OPTIONS)
    prep = _push(env, card, _WITHOUT_OPTIONS)
    assert prep.keyboard is None                      # кнопок не было — это и чиним
    assert od.parse_options(card.read_text(encoding="utf-8")) == []

    fixed, send = _heal(env)

    assert fixed == [prep.pid], "ремонт снова промолчал — копию так и не переспросили"
    labels = [row[0]["text"] for row in send.sent[0][1]["inline_keyboard"]]
    assert any(lbl.startswith("⭐ 1.") for lbl in labels)
    assert any(lbl.startswith("2.") for lbl in labels)
    # ЭФФЕКТ на файле, а не только на сообщении: копия догнала источник правды.
    assert len(od.parse_options(card.read_text(encoding="utf-8"))) == 2


def test_the_healed_text_carries_the_options_from_the_ref(env):
    """В сообщении — варианты С REF; в живой копии их не было ни одного."""
    card = _publish(env, _WITH_OPTIONS)
    _live(card, _WITHOUT_OPTIONS)
    _push(env, card, _WITHOUT_OPTIONS)

    _, send = _heal(env)

    text = send.sent[0][0].lower()
    assert "похоронить" in text and "воскресить" in text
    assert "кнопки подъехали" in text


def test_the_press_lands_in_the_card_after_the_repair(env):
    """Кнопка не декоративна: нажатие по досланному варианту пишется в карточку."""
    card = _publish(env, _WITH_OPTIONS)
    _live(card, _WITHOUT_OPTIONS)
    prep = _push(env, card, _WITHOUT_OPTIONS)
    _heal(env)

    res = od.record_choice(prep.pid, "2", 777, owner_chat_id=777,
                           now=FIXED_NOW, state_path=env["state"])

    assert res["ok"] is True, res
    assert res["choice"] == "2"
    assert "owner_choice" in card.read_text(encoding="utf-8")


def test_the_repair_marks_the_record_and_does_not_repeat(env):
    """Одна починка на решение: подъём бота не превращается в очередь дублей."""
    card = _publish(env, _WITH_OPTIONS)
    _live(card, _WITHOUT_OPTIONS)
    prep = _push(env, card, _WITHOUT_OPTIONS)

    first, _ = _heal(env)
    second, send2 = _heal(env)

    assert first == [prep.pid]
    assert second == []
    assert send2.sent == []
    assert _rec(env, prep.pid)["buttons_fixed_at"]


# ===========================================================================
# ОБРАТНЫЕ КОНТРОЛИ: где ремонту трогать копию НЕЛЬЗЯ
# ===========================================================================
def test_owner_answer_in_the_live_copy_is_never_overwritten(env):
    """Слепая перезапись — та же авария в другую сторону. Ответ владельца свят."""
    card = _publish(env, _WITH_OPTIONS)
    _live(card, _WITHOUT_OPTIONS, answer=True)
    before = card.read_text(encoding="utf-8")
    _push(env, card, _WITHOUT_OPTIONS)

    fixed, send = _heal(env)

    assert fixed == []
    assert send.sent == []
    assert card.read_text(encoding="utf-8") == before


def test_ref_without_options_leaves_the_live_copy_alone(env):
    """На ref вариантов тоже нет ⇒ обновлять нечего, отказ прежний и верный."""
    card = _publish(env, _WITHOUT_OPTIONS)
    _live(card, _WITHOUT_OPTIONS)
    before = card.read_text(encoding="utf-8")
    _push(env, card, _WITHOUT_OPTIONS)

    fixed, send = _heal(env)

    assert fixed == []
    assert send.sent == []
    assert card.read_text(encoding="utf-8") == before


def test_question_closed_on_the_ref_is_not_healed(env):
    """На ref вопрос уже закрыт — досылать кнопки к закрытому запрещено."""
    card = _publish(env, _WITH_OPTIONS, ref_status="ingested")
    _live(card, _WITHOUT_OPTIONS)
    before = card.read_text(encoding="utf-8")
    _push(env, card, _WITHOUT_OPTIONS)

    fixed, send = _heal(env)

    assert fixed == []
    assert send.sent == []
    assert card.read_text(encoding="utf-8") == before


def test_unmeasured_ref_is_not_a_green_light(env, tmp_path):
    """Карточка вне git: сверка НЕ ВЫПОЛНИЛАСЬ ⇒ молчим, а не «всё в порядке»."""
    outside = tmp_path / "outside"
    outside.mkdir()
    card = outside / CARD_NAME
    card.write_text(_card_text(_WITHOUT_OPTIONS), encoding="utf-8")
    before = card.read_text(encoding="utf-8")
    _push(env, card, _WITHOUT_OPTIONS)

    fixed, send = _heal(env)

    assert fixed == []
    assert send.sent == []
    assert card.read_text(encoding="utf-8") == before


def test_a_card_that_already_parses_options_never_touches_the_ref(env, monkeypatch):
    """Здоровый путь ничего не платит: варианты есть ⇒ git не трогаем вовсе.

    Ремонт крутится в `run_once` бота КАЖДУЮ итерацию поллинга, а сверка с ref —
    это `git ls-tree` по всему каталогу очереди. Ставить её на путь, где ответ уже
    известен, значило бы чинить одну аварию ценой другой.
    """
    card = _publish(env, _WITH_OPTIONS)
    prep = _push(env, card, _WITH_OPTIONS)
    assert prep.keyboard is None            # кнопок нет ПРО ОБРАБОТЧИКА, не про тело
    calls = []
    monkeypatch.setattr(od, "refresh_live_copy_from_ref",
                        lambda *a, **k: calls.append(a) or {"verdict": od.REFRESH_DONE})

    # Маячок ЛЕЖИТ и на починке — кнопок по-прежнему нет, но не из-за тела карточки.
    od.heal_buttonless(Sender(), now=FIXED_NOW, state_path=env["state"],
                       beacon_path=env["dead"])

    assert calls == [], "сверка с ref ушла на здоровый путь"
