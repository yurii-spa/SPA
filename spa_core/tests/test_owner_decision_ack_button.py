#!/usr/bin/env python3
"""На карточку-ПОРУЧЕНИЕ владельцу есть чем ответить с телефона (ADR-115).

Каждый тест здесь — положительный контроль измеренной аварии, а не украшение.

**Что случилось.** Замер цикла #197 (10.08) по журналу отправок: пять карточек
владельца — `owner-decision-reshenie-po-alertu-spa-7-day-checkpoint` и четыре
`...kritichnaya-nahodka-petli-*` — ушли 08.08 и за двое суток не получили НИ ОДНОГО
ответа. Все пять — поручения («сделай то-то») или сообщения о находке: секция «Что от
тебя нужно» вариантов не предлагает. Разбор вёл себя ПРАВИЛЬНО — вариантов нет,
выдумывать их запрещено (ADR-075), — и владелец получал текст «Вариантов в карточке не
нашёл», на который ответить можно только словами. Молчание в этом состоянии неотличимо
от «не увидел». На 21.08 22:52Z (`data/owner_decision_pending.json`) в этом же
состоянии висели три вопроса.

**Что чиним.** Карточке без выбора полагается пара кнопок «✅ Принято» / «🚫 Не надо».
Это НЕ выдуманный вариант: выдуманный вариант — подсунуть владельцу выбор между
действиями, которых карточка не предлагала, а здесь выбора нет вовсе и есть согласие с
уже сформулированным поручением.

**Инвариант #14 не ослаблен, и это проверяется** (`test_invariant_14_*`): кнопку жмёт
владелец, запись идёт единственным owner-путём `owner_answer.record_owner_answer` с
проверкой личности ВНУТРИ писателя, а `queue.set_status` по-прежнему отказывает агенту.
Прецедент — ADR-082 (ответ владельца текстом): канал другой, решение то же.

**Границы узкие (fail-CLOSED) и закреплены обратными контролями:**

* варианты разобрались · написаны, но не разобрались (`has_unparsed_options`) ·
  карточка разрешает выбрать несколько — кнопок подтверждения НЕТ, иначе «Принято»
  ПРЯЧЕТ настоящий выбор;
* **и главное — выбора не должно быть не только здесь, но и на источнике правды.**
  Каталог очереди автосинком не возится, прод-дерево штатно отстаёт от `origin/main`:
  замер 21.08 на живой `own-33` — в дереве проза, на origin ДВА варианта, дописанные
  через 52 минуты после отправки. Раньше ценой расхождения было «кнопок нет» (видно и
  безобидно); с подтверждением ценой стало бы «карточка закрыта ответом на вопрос,
  которого владелец не видел». Поэтому сверка обязательна, а её неудача —
  МОЛЧАНИЕ (`test_ack_is_refused_*`).

**Заодно — соседняя авария, измеренная тем же заходом** (`test_heal_*`): досылка кнопок
`heal_buttonless` не обновляла варианты в журнале. Живой сценарий 21.08 (`own-33`):
пуш без вариантов → карточка получает их через 52 минуты → досылка рисует «1»/«2» →
нажатие отвечает «Такого варианта в этой карточке нет». Кнопка, ведущая в никуда, — та
самая жалоба владельца, ради которой досылку и писали.

Фикстуры сверки — настоящие крошечные git-репозитории (без сети): проверяется ЭФФЕКТ
на git, а не подменённая заглушка. Время — вход, а не окружение: маячок ставится
относительно ``FIXED_NOW``, литеральных дат в фикстурах нет.
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

OWNER = "424242"
STRANGER = "999999"

#: Ветка, которую сверка считает источником правды. Имя со слешем — законное имя
#: ветки, и `git rev-parse` резолвит его так же, как настоящий remote-ref.
#: Литералом, а не `od.ACK_REF`: во-первых, смена константы обязана быть ЗАМЕЧЕНА
#: (тест ниже), во-вторых, обращение к ней на уровне модуля роняло бы весь файл при
#: сборе на дереве без неё — а один error сбора красит прогон целиком.
REF = "origin/main"

_HEAD = """---
trackerStatus:
  type: owner-decision
title: "Тревога com.spa.digest — требует реакции"
status: needs-owner
created: 2026-08-08
---

## Что случилось и почему это важно

Агент дайджеста молчит вторые сутки, и об этом не сказал ни один пульс.

## Что от тебя нужно

"""

#: Карточка-ПОРУЧЕНИЕ: выбора нет ни в каком виде. Ровно форма тех пяти от 08.08.
CARD_INSTRUCTION = _HEAD + (
    "Перезапусти агента `com.spa.digest` и подтверди, что дайджест пришёл.\n"
)

#: Варианты РАЗОБРАНЫ — подтверждению здесь не место (обратный контроль).
CARD_OPTIONS = _HEAD + (
    "* **Вариант 1 (рекомендую) — перезапустить агента.** Текст.\n"
    "* **Вариант 2 — вывести агента из флота.** Текст.\n"
)

#: Варианты НАПИСАНЫ, но разбор их не взял. Кнопка «Принято» спрятала бы выбор.
#:
#: НАМЕРЕННАЯ правка фикстуры, цикл #351 (инв. #16 — ни одно утверждение теста не тронуто).
#: Прежний текст был двумя строками «Вариант 1: …» / «Вариант 2: …», и он попадал сюда лишь
#: потому, что разбор не знал формы БЕЗ жирного. Теперь знает (замер по 609 живым карточкам:
#: кнопки появились у 2, пропали у 0), и прежняя фикстура перестала изображать состояние,
#: ради которого написана, — она стала разбираемой. Взята ДРУГАЯ форма того же состояния,
#: и она не случайная: это ПРОЗА в одну строку, которую разбор отвергает по правилу
#: «вторая метка в строке ⇒ это не перечень» — иначе владелец получил бы ОДНУ кнопку там,
#: где карточка предлагает две. Предмет теста прежний: выбор написан, кнопок собрать нельзя,
#: и «Принято» его бы спрятало.
CARD_UNPARSED = _HEAD + (
    "Вариант 1 — перезапустить агента. Вариант 2 — вывести его из флота. Выбери один.\n"
)

#: Карточка разрешает взять НЕСКОЛЬКО пунктов — кнопкой это не выразить.
CARD_MULTI = _HEAD + (
    "Выбери, как поступаем — можно взять несколько:\n"
    "* перезапустить агента;\n"
    "* завести карточку на разбор.\n"
)

#: Выбор, записанный БУКВАМИ внутри «Решения 1» — узкий `has_unparsed_options` его
#: не видит. Тело списано с живой `own-2026-08-19-sudba-voronki-chekapa-i-kanal-zayavok`
#: (открыта на 21.08). Замер по очереди показал, что это ЕДИНСТВЕННАЯ из пяти открытых
#: карточек, которую узкая проверка пропускала, — то есть подтверждение сработало бы
#: ровно там, где оно прячет настоящий выбор.
CARD_LETTERED = _HEAD + (
    "**Решение 1 — судьба чекапа.** Варианты:\n"
    "- **(а) Похоронить.** Признать продукт закрытым.\n"
    "- **(б) Воскресить.** Поднять сервис заново.\n"
)

#: Форма тех самых пяти карточек от 08.08, ради которых всё и делается (списана с
#: `owner-decision-kritichnaya-nahodka-petli-com-spa-digest` дословно по структуре).
CARD_FINDING_2026_08_08 = (
    "## Что случилось и почему это важно\n"
    "Сторож петли (architecture_conformance) нашёл КРИТИЧНОЕ расхождение с "
    "архитектурой: com.spa.digest_weekly работает при intent=retired\n\n"
    "## Что от тебя нужно\n"
    "Посмотреть находку и решить: чиним / принимаем осознанно (тогда фиксируем "
    "решение в манифесте или ADR). Рекомендация агента — чинить.\n\n"
    "## Как понять, что готово\n"
    "Находка исчезает из data/architecture_conformance.json.\n"
)

CARD_ID = "owner-decision-kritichnaya-nahodka-petli-com-spa-digest"


# ── окружение ────────────────────────────────────────────────────────────────


def _git(cwd, *args):
    res = subprocess.run(["git", "-C", str(cwd), *args],
                         capture_output=True, text=True)
    assert res.returncode == 0, f"git {' '.join(args)} -> {res.stderr}"
    return res.stdout


def _beacon(root, name, *, age_s: float):
    p = root / name
    p.write_text(json.dumps({
        "schema_version": 1, "source": "telegram_bot",
        "updated_at": (FIXED_NOW - timedelta(seconds=age_s)).isoformat(), "pid": 1,
        "capabilities": [aa.CAPABILITY],
    }), encoding="utf-8")
    return p


DEAD = aa.BEACON_MAX_AGE_S + 60
ALIVE = 10.0


@pytest.fixture()
def env(tmp_path):
    """Крошечный репозиторий с каталогом очереди и веткой-источником правды."""
    root = tmp_path / "repo"
    (root / origin_view.TRACKER_REL).mkdir(parents=True)
    _git(tmp_path, "init", "-q", "-b", REF, str(root))
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "test")
    return {
        "root": root,
        "tracker": root / origin_view.TRACKER_REL,
        "state": tmp_path / "telegram_owner_decisions.json",
        "alive": _beacon(tmp_path, "beacon-alive.json", age_s=ALIVE),
        "dead": _beacon(tmp_path, "beacon-dead.json", age_s=DEAD),
    }


def _write(env, body, name=CARD_ID) -> Path:
    p = env["tracker"] / f"{name}.md"
    p.write_text(body, encoding="utf-8")
    return p


def _commit(env, msg="c"):
    _git(env["root"], "add", "-A")
    _git(env["root"], "commit", "-q", "-m", msg)


def _push(env, card: Path, body):
    """Отправка через ту же дверь, что и прод (`register_push` → `prepare_push`)."""
    prep = od.register_push(card, "Тревога com.spa.digest", body, now=FIXED_NOW,
                            state_path=env["state"], beacon_path=env["alive"],
                            live_root=env["root"])
    live = json.loads(env["state"].read_text(encoding="utf-8"))["pushes"][-1]["card"]
    return prep, Path(live)


def _push_dead(env, card: Path, body):
    prep = od.register_push(card, "Тревога com.spa.digest", body, now=FIXED_NOW,
                            state_path=env["state"], beacon_path=env["dead"],
                            live_root=env["root"])
    live = json.loads(env["state"].read_text(encoding="utf-8"))["pushes"][-1]["card"]
    return prep, Path(live)


def _rec(env, pid):
    doc = json.loads(env["state"].read_text(encoding="utf-8"))
    return next(r for r in doc["pushes"] if r.get("pid") == pid)


class Sender:
    def __init__(self, ok=True):
        self.sent = []
        self.ok = ok

    def __call__(self, text, keyboard):
        self.sent.append((text, keyboard))
        return {"ok": True} if self.ok else None


# ── 1. сама авария: поручению есть чем ответить ──────────────────────────────


def test_instruction_card_gets_accept_and_decline_buttons(env):
    """Повтор 08.08: карточка-поручение уходит владельцу. Раньше — тупик."""
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)

    prep, _ = _push(env, card, CARD_INSTRUCTION)

    assert prep.ack is True
    assert prep.keyboard is not None, "поручение уехало бы снова без единой кнопки"
    labels = [row[0]["text"] for row in prep.keyboard["inline_keyboard"]]
    assert labels == [od.ACK_BUTTONS[od.ACK_ACCEPT],
                      od.ACK_BUTTONS[od.ACK_DECLINE], "📖 Подробнее"]
    assert all(prep.pid in row[0]["callback_data"]
               for row in prep.keyboard["inline_keyboard"])


def test_instruction_text_does_not_invent_options(env):
    """ADR-075: подтверждение — не вариант. В тексте нет ни «Варианты:», ни номеров."""
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)

    prep, _ = _push(env, card, CARD_INSTRUCTION)

    assert "<b>Варианты:</b>" not in prep.text
    assert "Выбора в карточке нет" in prep.text
    assert "Вариантов в карточке не нашёл" not in prep.text


def test_a_card_not_yet_on_the_ref_may_still_be_confirmed(env):
    """Карточки на ref НЕТ — это измеренное отсутствие, а не неудача сверки.

    Свежее нашей копии не существует, отставать не от чего.
    """
    _write(env, CARD_OPTIONS, name="own-other")   # ref существует и разрешается…
    _commit(env)
    card = _write(env, CARD_INSTRUCTION)          # …а этой карточки на нём ещё нет

    ok, why = od.ack_allowed(card, CARD_INSTRUCTION)

    assert ok is True, why


def test_dead_bot_still_promises_nothing(env):
    """Маячок молчит ⇒ кнопок нет, и текст их НЕ обещает (урок 08.08)."""
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)

    prep, _ = _push_dead(env, card, CARD_INSTRUCTION)

    assert prep.keyboard is None
    assert prep.ack is True, "режим карточки — свойство карточки, а не маячка"
    assert "Принято" not in prep.text
    assert "Вариантов в карточке не нашёл" in prep.text


# ── 2. fail-CLOSED сверки: отставшая копия не закрывается подтверждением ─────


def test_ack_is_refused_when_the_ref_copy_has_options(env):
    """ЯДРО: живой `own-33` (21.08) — в дереве проза, на источнике правды выбор.

    «Принято» здесь закрыло бы вопрос, вариантов которого владелец не видел.
    """
    _write(env, CARD_OPTIONS)
    _commit(env)
    card = _write(env, CARD_INSTRUCTION)  # дерево отстало: карточку переписали прозой

    ok, why = od.ack_allowed(card, CARD_INSTRUCTION)

    assert ok is False
    assert "отставшей копии" in why

    prep, _ = _push(env, card, CARD_INSTRUCTION)
    assert prep.ack is False
    assert prep.keyboard is None
    assert "Принято" not in prep.text


def test_ack_is_refused_when_the_comparison_cannot_be_made(env, tmp_path):
    """Не измерено ⇒ молчим. «Сверить не смогли» и «выбора нет» ведут к разному."""
    outside = tmp_path / "no-git"
    outside.mkdir()
    card = outside / f"{CARD_ID}.md"
    card.write_text(CARD_INSTRUCTION, encoding="utf-8")

    ok, why = od.ack_allowed(card, CARD_INSTRUCTION)

    assert ok is False
    assert "не выполнилась" in why


def test_the_source_of_truth_is_origin_main(env):
    """Сверка идёт с `origin/main`; смена константы обязана быть замечена тестом."""
    assert od.ACK_REF == REF


def test_prepare_never_confirms_on_its_own(env):
    """`prepare` чистая и в git не ходит ⇒ по умолчанию подтверждения НЕТ.

    Иначе любой вызывающий, не знающий про сверку, тихо получил бы кнопку,
    закрывающую карточку по копии неизвестной свежести.
    """
    prep = od.prepare("Тревога", CARD_INSTRUCTION, CARD_ID, now=FIXED_NOW,
                      beacon_path=env["alive"])

    assert prep.ack is False
    assert prep.keyboard is None


# ── 3. обратные контроли: подтверждение не прячет настоящий выбор ────────────


def test_parsed_options_keep_variant_buttons(env):
    card = _write(env, CARD_OPTIONS)
    _commit(env)

    prep, _ = _push(env, card, CARD_OPTIONS)

    assert prep.ack is False
    labels = [row[0]["text"] for row in prep.keyboard["inline_keyboard"]]
    assert any(lbl.startswith("⭐ 1.") for lbl in labels)
    assert od.ACK_BUTTONS[od.ACK_ACCEPT] not in labels


def test_unparsed_options_get_no_ack_buttons(env):
    """Варианты в карточке ЕСТЬ, а разбор их не взял — «Принято» спрятало бы выбор."""
    assert od.has_unparsed_options(CARD_UNPARSED), "предусловие фикстуры"
    card = _write(env, CARD_UNPARSED)
    _commit(env)

    prep, _ = _push(env, card, CARD_UNPARSED)

    assert prep.ack is False
    assert prep.keyboard is None
    assert "Варианты в карточке есть" in prep.text


def test_a_lettered_choice_now_gets_its_own_buttons_and_never_an_ack(env):
    """Дыра, найденная ЧУЖИМ тестом: «(а)/(б)» внутри «Решения 1».

    **Тест намеренно усилен циклом #349 (инв. #16, запись в `docs/journal/2026-W34.md`).**
    Прежняя редакция требовала ``has_unparsed_options(CARD_LETTERED) is False`` как
    «предусловие: узкая молчит» и ``prep.keyboard is None``. Оба утверждения
    закрепляли слепоту разбора как свойство КАРТОЧКИ: варианты в ней написаны ровно
    по §2.4 (буквы + рекомендация), просто форма разбору не была известна, и живой
    `own-2026-08-19-sudba-voronki-chekapa-i-kanal-zayavok` (`high`) простоял из-за
    этого неотвечаемым с 19.08 по 22.08. Ослабления нет: старое требование «кнопка
    „Принято“ НЕ появляется» сохранено ДОСЛОВНО, а к нему добавлено более сильное —
    владелец получает НАСТОЯЩИЕ варианты карточки, а не молчание.
    """
    assert od.looks_like_a_choice(CARD_LETTERED) is True

    card = _write(env, CARD_LETTERED, name="own-lettered")
    _commit(env)
    prep, _ = _push(env, card, CARD_LETTERED)

    assert prep.ack is False, "подтверждение спрятало бы выбор — как и раньше"
    assert [o.num for o in prep.options] == ["а", "б"]
    labels = [b["text"] for row in prep.keyboard["inline_keyboard"] for b in row]
    assert any("Похоронить" in t for t in labels), labels
    assert any("Воскресить" in t for t in labels), labels
    assert od.ACK_BUTTONS[od.ACK_ACCEPT] not in labels


def test_the_same_letters_in_two_decisions_stay_buttonless_and_are_named_as_ours(env):
    """Граница fail-CLOSED не сдвинута: ДВА решения в одной карточке — не выбор одного.

    Метки повторяются («а»/«б» в каждом решении) ⇒ разбор отказывает целиком, иначе
    нажатие закрыло бы карточку, похоронив второй вопрос. Отказ верен — и обязан
    звучать как НАША неполадка, а не как «выбора не предлагали».
    """
    body = CARD_LETTERED + (
        "\n**Решение 2 — канал заявок.** Варианты:\n"
        "- **(а) Телеграм.** Заявки идут в чат.\n"
        "- **(б) Почта.** Заявки идут письмом.\n"
    )
    assert od.parse_options(body) == []
    assert od.has_unparsed_options(body) is True

    card = _write(env, body, name="own-two-decisions")
    _commit(env)
    prep, _ = _push(env, card, body)

    assert prep.ack is False
    assert prep.keyboard is None
    assert "Варианты в карточке есть" in prep.text


def test_the_five_cards_of_2026_08_08_would_get_buttons(env):
    """Критерий «сделано» исходной карточки — на форме тех самых пяти.

    Проверка в обе стороны: широкий сторож обязан не только молчать там, где выбор
    есть, но и СРАБАТЫВАТЬ там, ради чего написан. Сторож, который молчит всегда, —
    тоже украшение.
    """
    card = _write(env, CARD_FINDING_2026_08_08, name="own-08-08")
    _commit(env)

    prep, _ = _push(env, card, CARD_FINDING_2026_08_08)

    assert prep.ack is True
    labels = [row[0]["text"] for row in prep.keyboard["inline_keyboard"]]
    assert od.ACK_BUTTONS[od.ACK_ACCEPT] in labels


def test_multiselect_gets_no_ack_buttons(env):
    """«Можно взять несколько» одной кнопкой не выражается — молчим, как раньше."""
    assert od.allows_multiple(CARD_MULTI), "предусловие фикстуры"
    card = _write(env, CARD_MULTI)
    _commit(env)

    prep, _ = _push(env, card, CARD_MULTI)

    assert prep.ack is False
    assert prep.keyboard is None
    assert "НЕСКОЛЬКО пунктов" in prep.text


# ── 4. нажатие: карточка закрывается решением ВЛАДЕЛЬЦА ──────────────────────


def test_accept_records_the_owner_answer_and_leaves_the_card_open(env):
    """ИЗМЕНЁН НАМЕРЕННО циклом #350 (инв. #16), и проверка при этом УСИЛЕНА.

    Раньше здесь стояло ``assert "status: owner-done" in text`` — тест закреплял
    поведение, которое оказалось АВАРИЕЙ: 22.08 20:29Z нажатие «✅ Принято» сделало
    карточку-поручение терминальной в момент, когда её собственный критерий приёмки
    не выполнен (замер 20:47Z), и обещанной перепроверки делать стало некому.
    Ни один assert не снят: к прежним четырём (след ответа владельца + отсутствие
    выдуманного «варианта») добавлены ДВА новых — статус ровно ``owner-accepted``
    и явный запрет терминального. Разбор аварии — `test_owner_accepted_status.py`,
    обоснование — `docs/journal/2026-W34.md`, цикл #350.
    """
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)
    prep, live = _push(env, card, CARD_INSTRUCTION)

    res = od.record_choice(prep.pid, od.ACK_ACCEPT, OWNER, owner_chat_id=OWNER,
                           now=FIXED_NOW, state_path=env["state"])

    assert res["ok"] is True and res["kind"] == "ack"
    text = live.read_text(encoding="utf-8")
    assert "status: owner-accepted" in text
    assert "status: owner-done" not in text, (
        "«принято» — обещание совершить действие, а не действие: терминальный "
        "статус здесь теряет обещанную перепроверку (авария 22.08 20:29Z)")
    assert "owner_choice: ack" in text
    assert "owner_answer_kind: ack" in text
    assert "**Принято — беру в работу**" in text
    assert "Вариант ack" not in text, "выдуманный «вариант» в ответе — тот же обман"


def test_decline_is_a_real_answer_too(env):
    """Без «Не надо» кнопка «Принято» была бы не выбором, а подписью."""
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)
    prep, live = _push(env, card, CARD_INSTRUCTION)

    res = od.record_choice(prep.pid, od.ACK_DECLINE, OWNER, owner_chat_id=OWNER,
                           now=FIXED_NOW, state_path=env["state"])

    assert res["ok"] is True
    text = live.read_text(encoding="utf-8")
    assert "status: owner-done" in text
    assert "**Не надо — не делаем**" in text
    assert "делать не буду" in od.confirmation_text(res)


def test_confirmation_never_calls_it_a_variant(env):
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)
    prep, _ = _push(env, card, CARD_INSTRUCTION)

    res = od.record_choice(prep.pid, od.ACK_ACCEPT, OWNER, owner_chat_id=OWNER,
                           now=FIXED_NOW, state_path=env["state"])

    assert "вариант" not in od.confirmation_text(res).lower()
    assert "Принято — беру в работу" in od.confirmation_text(res)


def test_second_press_is_idempotent(env):
    """Владелец жмёт дважды из двух чатов — это одно решение, не два."""
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)
    prep, live = _push(env, card, CARD_INSTRUCTION)

    od.record_choice(prep.pid, od.ACK_ACCEPT, OWNER, owner_chat_id=OWNER,
                     now=FIXED_NOW, state_path=env["state"])
    res = od.record_choice(prep.pid, od.ACK_ACCEPT, OWNER, owner_chat_id=OWNER,
                           now=FIXED_NOW, state_path=env["state"])

    assert res["already"] is True
    assert live.read_text(encoding="utf-8").count("## Решение владельца") == 1


def test_push_journal_records_the_ack_mode(env):
    """Журнал различает три факта: варианты · режим подтверждения · уехали ли кнопки."""
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)
    prep, _ = _push(env, card, CARD_INSTRUCTION)

    rec = _rec(env, prep.pid)
    assert rec["options"] == [], "options — только вычитанное из карточки"
    assert rec["ack"] is True
    assert rec["buttons"] is True


# ── 5. инвариант #14 ─────────────────────────────────────────────────────────


def test_invariant_14_stranger_press_writes_nothing(env):
    """Не владелец — не решение. Карточка не меняется ни байтом."""
    card = _write(env, CARD_INSTRUCTION)
    _commit(env)
    prep, live = _push(env, card, CARD_INSTRUCTION)
    before = live.read_text(encoding="utf-8")

    res = od.record_choice(prep.pid, od.ACK_ACCEPT, STRANGER, owner_chat_id=OWNER,
                           now=FIXED_NOW, state_path=env["state"])

    assert res["ok"] is False and res["reason"] == "not_owner"
    assert live.read_text(encoding="utf-8") == before


def test_invariant_14_agent_still_cannot_set_owner_done(env):
    """`queue.set_status` отказывает агенту — подтверждение этого не ослабило."""
    from spa_core.owner_queue import queue as q

    card = _write(env, CARD_INSTRUCTION, name="own-inv14")
    with pytest.raises(Exception) as exc:
        q.set_status(card, "owner-done")
    assert "OwnerDone" in type(exc.value).__name__ or "owner-done" in str(exc.value)
    assert "status: needs-owner" in card.read_text(encoding="utf-8")


# ── 6. сторож называет ПРИЧИНУ, которая лечится тем, чем надо ────────────────


def test_reason_for_instruction_card_is_no_longer_form_of_the_question(env):
    """В проде 21.08 такая запись получала «no_options_in_card: лечится формой»."""
    from spa_core.telegram import buttonless_reason as br

    card = _write(env, CARD_INSTRUCTION, name="own-reason")
    _commit(env)

    reason = br.explain(card, now=FIXED_NOW, beacon_path=env["alive"], ref=REF)

    assert reason.code == br.CODE_HEAL_PENDING
    assert reason.code != br.CODE_NO_OPTIONS
    assert "(0)" not in reason.text, "«варианты разбираются (0)» — неправда о себе"


def test_reason_for_instruction_card_with_dead_bot_blames_the_bot(env):
    from spa_core.telegram import buttonless_reason as br

    card = _write(env, CARD_INSTRUCTION, name="own-reason-dead")
    _commit(env)

    reason = br.explain(card, now=FIXED_NOW, beacon_path=env["dead"], ref=REF)

    assert reason.code == br.CODE_HANDLER_UNAVAILABLE
    assert "поручение" in reason.text


def test_reason_still_names_a_stale_tree_first(env):
    """Обратный контроль: подтверждение НЕ съело сигнал «спрашивают по копии».

    Он и есть причина, по которой сверка обязательна: до неё этот сторож увидел бы
    поручение и объявил ремонт, а владелец получил бы кнопку не на тот вопрос.
    """
    from spa_core.telegram import buttonless_reason as br

    _write(env, CARD_OPTIONS, name="own-stale")
    _commit(env)
    card = _write(env, CARD_INSTRUCTION, name="own-stale")

    reason = br.explain(card, now=FIXED_NOW, beacon_path=env["alive"], ref=REF)

    assert reason.code == br.CODE_STALE_VS_ORIGIN


# ── 7. соседняя авария: досылка несла варианты, которых нет в журнале ────────


def test_heal_refreshes_options_so_the_button_leads_somewhere(env):
    """Живой сценарий `own-33` (21.08): варианты дописаны через 52 минуты.

    До починки: досылка рисует «1»/«2», нажатие отвечает «Такого варианта в этой
    карточке нет» — кнопка ведёт в никуда.
    """
    card = _write(env, CARD_INSTRUCTION, name="own-33-heal")
    _commit(env)
    prep, live = _push_dead(env, card, CARD_INSTRUCTION)
    assert prep.keyboard is None, "предусловие: кнопок не было"
    live.write_text(CARD_OPTIONS, encoding="utf-8")

    send = Sender()
    assert od.heal_buttonless(send, now=FIXED_NOW, state_path=env["state"],
                              beacon_path=env["alive"]) == [prep.pid]
    assert [o["num"] for o in _rec(env, prep.pid)["options"]] == ["1", "2"]

    res = od.record_choice(prep.pid, "1", OWNER, owner_chat_id=OWNER,
                           now=FIXED_NOW, state_path=env["state"])
    assert res["ok"] is True, "нажатие по досланной кнопке обязано записываться"
    assert "status: owner-done" in live.read_text(encoding="utf-8")


def test_heal_delivers_ack_buttons_to_an_instruction_card(env):
    """Три висящих 21.08 вопроса чинятся тем же штатным ремонтом, без нового кода."""
    card = _write(env, CARD_INSTRUCTION, name="own-heal-ack")
    _commit(env)
    prep, live = _push_dead(env, card, CARD_INSTRUCTION)

    send = Sender()
    assert od.heal_buttonless(send, now=FIXED_NOW, state_path=env["state"],
                              beacon_path=env["alive"]) == [prep.pid]
    labels = [row[0]["text"] for row in send.sent[0][1]["inline_keyboard"]]
    assert od.ACK_BUTTONS[od.ACK_ACCEPT] in labels
    assert _rec(env, prep.pid)["ack"] is True

    res = od.record_choice(prep.pid, od.ACK_ACCEPT, OWNER, owner_chat_id=OWNER,
                           now=FIXED_NOW, state_path=env["state"])
    assert res["ok"] is True
    # ИЗМЕНЕНО НАМЕРЕННО (#350, инв. #16) и УСИЛЕНО: досланная кнопка обязана вести
    # туда же, куда исходная, — а «туда же» с #350 означает НЕтерминальный
    # `owner-accepted`. Проверяется не только статус, но и след ответа владельца,
    # которого прежнее утверждение не касалось вовсе.
    text = live.read_text(encoding="utf-8")
    assert "status: owner-accepted" in text and "status: owner-done" not in text
    assert "owner_choice: ack" in text and "owner_answer_kind: ack" in text
